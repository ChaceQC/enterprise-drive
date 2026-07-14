from __future__ import annotations

from io import BytesIO
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.config import Settings
from app.infrastructure.storage import s3 as s3_module
from app.infrastructure.storage.s3 import S3StorageAdapter


class RecordingMinio:
    instances: list[RecordingMinio] = []

    def __init__(
        self,
        endpoint: str,
        *,
        access_key: str,
        secret_key: str,
        region: str,
        secure: bool,
    ) -> None:
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.secure = secure
        self.put_calls: list[tuple[str, str, int, str]] = []
        self.upload_presign_calls: list[tuple[str, str, str, dict[str, str]]] = []
        self.download_presign_calls: list[tuple[str, str]] = []
        self.instances.append(self)

    def bucket_exists(self, bucket: str) -> bool:
        return True

    def put_object(
        self,
        bucket: str,
        storage_key: str,
        data: BytesIO,
        *,
        length: int,
        content_type: str,
    ) -> None:
        assert data.read() == b"content"
        self.put_calls.append((bucket, storage_key, length, content_type))

    def get_presigned_url(
        self,
        method: str,
        bucket: str,
        storage_key: str,
        *,
        expires: Any,
        extra_query_params: dict[str, str],
    ) -> str:
        del expires
        self.upload_presign_calls.append((method, bucket, storage_key, extra_query_params))
        return (
            f"{self._scheme}://{self.endpoint}/{bucket}/{storage_key}"
            f"?partNumber={extra_query_params['partNumber']}"
            f"&uploadId={extra_query_params['uploadId']}"
        )

    def presigned_get_object(
        self,
        bucket: str,
        storage_key: str,
        *,
        expires: Any,
        response_headers: dict[str, str],
    ) -> str:
        del expires, response_headers
        self.download_presign_calls.append((bucket, storage_key))
        return f"{self._scheme}://{self.endpoint}/{bucket}/{storage_key}"

    @property
    def _scheme(self) -> str:
        return "https" if self.secure else "http"


@pytest.fixture
def recording_minio(monkeypatch: pytest.MonkeyPatch) -> None:
    RecordingMinio.instances = []
    monkeypatch.setattr(s3_module, "Minio", RecordingMinio)


@pytest.mark.asyncio
async def test_storage_uses_internal_client_and_presign_uses_public_client(
    recording_minio: None,
) -> None:
    del recording_minio
    settings = Settings(
        environment="test",
        secret_key="test-secret",
        s3_endpoint_url="http://minio:9000",
        s3_public_endpoint_url="https://files.example.test:9443",
        s3_access_key_id="access-key",
        s3_secret_access_key="secret-key",
        s3_region="ap-northeast-1",
    )
    storage = S3StorageAdapter(settings=settings)

    assert len(RecordingMinio.instances) == 2
    internal_client, public_client = RecordingMinio.instances
    assert (internal_client.endpoint, internal_client.secure, internal_client.region) == (
        "minio:9000",
        False,
        "ap-northeast-1",
    )
    assert (public_client.endpoint, public_client.secure, public_client.region) == (
        "files.example.test:9443",
        True,
        "ap-northeast-1",
    )

    await storage.put_object_bytes(
        bucket="drive",
        storage_key="objects/file.txt",
        content=b"content",
        content_type="text/plain",
    )
    upload = await storage.presign_upload_part(
        bucket="drive",
        storage_key="uploads/file.txt",
        provider_upload_id="upload-id",
        part_no=3,
        expires_in_seconds=60,
    )
    download = await storage.presign_download(
        bucket="drive",
        storage_key="objects/file.txt",
        filename="文件.txt",
        expires_in_seconds=60,
    )

    assert internal_client.put_calls == [
        ("drive", "objects/file.txt", len(b"content"), "text/plain")
    ]
    assert internal_client.upload_presign_calls == []
    assert internal_client.download_presign_calls == []
    assert public_client.upload_presign_calls == [
        (
            "PUT",
            "drive",
            "uploads/file.txt",
            {"partNumber": "3", "uploadId": "upload-id"},
        )
    ]
    assert public_client.download_presign_calls == [("drive", "objects/file.txt")]
    assert (urlsplit(upload.upload_url).scheme, urlsplit(upload.upload_url).netloc) == (
        "https",
        "files.example.test:9443",
    )
    assert (urlsplit(download.download_url).scheme, urlsplit(download.download_url).netloc) == (
        "https",
        "files.example.test:9443",
    )


@pytest.mark.asyncio
async def test_presign_endpoint_falls_back_to_internal_endpoint(
    recording_minio: None,
) -> None:
    del recording_minio
    settings = Settings(
        environment="test",
        secret_key="test-secret",
        s3_endpoint_url="https://storage.internal.test:9000",
        s3_access_key_id="access-key",
        s3_secret_access_key="secret-key",
        s3_region="us-east-1",
    )
    storage = S3StorageAdapter(settings=settings)

    assert len(RecordingMinio.instances) == 2
    internal_client, presign_client = RecordingMinio.instances
    assert (internal_client.endpoint, internal_client.secure) == (
        "storage.internal.test:9000",
        True,
    )
    assert (presign_client.endpoint, presign_client.secure) == (
        "storage.internal.test:9000",
        True,
    )

    upload = await storage.presign_upload_part(
        bucket="drive",
        storage_key="uploads/file.txt",
        provider_upload_id="upload-id",
        part_no=1,
        expires_in_seconds=60,
    )
    download = await storage.presign_download(
        bucket="drive",
        storage_key="objects/file.txt",
        filename="file.txt",
        expires_in_seconds=60,
    )

    assert urlsplit(upload.upload_url).netloc == "storage.internal.test:9000"
    assert urlsplit(download.download_url).netloc == "storage.internal.test:9000"


@pytest.mark.asyncio
async def test_real_minio_presigned_urls_use_public_host_scheme_and_region() -> None:
    settings = Settings(
        environment="test",
        secret_key="test-secret",
        s3_endpoint_url="http://minio:9000",
        s3_public_endpoint_url="https://files.example.test:9443",
        s3_access_key_id="access-key",
        s3_secret_access_key="secret-key",
        s3_region="ap-northeast-1",
    )
    storage = S3StorageAdapter(settings=settings)

    upload = await storage.presign_upload_part(
        bucket="drive",
        storage_key="uploads/file.txt",
        provider_upload_id="upload-id",
        part_no=2,
        expires_in_seconds=60,
    )
    download = await storage.presign_download(
        bucket="drive",
        storage_key="objects/file.txt",
        filename="file.txt",
        expires_in_seconds=60,
    )

    for url in (upload.upload_url, download.download_url):
        parsed = urlsplit(url)
        credential = parse_qs(parsed.query)["X-Amz-Credential"][0]
        assert parsed.scheme == "https"
        assert parsed.netloc == "files.example.test:9443"
        assert "/ap-northeast-1/s3/aws4_request" in credential
