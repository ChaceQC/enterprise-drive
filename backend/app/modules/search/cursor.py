from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass

from app.api.errors import ApiError
from app.core.config import Settings


@dataclass(frozen=True)
class SearchCursor:
    query: str
    sort_values: list[object]


def encode_search_cursor(
    settings: Settings,
    *,
    query: str,
    sort_values: list[object],
) -> str:
    payload = {
        "query": query,
        "sort": [_json_scalar(value) for value in sort_values],
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_token = _base64_url_encode(payload_bytes)
    signature = _sign(settings, payload_token)
    return f"{payload_token}.{signature}"


def decode_search_cursor(settings: Settings, cursor: str | None) -> SearchCursor | None:
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
        query = str(payload["query"])
        sort_values = payload["sort"]
        if not isinstance(sort_values, list):
            raise ValueError
        return SearchCursor(
            query=query,
            sort_values=[_json_scalar(value) for value in sort_values],
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


def _json_scalar(value: object) -> object:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    raise ValueError("Search cursor sort value must be JSON scalar")


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
