from __future__ import annotations

from app.api.errors import ApiError

SUPPORTED_UPLOAD_HASH_ALGOS = {"sha256"}


def ensure_supported_upload_hash_algo(hash_algo: str) -> None:
    if hash_algo.lower() not in SUPPORTED_UPLOAD_HASH_ALGOS:
        raise ApiError("UPLOAD_HASH_ALGO_UNSUPPORTED", "上传 hash 算法不支持", status_code=422)


def normalize_upload_hash(hash_value: str) -> str:
    return hash_value.lower()
