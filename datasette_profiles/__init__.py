import base64
import re
import binascii
from datasette import hookimpl, Response, Forbidden, NotFound
from datasette.utils.asgi import Request
from datasette.utils import make_slot_function
from urllib.parse import quote
from datasette.plugins import pm
from . import hookspecs

pm.add_hookspecs(hookspecs)


CREATE_SQL = """
create table if not exists profiles (
    id text primary key,
    name text,
    title text,
    email text,
    bio text
);

-- Keep these in a separate 1-1 table to avoid bloating main table
create table if not exists profiles_avatars (
    profile_id text primary key references profiles(id),
    avatar_image blob
);
"""


@hookimpl
def startup(datasette):
    async def inner():
        db = datasette.get_internal_database()
        await db.execute_write_script(CREATE_SQL)

    return inner


_track_event_seen_actor_ids = set()


@hookimpl
def permission_allowed(datasette, actor):
    actor_id = actor.get("id") if actor else None
    if not actor_id:
        return
    if actor_id in _track_event_seen_actor_ids:
        return

    async def inner():
        db = datasette.get_internal_database()
        # Insert into profiles if it doesn't exist
        await db.execute_write(
            """
            insert into profiles (id)
            values (:id)
            on conflict (id) do nothing
            """,
            {"id": str(actor_id)},
        )
        _track_event_seen_actor_ids.add(actor_id)

    return inner


# Regular expression to extract base64 data from Data URL
DATA_URL_RE = re.compile(r"data:image/(jpeg|png|gif|webp);base64,(.*)")


async def edit_profile(request: Request, datasette):
    actor = request.actor
    if not actor:
        raise Forbidden("You must be logged in to edit your profile")

    actor_id = actor["id"]
    internal_db = datasette.get_internal_database()

    # Get existing profile if it exists
    profile_row = (
        await internal_db.execute(
            """
            select 
                profiles.id, profiles.name, profiles.title, 
                profiles.email, profiles.bio,
                profiles_avatars.avatar_image is not null as has_avatar
            from 
                profiles
            left join
                profiles_avatars on profiles.id = profiles_avatars.profile_id
            where profiles.id = :id
            """,
            {"id": actor_id},
        )
    ).first()

    profile_exists = profile_row is not None

    message = None

    # Handle form submission
    if request.method == "POST":
        post_vars = await request.post_vars()
        formdata = {
            key: (post_vars.get(key) or "").strip()
            for key in ("name", "title", "email", "bio")
        }

        save_avatar_data = None
        avatar_data_url = post_vars.get("avatar_data_url")
        if avatar_data_url:
            data_url_error = None
            match = DATA_URL_RE.match(avatar_data_url)
            if not match:
                data_url_error = "Invalid data URL format"
            else:
                base64_data = match.group(1)
                try:
                    save_avatar_data = base64.b64decode(base64_data)
                except (binascii.Error, ValueError):
                    data_url_error = "Invalid base64 data"
            if data_url_error:
                datasette.add_message(
                    request, "Invalid avatar image data received", datasette.ERROR
                )
                return Response.redirect(request.path)

        # Handle avatar deletion if requested (and no new avatar provided)
        if post_vars.get("delete_avatar") and not save_avatar_data:
            await internal_db.execute_write(
                "delete from profiles_avatars where profile_id = :profile_id",
                {"profile_id": actor_id},
            )
        elif save_avatar_data:
            await internal_db.execute_write(
                """
                insert into profiles_avatars (profile_id, avatar_image)
                values (:profile_id, :avatar_image)
                on conflict (profile_id) do update set
                avatar_image = excluded.avatar_image
                """,
                {"profile_id": actor_id, "avatar_image": save_avatar_data},
            )

        # Insert or update profile
        if profile_exists:
            await internal_db.execute_write(
                """
                update profiles set
                    name = :name,
                    title = :title,
                    email = :email,
                    bio = :bio
                where
                    id = :id
                """,
                {"id": actor_id, **formdata},
            )
            message = "Profile updated"
        else:
            await internal_db.execute_write(
                """
                insert into profiles
                (id, name, title, email, bio)
                values
                (:id, :name, :title, :email, :bio)
                """,
                {"id": actor_id, **formdata},
            )
            message = "Profile created"

        # Add success message
        if message:
            datasette.add_message(request, message)

        # Redirect to reset the form and avoid resubmission
        return Response.redirect(request.path)

    # Prepare data for the template (GET request or initial load)
    if profile_exists:
        profile_data = dict(profile_row)
    else:
        # Default values for new profile
        profile_data = _default_profile_data(actor)

    # Get avatar URL if it exists
    avatar_url = None
    if profile_data.get("has_avatar"):
        avatar_url = _get_avatar_url(datasette, str(actor_id))

    return Response.html(
        await datasette.render_template(
            "edit_profile.html",
            {
                "profile": profile_data,
                "profile_url": datasette.urls.path(f"/~{quote(str(actor_id))}"),
                "avatar_url": avatar_url,
                "message": message,
            },
            request=request,
        )
    )


