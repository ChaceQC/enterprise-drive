from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal
from uuid import UUID

from celery import Celery  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import build_audit_context, get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.modules.admin.job_repository import AdminJobRepository
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.governance.repository import GovernanceRepository
from app.modules.governance.schemas import (
    AdminTreeOperationListResponse,
    GovernanceOverviewResponse,
    LifecyclePolicyResponse,
    LifecyclePolicyUpdateRequest,
    LifecycleRunCreateRequest,
    LifecycleRunListResponse,
    LifecycleRunResponse,
    PermissionRebuildCreateRequest,
    PermissionRebuildOperationListResponse,
    PermissionRebuildOperationResponse,
)
from app.modules.governance.service import GovernanceService

router = APIRouter()


@lru_cache
def _governance_task_client(*, broker_url: str, result_backend: str) -> Celery:
    return Celery(
        "enterprise_drive_governance_client",
        broker=broker_url,
        backend=result_backend,
    )


def get_governance_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GovernanceService:
    audit_repository = AuditRepository(session)
    return GovernanceService(
        repository=GovernanceRepository(session),
        job_repository=AdminJobRepository(session),
        audit_service=AuditService(repository=audit_repository),
        celery_app=_governance_task_client(
            broker_url=settings.celery_broker_url,
            result_backend=settings.celery_result_backend,
        ),
        settings=settings,
    )


@router.get("/overview", response_model=GovernanceOverviewResponse)
async def get_governance_overview(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
) -> GovernanceOverviewResponse:
    return await service.get_overview(
        current_user=current_user,
        audit_context=build_audit_context(http_request),
    )


@router.get("/lifecycle-policy", response_model=LifecyclePolicyResponse)
async def get_lifecycle_policy(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
) -> LifecyclePolicyResponse:
    return await service.get_lifecycle_policy(
        current_user=current_user,
        audit_context=build_audit_context(http_request),
    )


@router.patch("/lifecycle-policy", response_model=LifecyclePolicyResponse)
async def update_lifecycle_policy(
    http_request: Request,
    request: LifecyclePolicyUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
) -> LifecyclePolicyResponse:
    return await service.update_lifecycle_policy(
        current_user=current_user,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.post(
    "/lifecycle-runs",
    response_model=LifecycleRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_lifecycle_run(
    http_request: Request,
    request: LifecycleRunCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
) -> LifecycleRunResponse:
    return await service.create_lifecycle_run(
        current_user=current_user,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.get("/lifecycle-runs", response_model=LifecycleRunListResponse)
async def list_lifecycle_runs(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> LifecycleRunListResponse:
    return await service.list_lifecycle_runs(
        current_user=current_user,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )


@router.post(
    "/permission-rebuilds",
    response_model=PermissionRebuildOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_permission_rebuild(
    http_request: Request,
    request: PermissionRebuildCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
) -> PermissionRebuildOperationResponse:
    return await service.create_permission_rebuild(
        current_user=current_user,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.get(
    "/permission-rebuilds",
    response_model=PermissionRebuildOperationListResponse,
)
async def list_permission_rebuilds(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
    operation_status: Annotated[
        Literal["pending", "running", "completed", "failed"] | None,
        Query(alias="status"),
    ] = None,
    scope: Annotated[Literal["space", "node"] | None, Query()] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> PermissionRebuildOperationListResponse:
    return await service.list_permission_rebuilds(
        current_user=current_user,
        status=operation_status,
        scope=scope,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )


@router.get(
    "/permission-rebuilds/{operation_id}",
    response_model=PermissionRebuildOperationResponse,
)
async def get_permission_rebuild(
    http_request: Request,
    operation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
) -> PermissionRebuildOperationResponse:
    return await service.get_permission_rebuild(
        current_user=current_user,
        operation_id=operation_id,
        audit_context=build_audit_context(http_request),
    )


@router.post(
    "/permission-rebuilds/{operation_id}/retry",
    response_model=PermissionRebuildOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_permission_rebuild(
    http_request: Request,
    operation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
) -> PermissionRebuildOperationResponse:
    return await service.retry_permission_rebuild(
        current_user=current_user,
        operation_id=operation_id,
        audit_context=build_audit_context(http_request),
    )


@router.get("/tree-operations", response_model=AdminTreeOperationListResponse)
async def list_governance_tree_operations(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[GovernanceService, Depends(get_governance_service)],
    operation_status: Annotated[
        Literal["pending", "running", "completed", "failed"] | None,
        Query(alias="status"),
    ] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminTreeOperationListResponse:
    return await service.list_tree_operations(
        current_user=current_user,
        status=operation_status,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )
