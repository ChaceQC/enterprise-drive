from __future__ import annotations

from uuid import UUID

from app.modules.org.service import OrgService
from app.modules.permission.actions import (
    ACTION_DELETE,
    ACTION_DOWNLOAD,
    ACTION_GRANT,
    ACTION_LIST,
    ACTION_MANAGE,
    ACTION_PREVIEW,
    ACTION_READ_META,
    ACTION_RESTORE,
    ACTION_SHARE,
    ACTION_UPDATE,
    ACTION_UPLOAD,
    PERMISSION_ACTIONS,
)
from app.modules.permission.constants import (
    ACL_EFFECT_ALLOW,
    ACL_EFFECT_DENY,
    ACL_SUBJECT_DEPARTMENT,
    ACL_SUBJECT_GROUP,
    ACL_SUBJECT_USER,
    SPACE_ROLE_ADMIN,
    SPACE_ROLE_EDITOR,
    SPACE_ROLE_OWNER,
    SPACE_ROLE_VIEWER,
)
from app.modules.permission.models import SpaceMember
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
    def __init__(
        self, *, repository: PermissionRepository, org_service: OrgService | None = None
    ) -> None:
        self.repository = repository
        self.org_service = org_service

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

    async def can_access_node(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        space_id: UUID,
        action: str,
        node_path_ids: list[UUID],
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

        role_allows = action in SPACE_ROLE_ACTIONS.get(member.role, frozenset())
        subjects = await self._list_user_subjects(tenant_id=tenant_id, user_id=user_id)
        acl_entries = await self.repository.list_acl_entries_for_subjects(
            tenant_id=tenant_id,
            subjects=subjects,
            node_ids=node_path_ids,
        )
        target_node_id = node_path_ids[-1] if node_path_ids else None
        matched_effects = {
            entry.effect
            for entry in acl_entries
            if action in entry.actions and (entry.node_id == target_node_id or entry.inherit)
        }
        if ACL_EFFECT_DENY in matched_effects:
            return False
        if ACL_EFFECT_ALLOW in matched_effects:
            return True
        return role_allows

    async def list_user_space_members(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
    ) -> list[SpaceMember]:
        return await self.repository.list_user_space_members(
            tenant_id=tenant_id,
            user_id=user_id,
        )

    async def batch_check_nodes(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        space_id: UUID,
        node_paths: dict[UUID, list[UUID]],
        actions: list[str],
    ) -> dict[UUID, dict[str, bool]]:
        unsupported_actions = [action for action in actions if action not in PERMISSION_ACTIONS]
        if unsupported_actions:
            raise ValueError(f"unsupported permission action: {unsupported_actions[0]}")
        default_result = {node_id: {action: False for action in actions} for node_id in node_paths}
        if not node_paths:
            return default_result

        member = await self.repository.get_space_member(
            tenant_id=tenant_id,
            space_id=space_id,
            user_id=user_id,
        )
        if member is None:
            return default_result

        role_actions = SPACE_ROLE_ACTIONS.get(member.role, frozenset())
        node_ids = sorted(
            {path_node_id for node_path in node_paths.values() for path_node_id in node_path},
            key=str,
        )
        subjects = await self._list_user_subjects(tenant_id=tenant_id, user_id=user_id)
        acl_entries = await self.repository.list_acl_entries_for_subjects(
            tenant_id=tenant_id,
            subjects=subjects,
            node_ids=node_ids,
        )

        result: dict[UUID, dict[str, bool]] = {}
        for node_id, node_path in node_paths.items():
            target_node_id = node_path[-1] if node_path else None
            node_acls = [
                entry
                for entry in acl_entries
                if entry.node_id in node_path and (entry.node_id == target_node_id or entry.inherit)
            ]
            node_permissions: dict[str, bool] = {}
            for action in actions:
                effects = {entry.effect for entry in node_acls if action in entry.actions}
                if ACL_EFFECT_DENY in effects:
                    node_permissions[action] = False
                elif ACL_EFFECT_ALLOW in effects:
                    node_permissions[action] = True
                else:
                    node_permissions[action] = action in role_actions
            result[node_id] = node_permissions
        return result

    async def _list_user_subjects(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
    ) -> dict[str, set[UUID]]:
        subjects = {ACL_SUBJECT_USER: {user_id}}
        if self.org_service is None:
            return subjects
        department_ids = await self.org_service.list_user_department_ids(
            tenant_id=tenant_id,
            user_id=user_id,
        )
        group_ids = await self.org_service.list_user_group_ids(
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if department_ids:
            subjects[ACL_SUBJECT_DEPARTMENT] = set(department_ids)
        if group_ids:
            subjects[ACL_SUBJECT_GROUP] = set(group_ids)
        return subjects


FILE_LIST_PERMISSION_ACTIONS = [
    ACTION_LIST,
    ACTION_READ_META,
    ACTION_PREVIEW,
    ACTION_DOWNLOAD,
    ACTION_UPLOAD,
    ACTION_UPDATE,
    ACTION_DELETE,
    ACTION_RESTORE,
    ACTION_SHARE,
    ACTION_GRANT,
    ACTION_MANAGE,
]
