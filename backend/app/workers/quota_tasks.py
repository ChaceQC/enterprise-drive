from __future__ import annotations

import asyncio
from uuid import UUID

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.infrastructure.queue.celery_app import celery_app
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditContext
from app.modules.audit.service import AuditService
from app.modules.auth.repository import AuthRepository
from app.modules.quota.reconciliation import QuotaReconciliationService
from app.modules.quota.repository import QuotaRepository

_COUNTER_KEYS = (
    "scanned",
    "missing_accounts",
    "snapshot_drifts",
    "ledger_drifts",
    "repaired_accounts",
    "ledger_entries",
)


def reconcile_space_usage(
    tenant_id: str | None = None,
    limit: int = 100,
    repair: bool = False,
    request_id: str | None = None,
    scan_all: bool = True,
) -> dict[str, object]:
    return asyncio.run(
        _reconcile_space_usage(
            tenant_id=UUID(tenant_id) if tenant_id else None,
            limit=limit,
            repair=repair,
            request_id=request_id,
            scan_all=scan_all,
        )
    )


celery_app.task(name="quota.reconcile_space_usage")(reconcile_space_usage)


async def _reconcile_space_usage(
    *,
    tenant_id: UUID | None,
    limit: int,
    repair: bool,
    request_id: str | None,
    scan_all: bool = True,
) -> dict[str, object]:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        tenant_ids = [tenant_id] if tenant_id else await AuthRepository(session).list_tenant_ids()
        total: dict[str, object] = {
            "scanned": 0,
            "missing_accounts": 0,
            "snapshot_drifts": 0,
            "ledger_drifts": 0,
            "repaired_accounts": 0,
            "ledger_entries": 0,
            "items": [],
        }
        if limit <= 0:
            return total
        for current_tenant_id in tenant_ids:
            service = QuotaReconciliationService(
                repository=QuotaRepository(session),
                default_space_limit_bytes=settings.default_space_quota_bytes,
                audit_service=AuditService(repository=AuditRepository(session)),
            )
            after_space_id: UUID | None = None
            while True:
                result = await service.reconcile_space_usage(
                    tenant_id=current_tenant_id,
                    limit=limit,
                    after_space_id=after_space_id,
                    repair=repair,
                    audit_context=AuditContext(request_id=request_id),
                )
                payload = result.to_dict()
                for key in _COUNTER_KEYS:
                    total[key] = _counter(total, key) + _counter(payload, key)
                total_items = total["items"]
                payload_items = payload["items"]
                assert isinstance(total_items, list)
                assert isinstance(payload_items, list)
                total_items.extend(payload_items)
                if not scan_all or result.next_space_id is None:
                    break
                after_space_id = result.next_space_id
        return total


def _counter(payload: dict[str, object], key: str) -> int:
    value = payload[key]
    assert isinstance(value, int)
    return value
