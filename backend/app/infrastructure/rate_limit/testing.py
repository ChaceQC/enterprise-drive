from __future__ import annotations

import time
from collections.abc import Callable

from app.infrastructure.rate_limit.base import RateLimitDecision, RateLimitRule


class InMemoryFixedWindowRateLimiter:
    def __init__(self, *, now: Callable[[], float] | None = None) -> None:
        self._now = now or time.monotonic
        self._windows: dict[str, tuple[int, float]] = {}

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

        now = self._now()
        full_key = f"{rule.action}:{key}"
        count, expires_at = self._windows.get(full_key, (0, now + rule.window_seconds))
        if now >= expires_at:
            count = 0
            expires_at = now + rule.window_seconds

        count += 1
        self._windows[full_key] = (count, expires_at)
        retry_after = max(int(expires_at - now), 1)
        return RateLimitDecision(
            allowed=count <= rule.limit,
            limit=rule.limit,
            remaining=max(rule.limit - count, 0),
            retry_after_seconds=0 if count <= rule.limit else retry_after,
        )
