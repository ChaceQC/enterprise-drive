from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import utc_now
from app.infrastructure.storage.testing import InMemoryStorageAdapter
from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditContext
from app.modules.audit.service import AuditService
from app.modules.upload.cleanup import UploadCleanupService
from app.modules.upload.models import UploadSession
from app.modules.upload.repository import UploadRepository
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


async def create_upload_session(
    client: AsyncClient,
    token: str,
    *,
    space_id: str,
    parent_id: str,
    file_name: str,
    content_hash: str,
) -> UUID:
    response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": token},
        json={
            "space_id": space_id,
            "parent_id": parent_id,
            "file_name": file_name,
            "size_bytes": 1024,
            "content_hash": content_hash,
            "hash_algo": "sha256",
        },
    )
    assert response.status_code == 201
    return UUID(response.json()["session_id"])


@pytest.mark.asyncio
async def test_expire_upload_sessions_marks_active_session_and_cleans_storage(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="expired-upload-space")
    session_id = await create_upload_session(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="过期上传.bin",
        content_hash="e" * 64,
    )

    async with session_factory() as session:
        upload_session = (
            await session.execute(select(UploadSession).where(UploadSession.id == session_id))
        ).scalar_one()
        upload_session.status = "uploading"
        upload_session.expires_at = utc_now() - timedelta(minutes=1)
        provider_upload_id = str(upload_session.provider_upload_id)
        storage_key = upload_session.storage_key
        storage_adapter.object_contents[(settings.s3_bucket, storage_key)] = b"partial"
        await session.commit()

    async with session_factory() as session:
        service = UploadCleanupService(
            repository=UploadRepository(session),
            storage=storage_adapter,
            audit_service=AuditService(repository=AuditRepository(session)),
        )
        result = await service.expire_upload_sessions(
            tenant_id=UUID(str(space["tenant_id"])),
            limit=10,
            audit_context=AuditContext(request_id="req_upload_expire"),
        )

    assert result.to_dict() == {
        "scanned": 1,
        "expired": 1,
        "skipped": 0,
        "aborted": 1,
        "deleted": 1,
        "storage_errors": 0,
    }
    assert provider_upload_id in storage_adapter.aborted_uploads
    assert storage_adapter.deleted_objects == [(settings.s3_bucket, storage_key)]
    assert (settings.s3_bucket, storage_key) not in storage_adapter.object_contents

    async with session_factory() as session:
        upload_session = (
            await session.execute(select(UploadSession).where(UploadSession.id == session_id))
        ).scalar_one()
        audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "upload.expired"))
        ).scalar_one()
        outbox_event = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.event_type == "audit.upload.expired")
            )
        ).scalar_one()

    assert upload_session.status == "expired"
    assert audit.actor_id is None
    assert audit.actor_type == "system"
    assert audit.request_id == "req_upload_expire"
    assert audit.metadata_json["cleanup_status"] == "cleaned"
    assert audit.metadata_json["cleanup_errors"] == []
    assert audit.metadata_json["has_provider_upload"] is True
    assert outbox_event.aggregate_type == "audit_log"


@pytest.mark.asyncio
async def test_expire_upload_sessions_ignores_terminal_and_not_due_sessions(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="expire-skip-space")
    completed_session_id = await create_upload_session(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="已完成.bin",
        content_hash="a" * 64,
    )
    active_session_id = await create_upload_session(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="未到期.bin",
        content_hash="b" * 64,
    )

    async with session_factory() as session:
        sessions = (
            (
                await session.execute(
                    select(UploadSession).where(
                        UploadSession.id.in_([completed_session_id, active_session_id])
                    )
                )
            )
            .scalars()
            .all()
        )
        by_id = {item.id: item for item in sessions}
        by_id[completed_session_id].status = "completed"
        by_id[completed_session_id].expires_at = utc_now() - timedelta(minutes=1)
        by_id[active_session_id].status = "uploading"
        by_id[active_session_id].expires_at = utc_now() + timedelta(minutes=10)
        await session.commit()

    async with session_factory() as session:
        service = UploadCleanupService(
            repository=UploadRepository(session),
            storage=storage_adapter,
            audit_service=AuditService(repository=AuditRepository(session)),
        )
        result = await service.expire_upload_sessions(
            tenant_id=UUID(str(space["tenant_id"])),
            limit=10,
        )

    assert result.to_dict() == {
        "scanned": 0,
        "expired": 0,
        "skipped": 0,
        "aborted": 0,
        "deleted": 0,
        "storage_errors": 0,
    }
    assert storage_adapter.aborted_uploads == set()
    assert storage_adapter.deleted_objects == []

    async with session_factory() as session:
        sessions = (
            (
                await session.execute(
                    select(UploadSession).where(
                        UploadSession.id.in_([completed_session_id, active_session_id])
                    )
                )
            )
            .scalars()
            .all()
        )
        audits = (await session.execute(select(AuditLog))).scalars().all()

    by_id = {item.id: item for item in sessions}
    assert by_id[completed_session_id].status == "completed"
    assert by_id[active_session_id].status == "uploading"
    assert "upload.expired" not in {audit.action for audit in audits}
