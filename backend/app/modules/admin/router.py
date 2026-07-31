from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import build_audit_context, get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.modules.admin.audit import AdminAuditService
from app.modules.admin.schemas import AdminAuditLogListResponse
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User

router = APIRouter()


def get_admin_audit_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AdminAuditService:
    repository = AuditRepository(session)
    return AdminAuditService(
        repository=repository,
        audit_service=AuditService(repository=repository),
        settings=settings,
    )


@router.get("/audit-logs", response_model=AdminAuditLogListResponse)
async def list_admin_audit_logs(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminAuditService, Depends(get_admin_audit_service)],
    actor_id: Annotated[UUID | None, Query()] = None,
    actor_type: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    action: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    resource_type: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    resource_id: Annotated[UUID | None, Query()] = None,
    result: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    risk_level: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    request_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    created_from: Annotated[datetime | None, Query()] = None,
    created_to: Annotated[datetime | None, Query()] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminAuditLogListResponse:
    return await service.list_audit_logs(
        current_user=current_user,
        actor_id=actor_id,
        actor_type=actor_type,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        result=result,
        risk_level=risk_level,
        request_id=request_id,
        created_from=created_from,
        created_to=created_to,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )
