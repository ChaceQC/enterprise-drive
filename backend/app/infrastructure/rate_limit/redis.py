from __future__ import annotations

from typing import Any, cast

import redis.asyncio as redis

from app.infrastructure.rate_limit.base import RateLimitDecision, RateLimitRule

_FIXED_WINDOW_LUA = """
local count = redis.call("INCR", KEYS[1])
if count == 1 then
  redis.call("EXPIRE", KEYS[1], ARGV[1])
end
local ttl = redis.call("TTL", KEYS[1])
if ttl < 0 then
  redis.call("EXPIRE", KEYS[1], ARGV[1])
  ttl = tonumber(ARGV[1])
end
return {count, ttl}
"""


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
        count, ttl = await self._hit_window(
            redis_key=redis_key,
            window_seconds=rule.window_seconds,
        )
        remaining = max(rule.limit - count, 0)
        return RateLimitDecision(
            allowed=count <= rule.limit,
            limit=rule.limit,
            remaining=remaining,
            retry_after_seconds=0 if count <= rule.limit else ttl,
        )

    async def _hit_window(self, *, redis_key: str, window_seconds: int) -> tuple[int, int]:
        result = await self._client.eval(_FIXED_WINDOW_LUA, 1, redis_key, window_seconds)
        count, ttl = result
        count = int(count)
        ttl = int(ttl)
        return count, ttl if ttl > 0 else window_seconds

    async def close(self) -> None:
        close = getattr(self._client, "aclose", None)
        if close is None:
            return
        result = close()
        if hasattr(result, "__await__"):
            await result
