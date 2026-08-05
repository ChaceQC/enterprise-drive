from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.audit.models import OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.auth.models import Tenant, User
from app.modules.permission.cache import (
    PERMISSION_CHANGED_EVENT,
    InMemoryPermissionCacheInvalidator,
    permission_cache_key,
)
from app.workers import audit_tasks, permission_tasks
from tests.helpers import (
    seed_admin,
)
from tests.helpers import (
    session_factory as session_factory,
)
from tests.helpers import (
    settings as settings,
)


@pytest.mark.asyncio
async def test_permission_cache_invalidator_removes_space_and_node_patterns() -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    other_user_id = uuid4()
    space_id = uuid4()
    other_space_id = uuid4()
    node_id = uuid4()
    other_node_id = uuid4()
    matching_space_key = permission_cache_key(
        tenant_id=tenant_id,
        user_id=user_id,
        space_id=space_id,
        node_id=node_id,
        action="download",
        permission_version=3,
    )
    other_space_key = permission_cache_key(
        tenant_id=tenant_id,
        user_id=user_id,
        space_id=other_space_id,
        node_id=other_node_id,
        action="download",
        permission_version=3,
    )
    other_user_key = permission_cache_key(
        tenant_id=tenant_id,
        user_id=other_user_id,
        space_id=space_id,
        node_id=node_id,
        action="download",
        permission_version=3,
    )
    invalidator = InMemoryPermissionCacheInvalidator(
        keys={matching_space_key, other_space_key, other_user_key}
    )
    space_event = OutboxEvent(
        tenant_id=tenant_id,
        event_type=PERMISSION_CHANGED_EVENT,
        aggregate_type="space",
        aggregate_id=space_id,
        payload={
            "scope": "space",
            "resource_id": str(space_id),
            "permission_version": 2,
            "affected_user_id": str(user_id),
        },
    )

    space_result = await invalidator.invalidate_permission_changed(event=space_event)

    assert space_result.deleted == 1
    assert invalidator.keys == {other_space_key, other_user_key}

    node_event = OutboxEvent(
        tenant_id=tenant_id,
        event_type=PERMISSION_CHANGED_EVENT,
        aggregate_type="node",
        aggregate_id=node_id,
        payload={
            "scope": "node",
            "resource_id": str(node_id),
            "permission_version": 4,
            "affected_user_id": str(user_id),
        },
    )

    node_result = await invalidator.invalidate_permission_changed(event=node_event)

    assert node_result.deleted == 1
    assert invalidator.keys == {other_user_key}

    org_subject_event = OutboxEvent(
        tenant_id=tenant_id,
        event_type=PERMISSION_CHANGED_EVENT,
        aggregate_type="node",
        aggregate_id=node_id,
        payload={
            "scope": "node",
            "resource_id": str(node_id),
            "permission_version": 5,
            "subject_type": "department",
            "subject_id": str(uuid4()),
        },
    )

    org_subject_result = await invalidator.invalidate_permission_changed(event=org_subject_event)

    assert org_subject_result.deleted == 1
    assert invalidator.keys == set()


@pytest.mark.asyncio
async def test_permission_cache_invalidator_supports_tenant_wide_and_user_scopes() -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    other_user_id = uuid4()
    first_user_key = permission_cache_key(
        tenant_id=tenant_id,
        user_id=user_id,
        space_id=uuid4(),
        node_id=uuid4(),
        action="download",
        permission_version=1,
    )
    second_user_key = permission_cache_key(
        tenant_id=tenant_id,
        user_id=other_user_id,
        space_id=uuid4(),
        node_id=uuid4(),
        action="download",
        permission_version=1,
    )
    invalidator = InMemoryPermissionCacheInvalidator(keys={first_user_key, second_user_key})

    user_event = OutboxEvent(
        tenant_id=tenant_id,
        event_type=PERMISSION_CHANGED_EVENT,
        aggregate_type="tenant",
        aggregate_id=tenant_id,
        payload={
            "scope": "tenant",
            "resource_id": str(tenant_id),
            "permission_version": 2,
            "affected_user_id": str(user_id),
        },
    )
    user_result = await invalidator.invalidate_permission_changed(event=user_event)

    assert user_result.deleted == 1
    assert invalidator.keys == {second_user_key}

    tenant_event = OutboxEvent(
        tenant_id=tenant_id,
        event_type=PERMISSION_CHANGED_EVENT,
        aggregate_type="tenant",
        aggregate_id=tenant_id,
        payload={
            "scope": "tenant",
            "resource_id": str(tenant_id),
            "permission_version": 3,
        },
    )
    tenant_result = await invalidator.invalidate_permission_changed(event=tenant_event)

    assert tenant_result.deleted == 1
    assert invalidator.keys == set()


