from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol

from app.core.security import utc_now
from app.modules.audit.models import OutboxEvent
from app.modules.audit.repository import AuditRepository

logger = logging.getLogger("enterprise_drive.outbox")


class OutboxPublisher(Protocol):
    async def publish(self, event: OutboxEvent) -> None: ...


class OutboxPublishError(Exception):
    def __init__(
        self,
        *,
        kind: Literal["transient", "permanent"],
        code: str,
    ) -> None:
        super().__init__(code)
        self.kind = kind
        self.code = code


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
        retry_max_delay_seconds: int = 300,
        retry_jitter_ratio: float = 0.2,
        processing_timeout_seconds: int = 300,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.max_retries = max_retries
        self.retry_max_delay_seconds = retry_max_delay_seconds
        self.retry_jitter_ratio = retry_jitter_ratio
        self.processing_timeout_seconds = processing_timeout_seconds
        self.random_value = random_value

    async def dispatch_pending(
        self,
        *,
        batch_size: int,
        event_types: list[str] | None = None,
        event_type_prefixes: list[str] | None = None,
    ) -> OutboxDispatchResult:
        await self.repository.reset_stale_processing(
            before=utc_now() - timedelta(seconds=self.processing_timeout_seconds)
        )
        events = await self.repository.claim_due_outbox_events(
            limit=batch_size,
            event_types=event_types,
            event_type_prefixes=event_type_prefixes,
        )
        sent = 0
        failed = 0
        dead = 0

        for event in events:
            try:
                await self.publisher.publish(event)
            except Exception as exc:
                failure = self._classify_failure(exc)
                next_retry_at = self._next_retry_at(event)
                await self.repository.mark_outbox_failed(
                    event=event,
                    next_retry_at=next_retry_at,
                    max_retries=self.max_retries,
                    error_kind=failure.kind,
                    error_code=failure.code,
                    permanent=failure.kind == "permanent",
                )
                logger.warning(
                    "outbox event delivery failed",
                    extra={
                        "event_id": str(event.id),
                        "event_type": event.event_type,
                        "failure_kind": failure.kind,
                        "failure_code": failure.code,
                        "status": event.status,
                    },
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

    def _next_retry_at(self, event: OutboxEvent) -> datetime:
        base_delay = min(
            2 ** max(event.retry_count, 0),
            self.retry_max_delay_seconds,
        )
        jitter_window = base_delay * self.retry_jitter_ratio
        jitter = ((self.random_value() * 2) - 1) * jitter_window
        delay_seconds = max(base_delay + jitter, 0)
        return utc_now() + timedelta(seconds=delay_seconds)

    @staticmethod
    def _classify_failure(exc: Exception) -> OutboxPublishError:
        if isinstance(exc, OutboxPublishError):
            return exc
        if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
            return OutboxPublishError(
                kind="transient",
                code="dependency_unavailable",
            )
        return OutboxPublishError(
            kind="transient",
            code="unexpected_error",
        )
