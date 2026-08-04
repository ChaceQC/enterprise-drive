from __future__ import annotations

import os

from app.api.errors import ApiError


class EnvironmentSecretResolver:
    """Resolve protected references without storing secret values in identity rows."""

    def resolve(self, secret_ref: str | None) -> str | None:
        if secret_ref is None:
            return None
        normalized = secret_ref.strip()
        if normalized.startswith("env:"):
            name = normalized.removeprefix("env:").strip()
            value = os.environ.get(name)
            if not name or value is None or not value.strip():
                raise ApiError(
                    "IDENTITY_SECRET_UNAVAILABLE",
                    "身份源凭据不可用",
                    status_code=503,
                )
            return value
        raise ApiError(
            "IDENTITY_SECRET_REF_INVALID",
            "身份源凭据引用格式不合法",
            status_code=422,
        )
