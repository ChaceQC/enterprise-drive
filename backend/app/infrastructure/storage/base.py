from __future__ import annotations

from collections.abc import AsyncIterator
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


@dataclass(frozen=True)
class StorageObject:
    storage_key: str
    size_bytes: int | None = None
    last_modified: datetime | None = None


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

    async def calculate_object_hash(
        self,
        *,
        bucket: str,
        storage_key: str,
        hash_algo: str,
    ) -> str:
        """Calculate a content hash for one completed private object."""

    async def copy_object(
        self,
        *,
        bucket: str,
        source_key: str,
        destination_key: str,
    ) -> None:
        """Copy one private object within the same bucket."""

    async def delete_object(
        self,
        *,
        bucket: str,
        storage_key: str,
    ) -> None:
        """Delete one private object if it exists."""

    async def read_object_bytes(
        self,
        *,
        bucket: str,
        storage_key: str,
        max_bytes: int,
    ) -> bytes:
        """Read at most max_bytes from one private object."""

    def stream_object(
        self,
        *,
        bucket: str,
        storage_key: str,
        offset: int,
        length: int,
        chunk_size: int,
    ) -> AsyncIterator[bytes]:
        """Stream one bounded byte range from a private object."""

    async def put_object_bytes(
        self,
        *,
        bucket: str,
        storage_key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        """Write one private object from bytes."""

    async def list_objects(
        self,
        *,
        bucket: str,
        prefix: str,
        limit: int,
        start_after: str | None = None,
    ) -> list[StorageObject]:
        """List private objects by prefix, returning at most limit keys."""
