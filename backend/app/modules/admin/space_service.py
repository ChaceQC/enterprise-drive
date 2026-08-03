from __future__ import annotations

import unicodedata
from typing import NoReturn
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.pagination import decode_page_cursor, encode_page_cursor
from app.modules.admin.space_repository import AdminSpaceRecord, AdminSpaceRepository
from app.modules.admin.space_schemas import (
    AdminSpaceCreateRequest,
    AdminSpaceListResponse,
    AdminSpaceResponse,
    AdminSpaceUpdateRequest,
)
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.repository import FileRepository
from app.modules.permission.constants import SPACE_ROLE_OWNER
from app.modules.permission.events import emit_permission_changed
from app.modules.permission.repository import PermissionRepository
from app.modules.quota.repository import QuotaRepository
from app.modules.space.models import Space
from app.modules.space.repository import SpaceRepository


class AdminSpaceService:
    def __init__(
        self,
        *,
        repository: AdminSpaceRepository,
        space_repository: SpaceRepository,
        file_repository: FileRepository,
        permission_repository: PermissionRepository,
        quota_repository: QuotaRepository,
        audit_service: AuditService,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.space_repository = space_repository
        self.file_repository = file_repository
        self.permission_repository = permission_repository
        self.quota_repository = quota_repository
        self.audit_service = audit_service
        self.settings = settings

    async def list_spaces(
        self,
        *,
        current_user: User,
        is_active: bool | None,
        space_type: str | None,
        owner_id: UUID | None,
        query: str | None,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext | None,
    ) -> AdminSpaceListResponse:
        await self._require_admin(
            current_user=current_user,
            action="admin.spaces.queried",
            resource_id=None,
            audit_context=audit_context,
        )
        decoded_cursor = decode_page_cursor(self.settings, cursor)
        spaces = await self.repository.list_spaces(
            tenant_id=current_user.tenant_id,
            is_active=is_active,
            space_type=space_type,
            owner_id=owner_id,
            query=_normalize_query(query),
            cursor=decoded_cursor,
            limit=page_size + 1,
        )
        page = spaces[:page_size]
        next_cursor = None
        if len(spaces) > page_size and page:
            last = page[-1].space
            next_cursor = encode_page_cursor(
                self.settings,
                created_at=last.created_at,
                item_id=last.id,
            )
        await self._record(
            current_user=current_user,
            action="admin.spaces.queried",
            resource_id=None,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "is_active": is_active,
                "space_type": space_type,
                "owner_id": str(owner_id) if owner_id else None,
                "query": _normalize_query(query),
                "returned_count": len(page),
                "has_next": next_cursor is not None,
            },
        )
        await self.repository.commit()
        return AdminSpaceListResponse(
            items=[_space_response(item) for item in page],
            next_cursor=next_cursor,
        )

    async def get_space(
        self,
        *,
        current_user: User,
        space_id: UUID,
        audit_context: AuditContext | None,
    ) -> AdminSpaceResponse:
        await self._require_admin(
            current_user=current_user,
            action="admin.space.viewed",
            resource_id=space_id,
            audit_context=audit_context,
        )
        record = await self.repository.get_space_record(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
        )
        if record is None:
            await self._deny(
                current_user=current_user,
                action="admin.space.viewed",
                resource_id=space_id,
                code="ADMIN_SPACE_NOT_FOUND",
                message="空间不存在",
                status_code=404,
                audit_context=audit_context,
                metadata={"reason": "space_not_found"},
            )
        await self._record(
            current_user=current_user,
            action="admin.space.viewed",
            resource_id=space_id,
            result="allowed",
            audit_context=audit_context,
            metadata={},
        )
        await self.repository.commit()
        return _space_response(record)

    async def create_space(
        self,
        *,
        current_user: User,
        request: AdminSpaceCreateRequest,
        audit_context: AuditContext | None,
    ) -> AdminSpaceResponse:
        action = "admin.space.created"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_id=None,
            audit_context=audit_context,
        )
        owner_id = request.owner_id or current_user.id
        await self._get_active_owner_or_deny(
            current_user=current_user,
            owner_id=owner_id,
            action=action,
            audit_context=audit_context,
        )
        slug = request.slug.casefold()
        name = _normalize_space_name(request.name)
        try:
            space = await self.space_repository.create_space(
                tenant_id=current_user.tenant_id,
                owner_id=owner_id,
                slug=slug,
                name=name,
                space_type=request.space_type,
            )
            await self.file_repository.create_node(
                tenant_id=current_user.tenant_id,
                space_id=space.id,
                parent_id=None,
                owner_id=owner_id,
                node_type="folder",
                name="root",
                normalized_name="root",
            )
            await self.quota_repository.ensure_account(
                tenant_id=current_user.tenant_id,
                owner_type="space",
                owner_id=space.id,
                limit_bytes=(
                    request.limit_bytes
                    if request.limit_bytes is not None
                    else self.settings.default_space_quota_bytes
                ),
            )
            await self.permission_repository.create_space_member(
                tenant_id=current_user.tenant_id,
                space_id=space.id,
                user_id=owner_id,
                role=SPACE_ROLE_OWNER,
                created_by=current_user.id,
            )
            await self._record(
                current_user=current_user,
                action=action,
                resource_id=space.id,
                result="allowed",
                audit_context=audit_context,
                metadata={
                    "owner_id": str(owner_id),
                    "slug": slug,
                    "space_type": request.space_type,
                    "limit_bytes": request.limit_bytes,
                },
            )
            await self.repository.commit()
        except IntegrityError:
            await self.repository.rollback()
            await self._deny(
                current_user=current_user,
                action=action,
                resource_id=None,
                code="SPACE_SLUG_EXISTS",
                message="空间标识已存在",
                status_code=409,
                audit_context=audit_context,
                metadata={"slug": slug, "reason": "slug_conflict"},
            )
        return await self._load_response(current_user=current_user, space_id=space.id)

    async def update_space(
        self,
        *,
        current_user: User,
        space_id: UUID,
        request: AdminSpaceUpdateRequest,
        audit_context: AuditContext | None,
    ) -> AdminSpaceResponse:
        action = "admin.space.updated"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_id=space_id,
            audit_context=audit_context,
        )
        space = await self._get_space_for_update_or_deny(
            current_user=current_user,
            space_id=space_id,
            expected_version=request.expected_version,
            action=action,
            audit_context=audit_context,
        )
        changed_fields: list[str] = []
        permission_changed = False
        if request.owner_id is not None and request.owner_id != space.owner_id:
            await self._get_active_owner_or_deny(
                current_user=current_user,
                owner_id=request.owner_id,
                action=action,
                audit_context=audit_context,
            )
            root_node = await self.file_repository.get_root_node(
                tenant_id=current_user.tenant_id,
                space_id=space.id,
            )
            if root_node is None:
                await self._deny(
                    current_user=current_user,
                    action=action,
                    resource_id=space.id,
                    code="ADMIN_SPACE_ROOT_MISSING",
                    message="空间根目录不存在",
                    status_code=409,
                    audit_context=audit_context,
                    metadata={"reason": "root_node_missing"},
                )
            member = await self.permission_repository.get_space_member_for_update(
                tenant_id=current_user.tenant_id,
                space_id=space.id,
                user_id=request.owner_id,
            )
            if member is None:
                await self.permission_repository.create_space_member(
                    tenant_id=current_user.tenant_id,
                    space_id=space.id,
                    user_id=request.owner_id,
                    role=SPACE_ROLE_OWNER,
                    created_by=current_user.id,
                )
            elif member.role != SPACE_ROLE_OWNER:
                await self.permission_repository.update_space_member_role(
                    member=member,
                    role=SPACE_ROLE_OWNER,
                )
            space.owner_id = request.owner_id
            root_node.owner_id = request.owner_id
            changed_fields.append("owner_id")
            permission_changed = True
        if request.slug is not None and request.slug.casefold() != space.slug:
            space.slug = request.slug.casefold()
            changed_fields.append("slug")
        if request.name is not None:
            name = _normalize_space_name(request.name)
            if name != space.name:
                space.name = name
                changed_fields.append("name")
        for field_name, value in (
            ("space_type", request.space_type),
            ("is_active", request.is_active),
        ):
            if value is not None and getattr(space, field_name) != value:
                setattr(space, field_name, value)
                changed_fields.append(field_name)
        space.version += 1
        if permission_changed:
            permission_version = await self.permission_repository.bump_space_permission_version(
                tenant_id=current_user.tenant_id,
                space_id=space.id,
            )
            await emit_permission_changed(
                audit_service=self.audit_service,
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                scope="space",
                resource_id=space.id,
                permission_version=permission_version,
                reason="admin_space_owner_changed",
                affected_user_id=request.owner_id,
                metadata={"owner_id": str(request.owner_id)},
            )
        try:
            await self._record(
                current_user=current_user,
                action=action,
                resource_id=space.id,
                result="allowed",
                audit_context=audit_context,
                metadata={
                    "changed_fields": changed_fields,
                    "version": space.version,
                },
            )
            await self.repository.commit()
        except IntegrityError:
            await self.repository.rollback()
            await self._deny(
                current_user=current_user,
                action=action,
                resource_id=space_id,
                code="SPACE_SLUG_EXISTS",
                message="空间标识已存在",
                status_code=409,
                audit_context=audit_context,
                metadata={"reason": "slug_conflict"},
            )
        return await self._load_response(current_user=current_user, space_id=space_id)

    async def deactivate_space(
        self,
        *,
        current_user: User,
        space_id: UUID,
        expected_version: int,
        audit_context: AuditContext | None,
    ) -> AdminSpaceResponse:
        action = "admin.space.deactivated"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_id=space_id,
            audit_context=audit_context,
        )
        space = await self._get_space_for_update_or_deny(
            current_user=current_user,
            space_id=space_id,
            expected_version=expected_version,
            action=action,
            audit_context=audit_context,
        )
        space.is_active = False
        space.version += 1
        await self._record(
            current_user=current_user,
            action=action,
            resource_id=space.id,
            result="allowed",
            audit_context=audit_context,
            metadata={"version": space.version},
        )
        await self.repository.commit()
        return await self._load_response(current_user=current_user, space_id=space_id)

    async def _load_response(
        self,
        *,
        current_user: User,
        space_id: UUID,
    ) -> AdminSpaceResponse:
        record = await self.repository.get_space_record(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
        )
        if record is None:
            raise ApiError("ADMIN_SPACE_NOT_FOUND", "空间不存在", status_code=404)
        return _space_response(record)

    async def _get_space_for_update_or_deny(
        self,
        *,
        current_user: User,
        space_id: UUID,
        expected_version: int,
        action: str,
        audit_context: AuditContext | None,
    ) -> Space:
        space = await self.repository.get_space_for_update(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
        )
        if space is None:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_id=space_id,
                code="ADMIN_SPACE_NOT_FOUND",
                message="空间不存在",
                status_code=404,
                audit_context=audit_context,
                metadata={"reason": "space_not_found"},
            )
        if space.version != expected_version:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_id=space_id,
                code="ADMIN_SPACE_CHANGED",
                message="空间已被其他请求修改",
                status_code=409,
                audit_context=audit_context,
                metadata={
                    "expected_version": expected_version,
                    "current_version": space.version,
                    "reason": "stale_precondition",
                },
            )
        return space

    async def _get_active_owner_or_deny(
        self,
        *,
        current_user: User,
        owner_id: UUID,
        action: str,
        audit_context: AuditContext | None,
    ) -> User:
        owner = await self.repository.get_active_user(
            tenant_id=current_user.tenant_id,
            user_id=owner_id,
        )
        if owner is None:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_id=None,
                code="ADMIN_SPACE_OWNER_NOT_FOUND",
                message="空间所有者不存在或不可用",
                status_code=404,
                audit_context=audit_context,
                metadata={"owner_id": str(owner_id), "reason": "owner_not_found"},
            )
        return owner

    async def _require_admin(
        self,
        *,
        current_user: User,
        action: str,
        resource_id: UUID | None,
        audit_context: AuditContext | None,
    ) -> None:
        if current_user.is_super_admin:
            return
        await self._deny(
            current_user=current_user,
            action=action,
            resource_id=resource_id,
            code="ADMIN_REQUIRED",
            message="需要系统管理员权限",
            status_code=403,
            audit_context=audit_context,
            metadata={"reason": "super_admin_required"},
        )

    async def _deny(
        self,
        *,
        current_user: User,
        action: str,
        resource_id: UUID | None,
        code: str,
        message: str,
        status_code: int,
        audit_context: AuditContext | None,
        metadata: dict[str, object],
    ) -> NoReturn:
        await self._record(
            current_user=current_user,
            action=action,
            resource_id=resource_id,
            result="denied",
            audit_context=audit_context,
            metadata=metadata,
        )
        await self.repository.commit()
        raise ApiError(code, message, status_code=status_code)

    async def _record(
        self,
        *,
        current_user: User,
        action: str,
        resource_id: UUID | None,
        result: str,
        audit_context: AuditContext | None,
        metadata: dict[str, object],
    ) -> None:
        await self.audit_service.record(
            event=AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action=action,
                resource_type="space",
                resource_id=resource_id,
                result=result,
                risk_level="high",
                metadata=metadata,
            ),
            context=audit_context or AuditContext(),
        )


def _space_response(record: AdminSpaceRecord) -> AdminSpaceResponse:
    space = record.space
    return AdminSpaceResponse(
        id=space.id,
        tenant_id=space.tenant_id,
        owner_id=space.owner_id,
        slug=space.slug,
        name=space.name,
        space_type=space.space_type,  # type: ignore[arg-type]
        is_active=space.is_active,
        version=space.version,
        permission_version=space.permission_version,
        member_count=record.member_count,
        node_count=record.node_count,
        used_bytes=record.used_bytes,
        limit_bytes=record.limit_bytes,
        created_at=space.created_at,
        updated_at=space.updated_at,
    )


def _normalize_query(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    return normalized or None


def _normalize_space_name(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or any(ord(char) < 32 for char in normalized):
        raise ApiError("SPACE_NAME_INVALID", "空间名称不合法", status_code=422)
    return normalized
