from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class MultipartUpload:
    provider_upload_id: str


@dataclass(frozen=True)
class PresignedUploadPart:
    part_no: int
    upload_url: str
    expires_at: datetime
    headers: dict[str, str]


@dataclass(frozen=True)
class CompletedUploadPart:
    part_no: int
    etag: str
    size_bytes: int | None = None


@dataclass(frozen=True)
class CompletedMultipartUpload:
    etag: str | None
    size_bytes: int | None


@dataclass(frozen=True)
class PresignedDownload:
    download_url: str
    expires_at: datetime
    headers: dict[str, str]


class StorageAdapter(Protocol):
    async def create_multipart_upload(
        self,
        *,
        bucket: str,
        storage_key: str,
        content_type: str | None,
    ) -> MultipartUpload:
        """Create a provider-side multipart upload and return its provider id."""

    async def presign_upload_part(
        self,
        *,
        bucket: str,
        storage_key: str,
        provider_upload_id: str,
        part_no: int,
        expires_in_seconds: int,
    ) -> PresignedUploadPart:
        """Create a short-lived URL for one multipart upload part."""

    async def abort_multipart_upload(
        self,
        *,
        bucket: str,
        storage_key: str,
        provider_upload_id: str,
    ) -> None:
        """Abort a provider-side multipart upload."""

    async def complete_multipart_upload(
        self,
        *,
        bucket: str,
        storage_key: str,
        provider_upload_id: str,
        parts: list[CompletedUploadPart],
    ) -> CompletedMultipartUpload:
        """Complete a provider-side multipart upload."""

    async def presign_download(
        self,
        *,
        bucket: str,
        storage_key: str,
        filename: str,
        expires_in_seconds: int,
    ) -> PresignedDownload:
        """Create a short-lived URL for downloading one private object."""
