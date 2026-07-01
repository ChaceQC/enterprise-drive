from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    enforce_rate_limit,
    get_current_user,
    get_rate_limiter,
    get_search_index_adapter,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.infrastructure.rate_limit.base import RateLimiter
from app.infrastructure.search.base import SearchIndexAdapter
from app.modules.auth.models import User
from app.modules.org.repository import OrgRepository
from app.modules.org.service import OrgService
from app.modules.permission.repository import PermissionRepository
from app.modules.permission.service import PermissionService
from app.modules.search.repository import SearchRepository
from app.modules.search.schemas import SearchFilesResponse
from app.modules.search.service import SearchService

router = APIRouter()


def get_search_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    index_adapter: Annotated[SearchIndexAdapter, Depends(get_search_index_adapter)],
) -> SearchService:
    org_service = OrgService(repository=OrgRepository(session))
    return SearchService(
        repository=SearchRepository(session),
        index_adapter=index_adapter,
        permission_service=PermissionService(
            repository=PermissionRepository(session),
            org_service=org_service,
        ),
        org_service=org_service,
    )


@router.get("", response_model=SearchFilesResponse)
async def search_files(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    service: Annotated[SearchService, Depends(get_search_service)],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchFilesResponse:
    await enforce_rate_limit(
        settings=settings,
        rate_limiter=rate_limiter,
        current_user=current_user,
        action="search.query",
        resource_key="search",
        request=http_request,
    )
    return await service.search_files(current_user=current_user, query=q, limit=limit)
