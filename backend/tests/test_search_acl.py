from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.infrastructure.search.testing import InMemorySearchIndexAdapter
from app.modules.audit.dispatcher import LoggingOutboxPublisher, OutboxDispatcher
from app.modules.audit.models import OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.file.models import FileBlob
from app.modules.permission.events import emit_permission_changed
from app.modules.permission.models import AclEntry, SpaceMember
from app.modules.search.acl import build_index_acl_token_set, build_index_acl_tokens
from app.modules.search.events import SEARCH_ACL_REBUILD_REQUESTED, SEARCH_INDEX_REQUESTED
from app.modules.search.indexer import SearchIndexService
from app.modules.search.repository import SearchRepository
from app.workers import search_tasks
from tests.helpers import client as client
from tests.helpers import create_space, login, seed_admin
from tests.helpers import session_factory as session_factory
from tests.helpers import settings as settings
from tests.helpers import storage_adapter as storage_adapter
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
async def test_search_dispatcher_consumes_acl_rebuild_events(
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


@pytest.mark.asyncio
async def test_instant_upload_writes_search_index_event(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="search-index-event-space")
    tenant_id = UUID(str(space["tenant_id"]))
    async with session_factory() as session:
        session.add(
            FileBlob(
                tenant_id=tenant_id,
                hash_algo="sha256",
                content_hash="c" * 64,
                size_bytes=128,
                storage_key="objects/test/cc",
                mime_type="text/plain",
                ref_count=0,
            )
        )
        await session.commit()

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "搜索事件.txt",
            "size_bytes": 128,
            "content_hash": "c" * 64,
            "hash_algo": "sha256",
            "mime_type": "text/plain",
        },
    )

    assert response.status_code == 201
    node_id = response.json()["node_id"]
    async with session_factory() as session:
        event = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.event_type == SEARCH_INDEX_REQUESTED)
            )
        ).scalar_one()

    assert event.aggregate_type == "node"
    assert event.aggregate_id == UUID(node_id)
    assert event.payload["node_id"] == node_id
    assert event.payload["reason"] == "upload_instant"


@pytest.mark.asyncio
async def test_search_index_requested_event_indexes_file_document(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="search-index-worker-space")
    tenant_id = UUID(str(space["tenant_id"]))
    async with session_factory() as session:
        session.add(
            FileBlob(
                tenant_id=tenant_id,
                hash_algo="sha256",
                content_hash="d" * 64,
                size_bytes=256,
                storage_key="objects/test/dd",
                mime_type="text/plain",
                ref_count=0,
            )
        )
        await session.commit()

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "搜索索引.txt",
            "size_bytes": 256,
            "content_hash": "d" * 64,
            "hash_algo": "sha256",
            "mime_type": "text/plain",
        },
    )
    assert response.status_code == 201
    node_id = response.json()["node_id"]
    index_adapter = InMemorySearchIndexAdapter()

    async with session_factory() as session:
        dispatcher = OutboxDispatcher(
            repository=AuditRepository(session),
            publisher=search_tasks.SearchOutboxPublisher(
                index_service=SearchIndexService(
                    repository=SearchRepository(session),
                    index_adapter=index_adapter,
                ),
                fallback_publisher=LoggingOutboxPublisher(),
            ),
            max_retries=settings.outbox_max_retries,
        )
        result = await dispatcher.dispatch_pending(
            batch_size=10,
            event_types=[SEARCH_INDEX_REQUESTED],
        )
        await session.commit()

    assert result.to_dict() == {"claimed": 1, "sent": 1, "failed": 0, "dead": 0}
    document = index_adapter.documents[f"{tenant_id}:{node_id}"]
    assert document.name == "搜索索引.txt"
    assert document.node_id == node_id
    assert document.space_id == str(space["id"])
    assert document.content_hash == "d" * 64
    assert document.acl_tokens == [f"space:{space['id']}:role:owner"]
    assert document.deny_acl_tokens == []


