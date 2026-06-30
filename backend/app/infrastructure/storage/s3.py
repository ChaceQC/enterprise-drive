from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import boto3  # type: ignore[import-untyped]

from app.core.config import Settings
from app.core.security import utc_now
from app.infrastructure.storage.base import MultipartUpload, PresignedUploadPart


class S3StorageAdapter:
    def __init__(self, *, settings: Settings) -> None:
        self.settings = settings
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
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
