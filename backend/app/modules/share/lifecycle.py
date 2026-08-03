from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.share.recipient_grants import ShareRecipientGrantService
from app.modules.share.repository import ShareRepository


@dataclass(frozen=True)
class ShareExpiryResult:
    scanned: int = 0
    expired: int = 0
    grants_deactivated: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "expired": self.expired,
            "grants_deactivated": self.grants_deactivated,
        }


class ShareLifecycleService:
    def __init__(
        self,
        *,
        repository: ShareRepository,
        recipient_grant_service: ShareRecipientGrantService,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.recipient_grant_service = recipient_grant_service
        self.audit_service = audit_service

    async def expire_shares(
        self,
        *,
        tenant_id: UUID,
        limit: int,
        audit_context: AuditContext | None = None,
    ) -> ShareExpiryResult:
        shares = await self.repository.list_expired_active_shares(
            tenant_id=tenant_id,
            limit=limit,
        )
        grants_deactivated = 0
        for share in shares:
            share.status = "expired"
            reconciliation = await self.recipient_grant_service.reconcile_share(
                tenant_id=tenant_id,
                share_id=share.id,
            )
            grants_deactivated += reconciliation.deactivated
            if self.audit_service is not None:
                await self.audit_service.record(
                    event=AuditEvent(
                        tenant_id=tenant_id,
                        actor_id=None,
                        actor_type="system",
                        action="share.expired",
                        resource_type="share",
                        resource_id=share.id,
                        result="allowed",
                        metadata={
                            "share_type": share.share_type,
                            "grants_deactivated": reconciliation.deactivated,
                        },
                    ),
                    context=audit_context or AuditContext(),
                )
        await self.repository.commit()
        return ShareExpiryResult(
            scanned=len(shares),
            expired=len(shares),
            grants_deactivated=grants_deactivated,
        )
