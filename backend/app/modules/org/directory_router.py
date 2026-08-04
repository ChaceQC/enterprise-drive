from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.modules.auth.models import User
from app.modules.org.directory_schemas import (
    DirectoryDepartmentListResponse,
    DirectoryGroupListResponse,
    DirectoryUserListResponse,
)
from app.modules.org.directory_service import DirectoryService
from app.modules.org.repository import OrgRepository

router = APIRouter()


def get_directory_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DirectoryService:
    return DirectoryService(
        repository=OrgRepository(session),
        settings=settings,
    )


@router.get("/users", response_model=DirectoryUserListResponse)
async def list_directory_users(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DirectoryService, Depends(get_directory_service)],
    q: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DirectoryUserListResponse:
    return await service.list_users(
        tenant_id=current_user.tenant_id,
        query=q,
        cursor=cursor,
        page_size=page_size,
    )


@router.get("/departments", response_model=DirectoryDepartmentListResponse)
async def list_directory_departments(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DirectoryService, Depends(get_directory_service)],
    q: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DirectoryDepartmentListResponse:
    return await service.list_departments(
        tenant_id=current_user.tenant_id,
        query=q,
        cursor=cursor,
        page_size=page_size,
    )


@router.get("/groups", response_model=DirectoryGroupListResponse)
async def list_directory_groups(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DirectoryService, Depends(get_directory_service)],
    q: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DirectoryGroupListResponse:
    return await service.list_groups(
        tenant_id=current_user.tenant_id,
        query=q,
        cursor=cursor,
        page_size=page_size,
    )
