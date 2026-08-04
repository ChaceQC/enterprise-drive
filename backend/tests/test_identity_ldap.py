from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Literal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.security import hash_password, utc_now
from app.db.base import Base
from app.infrastructure.identity.base import (
    LdapDepartmentRecord,
    LdapDirectorySnapshot,
    LdapGroupRecord,
    LdapSourceConfig,
    LdapUserRecord,
)
from app.modules.audit.models import OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository
from app.modules.device.models import DesktopDevice, DeviceSession
from app.modules.identity.ldap_service import LdapIdentityService
from app.modules.identity.models import (
    LdapMembershipClaim,
    LdapMembershipRelation,
    LdapObjectBinding,
    LdapSyncConflict,
)
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.schemas import (
    LdapSourceCreateRequest,
    LdapSyncRequest,
    LdapSyncRunResponse,
)
from app.modules.org.models import Department, DepartmentMember, UserGroup, UserGroupMember


class FakeSecretResolver:
    def resolve(self, secret_ref: str | None) -> str | None:
        return "ldap-bind-password" if secret_ref else None


class FakeLdapAdapter:
    def __init__(self, *snapshots: LdapDirectorySnapshot) -> None:
        self.snapshots = list(snapshots)
        self.calls: list[tuple[str, str | None, int]] = []

    async def test_connection(self, config: LdapSourceConfig) -> dict[str, object]:
        return {"server": config.server_url, "base_dn_found": True}

    async def read_directory(
        self,
        *,
        config: LdapSourceConfig,
        mode: str,
        cursor: str | None,
        page_size: int,
    ) -> LdapDirectorySnapshot:
        self.calls.append((mode, cursor, page_size))
        return self.snapshots.pop(0)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        secret_key="test-secret",
        trusted_hosts=["testserver"],
        cors_origins=[],
        database_url="sqlite+aiosqlite:///:memory:",
        session_days=30,
        rate_limit_enabled=False,
    )


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _seed_admin(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID]:
    async with session_factory() as session:
        repository = AuthRepository(session)
        tenant = await repository.create_tenant(slug="default", name="Default")
        admin = await repository.create_user(
            tenant_id=tenant.id,
            username="admin",
            email="admin@example.com",
            display_name="Admin",
            password_hash=hash_password("local-password"),
            is_super_admin=True,
        )
        await repository.commit()
        return tenant.id, admin.id


def _service(
    session: AsyncSession,
    settings: Settings,
    adapter: FakeLdapAdapter,
) -> LdapIdentityService:
    return LdapIdentityService(
        repository=IdentityRepository(session),
        provider_adapter=adapter,
        secret_resolver=FakeSecretResolver(),
        settings=settings,
        audit_service=AuditService(repository=AuditRepository(session)),
    )


async def _create_source(
    service: LdapIdentityService,
    *,
    admin: User,
) -> UUID:
    source = await service.create_source(
        current_user=admin,
        request=LdapSourceCreateRequest(
            slug="corp",
            name="Corp LDAP",
            server_url="ldaps://ldap.example",
            base_dn="dc=example,dc=com",
            bind_dn="cn=reader,dc=example,dc=com",
            bind_password_ref="env:LDAP_BIND_PASSWORD",
            user_base_dn="ou=users,dc=example,dc=com",
            user_filter="(objectClass=person)",
            department_base_dn="ou=departments,dc=example,dc=com",
            department_filter="(objectClass=organizationalUnit)",
            group_base_dn="ou=groups,dc=example,dc=com",
            group_filter="(objectClass=groupOfNames)",
            attribute_mapping={
                "user_external_id": "entryUUID",
                "user_username": "uid",
                "user_display_name": "displayName",
            },
        ),
        audit_context=None,
    )
    return source.id


async def _run_sync(
    service: LdapIdentityService,
    *,
    admin: User,
    source_id: UUID,
    mode: Literal["dry_run", "full", "incremental"],
) -> LdapSyncRunResponse:
    queued = await service.request_sync(
        current_user=admin,
        source_id=source_id,
        request=LdapSyncRequest(mode=mode),
        audit_context=None,
    )
    return await service.execute_run(run_id=queued.id)


async def _binding_map(
    session: AsyncSession,
    *,
    source_id: UUID,
) -> dict[tuple[str, str], UUID]:
    bindings = list(
        (
            await session.execute(
                select(LdapObjectBinding).where(LdapObjectBinding.source_id == source_id)
            )
        ).scalars()
    )
    return {
        (binding.object_type, binding.external_id): binding.local_object_id for binding in bindings
    }


