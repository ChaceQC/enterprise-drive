from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import build_audit_context, get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.repository import FileRepository
from app.modules.permission.repository import PermissionRepository
from app.modules.quota.repository import QuotaRepository
from app.modules.quota.service import QuotaService
from app.modules.space.repository import SpaceRepository
from app.modules.space.schemas import CreateSpaceRequest, CreateSpaceResponse, SpaceListResponse
from app.modules.space.service import SpaceService

router = APIRouter()


def get_space_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SpaceService:
    return SpaceService(
        repository=SpaceRepository(session),
        file_repository=FileRepository(session),
        permission_repository=PermissionRepository(session),
        quota_service=QuotaService(
            repository=QuotaRepository(session),
            default_space_limit_bytes=settings.default_space_quota_bytes,
        ),
        settings=settings,
        audit_service=AuditService(repository=AuditRepository(session)),
    )


@router.post("", response_model=CreateSpaceResponse, status_code=status.HTTP_201_CREATED)
async def create_space(
    http_request: Request,
    request: CreateSpaceRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SpaceService, Depends(get_space_service)],
) -> CreateSpaceResponse:
    return await service.create_space(
        current_user=current_user,
        slug=request.slug,
        name=request.name,
        space_type=request.space_type,
        audit_context=build_audit_context(http_request),
    )


@router.get("", response_model=SpaceListResponse)
async def list_spaces(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SpaceService, Depends(get_space_service)],
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SpaceListResponse:
    return await service.list_spaces(
        current_user=current_user,
        cursor=cursor,
        page_size=page_size,
    )
