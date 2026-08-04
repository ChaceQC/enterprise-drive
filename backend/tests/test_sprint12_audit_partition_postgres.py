from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.modules.audit.models import AuditLog
from app.modules.audit.partitioning import ensure_audit_partitions
from app.modules.auth.models import Tenant

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
        await connection.execute(
            text("DELETE FROM tenants WHERE slug = 'sprint12-audit-partition'")
        )

    yield async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM tenants WHERE slug = 'sprint12-audit-partition'")
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_audit_table_is_partitioned_and_partition_maintenance_is_idempotent(
    postgres_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with postgres_session_factory() as session:
        relkind = await session.scalar(
            text("SELECT relkind::text FROM pg_class WHERE oid = 'audit_logs'::regclass")
        )
        partition_count = await session.scalar(
            text("SELECT count(*) FROM pg_inherits WHERE inhparent = 'audit_logs'::regclass")
        )
        assert relkind == "p"
        assert int(partition_count or 0) >= 2

        first = await ensure_audit_partitions(
            session=session,
            months_ahead=8,
            reference_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
        await session.commit()
        second = await ensure_audit_partitions(
            session=session,
            months_ahead=8,
            reference_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
        assert first["supported"] is True
        assert "audit_logs_202704" in first["partitions"]
        assert second["created"] == 0

        tenant = Tenant(
            slug="sprint12-audit-partition",
            name="Sprint 12 审计分区租户",
        )
        session.add(tenant)
        await session.flush()
        audit_log = AuditLog(
            id=uuid4(),
            tenant_id=tenant.id,
            action="fixture.partition",
            resource_type="fixture",
            result="allowed",
            risk_level="low",
            metadata_json={},
            created_at=datetime(2026, 8, 4, 12, tzinfo=UTC),
        )
        session.add(audit_log)
        await session.flush()
        partition_name = await session.scalar(
            text("SELECT tableoid::regclass::text FROM audit_logs WHERE id = :audit_log_id"),
            {"audit_log_id": audit_log.id},
        )
        assert partition_name == "audit_logs_202608"
