from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from scripts import object_storage_admin as admin_module
from scripts.object_storage_admin import (
    ObjectStorageAdminError,
    S3Connection,
    initialize_storage,
    inventory_storage,
    migrate_storage,
    probe_get,
    probe_put,
)


@dataclass
class StoredObject:
    content: bytes
    content_type: str = "application/octet-stream"
    metadata: dict[str, str] | None = None
    tags: dict[str, str] | None = None


class ObjectBody(BytesIO):
    def stream(self, chunk_size: int) -> list[bytes]:
        return [
            self.getvalue()[offset : offset + chunk_size]
            for offset in range(0, len(self.getvalue()), chunk_size)
        ]

    def release_conn(self) -> None:
        return None


class FakeS3Client:
    def __init__(
        self,
        objects: dict[str, StoredObject] | None = None,
        *,
        incomplete_uploads: list[tuple[str, str]] | None = None,
    ) -> None:
        self.objects = objects or {}
        self.incomplete_uploads = incomplete_uploads or []
        self.bucket_exists_value = True
        self.made_buckets: list[tuple[str, str]] = []
        self.removed: list[str] = []
        self.put_calls: list[dict[str, Any]] = []

    def bucket_exists(self, bucket: str) -> bool:
        del bucket
        return self.bucket_exists_value

    def make_bucket(self, bucket: str, *, location: str) -> None:
        self.made_buckets.append((bucket, location))
        self.bucket_exists_value = True

    def list_objects(
        self,
        bucket: str,
        *,
        prefix: str,
        recursive: bool,
    ) -> list[SimpleNamespace]:
        del bucket
        assert recursive is True
        return [
            SimpleNamespace(object_name=key)
            for key in sorted(self.objects)
            if key.startswith(prefix)
        ]

    def stat_object(self, bucket: str, key: str) -> SimpleNamespace:
        del bucket
        stored = self.objects[key]
        metadata = {f"X-Amz-Meta-{name}": value for name, value in (stored.metadata or {}).items()}
        metadata["Content-Type"] = stored.content_type
        return SimpleNamespace(
            size=len(stored.content),
            content_type=stored.content_type,
            metadata=metadata,
        )

    def get_object_tags(self, bucket: str, key: str) -> dict[str, str] | None:
        del bucket
        return self.objects[key].tags

    def get_object(self, bucket: str, key: str) -> ObjectBody:
        del bucket
        return ObjectBody(self.objects[key].content)

    def put_object(
        self,
        bucket: str,
        key: str,
        data: Any,
        *,
        length: int,
        content_type: str,
        metadata: dict[str, str] | None = None,
        tags: dict[str, str] | None = None,
        num_parallel_uploads: int = 3,
    ) -> None:
        del bucket
        content = data.read()
        assert len(content) == length
        self.objects[key] = StoredObject(
            content=content,
            content_type=content_type,
            metadata=dict(metadata or {}),
            tags=dict(tags or {}),
        )
        self.put_calls.append(
            {
                "key": key,
                "content_type": content_type,
                "metadata": dict(metadata or {}),
                "tags": dict(tags or {}),
                "num_parallel_uploads": num_parallel_uploads,
            }
        )

    def remove_object(self, bucket: str, key: str) -> None:
        del bucket
        self.removed.append(key)
        self.objects.pop(key, None)

    def get_presigned_url(
        self,
        method: str,
        bucket: str,
        key: str,
        *,
        expires: Any,
    ) -> str:
        del expires
        return f"https://storage.test/{bucket}/{key}?signed={method}"

    def _list_multipart_uploads(
        self,
        bucket: str,
        *,
        prefix: str,
        max_uploads: int,
    ) -> SimpleNamespace:
        del bucket
        assert max_uploads == 1000
        uploads = [
            SimpleNamespace(object_name=key, upload_id=upload_id)
            for key, upload_id in self.incomplete_uploads
            if key.startswith(prefix)
        ]
        return SimpleNamespace(uploads=uploads, is_truncated=False)


