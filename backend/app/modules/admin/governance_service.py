from __future__ import annotations

from datetime import UTC, datetime
from typing import NoReturn
from uuid import UUID

from celery import Celery  # type: ignore[import-untyped]

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.maintenance_health import (
    MAINTENANCE_TASK_INTERVAL_SECONDS,
    expected_interval_seconds,
    is_task_stale,
    load_maintenance_task_health,
)
from app.core.pagination import decode_page_cursor, encode_page_cursor
from app.infrastructure.storage.base import StorageAdapter
from app.modules.admin.governance_repository import AdminGovernanceRepository
from app.modules.admin.governance_schemas import (
    AdminExportCreateRequest,
    AdminExportDownloadResponse,
    AdminJobListResponse,
    AdminJobResponse,
    AdminMaintenanceOverviewResponse,
    AdminMaintenanceRunRequest,
    AdminMaintenanceTaskHealthResponse,
    AdminOverviewStatsResponse,
)
from app.modules.admin.job_repository import AdminJobRepository
from app.modules.admin.models import AdminJob
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User


class AdminGovernanceService:
    def __init__(
        self,
        *,
        repository: AdminGovernanceRepository,
        job_repository: AdminJobRepository,
        audit_service: AuditService,
        celery_app: Celery,
        storage: StorageAdapter,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.job_repository = job_repository
        self.audit_service = audit_service
        self.celery_app = celery_app
        self.storage = storage
        self.settings = settings

    async def get_overview_stats(
        self,
        *,
        current_user: User,
        audit_context: AuditContext | None,
    ) -> AdminOverviewStatsResponse:
        await self._require_admin(
            current_user=current_user,
            action="admin.stats.queried",
            resource_type="statistics",
            resource_id=None,
            audit_context=audit_context,
        )
        values = await self.repository.overview_stats(tenant_id=current_user.tenant_id)
        await self._record(
            current_user=current_user,
            action="admin.stats.queried",
            resource_type="statistics",
            resource_id=None,
            result="allowed",
            audit_context=audit_context,
            metadata={"scope": "overview"},
        )
        await self.job_repository.commit()
        return AdminOverviewStatsResponse(
            generated_at=datetime.now(UTC),
            **values,
        )

    async def get_maintenance_overview(
        self,
        *,
        current_user: User,
        audit_context: AuditContext | None,
    ) -> AdminMaintenanceOverviewResponse:
        await self._require_admin(
            current_user=current_user,
            action="admin.maintenance.queried",
            resource_type="maintenance",
            resource_id=None,
            audit_context=audit_context,
        )
        tasks = [
            AdminMaintenanceTaskHealthResponse(
                task_name=health.task_name,  # type: ignore[arg-type]
                expected_interval_seconds=expected_interval_seconds(
                    settings=self.settings,
                    task_name=health.task_name,
                ),
                consecutive_failures=health.consecutive_failures,
                alert_active=health.alert_active,
                stale=is_task_stale(settings=self.settings, health=health),
                last_status=health.last_status,
                last_finished_at=_timestamp(health.last_finished_at),
                last_success_at=_timestamp(health.last_success_at),
                last_failure_at=_timestamp(health.last_failure_at),
            )
            for health in load_maintenance_task_health(settings=self.settings)
        ]
        await self._record(
            current_user=current_user,
            action="admin.maintenance.queried",
            resource_type="maintenance",
            resource_id=None,
            result="allowed",
            audit_context=audit_context,
            metadata={"task_count": len(tasks)},
        )
        await self.job_repository.commit()
        return AdminMaintenanceOverviewResponse(
            generated_at=datetime.now(UTC),
            tasks=tasks,
        )

    async def create_maintenance_run(
        self,
        *,
        current_user: User,
        request: AdminMaintenanceRunRequest,
        audit_context: AuditContext | None,
    ) -> AdminJobResponse:
        action = "admin.maintenance_run.created"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="maintenance_run",
            resource_id=None,
            audit_context=audit_context,
        )
        _validate_maintenance_request(request)
        parameters = _maintenance_parameters(
            request=request,
            tenant_id=current_user.tenant_id,
            request_id=(audit_context.request_id if audit_context else None),
        )
        job = await self.job_repository.create_job(
            tenant_id=current_user.tenant_id,
            kind="maintenance",
            operation=request.task_name,
            created_by=current_user.id,
            parameters=parameters,
        )
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="maintenance_run",
            resource_id=job.id,
            result="allowed",
            audit_context=audit_context,
            metadata={"task_name": request.task_name, "parameters": parameters},
        )
        await self.job_repository.commit()
        await self._enqueue_job(
            current_user=current_user,
            job=job,
            task_name="admin.execute_maintenance_run",
            action=action,
            audit_context=audit_context,
        )
        return _job_response(job)

    async def list_maintenance_runs(
        self,
        *,
        current_user: User,
        status: str | None,
        task_name: str | None,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext | None,
    ) -> AdminJobListResponse:
        return await self._list_jobs(
            current_user=current_user,
            kind="maintenance",
            status=status,
            operation=task_name,
            cursor=cursor,
            page_size=page_size,
            action="admin.maintenance_runs.queried",
            audit_context=audit_context,
        )

    async def get_maintenance_run(
        self,
        *,
        current_user: User,
        run_id: UUID,
        audit_context: AuditContext | None,
    ) -> AdminJobResponse:
        return await self._get_job(
            current_user=current_user,
            job_id=run_id,
            kind="maintenance",
            action="admin.maintenance_run.viewed",
            audit_context=audit_context,
        )

    async def create_export(
        self,
        *,
        current_user: User,
        request: AdminExportCreateRequest,
        audit_context: AuditContext | None,
    ) -> AdminJobResponse:
        action = "admin.export.created"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="export",
            resource_id=None,
            audit_context=audit_context,
        )
        filters = _validate_export_filters(resource=request.resource, filters=request.filters)
        job = await self.job_repository.create_job(
            tenant_id=current_user.tenant_id,
            kind="export",
            operation=request.resource,
            created_by=current_user.id,
            parameters={"filters": filters},
        )
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="export",
            resource_id=job.id,
            result="allowed",
            audit_context=audit_context,
            metadata={"resource": request.resource, "filters": filters},
        )
        await self.job_repository.commit()
        await self._enqueue_job(
            current_user=current_user,
            job=job,
            task_name="admin.generate_export",
            action=action,
            audit_context=audit_context,
        )
        return _job_response(job)

    async def _enqueue_job(
        self,
        *,
        current_user: User,
        job: AdminJob,
        task_name: str,
        action: str,
        audit_context: AuditContext | None,
    ) -> None:
        try:
            async_result = self.celery_app.send_task(
                task_name,
                kwargs={"job_id": str(job.id)},
                queue="maintenance",
            )
            job.celery_task_id = str(async_result.id)
            job.version += 1
            await self.job_repository.commit()
        except Exception as exc:
            job.status = "failed"
            job.error_code = "ADMIN_JOB_ENQUEUE_FAILED"
            job.error_message = type(exc).__name__
            job.completed_at = datetime.now(UTC)
            job.version += 1
            await self._record(
                current_user=current_user,
                action=f"{action}.enqueue_failed",
                resource_type=f"{job.kind}_job",
                resource_id=job.id,
                result="denied",
                audit_context=audit_context,
                metadata={"reason": "queue_unavailable"},
            )
            await self.job_repository.commit()
            raise ApiError(
                "ADMIN_JOB_QUEUE_UNAVAILABLE",
                "管理任务队列暂不可用",
                status_code=503,
            ) from exc

    async def list_exports(
        self,
        *,
        current_user: User,
        status: str | None,
        resource: str | None,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext | None,
    ) -> AdminJobListResponse:
        return await self._list_jobs(
            current_user=current_user,
            kind="export",
            status=status,
            operation=resource,
            cursor=cursor,
            page_size=page_size,
            action="admin.exports.queried",
            audit_context=audit_context,
        )

    async def get_export(
        self,
        *,
        current_user: User,
        export_id: UUID,
        audit_context: AuditContext | None,
    ) -> AdminJobResponse:
        return await self._get_job(
            current_user=current_user,
            job_id=export_id,
            kind="export",
            action="admin.export.viewed",
            audit_context=audit_context,
        )

    async def get_export_download(
        self,
        *,
        current_user: User,
        export_id: UUID,
        audit_context: AuditContext | None,
    ) -> AdminExportDownloadResponse:
        action = "admin.export.downloaded"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type="export",
            resource_id=export_id,
            audit_context=audit_context,
        )
        job = await self._load_job_or_deny(
            current_user=current_user,
            job_id=export_id,
            kind="export",
            action=action,
            audit_context=audit_context,
        )
        if (
            job.status != "succeeded"
            or job.storage_bucket is None
            or job.storage_key is None
            or job.file_name is None
            or job.content_type is None
            or job.size_bytes is None
        ):
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="export",
                resource_id=export_id,
                code="ADMIN_EXPORT_NOT_READY",
                message="导出任务尚未生成可下载文件",
                status_code=409,
                audit_context=audit_context,
                metadata={"status": job.status, "reason": "export_not_ready"},
            )
        download = await self.storage.presign_download(
            bucket=job.storage_bucket,
            storage_key=job.storage_key,
            filename=job.file_name,
            expires_in_seconds=self.settings.admin_export_presign_expires_seconds,
        )
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="export",
            resource_id=job.id,
            result="allowed",
            audit_context=audit_context,
            metadata={"size_bytes": job.size_bytes},
        )
        await self.job_repository.commit()
        return AdminExportDownloadResponse(
            job_id=job.id,
            file_name=job.file_name,
            content_type=job.content_type,
            size_bytes=job.size_bytes,
            download_url=download.download_url,
            expires_at=download.expires_at,
        )

    async def _list_jobs(
        self,
        *,
        current_user: User,
        kind: str,
        status: str | None,
        operation: str | None,
        cursor: str | None,
        page_size: int,
        action: str,
        audit_context: AuditContext | None,
    ) -> AdminJobListResponse:
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type=f"{kind}_job",
            resource_id=None,
            audit_context=audit_context,
        )
        decoded_cursor = decode_page_cursor(self.settings, cursor)
        jobs = await self.job_repository.list_jobs(
            tenant_id=current_user.tenant_id,
            kind=kind,
            status=status,
            operation=operation,
            cursor=decoded_cursor,
            limit=page_size + 1,
        )
        page = jobs[:page_size]
        next_cursor = None
        if len(jobs) > page_size and page:
            next_cursor = encode_page_cursor(
                self.settings,
                created_at=page[-1].created_at,
                item_id=page[-1].id,
            )
        await self._record(
            current_user=current_user,
            action=action,
            resource_type=f"{kind}_job",
            resource_id=None,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "status": status,
                "operation": operation,
                "returned_count": len(page),
                "has_next": next_cursor is not None,
            },
        )
        await self.job_repository.commit()
        return AdminJobListResponse(
            items=[_job_response(job) for job in page],
            next_cursor=next_cursor,
        )

    async def _get_job(
        self,
        *,
        current_user: User,
        job_id: UUID,
        kind: str,
        action: str,
        audit_context: AuditContext | None,
    ) -> AdminJobResponse:
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_type=f"{kind}_job",
            resource_id=job_id,
            audit_context=audit_context,
        )
        job = await self._load_job_or_deny(
            current_user=current_user,
            job_id=job_id,
            kind=kind,
            action=action,
            audit_context=audit_context,
        )
        await self._record(
            current_user=current_user,
            action=action,
            resource_type=f"{kind}_job",
            resource_id=job.id,
            result="allowed",
            audit_context=audit_context,
            metadata={"status": job.status},
        )
        await self.job_repository.commit()
        return _job_response(job)

    async def _load_job_or_deny(
        self,
        *,
        current_user: User,
        job_id: UUID,
        kind: str,
        action: str,
        audit_context: AuditContext | None,
    ) -> AdminJob:
        job = await self.job_repository.get_job(
            tenant_id=current_user.tenant_id,
            job_id=job_id,
            kind=kind,
        )
        if job is None:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type=f"{kind}_job",
                resource_id=job_id,
                code="ADMIN_JOB_NOT_FOUND",
                message="管理任务不存在",
                status_code=404,
                audit_context=audit_context,
                metadata={"reason": "job_not_found"},
            )
        return job

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
        await self.job_repository.commit()
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
                risk_level="high",
                metadata=metadata,
            ),
            context=audit_context or AuditContext(),
        )


