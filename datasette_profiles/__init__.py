from datasette import hookimpl, Response


CREATE_SQL = """
create table if not exists profiles (
    id text primary key,
    name text,
    title text,
    profile_slug text,
    email text,
    bio text
);
-- profile_slug is unique if not null, sqlite
create unique index if not exists profiles_profile_slug
on profiles (profile_slug);

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


async def edit_profile(request, datasette):
    # Check if the user is logged in
    if not request.actor:
        raise Forbidden("You must be logged in to edit your profile")
    
    actor_id = request.actor["id"]
    internal_db = datasette.get_internal_database()
    
    # Get existing profile if it exists
    profile = (
        await internal_db.execute(
            """
            select 
                profiles.id, profiles.name, profiles.title, 
                profiles.profile_slug, profiles.email, profiles.bio,
                profiles_avatars.avatar_image is not null as has_avatar
            from 
                profiles
            left join
                profiles_avatars on profiles.id = profiles_avatars.profile_id
            where profiles.id = :id
            """,
            {"id": actor_id}
        )
    ).first()
    
    message = None
    
    # Handle form submission
    if request.method == "POST":
        post_vars = await request.post_vars()
        formdata = {
            "name": (post_vars.get("name") or "").strip(),
            "title": (post_vars.get("title") or "").strip(),
            "profile_slug": (post_vars.get("profile_slug") or "").strip() or None,
            "email": (post_vars.get("email") or "").strip(),
            "bio": (post_vars.get("bio") or "").strip(),
        }
        
        # Validate slug format if provided
        if formdata["profile_slug"] and not _is_valid_slug(formdata["profile_slug"]):
            datasette.add_message(
                request,
                "Profile slug must contain only letters, numbers, hyphens and underscores",
                datasette.ERROR
            )
            return Response.redirect(request.path)
        
        # Check for slug uniqueness if provided
        if formdata["profile_slug"]:
            existing = (
                await internal_db.execute(
                    """
                    select id from profiles 
                    where profile_slug = :slug and id != :id
                    """,
                    {"slug": formdata["profile_slug"], "id": actor_id}
                )
            ).first()
            
            if existing:
                datasette.add_message(
                    request,
                    f"Profile slug '{formdata['profile_slug']}' is already in use",
                    datasette.ERROR
                )
                return Response.redirect(request.path)
        
        # Handle avatar upload if present
        avatar_file = None
        if post_vars.get("avatar"):
            avatar_file = post_vars["avatar"]
            if hasattr(avatar_file, "file"):  # It's an UploadFile
                avatar_data = avatar_file.file.read()
                # Update or insert avatar
                await internal_db.execute_write(
                    """
                    insert into profiles_avatars (profile_id, avatar_image)
                    values (:profile_id, :avatar_image)
                    on conflict (profile_id) do update set
                    avatar_image = :avatar_image
                    """,
                    {
                        "profile_id": actor_id,
                        "avatar_image": avatar_data
                    }
                )
        
        # Handle avatar deletion if requested
        if post_vars.get("delete_avatar"):
            await internal_db.execute_write(
                "delete from profiles_avatars where profile_id = :profile_id",
                {"profile_id": actor_id}
            )
        
        # Insert or update profile
        if profile:
            await internal_db.execute_write(
                """
                update profiles set
                name = :name,
                title = :title,
                profile_slug = :profile_slug,
                email = :email,
                bio = :bio
                where id = :id
                """,
                {"id": actor_id, **formdata}
            )
            message = "Profile updated"
        else:
            await internal_db.execute_write(
                """
                insert into profiles
                (id, name, title, profile_slug, email, bio)
                values
                (:id, :name, :title, :profile_slug, :email, :bio)
                """,
                {"id": actor_id, **formdata}
            )
            message = "Profile created"
        
        # Add success message
        if message:
            datasette.add_message(request, message)
        
        # Redirect to reset the form and avoid resubmission
        return Response.redirect(request.path)
    
    # Prepare data for the template
    if profile:
        profile_data = dict(profile)
    else:
        # Default values for new profile
        profile_data = {
            "id": actor_id,
            "name": request.actor.get("display") or actor_id,
            "title": "",
            "profile_slug": "",
            "email": "",
            "bio": "",
            "has_avatar": False
        }
    
    # Get avatar URL if it exists
    avatar_url = None
    if profile_data.get("has_avatar"):
        avatar_url = f"/-/profile/avatar/{quote(actor_id)}"
    
    return Response.html(
        await datasette.render_template(
            "edit_profile.html",
            {
                "profile": profile_data,
                "avatar_url": avatar_url,
                "message": message
            },
            request=request,
        )
    )



async def view_profile(request):
    profile_id = request.url_vars["profile_id"]
    return Response.text(f"View profile {profile_id}")


@hookimpl
def register_routes():
    return [
        (r"^/-/edit-profile$", edit_profile),
        (r"^/~(?P<profile_id>[^/]+)$", view_profile),
        (r"^/-/profiles/avatar/(?P<id>.+)$", profile_avatar),
    ]


@hookimpl
def menu_links(datasette, actor):
    if actor:
        return [
            {
                # "href": f"/~{actor['id']}",
                "href": datasette.urls.path("/-/edit-profile"),
                "label": "Edit your profile",
            }
        ]


from datasette import Response, Forbidden
from datasette.utils.asgi import Request
import json
import base64
from urllib.parse import quote



def _is_valid_slug(slug):
    """
    Validate that a slug contains only allowed characters:
    letters, numbers, hyphens, and underscores
    """
    import re
    slug_pattern = re.compile(r"^[a-zA-Z0-9_-]+$")
    return bool(slug_pattern.match(slug))


async def profile_avatar(request, datasette):
    """View to serve avatar images"""
    profile_id = request.url_vars["id"]
    internal_db = datasette.get_internal_database()
    
    avatar = (
        await internal_db.execute(
            "select avatar_image from profiles_avatars where profile_id = :id",
            {"id": profile_id}
        )
    ).first()
    
    if not avatar or not avatar["avatar_image"]:
        raise NotFound("Avatar not found")
    
    return Response(
        avatar["avatar_image"],
        content_type="image/jpeg"  # You might want to store and detect actual mime type
    )