from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    build_audit_context,
    enforce_public_rate_limit,
    get_current_user,
    get_rate_limiter,
)
from app.core.config import Settings, get_settings
from app.core.security import hash_token
from app.db.session import get_db_session
from app.infrastructure.rate_limit.base import RateLimiter
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import (
    LoginRequest,
    LogoutResponse,
    SessionResponse,
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


@router.post("/login", response_model=SessionResponse)
async def login(
    http_request: Request,
    response: Response,
    request: LoginRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> SessionResponse:
    account_key = hash_token(
        f"{request.tenant_slug.strip().casefold()}:{request.username.strip().casefold()}"
    )
    await enforce_public_rate_limit(
        settings=settings,
        rate_limiter=rate_limiter,
        action="auth.login.ip",
        request=http_request,
        resource_key="login",
    )
    await enforce_public_rate_limit(
        settings=settings,
        rate_limiter=rate_limiter,
        action="auth.login.account",
        request=http_request,
        resource_key=f"account:{account_key}",
        include_client_ip=False,
    )
    issued_session = await service.login(
        tenant_slug=request.tenant_slug,
        username=request.username,
        password=request.password,
        audit_context=build_audit_context(http_request),
    )
    _set_session_cookie(
        response=response,
        request=http_request,
        session_token=issued_session.session_token,
        csrf_token=issued_session.csrf_token,
    )
    return issued_session.response


@router.post("/session/rotate", response_model=SessionResponse)
async def rotate_session(
    http_request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> SessionResponse:
    session_token = _require_session_cookie(http_request)
    issued_session = await service.rotate_session(
        session_token=session_token,
        csrf_token=_read_csrf_header(http_request),
        audit_context=build_audit_context(http_request),
    )
    _set_session_cookie(
        response=response,
        request=http_request,
        session_token=issued_session.session_token,
        csrf_token=issued_session.csrf_token,
    )
    return issued_session.response


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    http_request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> LogoutResponse:
    session_token = _read_session_cookie(http_request, required=False)
    if session_token is not None:
        await service.logout(
            session_token=session_token,
            csrf_token=_read_csrf_header(http_request),
            audit_context=build_audit_context(http_request),
        )
    _clear_session_cookie(response=response, request=http_request)
    return LogoutResponse()


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


def _read_session_cookie(request: Request, *, required: bool = True) -> str | None:
    settings = request.app.state.settings
    session_token = request.cookies.get(settings.session_cookie_name)
    if session_token is None and required:
        from app.api.errors import ApiError

        raise ApiError("AUTH_REQUIRED", "请先登录", status_code=401)
    return session_token


def _require_session_cookie(request: Request) -> str:
    session_token = _read_session_cookie(request)
    assert session_token is not None
    return session_token


def _set_session_cookie(
    *,
    response: Response,
    request: Request,
    session_token: str,
    csrf_token: str,
) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        max_age=settings.session_days * 24 * 60 * 60,
        path=settings.session_cookie_path,
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite=settings.session_cookie_samesite,
    )
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        max_age=settings.session_days * 24 * 60 * 60,
        path=settings.session_cookie_path,
        secure=settings.session_cookie_secure,
        httponly=False,
        samesite=settings.session_cookie_samesite,
    )


def _clear_session_cookie(*, response: Response, request: Request) -> None:
    settings = request.app.state.settings
    response.delete_cookie(
        key=settings.session_cookie_name,
        path=settings.session_cookie_path,
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite=settings.session_cookie_samesite,
    )
    response.delete_cookie(
        key=settings.csrf_cookie_name,
        path=settings.session_cookie_path,
        secure=settings.session_cookie_secure,
        httponly=False,
        samesite=settings.session_cookie_samesite,
    )


def _read_csrf_header(request: Request) -> str | None:
    settings = request.app.state.settings
    token = request.headers.get(settings.csrf_header_name)
    return token.strip() if token else None
