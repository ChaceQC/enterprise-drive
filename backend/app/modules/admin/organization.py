from __future__ import annotations

import unicodedata
from typing import NoReturn, cast
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.metrics import record_auth_security_event
from app.core.pagination import decode_page_cursor, encode_page_cursor
from app.core.security import ensure_utc, hash_password, utc_now
from app.modules.admin.organization_repository import AdminOrganizationRepository
from app.modules.admin.organization_schemas import (
    AdminDepartmentCreateRequest,
    AdminDepartmentListResponse,
    AdminDepartmentResponse,
    AdminDepartmentUpdateRequest,
    AdminGroupCreateRequest,
    AdminGroupListResponse,
    AdminGroupResponse,
    AdminGroupUpdateRequest,
    AdminOrganizationMemberListResponse,
    AdminOrganizationMemberRemovalResponse,
    AdminOrganizationMemberResponse,
    AdminUserCreateRequest,
    AdminUserListResponse,
    AdminUserPasswordResetRequest,
    AdminUserResponse,
    AdminUserUnlockRequest,
    AdminUserUpdateRequest,
    OrganizationStatus,
)
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.auth.service import ensure_password_policy
from app.modules.org.models import Department, DepartmentMember, UserGroup, UserGroupMember
from app.modules.share.events import emit_share_recipients_rebuild_requested

_MAX_DEPARTMENT_PATH_LENGTH = 2048


