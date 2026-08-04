from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from celery import Celery  # type: ignore[import-untyped]

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.maintenance_health import is_task_stale, load_maintenance_task_health
from app.core.pagination import decode_page_cursor, encode_page_cursor
from app.core.security import utc_now
from app.modules.admin.job_repository import AdminJobRepository
from app.modules.admin.models import AdminJob
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.models import FileTreeOperation
from app.modules.governance.models import LifecyclePolicy, PermissionRebuildOperation
from app.modules.governance.repository import GovernanceRepository
from app.modules.governance.schemas import (
    AdminTreeOperationListResponse,
    AdminTreeOperationResponse,
    GovernanceOverviewResponse,
    LifecyclePolicyResponse,
    LifecyclePolicyUpdateRequest,
    LifecycleRunCreateRequest,
    LifecycleRunListResponse,
    LifecycleRunResponse,
    PermissionRebuildCreateRequest,
    PermissionRebuildOperationListResponse,
    PermissionRebuildOperationResponse,
    PermissionRebuildScope,
)


class GovernanceService:
    def __init__(
        self,
        *,
        repository: GovernanceRepository,
        job_repository: AdminJobRepository,
        audit_service: AuditService,
        celery_app: Celery,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.job_repository = job_repository
        self.audit_service = audit_service
        self.celery_app = celery_app
        self.settings = settings

    async def get_overview(
        self,
        *,
        current_user: User,
        audit_context: AuditContext,
    ) -> GovernanceOverviewResponse:
        await self._require_admin(
            current_user=current_user,
            action="admin.governance.overview.queried",
            audit_context=audit_context,
        )
        values = await self.repository.governance_counts(tenant_id=current_user.tenant_id)
        health = load_maintenance_task_health(settings=self.settings)
        values["maintenance_alerts"] = sum(item.alert_active for item in health)
        values["maintenance_stale"] = sum(
            is_task_stale(settings=self.settings, health=item) for item in health
        )
        await self._record(
            current_user=current_user,
            action="admin.governance.overview.queried",
            resource_type="governance",
            resource_id=None,
            result="allowed",
            audit_context=audit_context,
            metadata=cast(dict[str, object], values),
        )
        await self.repository.commit()
        return GovernanceOverviewResponse(
            generated_at=datetime.now(UTC),
            **values,
        )

    async def get_lifecycle_policy(
        self,
        *,
        current_user: User,
        audit_context: AuditContext,
    ) -> LifecyclePolicyResponse:
        await self._require_admin(
            current_user=current_user,
            action="admin.lifecycle_policy.queried",
            audit_context=audit_context,
        )
        policy = await self._ensure_policy(current_user=current_user)
        await self._record(
            current_user=current_user,
            action="admin.lifecycle_policy.queried",
            resource_type="lifecycle_policy",
            resource_id=policy.id,
            result="allowed",
            audit_context=audit_context,
            metadata={"version": policy.version},
        )
        await self.repository.commit()
        return _policy_response(policy)

    async def update_lifecycle_policy(
        self,
        *,
        current_user: User,
        request: LifecyclePolicyUpdateRequest,
        audit_context: AuditContext,
    ) -> LifecyclePolicyResponse:
        await self._require_admin(
            current_user=current_user,
            action="admin.lifecycle_policy.updated",
            audit_context=audit_context,
        )
        policy = await self.repository.get_lifecycle_policy_for_update(
            tenant_id=current_user.tenant_id
        )
        if policy is None:
            policy = await self._ensure_policy(current_user=current_user)
        if policy.version != request.expected_version:
            await self.repository.rollback()
            raise ApiError(
                "LIFECYCLE_POLICY_VERSION_CONFLICT",
                "生命周期策略版本已变化",
                status_code=409,
                details={"current_version": policy.version},
            )
        policy.trash_retention_days = request.trash_retention_days
        policy.preview_retention_days = request.preview_retention_days
        policy.expire_uploads = request.expire_uploads
        policy.expire_shares = request.expire_shares
        policy.cleanup_unreferenced_blobs = request.cleanup_unreferenced_blobs
        policy.cleanup_orphaned_objects = request.cleanup_orphaned_objects
        policy.updated_by = current_user.id
        policy.version += 1
        policy.updated_at = utc_now()
        await self._record(
            current_user=current_user,
            action="admin.lifecycle_policy.updated",
            resource_type="lifecycle_policy",
            resource_id=policy.id,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "version": policy.version,
                "trash_retention_days": policy.trash_retention_days,
                "preview_retention_days": policy.preview_retention_days,
                "expire_uploads": policy.expire_uploads,
                "expire_shares": policy.expire_shares,
                "cleanup_unreferenced_blobs": policy.cleanup_unreferenced_blobs,
                "cleanup_orphaned_objects": policy.cleanup_orphaned_objects,
            },
        )
        await self.repository.commit()
        return _policy_response(policy)

    async def create_lifecycle_run(
        self,
        *,
        current_user: User,
        request: LifecycleRunCreateRequest,
        audit_context: AuditContext,
    ) -> LifecycleRunResponse:
        await self._require_admin(
            current_user=current_user,
            action="admin.lifecycle_run.created",
            audit_context=audit_context,
        )
        policy = await self._ensure_policy(current_user=current_user)
        parameters: dict[str, object] = {
            "tenant_id": str(current_user.tenant_id),
            "dry_run": request.dry_run,
            "limit": request.limit,
            "policy_id": str(policy.id),
            "policy_version": policy.version,
            "trash_retention_days": policy.trash_retention_days,
            "preview_retention_days": policy.preview_retention_days,
            "expire_uploads": policy.expire_uploads,
            "expire_shares": policy.expire_shares,
            "cleanup_unreferenced_blobs": policy.cleanup_unreferenced_blobs,
            "cleanup_orphaned_objects": policy.cleanup_orphaned_objects,
            "request_id": audit_context.request_id,
        }
        job = await self.job_repository.create_job(
            tenant_id=current_user.tenant_id,
            kind="governance",
            operation="lifecycle.run_policy",
            created_by=current_user.id,
            parameters=parameters,
        )
        await self._record(
            current_user=current_user,
            action="admin.lifecycle_run.created",
            resource_type="lifecycle_run",
            resource_id=job.id,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "dry_run": request.dry_run,
                "limit": request.limit,
                "policy_version": policy.version,
            },
        )
        await self.repository.commit()
        await self._enqueue_job(
            job=job,
            task_name="governance.run_lifecycle_policy",
        )
        return _lifecycle_run_response(job)

    async def list_lifecycle_runs(
        self,
        *,
        current_user: User,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext,
    ) -> LifecycleRunListResponse:
        await self._require_admin(
            current_user=current_user,
            action="admin.lifecycle_runs.queried",
            audit_context=audit_context,
        )
        decoded = decode_page_cursor(self.settings, cursor)
        records = await self.repository.list_lifecycle_runs(
            tenant_id=current_user.tenant_id,
            cursor=decoded,
            limit=page_size + 1,
        )
        page = records[:page_size]
        next_cursor = _next_cursor(self.settings, records=records, page=page, page_size=page_size)
        await self._record(
            current_user=current_user,
            action="admin.lifecycle_runs.queried",
            resource_type="lifecycle_run",
            resource_id=None,
            result="allowed",
            audit_context=audit_context,
            metadata={"returned_count": len(page), "has_next": next_cursor is not None},
        )
        await self.repository.commit()
        return LifecycleRunListResponse(
            items=[_lifecycle_run_response(record) for record in page],
            next_cursor=next_cursor,
        )

    async def create_permission_rebuild(
        self,
        *,
        current_user: User,
        request: PermissionRebuildCreateRequest,
        audit_context: AuditContext,
    ) -> PermissionRebuildOperationResponse:
        await self._require_admin(
            current_user=current_user,
            action="admin.permission_rebuild.created",
            audit_context=audit_context,
        )
        space = await self.repository.get_space(
            tenant_id=current_user.tenant_id,
            space_id=request.space_id,
        )
        if space is None:
            raise ApiError("SPACE_NOT_FOUND", "空间不存在", status_code=404)

        root_node_id: UUID | None = None
        permission_version = space.permission_version
        if request.scope == "space":
            if request.root_node_id is not None:
                raise ApiError(
                    "PERMISSION_REBUILD_SCOPE_INVALID",
                    "空间级权限重算不能指定根节点",
                    status_code=422,
                )
        else:
            if request.root_node_id is None:
                raise ApiError(
                    "PERMISSION_REBUILD_SCOPE_INVALID",
                    "节点级权限重算必须指定根节点",
                    status_code=422,
                )
            node = await self.repository.get_node(
                tenant_id=current_user.tenant_id,
                node_id=request.root_node_id,
            )
            if node is None or node.space_id != request.space_id:
                raise ApiError("NODE_NOT_FOUND", "节点不存在", status_code=404)
            root_node_id = node.id
            permission_version = max(permission_version, node.permission_version)

        operation, created = await self.repository.create_or_refresh_permission_rebuild(
            tenant_id=current_user.tenant_id,
            space_id=request.space_id,
            root_node_id=root_node_id,
            scope=request.scope,
            permission_version=permission_version,
            requested_by=current_user.id,
            request_id=audit_context.request_id,
        )
        await self._record(
            current_user=current_user,
            action="admin.permission_rebuild.created",
            resource_type=request.scope,
            resource_id=root_node_id or request.space_id,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "operation_id": str(operation.id),
                "created": created,
                "permission_version": operation.permission_version,
                "restart_requested": operation.restart_requested,
            },
        )
        await self.repository.commit()
        return _permission_rebuild_response(operation)

    async def list_permission_rebuilds(
        self,
        *,
        current_user: User,
        status: str | None,
        scope: str | None,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext,
    ) -> PermissionRebuildOperationListResponse:
        await self._require_admin(
            current_user=current_user,
            action="admin.permission_rebuilds.queried",
            audit_context=audit_context,
        )
        decoded = decode_page_cursor(self.settings, cursor)
        records = await self.repository.list_permission_rebuilds(
            tenant_id=current_user.tenant_id,
            status=status,
            scope=scope,
            cursor=decoded,
            limit=page_size + 1,
        )
        page = records[:page_size]
        next_cursor = _next_cursor(self.settings, records=records, page=page, page_size=page_size)
        await self._record(
            current_user=current_user,
            action="admin.permission_rebuilds.queried",
            resource_type="permission_rebuild",
            resource_id=None,
            result="allowed",
            audit_context=audit_context,
            metadata={"returned_count": len(page), "has_next": next_cursor is not None},
        )
        await self.repository.commit()
        return PermissionRebuildOperationListResponse(
            items=[_permission_rebuild_response(record) for record in page],
            next_cursor=next_cursor,
        )

    async def get_permission_rebuild(
        self,
        *,
        current_user: User,
        operation_id: UUID,
        audit_context: AuditContext,
    ) -> PermissionRebuildOperationResponse:
        await self._require_admin(
            current_user=current_user,
            action="admin.permission_rebuild.viewed",
            audit_context=audit_context,
        )
        operation = await self.repository.get_permission_rebuild(
            tenant_id=current_user.tenant_id,
            operation_id=operation_id,
        )
        if operation is None:
            raise ApiError(
                "PERMISSION_REBUILD_NOT_FOUND",
                "权限重算任务不存在",
                status_code=404,
            )
        await self._record(
            current_user=current_user,
            action="admin.permission_rebuild.viewed",
            resource_type="permission_rebuild",
            resource_id=operation.id,
            result="allowed",
            audit_context=audit_context,
            metadata={"status": operation.status},
        )
        await self.repository.commit()
        return _permission_rebuild_response(operation)

    async def retry_permission_rebuild(
        self,
        *,
        current_user: User,
        operation_id: UUID,
        audit_context: AuditContext,
    ) -> PermissionRebuildOperationResponse:
        await self._require_admin(
            current_user=current_user,
            action="admin.permission_rebuild.retried",
            audit_context=audit_context,
        )
        operation = await self.repository.get_permission_rebuild(
            tenant_id=current_user.tenant_id,
            operation_id=operation_id,
            for_update=True,
        )
        if operation is None:
            raise ApiError(
                "PERMISSION_REBUILD_NOT_FOUND",
                "权限重算任务不存在",
                status_code=404,
            )
        if operation.status != "failed":
            raise ApiError(
                "PERMISSION_REBUILD_NOT_RETRYABLE",
                "权限重算任务当前状态不可重试",
                status_code=409,
            )
        operation.status = "pending"
        operation.error_code = None
        operation.completed_at = None
        operation.updated_at = utc_now()
        await self._record(
            current_user=current_user,
            action="admin.permission_rebuild.retried",
            resource_type="permission_rebuild",
            resource_id=operation.id,
            result="allowed",
            audit_context=audit_context,
            metadata={"processed_count": operation.processed_count},
        )
        await self.repository.commit()
        return _permission_rebuild_response(operation)

    async def list_tree_operations(
        self,
        *,
        current_user: User,
        status: str | None,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext,
    ) -> AdminTreeOperationListResponse:
        await self._require_admin(
            current_user=current_user,
            action="admin.tree_operations.queried",
            audit_context=audit_context,
        )
        decoded = decode_page_cursor(self.settings, cursor)
        records = await self.repository.list_tree_operations(
            tenant_id=current_user.tenant_id,
            status=status,
            cursor=decoded,
            limit=page_size + 1,
        )
        page = records[:page_size]
        next_cursor = _next_cursor(self.settings, records=records, page=page, page_size=page_size)
        await self._record(
            current_user=current_user,
            action="admin.tree_operations.queried",
            resource_type="file_tree_operation",
            resource_id=None,
            result="allowed",
            audit_context=audit_context,
            metadata={"returned_count": len(page), "has_next": next_cursor is not None},
        )
        await self.repository.commit()
        return AdminTreeOperationListResponse(
            items=[_tree_operation_response(record) for record in page],
            next_cursor=next_cursor,
        )

    async def _ensure_policy(self, *, current_user: User) -> LifecyclePolicy:
        policy = await self.repository.get_lifecycle_policy(tenant_id=current_user.tenant_id)
        if policy is not None:
            return policy
        return await self.repository.create_lifecycle_policy(
            tenant_id=current_user.tenant_id,
            updated_by=current_user.id,
            trash_retention_days=self.settings.trash_retention_days,
            preview_retention_days=self.settings.preview_artifact_retention_days,
        )

    async def _enqueue_job(self, *, job: AdminJob, task_name: str) -> None:
        try:
            result = self.celery_app.send_task(
                task_name,
                kwargs={"job_id": str(job.id)},
                queue="maintenance",
            )
            job.celery_task_id = str(result.id)
            job.version += 1
            await self.repository.commit()
        except Exception as exc:
            job.status = "failed"
            job.error_code = "GOVERNANCE_JOB_ENQUEUE_FAILED"
            job.error_message = type(exc).__name__
            job.completed_at = utc_now()
            job.version += 1
            await self.repository.commit()

    async def _require_admin(
        self,
        *,
        current_user: User,
        action: str,
        audit_context: AuditContext,
    ) -> None:
        if current_user.is_super_admin:
            return
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="governance",
            resource_id=None,
            result="denied",
            audit_context=audit_context,
            metadata={"reason": "super_admin_required"},
        )
        await self.repository.commit()
        raise ApiError("ADMIN_REQUIRED", "需要系统管理员权限", status_code=403)

    async def _record(
        self,
        *,
        current_user: User,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        result: str,
        audit_context: AuditContext,
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
                risk_level="high",
                metadata=metadata,
            ),
            context=audit_context,
        )


