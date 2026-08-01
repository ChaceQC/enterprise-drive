from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    build_audit_context,
    enforce_rate_limit,
    ensure_supported_transfer_protocol,
    get_current_user,
    get_rate_limiter,
    get_storage_adapter,
)
from app.api.errors import ApiError
from app.core.config import Settings, get_settings
from app.core.metrics import record_upload_failure, record_upload_session
from app.db.session import get_db_session
from app.infrastructure.rate_limit.base import RateLimiter
from app.infrastructure.storage.base import StorageAdapter
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.repository import FileRepository
from app.modules.org.repository import OrgRepository
from app.modules.org.service import OrgService
from app.modules.permission.repository import PermissionRepository
from app.modules.permission.service import PermissionService
from app.modules.quota.repository import QuotaRepository
from app.modules.quota.service import QuotaService
from app.modules.space.repository import SpaceRepository
from app.modules.upload.lifecycle import UploadLifecycleService
from app.modules.upload.repository import UploadRepository
from app.modules.upload.schemas import (
    AbortUploadResponse,
    CompleteUploadRequest,
    CompleteUploadResponse,
    InitUploadRequest,
    InitUploadResponse,
    UploadPartUrlResponse,
    UploadSessionStatusResponse,
)
from app.modules.upload.service import UploadService
from app.modules.upload.timing import UploadCompleteTimings

router = APIRouter(dependencies=[Depends(ensure_supported_transfer_protocol)])


def get_upload_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[StorageAdapter, Depends(get_storage_adapter)],
) -> UploadService:
    permission_repository = PermissionRepository(session)
    org_service = OrgService(repository=OrgRepository(session))
    return UploadService(
        repository=UploadRepository(session),
        file_repository=FileRepository(session),
        space_repository=SpaceRepository(session),
        permission_service=PermissionService(
            repository=permission_repository,
            org_service=org_service,
        ),
        quota_service=QuotaService(
            repository=QuotaRepository(session),
            default_space_limit_bytes=settings.default_space_quota_bytes,
            default_user_limit_bytes=settings.default_user_quota_bytes,
            default_tenant_limit_bytes=settings.default_tenant_quota_bytes,
            policy_enabled=settings.quota_policy_enabled,
        ),
        storage=storage,
        settings=settings,
        audit_service=AuditService(repository=AuditRepository(session)),
    )


def get_upload_lifecycle_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[StorageAdapter, Depends(get_storage_adapter)],
) -> UploadLifecycleService:
    permission_repository = PermissionRepository(session)
    org_service = OrgService(repository=OrgRepository(session))
    return UploadLifecycleService(
        repository=UploadRepository(session),
        file_repository=FileRepository(session),
        space_repository=SpaceRepository(session),
        permission_service=PermissionService(
            repository=permission_repository,
            org_service=org_service,
        ),
        quota_service=QuotaService(
            repository=QuotaRepository(session),
            default_space_limit_bytes=settings.default_space_quota_bytes,
            default_user_limit_bytes=settings.default_user_quota_bytes,
            default_tenant_limit_bytes=settings.default_tenant_quota_bytes,
            policy_enabled=settings.quota_policy_enabled,
        ),
        storage=storage,
        audit_service=AuditService(repository=AuditRepository(session)),
    )


@router.post("/init", response_model=InitUploadResponse, status_code=status.HTTP_201_CREATED)
async def init_upload(
    http_request: Request,
    request: InitUploadRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    service: Annotated[UploadService, Depends(get_upload_service)],
) -> InitUploadResponse:
    try:
        await enforce_rate_limit(
            settings=settings,
            rate_limiter=rate_limiter,
            current_user=current_user,
            action="upload.init",
        )
        response = await service.init_upload(
            current_user=current_user,
            space_id=request.space_id,
            parent_id=request.parent_id,
            file_name=request.file_name,
            size_bytes=request.size_bytes,
            content_hash=request.content_hash,
            hash_algo=request.hash_algo,
            mime_type=request.mime_type,
            audit_context=build_audit_context(http_request),
        )
    except ApiError as exc:
        record_upload_failure(stage="init", reason=exc.code)
        raise
    except Exception:
        record_upload_failure(stage="init", reason="internal_error")
        raise
    record_upload_session(mode=response.mode, outcome="created")
    return response


@router.get("/{session_id}", response_model=UploadSessionStatusResponse)
async def get_upload_status(
    session_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[UploadService, Depends(get_upload_service)],
) -> UploadSessionStatusResponse:
    return await service.get_upload_status(
        current_user=current_user,
        session_id=session_id,
    )


@router.post("/{session_id}/parts/{part_no}/presign", response_model=UploadPartUrlResponse)
async def presign_upload_part(
    session_id: UUID,
    part_no: Annotated[int, Path(ge=1)],
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    service: Annotated[UploadService, Depends(get_upload_service)],
) -> UploadPartUrlResponse:
    try:
        await enforce_rate_limit(
            settings=settings,
            rate_limiter=rate_limiter,
            current_user=current_user,
            action="upload.part_presign",
            resource_key=f"session:{session_id}",
        )
        return await service.presign_upload_part(
            current_user=current_user,
            session_id=session_id,
            part_no=part_no,
        )
    except ApiError as exc:
        record_upload_failure(stage="part_presign", reason=exc.code)
        raise
    except Exception:
        record_upload_failure(stage="part_presign", reason="internal_error")
        raise


@router.post("/{session_id}/complete", response_model=CompleteUploadResponse)
async def complete_upload(
    http_request: Request,
    http_response: Response,
    session_id: UUID,
    request: CompleteUploadRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[UploadLifecycleService, Depends(get_upload_lifecycle_service)],
) -> CompleteUploadResponse:
    timings = (
        UploadCompleteTimings()
        if settings.environment != "production"
        and http_request.headers.get("X-Drive-Benchmark") == "BE-029"
        else None
    )
    try:
        result = await service.complete_upload(
            current_user=current_user,
            session_id=session_id,
            parts=request.parts,
            audit_context=build_audit_context(http_request),
            timings=timings,
        )
    except ApiError as exc:
        record_upload_failure(stage="complete", reason=exc.code)
        raise
    except Exception:
        record_upload_failure(stage="complete", reason="internal_error")
        raise
    if timings is not None:
        http_response.headers["Server-Timing"] = timings.server_timing_header()
    record_upload_session(mode="multipart", outcome="completed")
    return result


@router.post("/{session_id}/abort", response_model=AbortUploadResponse)
async def abort_upload(
    http_request: Request,
    session_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[UploadLifecycleService, Depends(get_upload_lifecycle_service)],
) -> AbortUploadResponse:
    try:
        response = await service.abort_upload(
            current_user=current_user,
            session_id=session_id,
            audit_context=build_audit_context(http_request),
        )
    except ApiError as exc:
        record_upload_failure(stage="abort", reason=exc.code)
        raise
    except Exception:
        record_upload_failure(stage="abort", reason="internal_error")
        raise
    record_upload_session(mode="multipart", outcome="aborted")
    return response
