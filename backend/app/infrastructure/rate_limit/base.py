from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RateLimitRule:
    action: str
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class RateLimiter(Protocol):
    async def hit(
        self,
        *,
        key: str,
        rule: RateLimitRule,
    ) -> RateLimitDecision:
        """Count one request for a key and return whether it is allowed."""
