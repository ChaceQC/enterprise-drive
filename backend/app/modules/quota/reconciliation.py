from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from app.api.errors import ApiError
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.quota.repository import QuotaRepository


@dataclass(frozen=True)
class SpaceQuotaReconciliationItem:
    space_id: UUID
    account_id: UUID | None
    actual_bytes: int
    used_bytes: int | None
    ledger_bytes: int
    snapshot_delta_bytes: int | None
    ledger_delta_bytes: int | None
    missing_account: bool
    repaired: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "space_id": str(self.space_id),
            "account_id": str(self.account_id) if self.account_id else None,
            "actual_bytes": self.actual_bytes,
            "used_bytes": self.used_bytes,
            "ledger_bytes": self.ledger_bytes,
            "snapshot_delta_bytes": self.snapshot_delta_bytes,
            "ledger_delta_bytes": self.ledger_delta_bytes,
            "missing_account": self.missing_account,
            "repaired": self.repaired,
        }


@dataclass
class SpaceQuotaReconciliationResult:
    scanned: int = 0
    missing_accounts: int = 0
    snapshot_drifts: int = 0
    ledger_drifts: int = 0
    repaired_accounts: int = 0
    ledger_entries: int = 0
    next_space_id: UUID | None = None
    items: list[SpaceQuotaReconciliationItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "scanned": self.scanned,
            "missing_accounts": self.missing_accounts,
            "snapshot_drifts": self.snapshot_drifts,
            "ledger_drifts": self.ledger_drifts,
            "repaired_accounts": self.repaired_accounts,
            "ledger_entries": self.ledger_entries,
            "next_space_id": str(self.next_space_id) if self.next_space_id else None,
            "items": [item.to_dict() for item in self.items],
        }


class QuotaReconciliationService:
    def __init__(
        self,
        *,
        repository: QuotaRepository,
        default_space_limit_bytes: int,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.default_space_limit_bytes = default_space_limit_bytes
        self.audit_service = audit_service

    async def reconcile_space_usage(
        self,
        *,
        tenant_id: UUID,
        limit: int = 100,
        after_space_id: UUID | None = None,
        repair: bool = False,
        audit_context: AuditContext | None = None,
    ) -> SpaceQuotaReconciliationResult:
        if limit <= 0:
            return SpaceQuotaReconciliationResult()

        try:
            snapshots = await self.repository.list_space_usage_snapshots(
                tenant_id=tenant_id,
                limit=limit + 1,
                after_space_id=after_space_id,
            )
            has_more = len(snapshots) > limit
            snapshots = snapshots[:limit]
            result = SpaceQuotaReconciliationResult(
                scanned=len(snapshots),
                next_space_id=snapshots[-1].space_id if has_more and snapshots else None,
            )
            for snapshot in snapshots:
                item = await self._reconcile_one(
                    tenant_id=tenant_id,
                    actual_bytes=snapshot.actual_bytes,
                    used_bytes=snapshot.used_bytes,
                    ledger_bytes=snapshot.ledger_bytes,
                    space_id=snapshot.space_id,
                    account_id=snapshot.account_id,
                    repair=repair,
                )
                result.items.append(item)
                if item.missing_account:
                    result.missing_accounts += 1
                if item.snapshot_delta_bytes not in (None, 0):
                    result.snapshot_drifts += 1
                if item.ledger_delta_bytes not in (None, 0):
                    result.ledger_drifts += 1
                if item.repaired:
                    result.repaired_accounts += 1
                if repair and item.ledger_delta_bytes not in (None, 0):
                    result.ledger_entries += 1
            if repair:
                await self._record_reconciliation_event(
                    tenant_id=tenant_id,
                    result=result,
                    audit_context=audit_context,
                )
                await self.repository.commit()
            else:
                await self.repository.rollback()
            return result
        except Exception:
            await self.repository.rollback()
            raise

    async def _reconcile_one(
        self,
        *,
        tenant_id: UUID,
        actual_bytes: int,
        used_bytes: int | None,
        ledger_bytes: int,
        space_id: UUID,
        account_id: UUID | None,
        repair: bool,
    ) -> SpaceQuotaReconciliationItem:
        missing_account = account_id is None
        original_used_bytes = used_bytes
        if missing_account and repair:
            account = await self.repository.create_account(
                tenant_id=tenant_id,
                owner_type="space",
                owner_id=space_id,
                limit_bytes=self.default_space_limit_bytes,
            )
            account_id = account.id

        snapshot_delta = None if original_used_bytes is None else actual_bytes - original_used_bytes
        ledger_delta = None if account_id is None else actual_bytes - ledger_bytes
        repaired = False
        if repair and account_id is not None:
            if missing_account or snapshot_delta not in (None, 0):
                repaired = await self.repository.set_account_used_bytes(
                    tenant_id=tenant_id,
                    account_id=account_id,
                    used_bytes=actual_bytes,
                )
                if not repaired:
                    raise ApiError("QUOTA_RECONCILE_FAILED", "容量校准失败", status_code=500)
            if ledger_delta is not None and ledger_delta != 0:
                await self.repository.add_ledger(
                    tenant_id=tenant_id,
                    account_id=account_id,
                    account_type="space",
                    delta_bytes=ledger_delta,
                    reason="quota_reconciled",
                    ref_type="space",
                    ref_id=space_id,
                )

        return SpaceQuotaReconciliationItem(
            space_id=space_id,
            account_id=account_id,
            actual_bytes=actual_bytes,
            used_bytes=original_used_bytes,
            ledger_bytes=ledger_bytes,
            snapshot_delta_bytes=snapshot_delta,
            ledger_delta_bytes=ledger_delta,
            missing_account=missing_account,
            repaired=repaired,
        )

    async def _record_reconciliation_event(
        self,
        *,
        tenant_id: UUID,
        result: SpaceQuotaReconciliationResult,
        audit_context: AuditContext | None,
    ) -> None:
        if self.audit_service is None:
            return
        await self.audit_service.record(
            event=AuditEvent(
                tenant_id=tenant_id,
                actor_id=None,
                actor_type="system",
                action="quota.reconciled",
                resource_type="quota",
                resource_id=None,
                result="allowed",
                metadata={
                    "scanned": result.scanned,
                    "missing_accounts": result.missing_accounts,
                    "snapshot_drifts": result.snapshot_drifts,
                    "ledger_drifts": result.ledger_drifts,
                    "repaired_accounts": result.repaired_accounts,
                    "ledger_entries": result.ledger_entries,
                },
            ),
            context=audit_context or AuditContext(),
        )
