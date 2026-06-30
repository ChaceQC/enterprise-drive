from __future__ import annotations

import asyncio
import hashlib
from datetime import timedelta
from typing import Any
from urllib.parse import quote

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]

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
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ),
        )

    async def create_multipart_upload(
        self,
        *,
        bucket: str,
        storage_key: str,
        content_type: str | None,
    ) -> MultipartUpload:
        await asyncio.to_thread(self._ensure_bucket, bucket)
        response = await asyncio.to_thread(
            self._client.create_multipart_upload,
            Bucket=bucket,
            Key=storage_key,
            ContentType=content_type or "application/octet-stream",
        )
        provider_upload_id = str(response["UploadId"])
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
        params = {
            "Bucket": bucket,
            "Key": storage_key,
            "UploadId": provider_upload_id,
            "PartNumber": part_no,
        }
        upload_url = await asyncio.to_thread(
            self._client.generate_presigned_url,
            "upload_part",
            Params=params,
            ExpiresIn=expires_in_seconds,
            HttpMethod="PUT",
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
            self._client.abort_multipart_upload,
            Bucket=bucket,
            Key=storage_key,
            UploadId=provider_upload_id,
        )

    async def complete_multipart_upload(
        self,
        *,
        bucket: str,
        storage_key: str,
        provider_upload_id: str,
        parts: list[CompletedUploadPart],
    ) -> CompletedMultipartUpload:
        response = await asyncio.to_thread(
            self._client.complete_multipart_upload,
            Bucket=bucket,
            Key=storage_key,
            UploadId=provider_upload_id,
            MultipartUpload={
                "Parts": [
                    {"PartNumber": part.part_no, "ETag": part.etag}
                    for part in sorted(parts, key=lambda item: item.part_no)
                ]
            },
        )
        head_response = await asyncio.to_thread(
            self._client.head_object,
            Bucket=bucket,
            Key=storage_key,
        )
        return CompletedMultipartUpload(
            etag=str(response.get("ETag")) if response.get("ETag") is not None else None,
            size_bytes=int(head_response["ContentLength"]),
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
            self._client.generate_presigned_url,
            "get_object",
            Params={
                "Bucket": bucket,
                "Key": storage_key,
                "ResponseContentDisposition": content_disposition,
            },
            ExpiresIn=expires_in_seconds,
            HttpMethod="GET",
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

    def _ensure_bucket(self, bucket: str) -> None:
        try:
            self._client.head_bucket(Bucket=bucket)
        except Exception:
            kwargs: dict[str, Any] = {"Bucket": bucket}
            if self.settings.s3_region != "us-east-1":
                kwargs["CreateBucketConfiguration"] = {
                    "LocationConstraint": self.settings.s3_region
                }
            self._client.create_bucket(**kwargs)

    def _calculate_sha256(self, bucket: str, storage_key: str) -> str:
        response = self._client.get_object(Bucket=bucket, Key=storage_key)
        digest = hashlib.sha256()
        body = response["Body"]
        try:
            for chunk in body.iter_chunks(chunk_size=1024 * 1024):
                if chunk:
                    digest.update(chunk)
        finally:
            body.close()
        return digest.hexdigest()
