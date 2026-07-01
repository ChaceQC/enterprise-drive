from __future__ import annotations

import asyncio
import hashlib
from datetime import timedelta
from io import BytesIO
from urllib.parse import quote, urlsplit

from minio import Minio
from minio.commonconfig import CopySource
from minio.datatypes import Part

from app.core.config import Settings
from app.core.security import utc_now
from app.infrastructure.storage.base import (
    CompletedMultipartUpload,
    CompletedUploadPart,
    MultipartUpload,
    PresignedDownload,
    PresignedUploadPart,
)


class S3StorageAdapter:
    def __init__(self, *, settings: Settings) -> None:
        self.settings = settings
        endpoint_url = urlsplit(settings.s3_endpoint_url)
        endpoint = endpoint_url.netloc or endpoint_url.path
        self._client = Minio(
            endpoint,
            access_key=settings.s3_access_key_id,
            secret_key=settings.s3_secret_access_key,
            region=settings.s3_region,
            secure=endpoint_url.scheme == "https",
        )

    async def create_multipart_upload(
        self,
        *,
        bucket: str,
        storage_key: str,
        content_type: str | None,
    ) -> MultipartUpload:
        await asyncio.to_thread(self._ensure_bucket, bucket)
        provider_upload_id = await asyncio.to_thread(
            self._client._create_multipart_upload,
            bucket,
            storage_key,
            {"Content-Type": content_type or "application/octet-stream"},
        )
        return MultipartUpload(provider_upload_id=str(provider_upload_id))

    async def presign_upload_part(
        self,
        *,
        bucket: str,
        storage_key: str,
        provider_upload_id: str,
        part_no: int,
        expires_in_seconds: int,
    ) -> PresignedUploadPart:
        upload_url = await asyncio.to_thread(
            self._client.get_presigned_url,
            "PUT",
            bucket,
            storage_key,
            expires=timedelta(seconds=expires_in_seconds),
            extra_query_params={
                "partNumber": str(part_no),
                "uploadId": provider_upload_id,
            },
        )
        return PresignedUploadPart(
            part_no=part_no,
            upload_url=str(upload_url),
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
        await asyncio.to_thread(
            self._client._abort_multipart_upload,
            bucket,
            storage_key,
            provider_upload_id,
        )

    async def complete_multipart_upload(
        self,
        *,
        bucket: str,
        storage_key: str,
        provider_upload_id: str,
        parts: list[CompletedUploadPart],
    ) -> CompletedMultipartUpload:
        multipart_parts = [
            Part(part.part_no, part.etag, size=part.size_bytes)
            for part in sorted(parts, key=lambda item: item.part_no)
        ]
        response = await asyncio.to_thread(
            self._client._complete_multipart_upload,
            bucket,
            storage_key,
            provider_upload_id,
            multipart_parts,
        )
        head_response = await asyncio.to_thread(
            self._client.stat_object,
            bucket,
            storage_key,
        )
        return CompletedMultipartUpload(
            etag=str(response.etag) if response.etag is not None else None,
            size_bytes=int(head_response.size) if head_response.size is not None else None,
        )

    async def presign_download(
        self,
        *,
        bucket: str,
        storage_key: str,
        filename: str,
        expires_in_seconds: int,
    ) -> PresignedDownload:
        safe_filename = filename.replace("/", "_").replace("\\", "_").replace('"', "_")
        ascii_filename = safe_filename.encode("ascii", "ignore").decode() or "download"
        content_disposition = (
            f'attachment; filename="{ascii_filename}"; '
            f"filename*=UTF-8''{quote(safe_filename, safe='')}"
        )
        download_url = await asyncio.to_thread(
            self._client.presigned_get_object,
            bucket,
            storage_key,
            expires=timedelta(seconds=expires_in_seconds),
            response_headers={"response-content-disposition": content_disposition},
        )
        return PresignedDownload(
            download_url=str(download_url),
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
        return await asyncio.to_thread(self._calculate_sha256, bucket, storage_key)

    async def copy_object(
        self,
        *,
        bucket: str,
        source_key: str,
        destination_key: str,
    ) -> None:
        await asyncio.to_thread(
            self._client.copy_object,
            bucket,
            destination_key,
            CopySource(bucket, source_key),
        )

    async def delete_object(
        self,
        *,
        bucket: str,
        storage_key: str,
    ) -> None:
        await asyncio.to_thread(
            self._client.remove_object,
            bucket,
            storage_key,
        )

    async def read_object_bytes(
        self,
        *,
        bucket: str,
        storage_key: str,
        max_bytes: int,
    ) -> bytes:
        return await asyncio.to_thread(self._read_object_bytes, bucket, storage_key, max_bytes)

    async def put_object_bytes(
        self,
        *,
        bucket: str,
        storage_key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        await asyncio.to_thread(self._put_object_bytes, bucket, storage_key, content, content_type)

    def _ensure_bucket(self, bucket: str) -> None:
        if self._client.bucket_exists(bucket):
            return
        self._client.make_bucket(bucket, location=self.settings.s3_region)

    def _calculate_sha256(self, bucket: str, storage_key: str) -> str:
        response = self._client.get_object(bucket, storage_key)
        digest = hashlib.sha256()
        try:
            for chunk in response.stream(1024 * 1024):
                if chunk:
                    digest.update(chunk)
        finally:
            response.close()
            response.release_conn()
        return digest.hexdigest()

    def _read_object_bytes(self, bucket: str, storage_key: str, max_bytes: int) -> bytes:
        response = self._client.get_object(bucket, storage_key)
        chunks: list[bytes] = []
        remaining = max(max_bytes, 0)
        try:
            for chunk in response.stream(64 * 1024):
                if remaining <= 0:
                    break
                if not chunk:
                    continue
                chunks.append(chunk[:remaining])
                remaining -= len(chunks[-1])
        finally:
            response.close()
            response.release_conn()
        return b"".join(chunks)

    def _put_object_bytes(
        self,
        bucket: str,
        storage_key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        self._ensure_bucket(bucket)
        self._client.put_object(
            bucket,
            storage_key,
            BytesIO(content),
            length=len(content),
            content_type=content_type,
        )
