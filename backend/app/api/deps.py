from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.core.config import Settings, get_settings
from app.core.security import decode_access_token
from app.db.session import get_db_session
from app.infrastructure.rate_limit.base import RateLimiter, RateLimitRule
from app.infrastructure.rate_limit.redis import RedisFixedWindowRateLimiter
from app.infrastructure.storage.base import StorageAdapter
from app.infrastructure.storage.s3 import S3StorageAdapter
from app.modules.audit.schemas import AuditContext
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository


@lru_cache
def _get_redis_rate_limiter(redis_url: str) -> RedisFixedWindowRateLimiter:
    return RedisFixedWindowRateLimiter(redis_url=redis_url)


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


def get_rate_limiter(
    settings: Annotated[Settings, Depends(get_settings)],
) -> RateLimiter:
    return _get_redis_rate_limiter(settings.redis_url)


async def enforce_rate_limit(
    *,
    settings: Settings,
    rate_limiter: RateLimiter,
    current_user: User,
    action: str,
    resource_key: str | None = None,
    request: Request | None = None,
) -> None:
    if not settings.rate_limit_enabled:
        return
    rule = _rate_limit_rule(settings=settings, action=action)
    decision = await rate_limiter.hit(
        key=_rate_limit_key(
            current_user=current_user,
            resource_key=resource_key,
            request=request,
        ),
        rule=rule,
    )
    if decision.allowed:
        return
    raise ApiError(
        "RATE_LIMITED",
        "请求过于频繁，请稍后再试",
        status_code=429,
        details={
            "action": action,
            "limit": decision.limit,
            "window_seconds": rule.window_seconds,
            "retry_after_seconds": decision.retry_after_seconds,
        },
    )


def _rate_limit_rule(*, settings: Settings, action: str) -> RateLimitRule:
    if action == "upload.init":
        return RateLimitRule(
            action=action,
            limit=settings.upload_init_rate_limit_count,
            window_seconds=settings.upload_init_rate_limit_window_seconds,
        )
    if action == "upload.part_presign":
        return RateLimitRule(
            action=action,
            limit=settings.upload_part_presign_rate_limit_count,
            window_seconds=settings.upload_part_presign_rate_limit_window_seconds,
        )
    if action == "file.download_presign":
        return RateLimitRule(
            action=action,
            limit=settings.download_presign_rate_limit_count,
            window_seconds=settings.download_presign_rate_limit_window_seconds,
        )
    raise ApiError("RATE_LIMIT_RULE_NOT_FOUND", "限流规则不存在", status_code=500)


def _rate_limit_key(
    *,
    current_user: User,
    resource_key: str | None,
    request: Request | None,
) -> str:
    parts = [f"tenant:{current_user.tenant_id}", f"user:{current_user.id}"]
    if resource_key:
        parts.append(resource_key)
    if request is not None and request.client is not None:
        parts.append(f"ip:{request.client.host}")
    return ":".join(parts)
