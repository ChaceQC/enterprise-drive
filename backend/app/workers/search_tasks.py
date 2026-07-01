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
from app.modules.search.events import SEARCH_ACL_REBUILD_REQUESTED, SEARCH_INDEX_REQUESTED
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
            event_types=[SEARCH_INDEX_REQUESTED, SEARCH_ACL_REBUILD_REQUESTED],
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
        if event.event_type == SEARCH_INDEX_REQUESTED:
            await self._publish_index_requested(event)
            return
        if event.event_type == SEARCH_ACL_REBUILD_REQUESTED:
            await self._publish_acl_rebuild_requested(event)
            return
        if event.event_type.startswith("search."):
            raise ValueError(f"unsupported search event type: {event.event_type}")
        await self.fallback_publisher.publish(event)

    async def _publish_index_requested(self, event: OutboxEvent) -> None:
        node_id = event.payload.get("node_id")
        if not isinstance(node_id, str):
            raise ValueError("search index event missing node_id")
        await self.index_service.index_file(
            tenant_id=event.tenant_id,
            node_id=UUID(node_id),
        )

    async def _publish_acl_rebuild_requested(self, event: OutboxEvent) -> None:
        scope = event.payload.get("scope")
        resource_id = event.payload.get("resource_id")
        if not isinstance(scope, str) or not isinstance(resource_id, str):
            raise ValueError("search acl rebuild event missing scope or resource_id")
        await self.index_service.rebuild_acl_tokens(
            tenant_id=event.tenant_id,
            scope=scope,
            resource_id=UUID(resource_id),
        )
