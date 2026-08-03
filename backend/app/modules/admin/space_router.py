from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import build_audit_context, get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.modules.admin.space_repository import AdminSpaceRepository
from app.modules.admin.space_schemas import (
    AdminSpaceCreateRequest,
    AdminSpaceListResponse,
    AdminSpaceResponse,
    AdminSpaceType,
    AdminSpaceUpdateRequest,
)
from app.modules.admin.space_service import AdminSpaceService
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.repository import FileRepository
from app.modules.permission.repository import PermissionRepository
from app.modules.quota.repository import QuotaRepository
from app.modules.space.repository import SpaceRepository

router = APIRouter()


def get_admin_space_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AdminSpaceService:
    return AdminSpaceService(
        repository=AdminSpaceRepository(session),
        space_repository=SpaceRepository(session),
        file_repository=FileRepository(session),
        permission_repository=PermissionRepository(session),
        quota_repository=QuotaRepository(session),
        audit_service=AuditService(repository=AuditRepository(session)),
        settings=settings,
    )


@router.get("", response_model=AdminSpaceListResponse)
async def list_admin_spaces(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminSpaceService, Depends(get_admin_space_service)],
    is_active: Annotated[bool | None, Query()] = None,
    space_type: Annotated[AdminSpaceType | None, Query()] = None,
    owner_id: Annotated[UUID | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminSpaceListResponse:
    return await service.list_spaces(
        current_user=current_user,
        is_active=is_active,
        space_type=space_type,
        owner_id=owner_id,
        query=q,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )


@router.post("", response_model=AdminSpaceResponse, status_code=status.HTTP_201_CREATED)
async def create_admin_space(
    http_request: Request,
    request: AdminSpaceCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminSpaceService, Depends(get_admin_space_service)],
) -> AdminSpaceResponse:
    return await service.create_space(
        current_user=current_user,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.get("/{space_id}", response_model=AdminSpaceResponse)
async def get_admin_space(
    http_request: Request,
    space_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminSpaceService, Depends(get_admin_space_service)],
) -> AdminSpaceResponse:
    return await service.get_space(
        current_user=current_user,
        space_id=space_id,
        audit_context=build_audit_context(http_request),
    )


@router.patch("/{space_id}", response_model=AdminSpaceResponse)
async def update_admin_space(
    http_request: Request,
    space_id: UUID,
    request: AdminSpaceUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminSpaceService, Depends(get_admin_space_service)],
) -> AdminSpaceResponse:
    return await service.update_space(
        current_user=current_user,
        space_id=space_id,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.delete("/{space_id}", response_model=AdminSpaceResponse)
async def deactivate_admin_space(
    http_request: Request,
    space_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminSpaceService, Depends(get_admin_space_service)],
    expected_version: Annotated[int, Query(ge=1)],
) -> AdminSpaceResponse:
    return await service.deactivate_space(
        current_user=current_user,
        space_id=space_id,
        expected_version=expected_version,
        audit_context=build_audit_context(http_request),
    )
