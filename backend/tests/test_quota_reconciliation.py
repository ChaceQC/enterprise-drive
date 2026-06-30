from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditContext
from app.modules.audit.service import AuditService
from app.modules.file.models import FileBlob
from app.modules.quota.models import QuotaAccount, QuotaLedger
from app.modules.quota.reconciliation import QuotaReconciliationService
from app.modules.quota.repository import QuotaRepository
from app.workers import quota_tasks
from tests.helpers import (
    client as client,
)
from tests.helpers import (
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


async def create_instant_file(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    csrf_token: str,
    *,
    tenant_id: str,
    space_id: str,
    parent_id: str,
    file_name: str,
    content_hash: str,
    size_bytes: int,
) -> dict[str, object]:
    async with session_factory() as session:
        blob = FileBlob(
            tenant_id=UUID(tenant_id),
            hash_algo="sha256",
            content_hash=content_hash,
            size_bytes=size_bytes,
            storage_key=f"objects/test/{content_hash[:2]}/{content_hash}",
            mime_type="text/plain",
            ref_count=0,
        )
        session.add(blob)
        await session.commit()

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "space_id": space_id,
            "parent_id": parent_id,
            "file_name": file_name,
            "size_bytes": size_bytes,
            "content_hash": content_hash,
            "hash_algo": "sha256",
            "mime_type": "text/plain",
        },
    )
    assert response.status_code == 201
    payload = dict(response.json())
    assert payload["mode"] == "instant"
    return payload


@pytest.mark.asyncio
async def test_reconcile_space_usage_reports_snapshot_and_ledger_drift(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="quota-report-space")
    await create_instant_file(
        client,
        session_factory,
        csrf_token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="容量报告.txt",
        content_hash="d" * 64,
        size_bytes=4096,
    )

    async with session_factory() as session:
        quota_account = (await session.execute(select(QuotaAccount))).scalar_one()
        quota_account.used_bytes = 1024
        ledger = (await session.execute(select(QuotaLedger))).scalar_one()
        await session.delete(ledger)
        await session.commit()

    async with session_factory() as session:
        service = QuotaReconciliationService(
            repository=QuotaRepository(session),
            default_space_limit_bytes=settings.default_space_quota_bytes,
        )
        result = await service.reconcile_space_usage(
            tenant_id=UUID(str(space["tenant_id"])),
            repair=False,
        )

    assert result.scanned == 1
    assert result.missing_accounts == 0
    assert result.snapshot_drifts == 1
    assert result.ledger_drifts == 1
    assert result.repaired_accounts == 0
    assert result.ledger_entries == 0
    assert len(result.items) == 1
    item = result.items[0]
    assert item.space_id == UUID(str(space["id"]))
    assert item.actual_bytes == 4096
    assert item.used_bytes == 1024
    assert item.ledger_bytes == 0
    assert item.snapshot_delta_bytes == 3072
    assert item.ledger_delta_bytes == 4096
    assert item.repaired is False

    async with session_factory() as session:
        quota_account = (await session.execute(select(QuotaAccount))).scalar_one()
        ledgers = (await session.execute(select(QuotaLedger))).scalars().all()

    assert quota_account.used_bytes == 1024
    assert ledgers == []


@pytest.mark.asyncio
async def test_reconcile_space_usage_repairs_snapshot_and_writes_ledger_delta(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="quota-repair-space")
    await create_instant_file(
        client,
        session_factory,
        csrf_token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="容量修复.txt",
        content_hash="e" * 64,
        size_bytes=8192,
    )

    async with session_factory() as session:
        quota_account = (await session.execute(select(QuotaAccount))).scalar_one()
        quota_account.used_bytes = 2048
        ledger = (await session.execute(select(QuotaLedger))).scalar_one()
        await session.delete(ledger)
        await session.commit()
        account_id = quota_account.id

    async with session_factory() as session:
        service = QuotaReconciliationService(
            repository=QuotaRepository(session),
            default_space_limit_bytes=settings.default_space_quota_bytes,
            audit_service=AuditService(repository=AuditRepository(session)),
        )
        result = await service.reconcile_space_usage(
            tenant_id=UUID(str(space["tenant_id"])),
            repair=True,
            audit_context=AuditContext(request_id="req_quota_repair"),
        )

    assert result.scanned == 1
    assert result.snapshot_drifts == 1
    assert result.ledger_drifts == 1
    assert result.repaired_accounts == 1
    assert result.ledger_entries == 1
    assert result.items[0].repaired is True
    assert result.items[0].snapshot_delta_bytes == 6144
    assert result.items[0].ledger_delta_bytes == 8192

    async with session_factory() as session:
        quota_account = (await session.execute(select(QuotaAccount))).scalar_one()
        ledgers = (await session.execute(select(QuotaLedger))).scalars().all()
        audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "quota.reconciled"))
        ).scalar_one()
        outbox_event = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.event_type == "audit.quota.reconciled")
            )
        ).scalar_one()

    assert quota_account.used_bytes == 8192
    assert len(ledgers) == 1
    assert ledgers[0].account_id == account_id
    assert ledgers[0].delta_bytes == 8192
    assert ledgers[0].reason == "quota_reconciled"
    assert ledgers[0].ref_type == "space"
    assert ledgers[0].ref_id == UUID(str(space["id"]))
    assert audit.actor_id is None
    assert audit.actor_type == "system"
    assert audit.request_id == "req_quota_repair"
    assert audit.metadata_json["snapshot_drifts"] == 1
    assert audit.metadata_json["ledger_entries"] == 1
    assert outbox_event.aggregate_type == "audit_log"


