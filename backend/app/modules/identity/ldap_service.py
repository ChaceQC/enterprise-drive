from __future__ import annotations

import secrets
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.metrics import record_identity_provider_operation
from app.core.security import hash_password, utc_now
from app.infrastructure.identity.base import (
    LdapDepartmentRecord,
    LdapDirectorySnapshot,
    LdapGroupRecord,
    LdapProviderAdapter,
    LdapSourceConfig,
    LdapUserRecord,
    SecretResolver,
)
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.identity.models import (
    LdapMembershipClaim,
    LdapMembershipRelation,
    LdapObjectBinding,
    LdapSource,
    LdapSyncConflict,
    LdapSyncRun,
)
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.schemas import (
    LdapConnectionTestResponse,
    LdapSourceCreateRequest,
    LdapSourceListResponse,
    LdapSourceResponse,
    LdapSourceUpdateRequest,
    LdapSyncConflictListResponse,
    LdapSyncConflictResponse,
    LdapSyncRequest,
    LdapSyncRunListResponse,
    LdapSyncRunResponse,
)
from app.modules.org.models import Department, DepartmentMember, UserGroup, UserGroupMember
from app.modules.share.events import emit_share_recipients_rebuild_requested


@dataclass(slots=True)
class _LdapPermissionChanges:
    user_ids: set[UUID] = field(default_factory=set)
    department_ids: set[UUID] = field(default_factory=set)
    group_ids: set[UUID] = field(default_factory=set)

    @property
    def changed(self) -> bool:
        return bool(self.user_ids or self.department_ids or self.group_ids)


