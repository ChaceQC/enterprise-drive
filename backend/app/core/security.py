from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, VerifyMismatchError

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


def create_session_token() -> str:
    return secrets.token_urlsafe(48)


def create_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
