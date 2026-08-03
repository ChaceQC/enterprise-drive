from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.errors import ApiError
from app.core.config import Settings
from app.modules.admin.organization import AdminOrganizationService
from app.modules.admin.organization_repository import AdminOrganizationRepository
from app.modules.admin.organization_schemas import AdminGroupUpdateRequest
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import Tenant, User
from app.modules.org.models import UserGroup

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
async def test_group_updates_serialize_on_expected_version(
    postgres_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with postgres_session_factory() as session:
        tenant = Tenant(slug="org-race", name="组织管理竞争租户")
        session.add(tenant)
        await session.flush()
        admin = User(
            tenant_id=tenant.id,
            username="org-admin",
            display_name="Org Admin",
            password_hash="unused",
            is_super_admin=True,
        )
        group = UserGroup(
            tenant_id=tenant.id,
            slug="reviewers",
            name="评审组",
        )
        session.add_all([admin, group])
        await session.commit()
        admin_id = admin.id
        group_id = group.id

    async def update_name(name: str) -> tuple[str, int | None]:
        async with postgres_session_factory() as session:
            current_user = (
                await session.execute(select(User).where(User.id == admin_id))
            ).scalar_one()
            service = AdminOrganizationService(
                repository=AdminOrganizationRepository(session),
                audit_service=AuditService(repository=AuditRepository(session)),
                settings=Settings(environment="test", secret_key="test-secret"),
            )
            try:
                response = await service.update_group(
                    current_user=current_user,
                    group_id=group_id,
                    request=AdminGroupUpdateRequest(
                        expected_version=1,
                        name=name,
                    ),
                    audit_context=None,
                )
            except ApiError as exc:
                return exc.code, None
            return "updated", response.version

    results = await asyncio.gather(
        update_name("核心评审组"),
        update_name("高级评审组"),
    )

    async with postgres_session_factory() as session:
        group = (
            await session.execute(select(UserGroup).where(UserGroup.id == group_id))
        ).scalar_one()

    assert sorted(code for code, _ in results) == ["GROUP_CHANGED", "updated"]
    assert group.version == 2
    assert group.name in {"核心评审组", "高级评审组"}


@pytest.mark.asyncio
async def test_concurrent_admin_deactivation_preserves_one_active_super_admin(
    postgres_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with postgres_session_factory() as session:
        tenant = Tenant(slug="admin-race", name="管理员竞争租户")
        session.add(tenant)
        await session.flush()
        admins = [
            User(
                tenant_id=tenant.id,
                username=f"admin-{index}",
                display_name=f"Admin {index}",
                password_hash="unused",
                is_super_admin=True,
            )
            for index in (1, 2)
        ]
        session.add_all(admins)
        await session.commit()
        tenant_id = tenant.id
        admin_ids = [admin.id for admin in admins]

    tenant_lock_barrier = asyncio.Barrier(2)

    class BarrierRepository(AdminOrganizationRepository):
        async def lock_tenant_for_update(self, *, tenant_id: UUID) -> None:
            await tenant_lock_barrier.wait()
            await super().lock_tenant_for_update(tenant_id=tenant_id)

    async def deactivate_admin(admin_id: UUID) -> str:
        async with postgres_session_factory() as session:
            current_user = (
                await session.execute(select(User).where(User.id == admin_id))
            ).scalar_one()
            service = AdminOrganizationService(
                repository=BarrierRepository(session),
                audit_service=AuditService(repository=AuditRepository(session)),
                settings=Settings(environment="test", secret_key="test-secret"),
            )
            try:
                await service.deactivate_user(
                    current_user=current_user,
                    user_id=current_user.id,
                    expected_version=1,
                    audit_context=None,
                )
            except ApiError as exc:
                return exc.code
            return "deactivated"

    results = await asyncio.wait_for(
        asyncio.gather(*(deactivate_admin(admin_id) for admin_id in admin_ids)),
        timeout=30,
    )

    async with postgres_session_factory() as session:
        active_admin_count = (
            await session.execute(
                select(func.count())
                .select_from(User)
                .where(
                    User.tenant_id == tenant_id,
                    User.is_active.is_(True),
                    User.is_super_admin.is_(True),
                )
            )
        ).scalar_one()

    assert sorted(results) == ["LAST_ACTIVE_SUPER_ADMIN", "deactivated"]
    assert active_admin_count == 1