def _policy_response(policy: LifecyclePolicy) -> LifecyclePolicyResponse:
    return LifecyclePolicyResponse(
        id=policy.id,
        tenant_id=policy.tenant_id,
        trash_retention_days=policy.trash_retention_days,
        preview_retention_days=policy.preview_retention_days,
        expire_uploads=policy.expire_uploads,
        expire_shares=policy.expire_shares,
        cleanup_unreferenced_blobs=policy.cleanup_unreferenced_blobs,
        cleanup_orphaned_objects=policy.cleanup_orphaned_objects,
        version=policy.version,
        updated_by=policy.updated_by,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _lifecycle_run_response(job: AdminJob) -> LifecycleRunResponse:
    return LifecycleRunResponse(
        id=job.id,
        status=cast(
            Literal["pending", "running", "succeeded", "failed"],
            job.status,
        ),
        dry_run=bool(job.parameters_json.get("dry_run", True)),
        policy_version=_as_int(job.parameters_json.get("policy_version"), default=1),
        result=job.result_json,
        error_code=job.error_code,
        created_by=job.created_by,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def _permission_rebuild_response(
    operation: PermissionRebuildOperation,
) -> PermissionRebuildOperationResponse:
    return PermissionRebuildOperationResponse(
        id=operation.id,
        tenant_id=operation.tenant_id,
        space_id=operation.space_id,
        root_node_id=operation.root_node_id,
        scope=cast(PermissionRebuildScope, operation.scope),
        permission_version=operation.permission_version,
        status=operation.status,  # type: ignore[arg-type]
        total_count=operation.total_count,
        processed_count=operation.processed_count,
        indexed_count=operation.indexed_count,
        attempt_count=operation.attempt_count,
        restart_requested=operation.restart_requested,
        error_code=operation.error_code,
        requested_by=operation.requested_by,
        created_at=operation.created_at,
        updated_at=operation.updated_at,
        completed_at=operation.completed_at,
    )


def _tree_operation_response(operation: FileTreeOperation) -> AdminTreeOperationResponse:
    return AdminTreeOperationResponse(
        id=operation.id,
        user_id=operation.user_id,
        space_id=operation.space_id,
        node_id=operation.node_id,
        operation=operation.operation,  # type: ignore[arg-type]
        status=operation.status,  # type: ignore[arg-type]
        total_count=operation.total_count,
        processed_count=operation.processed_count,
        released_bytes=operation.released_bytes,
        attempt_count=operation.attempt_count,
        error_code=operation.error_code,
        created_at=operation.created_at,
        updated_at=operation.updated_at,
        completed_at=operation.completed_at,
    )


def _next_cursor(
    settings: Settings,
    *,
    records: Sequence[PermissionRebuildOperation | AdminJob | FileTreeOperation],
    page: Sequence[PermissionRebuildOperation | AdminJob | FileTreeOperation],
    page_size: int,
) -> str | None:
    if len(records) <= page_size or not page:
        return None
    last = page[-1]
    return encode_page_cursor(
        settings,
        created_at=last.created_at,
        item_id=last.id,
    )


def _as_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default
