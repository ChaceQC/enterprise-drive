from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import utc_now
from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditContext
from app.modules.audit.service import AuditService
from app.modules.auth.models import Tenant, User
from app.modules.file.models import FileBlob, FileVersion, Node
from app.modules.file.repository import FileRepository
from app.modules.file.trash_cleanup import TrashCleanupService
from app.modules.quota.models import QuotaAccount, QuotaLedger
from app.modules.quota.repository import QuotaRepository
from app.modules.quota.service import QuotaService
from app.modules.search.events import SEARCH_INDEX_REQUESTED
from app.modules.space.models import Space
from tests.helpers import (
    client as client,
)
from tests.helpers import (
    create_folder,
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


async def create_instant_file(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    token: str,
    *,
    tenant_id: str,
    space_id: str,
    parent_id: str,
    file_name: str,
    content_hash: str,
    size_bytes: int,
) -> dict[str, object]:
    async with session_factory() as session:
        blob = FileBlob(
            tenant_id=UUID(tenant_id),
            hash_algo="sha256",
            content_hash=content_hash,
            size_bytes=size_bytes,
            storage_key=f"objects/test/{content_hash[:2]}/{content_hash}",
            mime_type="text/plain",
            ref_count=0,
        )
        session.add(blob)
        await session.commit()

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": token},
        json={
            "space_id": space_id,
            "parent_id": parent_id,
            "file_name": file_name,
            "size_bytes": size_bytes,
            "content_hash": content_hash,
            "hash_algo": "sha256",
            "mime_type": "text/plain",
        },
    )
    assert response.status_code == 201
    payload = dict(response.json())
    assert payload["mode"] == "instant"
    return payload


