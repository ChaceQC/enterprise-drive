from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.errors import ApiError
from app.core.config import Settings
from app.modules.admin.quota import AdminQuotaService
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import Tenant, User
from app.modules.quota.models import QuotaAccount
from app.modules.quota.repository import QuotaRepository

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
async def test_quota_account_updates_use_optimistic_precondition_under_row_lock(
    postgres_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with postgres_session_factory() as session:
        tenant = Tenant(slug="quota-admin-race", name="配额管理竞争租户")
        session.add(tenant)
        await session.flush()
        admin = User(
            tenant_id=tenant.id,
            username="quota-admin",
            display_name="Quota Admin",
            password_hash="unused",
            is_super_admin=True,
        )
        session.add(admin)
        await session.flush()
        session.add(
            QuotaAccount(
                tenant_id=tenant.id,
                owner_type="tenant",
                owner_id=tenant.id,
                limit_bytes=1024,
                used_bytes=0,
            )
        )
        await session.commit()
        tenant_id = tenant.id
        admin_id = admin.id

    async def update_limit(limit_bytes: int) -> tuple[str, int | None]:
        async with postgres_session_factory() as session:
            current_user = (
                await session.execute(select(User).where(User.id == admin_id))
            ).scalar_one()
            repository = QuotaRepository(session)
            service = AdminQuotaService(
                repository=repository,
                audit_service=AuditService(repository=AuditRepository(session)),
                settings=Settings(environment="test", secret_key="test-secret"),
            )
            try:
                response = await service.upsert_account(
                    current_user=current_user,
                    owner_type="tenant",
                    owner_id=tenant_id,
                    limit_bytes=limit_bytes,
                    expected_limit_bytes=1024,
                    audit_context=None,
                )
            except ApiError as exc:
                return exc.code, None
            return "updated", response.limit_bytes

    results = await asyncio.gather(update_limit(2048), update_limit(4096))

    async with postgres_session_factory() as session:
        account = (
            await session.execute(
                select(QuotaAccount).where(
                    QuotaAccount.tenant_id == tenant_id,
                    QuotaAccount.owner_type == "tenant",
                )
            )
        ).scalar_one()

    assert sorted(code for code, _ in results) == ["QUOTA_ACCOUNT_CHANGED", "updated"]
    updated_limit = next(limit for code, limit in results if code == "updated")
    assert updated_limit in {2048, 4096}
    assert account.limit_bytes == updated_limit
