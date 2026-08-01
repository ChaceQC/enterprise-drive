from __future__ import annotations

from dataclasses import dataclass

from app.api.errors import ApiError


@dataclass(frozen=True, slots=True)
class ResolvedDownloadRange:
    start: int
    end: int
    total_size: int
    partial: bool

    @property
    def length(self) -> int:
        if self.end < self.start:
            return 0
        return self.end - self.start + 1

    @property
    def content_range(self) -> str:
        return f"bytes {self.start}-{self.end}/{self.total_size}"


def resolve_download_range(
    value: str | None,
    *,
    size_bytes: int,
    max_range_bytes: int,
) -> ResolvedDownloadRange:
    if value is None:
        return ResolvedDownloadRange(
            start=0,
            end=size_bytes - 1,
            total_size=size_bytes,
            partial=False,
        )
    if size_bytes <= 0:
        raise _range_error(size_bytes=size_bytes, reason="empty_object")

    normalized = value.strip()
    if not normalized.startswith("bytes=") or "," in normalized:
        raise _range_error(size_bytes=size_bytes, reason="syntax")
    spec = normalized.removeprefix("bytes=").strip()
    if "-" not in spec:
        raise _range_error(size_bytes=size_bytes, reason="syntax")
    start_text, end_text = spec.split("-", 1)

    if not start_text:
        if not end_text.isdigit():
            raise _range_error(size_bytes=size_bytes, reason="suffix")
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise _range_error(size_bytes=size_bytes, reason="suffix")
        start = max(size_bytes - suffix_length, 0)
        end = size_bytes - 1
    else:
        if not start_text.isdigit() or (end_text and not end_text.isdigit()):
            raise _range_error(size_bytes=size_bytes, reason="syntax")
        start = int(start_text)
        if start >= size_bytes:
            raise _range_error(size_bytes=size_bytes, reason="unsatisfied")
        end = size_bytes - 1 if not end_text else min(int(end_text), size_bytes - 1)
        if end < start:
            raise _range_error(size_bytes=size_bytes, reason="reversed")

    resolved = ResolvedDownloadRange(
        start=start,
        end=end,
        total_size=size_bytes,
        partial=True,
    )
    if resolved.length > max_range_bytes:
        raise ApiError(
            "DOWNLOAD_RANGE_TOO_LARGE",
            "单次代理下载范围过大",
            status_code=416,
            details={
                "max_range_bytes": max_range_bytes,
                "requested_bytes": resolved.length,
            },
            headers=_range_headers(size_bytes),
        )
    return resolved


def _range_error(*, size_bytes: int, reason: str) -> ApiError:
    return ApiError(
        "DOWNLOAD_RANGE_INVALID",
        "Range 请求不合法或不可满足",
        status_code=416,
        details={"reason": reason, "size_bytes": size_bytes},
        headers=_range_headers(size_bytes),
    )


def _range_headers(size_bytes: int) -> dict[str, str]:
    return {
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes */{size_bytes}",
    }