class LdapIdentityService:
    def __init__(
        self,
        *,
        repository: IdentityRepository,
        provider_adapter: LdapProviderAdapter,
        secret_resolver: SecretResolver,
        settings: Settings,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.provider_adapter = provider_adapter
        self.secret_resolver = secret_resolver
        self.settings = settings
        self.audit_service = audit_service

    async def list_sources(
        self,
        *,
        current_user: User,
        audit_context: AuditContext | None,
    ) -> LdapSourceListResponse:
        await self._require_admin(
            current_user=current_user,
            action="identity.ldap.source.list",
            resource_id=None,
            audit_context=audit_context,
        )
        sources = await self.repository.list_ldap_sources(tenant_id=current_user.tenant_id)
        return LdapSourceListResponse(items=[_source_response(source) for source in sources])

    async def create_source(
        self,
        *,
        current_user: User,
        request: LdapSourceCreateRequest,
        audit_context: AuditContext | None,
    ) -> LdapSourceResponse:
        await self._require_admin(
            current_user=current_user,
            action="identity.ldap.source.created",
            resource_id=None,
            audit_context=audit_context,
        )
        source = LdapSource(
            tenant_id=current_user.tenant_id,
            slug=request.slug.strip().lower(),
            name=request.name.strip(),
            server_url=request.server_url.strip(),
            base_dn=request.base_dn.strip(),
            bind_dn=_optional(request.bind_dn),
            bind_password_ref=_optional(request.bind_password_ref),
            user_base_dn=request.user_base_dn.strip(),
            user_filter=request.user_filter.strip(),
            department_base_dn=_optional(request.department_base_dn),
            department_filter=_optional(request.department_filter),
            group_base_dn=_optional(request.group_base_dn),
            group_filter=_optional(request.group_filter),
            attribute_mapping=_normalize_mapping(request.attribute_mapping),
            enabled=request.enabled,
        )
        try:
            await self.repository.create_ldap_source(source)
            await self._record(
                AuditEvent(
                    tenant_id=current_user.tenant_id,
                    actor_id=current_user.id,
                    action="identity.ldap.source.created",
                    resource_type="ldap_source",
                    resource_id=source.id,
                    result="allowed",
                    metadata={
                        "slug": source.slug,
                        "bind_password_configured": source.bind_password_ref is not None,
                    },
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise ApiError(
                "LDAP_SOURCE_CONFLICT",
                "LDAP 目录源标识已存在",
                status_code=409,
            ) from exc
        return _source_response(source)

    async def update_source(
        self,
        *,
        current_user: User,
        source_id: UUID,
        request: LdapSourceUpdateRequest,
        audit_context: AuditContext | None,
    ) -> LdapSourceResponse:
        await self._require_admin(
            current_user=current_user,
            action="identity.ldap.source.updated",
            resource_id=source_id,
            audit_context=audit_context,
        )
        source = await self.repository.get_ldap_source(
            tenant_id=current_user.tenant_id,
            source_id=source_id,
            for_update=True,
        )
        if source is None:
            raise ApiError("LDAP_SOURCE_NOT_FOUND", "LDAP 目录源不存在", status_code=404)
        if source.version != request.expected_version:
            raise ApiError(
                "RESOURCE_VERSION_CONFLICT",
                "LDAP 目录源已被其他请求修改",
                status_code=409,
                details={"current_version": source.version},
            )

        changed_fields: list[str] = []
        for field_name, value in (
            ("name", _strip_or_none(request.name)),
            ("server_url", _strip_or_none(request.server_url)),
            ("base_dn", _strip_or_none(request.base_dn)),
            ("user_base_dn", _strip_or_none(request.user_base_dn)),
            ("user_filter", _strip_or_none(request.user_filter)),
            ("enabled", request.enabled),
        ):
            if value is not None and getattr(source, field_name) != value:
                setattr(source, field_name, value)
                changed_fields.append(field_name)
        for field_name, value_name, clear_name in (
            ("bind_dn", "bind_dn", "clear_bind_dn"),
            ("bind_password_ref", "bind_password_ref", "clear_bind_password_ref"),
            ("department_base_dn", "department_base_dn", "clear_department_base_dn"),
            ("department_filter", "department_filter", "clear_department_filter"),
            ("group_base_dn", "group_base_dn", "clear_group_base_dn"),
            ("group_filter", "group_filter", "clear_group_filter"),
        ):
            value = getattr(request, value_name)
            if getattr(request, clear_name):
                if getattr(source, field_name) is not None:
                    setattr(source, field_name, None)
                    changed_fields.append(field_name)
            elif value is not None:
                normalized = _strip_or_none(value)
                if getattr(source, field_name) != normalized:
                    setattr(source, field_name, normalized)
                    changed_fields.append(field_name)
        if request.attribute_mapping is not None:
            mapping = _normalize_mapping(request.attribute_mapping)
            if source.attribute_mapping != mapping:
                source.attribute_mapping = mapping
                changed_fields.append("attribute_mapping")
        if changed_fields:
            source.version += 1
            source.updated_at = utc_now()
        await self._record(
            AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action="identity.ldap.source.updated",
                resource_type="ldap_source",
                resource_id=source.id,
                result="allowed",
                metadata={"changed_fields": changed_fields},
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        return _source_response(source)

    async def test_source(
        self,
        *,
        current_user: User,
        source_id: UUID,
        audit_context: AuditContext | None,
    ) -> LdapConnectionTestResponse:
        await self._require_admin(
            current_user=current_user,
            action="identity.ldap.source.tested",
            resource_id=source_id,
            audit_context=audit_context,
        )
        source = await self.repository.get_ldap_source(
            tenant_id=current_user.tenant_id,
            source_id=source_id,
        )
        if source is None:
            raise ApiError("LDAP_SOURCE_NOT_FOUND", "LDAP 目录源不存在", status_code=404)
        source_config = self._source_config(source)
        # Do not keep a database read transaction open while probing LDAP.
        await self.repository.commit()
        try:
            result = await self.provider_adapter.test_connection(source_config)
        except Exception:
            record_identity_provider_operation(
                provider_type="ldap",
                operation="connection_test",
                outcome="failure",
            )
            await self._record(
                AuditEvent(
                    tenant_id=current_user.tenant_id,
                    actor_id=current_user.id,
                    action="identity.ldap.source.tested",
                    resource_type="ldap_source",
                    resource_id=source.id,
                    result="denied",
                    risk_level="medium",
                    metadata={"connected": False},
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
            raise
        record_identity_provider_operation(
            provider_type="ldap",
            operation="connection_test",
            outcome="success",
        )
        await self._record(
            AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action="identity.ldap.source.tested",
                resource_type="ldap_source",
                resource_id=source.id,
                result="allowed",
                metadata={"connected": True},
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        return LdapConnectionTestResponse(
            server=str(result.get("server", "unknown")),
            base_dn_found=bool(result.get("base_dn_found", False)),
        )

    async def request_sync(
        self,
        *,
        current_user: User,
        source_id: UUID,
        request: LdapSyncRequest,
        audit_context: AuditContext | None,
    ) -> LdapSyncRunResponse:
        await self._require_admin(
            current_user=current_user,
            action="identity.ldap.sync.requested",
            resource_id=source_id,
            audit_context=audit_context,
        )
        source = await self.repository.get_ldap_source(
            tenant_id=current_user.tenant_id,
            source_id=source_id,
        )
        if source is None:
            raise ApiError("LDAP_SOURCE_NOT_FOUND", "LDAP 目录源不存在", status_code=404)
        if not source.enabled:
            raise ApiError("LDAP_SOURCE_DISABLED", "LDAP 目录源已停用", status_code=409)
        active = await self.repository.session.scalar(
            select(LdapSyncRun.id).where(
                LdapSyncRun.source_id == source.id,
                LdapSyncRun.status.in_(("queued", "running")),
            )
        )
        if active is not None:
            raise ApiError("LDAP_SYNC_ALREADY_RUNNING", "LDAP 同步已在运行", status_code=409)
        run = LdapSyncRun(
            tenant_id=current_user.tenant_id,
            source_id=source.id,
            requested_by=current_user.id,
            source_version=source.version,
            mode=request.mode,
            status="queued",
            cursor_before=source.sync_cursor,
            stats={},
        )
        try:
            await self.repository.create_ldap_run(run)
            await self._record(
                AuditEvent(
                    tenant_id=current_user.tenant_id,
                    actor_id=current_user.id,
                    action="identity.ldap.sync.requested",
                    resource_type="ldap_sync_run",
                    resource_id=run.id,
                    result="allowed",
                    metadata={"source_id": str(source.id), "mode": request.mode},
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise ApiError(
                "LDAP_SYNC_ALREADY_RUNNING",
                "LDAP 同步已在运行",
                status_code=409,
            ) from exc
        return _run_response(run)

    async def list_runs(
        self,
        *,
        current_user: User,
        source_id: UUID | None,
        limit: int,
        audit_context: AuditContext | None,
    ) -> LdapSyncRunListResponse:
        await self._require_admin(
            current_user=current_user,
            action="identity.ldap.sync.list",
            resource_id=source_id,
            audit_context=audit_context,
        )
        runs = await self.repository.list_ldap_runs(
            tenant_id=current_user.tenant_id,
            source_id=source_id,
            limit=limit,
        )
        return LdapSyncRunListResponse(items=[_run_response(run) for run in runs])

    async def list_conflicts(
        self,
        *,
        current_user: User,
        run_id: UUID,
        audit_context: AuditContext | None,
    ) -> LdapSyncConflictListResponse:
        await self._require_admin(
            current_user=current_user,
            action="identity.ldap.sync.conflicts.list",
            resource_id=run_id,
            audit_context=audit_context,
        )
        run = await self.repository.get_ldap_run(run_id=run_id)
        if run is None or run.tenant_id != current_user.tenant_id:
            raise ApiError("LDAP_SYNC_RUN_NOT_FOUND", "LDAP 同步记录不存在", status_code=404)
        conflicts = await self.repository.list_ldap_conflicts(
            tenant_id=current_user.tenant_id,
            run_id=run_id,
        )
        return LdapSyncConflictListResponse(
            items=[
                LdapSyncConflictResponse(
                    id=item.id,
                    run_id=item.run_id,
                    source_id=item.source_id,
                    object_type=cast(
                        Literal["user", "department", "group", "membership"],
                        item.object_type,
                    ),
                    external_id=item.external_id,
                    code=item.code,
                    details=item.details,
                    created_at=item.created_at,
                )
                for item in conflicts
            ]
        )

    async def execute_run(self, *, run_id: UUID) -> LdapSyncRunResponse:
        run = await self.repository.get_ldap_run(run_id=run_id, for_update=True)
        if run is None:
            raise ApiError("LDAP_SYNC_RUN_NOT_FOUND", "LDAP 同步记录不存在", status_code=404)
        if run.status != "queued":
            return _run_response(run)
        source = await self.repository.get_ldap_source(
            tenant_id=run.tenant_id,
            source_id=run.source_id,
            for_update=True,
        )
        if source is None:
            raise ApiError("LDAP_SOURCE_NOT_FOUND", "LDAP 目录源不存在", status_code=404)
        if source.version != run.source_version:
            run.status = "failed"
            run.error_code = "LDAP_SOURCE_VERSION_CHANGED"
            run.error_message = "LDAP 目录源配置已变更，请重新发起同步"
            run.finished_at = utc_now()
            await self.repository.commit()
            return _run_response(run)
        run.status = "running"
        run.started_at = run.started_at or utc_now()
        await self.repository.commit()

        try:
            snapshot = await self.provider_adapter.read_directory(
                config=self._source_config(source),
                mode="full" if run.mode == "dry_run" else run.mode,
                cursor=run.cursor_before,
                page_size=int(getattr(self.settings, "ldap_sync_page_size", 500)),
            )
            current_source_version = await self.repository.get_ldap_source_version(
                tenant_id=run.tenant_id,
                source_id=run.source_id,
                for_update=True,
            )
            if current_source_version != run.source_version:
                raise ApiError(
                    "LDAP_SOURCE_VERSION_CHANGED",
                    "LDAP 目录源配置已变更，请重新发起同步",
                    status_code=409,
                )
            await self._apply_snapshot(
                run=run,
                source=source,
                snapshot=snapshot,
                apply=run.mode != "dry_run",
            )
            run.status = "succeeded"
            run.cursor_after = snapshot.next_cursor
            run.finished_at = utc_now()
            if run.mode != "dry_run":
                source.sync_cursor = snapshot.next_cursor
                source.last_success_at = run.finished_at
            await self._record(
                AuditEvent(
                    tenant_id=run.tenant_id,
                    actor_id=run.requested_by,
                    action="identity.ldap.sync.completed",
                    resource_type="ldap_sync_run",
                    resource_id=run.id,
                    result="allowed",
                    metadata=dict(run.stats),
                ),
                audit_context=None,
            )
            await self.repository.commit()
        except ApiError as exc:
            await self.repository.rollback()
            await self._mark_failed(run_id=run_id, code=exc.code, message=exc.message)
        except Exception:
            await self.repository.rollback()
            await self._mark_failed(
                run_id=run_id,
                code="LDAP_SYNC_FAILED",
                message="LDAP 同步失败",
            )
        refreshed = await self.repository.get_ldap_run(run_id=run_id)
        assert refreshed is not None
        return _run_response(refreshed)

    async def _apply_snapshot(
        self,
        *,
        run: LdapSyncRun,
        source: LdapSource,
        snapshot: LdapDirectorySnapshot,
        apply: bool,
    ) -> None:
        stats: dict[str, int] = defaultdict(int)
        stats["users_seen"] = len(snapshot.users)
        stats["departments_seen"] = len(snapshot.departments)
        stats["groups_seen"] = len(snapshot.groups)
        permission_changes = _LdapPermissionChanges()
        self._validate_snapshot(snapshot)

        department_ids: dict[str, UUID] = {}
        for department_record in _topological_departments(snapshot.departments):
            department = await self._apply_department(
                run=run,
                source=source,
                record=department_record,
                department_ids=department_ids,
                apply=apply,
                stats=stats,
                permission_changes=permission_changes,
            )
            if department is not None:
                department_ids[department_record.external_id] = department.id

        user_ids: dict[str, UUID] = {}
        for user_record in snapshot.users:
            user = await self._apply_user(
                run=run,
                source=source,
                record=user_record,
                apply=apply,
                stats=stats,
                permission_changes=permission_changes,
            )
            if user is not None:
                user_ids[user_record.external_id] = user.id

        group_ids: dict[str, UUID] = {}
        for group_record in snapshot.groups:
            group = await self._apply_group(
                run=run,
                source=source,
                record=group_record,
                apply=apply,
                stats=stats,
                permission_changes=permission_changes,
            )
            if group is not None:
                group_ids[group_record.external_id] = group.id

        if apply:
            for user_record in snapshot.users:
                user_id = user_ids.get(user_record.external_id)
                if user_id is None:
                    continue
                for department_external_id in user_record.department_external_ids:
                    department_id = department_ids.get(department_external_id)
                    if department_id is not None:
                        await self._ensure_membership(
                            run=run,
                            source=source,
                            relation_type="department",
                            container_id=department_id,
                            external_container_id=department_external_id,
                            user_id=user_id,
                            external_user_id=user_record.external_id,
                            stats=stats,
                            permission_changes=permission_changes,
                        )
                for group_external_id in user_record.group_external_ids:
                    group_id = group_ids.get(group_external_id)
                    if group_id is not None:
                        await self._ensure_membership(
                            run=run,
                            source=source,
                            relation_type="group",
                            container_id=group_id,
                            external_container_id=group_external_id,
                            user_id=user_id,
                            external_user_id=user_record.external_id,
                            stats=stats,
                            permission_changes=permission_changes,
                        )
            for group_record in snapshot.groups:
                group_id = group_ids.get(group_record.external_id)
                if group_id is None:
                    continue
                for external_user_id in group_record.member_external_ids:
                    user_id = user_ids.get(external_user_id)
                    if user_id is not None:
                        await self._ensure_membership(
                            run=run,
                            source=source,
                            relation_type="group",
                            container_id=group_id,
                            external_container_id=group_record.external_id,
                            user_id=user_id,
                            external_user_id=external_user_id,
                            stats=stats,
                            permission_changes=permission_changes,
                        )
            if run.mode == "full":
                await self._mark_missing_objects(
                    run=run,
                    source=source,
                    seen={
                        "user": set(user_ids),
                        "department": set(department_ids),
                        "group": set(group_ids),
                    },
                    stats=stats,
                    permission_changes=permission_changes,
                )
                await self._remove_stale_membership_claims(
                    run=run,
                    source=source,
                    stats=stats,
                    permission_changes=permission_changes,
                )
            if permission_changes.changed:
                permission_version = await self.repository.bump_tenant_permission_version(
                    tenant_id=run.tenant_id
                )
                await self._emit_permission_changes(
                    run=run,
                    source=source,
                    permission_version=permission_version,
                    changes=permission_changes,
                )
        stats["conflicts"] += int(run.stats.get("conflicts", 0))
        run.stats = dict(stats)

    async def _apply_department(
        self,
        *,
        run: LdapSyncRun,
        source: LdapSource,
        record: LdapDepartmentRecord,
        department_ids: dict[str, UUID],
        apply: bool,
        stats: dict[str, int],
        permission_changes: _LdapPermissionChanges,
    ) -> Department | None:
        binding = await self.repository.get_ldap_binding(
            tenant_id=run.tenant_id,
            source_id=source.id,
            object_type="department",
            external_id=record.external_id,
            for_update=apply,
        )
        parent_id = (
            department_ids.get(record.parent_external_id)
            if record.parent_external_id is not None
            else None
        )
        if record.parent_external_id is not None and parent_id is None:
            await self._conflict(
                run=run,
                source=source,
                object_type="department",
                external_id=record.external_id,
                code="parent_missing",
                details={"parent_external_id": record.parent_external_id},
            )
            return None
        parent = (
            await self.repository.get_department(
                tenant_id=run.tenant_id,
                department_id=parent_id,
            )
            if parent_id is not None
            else None
        )
        path = _department_path(parent.path if parent else None, record.name)
        department: Department | None = None
        if binding is not None:
            department = await self.repository.get_department(
                tenant_id=run.tenant_id,
                department_id=binding.local_object_id,
            )
            if department is None:
                await self._conflict(
                    run=run,
                    source=source,
                    object_type="department",
                    external_id=record.external_id,
                    code="local_object_missing",
                    details={},
                )
                return None
        else:
            department = await self.repository.find_department_by_path(
                tenant_id=run.tenant_id,
                path=path,
            )
            if department is not None:
                await self._conflict(
                    run=run,
                    source=source,
                    object_type="department",
                    external_id=record.external_id,
                    code="path_conflict",
                    details={"path": path},
                )
                return None
            if not apply:
                stats["created"] += 1
                return None
            department = Department(
                tenant_id=run.tenant_id,
                parent_id=parent_id,
                name=record.name.strip(),
                path=path,
                status="active" if record.enabled else "disabled",
                sort_order=0,
            )
            await self.repository.add_local_object(department)
            binding = LdapObjectBinding(
                tenant_id=run.tenant_id,
                source_id=source.id,
                object_type="department",
                external_id=record.external_id,
                local_object_id=department.id,
                authoritative=True,
            )
            await self.repository.add_ldap_binding(binding)
            stats["created"] += 1
            permission_changes.department_ids.add(department.id)
        if not apply:
            if department.name != record.name or department.path != path:
                stats["updated"] += 1
            if department.status == "active" and not record.enabled:
                stats["disabled"] += 1
            return department
        changed = False
        if department.name != record.name.strip():
            department.name = record.name.strip()
            changed = True
        if department.parent_id != parent_id:
            department.parent_id = parent_id
            changed = True
        if department.path != path:
            department.path = path
            changed = True
        next_status = "active" if record.enabled else "disabled"
        if department.status != next_status:
            department.status = next_status
            changed = True
            if next_status == "disabled":
                stats["disabled"] += 1
        if changed:
            department.version += 1
            department.updated_at = utc_now()
            stats["updated"] += 1
            permission_changes.department_ids.add(department.id)
        assert binding is not None
        binding.sync_state = "active" if record.enabled else "disabled"
        binding.last_seen_run_id = run.id
        binding.last_seen_at = utc_now()
        return department

    async def _apply_user(
        self,
        *,
        run: LdapSyncRun,
        source: LdapSource,
        record: LdapUserRecord,
        apply: bool,
        stats: dict[str, int],
        permission_changes: _LdapPermissionChanges,
    ) -> User | None:
        binding = await self.repository.get_ldap_binding(
            tenant_id=run.tenant_id,
            source_id=source.id,
            object_type="user",
            external_id=record.external_id,
            for_update=apply,
        )
        user: User | None = None
        if binding is not None:
            user = await self.repository.get_user(
                tenant_id=run.tenant_id,
                user_id=binding.local_object_id,
                for_update=apply,
            )
            if user is None:
                await self._conflict(
                    run=run,
                    source=source,
                    object_type="user",
                    external_id=record.external_id,
                    code="local_object_missing",
                    details={},
                )
                return None
        else:
            existing = await self.repository.find_user_by_login(
                tenant_id=run.tenant_id,
                username=record.username,
            )
            if existing is not None:
                await self._conflict(
                    run=run,
                    source=source,
                    object_type="user",
                    external_id=record.external_id,
                    code="username_conflict",
                    details={"username": record.username},
                )
                return None
            if not apply:
                stats["created"] += 1
                return None
            user = User(
                tenant_id=run.tenant_id,
                username=record.username.strip(),
                email=record.email,
                display_name=record.display_name.strip() or record.username.strip(),
                password_hash=hash_password(secrets.token_urlsafe(32)),
                local_password_enabled=False,
                is_active=record.enabled,
                is_super_admin=False,
                must_change_password=False,
            )
            await self.repository.add_local_object(user)
            binding = LdapObjectBinding(
                tenant_id=run.tenant_id,
                source_id=source.id,
                object_type="user",
                external_id=record.external_id,
                local_object_id=user.id,
                authoritative=True,
            )
            await self.repository.add_ldap_binding(binding)
            stats["created"] += 1
            permission_changes.user_ids.add(user.id)
        if not apply:
            if user.username != record.username or user.email != record.email:
                stats["updated"] += 1
            if user.is_active and not record.enabled:
                stats["disabled"] += 1
            return user
        changed = False
        if user.username != record.username.strip():
            collision = await self.repository.find_user_by_login(
                tenant_id=run.tenant_id,
                username=record.username,
            )
            if collision is not None and collision.id != user.id:
                await self._conflict(
                    run=run,
                    source=source,
                    object_type="user",
                    external_id=record.external_id,
                    code="username_conflict",
                    details={"username": record.username},
                )
                return None
            user.username = record.username.strip()
            changed = True
        if user.email != record.email:
            user.email = record.email
            changed = True
        display_name = record.display_name.strip() or record.username.strip()
        if user.display_name != display_name:
            user.display_name = display_name
            changed = True
        next_active = record.enabled
        if (
            user.is_active != next_active
            and not next_active
            and user.is_super_admin
            and await self.repository.count_active_super_admins(tenant_id=run.tenant_id) <= 1
        ):
            await self._conflict(
                run=run,
                source=source,
                object_type="user",
                external_id=record.external_id,
                code="last_super_admin",
                details={},
            )
            return None
        if user.is_active != next_active:
            user.is_active = next_active
            changed = True
            if not next_active:
                await self.repository.revoke_all_user_sessions(
                    tenant_id=user.tenant_id,
                    user_id=user.id,
                    revoked_at=utc_now(),
                    reason="ldap_disabled",
                )
                stats["disabled"] += 1
        if changed:
            user.version += 1
            user.updated_at = utc_now()
            stats["updated"] += 1
            permission_changes.user_ids.add(user.id)
        assert binding is not None
        binding.sync_state = "active" if record.enabled else "disabled"
        binding.last_seen_run_id = run.id
        binding.last_seen_at = utc_now()
        return user

    async def _apply_group(
        self,
        *,
        run: LdapSyncRun,
        source: LdapSource,
        record: LdapGroupRecord,
        apply: bool,
        stats: dict[str, int],
        permission_changes: _LdapPermissionChanges,
    ) -> UserGroup | None:
        binding = await self.repository.get_ldap_binding(
            tenant_id=run.tenant_id,
            source_id=source.id,
            object_type="group",
            external_id=record.external_id,
            for_update=apply,
        )
        group: UserGroup | None = None
        if binding is not None:
            group = await self.repository.get_group(
                tenant_id=run.tenant_id,
                group_id=binding.local_object_id,
            )
            if group is None:
                await self._conflict(
                    run=run,
                    source=source,
                    object_type="group",
                    external_id=record.external_id,
                    code="local_object_missing",
                    details={},
                )
                return None
        else:
            existing = await self.repository.find_group_by_slug(
                tenant_id=run.tenant_id,
                slug=record.slug,
            )
            if existing is not None:
                await self._conflict(
                    run=run,
                    source=source,
                    object_type="group",
                    external_id=record.external_id,
                    code="slug_conflict",
                    details={"slug": record.slug},
                )
                return None
            if not apply:
                stats["created"] += 1
                return None
            group = UserGroup(
                tenant_id=run.tenant_id,
                slug=record.slug.strip(),
                name=record.name.strip(),
                status="active" if record.enabled else "disabled",
            )
            await self.repository.add_local_object(group)
            binding = LdapObjectBinding(
                tenant_id=run.tenant_id,
                source_id=source.id,
                object_type="group",
                external_id=record.external_id,
                local_object_id=group.id,
                authoritative=True,
            )
            await self.repository.add_ldap_binding(binding)
            stats["created"] += 1
            permission_changes.group_ids.add(group.id)
        if not apply:
            if group.name != record.name or group.slug != record.slug:
                stats["updated"] += 1
            if group.status == "active" and not record.enabled:
                stats["disabled"] += 1
            return group
        changed = False
        if group.name != record.name.strip():
            group.name = record.name.strip()
            changed = True
        if group.slug != record.slug.strip():
            collision = await self.repository.find_group_by_slug(
                tenant_id=run.tenant_id,
                slug=record.slug,
            )
            if collision is not None and collision.id != group.id:
                await self._conflict(
                    run=run,
                    source=source,
                    object_type="group",
                    external_id=record.external_id,
                    code="slug_conflict",
                    details={"slug": record.slug},
                )
                return None
            group.slug = record.slug.strip()
            changed = True
        next_status = "active" if record.enabled else "disabled"
        if group.status != next_status:
            group.status = next_status
            changed = True
            if next_status == "disabled":
                stats["disabled"] += 1
        if changed:
            group.version += 1
            group.updated_at = utc_now()
            stats["updated"] += 1
            permission_changes.group_ids.add(group.id)
        assert binding is not None
        binding.sync_state = "active" if record.enabled else "disabled"
        binding.last_seen_run_id = run.id
        binding.last_seen_at = utc_now()
        return group

    async def _ensure_membership(
        self,
        *,
        run: LdapSyncRun,
        source: LdapSource,
        relation_type: str,
        container_id: UUID,
        external_container_id: str,
        user_id: UUID,
        external_user_id: str,
        stats: dict[str, int],
        permission_changes: _LdapPermissionChanges,
    ) -> None:
        relation = await self.repository.get_membership_relation(
            tenant_id=run.tenant_id,
            relation_type=relation_type,
            container_id=container_id,
            user_id=user_id,
        )
        if relation is None:
            if relation_type == "department":
                department_member = await self.repository.get_department_member(
                    tenant_id=run.tenant_id,
                    department_id=container_id,
                    user_id=user_id,
                )
                core_exists = department_member is not None
            else:
                group_member = await self.repository.get_group_member(
                    tenant_id=run.tenant_id,
                    group_id=container_id,
                    user_id=user_id,
                )
                core_exists = group_member is not None
            relation = LdapMembershipRelation(
                tenant_id=run.tenant_id,
                relation_type=relation_type,
                container_id=container_id,
                user_id=user_id,
                core_edge_managed=not core_exists,
            )
            await self.repository.add_membership_relation(relation)
            if not core_exists:
                if relation_type == "department":
                    await self.repository.add_department_member(
                        DepartmentMember(
                            tenant_id=run.tenant_id,
                            department_id=container_id,
                            user_id=user_id,
                        )
                    )
                    permission_changes.department_ids.add(container_id)
                else:
                    await self.repository.add_group_member(
                        UserGroupMember(
                            tenant_id=run.tenant_id,
                            group_id=container_id,
                            user_id=user_id,
                        )
                    )
                    permission_changes.group_ids.add(container_id)
                permission_changes.user_ids.add(user_id)
            stats["memberships_changed"] += 1
        claim = await self.repository.get_membership_claim(
            source_id=source.id,
            relation_id=relation.id,
        )
        if claim is None:
            await self.repository.add_membership_claim(
                LdapMembershipClaim(
                    tenant_id=run.tenant_id,
                    source_id=source.id,
                    relation_id=relation.id,
                    external_container_id=external_container_id,
                    external_user_id=external_user_id,
                    last_seen_run_id=run.id,
                )
            )
            stats["memberships_changed"] += 1
        else:
            claim.last_seen_run_id = run.id

    async def _mark_missing_objects(
        self,
        *,
        run: LdapSyncRun,
        source: LdapSource,
        seen: dict[str, set[str]],
        stats: dict[str, int],
        permission_changes: _LdapPermissionChanges,
    ) -> None:
        for binding in await self.repository.list_ldap_bindings(
            tenant_id=run.tenant_id,
            source_id=source.id,
        ):
            if binding.external_id in seen.get(binding.object_type, set()):
                continue
            if binding.sync_state == "missing":
                continue
            binding.sync_state = "missing"
            binding.last_seen_run_id = run.id
            if binding.object_type == "user":
                user = await self.repository.get_user(
                    tenant_id=run.tenant_id,
                    user_id=binding.local_object_id,
                    for_update=True,
                )
                if user is not None and user.is_active:
                    if (
                        user.is_super_admin
                        and await self.repository.count_active_super_admins(tenant_id=run.tenant_id)
                        <= 1
                    ):
                        await self._conflict(
                            run=run,
                            source=source,
                            object_type="user",
                            external_id=binding.external_id,
                            code="last_super_admin",
                            details={"reason": "missing_from_full_snapshot"},
                        )
                        continue
                    user.is_active = False
                    user.version += 1
                    user.updated_at = utc_now()
                    await self.repository.revoke_all_user_sessions(
                        tenant_id=user.tenant_id,
                        user_id=user.id,
                        revoked_at=utc_now(),
                        reason="ldap_missing",
                    )
                    stats["disabled"] += 1
                    permission_changes.user_ids.add(user.id)
            elif binding.object_type == "department":
                department = await self.repository.get_department(
                    tenant_id=run.tenant_id,
                    department_id=binding.local_object_id,
                )
                if department is not None and department.status != "disabled":
                    department.status = "disabled"
                    department.version += 1
                    department.updated_at = utc_now()
                    stats["disabled"] += 1
                    permission_changes.department_ids.add(department.id)
            elif binding.object_type == "group":
                group = await self.repository.get_group(
                    tenant_id=run.tenant_id,
                    group_id=binding.local_object_id,
                )
                if group is not None and group.status != "disabled":
                    group.status = "disabled"
                    group.version += 1
                    group.updated_at = utc_now()
                    stats["disabled"] += 1
                    permission_changes.group_ids.add(group.id)

    async def _remove_stale_membership_claims(
        self,
        *,
        run: LdapSyncRun,
        source: LdapSource,
        stats: dict[str, int],
        permission_changes: _LdapPermissionChanges,
    ) -> None:
        for claim, relation in await self.repository.list_stale_membership_claims(
            source_id=source.id,
            run_id=run.id,
        ):
            await self.repository.delete_membership_claim(claim)
            if await self.repository.count_membership_claims(relation_id=relation.id) == 0:
                if relation.core_edge_managed:
                    await self.repository.delete_core_membership(relation)
                    permission_changes.user_ids.add(relation.user_id)
                    if relation.relation_type == "department":
                        permission_changes.department_ids.add(relation.container_id)
                    else:
                        permission_changes.group_ids.add(relation.container_id)
                await self.repository.delete_membership_relation(relation)
                stats["memberships_changed"] += 1

    async def _emit_permission_changes(
        self,
        *,
        run: LdapSyncRun,
        source: LdapSource,
        permission_version: int,
        changes: _LdapPermissionChanges,
    ) -> None:
        if self.audit_service is None:
            return
        common_metadata: dict[str, object] = {
            "source_id": str(source.id),
            "run_id": str(run.id),
            "permission_version": permission_version,
        }
        await self.audit_service.record_permission_changed(
            tenant_id=run.tenant_id,
            actor_id=run.requested_by,
            scope="tenant",
            resource_id=run.tenant_id,
            permission_version=permission_version,
            reason="ldap_sync",
            metadata={
                **common_metadata,
                "users_changed": len(changes.user_ids),
                "departments_changed": len(changes.department_ids),
                "groups_changed": len(changes.group_ids),
            },
        )
        for department_id in sorted(changes.department_ids, key=str):
            await emit_share_recipients_rebuild_requested(
                audit_service=self.audit_service,
                tenant_id=run.tenant_id,
                scope="department",
                resource_id=department_id,
                reason="ldap_sync",
                affected_user_id=None,
                metadata={
                    **common_metadata,
                    "department_id": str(department_id),
                },
            )
        for group_id in sorted(changes.group_ids, key=str):
            await emit_share_recipients_rebuild_requested(
                audit_service=self.audit_service,
                tenant_id=run.tenant_id,
                scope="group",
                resource_id=group_id,
                reason="ldap_sync",
                affected_user_id=None,
                metadata={
                    **common_metadata,
                    "group_id": str(group_id),
                },
            )
        for user_id in sorted(changes.user_ids, key=str):
            await emit_share_recipients_rebuild_requested(
                audit_service=self.audit_service,
                tenant_id=run.tenant_id,
                scope="user",
                resource_id=user_id,
                reason="ldap_sync",
                affected_user_id=user_id,
                metadata=common_metadata,
            )

    async def _conflict(
        self,
        *,
        run: LdapSyncRun,
        source: LdapSource,
        object_type: str,
        external_id: str,
        code: str,
        details: dict[str, object],
    ) -> None:
        await self.repository.add_ldap_conflict(
            LdapSyncConflict(
                tenant_id=run.tenant_id,
                source_id=source.id,
                run_id=run.id,
                object_type=object_type,
                external_id=external_id,
                code=code,
                details=details,
            )
        )
        run.stats["conflicts"] = int(run.stats.get("conflicts", 0)) + 1

    async def _mark_failed(self, *, run_id: UUID, code: str, message: str) -> None:
        run = await self.repository.get_ldap_run(run_id=run_id, for_update=True)
        if run is None:
            return
        run.status = "failed"
        run.error_code = code
        run.error_message = message[:500]
        run.finished_at = utc_now()
        await self.repository.commit()

    def _source_config(self, source: LdapSource) -> LdapSourceConfig:
        return LdapSourceConfig(
            id=source.id,
            server_url=source.server_url,
            base_dn=source.base_dn,
            bind_dn=source.bind_dn,
            bind_password=self.secret_resolver.resolve(source.bind_password_ref),
            user_base_dn=source.user_base_dn,
            user_filter=source.user_filter,
            department_base_dn=source.department_base_dn,
            department_filter=source.department_filter,
            group_base_dn=source.group_base_dn,
            group_filter=source.group_filter,
            attribute_mapping=dict(source.attribute_mapping),
        )

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
        await self._record(
            AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action=action,
                resource_type="identity",
                resource_id=resource_id,
                result="denied",
                risk_level="medium",
                metadata={"reason": "super_admin_required"},
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        raise ApiError("ADMIN_REQUIRED", "需要系统管理员权限", status_code=403)

    def _validate_snapshot(self, snapshot: LdapDirectorySnapshot) -> None:
        for name, values in (
            ("users", snapshot.users),
            ("departments", snapshot.departments),
            ("groups", snapshot.groups),
        ):
            ids = [item.external_id for item in values]
            if len(ids) != len(set(ids)):
                raise ApiError(
                    "LDAP_DUPLICATE_EXTERNAL_ID",
                    "LDAP 同步返回重复外部标识",
                    status_code=422,
                    details={"object_type": name},
                )

    async def _record(
        self,
        event: AuditEvent,
        *,
        audit_context: AuditContext | None,
    ) -> None:
        if self.audit_service is None:
            return
        await self.audit_service.record(
            event=event,
            context=audit_context or AuditContext(),
        )


def _source_response(source: LdapSource) -> LdapSourceResponse:
    return LdapSourceResponse(
        id=source.id,
        tenant_id=source.tenant_id,
        slug=source.slug,
        name=source.name,
        server_url=source.server_url,
        base_dn=source.base_dn,
        bind_dn=source.bind_dn,
        bind_password_configured=source.bind_password_ref is not None,
        user_base_dn=source.user_base_dn,
        user_filter=source.user_filter,
        department_base_dn=source.department_base_dn,
        department_filter=source.department_filter,
        group_base_dn=source.group_base_dn,
        group_filter=source.group_filter,
        attribute_mapping=dict(source.attribute_mapping),
        enabled=source.enabled,
        sync_cursor=source.sync_cursor,
        last_success_at=source.last_success_at,
        version=source.version,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def _run_response(run: LdapSyncRun) -> LdapSyncRunResponse:
    return LdapSyncRunResponse(
        id=run.id,
        tenant_id=run.tenant_id,
        source_id=run.source_id,
        requested_by=run.requested_by,
        source_version=run.source_version,
        mode=cast(Literal["dry_run", "full", "incremental"], run.mode),
        status=cast(Literal["queued", "running", "succeeded", "failed"], run.status),
        cursor_before=run.cursor_before,
        cursor_after=run.cursor_after,
        stats=dict(run.stats),
        error_code=run.error_code,
        error_message=run.error_message,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
    )


def _normalize_mapping(mapping: dict[str, str]) -> dict[str, str]:
    normalized = {
        str(key).strip(): str(value).strip()
        for key, value in mapping.items()
        if str(key).strip() and str(value).strip()
    }
    required = {
        "user_external_id",
        "user_username",
        "user_display_name",
    }
    if not required.issubset(normalized):
        raise ApiError(
            "LDAP_ATTRIBUTE_MAPPING_INVALID",
            "LDAP 用户属性映射不完整",
            status_code=422,
        )
    return normalized


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _strip_or_none(value: str | None) -> str | None:
    return _optional(value)


def _department_path(parent_path: str | None, name: str) -> str:
    clean_name = name.strip().replace("/", "／").replace("\\", "＼")
    return f"{parent_path}/{clean_name}" if parent_path else f"/{clean_name}"


def _topological_departments(
    records: Iterable[LdapDepartmentRecord],
) -> list[LdapDepartmentRecord]:
    pending: list[LdapDepartmentRecord] = list(records)
    result: list[LdapDepartmentRecord] = []
    known: set[str] = set()
    while pending:
        progressed = False
        for record in list(pending):
            parent_external_id = getattr(record, "parent_external_id", None)
            if parent_external_id is None or parent_external_id in known:
                result.append(record)
                known.add(record.external_id)
                pending.remove(record)
                progressed = True
        if not progressed:
            # Keep deterministic output; the service will emit parent_missing.
            result.extend(pending)
            break
    return result