@pytest.mark.asyncio
async def test_ldap_connection_test_path_returns_success(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    _, admin_id = await _seed_admin(session_factory)
    async with session_factory() as session:
        admin = await session.get(User, admin_id)
        assert admin is not None
        service = _service(session, settings, FakeLdapAdapter())
        source_id = await _create_source(service, admin=admin)

        result = await service.test_source(
            current_user=admin,
            source_id=source_id,
            audit_context=None,
        )

        assert result.connected is True
        assert result.server == "ldaps://ldap.example"
        assert result.base_dn_found is True


@pytest.mark.asyncio
async def test_ldap_bound_user_disable_increments_version_once(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    _, admin_id = await _seed_admin(session_factory)
    adapter = FakeLdapAdapter(
        LdapDirectorySnapshot(
            users=(
                LdapUserRecord(
                    external_id="user-1",
                    username="alice",
                    display_name="Alice",
                    enabled=True,
                ),
            ),
            next_cursor="cursor-1",
        ),
        LdapDirectorySnapshot(
            users=(
                LdapUserRecord(
                    external_id="user-1",
                    username="alice",
                    display_name="Alice",
                    enabled=False,
                ),
            ),
            next_cursor="cursor-2",
        ),
    )

    async with session_factory() as session:
        admin = await session.get(User, admin_id)
        assert admin is not None
        service = _service(session, settings, adapter)
        source_id = await _create_source(service, admin=admin)

        first = await _run_sync(service, admin=admin, source_id=source_id, mode="full")
        assert first.status == "succeeded"
        user_id = (await _binding_map(session, source_id=source_id))[("user", "user-1")]
        user = await session.get(User, user_id)
        assert user is not None
        initial_version = user.version

        second = await _run_sync(
            service,
            admin=admin,
            source_id=source_id,
            mode="incremental",
        )

        assert second.status == "succeeded"
        assert second.stats["disabled"] == 1
        user = await session.get(User, user_id)
        assert user is not None
        assert user.is_active is False
        assert user.version == initial_version + 1
        binding = (
            await session.execute(
                select(LdapObjectBinding).where(
                    LdapObjectBinding.source_id == source_id,
                    LdapObjectBinding.object_type == "user",
                    LdapObjectBinding.external_id == "user-1",
                )
            )
        ).scalar_one()
        assert binding.sync_state == "disabled"


@pytest.mark.asyncio
async def test_ldap_dry_run_reports_changes_without_core_writes(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    tenant_id, admin_id = await _seed_admin(session_factory)
    snapshot = LdapDirectorySnapshot(
        departments=(LdapDepartmentRecord(external_id="dept-1", name="Engineering"),),
        users=(
            LdapUserRecord(
                external_id="user-1",
                username="alice",
                display_name="Alice",
                department_external_ids=("dept-1",),
                group_external_ids=("group-1",),
            ),
        ),
        groups=(
            LdapGroupRecord(
                external_id="group-1",
                slug="engineers",
                name="Engineers",
                member_external_ids=("user-1",),
            ),
        ),
        next_cursor="dry-run-cursor",
    )
    adapter = FakeLdapAdapter(snapshot)

    async with session_factory() as session:
        admin = await session.get(User, admin_id)
        assert admin is not None
        service = _service(session, settings, adapter)
        source_id = await _create_source(service, admin=admin)

        result = await _run_sync(
            service,
            admin=admin,
            source_id=source_id,
            mode="dry_run",
        )

        assert result.status == "succeeded"
        assert result.stats["created"] == 3
        assert adapter.calls[0][0] == "full"
        assert await session.scalar(select(func.count()).select_from(User)) == 1
        assert await session.scalar(select(func.count()).select_from(Department)) == 0
        assert await session.scalar(select(func.count()).select_from(UserGroup)) == 0
        assert await session.scalar(select(func.count()).select_from(DepartmentMember)) == 0
        assert await session.scalar(select(func.count()).select_from(UserGroupMember)) == 0
        assert await session.scalar(select(func.count()).select_from(LdapObjectBinding)) == 0
        source = await IdentityRepository(session).get_ldap_source(
            tenant_id=tenant_id,
            source_id=source_id,
        )
        assert source is not None
        assert source.sync_cursor is None
        assert source.last_success_at is None


@pytest.mark.asyncio
async def test_ldap_bindings_survive_incremental_updates_and_manual_membership(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    tenant_id, admin_id = await _seed_admin(session_factory)
    initial = LdapDirectorySnapshot(
        departments=(LdapDepartmentRecord(external_id="dept-1", name="Engineering"),),
        users=(
            LdapUserRecord(
                external_id="user-1",
                username="alice",
                display_name="Alice",
                email="alice@example.com",
            ),
        ),
        groups=(
            LdapGroupRecord(
                external_id="group-1",
                slug="engineers",
                name="Engineers",
            ),
        ),
        next_cursor="cursor-1",
    )
    incremental = LdapDirectorySnapshot(
        departments=(LdapDepartmentRecord(external_id="dept-1", name="Platform"),),
        users=(
            LdapUserRecord(
                external_id="user-1",
                username="alice-renamed",
                display_name="Alice Updated",
                email="alice.updated@example.com",
                group_external_ids=("group-1",),
            ),
        ),
        groups=(
            LdapGroupRecord(
                external_id="group-1",
                slug="engineers",
                name="Platform Engineers",
            ),
        ),
        next_cursor="cursor-2",
    )
    membership_removed = LdapDirectorySnapshot(
        departments=(LdapDepartmentRecord(external_id="dept-1", name="Platform"),),
        users=(
            LdapUserRecord(
                external_id="user-1",
                username="alice-renamed",
                display_name="Alice Updated",
                email="alice.updated@example.com",
            ),
        ),
        groups=(
            LdapGroupRecord(
                external_id="group-1",
                slug="engineers",
                name="Platform Engineers",
            ),
        ),
        next_cursor="cursor-3",
    )
    adapter = FakeLdapAdapter(initial, incremental, membership_removed)

    async with session_factory() as session:
        admin = await session.get(User, admin_id)
        assert admin is not None
        service = _service(session, settings, adapter)
        source_id = await _create_source(service, admin=admin)

        first = await _run_sync(service, admin=admin, source_id=source_id, mode="full")
        assert first.status == "succeeded"
        tenant = await IdentityRepository(session).get_tenant_by_slug("default")
        assert tenant is not None
        assert tenant.permission_version == 2
        first_bindings = await _binding_map(session, source_id=source_id)
        assert set(first_bindings) == {
            ("department", "dept-1"),
            ("group", "group-1"),
            ("user", "user-1"),
        }
        permission_events = list(
            (
                await session.execute(
                    select(OutboxEvent).where(OutboxEvent.event_type == "permission.changed")
                )
            ).scalars()
        )
        rebuild_events = list(
            (
                await session.execute(
                    select(OutboxEvent).where(
                        OutboxEvent.event_type == "share.recipients_rebuild_requested"
                    )
                )
            ).scalars()
        )
        assert len(permission_events) == 1
        assert permission_events[0].payload["permission_version"] == 2
        assert {
            (event.aggregate_type, event.aggregate_id) for event in rebuild_events
        } == {
            ("department", first_bindings[("department", "dept-1")]),
            ("group", first_bindings[("group", "group-1")]),
            ("user", first_bindings[("user", "user-1")]),
        }

        user_id = first_bindings[("user", "user-1")]
        group_id = first_bindings[("group", "group-1")]
        session.add(
            UserGroupMember(
                tenant_id=tenant_id,
                group_id=group_id,
                user_id=user_id,
            )
        )
        await session.commit()

        second = await _run_sync(
            service,
            admin=admin,
            source_id=source_id,
            mode="incremental",
        )
        assert second.status == "succeeded"
        await session.refresh(tenant)
        assert tenant.permission_version == 3
        assert second.cursor_before == "cursor-1"
        assert second.cursor_after == "cursor-2"
        assert await _binding_map(session, source_id=source_id) == first_bindings

        user = await session.get(User, user_id)
        assert user is not None
        assert user.username == "alice-renamed"
        assert user.display_name == "Alice Updated"
        assert user.email == "alice.updated@example.com"
        relation = (
            await session.execute(
                select(LdapMembershipRelation).where(
                    LdapMembershipRelation.relation_type == "group",
                    LdapMembershipRelation.container_id == group_id,
                    LdapMembershipRelation.user_id == user_id,
                )
            )
        ).scalar_one()
        assert relation.core_edge_managed is False
        assert (
            await session.scalar(
                select(func.count())
                .select_from(LdapMembershipClaim)
                .where(LdapMembershipClaim.relation_id == relation.id)
            )
            == 1
        )

        third = await _run_sync(service, admin=admin, source_id=source_id, mode="full")
        assert third.status == "succeeded"
        await session.refresh(tenant)
        assert tenant.permission_version == 3
        assert await _binding_map(session, source_id=source_id) == first_bindings
        assert (
            await session.scalar(
                select(func.count())
                .select_from(UserGroupMember)
                .where(
                    UserGroupMember.tenant_id == tenant_id,
                    UserGroupMember.group_id == group_id,
                    UserGroupMember.user_id == user_id,
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(LdapMembershipClaim)
                .where(LdapMembershipClaim.source_id == source_id)
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(LdapMembershipRelation)
                .where(
                    LdapMembershipRelation.relation_type == "group",
                    LdapMembershipRelation.container_id == group_id,
                    LdapMembershipRelation.user_id == user_id,
                )
            )
            == 0
        )


@pytest.mark.asyncio
async def test_ldap_full_missing_user_disables_account_and_revokes_all_sessions(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    tenant_id, admin_id = await _seed_admin(session_factory)
    adapter = FakeLdapAdapter(
        LdapDirectorySnapshot(
            users=(
                LdapUserRecord(
                    external_id="user-1",
                    username="alice",
                    display_name="Alice",
                ),
            ),
            next_cursor="cursor-1",
        ),
        LdapDirectorySnapshot(next_cursor="cursor-2"),
    )

    async with session_factory() as session:
        admin = await session.get(User, admin_id)
        assert admin is not None
        service = _service(session, settings, adapter)
        source_id = await _create_source(service, admin=admin)
        first = await _run_sync(service, admin=admin, source_id=source_id, mode="full")
        assert first.status == "succeeded"
        bindings = await _binding_map(session, source_id=source_id)
        user_id = bindings[("user", "user-1")]

        browser_session = await AuthRepository(session).create_auth_session(
            tenant_id=tenant_id,
            user_id=user_id,
            family_id=uuid4(),
            token_hash="a" * 64,
            csrf_token_hash="b" * 64,
            expires_at=utc_now() + timedelta(days=1),
        )
        device = DesktopDevice(
            tenant_id=tenant_id,
            user_id=user_id,
            installation_id_hash="c" * 64,
            name="Alice PC",
            platform="windows",
            client_version="0.8.0",
        )
        session.add(device)
        await session.flush()
        device_session = DeviceSession(
            tenant_id=tenant_id,
            user_id=user_id,
            device_id=device.id,
            family_id=uuid4(),
            token_hash="d" * 64,
            expires_at=utc_now() + timedelta(days=1),
        )
        session.add(device_session)
        await session.commit()

        second = await _run_sync(service, admin=admin, source_id=source_id, mode="full")
        assert second.status == "succeeded"
        assert second.stats["disabled"] == 1
        user = await session.get(User, user_id)
        assert user is not None
        assert user.is_active is False
        await session.refresh(browser_session)
        await session.refresh(device_session)
        assert browser_session.revoked_at is not None
        assert browser_session.revoked_reason == "ldap_missing"
        assert device_session.revoked_at is not None
        assert device_session.revoked_reason == "ldap_missing"
        binding = (
            await session.execute(
                select(LdapObjectBinding).where(
                    LdapObjectBinding.source_id == source_id,
                    LdapObjectBinding.object_type == "user",
                    LdapObjectBinding.external_id == "user-1",
                )
            )
        ).scalar_one()
        assert binding.sync_state == "missing"


@pytest.mark.asyncio
async def test_ldap_local_name_collisions_are_recorded_as_conflicts(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    tenant_id, admin_id = await _seed_admin(session_factory)
    snapshot = LdapDirectorySnapshot(
        departments=(LdapDepartmentRecord(external_id="dept-1", name="Existing"),),
        users=(
            LdapUserRecord(
                external_id="user-1",
                username="collision",
                display_name="Collision",
            ),
        ),
        groups=(
            LdapGroupRecord(
                external_id="group-1",
                slug="existing",
                name="Existing",
            ),
        ),
    )
    adapter = FakeLdapAdapter(snapshot)

    async with session_factory() as session:
        admin = await session.get(User, admin_id)
        assert admin is not None
        local_user = await AuthRepository(session).create_user(
            tenant_id=tenant_id,
            username="collision",
            email="collision@example.com",
            display_name="Local Collision",
            password_hash=hash_password("local-password"),
        )
        session.add_all(
            [
                Department(
                    tenant_id=tenant_id,
                    name="Existing",
                    path="/Existing",
                ),
                UserGroup(
                    tenant_id=tenant_id,
                    slug="existing",
                    name="Existing",
                ),
            ]
        )
        await session.commit()
        assert local_user.id

        service = _service(session, settings, adapter)
        source_id = await _create_source(service, admin=admin)
        result = await _run_sync(service, admin=admin, source_id=source_id, mode="full")

        assert result.status == "succeeded"
        assert result.stats["conflicts"] == 3
        conflicts = list(
            (
                await session.execute(
                    select(LdapSyncConflict)
                    .where(LdapSyncConflict.run_id == result.id)
                    .order_by(LdapSyncConflict.code)
                )
            ).scalars()
        )
        assert {conflict.code for conflict in conflicts} == {
            "path_conflict",
            "slug_conflict",
            "username_conflict",
        }
        assert await _binding_map(session, source_id=source_id) == {}