@pytest.mark.asyncio
async def test_file_change_search_events_update_and_delete_index_document(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="search-file-change-events")
    tenant_id = UUID(str(space["tenant_id"]))
    async with session_factory() as session:
        session.add(
            FileBlob(
                tenant_id=tenant_id,
                hash_algo="sha256",
                content_hash="f" * 64,
                size_bytes=384,
                storage_key="objects/test/ff",
                mime_type="text/plain",
                ref_count=0,
            )
        )
        await session.commit()

    upload_response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "索引变更前.txt",
            "size_bytes": 384,
            "content_hash": "f" * 64,
            "hash_algo": "sha256",
            "mime_type": "text/plain",
        },
    )
    assert upload_response.status_code == 201
    node_id = UUID(upload_response.json()["node_id"])
    index_adapter = InMemorySearchIndexAdapter()

    await _dispatch_search_events(
        session_factory=session_factory,
        settings=settings,
        index_adapter=index_adapter,
        batch_size=10,
    )
    assert index_adapter.documents[f"{tenant_id}:{node_id}"].name == "索引变更前.txt"

    rename_response = await client.patch(
        f"/api/v1/files/{node_id}",
        headers={"X-CSRF-Token": token},
        json={"name": "索引变更后.txt"},
    )
    assert rename_response.status_code == 200

    await _dispatch_search_events(
        session_factory=session_factory,
        settings=settings,
        index_adapter=index_adapter,
        batch_size=10,
    )
    assert index_adapter.documents[f"{tenant_id}:{node_id}"].name == "索引变更后.txt"

    delete_response = await client.delete(
        f"/api/v1/files/{node_id}",
        headers={"X-CSRF-Token": token},
    )
    assert delete_response.status_code == 200

    await _dispatch_search_events(
        session_factory=session_factory,
        settings=settings,
        index_adapter=index_adapter,
        batch_size=10,
    )
    assert f"{tenant_id}:{node_id}" not in index_adapter.documents
    assert index_adapter.deleted_document_ids[-1] == f"{tenant_id}:{node_id}"


@pytest.mark.asyncio
async def test_acl_rebuild_event_reindexes_file_acl_tokens(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="search-acl-rebuild-space")
    tenant_id = UUID(str(space["tenant_id"]))
    _, actor_id = await _get_seeded_tenant_and_user(session_factory)
    subject_id = uuid4()
    async with session_factory() as session:
        session.add(
            FileBlob(
                tenant_id=tenant_id,
                hash_algo="sha256",
                content_hash="e" * 64,
                size_bytes=512,
                storage_key="objects/test/ee",
                mime_type="text/plain",
                ref_count=0,
            )
        )
        await session.commit()

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "ACL重建.txt",
            "size_bytes": 512,
            "content_hash": "e" * 64,
            "hash_algo": "sha256",
            "mime_type": "text/plain",
        },
    )
    assert response.status_code == 201
    node_id = UUID(response.json()["node_id"])
    index_adapter = InMemorySearchIndexAdapter()

    async with session_factory() as session:
        dispatcher = OutboxDispatcher(
            repository=AuditRepository(session),
            publisher=search_tasks.SearchOutboxPublisher(
                index_service=SearchIndexService(
                    repository=SearchRepository(session),
                    index_adapter=index_adapter,
                ),
                fallback_publisher=LoggingOutboxPublisher(),
            ),
            max_retries=settings.outbox_max_retries,
        )
        await dispatcher.dispatch_pending(batch_size=10, event_types=[SEARCH_INDEX_REQUESTED])
        await session.commit()

    document_id = f"{tenant_id}:{node_id}"
    assert index_adapter.documents[document_id].acl_tokens == [f"space:{space['id']}:role:owner"]

    async with session_factory() as session:
        session.add(
            AclEntry(
                tenant_id=tenant_id,
                node_id=node_id,
                subject_type="user",
                subject_id=subject_id,
                effect="allow",
                actions=["download"],
                inherit=True,
                created_by=actor_id,
            )
        )
        await AuditRepository(session).add_outbox_event(
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
        await session.commit()

    async with session_factory() as session:
        dispatcher = OutboxDispatcher(
            repository=AuditRepository(session),
            publisher=search_tasks.SearchOutboxPublisher(
                index_service=SearchIndexService(
                    repository=SearchRepository(session),
                    index_adapter=index_adapter,
                ),
                fallback_publisher=LoggingOutboxPublisher(),
            ),
            max_retries=settings.outbox_max_retries,
        )
        result = await dispatcher.dispatch_pending(
            batch_size=10,
            event_types=[SEARCH_ACL_REBUILD_REQUESTED],
        )
        await session.commit()

    assert result.to_dict() == {"claimed": 1, "sent": 1, "failed": 0, "dead": 0}
    rebuilt_document = index_adapter.documents[document_id]
    assert rebuilt_document.acl_tokens == sorted(
        [f"space:{space['id']}:role:owner", f"user:{subject_id}"]
    )


async def _dispatch_search_events(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    index_adapter: InMemorySearchIndexAdapter,
    batch_size: int,
) -> None:
    async with session_factory() as session:
        dispatcher = OutboxDispatcher(
            repository=AuditRepository(session),
            publisher=search_tasks.SearchOutboxPublisher(
                index_service=SearchIndexService(
                    repository=SearchRepository(session),
                    index_adapter=index_adapter,
                ),
                fallback_publisher=LoggingOutboxPublisher(),
            ),
            max_retries=settings.outbox_max_retries,
        )
        result = await dispatcher.dispatch_pending(
            batch_size=batch_size,
            event_types=[SEARCH_INDEX_REQUESTED],
        )
        await session.commit()
    assert result.failed == 0
    assert result.dead == 0
