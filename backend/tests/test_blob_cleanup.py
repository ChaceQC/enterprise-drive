from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.infrastructure.storage.testing import InMemoryStorageAdapter
from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditContext
from app.modules.audit.service import AuditService
from app.modules.file.blob_cleanup import BlobCleanupService
from app.modules.file.models import FileBlob, FileVersion, Node
from app.modules.file.repository import FileRepository
from app.modules.upload.models import UploadSession
from app.workers import file_tasks
from tests.helpers import (
    client as client,
)
from tests.helpers import (
    create_space,
    login,
    seed_admin,
)
from tests.helpers import (
    session_factory as session_factory,
)
from tests.helpers import (
    settings as settings,
)
from tests.helpers import (
    storage_adapter as storage_adapter,
)


class FailingDeleteStorageAdapter(InMemoryStorageAdapter):
    async def delete_object(self, *, bucket: str, storage_key: str) -> None:
        raise RuntimeError("delete failed")


async def create_blob(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: str,
    content_hash: str,
    size_bytes: int = 1024,
    ref_count: int = 0,
    status: str = "active",
) -> UUID:
    async with session_factory() as session:
        blob = FileBlob(
            tenant_id=UUID(tenant_id),
            hash_algo="sha256",
            content_hash=content_hash,
            size_bytes=size_bytes,
            storage_key=f"objects/test/{content_hash[:2]}/{content_hash}",
            mime_type="application/octet-stream",
            ref_count=ref_count,
            status=status,
        )
        session.add(blob)
        await session.commit()
        return blob.id


@pytest.mark.asyncio
async def test_cleanup_unreferenced_blobs_deletes_object_and_metadata(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="blob-cleanup-space")
    tenant_id = str(space["tenant_id"])
    content_hash = "1" * 64
    blob_id = await create_blob(
        session_factory,
        tenant_id=tenant_id,
        content_hash=content_hash,
    )
    storage_key = f"objects/test/{content_hash[:2]}/{content_hash}"
    storage_adapter.object_contents[(settings.s3_bucket, storage_key)] = b"unused"

    async with session_factory() as session:
        service = BlobCleanupService(
            repository=FileRepository(session),
            storage=storage_adapter,
            bucket=settings.s3_bucket,
            audit_service=AuditService(repository=AuditRepository(session)),
        )
        result = await service.cleanup_unreferenced_blobs(
            tenant_id=UUID(tenant_id),
            limit=10,
            audit_context=AuditContext(request_id="req_blob_cleanup"),
        )

    assert result.to_dict() == {
        "scanned": 1,
        "claimed": 1,
        "cleaned": 1,
        "skipped": 0,
        "storage_errors": 0,
        "db_conflicts": 0,
    }
    assert storage_adapter.deleted_objects == [(settings.s3_bucket, storage_key)]
    assert (settings.s3_bucket, storage_key) not in storage_adapter.object_contents

    async with session_factory() as session:
        blob = (
            await session.execute(select(FileBlob).where(FileBlob.id == blob_id))
        ).scalar_one_or_none()
        audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "file.blob.cleaned"))
        ).scalar_one()
        outbox_event = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.event_type == "audit.file.blob.cleaned")
            )
        ).scalar_one()

    assert blob is None
    assert audit.actor_id is None
    assert audit.actor_type == "system"
    assert audit.request_id == "req_blob_cleanup"
    assert audit.resource_id == blob_id
    assert audit.resource_type == "file_blob"
    assert audit.metadata_json["cleanup_status"] == "cleaned"
    assert "storage_key" not in audit.metadata_json
    assert outbox_event.aggregate_type == "audit_log"


@pytest.mark.asyncio
async def test_cleanup_unreferenced_blobs_restores_active_status_on_storage_failure(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="blob-cleanup-failure-space")
    tenant_id = str(space["tenant_id"])
    blob_id = await create_blob(
        session_factory,
        tenant_id=tenant_id,
        content_hash="2" * 64,
    )
    storage = FailingDeleteStorageAdapter()

    async with session_factory() as session:
        service = BlobCleanupService(
            repository=FileRepository(session),
            storage=storage,
            bucket=settings.s3_bucket,
            audit_service=AuditService(repository=AuditRepository(session)),
        )
        result = await service.cleanup_unreferenced_blobs(
            tenant_id=UUID(tenant_id),
            limit=10,
            audit_context=AuditContext(request_id="req_blob_cleanup_failed"),
        )

    assert result.to_dict() == {
        "scanned": 1,
        "claimed": 1,
        "cleaned": 0,
        "skipped": 0,
        "storage_errors": 1,
        "db_conflicts": 0,
    }

    async with session_factory() as session:
        blob = (await session.execute(select(FileBlob).where(FileBlob.id == blob_id))).scalar_one()
        audit = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "file.blob.cleanup_failed")
            )
        ).scalar_one()

    assert blob.status == "active"
    assert blob.ref_count == 0
    assert audit.result == "error"
    assert audit.request_id == "req_blob_cleanup_failed"
    assert audit.metadata_json["reason"] == "storage_delete_failed"