@pytest.mark.asyncio
async def test_cleanup_expired_trash_purges_due_batch_and_preserves_other_data(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="trash-retention-space")
    folder = await create_folder(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="到期目录",
    )
    expired_file = await create_instant_file(
        client,
        session_factory,
        token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(folder["id"]),
        file_name="到期文件.txt",
        content_hash="d" * 64,
        size_bytes=1024,
    )
    fresh_file = await create_instant_file(
        client,
        session_factory,
        token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="未到期文件.txt",
        content_hash="e" * 64,
        size_bytes=2048,
    )

    assert (
        await client.delete(
            f"/api/v1/files/{folder['id']}",
            headers={"X-CSRF-Token": token},
        )
    ).status_code == 200
    assert (
        await client.delete(
            f"/api/v1/files/{fresh_file['node_id']}",
            headers={"X-CSRF-Token": token},
        )
    ).status_code == 200

    now = utc_now()
    expired_at = now - timedelta(days=31)
    second_tenant_node_id: UUID
    async with session_factory() as session:
        expired_nodes = (
            (
                await session.execute(
                    select(Node).where(
                        Node.id.in_(
                            [
                                UUID(str(folder["id"])),
                                UUID(str(expired_file["node_id"])),
                            ]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        for node in expired_nodes:
            node.deleted_at = expired_at

        second_tenant = Tenant(slug="trash-retention-second", name="第二租户")
        session.add(second_tenant)
        await session.flush()
        second_user = User(
            tenant_id=second_tenant.id,
            username="second-admin",
            email="second-admin@example.com",
            display_name="第二管理员",
            password_hash="unused",
            is_super_admin=True,
        )
        session.add(second_user)
        await session.flush()
        second_space = Space(
            tenant_id=second_tenant.id,
            owner_id=second_user.id,
            slug="second-space",
            name="第二空间",
            space_type="team",
        )
        session.add(second_space)
        await session.flush()
        second_root = Node(
            tenant_id=second_tenant.id,
            space_id=second_space.id,
            parent_id=None,
            owner_id=second_user.id,
            node_type="folder",
            name="/",
            normalized_name="/",
        )
        session.add(second_root)
        await session.flush()
        second_deleted = Node(
            tenant_id=second_tenant.id,
            space_id=second_space.id,
            parent_id=second_root.id,
            owner_id=second_user.id,
            node_type="folder",
            name="第二租户到期目录",
            normalized_name="第二租户到期目录",
            is_deleted=True,
            deleted_at=expired_at,
            deleted_by=second_user.id,
        )
        session.add(second_deleted)
        await session.commit()
        second_tenant_node_id = second_deleted.id

    async with session_factory() as session:
        service = TrashCleanupService(
            repository=FileRepository(session),
            quota_service=QuotaService(
                repository=QuotaRepository(session),
                default_space_limit_bytes=settings.default_space_quota_bytes,
            ),
            audit_service=AuditService(repository=AuditRepository(session)),
        )
        result = await service.cleanup_expired_trash(
            tenant_id=UUID(str(space["tenant_id"])),
            retention_days=30,
            limit=10,
            now=now,
            audit_context=AuditContext(request_id="req_trash_retention"),
        )

    assert result.to_dict() == {
        "scanned": 1,
        "purged_roots": 1,
        "purged_nodes": 2,
        "released_bytes": 1024,
        "skipped": 0,
        "failed": 0,
    }

    async with session_factory() as session:
        expired_node_rows = (
            (
                await session.execute(
                    select(Node).where(
                        Node.id.in_(
                            [
                                UUID(str(folder["id"])),
                                UUID(str(expired_file["node_id"])),
                            ]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        fresh_node = (
            await session.execute(select(Node).where(Node.id == UUID(str(fresh_file["node_id"]))))
        ).scalar_one()
        second_tenant_node = (
            await session.execute(select(Node).where(Node.id == second_tenant_node_id))
        ).scalar_one()
        expired_version = (
            await session.execute(
                select(FileVersion).where(FileVersion.id == UUID(str(expired_file["version_id"])))
            )
        ).scalar_one_or_none()
        fresh_version = (
            await session.execute(
                select(FileVersion).where(FileVersion.id == UUID(str(fresh_file["version_id"])))
            )
        ).scalar_one()
        expired_blob = (
            await session.execute(
                select(FileBlob).where(FileBlob.id == UUID(str(expired_file["blob_id"])))
            )
        ).scalar_one()
        fresh_blob = (
            await session.execute(
                select(FileBlob).where(FileBlob.id == UUID(str(fresh_file["blob_id"])))
            )
        ).scalar_one()
        quota_account = (
            await session.execute(
                select(QuotaAccount).where(
                    QuotaAccount.tenant_id == UUID(str(space["tenant_id"])),
                    QuotaAccount.owner_id == UUID(str(space["id"])),
                )
            )
        ).scalar_one()
        release_ledger = (
            await session.execute(
                select(QuotaLedger).where(
                    QuotaLedger.reason == "file_purged",
                    QuotaLedger.ref_id == UUID(str(folder["id"])),
                )
            )
        ).scalar_one()
        audit = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "file.trash.retention_purged")
            )
        ).scalar_one()
        search_event = (
            await session.execute(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == SEARCH_INDEX_REQUESTED,
                    OutboxEvent.aggregate_id == UUID(str(expired_file["node_id"])),
                    OutboxEvent.payload["reason"].as_string() == "trash_retention_expired",
                )
            )
        ).scalar_one()

    assert expired_node_rows == []
    assert expired_version is None
    assert fresh_node.is_deleted is True
    assert fresh_version.id == UUID(str(fresh_file["version_id"]))
    assert second_tenant_node.is_deleted is True
    assert expired_blob.ref_count == 0
    assert fresh_blob.ref_count == 1
    assert quota_account.used_bytes == 2048
    assert release_ledger.delta_bytes == -1024
    assert audit.actor_id is None
    assert audit.actor_type == "system"
    assert audit.request_id == "req_trash_retention"
    assert audit.resource_id == UUID(str(folder["id"]))
    assert audit.metadata_json["purged_count"] == 2
    assert audit.metadata_json["released_bytes"] == 1024
    assert search_event.payload["root_node_id"] == str(folder["id"])
