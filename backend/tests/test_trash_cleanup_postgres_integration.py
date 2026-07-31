from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.security import utc_now
from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.audit.repository import AuditRepository
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

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def postgres_url() -> str:
    if os.getenv("DRIVE_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("set DRIVE_RUN_POSTGRES_TESTS=1 to run PostgreSQL integration tests")
    database_url = os.getenv("DRIVE_TEST_POSTGRES_URL")
    if not database_url:
        pytest.fail("DRIVE_TEST_POSTGRES_URL is required")
    return database_url


@pytest_asyncio.fixture
async def postgres_session_factory(
    postgres_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text("truncate table tenants cascade"))

    yield async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.execute(text("truncate table tenants cascade"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_expired_trash_cleanup_uses_migrated_postgresql_schema_and_tenant_locks(
    postgres_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = utc_now()
    expired_at = now - timedelta(days=31)
    fresh_at = now - timedelta(days=1)
    size_bytes = 4096

    async with postgres_session_factory() as session:
        tenant = Tenant(slug="postgres-trash", name="PostgreSQL 回收站租户")
        other_tenant = Tenant(slug="postgres-trash-other", name="其他租户")
        session.add_all([tenant, other_tenant])
        await session.flush()

        owner = User(
            tenant_id=tenant.id,
            username="postgres-owner",
            email="postgres-owner@example.com",
            display_name="PostgreSQL Owner",
            password_hash="unused",
            is_super_admin=True,
        )
        other_owner = User(
            tenant_id=other_tenant.id,
            username="postgres-other-owner",
            email="postgres-other-owner@example.com",
            display_name="PostgreSQL Other Owner",
            password_hash="unused",
            is_super_admin=True,
        )
        session.add_all([owner, other_owner])
        await session.flush()

        space = Space(
            tenant_id=tenant.id,
            owner_id=owner.id,
            slug="postgres-trash-space",
            name="PostgreSQL 回收站空间",
            space_type="team",
        )
        other_space = Space(
            tenant_id=other_tenant.id,
            owner_id=other_owner.id,
            slug="postgres-trash-other-space",
            name="其他租户空间",
            space_type="team",
        )
        session.add_all([space, other_space])
        await session.flush()

        root = Node(
            tenant_id=tenant.id,
            space_id=space.id,
            parent_id=None,
            owner_id=owner.id,
            node_type="folder",
            name="/",
            normalized_name="/",
        )
        other_root = Node(
            tenant_id=other_tenant.id,
            space_id=other_space.id,
            parent_id=None,
            owner_id=other_owner.id,
            node_type="folder",
            name="/",
            normalized_name="/",
        )
        session.add_all([root, other_root])
        await session.flush()

        expired_folder = Node(
            tenant_id=tenant.id,
            space_id=space.id,
            parent_id=root.id,
            owner_id=owner.id,
            node_type="folder",
            name="到期目录",
            normalized_name="到期目录",
            is_deleted=True,
            deleted_at=expired_at,
            deleted_by=owner.id,
        )
        fresh_file = Node(
            tenant_id=tenant.id,
            space_id=space.id,
            parent_id=root.id,
            owner_id=owner.id,
            node_type="file",
            name="未到期文件.txt",
            normalized_name="未到期文件.txt",
            is_deleted=True,
            deleted_at=fresh_at,
            deleted_by=owner.id,
        )
        other_expired = Node(
            tenant_id=other_tenant.id,
            space_id=other_space.id,
            parent_id=other_root.id,
            owner_id=other_owner.id,
            node_type="folder",
            name="其他租户到期目录",
            normalized_name="其他租户到期目录",
            is_deleted=True,
            deleted_at=expired_at,
            deleted_by=other_owner.id,
        )
        session.add_all([expired_folder, fresh_file, other_expired])
        await session.flush()

        expired_file = Node(
            tenant_id=tenant.id,
            space_id=space.id,
            parent_id=expired_folder.id,
            owner_id=owner.id,
            node_type="file",
            name="到期文件.txt",
            normalized_name="到期文件.txt",
            is_deleted=True,
            deleted_at=expired_at,
            deleted_by=owner.id,
        )
        blob = FileBlob(
            tenant_id=tenant.id,
            hash_algo="sha256",
            content_hash="f" * 64,
            size_bytes=size_bytes,
            storage_key=f"objects/{tenant.id}/ff/{'f' * 64}",
            mime_type="text/plain",
            ref_count=1,
        )
        session.add_all([expired_file, blob])
        await session.flush()

        version = FileVersion(
            tenant_id=tenant.id,
            node_id=expired_file.id,
            blob_id=blob.id,
            version_no=1,
            size_bytes=size_bytes,
            mime_type="text/plain",
            created_by=owner.id,
        )
        session.add(version)
        await session.flush()
        expired_file.current_version_id = version.id

        quota_account = QuotaAccount(
            tenant_id=tenant.id,
            owner_type="space",
            owner_id=space.id,
            limit_bytes=1024 * 1024,
            used_bytes=size_bytes,
        )
        session.add(quota_account)
        await session.flush()
        session.add(
            QuotaLedger(
                tenant_id=tenant.id,
                account_id=quota_account.id,
                account_type="space",
                delta_bytes=size_bytes,
                reason="file_version_created",
                ref_type="file_version",
                ref_id=version.id,
            )
        )
        await session.commit()

        tenant_id = tenant.id
        expired_folder_id = expired_folder.id
        expired_file_id = expired_file.id
        version_id = version.id
        blob_id = blob.id
        fresh_file_id = fresh_file.id
        other_expired_id = other_expired.id

    async with postgres_session_factory() as session:
        index_name = (
            await session.execute(
                text(
                    "select indexname from pg_indexes "
                    "where schemaname = current_schema() "
                    "and tablename = 'nodes' "
                    "and indexname = 'idx_nodes_trash_cleanup'"
                )
            )
        ).scalar_one()
        service = TrashCleanupService(
            repository=FileRepository(session),
            quota_service=QuotaService(
                repository=QuotaRepository(session),
                default_space_limit_bytes=1024 * 1024,
            ),
            audit_service=AuditService(repository=AuditRepository(session)),
        )
        result = await service.cleanup_expired_trash(
            tenant_id=tenant_id,
            retention_days=30,
            limit=10,
            now=now,
        )

    assert index_name == "idx_nodes_trash_cleanup"
    assert result.to_dict() == {
        "scanned": 1,
        "purged_roots": 1,
        "purged_nodes": 2,
        "released_bytes": size_bytes,
        "skipped": 0,
        "failed": 0,
    }

    async with postgres_session_factory() as session:
        purged_nodes = (
            (
                await session.execute(
                    select(Node).where(Node.id.in_([expired_folder_id, expired_file_id]))
                )
            )
            .scalars()
            .all()
        )
        fresh_node = (
            await session.execute(select(Node).where(Node.id == fresh_file_id))
        ).scalar_one()
        other_node = (
            await session.execute(select(Node).where(Node.id == other_expired_id))
        ).scalar_one()
        removed_version = (
            await session.execute(select(FileVersion).where(FileVersion.id == version_id))
        ).scalar_one_or_none()
        updated_blob = (
            await session.execute(select(FileBlob).where(FileBlob.id == blob_id))
        ).scalar_one()
        updated_quota = (
            await session.execute(
                select(QuotaAccount).where(
                    QuotaAccount.tenant_id == tenant_id,
                    QuotaAccount.owner_type == "space",
                )
            )
        ).scalar_one()
        audit = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "file.trash.retention_purged")
            )
        ).scalar_one()
        search_events = (
            (
                await session.execute(
                    select(OutboxEvent).where(
                        OutboxEvent.event_type == SEARCH_INDEX_REQUESTED,
                        OutboxEvent.aggregate_id == expired_file_id,
                    )
                )
            )
            .scalars()
            .all()
        )

    assert purged_nodes == []
    assert removed_version is None
    assert fresh_node.is_deleted is True
    assert other_node.is_deleted is True
    assert updated_blob.ref_count == 0
    assert updated_quota.used_bytes == 0
    assert audit.actor_type == "system"
    assert audit.metadata_json["purged_count"] == 2
    assert [event.payload["reason"] for event in search_events] == ["trash_retention_expired"]
