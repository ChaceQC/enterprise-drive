from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.core.config import Settings, get_settings
from app.core.security import decode_access_token
from app.db.session import get_db_session
from app.infrastructure.storage.base import StorageAdapter
from app.infrastructure.storage.s3 import S3StorageAdapter
from app.modules.audit.schemas import AuditContext
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> User:
    if authorization is None or not authorization.lower().startswith("bearer "):
        raise ApiError("AUTH_REQUIRED", "请先登录", status_code=401)

    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(settings, token)
        tenant_id = UUID(str(payload["tenant_id"]))
        user_id = UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise ApiError("TOKEN_INVALID", "访问令牌无效", status_code=401) from exc

    user = await AuthRepository(session).get_user_by_id(tenant_id=tenant_id, user_id=user_id)
    if user is None or not user.is_active:
        raise ApiError("AUTH_REQUIRED", "认证已失效", status_code=401)
    return user


def build_audit_context(request: Request) -> AuditContext:
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")
    request_id = getattr(request.state, "request_id", None)
    return AuditContext(
        request_id=str(request_id) if request_id else None,
        ip=client_ip,
        user_agent=user_agent,
    )


def get_storage_adapter(
    settings: Annotated[Settings, Depends(get_settings)],
) -> StorageAdapter:
    return S3StorageAdapter(settings=settings)
