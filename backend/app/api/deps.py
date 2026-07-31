from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.core.config import Settings, get_settings
from app.core.logging import update_log_context
from app.core.transfer_protocol import (
    DRIVE_TRANSFER_PROTOCOL_HEADER,
    DRIVE_TRANSFER_PROTOCOL_V1,
)
from app.db.session import get_db_session
from app.infrastructure.rate_limit.base import RateLimiter, RateLimitRule
from app.infrastructure.rate_limit.redis import RedisFixedWindowRateLimiter
from app.infrastructure.search.base import SearchIndexAdapter
from app.infrastructure.search.opensearch import OpenSearchIndexAdapter
from app.infrastructure.storage.base import StorageAdapter
from app.infrastructure.storage.s3 import S3StorageAdapter
from app.modules.audit.schemas import AuditContext
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService


@lru_cache
def _get_redis_rate_limiter(redis_url: str) -> RedisFixedWindowRateLimiter:
    return RedisFixedWindowRateLimiter(redis_url=redis_url)


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    session_token = request.cookies.get(settings.session_cookie_name)
    if session_token is None:
        raise ApiError("AUTH_REQUIRED", "请先登录", status_code=401)

    current_user = await AuthService(
        repository=AuthRepository(session),
        settings=settings,
    ).authenticate_session(
        session_token=session_token,
        csrf_token=_csrf_token_from_header(request=request, settings=settings),
        require_csrf=request.method.upper() in _CSRF_METHODS,
    )
    update_log_context(
        tenant_id=str(current_user.tenant_id),
        user_id=str(current_user.id),
    )
    return current_user


_CSRF_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _csrf_token_from_header(*, request: Request, settings: Settings) -> str | None:
    token = request.headers.get(settings.csrf_header_name)
    return token.strip() if token else None


def build_audit_context(request: Request) -> AuditContext:
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")
    request_id = getattr(request.state, "request_id", None)
    return AuditContext(
        request_id=str(request_id) if request_id else None,
        ip=client_ip,
        user_agent=user_agent,
    )


def ensure_supported_transfer_protocol(
    requested_version: Annotated[
        str | None,
        Header(alias=DRIVE_TRANSFER_PROTOCOL_HEADER),
    ] = None,
) -> None:
    if requested_version is None or requested_version.strip() == DRIVE_TRANSFER_PROTOCOL_V1:
        return
    raise ApiError(
        "TRANSFER_PROTOCOL_UNSUPPORTED",
        "不支持的文件传输协议版本",
        status_code=426,
        details={
            "requested": requested_version.strip(),
            "supported": [DRIVE_TRANSFER_PROTOCOL_V1],
        },
    )


def get_storage_adapter(
    settings: Annotated[Settings, Depends(get_settings)],
) -> StorageAdapter:
    return S3StorageAdapter(settings=settings)


def get_search_index_adapter(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SearchIndexAdapter:
    return OpenSearchIndexAdapter(settings=settings)


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
    _raise_rate_limited(
        action=action, rule=rule, limit=decision.limit, retry_after=decision.retry_after_seconds
    )


async def enforce_public_rate_limit(
    *,
    settings: Settings,
    rate_limiter: RateLimiter,
    action: str,
    request: Request,
    resource_key: str | None = None,
    include_client_ip: bool = True,
) -> None:
    if not settings.rate_limit_enabled:
        return
    rule = _rate_limit_rule(settings=settings, action=action)
    decision = await rate_limiter.hit(
        key=_public_rate_limit_key(
            resource_key=resource_key,
            request=request,
            include_client_ip=include_client_ip,
        ),
        rule=rule,
    )
    if decision.allowed:
        return
    _raise_rate_limited(
        action=action, rule=rule, limit=decision.limit, retry_after=decision.retry_after_seconds
    )


def _rate_limit_rule(*, settings: Settings, action: str) -> RateLimitRule:
    if action == "auth.login.ip":
        return RateLimitRule(
            action=action,
            limit=settings.login_ip_rate_limit_count,
            window_seconds=settings.login_rate_limit_window_seconds,
        )
    if action == "auth.login.account":
        return RateLimitRule(
            action=action,
            limit=settings.login_account_rate_limit_count,
            window_seconds=settings.login_rate_limit_window_seconds,
        )
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
    if action == "search.query":
        return RateLimitRule(
            action=action,
            limit=settings.search_query_rate_limit_count,
            window_seconds=settings.search_query_rate_limit_window_seconds,
        )
    if action == "share.external_access":
        return RateLimitRule(
            action=action,
            limit=settings.share_external_access_rate_limit_count,
            window_seconds=settings.share_external_access_rate_limit_window_seconds,
        )
    if action == "share.external_download":
        return RateLimitRule(
            action=action,
            limit=settings.share_external_download_rate_limit_count,
            window_seconds=settings.share_external_download_rate_limit_window_seconds,
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


def _public_rate_limit_key(
    *,
    resource_key: str | None,
    request: Request,
    include_client_ip: bool = True,
) -> str:
    parts = ["public"]
    if resource_key:
        parts.append(resource_key)
    if include_client_ip:
        parts.append(f"ip:{request.client.host}" if request.client is not None else "ip:unknown")
    return ":".join(parts)


def _raise_rate_limited(
    *,
    action: str,
    rule: RateLimitRule,
    limit: int,
    retry_after: int,
) -> None:
    raise ApiError(
        "RATE_LIMITED",
        "请求过于频繁，请稍后再试",
        status_code=429,
        details={
            "action": action,
            "limit": limit,
            "window_seconds": rule.window_seconds,
            "retry_after_seconds": retry_after,
        },
    )