class AdminOrganizationService:
    def __init__(
        self,
        *,
        repository: AdminOrganizationRepository,
        audit_service: AuditService,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.settings = settings

    async def list_users(
        self,
        *,
        current_user: User,
        is_active: bool | None,
        is_super_admin: bool | None,
        query: str | None,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext | None,
    ) -> AdminUserListResponse:
        action = "admin.users.queried"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="user",
            resource_id=None,
            audit_context=audit_context,
        )
        users = await self.repository.list_users(
            tenant_id=current_user.tenant_id,
            is_active=is_active,
            is_super_admin=is_super_admin,
            query=_normalize_query(query),
            cursor=decode_page_cursor(self.settings, cursor),
            limit=page_size + 1,
        )
        page = users[:page_size]
        next_cursor = _next_cursor(self.settings, users, page_size)
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="user",
            resource_id=None,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "is_active": is_active,
                "is_super_admin": is_super_admin,
                "query": _normalize_query(query),
                "returned_count": len(page),
                "has_next": next_cursor is not None,
            },
        )
        await self.repository.commit()
        return AdminUserListResponse(
            items=[_user_response(user) for user in page],
            next_cursor=next_cursor,
        )

    async def get_user(
        self,
        *,
        current_user: User,
        user_id: UUID,
        audit_context: AuditContext | None,
    ) -> AdminUserResponse:
        action = "admin.user.viewed"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="user",
            resource_id=user_id,
            audit_context=audit_context,
        )
        user = await self.repository.get_user(
            tenant_id=current_user.tenant_id,
            user_id=user_id,
        )
        if user is None:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="user",
                resource_id=user_id,
                code="ADMIN_USER_NOT_FOUND",
                message="用户不存在",
                status_code=404,
                audit_context=audit_context,
                metadata={"reason": "user_not_found"},
            )
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="user",
            resource_id=user.id,
            result="allowed",
            audit_context=audit_context,
            metadata={"target_username": user.username},
        )
        await self.repository.commit()
        return _user_response(user)

    async def create_user(
        self,
        *,
        current_user: User,
        request: AdminUserCreateRequest,
        audit_context: AuditContext | None,
    ) -> AdminUserResponse:
        action = "admin.user.created"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="user",
            resource_id=None,
            audit_context=audit_context,
        )
        username = request.username.strip().casefold()
        email = _normalize_email(request.email)
        display_name = _normalize_display_name(request.display_name)
        ensure_password_policy(settings=self.settings, password=request.password)
        try:
            user = await self.repository.create_user(
                tenant_id=current_user.tenant_id,
                username=username,
                email=email,
                display_name=display_name,
                password_hash=hash_password(request.password),
                is_active=request.is_active,
                is_super_admin=request.is_super_admin,
                must_change_password=request.must_change_password,
            )
            await self._record(
                current_user=current_user,
                action=action,
                resource_type="user",
                resource_id=user.id,
                result="allowed",
                audit_context=audit_context,
                metadata=_user_audit_metadata(user),
            )
            await self.repository.commit()
        except IntegrityError:
            await self._rollback_and_refresh_actor(current_user)
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="user",
                resource_id=None,
                code="ADMIN_USER_IDENTITY_EXISTS",
                message="用户名或邮箱已存在",
                status_code=409,
                audit_context=audit_context,
                metadata={
                    "username": username,
                    "email": email,
                    "reason": "identity_conflict",
                },
            )
        return _user_response(user)

    async def update_user(
        self,
        *,
        current_user: User,
        user_id: UUID,
        request: AdminUserUpdateRequest,
        audit_context: AuditContext | None,
    ) -> AdminUserResponse:
        action = "admin.user.updated"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="user",
            resource_id=user_id,
            audit_context=audit_context,
        )
        user = await self._get_user_for_update_or_deny(
            current_user=current_user,
            user_id=user_id,
            action=action,
            audit_context=audit_context,
        )
        await self._ensure_version(
            current_user=current_user,
            action=action,
            resource_type="user",
            resource_id=user.id,
            expected_version=request.expected_version,
            current_version=user.version,
            changed_code="ADMIN_USER_CHANGED",
            changed_message="用户已被其他请求修改",
            audit_context=audit_context,
        )

        next_active = request.is_active if request.is_active is not None else user.is_active
        next_super_admin = (
            request.is_super_admin if request.is_super_admin is not None else user.is_super_admin
        )
        await self._ensure_super_admin_survives(
            current_user=current_user,
            target_user=user,
            next_active=next_active,
            next_super_admin=next_super_admin,
            action=action,
            audit_context=audit_context,
        )

        changed_fields: list[str] = []
        if request.username is not None:
            username = request.username.strip().casefold()
            if username != user.username:
                user.username = username
                changed_fields.append("username")
        if request.clear_email:
            if user.email is not None:
                user.email = None
                changed_fields.append("email")
        elif request.email is not None:
            email = _normalize_email(request.email)
            if email != user.email:
                user.email = email
                changed_fields.append("email")
        if request.display_name is not None:
            display_name = _normalize_display_name(request.display_name)
            if display_name != user.display_name:
                user.display_name = display_name
                changed_fields.append("display_name")
        for field_name, value in (
            ("is_active", request.is_active),
            ("is_super_admin", request.is_super_admin),
            ("must_change_password", request.must_change_password),
        ):
            if value is not None and getattr(user, field_name) != value:
                setattr(user, field_name, value)
                changed_fields.append(field_name)

        active_changed = "is_active" in changed_fields
        if changed_fields:
            user.version += 1
            user.updated_at = utc_now()
            if active_changed and not user.is_active:
                await self.repository.revoke_user_sessions(
                    tenant_id=current_user.tenant_id,
                    user_id=user.id,
                    reason="admin_user_deactivated",
                )
            if active_changed:
                await self._emit_tenant_permission_changed(
                    current_user=current_user,
                    reason="admin_user_status_changed",
                    affected_user_id=user.id,
                    metadata={
                        "user_id": str(user.id),
                        "is_active": user.is_active,
                    },
                )

        try:
            await self._record(
                current_user=current_user,
                action=action,
                resource_type="user",
                resource_id=user.id,
                result="allowed",
                audit_context=audit_context,
                metadata={
                    **_user_audit_metadata(user),
                    "changed_fields": changed_fields,
                },
            )
            await self.repository.commit()
        except IntegrityError:
            await self._rollback_and_refresh_actor(current_user)
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="user",
                resource_id=user_id,
                code="ADMIN_USER_IDENTITY_EXISTS",
                message="用户名或邮箱已存在",
                status_code=409,
                audit_context=audit_context,
                metadata={"reason": "identity_conflict"},
            )
        return _user_response(user)

    async def deactivate_user(
        self,
        *,
        current_user: User,
        user_id: UUID,
        expected_version: int,
        audit_context: AuditContext | None,
    ) -> AdminUserResponse:
        action = "admin.user.deactivated"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="user",
            resource_id=user_id,
            audit_context=audit_context,
        )
        user = await self._get_user_for_update_or_deny(
            current_user=current_user,
            user_id=user_id,
            action=action,
            audit_context=audit_context,
        )
        await self._ensure_version(
            current_user=current_user,
            action=action,
            resource_type="user",
            resource_id=user.id,
            expected_version=expected_version,
            current_version=user.version,
            changed_code="ADMIN_USER_CHANGED",
            changed_message="用户已被其他请求修改",
            audit_context=audit_context,
        )
        await self._ensure_super_admin_survives(
            current_user=current_user,
            target_user=user,
            next_active=False,
            next_super_admin=user.is_super_admin,
            action=action,
            audit_context=audit_context,
        )
        if user.is_active:
            user.is_active = False
            user.version += 1
            user.updated_at = utc_now()
            await self.repository.revoke_user_sessions(
                tenant_id=current_user.tenant_id,
                user_id=user.id,
                reason="admin_user_deactivated",
            )
            await self._emit_tenant_permission_changed(
                current_user=current_user,
                reason="admin_user_deactivated",
                affected_user_id=user.id,
                metadata={"user_id": str(user.id)},
            )
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="user",
            resource_id=user.id,
            result="allowed",
            audit_context=audit_context,
            metadata=_user_audit_metadata(user),
        )
        await self.repository.commit()
        return _user_response(user)

    async def reset_user_password(
        self,
        *,
        current_user: User,
        user_id: UUID,
        request: AdminUserPasswordResetRequest,
        audit_context: AuditContext | None,
    ) -> AdminUserResponse:
        action = "admin.user.password_reset"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="user",
            resource_id=user_id,
            audit_context=audit_context,
        )
        user = await self._get_user_for_update_or_deny(
            current_user=current_user,
            user_id=user_id,
            action=action,
            audit_context=audit_context,
        )
        await self._ensure_version(
            current_user=current_user,
            action=action,
            resource_type="user",
            resource_id=user.id,
            expected_version=request.expected_version,
            current_version=user.version,
            changed_code="ADMIN_USER_CHANGED",
            changed_message="用户已被其他请求修改",
            audit_context=audit_context,
        )
        ensure_password_policy(settings=self.settings, password=request.new_password)

        now = utc_now()
        user.password_hash = hash_password(request.new_password)
        user.local_password_enabled = True
        user.must_change_password = True
        user.password_changed_at = now
        user.failed_login_attempts = 0
        user.last_failed_login_at = None
        user.locked_until = None
        user.lock_reason = None
        user.version += 1
        user.updated_at = now
        await self.repository.revoke_user_sessions(
            tenant_id=current_user.tenant_id,
            user_id=user.id,
            reason="admin_password_reset",
        )
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="user",
            resource_id=user.id,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "must_change_password": True,
                "all_sessions_revoked": True,
                "version": user.version,
            },
        )
        await self.repository.commit()
        record_auth_security_event(event="password_reset", outcome="allowed")
        return _user_response(user)

    async def unlock_user(
        self,
        *,
        current_user: User,
        user_id: UUID,
        request: AdminUserUnlockRequest,
        audit_context: AuditContext | None,
    ) -> AdminUserResponse:
        action = "admin.user.unlocked"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="user",
            resource_id=user_id,
            audit_context=audit_context,
        )
        user = await self._get_user_for_update_or_deny(
            current_user=current_user,
            user_id=user_id,
            action=action,
            audit_context=audit_context,
        )
        await self._ensure_version(
            current_user=current_user,
            action=action,
            resource_type="user",
            resource_id=user.id,
            expected_version=request.expected_version,
            current_version=user.version,
            changed_code="ADMIN_USER_CHANGED",
            changed_message="用户已被其他请求修改",
            audit_context=audit_context,
        )

        changed = any(
            (
                user.failed_login_attempts != 0,
                user.last_failed_login_at is not None,
                user.locked_until is not None,
                user.lock_reason is not None,
            )
        )
        if changed:
            user.failed_login_attempts = 0
            user.last_failed_login_at = None
            user.locked_until = None
            user.lock_reason = None
            user.version += 1
            user.updated_at = utc_now()
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="user",
            resource_id=user.id,
            result="allowed",
            audit_context=audit_context,
            metadata={"changed": changed, "version": user.version},
        )
        await self.repository.commit()
        record_auth_security_event(
            event="account_unlock",
            outcome="changed" if changed else "noop",
        )
        return _user_response(user)

    async def list_departments(
        self,
        *,
        current_user: User,
        status: OrganizationStatus | None,
        parent_id: UUID | None,
        root_only: bool,
        query: str | None,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext | None,
    ) -> AdminDepartmentListResponse:
        action = "admin.departments.queried"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="department",
            resource_id=parent_id,
            audit_context=audit_context,
        )
        if parent_id is not None and root_only:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="department",
                resource_id=parent_id,
                code="DEPARTMENT_FILTER_INVALID",
                message="parent_id 与 root_only 不能同时使用",
                status_code=422,
                audit_context=audit_context,
                metadata={"reason": "conflicting_parent_filters"},
            )
        departments = await self.repository.list_departments(
            tenant_id=current_user.tenant_id,
            status=status,
            parent_id=parent_id,
            root_only=root_only,
            query=_normalize_query(query),
            cursor=decode_page_cursor(self.settings, cursor),
            limit=page_size + 1,
        )
        page = departments[:page_size]
        next_cursor = _next_cursor(self.settings, departments, page_size)
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="department",
            resource_id=parent_id,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "status": status,
                "parent_id": str(parent_id) if parent_id else None,
                "root_only": root_only,
                "query": _normalize_query(query),
                "returned_count": len(page),
                "has_next": next_cursor is not None,
            },
        )
        await self.repository.commit()
        return AdminDepartmentListResponse(
            items=[_department_response(department) for department in page],
            next_cursor=next_cursor,
        )

    async def get_department(
        self,
        *,
        current_user: User,
        department_id: UUID,
        audit_context: AuditContext | None,
    ) -> AdminDepartmentResponse:
        action = "admin.department.viewed"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="department",
            resource_id=department_id,
            audit_context=audit_context,
        )
        department = await self.repository.get_department(
            tenant_id=current_user.tenant_id,
            department_id=department_id,
        )
        if department is None:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="department",
                resource_id=department_id,
                code="DEPARTMENT_NOT_FOUND",
                message="部门不存在",
                status_code=404,
                audit_context=audit_context,
                metadata={"reason": "department_not_found"},
            )
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="department",
            resource_id=department.id,
            result="allowed",
            audit_context=audit_context,
            metadata={"path": department.path, "status": department.status},
        )
        await self.repository.commit()
        return _department_response(department)

    async def create_department(
        self,
        *,
        current_user: User,
        request: AdminDepartmentCreateRequest,
        audit_context: AuditContext | None,
    ) -> AdminDepartmentResponse:
        action = "admin.department.created"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="department",
            resource_id=request.parent_id,
            audit_context=audit_context,
        )
        name = _normalize_organization_name(request.name, field_name="部门名称")
        parent = None
        if request.parent_id is not None:
            parent = await self.repository.get_department(
                tenant_id=current_user.tenant_id,
                department_id=request.parent_id,
            )
            if parent is None:
                await self._deny(
                    current_user=current_user,
                    action=action,
                    resource_type="department",
                    resource_id=request.parent_id,
                    code="DEPARTMENT_PARENT_NOT_FOUND",
                    message="上级部门不存在",
                    status_code=404,
                    audit_context=audit_context,
                    metadata={"reason": "parent_not_found"},
                )
            if parent.status != "active":
                await self._deny(
                    current_user=current_user,
                    action=action,
                    resource_type="department",
                    resource_id=parent.id,
                    code="DEPARTMENT_PARENT_DISABLED",
                    message="不能在停用部门下创建子部门",
                    status_code=409,
                    audit_context=audit_context,
                    metadata={"reason": "parent_disabled"},
                )
        path = _build_department_path(parent=parent, name=name)
        try:
            department = await self.repository.create_department(
                tenant_id=current_user.tenant_id,
                parent_id=parent.id if parent is not None else None,
                name=name,
                path=path,
                sort_order=request.sort_order,
            )
            await self._record(
                current_user=current_user,
                action=action,
                resource_type="department",
                resource_id=department.id,
                result="allowed",
                audit_context=audit_context,
                metadata=_department_audit_metadata(department),
            )
            await self.repository.commit()
        except IntegrityError:
            await self._rollback_and_refresh_actor(current_user)
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="department",
                resource_id=None,
                code="DEPARTMENT_PATH_EXISTS",
                message="同一层级已存在同名部门",
                status_code=409,
                audit_context=audit_context,
                metadata={"path": path, "reason": "path_conflict"},
            )
        return _department_response(department)

    async def update_department(
        self,
        *,
        current_user: User,
        department_id: UUID,
        request: AdminDepartmentUpdateRequest,
        audit_context: AuditContext | None,
    ) -> AdminDepartmentResponse:
        action = "admin.department.updated"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="department",
            resource_id=department_id,
            audit_context=audit_context,
        )
        department = await self._get_department_for_update_or_deny(
            current_user=current_user,
            department_id=department_id,
            action=action,
            audit_context=audit_context,
        )
        await self._ensure_version(
            current_user=current_user,
            action=action,
            resource_type="department",
            resource_id=department.id,
            expected_version=request.expected_version,
            current_version=department.version,
            changed_code="DEPARTMENT_CHANGED",
            changed_message="部门已被其他请求修改",
            audit_context=audit_context,
        )

        next_parent_id = (
            None
            if request.move_to_root
            else request.parent_id
            if request.parent_id is not None
            else department.parent_id
        )
        parent = await self._resolve_department_parent(
            current_user=current_user,
            department=department,
            parent_id=next_parent_id,
            action=action,
            audit_context=audit_context,
        )
        next_name = (
            _normalize_organization_name(request.name, field_name="部门名称")
            if request.name is not None
            else department.name
        )
        next_status = request.status if request.status is not None else department.status
        if next_status == "disabled" and department.status != "disabled":
            await self._ensure_department_has_no_active_children(
                current_user=current_user,
                department=department,
                action=action,
                audit_context=audit_context,
            )
        if next_status == "active" and parent is not None and parent.status != "active":
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="department",
                resource_id=department.id,
                code="DEPARTMENT_PARENT_DISABLED",
                message="上级部门停用时不能启用当前部门",
                status_code=409,
                audit_context=audit_context,
                metadata={"parent_id": str(parent.id), "reason": "parent_disabled"},
            )

        old_path = department.path
        next_path = _build_department_path(parent=parent, name=next_name)
        changed_fields: list[str] = []
        now = utc_now()
        if next_path != old_path:
            subtree = await self.repository.list_department_subtree_for_update(
                tenant_id=current_user.tenant_id,
                root_path=old_path,
            )
            for item in subtree:
                suffix = item.path[len(old_path) :]
                replacement = f"{next_path}{suffix}"
                _ensure_department_path_length(replacement)
                if item.id == department.id:
                    continue
                item.path = replacement
                item.version += 1
                item.updated_at = now
            department.path = next_path
            changed_fields.append("path")
        if department.parent_id != next_parent_id:
            department.parent_id = next_parent_id
            changed_fields.append("parent_id")
        if department.name != next_name:
            department.name = next_name
            changed_fields.append("name")
        if request.sort_order is not None and department.sort_order != request.sort_order:
            department.sort_order = request.sort_order
            changed_fields.append("sort_order")
        status_changed = department.status != next_status
        if status_changed:
            department.status = next_status
            changed_fields.append("status")
        if changed_fields:
            department.version += 1
            department.updated_at = now
        if status_changed:
            await self._emit_tenant_permission_changed(
                current_user=current_user,
                reason="department_status_changed",
                affected_user_id=None,
                metadata={
                    "department_id": str(department.id),
                    "status": department.status,
                },
            )

        try:
            await self._record(
                current_user=current_user,
                action=action,
                resource_type="department",
                resource_id=department.id,
                result="allowed",
                audit_context=audit_context,
                metadata={
                    **_department_audit_metadata(department),
                    "old_path": old_path,
                    "changed_fields": changed_fields,
                },
            )
            await self.repository.commit()
        except IntegrityError:
            await self._rollback_and_refresh_actor(current_user)
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="department",
                resource_id=department_id,
                code="DEPARTMENT_PATH_EXISTS",
                message="同一层级已存在同名部门",
                status_code=409,
                audit_context=audit_context,
                metadata={"path": next_path, "reason": "path_conflict"},
            )
        return _department_response(department)

    async def deactivate_department(
        self,
        *,
        current_user: User,
        department_id: UUID,
        expected_version: int,
        audit_context: AuditContext | None,
    ) -> AdminDepartmentResponse:
        action = "admin.department.deactivated"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="department",
            resource_id=department_id,
            audit_context=audit_context,
        )
        department = await self._get_department_for_update_or_deny(
            current_user=current_user,
            department_id=department_id,
            action=action,
            audit_context=audit_context,
        )
        await self._ensure_version(
            current_user=current_user,
            action=action,
            resource_type="department",
            resource_id=department.id,
            expected_version=expected_version,
            current_version=department.version,
            changed_code="DEPARTMENT_CHANGED",
            changed_message="部门已被其他请求修改",
            audit_context=audit_context,
        )
        if department.status != "disabled":
            await self._ensure_department_has_no_active_children(
                current_user=current_user,
                department=department,
                action=action,
                audit_context=audit_context,
            )
            department.status = "disabled"
            department.version += 1
            department.updated_at = utc_now()
            await self._emit_tenant_permission_changed(
                current_user=current_user,
                reason="department_deactivated",
                affected_user_id=None,
                metadata={"department_id": str(department.id)},
            )
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="department",
            resource_id=department.id,
            result="allowed",
            audit_context=audit_context,
            metadata=_department_audit_metadata(department),
        )
        await self.repository.commit()
        return _department_response(department)

    async def list_department_members(
        self,
        *,
        current_user: User,
        department_id: UUID,
        is_active: bool | None,
        query: str | None,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext | None,
    ) -> AdminOrganizationMemberListResponse:
        action = "admin.department_members.queried"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="department",
            resource_id=department_id,
            audit_context=audit_context,
        )
        department = await self.repository.get_department(
            tenant_id=current_user.tenant_id,
            department_id=department_id,
        )
        if department is None:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="department",
                resource_id=department_id,
                code="DEPARTMENT_NOT_FOUND",
                message="部门不存在",
                status_code=404,
                audit_context=audit_context,
                metadata={"reason": "department_not_found"},
            )
        members = await self.repository.list_department_members(
            tenant_id=current_user.tenant_id,
            department_id=department.id,
            is_active=is_active,
            query=_normalize_query(query),
            cursor=decode_page_cursor(self.settings, cursor),
            limit=page_size + 1,
        )
        page = members[:page_size]
        next_cursor = _next_membership_cursor(self.settings, members, page_size)
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="department",
            resource_id=department.id,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "is_active": is_active,
                "query": _normalize_query(query),
                "returned_count": len(page),
                "has_next": next_cursor is not None,
            },
        )
        await self.repository.commit()
        return AdminOrganizationMemberListResponse(
            items=[
                _member_response(member=member, user=user, organization_version=department.version)
                for member, user in page
            ],
            next_cursor=next_cursor,
            organization_version=department.version,
        )

    async def add_department_member(
        self,
        *,
        current_user: User,
        department_id: UUID,
        user_id: UUID,
        expected_version: int,
        audit_context: AuditContext | None,
    ) -> AdminOrganizationMemberResponse:
        action = "admin.department_member.added"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="department",
            resource_id=department_id,
            audit_context=audit_context,
        )
        department = await self._get_department_for_update_or_deny(
            current_user=current_user,
            department_id=department_id,
            action=action,
            audit_context=audit_context,
        )
        await self._ensure_version(
            current_user=current_user,
            action=action,
            resource_type="department",
            resource_id=department.id,
            expected_version=expected_version,
            current_version=department.version,
            changed_code="DEPARTMENT_CHANGED",
            changed_message="部门已被其他请求修改",
            audit_context=audit_context,
        )
        if department.status != "active":
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="department",
                resource_id=department.id,
                code="DEPARTMENT_DISABLED",
                message="停用部门不能新增成员",
                status_code=409,
                audit_context=audit_context,
                metadata={"reason": "department_disabled"},
            )
        user = await self._get_active_target_user_or_deny(
            current_user=current_user,
            user_id=user_id,
            action=action,
            resource_type="department",
            resource_id=department.id,
            audit_context=audit_context,
        )
        existing = await self.repository.get_department_member(
            tenant_id=current_user.tenant_id,
            department_id=department.id,
            user_id=user.id,
        )
        if existing is not None:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="department",
                resource_id=department.id,
                code="DEPARTMENT_MEMBER_EXISTS",
                message="部门成员已存在",
                status_code=409,
                audit_context=audit_context,
                metadata={"user_id": str(user.id), "reason": "member_exists"},
            )
        try:
            member = await self.repository.add_department_member(
                tenant_id=current_user.tenant_id,
                department_id=department.id,
                user_id=user.id,
            )
            department.version += 1
            department.updated_at = utc_now()
            await self._emit_tenant_permission_changed(
                current_user=current_user,
                reason="department_member_added",
                affected_user_id=user.id,
                metadata={
                    "department_id": str(department.id),
                    "user_id": str(user.id),
                },
            )
            await self._record(
                current_user=current_user,
                action=action,
                resource_type="department",
                resource_id=department.id,
                result="allowed",
                audit_context=audit_context,
                metadata={
                    "user_id": str(user.id),
                    "organization_version": department.version,
                },
            )
            await self.repository.commit()
        except IntegrityError:
            await self._rollback_and_refresh_actor(current_user)
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="department",
                resource_id=department_id,
                code="DEPARTMENT_MEMBER_EXISTS",
                message="部门成员已存在",
                status_code=409,
                audit_context=audit_context,
                metadata={"user_id": str(user_id), "reason": "member_conflict"},
            )
        return _member_response(
            member=member,
            user=user,
            organization_version=department.version,
        )

    async def remove_department_member(
        self,
        *,
        current_user: User,
        department_id: UUID,
        user_id: UUID,
        expected_version: int,
        audit_context: AuditContext | None,
    ) -> AdminOrganizationMemberRemovalResponse:
        action = "admin.department_member.removed"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="department",
            resource_id=department_id,
            audit_context=audit_context,
        )
        department = await self._get_department_for_update_or_deny(
            current_user=current_user,
            department_id=department_id,
            action=action,
            audit_context=audit_context,
        )
        await self._ensure_version(
            current_user=current_user,
            action=action,
            resource_type="department",
            resource_id=department.id,
            expected_version=expected_version,
            current_version=department.version,
            changed_code="DEPARTMENT_CHANGED",
            changed_message="部门已被其他请求修改",
            audit_context=audit_context,
        )
        member = await self.repository.get_department_member(
            tenant_id=current_user.tenant_id,
            department_id=department.id,
            user_id=user_id,
        )
        if member is None:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="department",
                resource_id=department.id,
                code="DEPARTMENT_MEMBER_NOT_FOUND",
                message="部门成员不存在",
                status_code=404,
                audit_context=audit_context,
                metadata={"user_id": str(user_id), "reason": "member_not_found"},
            )
        await self.repository.remove_department_member(
            tenant_id=current_user.tenant_id,
            department_id=department.id,
            user_id=user_id,
        )
        department.version += 1
        department.updated_at = utc_now()
        await self._emit_tenant_permission_changed(
            current_user=current_user,
            reason="department_member_removed",
            affected_user_id=user_id,
            metadata={
                "department_id": str(department.id),
                "user_id": str(user_id),
            },
        )
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="department",
            resource_id=department.id,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "user_id": str(user_id),
                "organization_version": department.version,
            },
        )
        await self.repository.commit()
        return AdminOrganizationMemberRemovalResponse(
            user_id=user_id,
            organization_version=department.version,
        )

    async def list_groups(
        self,
        *,
        current_user: User,
        status: OrganizationStatus | None,
        query: str | None,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext | None,
    ) -> AdminGroupListResponse:
        action = "admin.groups.queried"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="user_group",
            resource_id=None,
            audit_context=audit_context,
        )
        groups = await self.repository.list_groups(
            tenant_id=current_user.tenant_id,
            status=status,
            query=_normalize_query(query),
            cursor=decode_page_cursor(self.settings, cursor),
            limit=page_size + 1,
        )
        page = groups[:page_size]
        next_cursor = _next_cursor(self.settings, groups, page_size)
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="user_group",
            resource_id=None,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "status": status,
                "query": _normalize_query(query),
                "returned_count": len(page),
                "has_next": next_cursor is not None,
            },
        )
        await self.repository.commit()
        return AdminGroupListResponse(
            items=[_group_response(group) for group in page],
            next_cursor=next_cursor,
        )

    async def get_group(
        self,
        *,
        current_user: User,
        group_id: UUID,
        audit_context: AuditContext | None,
    ) -> AdminGroupResponse:
        action = "admin.group.viewed"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="user_group",
            resource_id=group_id,
            audit_context=audit_context,
        )
        group = await self.repository.get_group(
            tenant_id=current_user.tenant_id,
            group_id=group_id,
        )
        if group is None:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="user_group",
                resource_id=group_id,
                code="GROUP_NOT_FOUND",
                message="用户组不存在",
                status_code=404,
                audit_context=audit_context,
                metadata={"reason": "group_not_found"},
            )
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="user_group",
            resource_id=group.id,
            result="allowed",
            audit_context=audit_context,
            metadata={"slug": group.slug, "status": group.status},
        )
        await self.repository.commit()
        return _group_response(group)

    async def create_group(
        self,
        *,
        current_user: User,
        request: AdminGroupCreateRequest,
        audit_context: AuditContext | None,
    ) -> AdminGroupResponse:
        action = "admin.group.created"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="user_group",
            resource_id=None,
            audit_context=audit_context,
        )
        slug = request.slug.strip().casefold()
        name = _normalize_organization_name(request.name, field_name="用户组名称")
        try:
            group = await self.repository.create_group(
                tenant_id=current_user.tenant_id,
                slug=slug,
                name=name,
            )
            await self._record(
                current_user=current_user,
                action=action,
                resource_type="user_group",
                resource_id=group.id,
                result="allowed",
                audit_context=audit_context,
                metadata=_group_audit_metadata(group),
            )
            await self.repository.commit()
        except IntegrityError:
            await self._rollback_and_refresh_actor(current_user)
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="user_group",
                resource_id=None,
                code="GROUP_SLUG_EXISTS",
                message="用户组标识已存在",
                status_code=409,
                audit_context=audit_context,
                metadata={"slug": slug, "reason": "slug_conflict"},
            )
        return _group_response(group)

    async def update_group(
        self,
        *,
        current_user: User,
        group_id: UUID,
        request: AdminGroupUpdateRequest,
        audit_context: AuditContext | None,
    ) -> AdminGroupResponse:
        action = "admin.group.updated"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="user_group",
            resource_id=group_id,
            audit_context=audit_context,
        )
        group = await self._get_group_for_update_or_deny(
            current_user=current_user,
            group_id=group_id,
            action=action,
            audit_context=audit_context,
        )
        await self._ensure_version(
            current_user=current_user,
            action=action,
            resource_type="user_group",
            resource_id=group.id,
            expected_version=request.expected_version,
            current_version=group.version,
            changed_code="GROUP_CHANGED",
            changed_message="用户组已被其他请求修改",
            audit_context=audit_context,
        )

        changed_fields: list[str] = []
        if request.slug is not None:
            slug = request.slug.strip().casefold()
            if slug != group.slug:
                group.slug = slug
                changed_fields.append("slug")
        if request.name is not None:
            name = _normalize_organization_name(request.name, field_name="用户组名称")
            if name != group.name:
                group.name = name
                changed_fields.append("name")
        status_changed = False
        if request.status is not None and request.status != group.status:
            group.status = request.status
            changed_fields.append("status")
            status_changed = True
        if changed_fields:
            group.version += 1
            group.updated_at = utc_now()
        if status_changed:
            await self._emit_tenant_permission_changed(
                current_user=current_user,
                reason="group_status_changed",
                affected_user_id=None,
                metadata={"group_id": str(group.id), "status": group.status},
            )

        try:
            await self._record(
                current_user=current_user,
                action=action,
                resource_type="user_group",
                resource_id=group.id,
                result="allowed",
                audit_context=audit_context,
                metadata={
                    **_group_audit_metadata(group),
                    "changed_fields": changed_fields,
                },
            )
            await self.repository.commit()
        except IntegrityError:
            await self._rollback_and_refresh_actor(current_user)
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="user_group",
                resource_id=group_id,
                code="GROUP_SLUG_EXISTS",
                message="用户组标识已存在",
                status_code=409,
                audit_context=audit_context,
                metadata={"reason": "slug_conflict"},
            )
        return _group_response(group)

    async def deactivate_group(
        self,
        *,
        current_user: User,
        group_id: UUID,
        expected_version: int,
        audit_context: AuditContext | None,
    ) -> AdminGroupResponse:
        action = "admin.group.deactivated"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="user_group",
            resource_id=group_id,
            audit_context=audit_context,
        )
        group = await self._get_group_for_update_or_deny(
            current_user=current_user,
            group_id=group_id,
            action=action,
            audit_context=audit_context,
        )
        await self._ensure_version(
            current_user=current_user,
            action=action,
            resource_type="user_group",
            resource_id=group.id,
            expected_version=expected_version,
            current_version=group.version,
            changed_code="GROUP_CHANGED",
            changed_message="用户组已被其他请求修改",
            audit_context=audit_context,
        )
        if group.status != "disabled":
            group.status = "disabled"
            group.version += 1
            group.updated_at = utc_now()
            await self._emit_tenant_permission_changed(
                current_user=current_user,
                reason="group_deactivated",
                affected_user_id=None,
                metadata={"group_id": str(group.id)},
            )
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="user_group",
            resource_id=group.id,
            result="allowed",
            audit_context=audit_context,
            metadata=_group_audit_metadata(group),
        )
        await self.repository.commit()
        return _group_response(group)

    async def list_group_members(
        self,
        *,
        current_user: User,
        group_id: UUID,
        is_active: bool | None,
        query: str | None,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext | None,
    ) -> AdminOrganizationMemberListResponse:
        action = "admin.group_members.queried"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="user_group",
            resource_id=group_id,
            audit_context=audit_context,
        )
        group = await self.repository.get_group(
            tenant_id=current_user.tenant_id,
            group_id=group_id,
        )
        if group is None:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="user_group",
                resource_id=group_id,
                code="GROUP_NOT_FOUND",
                message="用户组不存在",
                status_code=404,
                audit_context=audit_context,
                metadata={"reason": "group_not_found"},
            )
        members = await self.repository.list_group_members(
            tenant_id=current_user.tenant_id,
            group_id=group.id,
            is_active=is_active,
            query=_normalize_query(query),
            cursor=decode_page_cursor(self.settings, cursor),
            limit=page_size + 1,
        )
        page = members[:page_size]
        next_cursor = _next_membership_cursor(self.settings, members, page_size)
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="user_group",
            resource_id=group.id,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "is_active": is_active,
                "query": _normalize_query(query),
                "returned_count": len(page),
                "has_next": next_cursor is not None,
            },
        )
        await self.repository.commit()
        return AdminOrganizationMemberListResponse(
            items=[
                _member_response(member=member, user=user, organization_version=group.version)
                for member, user in page
            ],
            next_cursor=next_cursor,
            organization_version=group.version,
        )

    async def add_group_member(
        self,
        *,
        current_user: User,
        group_id: UUID,
        user_id: UUID,
        expected_version: int,
        audit_context: AuditContext | None,
    ) -> AdminOrganizationMemberResponse:
        action = "admin.group_member.added"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="user_group",
            resource_id=group_id,
            audit_context=audit_context,
        )
        group = await self._get_group_for_update_or_deny(
            current_user=current_user,
            group_id=group_id,
            action=action,
            audit_context=audit_context,
        )
        await self._ensure_version(
            current_user=current_user,
            action=action,
            resource_type="user_group",
            resource_id=group.id,
            expected_version=expected_version,
            current_version=group.version,
            changed_code="GROUP_CHANGED",
            changed_message="用户组已被其他请求修改",
            audit_context=audit_context,
        )
        if group.status != "active":
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="user_group",
                resource_id=group.id,
                code="GROUP_DISABLED",
                message="停用用户组不能新增成员",
                status_code=409,
                audit_context=audit_context,
                metadata={"reason": "group_disabled"},
            )
        user = await self._get_active_target_user_or_deny(
            current_user=current_user,
            user_id=user_id,
            action=action,
            resource_type="user_group",
            resource_id=group.id,
            audit_context=audit_context,
        )
        existing = await self.repository.get_group_member(
            tenant_id=current_user.tenant_id,
            group_id=group.id,
            user_id=user.id,
        )
        if existing is not None:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="user_group",
                resource_id=group.id,
                code="GROUP_MEMBER_EXISTS",
                message="用户组成员已存在",
                status_code=409,
                audit_context=audit_context,
                metadata={"user_id": str(user.id), "reason": "member_exists"},
            )
        try:
            member = await self.repository.add_group_member(
                tenant_id=current_user.tenant_id,
                group_id=group.id,
                user_id=user.id,
            )
            group.version += 1
            group.updated_at = utc_now()
            await self._emit_tenant_permission_changed(
                current_user=current_user,
                reason="group_member_added",
                affected_user_id=user.id,
                metadata={"group_id": str(group.id), "user_id": str(user.id)},
            )
            await self._record(
                current_user=current_user,
                action=action,
                resource_type="user_group",
                resource_id=group.id,
                result="allowed",
                audit_context=audit_context,
                metadata={
                    "user_id": str(user.id),
                    "organization_version": group.version,
                },
            )
            await self.repository.commit()
        except IntegrityError:
            await self._rollback_and_refresh_actor(current_user)
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="user_group",
                resource_id=group_id,
                code="GROUP_MEMBER_EXISTS",
                message="用户组成员已存在",
                status_code=409,
                audit_context=audit_context,
                metadata={"user_id": str(user_id), "reason": "member_conflict"},
            )
        return _member_response(
            member=member,
            user=user,
            organization_version=group.version,
        )

    async def remove_group_member(
        self,
        *,
        current_user: User,
        group_id: UUID,
        user_id: UUID,
        expected_version: int,
        audit_context: AuditContext | None,
    ) -> AdminOrganizationMemberRemovalResponse:
        action = "admin.group_member.removed"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="user_group",
            resource_id=group_id,
            audit_context=audit_context,
        )
        group = await self._get_group_for_update_or_deny(
            current_user=current_user,
            group_id=group_id,
            action=action,
            audit_context=audit_context,
        )
        await self._ensure_version(
            current_user=current_user,
            action=action,
            resource_type="user_group",
            resource_id=group.id,
            expected_version=expected_version,
            current_version=group.version,
            changed_code="GROUP_CHANGED",
            changed_message="用户组已被其他请求修改",
            audit_context=audit_context,
        )
        member = await self.repository.get_group_member(
            tenant_id=current_user.tenant_id,
            group_id=group.id,
            user_id=user_id,
        )
        if member is None:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="user_group",
                resource_id=group.id,
                code="GROUP_MEMBER_NOT_FOUND",
                message="用户组成员不存在",
                status_code=404,
                audit_context=audit_context,
                metadata={"user_id": str(user_id), "reason": "member_not_found"},
            )
        await self.repository.remove_group_member(
            tenant_id=current_user.tenant_id,
            group_id=group.id,
            user_id=user_id,
        )
        group.version += 1
        group.updated_at = utc_now()
        await self._emit_tenant_permission_changed(
            current_user=current_user,
            reason="group_member_removed",
            affected_user_id=user_id,
            metadata={"group_id": str(group.id), "user_id": str(user_id)},
        )
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="user_group",
            resource_id=group.id,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "user_id": str(user_id),
                "organization_version": group.version,
            },
        )
        await self.repository.commit()
        return AdminOrganizationMemberRemovalResponse(
            user_id=user_id,
            organization_version=group.version,
        )

    async def _get_user_for_update_or_deny(
        self,
        *,
        current_user: User,
        user_id: UUID,
        action: str,
        audit_context: AuditContext | None,
    ) -> User:
        user = await self.repository.get_user_for_update(
            tenant_id=current_user.tenant_id,
            user_id=user_id,
        )
        if user is None:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="user",
                resource_id=user_id,
                code="ADMIN_USER_NOT_FOUND",
                message="用户不存在",
                status_code=404,
                audit_context=audit_context,
                metadata={"reason": "user_not_found"},
            )
        return user

    async def _get_department_for_update_or_deny(
        self,
        *,
        current_user: User,
        department_id: UUID,
        action: str,
        audit_context: AuditContext | None,
    ) -> Department:
        department = await self.repository.get_department_for_update(
            tenant_id=current_user.tenant_id,
            department_id=department_id,
        )
        if department is None:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="department",
                resource_id=department_id,
                code="DEPARTMENT_NOT_FOUND",
                message="部门不存在",
                status_code=404,
                audit_context=audit_context,
                metadata={"reason": "department_not_found"},
            )
        return department

    async def _get_group_for_update_or_deny(
        self,
        *,
        current_user: User,
        group_id: UUID,
        action: str,
        audit_context: AuditContext | None,
    ) -> UserGroup:
        group = await self.repository.get_group_for_update(
            tenant_id=current_user.tenant_id,
            group_id=group_id,
        )
        if group is None:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="user_group",
                resource_id=group_id,
                code="GROUP_NOT_FOUND",
                message="用户组不存在",
                status_code=404,
                audit_context=audit_context,
                metadata={"reason": "group_not_found"},
            )
        return group

    async def _get_active_target_user_or_deny(
        self,
        *,
        current_user: User,
        user_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID,
        audit_context: AuditContext | None,
    ) -> User:
        user = await self.repository.get_user(
            tenant_id=current_user.tenant_id,
            user_id=user_id,
        )
        if user is None or not user.is_active:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                code="ADMIN_USER_NOT_FOUND",
                message="用户不存在或不可用",
                status_code=404,
                audit_context=audit_context,
                metadata={"user_id": str(user_id), "reason": "user_missing_or_inactive"},
            )
        return user

    async def _resolve_department_parent(
        self,
        *,
        current_user: User,
        department: Department,
        parent_id: UUID | None,
        action: str,
        audit_context: AuditContext | None,
    ) -> Department | None:
        if parent_id is None:
            return None
        if parent_id == department.id:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="department",
                resource_id=department.id,
                code="DEPARTMENT_CYCLE",
                message="部门不能移动到自身或下级部门",
                status_code=409,
                audit_context=audit_context,
                metadata={"parent_id": str(parent_id), "reason": "self_parent"},
            )
        parent = await self.repository.get_department(
            tenant_id=current_user.tenant_id,
            department_id=parent_id,
        )
        if parent is None:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="department",
                resource_id=department.id,
                code="DEPARTMENT_PARENT_NOT_FOUND",
                message="上级部门不存在",
                status_code=404,
                audit_context=audit_context,
                metadata={"parent_id": str(parent_id), "reason": "parent_not_found"},
            )
        if parent.path.startswith(f"{department.path}/"):
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="department",
                resource_id=department.id,
                code="DEPARTMENT_CYCLE",
                message="部门不能移动到自身或下级部门",
                status_code=409,
                audit_context=audit_context,
                metadata={"parent_id": str(parent.id), "reason": "descendant_parent"},
            )
        if parent.status != "active":
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="department",
                resource_id=department.id,
                code="DEPARTMENT_PARENT_DISABLED",
                message="不能移动到停用部门",
                status_code=409,
                audit_context=audit_context,
                metadata={"parent_id": str(parent.id), "reason": "parent_disabled"},
            )
        return parent

    async def _ensure_department_has_no_active_children(
        self,
        *,
        current_user: User,
        department: Department,
        action: str,
        audit_context: AuditContext | None,
    ) -> None:
        count = await self.repository.count_active_department_children(
            tenant_id=current_user.tenant_id,
            department_id=department.id,
        )
        if count == 0:
            return
        await self._deny(
            current_user=current_user,
            action=action,
            resource_type="department",
            resource_id=department.id,
            code="DEPARTMENT_HAS_ACTIVE_CHILDREN",
            message="请先停用或移动下级部门",
            status_code=409,
            audit_context=audit_context,
            metadata={"active_child_count": count, "reason": "active_children"},
        )

    async def _ensure_super_admin_survives(
        self,
        *,
        current_user: User,
        target_user: User,
        next_active: bool,
        next_super_admin: bool,
        action: str,
        audit_context: AuditContext | None,
    ) -> None:
        removes_active_admin = (
            target_user.is_active
            and target_user.is_super_admin
            and (not next_active or not next_super_admin)
        )
        if not removes_active_admin:
            return
        # Serialize the tenant-wide invariant before counting active administrators.
        await self.repository.lock_tenant_for_update(tenant_id=current_user.tenant_id)
        count = await self.repository.count_active_super_admins(tenant_id=current_user.tenant_id)
        if count > 1:
            return
        await self._deny(
            current_user=current_user,
            action=action,
            resource_type="user",
            resource_id=target_user.id,
            code="LAST_ACTIVE_SUPER_ADMIN",
            message="不能停用或降级最后一个有效系统管理员",
            status_code=409,
            audit_context=audit_context,
            metadata={"reason": "last_active_super_admin"},
        )

    async def _ensure_version(
        self,
        *,
        current_user: User,
        action: str,
        resource_type: str,
        resource_id: UUID,
        expected_version: int,
        current_version: int,
        changed_code: str,
        changed_message: str,
        audit_context: AuditContext | None,
    ) -> None:
        if current_version == expected_version:
            return
        await self._deny(
            current_user=current_user,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            code=changed_code,
            message=changed_message,
            status_code=409,
            audit_context=audit_context,
            metadata={
                "expected_version": expected_version,
                "current_version": current_version,
                "reason": "stale_precondition",
            },
        )

    async def _emit_tenant_permission_changed(
        self,
        *,
        current_user: User,
        reason: str,
        affected_user_id: UUID | None,
        metadata: dict[str, object],
    ) -> None:
        permission_version = await self.repository.bump_tenant_permission_version(
            tenant_id=current_user.tenant_id
        )
        await self.audit_service.record_permission_changed(
            tenant_id=current_user.tenant_id,
            actor_id=current_user.id,
            scope="tenant",
            resource_id=current_user.tenant_id,
            permission_version=permission_version,
            reason=reason,
            affected_user_id=affected_user_id,
            metadata=metadata,
        )
        await emit_share_recipients_rebuild_requested(
            audit_service=self.audit_service,
            tenant_id=current_user.tenant_id,
            scope="tenant",
            resource_id=current_user.tenant_id,
            reason=reason,
            affected_user_id=affected_user_id,
            metadata=metadata,
        )

    async def _rollback_and_refresh_actor(self, current_user: User) -> None:
        await self.repository.rollback()
        await self.repository.refresh_user(current_user)

    async def _require_admin(
        self,
        *,
        current_user: User,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        audit_context: AuditContext | None,
    ) -> None:
        if current_user.is_super_admin:
            return
        await self._deny(
            current_user=current_user,
            action=action,
            resource_type=resource_type,
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
        resource_type: str,
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
            resource_type=resource_type,
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
        resource_type: str,
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
                resource_type=resource_type,
                resource_id=resource_id,
                result=result,
                risk_level=(
                    "high"
                    if action.endswith("password_reset")
                    else "medium"
                    if result == "denied"
                    or action.endswith(
                        (
                            "created",
                            "updated",
                            "deactivated",
                            "added",
                            "removed",
                            "unlocked",
                        )
                    )
                    else "low"
                ),
                metadata=metadata,
            ),
            context=audit_context or AuditContext(),
        )