@pytest.mark.asyncio
async def test_cleanup_unreferenced_blobs_skips_blob_with_versions(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="blob-cleanup-referenced-space")
    tenant_id = str(space["tenant_id"])
    blob_id = await create_blob(
        session_factory,
        tenant_id=tenant_id,
        content_hash="3" * 64,
        ref_count=0,
    )

    async with session_factory() as session:
        node = Node(
            tenant_id=UUID(tenant_id),
            space_id=UUID(str(space["id"])),
            parent_id=UUID(str(space["root_node_id"])),
            owner_id=UUID(str(space["owner_id"])),
            node_type="file",
            name="仍被版本引用.bin",
            normalized_name="仍被版本引用.bin",
        )
        session.add(node)
        await session.flush()
        version = FileVersion(
            tenant_id=UUID(tenant_id),
            node_id=node.id,
            blob_id=blob_id,
            version_no=1,
            size_bytes=1024,
            mime_type="application/octet-stream",
            created_by=UUID(str(space["owner_id"])),
        )
        session.add(version)
        await session.flush()
        node.current_version_id = version.id
        await session.commit()

    async with session_factory() as session:
        service = BlobCleanupService(
            repository=FileRepository(session),
            storage=storage_adapter,
            bucket=settings.s3_bucket,
            audit_service=AuditService(repository=AuditRepository(session)),
        )
        result = await service.cleanup_unreferenced_blobs(
            tenant_id=UUID(tenant_id),
            limit=10,
        )

    assert result.to_dict() == {
        "scanned": 0,
        "claimed": 0,
        "cleaned": 0,
        "skipped": 0,
        "storage_errors": 0,
        "db_conflicts": 0,
    }
    assert storage_adapter.deleted_objects == []

    async with session_factory() as session:
        blob = (await session.execute(select(FileBlob).where(FileBlob.id == blob_id))).scalar_one()
        audits = (await session.execute(select(AuditLog))).scalars().all()

    assert blob.status == "active"
    assert "file.blob.cleaned" not in {audit.action for audit in audits}


@pytest.mark.asyncio
async def test_blob_cleanup_worker_aggregates_tenant_results(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="blob-cleanup-worker-space")
    tenant_id = str(space["tenant_id"])
    content_hash = "4" * 64
    await create_blob(
        session_factory,
        tenant_id=tenant_id,
        content_hash=content_hash,
    )
    storage_key = f"objects/test/{content_hash[:2]}/{content_hash}"
    storage_adapter.object_contents[(settings.s3_bucket, storage_key)] = b"worker"

    monkeypatch.setattr(file_tasks, "get_settings", lambda: settings)
    monkeypatch.setattr(file_tasks, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(file_tasks, "S3StorageAdapter", lambda *, settings: storage_adapter)

    result = await file_tasks._cleanup_unreferenced_blobs(
        tenant_id=UUID(tenant_id),
        limit=10,
        request_id="req_blob_cleanup_worker",
    )

    assert result == {
        "scanned": 1,
        "claimed": 1,
        "cleaned": 1,
        "skipped": 0,
        "storage_errors": 0,
        "db_conflicts": 0,
    }
    assert storage_adapter.deleted_objects == [(settings.s3_bucket, storage_key)]

    async with session_factory() as session:
        audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "file.blob.cleaned"))
        ).scalar_one()

    assert audit.request_id == "req_blob_cleanup_worker"


@pytest.mark.asyncio
async def test_init_upload_rejects_deleting_blob_to_avoid_reusing_gc_candidate(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="blob-deleting-upload-space")
    tenant_id = str(space["tenant_id"])
    content_hash = "5" * 64
    await create_blob(
        session_factory,
        tenant_id=tenant_id,
        content_hash=content_hash,
        status="deleting",
    )

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "正在清理.bin",
            "size_bytes": 1024,
            "content_hash": content_hash,
            "hash_algo": "sha256",
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "BLOB_DELETING"

    async with session_factory() as session:
        upload_sessions = (await session.execute(select(UploadSession))).scalars().all()

    assert upload_sessions == []