def _default_profile_data(actor):
    """Returns default profile data structure for a new profile."""
    return {
        "id": actor["id"],
        "name": actor.get("name") or actor.get("username") or actor["id"],
        "title": "",
        "email": actor.get("email") or "",
        "bio": "",
        "has_avatar": False,
    }


def _get_avatar_url(datasette, profile_id: str):
    """Generates the URL for a profile's avatar."""
    return datasette.urls.path(f"/-/profiles/avatar/{quote(profile_id)}")


async def view_profile(request: Request, datasette):
    profile_key = request.url_vars["profile_key"]
    internal_db = datasette.get_internal_database()

    # Try fetching by slug first, then by ID if it looks like an ID
    profile_row = (
        await internal_db.execute(
            """
            select 
                p.id, p.name, p.title, p.email, p.bio,
                pa.avatar_image is not null as has_avatar
            from profiles p
            left join profiles_avatars pa on p.id = pa.profile_id
            where p.id = :key
            """,
            {"key": profile_key},
        )
    ).first()

    if not profile_row:
        raise NotFound(f"Profile '{profile_key}' not found")

    profile_data = dict(profile_row)
    avatar_url = None
    if profile_data.get("has_avatar"):
        avatar_url = _get_avatar_url(datasette, str(profile_data["id"]))

    return Response.html(
        await datasette.render_template(
            "profile.html",
            {
                "profile": profile_data,
                "avatar_url": avatar_url,
                "profile_bio": profile_data["bio"],
                "bottom_profile": make_slot_function(
                    "bottom_profile", datasette, request, profile_actor=profile_data
                ),
            },
            request=request,
        )
    )


async def list_profiles(request: Request, datasette):
    internal_db = datasette.get_internal_database()

    profiles_rows = (
        await internal_db.execute(
            """
            select 
                p.id, p.name, p.title,
                pa.avatar_image is not null as has_avatar
            from profiles p
            left join profiles_avatars pa on p.id = pa.profile_id
            order by p.name, p.id
            """
        )
    ).rows

    profiles_list = []
    for row in profiles_rows:
        profile_dict = dict(row)
        # Determine the correct URL for the profile view
        profile_dict["view_url"] = datasette.urls.path(f"/~{quote(profile_dict['id'])}")
        if profile_dict["has_avatar"]:
            profile_dict["avatar_url"] = _get_avatar_url(
                datasette, str(profile_dict["id"])
            )
        else:
            profile_dict["avatar_url"] = None
        profiles_list.append(profile_dict)

    return Response.html(
        await datasette.render_template(
            "list_profiles.html", {"profiles": profiles_list}, request=request
        )
    )


@hookimpl
def register_routes():
    return [
        (r"^/-/edit-profile$", edit_profile),
        (r"^/-/profiles$", list_profiles),  # Listing page
        (r"^/~(?P<profile_key>[^/]+)$", view_profile),  # Use 'profile_key'
        (r"^/-/profiles/avatar/(?P<id>.+)$", profile_avatar),
    ]


@hookimpl
def menu_links(datasette, actor):
    links = []
    if actor:
        links.append(
            {
                "href": datasette.urls.path("/-/edit-profile"),
                "label": "Edit your profile",
            }
        )
    # Always show the profiles list link (or only if actor? Your choice)
    links.append(
        {
            "href": datasette.urls.path("/-/profiles"),
            "label": "View profiles",
        }
    )
    return links


# _is_valid_slug remains the same
def _is_valid_slug(slug):
    """
    Validate that a slug contains only allowed characters:
    letters, numbers, hyphens, and underscores
    """
    import re

    slug_pattern = re.compile(r"^[a-zA-Z0-9_-]+$")
    return bool(slug_pattern.match(slug))


async def profile_avatar(request: Request, datasette):
    """View to serve avatar images"""
    profile_id = request.url_vars["id"]
    internal_db = datasette.get_internal_database()

    avatar = (
        await internal_db.execute(
            "select avatar_image from profiles_avatars where profile_id = :id",
            {"id": profile_id},
        )
    ).first()

    if not avatar or not avatar["avatar_image"]:
        raise NotFound("Avatar not found")

    # Basic content type, could be enhanced by storing it alongside the blob
    content_type = "image/jpeg"
    if avatar["avatar_image"].startswith(b"\x89PNG"):
        content_type = "image/png"
    elif avatar["avatar_image"].startswith(b"GIF8"):
        content_type = "image/gif"
    elif (
        avatar["avatar_image"].startswith(b"RIFF")
        and avatar["avatar_image"][8:12] == b"WEBP"
    ):
        content_type = "image/webp"

    return Response(
        avatar["avatar_image"],
        content_type=content_type,
        headers={
            # Add caching headers - e.g., cache for 1 hour
            "Cache-Control": "public, max-age=3600"
        },
    )
