from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from celery import Celery  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    build_audit_context,
    get_current_user,
    get_storage_adapter,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.infrastructure.storage.base import StorageAdapter
from app.modules.admin.governance_repository import AdminGovernanceRepository
from app.modules.admin.governance_schemas import (
    AdminExportCreateRequest,
    AdminExportDownloadResponse,
    AdminExportResource,
    AdminJobListResponse,
    AdminJobResponse,
    AdminJobStatus,
    AdminMaintenanceOperation,
    AdminMaintenanceOverviewResponse,
    AdminMaintenanceRunRequest,
    AdminOverviewStatsResponse,
)
from app.modules.admin.governance_service import AdminGovernanceService
from app.modules.admin.job_repository import AdminJobRepository
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User

router = APIRouter()


@lru_cache
def _admin_task_client(*, broker_url: str, result_backend: str) -> Celery:
    return Celery(
        "enterprise_drive_admin_client",
        broker=broker_url,
        backend=result_backend,
    )


def get_admin_governance_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[StorageAdapter, Depends(get_storage_adapter)],
) -> AdminGovernanceService:
    return AdminGovernanceService(
        repository=AdminGovernanceRepository(session),
        job_repository=AdminJobRepository(session),
        audit_service=AuditService(repository=AuditRepository(session)),
        celery_app=_admin_task_client(
            broker_url=settings.celery_broker_url,
            result_backend=settings.celery_result_backend,
        ),
        storage=storage,
        settings=settings,
    )


@router.get("/stats/overview", response_model=AdminOverviewStatsResponse)
async def get_admin_overview_stats(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminGovernanceService, Depends(get_admin_governance_service)],
) -> AdminOverviewStatsResponse:
    return await service.get_overview_stats(
        current_user=current_user,
        audit_context=build_audit_context(http_request),
    )


@router.get("/maintenance/tasks", response_model=AdminMaintenanceOverviewResponse)
async def get_admin_maintenance_tasks(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminGovernanceService, Depends(get_admin_governance_service)],
) -> AdminMaintenanceOverviewResponse:
    return await service.get_maintenance_overview(
        current_user=current_user,
        audit_context=build_audit_context(http_request),
    )


@router.post(
    "/maintenance/runs",
    response_model=AdminJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_admin_maintenance_run(
    http_request: Request,
    request: AdminMaintenanceRunRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminGovernanceService, Depends(get_admin_governance_service)],
) -> AdminJobResponse:
    return await service.create_maintenance_run(
        current_user=current_user,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.get("/maintenance/runs", response_model=AdminJobListResponse)
async def list_admin_maintenance_runs(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminGovernanceService, Depends(get_admin_governance_service)],
    job_status: Annotated[AdminJobStatus | None, Query(alias="status")] = None,
    task_name: Annotated[AdminMaintenanceOperation | None, Query()] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminJobListResponse:
    return await service.list_maintenance_runs(
        current_user=current_user,
        status=job_status,
        task_name=task_name,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )


@router.get("/maintenance/runs/{run_id}", response_model=AdminJobResponse)
async def get_admin_maintenance_run(
    http_request: Request,
    run_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminGovernanceService, Depends(get_admin_governance_service)],
) -> AdminJobResponse:
    return await service.get_maintenance_run(
        current_user=current_user,
        run_id=run_id,
        audit_context=build_audit_context(http_request),
    )


@router.post(
    "/exports",
    response_model=AdminJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_admin_export(
    http_request: Request,
    request: AdminExportCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminGovernanceService, Depends(get_admin_governance_service)],
) -> AdminJobResponse:
    return await service.create_export(
        current_user=current_user,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.get("/exports", response_model=AdminJobListResponse)
async def list_admin_exports(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminGovernanceService, Depends(get_admin_governance_service)],
    job_status: Annotated[AdminJobStatus | None, Query(alias="status")] = None,
    resource: Annotated[AdminExportResource | None, Query()] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminJobListResponse:
    return await service.list_exports(
        current_user=current_user,
        status=job_status,
        resource=resource,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )


@router.get("/exports/{export_id}", response_model=AdminJobResponse)
async def get_admin_export(
    http_request: Request,
    export_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminGovernanceService, Depends(get_admin_governance_service)],
) -> AdminJobResponse:
    return await service.get_export(
        current_user=current_user,
        export_id=export_id,
        audit_context=build_audit_context(http_request),
    )


@router.get("/exports/{export_id}/download", response_model=AdminExportDownloadResponse)
async def get_admin_export_download(
    http_request: Request,
    export_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminGovernanceService, Depends(get_admin_governance_service)],
) -> AdminExportDownloadResponse:
    return await service.get_export_download(
        current_user=current_user,
        export_id=export_id,
        audit_context=build_audit_context(http_request),
    )
