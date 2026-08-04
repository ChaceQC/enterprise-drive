from __future__ import annotations

from datetime import datetime
from typing import TypedDict
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PageCursor
from app.core.security import utc_now
from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.audit.schemas import AuditContext, AuditEvent


class OutboxGovernanceStats(TypedDict):
    pending: int
    processing: int
    failed: int
    dead: int
    sent: int
    last_sent_at: datetime | None
    last_failed_at: datetime | None
    oldest_pending_at: datetime | None


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_audit_log(
        self,
        *,
        event: AuditEvent,
        context: AuditContext,
        flush: bool = True,
    ) -> AuditLog:
        audit_log = AuditLog(
            id=uuid4(),
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
        if flush:
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
        flush: bool = True,
    ) -> OutboxEvent:
        outbox_event = OutboxEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
        )
        self.session.add(outbox_event)
        if flush:
            await self.session.flush()
        return outbox_event

    async def list_audit_logs(
        self,
        *,
        tenant_id: UUID,
        actor_id: UUID | None,
        actor_type: str | None,
        action: str | None,
        resource_type: str | None,
        resource_id: UUID | None,
        result: str | None,
        risk_level: str | None,
        request_id: str | None,
        created_from: datetime | None,
        created_to: datetime | None,
        cursor: PageCursor | None,
        limit: int,
    ) -> list[AuditLog]:
        conditions = [AuditLog.tenant_id == tenant_id]
        if actor_id is not None:
            conditions.append(AuditLog.actor_id == actor_id)
        if actor_type is not None:
            conditions.append(AuditLog.actor_type == actor_type)
        if action is not None:
            conditions.append(AuditLog.action == action)
        if resource_type is not None:
            conditions.append(AuditLog.resource_type == resource_type)
        if resource_id is not None:
            conditions.append(AuditLog.resource_id == resource_id)
        if result is not None:
            conditions.append(AuditLog.result == result)
        if risk_level is not None:
            conditions.append(AuditLog.risk_level == risk_level)
        if request_id is not None:
            conditions.append(AuditLog.request_id == request_id)
        if created_from is not None:
            conditions.append(AuditLog.created_at >= created_from)
        if created_to is not None:
            conditions.append(AuditLog.created_at <= created_to)
        if cursor is not None:
            conditions.append(
                or_(
                    AuditLog.created_at < cursor.created_at,
                    and_(
                        AuditLog.created_at == cursor.created_at,
                        AuditLog.id < cursor.item_id,
                    ),
                )
            )

        query_result = await self.session.execute(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
        )
        return list(query_result.scalars().all())

    async def get_audit_log(
        self,
        *,
        audit_log_id: UUID,
        tenant_id: UUID | None = None,
    ) -> AuditLog | None:
        conditions = [AuditLog.id == audit_log_id]
        if tenant_id is not None:
            conditions.append(AuditLog.tenant_id == tenant_id)
        result = await self.session.execute(
            select(AuditLog).where(*conditions).order_by(AuditLog.created_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

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
        event.dead_at = None
        event.updated_at = now
        await self.session.flush()

    async def mark_outbox_failed(
        self,
        *,
        event: OutboxEvent,
        next_retry_at: datetime,
        max_retries: int,
        error_kind: str,
        error_code: str,
        permanent: bool = False,
        failed_at: datetime | None = None,
    ) -> None:
        now = failed_at or utc_now()
        event.retry_count += 1
        is_dead = permanent or event.retry_count >= max_retries
        event.status = "dead" if is_dead else "failed"
        event.next_retry_at = next_retry_at
        event.last_error_kind = error_kind
        event.last_error_code = error_code
        event.last_failed_at = now
        event.dead_at = now if is_dead else None
        event.updated_at = now
        await self.session.flush()

    async def list_dead_letters(
        self,
        *,
        tenant_id: UUID,
        event_type: str | None,
        error_kind: str | None,
        cursor: PageCursor | None,
        limit: int,
    ) -> list[OutboxEvent]:
        conditions = [
            OutboxEvent.tenant_id == tenant_id,
            OutboxEvent.status == "dead",
        ]
        if event_type is not None:
            conditions.append(OutboxEvent.event_type == event_type)
        if error_kind is not None:
            conditions.append(OutboxEvent.last_error_kind == error_kind)
        if cursor is not None:
            conditions.append(
                or_(
                    OutboxEvent.created_at < cursor.created_at,
                    and_(
                        OutboxEvent.created_at == cursor.created_at,
                        OutboxEvent.id < cursor.item_id,
                    ),
                )
            )
        result = await self.session.execute(
            select(OutboxEvent)
            .where(*conditions)
            .order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_dead_letter(
        self,
        *,
        tenant_id: UUID,
        event_id: UUID,
        for_update: bool = False,
    ) -> OutboxEvent | None:
        statement = select(OutboxEvent).where(
            OutboxEvent.tenant_id == tenant_id,
            OutboxEvent.id == event_id,
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def replay_dead_letter(
        self,
        *,
        event: OutboxEvent,
        replayed_by: UUID,
        replayed_at: datetime | None = None,
    ) -> bool:
        if event.status != "dead":
            return False
        now = replayed_at or utc_now()
        event.status = "pending"
        event.retry_count = 0
        event.next_retry_at = now
        event.dead_at = None
        event.last_error_kind = None
        event.last_error_code = None
        event.last_failed_at = None
        event.replay_count += 1
        event.last_replayed_at = now
        event.last_replayed_by = replayed_by
        event.updated_at = now
        await self.session.flush()
        return True

    async def outbox_governance_stats(
        self,
        *,
        tenant_id: UUID,
    ) -> OutboxGovernanceStats:
        counts_result = await self.session.execute(
            select(OutboxEvent.status, func.count())
            .where(OutboxEvent.tenant_id == tenant_id)
            .group_by(OutboxEvent.status)
        )
        counts = {str(status): int(count) for status, count in counts_result.all()}
        timestamps_result = await self.session.execute(
            select(
                func.max(OutboxEvent.updated_at).filter(OutboxEvent.status == "sent"),
                func.max(OutboxEvent.last_failed_at),
                func.min(OutboxEvent.created_at).filter(
                    OutboxEvent.status.in_(["pending", "failed", "processing"])
                ),
            ).where(OutboxEvent.tenant_id == tenant_id)
        )
        last_sent_at, last_failed_at, oldest_pending_at = timestamps_result.one()
        return {
            "pending": counts.get("pending", 0),
            "processing": counts.get("processing", 0),
            "failed": counts.get("failed", 0),
            "dead": counts.get("dead", 0),
            "sent": counts.get("sent", 0),
            "last_sent_at": last_sent_at,
            "last_failed_at": last_failed_at,
            "oldest_pending_at": oldest_pending_at,
        }

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

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
