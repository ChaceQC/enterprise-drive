from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from app.core.security import utc_now
from app.infrastructure.storage.base import (
    CompletedMultipartUpload,
    CompletedUploadPart,
    MultipartUpload,
    PresignedUploadPart,
)


class InMemoryStorageAdapter:
    def __init__(self) -> None:
        self.created_uploads: dict[str, tuple[str, str]] = {}
        self.aborted_uploads: set[str] = set()
        self.completed_uploads: dict[str, list[CompletedUploadPart]] = {}

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
        self.completed_uploads[provider_upload_id] = parts
        size_bytes = sum(part.size_bytes or 0 for part in parts)
        return CompletedMultipartUpload(
            etag=f"completed-{provider_upload_id}",
            size_bytes=size_bytes or None,
        )