class InitHttpClient:
    def __init__(self, *, allowed_origin: str, cors_enabled: bool = True) -> None:
        self.allowed_origin = allowed_origin
        self.cors_enabled = cors_enabled
        self.content: bytes | None = None
        self.closed = False

    def put(
        self,
        url: str,
        *,
        content: bytes,
        headers: dict[str, str],
    ) -> httpx.Response:
        assert parse_qs(urlsplit(url).query)["signed"] == ["PUT"]
        assert headers["Content-Type"] == "text/plain"
        self.content = bytes(content)
        return httpx.Response(200)

    def get(self, url: str) -> httpx.Response:
        signed = parse_qs(urlsplit(url).query).get("signed")
        if not signed:
            return httpx.Response(403)
        assert signed == ["GET"]
        if self.content is None:
            return httpx.Response(404)
        return httpx.Response(200, content=self.content)

    def options(self, url: str, *, headers: dict[str, str]) -> httpx.Response:
        assert parse_qs(urlsplit(url).query)["signed"] == ["PUT"]
        origin = headers["Origin"]
        if self.cors_enabled and origin == self.allowed_origin:
            return httpx.Response(
                204,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": "GET, PUT",
                },
            )
        return httpx.Response(403)

    def delete(self, url: str) -> httpx.Response:
        assert parse_qs(urlsplit(url).query)["signed"] == ["DELETE"]
        self.content = None
        return httpx.Response(204)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def connection() -> S3Connection:
    return S3Connection(
        endpoint_url="https://user:embedded-secret@storage.test?token=hidden",
        access_key="access-key",
        secret_key="do-not-log-this-secret",
        bucket="drive",
        region="us-east-1",
    )


def test_initialize_storage_checks_signed_private_and_cors_paths(
    connection: S3Connection,
) -> None:
    client = FakeS3Client()
    client.bucket_exists_value = False
    http_client = InitHttpClient(allowed_origin="https://drive.test")

    report = initialize_storage(
        client,  # type: ignore[arg-type]
        connection,
        allowed_origin="https://drive.test",
        denied_origin="https://denied.test",
        http_client=http_client,  # type: ignore[arg-type]
    )

    assert report["status"] == "ok"
    assert report["bucket_created"] is True
    assert all(report["checks"].values())
    assert report["storage"] == {
        "endpoint_url": "https://storage.test",
        "bucket": "drive",
        "region": "us-east-1",
    }
    assert connection.secret_key not in str(report)
    assert client.made_buckets == [("drive", "us-east-1")]
    assert http_client.closed is False


def test_initialize_storage_fails_closed_and_cleans_probe(
    connection: S3Connection,
) -> None:
    client = FakeS3Client()
    http_client = InitHttpClient(
        allowed_origin="https://drive.test",
        cors_enabled=False,
    )

    with pytest.raises(ObjectStorageAdminError, match="allowed CORS preflight"):
        initialize_storage(
            client,  # type: ignore[arg-type]
            connection,
            allowed_origin="https://drive.test",
            denied_origin="https://denied.test",
            http_client=http_client,  # type: ignore[arg-type]
        )

    assert len(client.removed) == 1


def test_inventory_reports_recursive_hash_metadata_and_tags(
    connection: S3Connection,
) -> None:
    client = FakeS3Client(
        {
            "objects/b.txt": StoredObject(b"beta"),
            "objects/a.txt": StoredObject(
                b"alpha",
                content_type="text/plain",
                metadata={"Owner": "alice"},
                tags={"stage": "pilot"},
            ),
        }
    )

    report = inventory_storage(
        client,  # type: ignore[arg-type]
        connection,
        prefix="objects/",
    )

    assert report["object_count"] == 2
    assert report["total_size"] == 9
    assert report["objects"][0] == {
        "key": "objects/a.txt",
        "size": 5,
        "sha256": "8ed3f6ad685b959ead7022518e1af76cd816f8e8ec7ccdda1ed4018e8f2223f8",
        "content_type": "text/plain",
        "user_metadata": {"owner": "alice"},
        "tags": {"stage": "pilot"},
    }


def test_migrate_defaults_to_dry_run_and_reports_incomplete_multipart(
    connection: S3Connection,
) -> None:
    source_client = FakeS3Client(
        {"objects/a.txt": StoredObject(b"alpha")},
        incomplete_uploads=[("uploads/pending.bin", "upload-1")],
    )
    target_client = FakeS3Client()
    target = S3Connection(
        endpoint_url="https://target.test",
        access_key="target-access",
        secret_key="target-secret",
        bucket="drive-target",
    )

    report = migrate_storage(
        source_client,  # type: ignore[arg-type]
        connection,
        target_client,  # type: ignore[arg-type]
        target,
    )

    assert report["mode"] == "dry-run"
    assert report["records"][0]["action"] == "would_copy"
    assert target_client.put_calls == []
    assert report["multipart_uploads"] == {
        "migrated": False,
        "detection": "complete",
        "count": 1,
        "uploads": [{"key": "uploads/pending.bin", "upload_id": "upload-1"}],
        "note": "incomplete multipart uploads are reported but never migrated",
    }


