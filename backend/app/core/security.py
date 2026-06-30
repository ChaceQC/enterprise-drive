from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, VerifyMismatchError
from jose import JWTError, jwt  # type: ignore[import-untyped]

from app.core.config import Settings

password_hasher = PasswordHasher()


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (Argon2Error, VerifyMismatchError):
        return False


def create_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(
    *,
    settings: Settings,
    user_id: UUID,
    tenant_id: UUID,
    username: str,
    is_super_admin: bool,
) -> tuple[str, datetime]:
    expires_at = utc_now() + timedelta(minutes=settings.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "username": username,
        "is_super_admin": is_super_admin,
        "type": "access",
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_at


def decode_access_token(settings: Settings, token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError("invalid token") from exc

    if payload.get("type") != "access":
        raise ValueError("invalid token type")
    return cast(dict[str, Any], payload)
