from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.infrastructure.queue.celery_app import celery_app
from app.modules.audit.dispatcher import OutboxDispatcher
from app.modules.audit.models import OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.permission.cache import (
    PERMISSION_CHANGED_EVENT,
    PermissionCacheInvalidator,
    RedisPermissionCacheInvalidator,
)


class PermissionCacheInvalidationPublisher:
    def __init__(self, *, invalidator: PermissionCacheInvalidator) -> None:
        self.invalidator = invalidator

    async def publish(self, event: OutboxEvent) -> None:
        await self.invalidator.invalidate_permission_changed(event=event)


def invalidate_permission_cache(batch_size: int | None = None) -> dict[str, int]:
    return asyncio.run(_invalidate_permission_cache(batch_size=batch_size))


celery_app.task(name="permission.invalidate_cache")(invalidate_permission_cache)


async def _invalidate_permission_cache(
    batch_size: int | None = None,
    invalidator: PermissionCacheInvalidator | None = None,
) -> dict[str, int]:
    settings = get_settings()
    session_factory = get_session_factory()
    owned_invalidator = invalidator is None
    cache_invalidator = invalidator or RedisPermissionCacheInvalidator(redis_url=settings.redis_url)
    try:
        async with session_factory() as session:
            dispatcher = OutboxDispatcher(
                repository=AuditRepository(session),
                publisher=PermissionCacheInvalidationPublisher(invalidator=cache_invalidator),
                max_retries=settings.outbox_max_retries,
            )
            result = await dispatcher.dispatch_pending(
                batch_size=batch_size or settings.outbox_batch_size,
                event_types=[PERMISSION_CHANGED_EVENT],
            )
            await session.commit()
            return result.to_dict()
    finally:
        close = getattr(cache_invalidator, "close", None)
        if owned_invalidator and close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result
