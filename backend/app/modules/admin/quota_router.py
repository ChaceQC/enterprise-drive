from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import build_audit_context, get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.modules.admin.quota import AdminQuotaService
from app.modules.admin.quota_schemas import (
    AdminQuotaAccountListResponse,
    AdminQuotaAccountResponse,
    AdminQuotaAccountUpsertRequest,
    AdminQuotaPolicyCreateRequest,
    AdminQuotaPolicyListResponse,
    AdminQuotaPolicyResponse,
    AdminQuotaPolicyUpdateRequest,
    ManageableQuotaOwnerType,
    QuotaOwnerType,
)
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.quota.repository import QuotaRepository

router = APIRouter()


def get_admin_quota_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AdminQuotaService:
    return AdminQuotaService(
        repository=QuotaRepository(session),
        audit_service=AuditService(repository=AuditRepository(session)),
        settings=settings,
    )


@router.get("/accounts", response_model=AdminQuotaAccountListResponse)
async def list_quota_accounts(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminQuotaService, Depends(get_admin_quota_service)],
    owner_type: Annotated[QuotaOwnerType | None, Query()] = None,
    owner_id: Annotated[UUID | None, Query()] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminQuotaAccountListResponse:
    return await service.list_accounts(
        current_user=current_user,
        owner_type=owner_type,
        owner_id=owner_id,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )


@router.put(
    "/accounts/{owner_type}/{owner_id}",
    response_model=AdminQuotaAccountResponse,
)
async def upsert_quota_account(
    http_request: Request,
    owner_type: ManageableQuotaOwnerType,
    owner_id: UUID,
    request: AdminQuotaAccountUpsertRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminQuotaService, Depends(get_admin_quota_service)],
) -> AdminQuotaAccountResponse:
    return await service.upsert_account(
        current_user=current_user,
        owner_type=owner_type,
        owner_id=owner_id,
        limit_bytes=request.limit_bytes,
        expected_limit_bytes=request.expected_limit_bytes,
        audit_context=build_audit_context(http_request),
    )


@router.get("/policies", response_model=AdminQuotaPolicyListResponse)
async def list_quota_policies(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminQuotaService, Depends(get_admin_quota_service)],
    is_active: Annotated[bool | None, Query()] = None,
    name: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminQuotaPolicyListResponse:
    return await service.list_policies(
        current_user=current_user,
        is_active=is_active,
        name=name,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )


@router.post(
    "/policies",
    response_model=AdminQuotaPolicyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_quota_policy(
    http_request: Request,
    request: AdminQuotaPolicyCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminQuotaService, Depends(get_admin_quota_service)],
) -> AdminQuotaPolicyResponse:
    return await service.create_policy(
        current_user=current_user,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.patch("/policies/{policy_id}", response_model=AdminQuotaPolicyResponse)
async def update_quota_policy(
    http_request: Request,
    policy_id: UUID,
    request: AdminQuotaPolicyUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminQuotaService, Depends(get_admin_quota_service)],
) -> AdminQuotaPolicyResponse:
    return await service.update_policy(
        current_user=current_user,
        policy_id=policy_id,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.delete("/policies/{policy_id}", response_model=AdminQuotaPolicyResponse)
async def deactivate_quota_policy(
    http_request: Request,
    policy_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AdminQuotaService, Depends(get_admin_quota_service)],
    expected_limit_bytes: Annotated[int, Query(ge=1)],
) -> AdminQuotaPolicyResponse:
    return await service.deactivate_policy(
        current_user=current_user,
        policy_id=policy_id,
        expected_limit_bytes=expected_limit_bytes,
        audit_context=build_audit_context(http_request),
    )
