from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.modules.auth.models import User
from app.modules.file.repository import FileRepository
from app.modules.org.repository import OrgRepository
from app.modules.org.service import OrgService
from app.modules.permission.repository import PermissionRepository
from app.modules.permission.service import PermissionService
from app.modules.space.repository import SpaceRepository
from app.modules.sync.repository import SyncRepository
from app.modules.sync.schemas import SyncChangeListResponse
from app.modules.sync.service import SyncService

router = APIRouter()


def get_sync_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SyncService:
    permission_repository = PermissionRepository(session)
    return SyncService(
        repository=SyncRepository(session),
        file_repository=FileRepository(session),
        space_repository=SpaceRepository(session),
        permission_service=PermissionService(
            repository=permission_repository,
            org_service=OrgService(repository=OrgRepository(session)),
        ),
        settings=settings,
    )


@router.get("/changes", response_model=SyncChangeListResponse)
async def list_sync_changes(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SyncService, Depends(get_sync_service)],
    space_id: Annotated[UUID, Query()],
    root_node_id: Annotated[UUID, Query()],
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 100,
) -> SyncChangeListResponse:
    return await service.list_changes(
        current_user=current_user,
        space_id=space_id,
        root_node_id=root_node_id,
        raw_cursor=cursor,
        page_size=page_size,
    )
