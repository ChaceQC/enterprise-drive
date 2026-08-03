from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import build_audit_context, get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.modules.admin.file_security import AdminFileSecurityService
from app.modules.admin.file_security_schemas import (
    AdminFileSecurityPolicyCreateRequest,
    AdminFileSecurityPolicyListResponse,
    AdminFileSecurityPolicyResponse,
    AdminFileSecurityPolicyUpdateRequest,
    FileClassification,
)
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file_security.repository import FileSecurityRepository

router = APIRouter()


def get_admin_file_security_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AdminFileSecurityService:
    return AdminFileSecurityService(
        repository=FileSecurityRepository(session),
        audit_service=AuditService(repository=AuditRepository(session)),
        settings=settings,
    )


@router.get("/policies", response_model=AdminFileSecurityPolicyListResponse)
async def list_file_security_policies(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminFileSecurityService,
        Depends(get_admin_file_security_service),
    ],
    is_active: Annotated[bool | None, Query()] = None,
    classification: Annotated[FileClassification | None, Query()] = None,
    name: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminFileSecurityPolicyListResponse:
    return await service.list_policies(
        current_user=current_user,
        is_active=is_active,
        classification=classification,
        name=name,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )


@router.post(
    "/policies",
    response_model=AdminFileSecurityPolicyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_file_security_policy(
    http_request: Request,
    request: AdminFileSecurityPolicyCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminFileSecurityService,
        Depends(get_admin_file_security_service),
    ],
) -> AdminFileSecurityPolicyResponse:
    return await service.create_policy(
        current_user=current_user,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.patch("/policies/{policy_id}", response_model=AdminFileSecurityPolicyResponse)
async def update_file_security_policy(
    http_request: Request,
    policy_id: UUID,
    request: AdminFileSecurityPolicyUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminFileSecurityService,
        Depends(get_admin_file_security_service),
    ],
) -> AdminFileSecurityPolicyResponse:
    return await service.update_policy(
        current_user=current_user,
        policy_id=policy_id,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.delete("/policies/{policy_id}", response_model=AdminFileSecurityPolicyResponse)
async def deactivate_file_security_policy(
    http_request: Request,
    policy_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminFileSecurityService,
        Depends(get_admin_file_security_service),
    ],
    expected_version: Annotated[int, Query(ge=1)],
) -> AdminFileSecurityPolicyResponse:
    return await service.deactivate_policy(
        current_user=current_user,
        policy_id=policy_id,
        expected_version=expected_version,
        audit_context=build_audit_context(http_request),
    )
