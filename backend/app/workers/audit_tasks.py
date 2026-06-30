from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.infrastructure.queue.celery_app import celery_app
from app.modules.audit.dispatcher import LoggingOutboxPublisher, OutboxDispatcher
from app.modules.audit.repository import AuditRepository


def dispatch_outbox(batch_size: int | None = None) -> dict[str, int]:
    return asyncio.run(_dispatch_outbox(batch_size=batch_size))


celery_app.task(name="audit.dispatch_outbox")(dispatch_outbox)


async def _dispatch_outbox(batch_size: int | None = None) -> dict[str, int]:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        dispatcher = OutboxDispatcher(
            repository=AuditRepository(session),
            publisher=LoggingOutboxPublisher(),
            max_retries=settings.outbox_max_retries,
        )
        result = await dispatcher.dispatch_pending(
            batch_size=batch_size or settings.outbox_batch_size
        )
        await session.commit()
        return result.to_dict()
