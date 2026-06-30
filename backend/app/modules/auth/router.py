from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditContext
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import (
    LoginRequest,
    RefreshTokenRequest,
    TokenResponse,
    UserProfileResponse,
)
from app.modules.auth.service import AuthService

router = APIRouter()


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthService:
    return AuthService(
        repository=AuthRepository(session),
        settings=settings,
        audit_service=AuditService(repository=AuditRepository(session)),
    )


def build_audit_context(request: Request) -> AuditContext:
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")
    request_id = getattr(request.state, "request_id", None)
    return AuditContext(
        request_id=str(request_id) if request_id else None,
        ip=client_ip,
        user_agent=user_agent,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    http_request: Request,
    request: LoginRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    return await service.login(
        tenant_slug=request.tenant_slug,
        username=request.username,
        password=request.password,
        audit_context=build_audit_context(http_request),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    http_request: Request,
    request: RefreshTokenRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    return await service.refresh(
        refresh_token=request.refresh_token,
        audit_context=build_audit_context(http_request),
    )


@router.get("/me", response_model=UserProfileResponse)
async def me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserProfileResponse:
    return UserProfileResponse(
        id=current_user.id,
        tenant_id=current_user.tenant_id,
        username=current_user.username,
        email=current_user.email,
        display_name=current_user.display_name,
        is_super_admin=current_user.is_super_admin,
        must_change_password=current_user.must_change_password,
    )
