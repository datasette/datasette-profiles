from pluggy import HookspecMarker

hookspec = HookspecMarker("datasette")


@hookspec
def bottom_profile(datasette, request, profile_actor):
    "HTML to include at the bottom of the user profile page."
