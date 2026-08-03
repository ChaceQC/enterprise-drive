from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    build_audit_context,
    enforce_public_rate_limit,
    get_current_user,
    get_rate_limiter,
)
from app.api.errors import ApiError
from app.core.config import Settings, get_settings
from app.core.security import hash_token
from app.db.session import get_db_session
from app.infrastructure.rate_limit.base import RateLimiter
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService
from app.modules.device.repository import DeviceRepository
from app.modules.device.schemas import (
    DeviceListResponse,
    DeviceRegisterRequest,
    DeviceRevokeResponse,
    DeviceRotateRequest,
    DeviceSessionResponse,
)
from app.modules.device.service import DeviceSessionService

router = APIRouter()


def get_device_session_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DeviceSessionService:
    audit_service = AuditService(repository=AuditRepository(session))
    return DeviceSessionService(
        repository=DeviceRepository(session),
        auth_service=AuthService(
            repository=AuthRepository(session),
            settings=settings,
            audit_service=audit_service,
        ),
        settings=settings,
        audit_service=audit_service,
    )


@router.post("/register", response_model=DeviceSessionResponse)
async def register_device(
    http_request: Request,
    request: DeviceRegisterRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    service: Annotated[DeviceSessionService, Depends(get_device_session_service)],
) -> DeviceSessionResponse:
    account_key = hash_token(
        f"{request.tenant_slug.strip().casefold()}:{request.username.strip().casefold()}"
    )
    await enforce_public_rate_limit(
        settings=settings,
        rate_limiter=rate_limiter,
        action="auth.login.ip",
        request=http_request,
        resource_key="device-register",
    )
    await enforce_public_rate_limit(
        settings=settings,
        rate_limiter=rate_limiter,
        action="auth.login.account",
        request=http_request,
        resource_key=f"device-account:{account_key}",
        include_client_ip=False,
    )
    return await service.register(
        tenant_slug=request.tenant_slug,
        username=request.username,
        password=request.password,
        installation_id=request.installation_id,
        device_name=request.device_name,
        platform=request.platform,
        client_version=request.client_version,
        audit_context=build_audit_context(http_request),
    )


@router.post("/rotate", response_model=DeviceSessionResponse)
async def rotate_device_session(
    http_request: Request,
    request: DeviceRotateRequest,
    service: Annotated[DeviceSessionService, Depends(get_device_session_service)],
) -> DeviceSessionResponse:
    return await service.rotate(
        raw_token=_require_device_token(http_request),
        client_version=request.client_version,
        audit_context=build_audit_context(http_request),
    )


@router.get("", response_model=DeviceListResponse)
async def list_devices(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DeviceSessionService, Depends(get_device_session_service)],
) -> DeviceListResponse:
    current_device_id = getattr(http_request.state, "device_id", None)
    return await service.list_devices(
        current_user=current_user,
        current_device_id=current_device_id if isinstance(current_device_id, UUID) else None,
    )


@router.delete("/{device_id}", response_model=DeviceRevokeResponse)
async def revoke_device(
    http_request: Request,
    device_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DeviceSessionService, Depends(get_device_session_service)],
) -> DeviceRevokeResponse:
    return await service.revoke_device(
        current_user=current_user,
        device_id=device_id,
        audit_context=build_audit_context(http_request),
    )


@router.delete("", response_model=DeviceRevokeResponse)
async def revoke_all_devices(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DeviceSessionService, Depends(get_device_session_service)],
) -> DeviceRevokeResponse:
    return await service.revoke_all(
        current_user=current_user,
        audit_context=build_audit_context(http_request),
    )


def _require_device_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.casefold() != "device" or not token.strip():
        raise ApiError("DEVICE_SESSION_REQUIRED", "请提供设备会话", status_code=401)
    return token.strip()
