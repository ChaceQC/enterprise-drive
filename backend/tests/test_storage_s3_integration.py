from __future__ import annotations

import hashlib
import os
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from minio import Minio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.infrastructure.storage.base import CompletedUploadPart
from app.infrastructure.storage.s3 import S3StorageAdapter
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.file.blob_cleanup import BlobCleanupService
from app.modules.file.repository import FileRepository
from tests.helpers import session_factory as session_factory

pytestmark = pytest.mark.integration


def _env(primary: str, legacy: str, default: str) -> str:
    return os.getenv(primary) or os.getenv(legacy) or default


def _s3_settings() -> Settings:
    return Settings(
        environment="test",
        secret_key="test-secret",
        s3_endpoint_url=_env(
            "DRIVE_TEST_S3_ENDPOINT",
            "DRIVE_TEST_MINIO_ENDPOINT",
            "http://127.0.0.1:19000",
        ),
        s3_access_key_id=_env(
            "DRIVE_TEST_S3_ACCESS_KEY",
            "DRIVE_TEST_MINIO_ACCESS_KEY",
            "drive-dev",
        ),
        s3_secret_access_key=_env(
            "DRIVE_TEST_S3_SECRET_KEY",
            "DRIVE_TEST_MINIO_SECRET_KEY",
            "drive-dev-password",
        ),
        s3_bucket=_env(
            "DRIVE_TEST_S3_BUCKET",
            "DRIVE_TEST_MINIO_BUCKET",
            f"enterprise-drive-test-{uuid4()}",
        ),
        s3_region=_env("DRIVE_TEST_S3_REGION", "DRIVE_TEST_MINIO_REGION", "us-east-1"),
    )


def _s3_client(settings: Settings) -> Minio:
    parsed_endpoint = urlsplit(settings.s3_endpoint_url)
    endpoint = parsed_endpoint.netloc or parsed_endpoint.path
    return Minio(
        endpoint,
        access_key=settings.s3_access_key_id,
        secret_key=settings.s3_secret_access_key,
        region=settings.s3_region,
        secure=parsed_endpoint.scheme == "https",
    )


@pytest.fixture(scope="module")
def s3_settings() -> Settings:
    if (os.getenv("DRIVE_RUN_S3_TESTS") or os.getenv("DRIVE_RUN_MINIO_TESTS")) != "1":
        pytest.skip("set DRIVE_RUN_S3_TESTS=1 to run S3-compatible integration tests")
    settings = _s3_settings()
    client = _s3_client(settings)
    if client.bucket_exists(settings.s3_bucket):
        for item in client.list_objects(settings.s3_bucket, recursive=True):
            if item.object_name is not None:
                client.remove_object(settings.s3_bucket, item.object_name)
    else:
        client.make_bucket(settings.s3_bucket, location=settings.s3_region)
    return settings


@pytest.fixture
def storage_adapter(s3_settings: Settings) -> S3StorageAdapter:
    return S3StorageAdapter(settings=s3_settings)


@pytest.mark.asyncio
async def test_s3_storage_adapter_supports_core_object_operations(
    s3_settings: Settings,
    storage_adapter: S3StorageAdapter,
) -> None:
    key_prefix = f"integration/{uuid4()}"
    source_key = f"{key_prefix}/a-source.txt"
    destination_key = f"{key_prefix}/b-destination.txt"
    content = b"hello real s3 compatible storage"

    await storage_adapter.put_object_bytes(
        bucket=s3_settings.s3_bucket,
        storage_key=source_key,
        content=content,
        content_type="text/plain",
    )
    assert (
        await storage_adapter.read_object_bytes(
            bucket=s3_settings.s3_bucket,
            storage_key=source_key,
            max_bytes=1024,
        )
        == content
    )
    assert (
        await storage_adapter.calculate_object_hash(
            bucket=s3_settings.s3_bucket,
            storage_key=source_key,
            hash_algo="sha256",
        )
        == hashlib.sha256(content).hexdigest()
    )

    await storage_adapter.copy_object(
        bucket=s3_settings.s3_bucket,
        source_key=source_key,
        destination_key=destination_key,
    )
    listed_keys = {
        item.storage_key
        for item in await storage_adapter.list_objects(
            bucket=s3_settings.s3_bucket,
            prefix=key_prefix,
            limit=10,
        )
    }
    assert source_key in listed_keys
    assert destination_key in listed_keys

    after_source = await storage_adapter.list_objects(
        bucket=s3_settings.s3_bucket,
        prefix=key_prefix,
        limit=10,
        start_after=source_key,
    )
    assert destination_key in {item.storage_key for item in after_source}

    presigned = await storage_adapter.presign_download(
        bucket=s3_settings.s3_bucket,
        storage_key=destination_key,
        filename="下载.txt",
        expires_in_seconds=60,
    )
    assert "X-Amz-Signature=" in presigned.download_url
    get_response = httpx.get(presigned.download_url)
    assert get_response.status_code == 200
    assert get_response.content == content
    range_response = httpx.get(
        presigned.download_url,
        headers={"Range": "bytes=1-4"},
    )
    assert range_response.status_code == 206
    assert range_response.content == content[1:5]

    await storage_adapter.delete_object(
        bucket=s3_settings.s3_bucket,
        storage_key=source_key,
    )
    await storage_adapter.delete_object(
        bucket=s3_settings.s3_bucket,
        storage_key=destination_key,
    )

    remaining = await storage_adapter.list_objects(
        bucket=s3_settings.s3_bucket,
        prefix=key_prefix,
        limit=10,
    )
    assert source_key not in {item.storage_key for item in remaining}
    assert destination_key not in {item.storage_key for item in remaining}


