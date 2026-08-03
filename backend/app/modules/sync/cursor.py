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
class SyncCursor:
    tenant_id: UUID
    user_id: UUID
    space_id: UUID
    root_node_id: UUID
    sequence: int
    issued_at: datetime


def encode_sync_cursor(settings: Settings, cursor: SyncCursor) -> str:
    payload = {
        "v": 1,
        "tenant_id": str(cursor.tenant_id),
        "user_id": str(cursor.user_id),
        "space_id": str(cursor.space_id),
        "root_node_id": str(cursor.root_node_id),
        "sequence": cursor.sequence,
        "issued_at": ensure_utc(cursor.issued_at).isoformat(),
    }
    payload_token = _base64_url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = _sign(settings, payload_token)
    return f"{payload_token}.{signature}"


def decode_sync_cursor(settings: Settings, raw_cursor: str) -> SyncCursor:
    try:
        payload_token, signature = raw_cursor.split(".", 1)
    except ValueError as exc:
        raise _invalid_cursor() from exc
    if not hmac.compare_digest(signature, _sign(settings, payload_token)):
        raise _invalid_cursor()

    try:
        payload = json.loads(_base64_url_decode(payload_token).decode("utf-8"))
        if payload["v"] != 1:
            raise ValueError("unsupported cursor version")
        sequence = int(payload["sequence"])
        if sequence < 0:
            raise ValueError("negative sequence")
        return SyncCursor(
            tenant_id=UUID(str(payload["tenant_id"])),
            user_id=UUID(str(payload["user_id"])),
            space_id=UUID(str(payload["space_id"])),
            root_node_id=UUID(str(payload["root_node_id"])),
            sequence=sequence,
            issued_at=ensure_utc(datetime.fromisoformat(str(payload["issued_at"]))),
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
        f"sync:{payload_token}".encode(),
        hashlib.sha256,
    ).digest()
    return _base64_url_encode(digest)


def _base64_url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64_url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(f"{value}{'=' * (-len(value) % 4)}")


def _invalid_cursor() -> ApiError:
    return ApiError("SYNC_CURSOR_INVALID", "增量同步游标无效", status_code=400)