@pytest.mark.asyncio
async def test_permission_cache_worker_consumes_only_permission_changed_events(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_admin(session_factory, settings)
    tenant_id, user_id = await _get_seeded_tenant_and_user(session_factory)
    space_id = uuid4()
    node_id = uuid4()
    cache_key = permission_cache_key(
        tenant_id=tenant_id,
        user_id=user_id,
        space_id=space_id,
        node_id=node_id,
        action="download",
        permission_version=1,
    )
    async with session_factory() as session:
        repository = AuditRepository(session)
        permission_event = await repository.add_outbox_event(
            tenant_id=tenant_id,
            event_type=PERMISSION_CHANGED_EVENT,
            aggregate_type="node",
            aggregate_id=node_id,
            payload={
                "scope": "node",
                "resource_id": str(node_id),
                "permission_version": 2,
                "affected_user_id": str(user_id),
            },
        )
        audit_event = await repository.add_outbox_event(
            tenant_id=tenant_id,
            event_type="audit.auth.login",
            aggregate_type="audit_log",
            aggregate_id=uuid4(),
            payload={"audit_log_id": str(uuid4())},
        )
        await session.commit()

    monkeypatch.setattr(permission_tasks, "get_settings", lambda: settings)
    monkeypatch.setattr(permission_tasks, "get_session_factory", lambda: session_factory)
    invalidator = InMemoryPermissionCacheInvalidator(keys={cache_key})

    result = await permission_tasks._invalidate_permission_cache(
        batch_size=10,
        invalidator=invalidator,
    )

    assert result == {"claimed": 1, "sent": 1, "failed": 0, "dead": 0}
    assert invalidator.keys == set()
    async with session_factory() as session:
        stored_permission_event = await session.get(OutboxEvent, permission_event.id)
        stored_audit_event = await session.get(OutboxEvent, audit_event.id)

    assert stored_permission_event is not None
    assert stored_permission_event.status == "sent"
    assert stored_audit_event is not None
    assert stored_audit_event.status == "pending"


@pytest.mark.asyncio
async def test_audit_dispatcher_skips_permission_changed_events(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_admin(session_factory, settings)
    tenant_id, user_id = await _get_seeded_tenant_and_user(session_factory)
    async with session_factory() as session:
        repository = AuditRepository(session)
        permission_event = await repository.add_outbox_event(
            tenant_id=tenant_id,
            event_type=PERMISSION_CHANGED_EVENT,
            aggregate_type="space",
            aggregate_id=uuid4(),
            payload={
                "scope": "space",
                "resource_id": str(uuid4()),
                "permission_version": 2,
                "affected_user_id": str(user_id),
            },
        )
        audit_event = await repository.add_outbox_event(
            tenant_id=tenant_id,
            event_type="audit.auth.login",
            aggregate_type="audit_log",
            aggregate_id=uuid4(),
            payload={"audit_log_id": str(uuid4())},
        )
        await session.commit()

    monkeypatch.setattr(audit_tasks, "get_settings", lambda: settings)
    monkeypatch.setattr(audit_tasks, "get_session_factory", lambda: session_factory)

    result = await audit_tasks._dispatch_outbox(batch_size=10)

    assert result == {"claimed": 1, "sent": 1, "failed": 0, "dead": 0}
    async with session_factory() as session:
        stored_permission_event = await session.get(OutboxEvent, permission_event.id)
        stored_audit_event = await session.get(OutboxEvent, audit_event.id)

    assert stored_permission_event is not None
    assert stored_permission_event.status == "pending"
    assert stored_audit_event is not None
    assert stored_audit_event.status == "sent"


@pytest.mark.asyncio
async def test_audit_dispatcher_treats_blank_external_delivery_as_local_logging(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_admin(session_factory, settings)
    tenant_id, _ = await _get_seeded_tenant_and_user(session_factory)
    async with session_factory() as session:
        repository = AuditRepository(session)
        event = await repository.add_outbox_event(
            tenant_id=tenant_id,
            event_type="audit.fixture.blank_external_delivery",
            aggregate_type="audit_log",
            aggregate_id=uuid4(),
            payload={"audit_log_id": str(uuid4())},
        )
        await session.commit()

    blank_delivery_settings = settings.model_copy(
        update={
            "audit_external_delivery_url": "",
            "audit_external_hmac_key": "",
        }
    )
    monkeypatch.setattr(audit_tasks, "get_settings", lambda: blank_delivery_settings)
    monkeypatch.setattr(audit_tasks, "get_session_factory", lambda: session_factory)

    result = await audit_tasks._dispatch_outbox(batch_size=10)

    assert result == {"claimed": 1, "sent": 1, "failed": 0, "dead": 0}
    async with session_factory() as session:
        stored = await session.get(OutboxEvent, event.id)

    assert stored is not None
    assert stored.status == "sent"
    assert stored.retry_count == 0


@pytest.mark.asyncio
async def test_audit_dispatcher_treats_blank_hmac_as_misconfigured(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_admin(session_factory, settings)
    tenant_id, _ = await _get_seeded_tenant_and_user(session_factory)
    async with session_factory() as session:
        repository = AuditRepository(session)
        event = await repository.add_outbox_event(
            tenant_id=tenant_id,
            event_type="audit.fixture.blank_external_hmac",
            aggregate_type="audit_log",
            aggregate_id=uuid4(),
            payload={"audit_log_id": str(uuid4())},
        )
        await session.commit()

    blank_hmac_settings = settings.model_copy(
        update={
            "audit_external_delivery_url": "https://audit.example.test/events",
            "audit_external_hmac_key": "",
        }
    )
    monkeypatch.setattr(audit_tasks, "get_settings", lambda: blank_hmac_settings)
    monkeypatch.setattr(audit_tasks, "get_session_factory", lambda: session_factory)

    result = await audit_tasks._dispatch_outbox(batch_size=10)

    assert result == {"claimed": 1, "sent": 0, "failed": 0, "dead": 1}
    async with session_factory() as session:
        stored = await session.get(OutboxEvent, event.id)

    assert stored is not None
    assert stored.status == "dead"
    assert stored.retry_count == 1
    assert stored.last_error_kind == "permanent"
    assert stored.last_error_code == "external_signing_key_missing"


async def _get_seeded_tenant_and_user(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID]:
    async with session_factory() as session:
        tenant = (await session.execute(select(Tenant))).scalar_one()
        user = (await session.execute(select(User))).scalar_one()
        return tenant.id, user.id
