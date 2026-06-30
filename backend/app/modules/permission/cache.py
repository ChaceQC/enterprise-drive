from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any, Protocol, cast
from uuid import UUID

import redis.asyncio as redis

from app.modules.audit.models import OutboxEvent

PERMISSION_CHANGED_EVENT = "permission.changed"
PERMISSION_CACHE_KEY_PREFIX = "permission"


def permission_cache_key(
    *,
    tenant_id: UUID,
    user_id: UUID,
    space_id: UUID,
    node_id: UUID,
    action: str,
    permission_version: int,
) -> str:
    return (
        f"{PERMISSION_CACHE_KEY_PREFIX}:{tenant_id}:"
        f"user:{user_id}:space:{space_id}:node:{node_id}:"
        f"action:{action}:v:{permission_version}"
    )


@dataclass(frozen=True)
class PermissionCacheInvalidationResult:
    patterns: list[str]
    deleted: int


class PermissionCacheInvalidator(Protocol):
    async def invalidate_permission_changed(
        self,
        *,
        event: OutboxEvent,
    ) -> PermissionCacheInvalidationResult: ...


class RedisPermissionCacheInvalidator:
    def __init__(self, *, redis_url: str) -> None:
        self._client = cast(
            Any,
            redis.from_url(redis_url, encoding="utf-8", decode_responses=True),  # type: ignore[no-untyped-call]
        )

    async def invalidate_permission_changed(
        self,
        *,
        event: OutboxEvent,
    ) -> PermissionCacheInvalidationResult:
        patterns = build_permission_cache_invalidation_patterns(event=event)
        deleted = 0
        for pattern in patterns:
            keys = [key async for key in self._client.scan_iter(match=pattern, count=500)]
            if not keys:
                continue
            deleted += int(await self._client.delete(*keys))
        return PermissionCacheInvalidationResult(patterns=patterns, deleted=deleted)

    async def close(self) -> None:
        close = getattr(self._client, "aclose", None)
        if close is None:
            return
        result = close()
        if hasattr(result, "__await__"):
            await result


class InMemoryPermissionCacheInvalidator:
    def __init__(self, *, keys: set[str] | None = None) -> None:
        self.keys = keys or set()

    async def invalidate_permission_changed(
        self,
        *,
        event: OutboxEvent,
    ) -> PermissionCacheInvalidationResult:
        patterns = build_permission_cache_invalidation_patterns(event=event)
        matched = {key for key in self.keys if any(fnmatch(key, pattern) for pattern in patterns)}
        self.keys.difference_update(matched)
        return PermissionCacheInvalidationResult(patterns=patterns, deleted=len(matched))


def build_permission_cache_invalidation_patterns(*, event: OutboxEvent) -> list[str]:
    payload = event.payload
    scope = payload.get("scope")
    resource_id = payload.get("resource_id")
    affected_user_id = payload.get("affected_user_id", "*")
    if not isinstance(scope, str) or not isinstance(resource_id, str):
        raise ValueError("invalid permission.changed payload")
    if not isinstance(affected_user_id, str):
        affected_user_id = "*"

    user_part = f"user:{affected_user_id}"
    if scope == "space":
        return [
            f"{PERMISSION_CACHE_KEY_PREFIX}:{event.tenant_id}:{user_part}:space:{resource_id}:*"
        ]
    if scope == "node":
        return [f"{PERMISSION_CACHE_KEY_PREFIX}:{event.tenant_id}:{user_part}:space:*:node:*"]
    raise ValueError(f"unsupported permission changed scope: {scope}")
