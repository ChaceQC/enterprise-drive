from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.admin.job_repository import AdminJobRepository
from app.modules.audit.models import OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditContext
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.models import Node
from app.modules.governance.models import PermissionRebuildOperation
from app.modules.governance.permission_rebuild import PermissionRebuildProcessor
from app.modules.governance.repository import GovernanceRepository
from app.modules.governance.schemas import (
    LifecyclePolicyUpdateRequest,
    LifecycleRunCreateRequest,
)
from app.modules.governance.service import GovernanceService
from app.modules.search.events import SEARCH_ACL_REBUILD_REQUESTED
from app.workers.search_tasks import SearchOutboxPublisher
from tests.helpers import client as client
from tests.helpers import create_space, login, seed_admin
from tests.helpers import session_factory as session_factory
from tests.helpers import settings as settings
from tests.helpers import storage_adapter as storage_adapter


@pytest.mark.asyncio
async def test_permission_rebuild_resumes_batches_and_restarts_for_new_version(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space_payload = await create_space(client, csrf_token, slug="rebuild-space")
    tenant_id = UUID(str(space_payload["tenant_id"]))
    space_id = UUID(str(space_payload["id"]))
    root_id = UUID(str(space_payload["root_node_id"]))

    async with session_factory() as session:
        admin = (
            await session.execute(
                select(User).where(
                    User.tenant_id == tenant_id,
                    User.username == "admin",
                )
            )
        ).scalar_one()
        for index in range(5):
            session.add(
                Node(
                    tenant_id=tenant_id,
                    space_id=space_id,
                    parent_id=root_id,
                    node_type="file",
                    name=f"file-{index}.txt",
                    normalized_name=f"file-{index}.txt",
                    owner_id=admin.id,
                )
            )
        await session.commit()

    fake_index = _FakeIndexService()
    async with session_factory() as session:
        repository = GovernanceRepository(session)
        operation, created = await repository.create_or_refresh_permission_rebuild(
            tenant_id=tenant_id,
            space_id=space_id,
            root_node_id=None,
            scope="space",
            permission_version=1,
            requested_by=admin.id,
            request_id="request-1",
        )
        await repository.commit()
        assert created is True
        processor = PermissionRebuildProcessor(
            repository=repository,
            index_service=fake_index,  # type: ignore[arg-type]
            audit_service=AuditService(repository=AuditRepository(session)),
            batch_size=2,
        )
        first_status = await processor.process_operation(
            operation_id=operation.id,
            max_batches=1,
        )
        assert first_status == "running"

    async with session_factory() as session:
        repository = GovernanceRepository(session)
        active, created = await repository.create_or_refresh_permission_rebuild(
            tenant_id=tenant_id,
            space_id=space_id,
            root_node_id=None,
            scope="space",
            permission_version=2,
            requested_by=admin.id,
            request_id="request-2",
        )
        await repository.commit()
        assert created is False
        assert active.restart_requested is True

        processor = PermissionRebuildProcessor(
            repository=repository,
            index_service=fake_index,  # type: ignore[arg-type]
            audit_service=AuditService(repository=AuditRepository(session)),
            batch_size=2,
        )
        assert await processor.process_operation(operation_id=active.id) == "completed"

    async with session_factory() as session:
        stored = await session.get(PermissionRebuildOperation, operation.id)
        assert stored is not None
        assert stored.status == "completed"
        assert stored.permission_version == 2
        assert stored.processed_count == 5
        assert stored.indexed_count == 5
        assert stored.attempt_count == 1
    assert len(fake_index.node_ids) == 7


@pytest.mark.asyncio
async def test_lifecycle_policy_version_and_run_are_persisted(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    fake_celery = _FakeCelery()
    async with session_factory() as session:
        admin = (await session.execute(select(User).where(User.username == "admin"))).scalar_one()
        service = GovernanceService(
            repository=GovernanceRepository(session),
            job_repository=AdminJobRepository(session),
            audit_service=AuditService(repository=AuditRepository(session)),
            celery_app=fake_celery,  # type: ignore[arg-type]
            settings=settings,
        )
        initial = await service.get_lifecycle_policy(
            current_user=admin,
            audit_context=AuditContext(request_id="policy-read"),
        )
        updated = await service.update_lifecycle_policy(
            current_user=admin,
            request=LifecyclePolicyUpdateRequest(
                trash_retention_days=45,
                preview_retention_days=60,
                expire_uploads=True,
                expire_shares=True,
                cleanup_unreferenced_blobs=True,
                cleanup_orphaned_objects=True,
                expected_version=initial.version,
            ),
            audit_context=AuditContext(request_id="policy-update"),
        )
        run = await service.create_lifecycle_run(
            current_user=admin,
            request=LifecycleRunCreateRequest(dry_run=True, limit=25),
            audit_context=AuditContext(request_id="policy-run"),
        )

    assert updated.version == initial.version + 1
    assert updated.trash_retention_days == 45
    assert updated.cleanup_orphaned_objects is True
    assert run.status == "pending"
    assert run.dry_run is True
    assert run.policy_version == updated.version
    assert fake_celery.calls[0] == (
        "governance.run_lifecycle_policy",
        {"job_id": str(run.id)},
        "maintenance",
    )

    async with session_factory() as session:
        job = await AdminJobRepository(session).get_job(
            tenant_id=admin.tenant_id,
            job_id=run.id,
            kind="governance",
        )
        assert job is not None
        assert job.parameters_json["trash_retention_days"] == 45
        assert job.parameters_json["preview_retention_days"] == 60
        assert job.parameters_json["cleanup_orphaned_objects"] is True
        assert job.celery_task_id == "fake-task-id"


@pytest.mark.asyncio
async def test_search_acl_event_queues_persistent_permission_rebuild(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space_payload = await create_space(client, csrf_token, slug="event-rebuild")
    tenant_id = UUID(str(space_payload["tenant_id"]))
    space_id = UUID(str(space_payload["id"]))

    async with session_factory() as session:
        repository = GovernanceRepository(session)
        publisher = SearchOutboxPublisher(
            index_service=_FakeIndexService(),  # type: ignore[arg-type]
            governance_repository=repository,
            fallback_publisher=_FakeFallbackPublisher(),
        )
        event = OutboxEvent(
            tenant_id=tenant_id,
            event_type=SEARCH_ACL_REBUILD_REQUESTED,
            aggregate_type="space",
            aggregate_id=space_id,
            payload={
                "scope": "space",
                "resource_id": str(space_id),
                "permission_version": 3,
            },
        )

        await publisher.publish(event)
        operation = await repository.get_active_permission_rebuild(
            tenant_id=tenant_id,
            scope_key=f"space:{space_id}",
        )

    assert operation is not None
    assert operation.permission_version == 3
    assert operation.status == "pending"


@pytest.mark.asyncio
async def test_governance_admin_routes_expose_policy_and_rebuild_progress(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="governance-api")

    overview = await client.get("/api/v1/admin/governance/overview")
    policy = await client.get("/api/v1/admin/governance/lifecycle-policy")
    assert overview.status_code == 200
    assert policy.status_code == 200

    updated = await client.patch(
        "/api/v1/admin/governance/lifecycle-policy",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "trash_retention_days": 40,
            "preview_retention_days": 50,
            "expire_uploads": True,
            "expire_shares": True,
            "cleanup_unreferenced_blobs": True,
            "cleanup_orphaned_objects": False,
            "expected_version": policy.json()["version"],
        },
    )
    rebuild = await client.post(
        "/api/v1/admin/governance/permission-rebuilds",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "scope": "space",
            "space_id": space["id"],
        },
    )
    listed = await client.get(
        "/api/v1/admin/governance/permission-rebuilds",
        params={"status": "pending"},
    )

    assert updated.status_code == 200
    assert updated.json()["version"] == policy.json()["version"] + 1
    assert rebuild.status_code == 202
    assert rebuild.json()["scope"] == "space"
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == rebuild.json()["id"]


class _FakeIndexService:
    def __init__(self) -> None:
        self.node_ids: list[UUID] = []

    async def index_file(self, *, tenant_id: UUID, node_id: UUID) -> bool:
        del tenant_id
        self.node_ids.append(node_id)
        return True


class _FakeCelery:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], str]] = []

    def send_task(
        self,
        name: str,
        *,
        kwargs: dict[str, object],
        queue: str,
    ) -> SimpleNamespace:
        self.calls.append((name, kwargs, queue))
        return SimpleNamespace(id="fake-task-id")


class _FakeFallbackPublisher:
    async def publish(self, event: OutboxEvent) -> None:
        del event
