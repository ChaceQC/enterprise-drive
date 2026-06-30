from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.audit.models import OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.permission.events import emit_permission_changed
from app.modules.permission.models import AclEntry, SpaceMember
from app.modules.search.acl import build_index_acl_token_set, build_index_acl_tokens
from app.modules.search.events import SEARCH_ACL_REBUILD_REQUESTED
from app.workers import search_tasks
from tests.helpers import seed_admin
from tests.helpers import session_factory as session_factory
from tests.helpers import settings as settings
from tests.test_permission_cache import _get_seeded_tenant_and_user


def test_build_index_acl_tokens_includes_roles_and_allowed_subjects() -> None:
    tenant_id = uuid4()
    space_id = uuid4()
    owner_id = uuid4()
    viewer_id = uuid4()
    node_id = uuid4()
    department_id = uuid4()
    group_id = uuid4()
    tokens = build_index_acl_tokens(
        space_members=[
            SpaceMember(
                tenant_id=tenant_id,
                space_id=space_id,
                user_id=owner_id,
                role="owner",
                created_by=None,
            ),
            SpaceMember(
                tenant_id=tenant_id,
                space_id=space_id,
                user_id=viewer_id,
                role="viewer",
                created_by=owner_id,
            ),
        ],
        acl_entries=[
            AclEntry(
                tenant_id=tenant_id,
                node_id=node_id,
                subject_type="department",
                subject_id=department_id,
                effect="allow",
                actions=["download"],
                inherit=True,
                created_by=owner_id,
            ),
            AclEntry(
                tenant_id=tenant_id,
                node_id=node_id,
                subject_type="group",
                subject_id=group_id,
                effect="deny",
                actions=["download"],
                inherit=True,
                created_by=owner_id,
            ),
        ],
    )

    assert tokens == sorted(
        [
            f"space:{space_id}:role:owner",
            f"space:{space_id}:role:viewer",
            f"department:{department_id}",
        ]
    )


def test_build_index_acl_tokens_ignores_non_visible_and_denied_acl() -> None:
    tenant_id = uuid4()
    node_id = uuid4()
    owner_id = uuid4()
    upload_only_user_id = uuid4()
    denied_user_id = uuid4()

    tokens = build_index_acl_tokens(
        space_members=[],
        acl_entries=[
            AclEntry(
                tenant_id=tenant_id,
                node_id=node_id,
                subject_type="user",
                subject_id=upload_only_user_id,
                effect="allow",
                actions=["upload"],
                inherit=True,
                created_by=owner_id,
            ),
            AclEntry(
                tenant_id=tenant_id,
                node_id=node_id,
                subject_type="user",
                subject_id=denied_user_id,
                effect="allow",
                actions=["download"],
                inherit=True,
                created_by=owner_id,
            ),
            AclEntry(
                tenant_id=tenant_id,
                node_id=node_id,
                subject_type="user",
                subject_id=denied_user_id,
                effect="deny",
                actions=["download"],
                inherit=True,
                created_by=owner_id,
            ),
        ],
    )

    assert tokens == []


def test_build_index_acl_token_set_returns_deny_tokens_for_query_exclusion() -> None:
    tenant_id = uuid4()
    space_id = uuid4()
    node_id = uuid4()
    owner_id = uuid4()
    denied_group_id = uuid4()

    token_set = build_index_acl_token_set(
        space_members=[
            SpaceMember(
                tenant_id=tenant_id,
                space_id=space_id,
                user_id=owner_id,
                role="owner",
                created_by=None,
            )
        ],
        acl_entries=[
            AclEntry(
                tenant_id=tenant_id,
                node_id=node_id,
                subject_type="group",
                subject_id=denied_group_id,
                effect="deny",
                actions=["download"],
                inherit=True,
                created_by=owner_id,
            )
        ],
    )

    assert token_set.allow_tokens == [f"space:{space_id}:role:owner"]
    assert token_set.deny_tokens == [f"group:{denied_group_id}"]


@pytest.mark.asyncio
async def test_search_dispatcher_consumes_only_search_events(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_admin(session_factory, settings)
    tenant_id, _ = await _get_seeded_tenant_and_user(session_factory)
    node_id = uuid4()
    async with session_factory() as session:
        repository = AuditRepository(session)
        search_event = await repository.add_outbox_event(
            tenant_id=tenant_id,
            event_type=SEARCH_ACL_REBUILD_REQUESTED,
            aggregate_type="node",
            aggregate_id=node_id,
            payload={
                "scope": "node",
                "resource_id": str(node_id),
                "permission_version": 2,
                "reason": "node_acl_created",
            },
        )
        permission_event = await repository.add_outbox_event(
            tenant_id=tenant_id,
            event_type="permission.changed",
            aggregate_type="node",
            aggregate_id=node_id,
            payload={
                "scope": "node",
                "resource_id": str(node_id),
                "permission_version": 2,
            },
        )
        await session.commit()

    monkeypatch.setattr(search_tasks, "get_settings", lambda: settings)
    monkeypatch.setattr(search_tasks, "get_session_factory", lambda: session_factory)

    result = await search_tasks._dispatch_search_outbox(batch_size=10)

    assert result == {"claimed": 1, "sent": 1, "failed": 0, "dead": 0}
    async with session_factory() as session:
        stored_search_event = await session.get(OutboxEvent, search_event.id)
        stored_permission_event = await session.get(OutboxEvent, permission_event.id)

    assert stored_search_event is not None
    assert stored_search_event.status == "sent"
    assert stored_permission_event is not None
    assert stored_permission_event.status == "pending"


@pytest.mark.asyncio
async def test_permission_change_writes_search_acl_rebuild_event(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    tenant_id, user_id = await _get_seeded_tenant_and_user(session_factory)
    node_id = uuid4()
    async with session_factory() as session:
        await emit_permission_changed(
            audit_service=AuditService(repository=AuditRepository(session)),
            tenant_id=tenant_id,
            actor_id=user_id,
            scope="node",
            resource_id=node_id,
            permission_version=3,
            reason="node_acl_created",
            affected_user_id=user_id,
            metadata={"space_id": str(uuid4()), "subject_type": "user"},
        )
        await session.commit()

    async with session_factory() as session:
        events = (
            await session.execute(
                select(OutboxEvent.event_type, OutboxEvent.payload).order_by(OutboxEvent.created_at)
            )
        ).all()

    assert [event_type for event_type, _ in events] == [
        "permission.changed",
        SEARCH_ACL_REBUILD_REQUESTED,
    ]
    assert events[1][1]["reason"] == "node_acl_created"
