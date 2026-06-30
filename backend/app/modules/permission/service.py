from __future__ import annotations

from uuid import UUID

from app.modules.permission.actions import (
    ACTION_DELETE,
    ACTION_DOWNLOAD,
    ACTION_LIST,
    ACTION_PREVIEW,
    ACTION_READ_META,
    ACTION_RESTORE,
    ACTION_SHARE,
    ACTION_UPDATE,
    ACTION_UPLOAD,
    PERMISSION_ACTIONS,
)
from app.modules.permission.constants import (
    SPACE_ROLE_ADMIN,
    SPACE_ROLE_EDITOR,
    SPACE_ROLE_OWNER,
    SPACE_ROLE_VIEWER,
)
from app.modules.permission.repository import PermissionRepository

SPACE_ROLE_ACTIONS = {
    SPACE_ROLE_OWNER: PERMISSION_ACTIONS,
    SPACE_ROLE_ADMIN: PERMISSION_ACTIONS,
    SPACE_ROLE_EDITOR: frozenset(
        {
            ACTION_DELETE,
            ACTION_DOWNLOAD,
            ACTION_LIST,
            ACTION_PREVIEW,
            ACTION_READ_META,
            ACTION_RESTORE,
            ACTION_SHARE,
            ACTION_UPDATE,
            ACTION_UPLOAD,
        }
    ),
    SPACE_ROLE_VIEWER: frozenset(
        {
            ACTION_DOWNLOAD,
            ACTION_LIST,
            ACTION_PREVIEW,
            ACTION_READ_META,
        }
    ),
}


class PermissionService:
    def __init__(self, *, repository: PermissionRepository) -> None:
        self.repository = repository

    async def can_access_space(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        space_id: UUID,
        action: str,
    ) -> bool:
        if action not in PERMISSION_ACTIONS:
            raise ValueError(f"unsupported permission action: {action}")
        member = await self.repository.get_space_member(
            tenant_id=tenant_id,
            space_id=space_id,
            user_id=user_id,
        )
        if member is None:
            return False
        return action in SPACE_ROLE_ACTIONS.get(member.role, frozenset())
