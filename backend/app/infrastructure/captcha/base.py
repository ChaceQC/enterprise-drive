from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CaptchaContext:
    action: str
    client_ip: str | None


class CaptchaVerifier(Protocol):
    enabled: bool

    async def verify(
        self,
        *,
        token: str | None,
        context: CaptchaContext,
    ) -> bool:
        """Return whether a challenge token is valid for the current request."""


class DisabledCaptchaVerifier:
    enabled = False

    async def verify(
        self,
        *,
        token: str | None,
        context: CaptchaContext,
    ) -> bool:
        del token, context
        return False
