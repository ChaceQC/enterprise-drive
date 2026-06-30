from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import build_audit_context, get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.repository import FileRepository
from app.modules.file.schemas import CreateFolderRequest, FileListResponse, FileNodeResponse
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
