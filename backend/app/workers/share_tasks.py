from __future__ import annotations

import asyncio
from uuid import UUID

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.infrastructure.queue.celery_app import celery_app
from app.modules.audit.dispatcher import OutboxDispatcher
from app.modules.audit.models import OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditContext
from app.modules.audit.service import AuditService
from app.modules.auth.repository import AuthRepository
from app.modules.org.repository import OrgRepository
from app.modules.org.service import OrgService
from app.modules.share.constants import (
    SHARE_RECIPIENT_DEPARTMENT,
    SHARE_RECIPIENT_GROUP,
)
from app.modules.share.events import SHARE_RECIPIENTS_REBUILD_REQUESTED
from app.modules.share.lifecycle import ShareLifecycleService
from app.modules.share.recipient_grants import ShareRecipientGrantService
from app.modules.share.repository import ShareRepository


def dispatch_share_outbox(batch_size: int | None = None) -> dict[str, int]:
    return asyncio.run(_dispatch_share_outbox(batch_size=batch_size))


celery_app.task(name="share.dispatch_outbox")(dispatch_share_outbox)


def expire_shares(
    tenant_id: str | None = None,
    limit: int = 100,
    request_id: str | None = None,
) -> dict[str, int]:
    return asyncio.run(
        _expire_shares(
            tenant_id=UUID(tenant_id) if tenant_id else None,
            limit=limit,
            request_id=request_id,
        )
    )


celery_app.task(name="share.expire_shares")(expire_shares)


async def _dispatch_share_outbox(batch_size: int | None = None) -> dict[str, int]:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        repository = ShareRepository(session)
        publisher = ShareRecipientRebuildPublisher(
            recipient_grant_service=ShareRecipientGrantService(
                repository=repository,
                auth_repository=AuthRepository(session),
                org_service=OrgService(repository=OrgRepository(session)),
            )
        )
        dispatcher = OutboxDispatcher(
            repository=AuditRepository(session),
            publisher=publisher,
            max_retries=settings.outbox_max_retries,
        )
        result = await dispatcher.dispatch_pending(
            batch_size=batch_size or settings.outbox_batch_size,
            event_types=[SHARE_RECIPIENTS_REBUILD_REQUESTED],
        )
        await session.commit()
        return result.to_dict()


async def _expire_shares(
    *,
    tenant_id: UUID | None,
    limit: int,
    request_id: str | None,
) -> dict[str, int]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        auth_repository = AuthRepository(session)
        tenant_ids = [tenant_id] if tenant_id else await auth_repository.list_tenant_ids()
        total = {"scanned": 0, "expired": 0, "grants_deactivated": 0}
        for current_tenant_id in tenant_ids:
            repository = ShareRepository(session)
            result = await ShareLifecycleService(
                repository=repository,
                recipient_grant_service=ShareRecipientGrantService(
                    repository=repository,
                    auth_repository=auth_repository,
                    org_service=OrgService(repository=OrgRepository(session)),
                ),
                audit_service=AuditService(repository=AuditRepository(session)),
            ).expire_shares(
                tenant_id=current_tenant_id,
                limit=limit,
                audit_context=AuditContext(request_id=request_id),
            )
            payload = result.to_dict()
            for key in total:
                total[key] += payload[key]
        return total


class ShareRecipientRebuildPublisher:
    def __init__(self, *, recipient_grant_service: ShareRecipientGrantService) -> None:
        self.recipient_grant_service = recipient_grant_service

    async def publish(self, event: OutboxEvent) -> None:
        department_id = _optional_uuid(event.payload.get("department_id"))
        if department_id is not None:
            await self.recipient_grant_service.reconcile_subject(
                tenant_id=event.tenant_id,
                subject_type=SHARE_RECIPIENT_DEPARTMENT,
                subject_id=department_id,
            )
            return
        group_id = _optional_uuid(event.payload.get("group_id"))
        if group_id is not None:
            await self.recipient_grant_service.reconcile_subject(
                tenant_id=event.tenant_id,
                subject_type=SHARE_RECIPIENT_GROUP,
                subject_id=group_id,
            )
            return
        affected_user_id = _optional_uuid(event.payload.get("affected_user_id"))
        if affected_user_id is not None:
            await self.recipient_grant_service.reconcile_user(
                tenant_id=event.tenant_id,
                user_id=affected_user_id,
            )


def _optional_uuid(value: object) -> UUID | None:
    if not isinstance(value, str) or not value:
        return None
    return UUID(value)