def test_migrate_apply_streams_preserves_and_verifies_object(
    connection: S3Connection,
) -> None:
    source_client = FakeS3Client(
        {
            "objects/a.txt": StoredObject(
                b"alpha",
                content_type="text/plain",
                metadata={"Owner": "alice"},
                tags={"stage": "pilot"},
            )
        }
    )
    target_client = FakeS3Client()
    target_client.bucket_exists_value = False
    target = S3Connection(
        endpoint_url="https://target.test",
        access_key="target-access",
        secret_key="target-secret",
        bucket="drive-target",
    )

    report = migrate_storage(
        source_client,  # type: ignore[arg-type]
        connection,
        target_client,  # type: ignore[arg-type]
        target,
        apply=True,
    )

    assert report["status"] == "ok"
    assert report["records"][0]["action"] == "copied"
    assert all(report["records"][0]["verification"].values())
    assert target_client.put_calls == [
        {
            "key": "objects/a.txt",
            "content_type": "text/plain",
            "metadata": {"owner": "alice"},
            "tags": {"stage": "pilot"},
            "num_parallel_uploads": 1,
        }
    ]
    assert target_client.made_buckets == [("drive-target", "us-east-1")]


def test_migrate_apply_rejects_incomplete_multipart(
    connection: S3Connection,
) -> None:
    source_client = FakeS3Client(
        {"objects/a.txt": StoredObject(b"alpha")},
        incomplete_uploads=[("uploads/pending.bin", "upload-1")],
    )
    target_client = FakeS3Client()
    target = S3Connection(
        endpoint_url="https://target.test",
        access_key="target-access",
        secret_key="target-secret",
        bucket="drive-target",
    )

    report = migrate_storage(
        source_client,  # type: ignore[arg-type]
        connection,
        target_client,  # type: ignore[arg-type]
        target,
        apply=True,
    )

    assert report["status"] == "failed"
    assert report["object_count"] == 0
    assert report["records"] == []
    assert "multipart" in report["blocker"]
    assert target_client.made_buckets == []
    assert target_client.put_calls == []


def test_migrate_refuses_same_storage_location(connection: S3Connection) -> None:
    with pytest.raises(ObjectStorageAdminError, match="identical"):
        migrate_storage(
            FakeS3Client(),  # type: ignore[arg-type]
            connection,
            FakeS3Client(),  # type: ignore[arg-type]
            connection,
        )


def test_probe_put_and_get_use_generic_s3_client(connection: S3Connection) -> None:
    client = FakeS3Client()

    probe_put(
        client,  # type: ignore[arg-type]
        connection,
        key="backup/probe.txt",
        value="备份探针".encode(),
        content_type="text/plain",
    )

    assert (
        probe_get(
            client,  # type: ignore[arg-type]
            connection,
            key="backup/probe.txt",
        )
        == "备份探针".encode()
    )


def test_probe_get_cli_reads_generic_env_and_outputs_only_content(
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    client = FakeS3Client({"backup/probe.txt": StoredObject(b"probe-content")})
    monkeypatch.setenv("DRIVE_S3_ENDPOINT_URL", "https://storage.test")
    monkeypatch.setenv("DRIVE_S3_ACCESS_KEY_ID", "access-key")
    monkeypatch.setenv("DRIVE_S3_SECRET_ACCESS_KEY", "secret-key")
    monkeypatch.setenv("DRIVE_S3_BUCKET", "drive")
    monkeypatch.setattr(admin_module, "build_client", lambda connection: client)

    exit_code = admin_module.main(["probe-get", "--key", "backup/probe.txt"])

    captured = capfd.readouterr()
    assert exit_code == 0
    assert captured.out == "probe-content"
    assert captured.err == ""


def test_cli_failure_does_not_log_secret(
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    client = FakeS3Client()

    def fail_list_objects(*args: Any, **kwargs: Any) -> list[SimpleNamespace]:
        del args, kwargs
        raise RuntimeError("very-secret-value")

    monkeypatch.setattr(client, "list_objects", fail_list_objects)
    monkeypatch.setattr(admin_module, "build_client", lambda connection: client)

    exit_code = admin_module.main(
        [
            "inventory",
            "--endpoint",
            "https://storage.test",
            "--access-key",
            "access-key",
            "--secret-key",
            "very-secret-value",
            "--bucket",
            "drive",
        ]
    )

    captured = capfd.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "very-secret-value" not in captured.err
    assert '"error": "inventory failed: RuntimeError"' in captured.err
