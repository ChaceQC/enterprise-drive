from __future__ import annotations

import unicodedata

from app.api.errors import ApiError


def node_name_conflict_error() -> ApiError:
    return ApiError("NODE_NAME_EXISTS", "同一目录下已存在同名文件或文件夹", status_code=409)


def normalize_node_name(name: str) -> str:
    normalized_name = unicodedata.normalize("NFC", name).strip()
    if not normalized_name:
        raise ApiError("NODE_NAME_INVALID", "文件名不能为空", status_code=422)
    if normalized_name in {".", ".."} or ".." in normalized_name.split("/"):
        raise ApiError("NODE_NAME_INVALID", "文件名不能包含路径穿越片段", status_code=422)
    if any(char in normalized_name for char in {"/", "\\", "\x00"}):
        raise ApiError("NODE_NAME_INVALID", "文件名不能包含路径分隔符或 NUL 字符", status_code=422)
    if any(ord(char) < 32 for char in normalized_name):
        raise ApiError("NODE_NAME_INVALID", "文件名不能包含控制字符", status_code=422)
    if len(normalized_name) > 255:
        raise ApiError("NODE_NAME_INVALID", "文件名不能超过 255 个字符", status_code=422)
    return normalized_name
