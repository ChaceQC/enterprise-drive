from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import build_audit_context, get_current_user, get_storage_adapter
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.infrastructure.storage.base import StorageAdapter
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.repository import FileRepository
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

router = APIRouter()


def get_upload_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[StorageAdapter, Depends(get_storage_adapter)],
) -> UploadService:
    return UploadService(
        repository=UploadRepository(session),
        file_repository=FileRepository(session),
        space_repository=SpaceRepository(session),
        storage=storage,
        settings=settings,
        audit_service=AuditService(repository=AuditRepository(session)),
    )


def get_upload_lifecycle_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[StorageAdapter, Depends(get_storage_adapter)],
) -> UploadLifecycleService:
    return UploadLifecycleService(
        repository=UploadRepository(session),
        file_repository=FileRepository(session),
        space_repository=SpaceRepository(session),
        storage=storage,
        audit_service=AuditService(repository=AuditRepository(session)),
    )


@router.post("/init", response_model=InitUploadResponse, status_code=status.HTTP_201_CREATED)
async def init_upload(
    http_request: Request,
    request: InitUploadRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[UploadService, Depends(get_upload_service)],
) -> InitUploadResponse:
    return await service.init_upload(
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
    service: Annotated[UploadService, Depends(get_upload_service)],
) -> UploadPartUrlResponse:
    return await service.presign_upload_part(
        current_user=current_user,
        session_id=session_id,
        part_no=part_no,
    )


@router.post("/{session_id}/complete", response_model=CompleteUploadResponse)
async def complete_upload(
    http_request: Request,
    session_id: UUID,
    request: CompleteUploadRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[UploadLifecycleService, Depends(get_upload_lifecycle_service)],
) -> CompleteUploadResponse:
    return await service.complete_upload(
        current_user=current_user,
        session_id=session_id,
        parts=request.parts,
        audit_context=build_audit_context(http_request),
    )


@router.post("/{session_id}/abort", response_model=AbortUploadResponse)
async def abort_upload(
    http_request: Request,
    session_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[UploadLifecycleService, Depends(get_upload_lifecycle_service)],
) -> AbortUploadResponse:
    return await service.abort_upload(
        current_user=current_user,
        session_id=session_id,
        audit_context=build_audit_context(http_request),
    )
