# schemas/user_schemas.py
"""Payloads for the team directory shown as an avatar stack on the dashboard.

Kept separate from ``auth_schemas`` because the directory is a read-only,
self-contained view: no password/hash fields and no write payloads.
"""

from pydantic import BaseModel, ConfigDict

#: How many circles the dashboard asks for by default (one page of avatars).
DEFAULT_TEAM_LIMIT = 8
#: Hard ceiling so a caller cannot presign an unbounded number of photos.
MAX_TEAM_LIMIT = 24


class TeamMemberSchema(BaseModel):
    """One person in the avatar stack (photo is optional)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    firstname: str = ""
    lastname: str = ""
    full_name: str = ""
    position: str = ""
    status_text: str = ""
    image_url: str = ""
    has_photo: bool = False
    #: True for the signed-in user, so the client can mark their own circle.
    is_self: bool = False


class TeamDirectorySchema(BaseModel):
    #: Number of users in total (the client renders "+N" for the rest).
    total: int = 0
    #: Users that actually have a profile photo (informational).
    with_photo: int = 0
    items: list[TeamMemberSchema] = []
