from __future__ import annotations

import asyncio
from uuid import UUID

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.infrastructure.queue.celery_app import celery_app
from app.infrastructure.search.opensearch import OpenSearchIndexAdapter
from app.modules.audit.dispatcher import LoggingOutboxPublisher, OutboxDispatcher, OutboxPublisher
from app.modules.audit.models import OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.search.events import SEARCH_INDEX_REQUESTED
from app.modules.search.indexer import SearchIndexService
from app.modules.search.repository import SearchRepository


def dispatch_search_outbox(batch_size: int | None = None) -> dict[str, int]:
    return asyncio.run(_dispatch_search_outbox(batch_size=batch_size))


celery_app.task(name="search.dispatch_outbox")(dispatch_search_outbox)


async def _dispatch_search_outbox(batch_size: int | None = None) -> dict[str, int]:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        publisher = SearchOutboxPublisher(
            index_service=SearchIndexService(
                repository=SearchRepository(session),
                index_adapter=OpenSearchIndexAdapter(settings=settings),
            ),
            fallback_publisher=LoggingOutboxPublisher(),
        )
        dispatcher = OutboxDispatcher(
            repository=AuditRepository(session),
            publisher=publisher,
            max_retries=settings.outbox_max_retries,
        )
        result = await dispatcher.dispatch_pending(
            batch_size=batch_size or settings.outbox_batch_size,
            event_types=[SEARCH_INDEX_REQUESTED],
        )
        await session.commit()
        return result.to_dict()


class SearchOutboxPublisher:
    def __init__(
        self,
        *,
        index_service: SearchIndexService,
        fallback_publisher: OutboxPublisher,
    ) -> None:
        self.index_service = index_service
        self.fallback_publisher = fallback_publisher

    async def publish(self, event: OutboxEvent) -> None:
        if event.event_type != SEARCH_INDEX_REQUESTED:
            await self.fallback_publisher.publish(event)
            return
        node_id = event.payload.get("node_id")
        if not isinstance(node_id, str):
            raise ValueError("search index event missing node_id")
        await self.index_service.index_file(
            tenant_id=event.tenant_id,
            node_id=UUID(node_id),
        )