def _normalize_query(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    return normalized or None


def _normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    if not normalized:
        return None
    if (
        normalized.count("@") != 1
        or normalized.startswith("@")
        or normalized.endswith("@")
        or any(char.isspace() for char in normalized)
    ):
        raise ApiError("ADMIN_USER_EMAIL_INVALID", "邮箱格式不合法", status_code=422)
    return normalized


def _normalize_display_name(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or any(ord(char) < 32 for char in normalized):
        raise ApiError("ADMIN_USER_DISPLAY_NAME_INVALID", "用户显示名称不合法", status_code=422)
    return normalized


def _normalize_organization_name(value: str, *, field_name: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        raise ApiError("ORGANIZATION_NAME_INVALID", f"{field_name}不能为空", status_code=422)
    if any(char in normalized for char in {"/", "\\", "\x00"}) or any(
        ord(char) < 32 for char in normalized
    ):
        raise ApiError(
            "ORGANIZATION_NAME_INVALID",
            f"{field_name}不能包含路径分隔符或控制字符",
            status_code=422,
        )
    return normalized


def _build_department_path(*, parent: Department | None, name: str) -> str:
    path = f"/{name}" if parent is None else f"{parent.path}/{name}"
    _ensure_department_path_length(path)
    return path


def _ensure_department_path_length(path: str) -> None:
    if len(path) <= _MAX_DEPARTMENT_PATH_LENGTH:
        return
    raise ApiError("DEPARTMENT_PATH_TOO_LONG", "部门层级路径过长", status_code=422)


def _next_cursor(
    settings: Settings,
    items: list[User] | list[Department] | list[UserGroup],
    page_size: int,
) -> str | None:
    if len(items) <= page_size:
        return None
    page = items[:page_size]
    if not page:
        return None
    last = page[-1]
    return encode_page_cursor(
        settings,
        created_at=last.created_at,
        item_id=last.id,
    )


def _next_membership_cursor(
    settings: Settings,
    items: list[tuple[DepartmentMember, User]] | list[tuple[UserGroupMember, User]],
    page_size: int,
) -> str | None:
    if len(items) <= page_size:
        return None
    page = items[:page_size]
    if not page:
        return None
    last = page[-1][0]
    return encode_page_cursor(
        settings,
        created_at=last.created_at,
        item_id=last.id,
    )


def _user_response(user: User) -> AdminUserResponse:
    locked = user.locked_until is not None and ensure_utc(user.locked_until) > utc_now()
    return AdminUserResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        is_super_admin=user.is_super_admin,
        must_change_password=user.must_change_password,
        failed_login_attempts=user.failed_login_attempts,
        locked_until=user.locked_until,
        locked=locked,
        version=user.version,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _department_response(department: Department) -> AdminDepartmentResponse:
    return AdminDepartmentResponse(
        id=department.id,
        tenant_id=department.tenant_id,
        parent_id=department.parent_id,
        name=department.name,
        path=department.path,
        sort_order=department.sort_order,
        status=cast(OrganizationStatus, department.status),
        version=department.version,
        created_at=department.created_at,
        updated_at=department.updated_at,
    )


def _group_response(group: UserGroup) -> AdminGroupResponse:
    return AdminGroupResponse(
        id=group.id,
        tenant_id=group.tenant_id,
        slug=group.slug,
        name=group.name,
        status=cast(OrganizationStatus, group.status),
        version=group.version,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


def _member_response(
    *,
    member: DepartmentMember | UserGroupMember,
    user: User,
    organization_version: int,
) -> AdminOrganizationMemberResponse:
    return AdminOrganizationMemberResponse(
        id=member.id,
        user=_user_response(user),
        created_at=member.created_at,
        organization_version=organization_version,
    )


def _user_audit_metadata(user: User) -> dict[str, object]:
    return {
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "is_active": user.is_active,
        "is_super_admin": user.is_super_admin,
        "must_change_password": user.must_change_password,
        "failed_login_attempts": user.failed_login_attempts,
        "locked_until": user.locked_until.isoformat() if user.locked_until else None,
        "locked": user.locked_until is not None and ensure_utc(user.locked_until) > utc_now(),
        "version": user.version,
    }


def _department_audit_metadata(department: Department) -> dict[str, object]:
    return {
        "parent_id": str(department.parent_id) if department.parent_id else None,
        "name": department.name,
        "path": department.path,
        "sort_order": department.sort_order,
        "status": department.status,
        "version": department.version,
    }


def _group_audit_metadata(group: UserGroup) -> dict[str, object]:
    return {
        "slug": group.slug,
        "name": group.name,
        "status": group.status,
        "version": group.version,
    }
