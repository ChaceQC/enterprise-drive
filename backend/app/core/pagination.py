from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.security import ensure_utc


@dataclass(frozen=True)
class PageCursor:
    created_at: datetime
    item_id: UUID


def encode_page_cursor(
    settings: Settings,
    *,
    created_at: datetime,
    item_id: UUID,
) -> str:
    payload = {
        "created_at": ensure_utc(created_at).isoformat(),
        "id": str(item_id),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_token = _base64_url_encode(payload_bytes)
    signature = _sign(settings, payload_token)
    return f"{payload_token}.{signature}"


def decode_page_cursor(settings: Settings, cursor: str | None) -> PageCursor | None:
    if cursor is None:
        return None

    try:
        payload_token, signature = cursor.split(".", 1)
    except ValueError as exc:
        raise _invalid_cursor() from exc

    expected_signature = _sign(settings, payload_token)
    if not hmac.compare_digest(signature, expected_signature):
        raise _invalid_cursor()

    try:
        payload = json.loads(_base64_url_decode(payload_token).decode("utf-8"))
        return PageCursor(
            created_at=ensure_utc(datetime.fromisoformat(str(payload["created_at"]))),
            item_id=UUID(str(payload["id"])),
        )
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise _invalid_cursor() from exc


def _sign(settings: Settings, payload_token: str) -> str:
    digest = hmac.new(
        settings.secret_key.encode("utf-8"),
        payload_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _base64_url_encode(digest)


def _base64_url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64_url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def _invalid_cursor() -> ApiError:
    return ApiError("CURSOR_INVALID", "分页游标无效", status_code=400)
