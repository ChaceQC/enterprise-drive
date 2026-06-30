from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.api.errors import ApiError
from app.modules.audit.schemas import AuditContext
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.auth.service import AuthService
from app.modules.file.acl_audit import record_acl_event
from app.modules.file.models import Node
from app.modules.file.repository import FileRepository
from app.modules.permission.actions import ACTION_GRANT
from app.modules.permission.events import emit_permission_changed
from app.modules.permission.repository import PermissionRepository
from app.modules.permission.schemas import (
    AclEntryListResponse,
    AclEntryResponse,
    RemoveAclEntryResponse,
)
from app.modules.permission.service import PermissionService
from app.modules.space.repository import SpaceRepository


class FileAclService:
    def __init__(
        self,
        *,
        file_repository: FileRepository,
        permission_repository: PermissionRepository,
        permission_service: PermissionService,
        space_repository: SpaceRepository,
        auth_service: AuthService,
        audit_service: AuditService | None = None,
    ) -> None:
        self.file_repository = file_repository
        self.permission_repository = permission_repository
        self.permission_service = permission_service
        self.space_repository = space_repository
        self.auth_service = auth_service
        self.audit_service = audit_service

    async def list_acl_entries(
        self,
        *,
        current_user: User,
        node_id: UUID,
    ) -> AclEntryListResponse:
        node = await self._get_grantable_node(current_user=current_user, node_id=node_id)
        entries = await self.permission_repository.list_node_acl_entries(
            tenant_id=current_user.tenant_id,
            node_id=node.id,
        )
        return AclEntryListResponse(
            items=[AclEntryResponse.model_validate(entry) for entry in entries]
        )

    async def create_acl_entry(
        self,
        *,
        current_user: User,
        node_id: UUID,
        subject_user_id: UUID,
        effect: str,
        actions: list[str],
        inherit: bool,
        audit_context: AuditContext | None = None,
    ) -> AclEntryResponse:
        node = await self._get_grantable_node(current_user=current_user, node_id=node_id)
        await self._ensure_active_target_user(
            current_user=current_user,
            subject_user_id=subject_user_id,
        )
        try:
            entry = await self.permission_repository.create_acl_entry(
                tenant_id=current_user.tenant_id,
                node_id=node.id,
                subject_id=subject_user_id,
                effect=effect,
                actions=actions,
                inherit=inherit,
                created_by=current_user.id,
            )
            permission_version = await self.file_repository.bump_node_permission_version(
                tenant_id=current_user.tenant_id,
                node_id=node.id,
            )
            await record_acl_event(
                audit_service=self.audit_service,
                current_user=current_user,
                node=node,
                action="permission.node_acl.created",
                audit_context=audit_context,
                metadata={
                    "entry_id": str(entry.id),
                    "subject_user_id": str(subject_user_id),
                    "effect": effect,
                    "actions": actions,
                    "inherit": inherit,
                },
            )
            await emit_permission_changed(
                audit_service=self.audit_service,
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                scope="node",
                resource_id=node.id,
                permission_version=permission_version,
                reason="node_acl_created",
                affected_user_id=subject_user_id,
                metadata={
                    "space_id": str(node.space_id),
                    "entry_id": str(entry.id),
                    "effect": effect,
                    "actions": actions,
                    "inherit": inherit,
                },
            )
            await self.file_repository.commit()
        except IntegrityError as exc:
            await self.file_repository.rollback()
            raise ApiError("ACL_ENTRY_EXISTS", "ACL 规则已存在", status_code=409) from exc

        return AclEntryResponse.model_validate(entry)

    async def update_acl_entry(
        self,
        *,
        current_user: User,
        node_id: UUID,
        entry_id: UUID,
        effect: str,
        actions: list[str],
        inherit: bool,
        audit_context: AuditContext | None = None,
    ) -> AclEntryResponse:
        node = await self._get_grantable_node(current_user=current_user, node_id=node_id)
        entry = await self.permission_repository.get_acl_entry_for_update(
            tenant_id=current_user.tenant_id,
            node_id=node.id,
            entry_id=entry_id,
        )
        if entry is None:
            raise ApiError("ACL_ENTRY_NOT_FOUND", "ACL 规则不存在", status_code=404)

        old_effect = entry.effect
        old_actions = list(entry.actions)
        old_inherit = entry.inherit
        entry = await self.permission_repository.update_acl_entry(
            entry=entry,
            effect=effect,
            actions=actions,
            inherit=inherit,
        )
        permission_version = await self.file_repository.bump_node_permission_version(
            tenant_id=current_user.tenant_id,
            node_id=node.id,
        )
        await record_acl_event(
            audit_service=self.audit_service,
            current_user=current_user,
            node=node,
            action="permission.node_acl.updated",
            audit_context=audit_context,
            metadata={
                "entry_id": str(entry.id),
                "old_effect": old_effect,
                "new_effect": effect,
                "old_actions": old_actions,
                "new_actions": actions,
                "old_inherit": old_inherit,
                "new_inherit": inherit,
            },
        )
        await emit_permission_changed(
            audit_service=self.audit_service,
            tenant_id=current_user.tenant_id,
            actor_id=current_user.id,
            scope="node",
            resource_id=node.id,
            permission_version=permission_version,
            reason="node_acl_updated",
            affected_user_id=entry.subject_id,
            metadata={
                "space_id": str(node.space_id),
                "entry_id": str(entry.id),
                "old_effect": old_effect,
                "new_effect": effect,
                "old_actions": old_actions,
                "new_actions": actions,
                "old_inherit": old_inherit,
                "new_inherit": inherit,
            },
        )
        await self.file_repository.commit()
        return AclEntryResponse.model_validate(entry)

    async def remove_acl_entry(
        self,
        *,
        current_user: User,
        node_id: UUID,
        entry_id: UUID,
        audit_context: AuditContext | None = None,
    ) -> RemoveAclEntryResponse:
        node = await self._get_grantable_node(current_user=current_user, node_id=node_id)
        entry = await self.permission_repository.get_acl_entry(
            tenant_id=current_user.tenant_id,
            node_id=node.id,
            entry_id=entry_id,
        )
        if entry is None:
            raise ApiError("ACL_ENTRY_NOT_FOUND", "ACL 规则不存在", status_code=404)
        await self.permission_repository.delete_acl_entry(
            tenant_id=current_user.tenant_id,
            node_id=node.id,
            entry_id=entry_id,
        )
        permission_version = await self.file_repository.bump_node_permission_version(
            tenant_id=current_user.tenant_id,
            node_id=node.id,
        )
        await record_acl_event(
            audit_service=self.audit_service,
            current_user=current_user,
            node=node,
            action="permission.node_acl.removed",
            audit_context=audit_context,
            metadata={
                "entry_id": str(entry.id),
                "subject_user_id": str(entry.subject_id),
                "effect": entry.effect,
                "actions": list(entry.actions),
                "inherit": entry.inherit,
            },
        )
        await emit_permission_changed(
            audit_service=self.audit_service,
            tenant_id=current_user.tenant_id,
            actor_id=current_user.id,
            scope="node",
            resource_id=node.id,
            permission_version=permission_version,
            reason="node_acl_removed",
            affected_user_id=entry.subject_id,
            metadata={
                "space_id": str(node.space_id),
                "entry_id": str(entry.id),
                "effect": entry.effect,
                "actions": list(entry.actions),
                "inherit": entry.inherit,
            },
        )
        await self.file_repository.commit()
        return RemoveAclEntryResponse(entry_id=entry_id, removed=True)

    async def _get_grantable_node(self, *, current_user: User, node_id: UUID) -> Node:
        node = await self.file_repository.get_node_by_id(
            tenant_id=current_user.tenant_id,
            node_id=node_id,
        )
        if node is None:
            raise ApiError("NODE_NOT_FOUND", "节点不存在或无权访问", status_code=404)
        space = await self.space_repository.get_active_space(
            tenant_id=current_user.tenant_id,
            space_id=node.space_id,
        )
        node_path_ids = await self.file_repository.get_node_path_ids(
            tenant_id=current_user.tenant_id,
            space_id=node.space_id,
            node_id=node.id,
        )
        allowed = (
            space is not None
            and node_path_ids is not None
            and await self.permission_service.can_access_node(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                space_id=node.space_id,
                action=ACTION_GRANT,
                node_path_ids=node_path_ids,
            )
        )
        if not allowed:
            raise ApiError("NODE_NOT_FOUND", "节点不存在或无权访问", status_code=404)
        return node

    async def _ensure_active_target_user(
        self,
        *,
        current_user: User,
        subject_user_id: UUID,
    ) -> None:
        user = await self.auth_service.get_active_user(
            tenant_id=current_user.tenant_id,
            user_id=subject_user_id,
        )
        if user is None:
            raise ApiError("USER_NOT_FOUND", "用户不存在或不可用", status_code=404)
