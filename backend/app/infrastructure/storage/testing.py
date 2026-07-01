from __future__ import annotations

import hashlib
from datetime import timedelta
from uuid import uuid4

from app.core.security import utc_now
from app.infrastructure.storage.base import (
    CompletedMultipartUpload,
    CompletedUploadPart,
    MultipartUpload,
    PresignedDownload,
    PresignedUploadPart,
)


class InMemoryStorageAdapter:
    def __init__(self) -> None:
        self.created_uploads: dict[str, tuple[str, str]] = {}
        self.aborted_uploads: set[str] = set()
        self.completed_uploads: dict[str, list[CompletedUploadPart]] = {}
        self.object_contents: dict[tuple[str, str], bytes] = {}
        self.copied_objects: list[tuple[str, str, str]] = []
        self.deleted_objects: list[tuple[str, str]] = []
        self.presigned_downloads: list[tuple[str, str, str]] = []

    async def create_multipart_upload(
        self,
        *,
        bucket: str,
        storage_key: str,
        content_type: str | None,
    ) -> MultipartUpload:
        provider_upload_id = f"test-upload-{uuid4()}"
        self.created_uploads[provider_upload_id] = (bucket, storage_key)
        return MultipartUpload(provider_upload_id=provider_upload_id)

    async def presign_upload_part(
        self,
        *,
        bucket: str,
        storage_key: str,
        provider_upload_id: str,
        part_no: int,
        expires_in_seconds: int,
    ) -> PresignedUploadPart:
        return PresignedUploadPart(
            part_no=part_no,
            upload_url=(
                f"https://storage.test/{bucket}/{storage_key}"
                f"?upload_id={provider_upload_id}&part_no={part_no}"
            ),
            expires_at=utc_now() + timedelta(seconds=expires_in_seconds),
            headers={},
        )

    async def abort_multipart_upload(
        self,
        *,
        bucket: str,
        storage_key: str,
        provider_upload_id: str,
    ) -> None:
        self.aborted_uploads.add(provider_upload_id)

    async def complete_multipart_upload(
        self,
        *,
        bucket: str,
        storage_key: str,
        provider_upload_id: str,
        parts: list[CompletedUploadPart],
    ) -> CompletedMultipartUpload:
        self.created_uploads.setdefault(provider_upload_id, (bucket, storage_key))
        self.completed_uploads[provider_upload_id] = parts
        size_bytes = sum(part.size_bytes or 0 for part in parts)
        return CompletedMultipartUpload(
            etag=f"completed-{provider_upload_id}",
            size_bytes=size_bytes or None,
        )

    async def presign_download(
        self,
        *,
        bucket: str,
        storage_key: str,
        filename: str,
        expires_in_seconds: int,
    ) -> PresignedDownload:
        self.presigned_downloads.append((bucket, storage_key, filename))
        return PresignedDownload(
            download_url=f"https://storage.test/{bucket}/{storage_key}?download={filename}",
            expires_at=utc_now() + timedelta(seconds=expires_in_seconds),
            headers={},
        )

    async def calculate_object_hash(
        self,
        *,
        bucket: str,
        storage_key: str,
        hash_algo: str,
    ) -> str:
        if hash_algo != "sha256":
            raise ValueError(f"unsupported hash algorithm: {hash_algo}")
        content = self.object_contents.get((bucket, storage_key))
        if content is not None:
            return hashlib.sha256(content).hexdigest()
        parts = self._completed_parts_for(bucket=bucket, storage_key=storage_key)
        digest = hashlib.sha256()
        for part in sorted(parts, key=lambda item: item.part_no):
            digest.update(b"\x00" * (part.size_bytes or 0))
        return digest.hexdigest()

    async def copy_object(
        self,
        *,
        bucket: str,
        source_key: str,
        destination_key: str,
    ) -> None:
        self.copied_objects.append((bucket, source_key, destination_key))
        content = self.object_contents.get((bucket, source_key))
        if content is None:
            content = self._object_content_from_completed_parts(
                bucket=bucket,
                storage_key=source_key,
            )
        self.object_contents[(bucket, destination_key)] = content

    async def delete_object(
        self,
        *,
        bucket: str,
        storage_key: str,
    ) -> None:
        self.deleted_objects.append((bucket, storage_key))
        self.object_contents.pop((bucket, storage_key), None)

    async def read_object_bytes(
        self,
        *,
        bucket: str,
        storage_key: str,
        max_bytes: int,
    ) -> bytes:
        content = self.object_contents.get((bucket, storage_key))
        if content is None:
            content = self._object_content_from_completed_parts(
                bucket=bucket,
                storage_key=storage_key,
            )
        return content[:max_bytes]

    def _completed_parts_for(
        self,
        *,
        bucket: str,
        storage_key: str,
    ) -> list[CompletedUploadPart]:
        for provider_upload_id, location in self.created_uploads.items():
            if location == (bucket, storage_key):
                return self.completed_uploads.get(provider_upload_id, [])
        return []

    def _object_content_from_completed_parts(
        self,
        *,
        bucket: str,
        storage_key: str,
    ) -> bytes:
        parts = self._completed_parts_for(bucket=bucket, storage_key=storage_key)
        return b"".join(b"\x00" * (part.size_bytes or 0) for part in parts)
