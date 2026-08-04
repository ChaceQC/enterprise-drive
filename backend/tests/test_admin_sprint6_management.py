from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.security import utc_now
from app.infrastructure.storage.testing import InMemoryStorageAdapter
from app.modules.admin.governance_repository import AdminGovernanceRepository
from app.modules.admin.governance_schemas import AdminMaintenanceRunRequest
from app.modules.admin.governance_service import (
    AdminGovernanceService,
    _maintenance_parameters,
    _validate_export_filters,
)
from app.modules.admin.job_repository import AdminJobRepository
from app.modules.admin.models import AdminJob
from app.modules.audit.models import AuditLog
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import Tenant, User
from app.modules.file.models import Node
from app.modules.permission.models import SpaceMember
from app.modules.quota.models import QuotaAccount
from app.modules.space.models import Space
from app.workers import admin_tasks
from tests.helpers import (
    client as client,
)
from tests.helpers import (
    create_second_user,
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


@pytest.mark.asyncio
async def test_super_admin_manages_spaces_with_cursor_and_preconditions(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    member_id = await create_second_user(session_factory)

    first = await client.post(
        "/api/v1/admin/spaces",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "owner_id": str(member_id),
            "slug": "admin-first",
            "name": "管理空间一",
            "limit_bytes": 2048,
        },
    )
    second = await client.post(
        "/api/v1/admin/spaces",
        headers={"X-CSRF-Token": csrf_token},
        json={"slug": "admin-second", "name": "管理空间二"},
    )
    assert first.status_code == 201
    assert first.json()["owner_id"] == str(member_id)
    assert first.json()["member_count"] == 1
    assert first.json()["node_count"] == 1
    assert first.json()["limit_bytes"] == 2048
    assert first.json()["version"] == 1
    assert second.status_code == 201

    first_page = await client.get(
        "/api/v1/admin/spaces",
        params={"page_size": 1, "is_active": True},
    )
    second_page = await client.get(
        "/api/v1/admin/spaces",
        params={
            "page_size": 1,
            "is_active": True,
            "cursor": first_page.json()["next_cursor"],
        },
    )
    assert first_page.status_code == 200
    assert first_page.json()["items"][0]["id"] == second.json()["id"]
    assert second_page.status_code == 200
    assert second_page.json()["items"][0]["id"] == first.json()["id"]

    updated = await client.patch(
        f"/api/v1/admin/spaces/{first.json()['id']}",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "expected_version": 1,
            "name": "管理空间一已更新",
            "is_active": False,
        },
    )
    stale = await client.patch(
        f"/api/v1/admin/spaces/{first.json()['id']}",
        headers={"X-CSRF-Token": csrf_token},
        json={"expected_version": 1, "name": "过期更新"},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["is_active"] is False
    assert stale.status_code == 409
    assert stale.json()["code"] == "ADMIN_SPACE_CHANGED"

    async with session_factory() as session:
        space = await session.get(Space, UUID(first.json()["id"]))
        account = (
            await session.execute(
                select(QuotaAccount).where(
                    QuotaAccount.owner_type == "space",
                    QuotaAccount.owner_id == UUID(first.json()["id"]),
                )
            )
        ).scalar_one()
        member = (
            await session.execute(
                select(SpaceMember).where(
                    SpaceMember.space_id == UUID(first.json()["id"]),
                    SpaceMember.user_id == member_id,
                )
            )
        ).scalar_one()
        root = (
            await session.execute(
                select(Node).where(
                    Node.space_id == UUID(first.json()["id"]),
                    Node.parent_id.is_(None),
                )
            )
        ).scalar_one()
    assert space is not None and space.owner_id == member_id
    assert account.limit_bytes == 2048
    assert member.role == "owner"
    assert root.owner_id == member_id


@pytest.mark.asyncio
async def test_admin_stats_and_export_job_lifecycle(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="stats-space")
    tenant_id = UUID(str(space["tenant_id"]))

    stats = await client.get("/api/v1/admin/stats/overview")
    assert stats.status_code == 200
    assert stats.json()["users_total"] == 1
    assert stats.json()["spaces_total"] == 1
    assert stats.json()["spaces_active"] == 1
    assert stats.json()["nodes_total"] == 1

    async with session_factory() as session:
        tenant = await session.get(Tenant, tenant_id)
        admin = (
            await session.execute(
                select(User).where(
                    User.tenant_id == tenant_id,
                    User.username == "admin",
                )
            )
        ).scalar_one()
        assert tenant is not None
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_id=admin.id,
                action="fixture.export",
                resource_type="space",
                resource_id=UUID(str(space["id"])),
                result="allowed",
                risk_level="medium",
                metadata_json={},
            )
        )
        job = AdminJob(
            tenant_id=tenant_id,
            kind="export",
            operation="audit_logs",
            created_by=admin.id,
            parameters_json={"filters": {"action": "fixture.export"}},
            result_json={},
        )
        session.add(job)
        await session.commit()
        export_id = job.id

    monkeypatch.setattr(admin_tasks, "get_settings", lambda: settings)
    monkeypatch.setattr(admin_tasks, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(admin_tasks, "S3StorageAdapter", lambda *, settings: storage_adapter)
    result = await admin_tasks._generate_export(job_id=export_id)
    assert result["row_count"] == 1
    assert len(str(result["content_sha256"])) == 64
    assert result["signature_algorithm"] == "hmac-sha256"

    detail = await client.get(f"/api/v1/admin/exports/{export_id}")
    download = await client.get(f"/api/v1/admin/exports/{export_id}/download")
    assert detail.status_code == 200
    assert detail.json()["status"] == "succeeded"
    assert detail.json()["result"]["row_count"] == 1
    assert download.status_code == 200
    assert download.json()["size_bytes"] > 0
    assert len(download.json()["content_sha256"]) == 64
    assert download.json()["signature_algorithm"] == "hmac-sha256"
    assert download.json()["signature_key_id"] == settings.audit_signing_key_id
    assert len(download.json()["signature_value"]) == 64
    assert download.json()["download_url"].startswith("https://storage.test/")

    async with session_factory() as session:
        stored_job = await session.get(AdminJob, export_id)
        assert stored_job is not None
        assert stored_job.storage_key is not None
        assert stored_job.content_sha256 == download.json()["content_sha256"]
        assert stored_job.signature_value == download.json()["signature_value"]
        assert stored_job.storage_key.startswith(f"exports/{tenant_id}/{export_id}/")
        content = storage_adapter.object_contents[
            (settings.s3_bucket, stored_job.storage_key)
        ].decode("utf-8-sig")
        assert "fixture.export" in content
        stored_job.completed_at = utc_now() - timedelta(
            days=settings.admin_export_retention_days + 1
        )
        await session.commit()

    cleanup = await admin_tasks._cleanup_expired_exports(limit=10)
    assert cleanup == {"scanned": 1, "expired": 1, "storage_errors": 0}
    async with session_factory() as session:
        expired_job = await session.get(AdminJob, export_id)
        assert expired_job is not None
        assert expired_job.status == "expired"
        assert expired_job.storage_key is None


@pytest.mark.asyncio
async def test_admin_maintenance_run_is_persisted_and_tenant_scoped(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    async with session_factory() as session:
        admin = (await session.execute(select(User).where(User.username == "admin"))).scalar_one()
        fake_celery = _FakeCelery()
        service = AdminGovernanceService(
            repository=AdminGovernanceRepository(session),
            job_repository=AdminJobRepository(session),
            audit_service=AuditService(repository=AuditRepository(session)),
            celery_app=fake_celery,
            storage=storage_adapter,
            settings=settings,
        )
        response = await service.create_maintenance_run(
            current_user=admin,
            request=_maintenance_request(),
            audit_context=None,
        )

    assert response.status == "pending"
    assert fake_celery.calls == [
        (
            "admin.execute_maintenance_run",
            {"job_id": str(response.id)},
            "maintenance",
        )
    ]
    async with session_factory() as session:
        job = await session.get(AdminJob, response.id)
        assert job is not None
        assert job.parameters_json["tenant_id"] == str(admin.tenant_id)
        assert job.celery_task_id == "fake-task-id"


def test_permission_rebuild_maintenance_parameters_match_task_signature() -> None:
    tenant_id = uuid4()
    request = AdminMaintenanceRunRequest(
        task_name="governance.process_permission_rebuilds",
        dry_run=False,
        limit=25,
    )

    assert _maintenance_parameters(
        request=request,
        tenant_id=tenant_id,
        request_id="req-sprint12",
    ) == {
        "tenant_id": str(tenant_id),
        "limit": 25,
    }


@pytest.mark.asyncio
async def test_admin_space_owner_transfer_updates_root(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    original_owner_id = await create_second_user(session_factory)
    created = await client.post(
        "/api/v1/admin/spaces",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "owner_id": str(original_owner_id),
            "slug": "owner-transfer",
            "name": "Owner transfer",
        },
    )
    assert created.status_code == 201

    async with session_factory() as session:
        admin_id = (
            await session.execute(select(User.id).where(User.username == "admin"))
        ).scalar_one()

    updated = await client.patch(
        f"/api/v1/admin/spaces/{created.json()['id']}",
        headers={"X-CSRF-Token": csrf_token},
        json={"expected_version": 1, "owner_id": str(admin_id)},
    )
    assert updated.status_code == 200
    assert updated.json()["owner_id"] == str(admin_id)

    async with session_factory() as session:
        root_owner_id = (
            await session.execute(
                select(Node.owner_id).where(
                    Node.space_id == UUID(created.json()["id"]),
                    Node.parent_id.is_(None),
                )
            )
        ).scalar_one()
    assert root_owner_id == admin_id


def test_admin_export_safety_guards() -> None:
    assert admin_tasks._safe_csv_cell('=HYPERLINK("https://example.invalid")').startswith("'=")
    assert admin_tasks._safe_csv_cell("  +SUM(1,1)").startswith("'  +")
    assert admin_tasks._safe_csv_cell("ordinary") == "ordinary"
    assert admin_tasks._audit_result_summary(
        {
            "scanned": 2,
            "items": [{"space_id": "sensitive-detail"}],
            "items_truncated": False,
            "nested": {"internal": "value"},
        }
    ) == {
        "scanned": 2,
        "items_count": 1,
        "items_truncated": False,
        "nested_keys": ["internal"],
    }

    with pytest.raises(admin_tasks.AdminExportRowLimitExceededError):
        admin_tasks._raise_if_export_too_large(
            resource="users",
            count=11,
            max_rows=10,
        )

    with pytest.raises(ApiError):
        _validate_export_filters(
            resource="spaces",
            filters={"space_type": "unsupported"},
        )
    with pytest.raises(ApiError):
        _validate_export_filters(
            resource="audit_logs",
            filters={
                "created_from": "2026-08-03T02:00:00Z",
                "created_to": "2026-08-03T01:00:00Z",
            },
        )


class _FakeCelery:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], str]] = []

    def send_task(
        self,
        name: str,
        *,
        kwargs: dict[str, str],
        queue: str,
    ) -> SimpleNamespace:
        self.calls.append((name, kwargs, queue))
        return SimpleNamespace(id="fake-task-id")


def _maintenance_request() -> AdminMaintenanceRunRequest:
    return AdminMaintenanceRunRequest(
        task_name="file.cleanup_orphaned_objects",
        dry_run=True,
        limit=10,
        scan_all=False,
    )
