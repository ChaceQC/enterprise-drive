from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.api.errors import ApiError
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.auth.service import AuthService
from app.modules.permission.actions import ACTION_GRANT, ACTION_MANAGE
from app.modules.permission.constants import SPACE_ROLE_OWNER
from app.modules.permission.models import SpaceMember
from app.modules.permission.repository import PermissionRepository
from app.modules.permission.schemas import (
    RemoveSpaceMemberResponse,
    SpaceMemberListResponse,
    SpaceMemberResponse,
)
from app.modules.permission.service import PermissionService
from app.modules.space.models import Space
from app.modules.space.repository import SpaceRepository


class SpaceMemberService:
    def __init__(
        self,
        *,
        repository: PermissionRepository,
        permission_service: PermissionService,
        space_repository: SpaceRepository,
        auth_service: AuthService,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.permission_service = permission_service
        self.space_repository = space_repository
        self.auth_service = auth_service
        self.audit_service = audit_service

    async def list_members(
        self,
        *,
        current_user: User,
        space_id: UUID,
        audit_context: AuditContext | None = None,
    ) -> SpaceMemberListResponse:
        await self._get_manageable_space(
            current_user=current_user,
            space_id=space_id,
            action=ACTION_MANAGE,
            audit_context=audit_context,
            audit_action="permission.space_member.list.denied",
        )
        members = await self.repository.list_space_members(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
        )
        return SpaceMemberListResponse(
            items=[SpaceMemberResponse.model_validate(member) for member in members]
        )

    async def add_member(
        self,
        *,
        current_user: User,
        space_id: UUID,
        user_id: UUID,
        role: str,
        audit_context: AuditContext | None = None,
    ) -> SpaceMemberResponse:
        await self._get_manageable_space(
            current_user=current_user,
            space_id=space_id,
            action=ACTION_GRANT,
            audit_context=audit_context,
            audit_action="permission.space_member.add.denied",
            target_user_id=user_id,
        )
        await self._ensure_active_target_user(current_user=current_user, user_id=user_id)
        existing_member = await self.repository.get_space_member(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
            user_id=user_id,
        )
        if existing_member is not None:
            raise ApiError("SPACE_MEMBER_EXISTS", "空间成员已存在", status_code=409)

        try:
            member = await self.repository.create_space_member(
                tenant_id=current_user.tenant_id,
                space_id=space_id,
                user_id=user_id,
                role=role,
                created_by=current_user.id,
            )
            await self.repository.bump_space_permission_version(
                tenant_id=current_user.tenant_id,
                space_id=space_id,
            )
            await self._record_member_event(
                current_user=current_user,
                space_id=space_id,
                target_user_id=user_id,
                action="permission.space_member.added",
                audit_context=audit_context,
                metadata={"role": role},
            )
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise ApiError("SPACE_MEMBER_EXISTS", "空间成员已存在", status_code=409) from exc

        return SpaceMemberResponse.model_validate(member)

    async def update_member(
        self,
        *,
        current_user: User,
        space_id: UUID,
        user_id: UUID,
        role: str,
        audit_context: AuditContext | None = None,
    ) -> SpaceMemberResponse:
        await self._get_manageable_space(
            current_user=current_user,
            space_id=space_id,
            action=ACTION_GRANT,
            audit_context=audit_context,
            audit_action="permission.space_member.update.denied",
            target_user_id=user_id,
        )
        member = await self._get_member_for_change(
            current_user=current_user,
            space_id=space_id,
            user_id=user_id,
        )
        if member.role == SPACE_ROLE_OWNER and role != SPACE_ROLE_OWNER:
            await self._ensure_not_last_owner(current_user=current_user, space_id=space_id)

        old_role = member.role
        member = await self.repository.update_space_member_role(member=member, role=role)
        await self.repository.bump_space_permission_version(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
        )
        await self._record_member_event(
            current_user=current_user,
            space_id=space_id,
            target_user_id=user_id,
            action="permission.space_member.updated",
            audit_context=audit_context,
            metadata={"old_role": old_role, "new_role": role},
        )
        await self.repository.commit()
        return SpaceMemberResponse.model_validate(member)

    async def remove_member(
        self,
        *,
        current_user: User,
        space_id: UUID,
        user_id: UUID,
        audit_context: AuditContext | None = None,
    ) -> RemoveSpaceMemberResponse:
        await self._get_manageable_space(
            current_user=current_user,
            space_id=space_id,
            action=ACTION_GRANT,
            audit_context=audit_context,
            audit_action="permission.space_member.remove.denied",
            target_user_id=user_id,
        )
        member = await self._get_member_for_change(
            current_user=current_user,
            space_id=space_id,
            user_id=user_id,
        )
        if member.role == SPACE_ROLE_OWNER:
            await self._ensure_not_last_owner(current_user=current_user, space_id=space_id)

        await self.repository.delete_space_member(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
            user_id=user_id,
        )
        await self.repository.bump_space_permission_version(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
        )
        await self._record_member_event(
            current_user=current_user,
            space_id=space_id,
            target_user_id=user_id,
            action="permission.space_member.removed",
            audit_context=audit_context,
            metadata={"old_role": member.role},
        )
        await self.repository.commit()
        return RemoveSpaceMemberResponse(user_id=user_id, removed=True)

    async def _get_manageable_space(
        self,
        *,
        current_user: User,
        space_id: UUID,
        action: str,
        audit_context: AuditContext | None,
        audit_action: str,
        target_user_id: UUID | None = None,
    ) -> Space:
        space = await self.space_repository.get_active_space(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
        )
        allowed = space is not None and await self.permission_service.can_access_space(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            space_id=space_id,
            action=action,
        )
        if allowed and space is not None:
            return space

        await self._record_member_event(
            current_user=current_user,
            space_id=space_id,
            target_user_id=target_user_id,
            action=audit_action,
            audit_context=audit_context,
            result="denied",
            metadata={"required_action": action},
        )
        await self.repository.commit()
        raise ApiError("SPACE_NOT_FOUND", "空间不存在或无权访问", status_code=404)

    async def _ensure_active_target_user(
        self,
        *,
        current_user: User,
        user_id: UUID,
    ) -> User:
        user = await self.auth_service.get_active_user(
            tenant_id=current_user.tenant_id,
            user_id=user_id,
        )
        if user is None:
            raise ApiError("USER_NOT_FOUND", "用户不存在或不可用", status_code=404)
        return user

    async def _get_member_for_change(
        self,
        *,
        current_user: User,
        space_id: UUID,
        user_id: UUID,
    ) -> SpaceMember:
        member = await self.repository.get_space_member_for_update(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
            user_id=user_id,
        )
        if member is None:
            raise ApiError("SPACE_MEMBER_NOT_FOUND", "空间成员不存在", status_code=404)
        return member

    async def _ensure_not_last_owner(
        self,
        *,
        current_user: User,
        space_id: UUID,
    ) -> None:
        owner_count = await self.repository.count_space_owners(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
        )
        if owner_count <= 1:
            raise ApiError("LAST_SPACE_OWNER", "不能移除或降级最后一个空间所有者", status_code=409)

    async def _record_member_event(
        self,
        *,
        current_user: User,
        space_id: UUID,
        target_user_id: UUID | None,
        action: str,
        audit_context: AuditContext | None,
        result: str = "allowed",
        metadata: dict[str, object] | None = None,
    ) -> None:
        if self.audit_service is None:
            return
        event_metadata = dict(metadata or {})
        if target_user_id is not None:
            event_metadata["target_user_id"] = str(target_user_id)
        await self.audit_service.record(
            event=AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action=action,
                resource_type="space",
                resource_id=space_id,
                result=result,
                risk_level="high",
                metadata=event_metadata,
            ),
            context=audit_context or AuditContext(),
        )
