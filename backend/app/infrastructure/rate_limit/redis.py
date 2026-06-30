from __future__ import annotations

from typing import Any, cast

import redis.asyncio as redis

from app.infrastructure.rate_limit.base import RateLimitDecision, RateLimitRule


class RedisFixedWindowRateLimiter:
    def __init__(self, *, redis_url: str) -> None:
        self._client = cast(
            Any,
            redis.from_url(redis_url, encoding="utf-8", decode_responses=True),  # type: ignore[no-untyped-call]
        )

    async def hit(
        self,
        *,
        key: str,
        rule: RateLimitRule,
    ) -> RateLimitDecision:
        if rule.limit <= 0 or rule.window_seconds <= 0:
            return RateLimitDecision(
                allowed=False,
                limit=max(rule.limit, 0),
                remaining=0,
                retry_after_seconds=max(rule.window_seconds, 1),
            )

        redis_key = f"rate_limit:{rule.action}:{key}"
        count = await self._increment(redis_key=redis_key, window_seconds=rule.window_seconds)
        ttl = await self._ttl(redis_key=redis_key, fallback_seconds=rule.window_seconds)
        remaining = max(rule.limit - count, 0)
        return RateLimitDecision(
            allowed=count <= rule.limit,
            limit=rule.limit,
            remaining=remaining,
            retry_after_seconds=0 if count <= rule.limit else ttl,
        )

    async def _increment(self, *, redis_key: str, window_seconds: int) -> int:
        count = int(await self._client.incr(redis_key))
        if count == 1:
            await self._client.expire(redis_key, window_seconds)
        return count

    async def _ttl(self, *, redis_key: str, fallback_seconds: int) -> int:
        ttl = await self._client.ttl(redis_key)
        if not isinstance(ttl, int):
            ttl = int(ttl)
        return ttl if ttl > 0 else fallback_seconds

    async def close(self) -> None:
        close = getattr(self._client, "aclose", None)
        if close is None:
            return
        result = close()
        if hasattr(result, "__await__"):
            await result
