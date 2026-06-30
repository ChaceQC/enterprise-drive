from __future__ import annotations

SPACE_ROLE_OWNER = "owner"
SPACE_ROLE_ADMIN = "admin"
SPACE_ROLE_EDITOR = "editor"
SPACE_ROLE_VIEWER = "viewer"

SPACE_ROLES = frozenset(
    {
        SPACE_ROLE_OWNER,
        SPACE_ROLE_ADMIN,
        SPACE_ROLE_EDITOR,
        SPACE_ROLE_VIEWER,
    }
)
