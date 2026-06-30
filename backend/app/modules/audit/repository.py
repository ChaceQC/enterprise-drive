from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utc_now
from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.audit.schemas import AuditContext, AuditEvent


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_audit_log(self, *, event: AuditEvent, context: AuditContext) -> AuditLog:
        audit_log = AuditLog(
            tenant_id=event.tenant_id,
            actor_id=event.actor_id,
            actor_type=event.actor_type,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            result=event.result,
            risk_level=event.risk_level,
            request_id=context.request_id,
            ip=context.ip,
            user_agent=context.user_agent,
            metadata_json=event.metadata,
        )
        self.session.add(audit_log)
        await self.session.flush()
        return audit_log

    async def add_outbox_event(
        self,
        *,
        tenant_id: UUID,
        event_type: str,
        aggregate_type: str,
        aggregate_id: UUID,
        payload: dict[str, object],
    ) -> OutboxEvent:
        outbox_event = OutboxEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
        )
        self.session.add(outbox_event)
        await self.session.flush()
        return outbox_event

    async def claim_due_outbox_events(
        self,
        *,
        limit: int,
        now: datetime | None = None,
        event_types: list[str] | None = None,
        event_type_prefixes: list[str] | None = None,
    ) -> list[OutboxEvent]:
        claimed_at = now or utc_now()
        conditions = [
            OutboxEvent.status.in_(["pending", "failed"]),
            OutboxEvent.next_retry_at <= claimed_at,
        ]
        event_type_conditions = []
        if event_types:
            event_type_conditions.append(OutboxEvent.event_type.in_(event_types))
        if event_type_prefixes:
            event_type_conditions.extend(
                OutboxEvent.event_type.like(f"{prefix}%") for prefix in event_type_prefixes
            )
        if event_type_conditions:
            conditions.append(or_(*event_type_conditions))

        result = await self.session.execute(
            select(OutboxEvent)
            .where(*conditions)
            .order_by(OutboxEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        events = list(result.scalars().all())
        for event in events:
            event.status = "processing"
            event.updated_at = claimed_at
        await self.session.flush()
        return events

    async def mark_outbox_sent(
        self,
        *,
        event: OutboxEvent,
        sent_at: datetime | None = None,
    ) -> None:
        now = sent_at or utc_now()
        event.status = "sent"
        event.updated_at = now
        await self.session.flush()

    async def mark_outbox_failed(
        self,
        *,
        event: OutboxEvent,
        next_retry_at: datetime,
        max_retries: int,
        failed_at: datetime | None = None,
    ) -> None:
        now = failed_at or utc_now()
        event.retry_count += 1
        event.status = "dead" if event.retry_count >= max_retries else "failed"
        event.next_retry_at = next_retry_at
        event.updated_at = now
        await self.session.flush()

    async def reset_stale_processing(
        self,
        *,
        before: datetime,
    ) -> int:
        result = await self.session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.status == "processing", OutboxEvent.updated_at < before)
            .values(status="failed", next_retry_at=utc_now(), updated_at=utc_now())
        )
        rowcount = getattr(result, "rowcount", 0)
        return int(rowcount or 0)
