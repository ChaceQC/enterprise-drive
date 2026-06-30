from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.modules.audit.dispatcher import OutboxDispatcher
from app.modules.audit.models import OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.auth.models import Tenant


class CapturingPublisher:
    def __init__(self) -> None:
        self.event_ids: list[str] = []

    async def publish(self, event: OutboxEvent) -> None:
        self.event_ids.append(str(event.id))


class FailingPublisher:
    async def publish(self, event: OutboxEvent) -> None:
        raise RuntimeError(f"publish failed: {event.id}")


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    await engine.dispose()


async def create_tenant(session: AsyncSession) -> Tenant:
    tenant = Tenant(slug=f"tenant-{uuid4().hex[:8]}", name="测试企业")
    session.add(tenant)
    await session.flush()
    return tenant


async def create_outbox_event(session: AsyncSession, tenant: Tenant) -> OutboxEvent:
    repository = AuditRepository(session)
    return await repository.add_outbox_event(
        tenant_id=tenant.id,
        event_type="audit.auth.login",
        aggregate_type="audit_log",
        aggregate_id=uuid4(),
        payload={"audit_log_id": str(uuid4())},
    )


@pytest.mark.asyncio
async def test_dispatcher_marks_due_events_sent(session: AsyncSession) -> None:
    tenant = await create_tenant(session)
    event = await create_outbox_event(session, tenant)
    publisher = CapturingPublisher()
    dispatcher = OutboxDispatcher(
        repository=AuditRepository(session),
        publisher=publisher,
        max_retries=3,
    )

    result = await dispatcher.dispatch_pending(batch_size=10)

    assert result.to_dict() == {"claimed": 1, "sent": 1, "failed": 0, "dead": 0}
    assert publisher.event_ids == [str(event.id)]
    stored_event = await session.get(OutboxEvent, event.id)
    assert stored_event is not None
    assert stored_event.status == "sent"


@pytest.mark.asyncio
async def test_dispatcher_marks_failed_events_for_retry(session: AsyncSession) -> None:
    tenant = await create_tenant(session)
    event = await create_outbox_event(session, tenant)
    dispatcher = OutboxDispatcher(
        repository=AuditRepository(session),
        publisher=FailingPublisher(),
        max_retries=3,
    )

    result = await dispatcher.dispatch_pending(batch_size=10)

    assert result.to_dict() == {"claimed": 1, "sent": 0, "failed": 1, "dead": 0}
    stored_event = await session.get(OutboxEvent, event.id)
    assert stored_event is not None
    assert stored_event.status == "failed"
    assert stored_event.retry_count == 1
    assert stored_event.next_retry_at > event.created_at


@pytest.mark.asyncio
async def test_dispatcher_marks_event_dead_after_max_retries(session: AsyncSession) -> None:
    tenant = await create_tenant(session)
    event = await create_outbox_event(session, tenant)
    event.retry_count = 2
    dispatcher = OutboxDispatcher(
        repository=AuditRepository(session),
        publisher=FailingPublisher(),
        max_retries=3,
    )

    result = await dispatcher.dispatch_pending(batch_size=10)

    assert result.to_dict() == {"claimed": 1, "sent": 0, "failed": 0, "dead": 1}
    stored_event = await session.get(OutboxEvent, event.id)
    assert stored_event is not None
    assert stored_event.status == "dead"
    assert stored_event.retry_count == 3


@pytest.mark.asyncio
async def test_dispatcher_skips_future_retry_events(session: AsyncSession) -> None:
    tenant = await create_tenant(session)
    event = await create_outbox_event(session, tenant)
    event.status = "failed"
    event.next_retry_at = event.next_retry_at.replace(year=event.next_retry_at.year + 1)
    dispatcher = OutboxDispatcher(
        repository=AuditRepository(session),
        publisher=CapturingPublisher(),
        max_retries=3,
    )

    result = await dispatcher.dispatch_pending(batch_size=10)
    stored_events = (await session.execute(select(OutboxEvent))).scalars().all()

    assert result.to_dict() == {"claimed": 0, "sent": 0, "failed": 0, "dead": 0}
    assert len(stored_events) == 1
    assert stored_events[0].status == "failed"