@pytest.mark.asyncio
async def test_s3_storage_adapter_multipart_standard_http_control(
    s3_settings: Settings,
    storage_adapter: S3StorageAdapter,
) -> None:
    storage_key = f"integration/{uuid4()}/multipart.bin"
    upload = await storage_adapter.create_multipart_upload(
        bucket=s3_settings.s3_bucket,
        storage_key=storage_key,
        content_type="application/octet-stream",
    )
    presigned = await storage_adapter.presign_upload_part(
        bucket=s3_settings.s3_bucket,
        storage_key=storage_key,
        provider_upload_id=upload.provider_upload_id,
        part_no=1,
        expires_in_seconds=60,
    )
    assert "uploadId=" in presigned.upload_url

    await storage_adapter.abort_multipart_upload(
        bucket=s3_settings.s3_bucket,
        storage_key=storage_key,
        provider_upload_id=upload.provider_upload_id,
    )

    upload = await storage_adapter.create_multipart_upload(
        bucket=s3_settings.s3_bucket,
        storage_key=storage_key,
        content_type="application/octet-stream",
    )
    part_content = b"x" * (5 * 1024 * 1024)
    presigned = await storage_adapter.presign_upload_part(
        bucket=s3_settings.s3_bucket,
        storage_key=storage_key,
        provider_upload_id=upload.provider_upload_id,
        part_no=1,
        expires_in_seconds=60,
    )
    put_response = httpx.put(presigned.upload_url, content=part_content)
    assert put_response.status_code == 200
    etag = put_response.headers["etag"].strip('"')
    completed = await storage_adapter.complete_multipart_upload(
        bucket=s3_settings.s3_bucket,
        storage_key=storage_key,
        provider_upload_id=upload.provider_upload_id,
        parts=[CompletedUploadPart(part_no=1, etag=etag, size_bytes=len(part_content))],
    )

    assert completed.size_bytes == len(part_content)
    assert (
        await storage_adapter.calculate_object_hash(
            bucket=s3_settings.s3_bucket,
            storage_key=storage_key,
            hash_algo="sha256",
        )
        == hashlib.sha256(part_content).hexdigest()
    )
    await storage_adapter.delete_object(bucket=s3_settings.s3_bucket, storage_key=storage_key)


@pytest.mark.asyncio
async def test_orphan_cleanup_uses_real_s3_list_and_delete(
    s3_settings: Settings,
    storage_adapter: S3StorageAdapter,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = uuid4()
    orphan_hash = "a" * 64
    orphan_key = f"objects/{tenant_id}/{orphan_hash[:2]}/{orphan_hash}"
    await storage_adapter.put_object_bytes(
        bucket=s3_settings.s3_bucket,
        storage_key=orphan_key,
        content=b"orphan",
        content_type="application/octet-stream",
    )

    async with session_factory() as session:
        service = BlobCleanupService(
            repository=FileRepository(session),
            storage=storage_adapter,
            bucket=s3_settings.s3_bucket,
            audit_service=AuditService(repository=AuditRepository(session)),
        )
        dry_run = await service.cleanup_orphaned_objects(
            tenant_id=UUID(str(tenant_id)),
            limit=10,
            dry_run=True,
        )
        cleaned = await service.cleanup_orphaned_objects(
            tenant_id=UUID(str(tenant_id)),
            limit=10,
            dry_run=False,
        )

    assert dry_run.orphaned == 1
    assert dry_run.dry_run == 1
    assert cleaned.cleaned == 1
    remaining = await storage_adapter.list_objects(
        bucket=s3_settings.s3_bucket,
        prefix=f"objects/{tenant_id}/",
        limit=10,
    )
    assert orphan_key not in {item.storage_key for item in remaining}
