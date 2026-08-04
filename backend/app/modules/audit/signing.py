from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass


@dataclass(frozen=True)
class ContentSignature:
    content_sha256: str
    algorithm: str
    key_id: str
    value: str


def sign_content(
    *,
    content: bytes,
    key: str,
    key_id: str,
    purpose: str,
) -> ContentSignature:
    content_sha256 = hashlib.sha256(content).hexdigest()
    message = f"enterprise-drive:{purpose}:v1:{content_sha256}".encode()
    value = hmac.new(key.encode(), message, hashlib.sha256).hexdigest()
    return ContentSignature(
        content_sha256=content_sha256,
        algorithm="hmac-sha256",
        key_id=key_id,
        value=value,
    )
