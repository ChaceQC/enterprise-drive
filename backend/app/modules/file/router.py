from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import build_audit_context, get_current_user, get_storage_adapter
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.infrastructure.storage.base import StorageAdapter
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.download import FileDownloadService
from app.modules.file.repository import FileRepository
from app.modules.file.schemas import (
    CreateFolderRequest,
    DeleteNodeResponse,
    FileDownloadUrlResponse,
    FileListResponse,
    FileNodeResponse,
    MoveNodeRequest,
    RenameNodeRequest,
    RestoreNodeRequest,
)
from app.modules.file.service import FileService
from app.modules.space.repository import SpaceRepository

router = APIRouter()


def get_file_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileService:
    return FileService(
        repository=FileRepository(session),
        space_repository=SpaceRepository(session),
        settings=settings,
        audit_service=AuditService(repository=AuditRepository(session)),
    )


def get_file_download_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[StorageAdapter, Depends(get_storage_adapter)],
) -> FileDownloadService:
    return FileDownloadService(
        repository=FileRepository(session),
        space_repository=SpaceRepository(session),
        storage=storage,
        settings=settings,
        audit_service=AuditService(repository=AuditRepository(session)),
    )


@router.post("/folders", response_model=FileNodeResponse, status_code=status.HTTP_201_CREATED)
async def create_folder(
    http_request: Request,
    request: CreateFolderRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileNodeResponse:
    return await service.create_folder(
        current_user=current_user,
        space_id=request.space_id,
        parent_id=request.parent_id,
        name=request.name,
        audit_context=build_audit_context(http_request),
    )


@router.get("", response_model=FileListResponse)
async def list_files(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileService, Depends(get_file_service)],
    space_id: Annotated[UUID, Query()],
    parent_id: Annotated[UUID | None, Query()] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> FileListResponse:
    return await service.list_children(
        current_user=current_user,
        space_id=space_id,
        parent_id=parent_id,
        cursor=cursor,
        page_size=page_size,
    )


@router.patch("/{node_id}", response_model=FileNodeResponse)
async def rename_node(
    http_request: Request,
    node_id: UUID,
    request: RenameNodeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileNodeResponse:
    return await service.rename_node(
        current_user=current_user,
        node_id=node_id,
        name=request.name,
        audit_context=build_audit_context(http_request),
    )


@router.post("/{node_id}/move", response_model=FileNodeResponse)
async def move_node(
    http_request: Request,
    node_id: UUID,
    request: MoveNodeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileNodeResponse:
    return await service.move_node(
        current_user=current_user,
        node_id=node_id,
        target_parent_id=request.target_parent_id,
        new_name=request.new_name,
        audit_context=build_audit_context(http_request),
    )


@router.delete("/{node_id}", response_model=DeleteNodeResponse)
async def delete_node(
    http_request: Request,
    node_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> DeleteNodeResponse:
    return await service.delete_node(
        current_user=current_user,
        node_id=node_id,
        audit_context=build_audit_context(http_request),
    )


@router.get("/{node_id}/download", response_model=FileDownloadUrlResponse)
async def create_download_url(
    http_request: Request,
    node_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileDownloadService, Depends(get_file_download_service)],
) -> FileDownloadUrlResponse:
    return await service.create_download_url(
        current_user=current_user,
        node_id=node_id,
        audit_context=build_audit_context(http_request),
    )


@router.post("/{node_id}/restore", response_model=FileNodeResponse)
async def restore_node(
    http_request: Request,
    node_id: UUID,
    request: RestoreNodeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileNodeResponse:
    return await service.restore_node(
        current_user=current_user,
        node_id=node_id,
        target_parent_id=request.target_parent_id,
        new_name=request.new_name,
        audit_context=build_audit_context(http_request),
    )
