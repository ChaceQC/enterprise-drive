from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from app.core.security import utc_now
from app.modules.audit.models import OutboxEvent
from app.modules.audit.repository import AuditRepository

logger = logging.getLogger("enterprise_drive.outbox")


class OutboxPublisher(Protocol):
    async def publish(self, event: OutboxEvent) -> None: ...


class LoggingOutboxPublisher:
    async def publish(self, event: OutboxEvent) -> None:
        logger.info(
            "outbox event dispatched",
            extra={
                "event_id": str(event.id),
                "event_type": event.event_type,
                "tenant_id": str(event.tenant_id),
            },
        )


@dataclass(frozen=True)
class OutboxDispatchResult:
    claimed: int
    sent: int
    failed: int
    dead: int

    def to_dict(self) -> dict[str, int]:
        return {
            "claimed": self.claimed,
            "sent": self.sent,
            "failed": self.failed,
            "dead": self.dead,
        }


class OutboxDispatcher:
    def __init__(
        self,
        *,
        repository: AuditRepository,
        publisher: OutboxPublisher,
        max_retries: int,
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.max_retries = max_retries

    async def dispatch_pending(self, *, batch_size: int) -> OutboxDispatchResult:
        events = await self.repository.claim_due_outbox_events(limit=batch_size)
        sent = 0
        failed = 0
        dead = 0

        for event in events:
            try:
                await self.publisher.publish(event)
            except Exception:
                next_retry_at = self._next_retry_at(event)
                await self.repository.mark_outbox_failed(
                    event=event,
                    next_retry_at=next_retry_at,
                    max_retries=self.max_retries,
                )
                if event.status == "dead":
                    dead += 1
                else:
                    failed += 1
            else:
                await self.repository.mark_outbox_sent(event=event)
                sent += 1

        return OutboxDispatchResult(
            claimed=len(events),
            sent=sent,
            failed=failed,
            dead=dead,
        )

    @staticmethod
    def _next_retry_at(event: OutboxEvent) -> datetime:
        delay_seconds = min(2 ** max(event.retry_count, 0), 300)
        return utc_now() + timedelta(seconds=delay_seconds)