@pytest.mark.asyncio
async def test_reconcile_space_usage_repairs_missing_space_account(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="quota-missing-account-space")
    await create_instant_file(
        client,
        session_factory,
        csrf_token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="缺账号修复.txt",
        content_hash="f" * 64,
        size_bytes=2048,
    )

    async with session_factory() as session:
        quota_account = (await session.execute(select(QuotaAccount))).scalar_one()
        ledger = (await session.execute(select(QuotaLedger))).scalar_one()
        await session.delete(ledger)
        await session.delete(quota_account)
        await session.commit()

    async with session_factory() as session:
        service = QuotaReconciliationService(
            repository=QuotaRepository(session),
            default_space_limit_bytes=settings.default_space_quota_bytes,
        )
        result = await service.reconcile_space_usage(
            tenant_id=UUID(str(space["tenant_id"])),
            repair=True,
        )

    assert result.scanned == 1
    assert result.missing_accounts == 1
    assert result.snapshot_drifts == 0
    assert result.ledger_drifts == 1
    assert result.repaired_accounts == 1
    assert result.ledger_entries == 1
    assert result.items[0].missing_account is True
    assert result.items[0].used_bytes is None
    assert result.items[0].ledger_delta_bytes == 2048

    async with session_factory() as session:
        quota_account = (await session.execute(select(QuotaAccount))).scalar_one()
        ledgers = (
            (await session.execute(select(QuotaLedger).order_by(QuotaLedger.created_at)))
            .scalars()
            .all()
        )

    assert quota_account.owner_type == "space"
    assert quota_account.owner_id == UUID(str(space["id"]))
    assert quota_account.limit_bytes == settings.default_space_quota_bytes
    assert quota_account.used_bytes == 2048
    assert [ledger.delta_bytes for ledger in ledgers] == [2048]
    assert ledgers[0].reason == "quota_reconciled"


@pytest.mark.asyncio
async def test_quota_reconcile_worker_aggregates_tenant_results(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="quota-worker-space")
    other_space = await create_space(client, csrf_token, slug="quota-worker-other-space")
    await create_instant_file(
        client,
        session_factory,
        csrf_token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="任务校准.txt",
        content_hash="a" * 64,
        size_bytes=1024,
    )
    await create_instant_file(
        client,
        session_factory,
        csrf_token,
        tenant_id=str(other_space["tenant_id"]),
        space_id=str(other_space["id"]),
        parent_id=str(other_space["root_node_id"]),
        file_name="任务校准二.txt",
        content_hash="b" * 64,
        size_bytes=2048,
    )

    async with session_factory() as session:
        quota_accounts = (await session.execute(select(QuotaAccount))).scalars().all()
        for quota_account in quota_accounts:
            quota_account.used_bytes = 0
        await session.commit()

    monkeypatch.setattr(quota_tasks, "get_settings", lambda: settings)
    monkeypatch.setattr(quota_tasks, "get_session_factory", lambda: session_factory)

    result = await quota_tasks._reconcile_space_usage(
        tenant_id=UUID(str(space["tenant_id"])),
        limit=1,
        repair=True,
        request_id="req_quota_worker",
    )

    assert result["scanned"] == 2
    assert result["snapshot_drifts"] == 2
    assert result["repaired_accounts"] == 2
    assert isinstance(result["items"], list)
    assert {item["space_id"] for item in result["items"]} == {
        str(space["id"]),
        str(other_space["id"]),
    }

    async with session_factory() as session:
        quota_accounts = (await session.execute(select(QuotaAccount))).scalars().all()
        audits = (
            (await session.execute(select(AuditLog).where(AuditLog.action == "quota.reconciled")))
            .scalars()
            .all()
        )

    used_bytes_by_space = {str(account.owner_id): account.used_bytes for account in quota_accounts}
    assert used_bytes_by_space[str(space["id"])] == 1024
    assert used_bytes_by_space[str(other_space["id"])] == 2048
    assert {audit.request_id for audit in audits} == {"req_quota_worker"}