def _job_response(job: AdminJob) -> AdminJobResponse:
    return AdminJobResponse(
        id=job.id,
        tenant_id=job.tenant_id,
        kind=job.kind,  # type: ignore[arg-type]
        operation=job.operation,
        status=job.status,  # type: ignore[arg-type]
        created_by=job.created_by,
        parameters=dict(job.parameters_json),
        result=dict(job.result_json),
        file_name=job.file_name,
        content_type=job.content_type,
        size_bytes=job.size_bytes,
        error_code=job.error_code,
        error_message=job.error_message,
        version=job.version,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def _timestamp(value: float) -> datetime | None:
    return datetime.fromtimestamp(value, tz=UTC) if value > 0 else None


def _maintenance_parameters(
    *,
    request: AdminMaintenanceRunRequest,
    tenant_id: UUID,
    request_id: str | None,
) -> dict[str, object]:
    parameters: dict[str, object] = {
        "tenant_id": str(tenant_id),
        "limit": request.limit,
        "request_id": request_id,
    }
    if request.task_name == "file.cleanup_orphaned_objects":
        parameters.update({"dry_run": request.dry_run, "scan_all": request.scan_all})
    elif request.task_name == "preview.cleanup_artifacts":
        parameters.update(
            {
                "dry_run": request.dry_run,
                "scan_all": request.scan_all,
                "retention_days": request.retention_days,
            }
        )
    elif request.task_name == "quota.reconcile_space_usage":
        parameters.update({"repair": request.repair, "scan_all": request.scan_all})
    elif request.task_name == "file.cleanup_expired_trash":
        parameters["retention_days"] = request.retention_days
    elif request.task_name == "file.process_tree_operations":
        parameters.pop("request_id")
    return {key: value for key, value in parameters.items() if value is not None}


_EXPORT_FILTERS: dict[str, dict[str, type[object]]] = {
    "audit_logs": {
        "action": str,
        "result": str,
        "risk_level": str,
        "created_from": str,
        "created_to": str,
    },
    "spaces": {
        "is_active": bool,
        "space_type": str,
    },
    "users": {
        "is_active": bool,
        "is_super_admin": bool,
    },
}


def _validate_export_filters(*, resource: str, filters: dict[str, object]) -> dict[str, object]:
    allowed = _EXPORT_FILTERS[resource]
    unknown = sorted(set(filters) - set(allowed))
    if unknown:
        raise ApiError(
            "ADMIN_EXPORT_FILTER_INVALID",
            "导出筛选条件不合法",
            status_code=422,
            details={"unknown_filters": unknown},
        )
    normalized: dict[str, object] = {}
    for key, value in filters.items():
        if not isinstance(value, allowed[key]):
            raise ApiError(
                "ADMIN_EXPORT_FILTER_INVALID",
                "导出筛选条件类型不合法",
                status_code=422,
                details={"filter": key},
            )
        if key in {"created_from", "created_to"}:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError as exc:
                raise ApiError(
                    "ADMIN_EXPORT_FILTER_INVALID",
                    "导出时间筛选条件不合法",
                    status_code=422,
                    details={"filter": key},
                ) from exc
            if parsed.tzinfo is None:
                raise ApiError(
                    "ADMIN_EXPORT_FILTER_INVALID",
                    "导出时间筛选条件必须包含时区",
                    status_code=422,
                    details={"filter": key},
                )
            normalized[key] = parsed.astimezone(UTC).isoformat()
        else:
            normalized[key] = value
    if resource == "spaces":
        space_type = normalized.get("space_type")
        if isinstance(space_type, str) and space_type not in {"team", "personal"}:
            raise ApiError(
                "ADMIN_EXPORT_FILTER_INVALID",
                "导出空间类型筛选条件不合法",
                status_code=422,
                details={"filter": "space_type"},
            )
    created_from = normalized.get("created_from")
    created_to = normalized.get("created_to")
    if (
        isinstance(created_from, str)
        and isinstance(created_to, str)
        and datetime.fromisoformat(created_from) > datetime.fromisoformat(created_to)
    ):
        raise ApiError(
            "ADMIN_EXPORT_FILTER_INVALID",
            "导出开始时间不能晚于结束时间",
            status_code=422,
            details={"filter": "created_from"},
        )
    return normalized


_DRY_RUN_TASKS = frozenset(
    {
        "file.cleanup_orphaned_objects",
        "preview.cleanup_artifacts",
        "quota.reconcile_space_usage",
    }
)


def _validate_maintenance_request(request: AdminMaintenanceRunRequest) -> None:
    if request.task_name not in MAINTENANCE_TASK_INTERVAL_SECONDS:
        raise ApiError(
            "ADMIN_MAINTENANCE_TASK_INVALID",
            "维护任务不受管理接口支持",
            status_code=422,
        )
    if request.task_name not in _DRY_RUN_TASKS and request.dry_run:
        raise ApiError(
            "ADMIN_MAINTENANCE_CONFIRMATION_REQUIRED",
            "该维护任务会修改数据，必须显式设置 dry_run=false",
            status_code=422,
        )
    if request.task_name != "quota.reconcile_space_usage" and request.repair:
        raise ApiError(
            "ADMIN_MAINTENANCE_OPTION_INVALID",
            "repair 仅适用于容量校准任务",
            status_code=422,
        )
    if request.retention_days is not None and request.task_name not in {
        "file.cleanup_expired_trash",
        "preview.cleanup_artifacts",
    }:
        raise ApiError(
            "ADMIN_MAINTENANCE_OPTION_INVALID",
            "retention_days 仅适用于回收站或预览产物清理任务",
            status_code=422,
        )
    if not request.scan_all and request.task_name not in {
        "file.cleanup_orphaned_objects",
        "preview.cleanup_artifacts",
        "quota.reconcile_space_usage",
    }:
        raise ApiError(
            "ADMIN_MAINTENANCE_OPTION_INVALID",
            "scan_all 仅适用于支持游标扫描的维护任务",
            status_code=422,
        )
    if request.task_name == "quota.reconcile_space_usage" and request.dry_run == request.repair:
        raise ApiError(
            "ADMIN_MAINTENANCE_OPTION_INVALID",
            "容量校准必须使用 dry_run=true/repair=false 或 dry_run=false/repair=true",
            status_code=422,
        )
