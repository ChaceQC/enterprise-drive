from __future__ import annotations

import pytest

from app.infrastructure.storage.base import CompletedUploadPart
from app.infrastructure.storage.s3 import S3StorageAdapter
from app.infrastructure.storage.s3_multipart import (
    S3MultipartControlClient,
    S3MultipartControlError,
)


class FakeMinioClient:
    def __init__(self) -> None:
        self.presign_calls: list[tuple[str, str, str, dict[str, str]]] = []

    def get_presigned_url(
        self,
        method: str,
        bucket: str,
        storage_key: str,
        *,
        expires: object,
        extra_query_params: dict[str, str],
    ) -> str:
        self.presign_calls.append((method, bucket, storage_key, extra_query_params))
        return f"https://storage.test/{bucket}/{storage_key}?method={method}"


def test_multipart_control_uses_public_presigned_s3_requests() -> None:
    client = FakeMinioClient()
    control = S3MultipartControlClient(
        client=client,  # type: ignore[arg-type]
        request_timeout_seconds=30,
        presign_expires_seconds=300,
    )
    responses = iter(
        [
            b"<InitiateMultipartUploadResult><UploadId>upload-1</UploadId>"
            b"</InitiateMultipartUploadResult>",
            b"<CompleteMultipartUploadResult><ETag>completed-etag</ETag>"
            b"</CompleteMultipartUploadResult>",
            b"",
        ]
    )
    requests: list[dict[str, object]] = []

    def fake_request(**kwargs: object) -> bytes:
        requests.append(kwargs)
        return next(responses)

    control._request = fake_request  # type: ignore[method-assign]

    upload_id = control.create(
        bucket="bucket",
        storage_key="uploads/file.bin",
        content_type="application/octet-stream",
    )
    completed_etag = control.complete(
        bucket="bucket",
        storage_key="uploads/file.bin",
        provider_upload_id=upload_id,
        parts=[
            CompletedUploadPart(part_no=2, etag='"etag-2"'),
            CompletedUploadPart(part_no=1, etag="etag-1"),
        ],
    )
    control.abort(
        bucket="bucket",
        storage_key="uploads/file.bin",
        provider_upload_id=upload_id,
    )

    assert upload_id == "upload-1"
    assert completed_etag == "completed-etag"
    assert [call[0] for call in client.presign_calls] == ["POST", "POST", "DELETE"]
    assert client.presign_calls[0][3] == {"uploads": ""}
    assert client.presign_calls[1][3] == {"uploadId": "upload-1"}
    assert requests[1]["body"] == (
        b"<CompleteMultipartUpload><Part><PartNumber>1</PartNumber>"
        b'<ETag>"etag-1"</ETag></Part><Part><PartNumber>2</PartNumber>'
        b'<ETag>"etag-2"</ETag></Part></CompleteMultipartUpload>'
    )


def test_multipart_abort_is_idempotent_when_provider_upload_is_missing() -> None:
    control = S3MultipartControlClient(
        client=FakeMinioClient(),  # type: ignore[arg-type]
        request_timeout_seconds=30,
        presign_expires_seconds=300,
    )

    def missing_request(**kwargs: object) -> bytes:
        raise S3MultipartControlError(
            code="NoSuchUpload",
            message="upload no longer exists",
            status_code=404,
        )

    control._request = missing_request  # type: ignore[method-assign]

    control.abort(
        bucket="bucket",
        storage_key="uploads/file.bin",
        provider_upload_id="missing",
    )


def test_multipart_control_rejects_unsafe_xml_entities() -> None:
    control = S3MultipartControlClient(
        client=FakeMinioClient(),  # type: ignore[arg-type]
        request_timeout_seconds=30,
        presign_expires_seconds=300,
    )

    control._request = (  # type: ignore[method-assign]
        lambda **kwargs: (
            b"<!DOCTYPE response [<!ENTITY blocked SYSTEM "
            b'"file:///tmp/fixture-secret">]><InitiateMultipartUploadResult>'
            b"<UploadId>&blocked;</UploadId></InitiateMultipartUploadResult>"
        )
    )

    with pytest.raises(S3MultipartControlError) as exc_info:
        control.create(
            bucket="bucket",
            storage_key="uploads/file.bin",
            content_type="application/octet-stream",
        )

    assert exc_info.value.code == "InvalidS3XmlResponse"


@pytest.mark.asyncio
async def test_storage_adapter_recovers_ambiguous_complete_from_object_stat() -> None:
    adapter = object.__new__(S3StorageAdapter)

    class FailingControl:
        def complete(self, **kwargs: object) -> str | None:
            raise TimeoutError("response lost after provider commit")

    class Stat:
        etag = "recovered-etag"
        size = 5

    class StatClient:
        def stat_object(self, bucket: str, storage_key: str) -> Stat:
            return Stat()

    adapter._multipart_control = FailingControl()  # type: ignore[assignment]
    adapter._client = StatClient()  # type: ignore[assignment]

    completed = await adapter.complete_multipart_upload(
        bucket="bucket",
        storage_key="uploads/file.bin",
        provider_upload_id="upload-1",
        parts=[CompletedUploadPart(part_no=1, etag="etag-1", size_bytes=5)],
    )

    assert completed.etag == "recovered-etag"
    assert completed.size_bytes == 5
