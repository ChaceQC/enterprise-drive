from __future__ import annotations

import asyncio
from uuid import UUID

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.infrastructure.queue.celery_app import celery_app
from app.infrastructure.search.content_extraction import (
    LibreOfficeSearchConverter,
    TesseractOcrEngine,
)
from app.infrastructure.search.opensearch import OpenSearchIndexAdapter
from app.infrastructure.storage.s3 import S3StorageAdapter
from app.modules.audit.dispatcher import LoggingOutboxPublisher, OutboxDispatcher, OutboxPublisher
from app.modules.audit.models import OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.governance.repository import GovernanceRepository
from app.modules.search.events import (
    SEARCH_ACL_REBUILD_REQUESTED,
    SEARCH_EXTRACT_REQUESTED,
    SEARCH_INDEX_REQUESTED,
)
from app.modules.search.extractor import SearchExtractionService
from app.modules.search.extractors import default_text_extractors
from app.modules.search.indexer import SearchIndexService
from app.modules.search.repository import SearchRepository


def dispatch_search_outbox(batch_size: int | None = None) -> dict[str, int]:
    return asyncio.run(_dispatch_search_outbox(batch_size=batch_size))


celery_app.task(name="search.dispatch_outbox")(dispatch_search_outbox)


async def _dispatch_search_outbox(batch_size: int | None = None) -> dict[str, int]:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        search_repository = SearchRepository(session)
        index_adapter = OpenSearchIndexAdapter(settings=settings)
        index_service = SearchIndexService(
            repository=search_repository,
            index_adapter=index_adapter,
        )
        ocr_engine = (
            TesseractOcrEngine(
                command=settings.search_ocr_command,
                pdf_command=settings.preview_pdf_command,
                languages=settings.search_ocr_languages,
                page_segmentation_mode=settings.search_ocr_page_segmentation_mode,
                max_pages=settings.search_ocr_max_pages,
                pdf_dpi=settings.search_ocr_pdf_dpi,
                max_pixels=settings.search_ocr_max_pixels,
                max_rendered_bytes=settings.search_ocr_max_rendered_bytes,
                timeout_seconds=settings.search_ocr_command_timeout_seconds,
                max_output_chars=settings.search_extract_max_chars,
            )
            if settings.search_ocr_enabled
            else None
        )
        publisher = SearchOutboxPublisher(
            index_service=index_service,
            governance_repository=GovernanceRepository(session),
            extraction_service=SearchExtractionService(
                repository=search_repository,
                index_service=index_service,
                storage=S3StorageAdapter(settings=settings),
                settings=settings,
                max_chars=settings.search_extract_max_chars,
                extractors=default_text_extractors(
                    ocr_engine=ocr_engine,
                    office_converter=LibreOfficeSearchConverter(
                        command=settings.preview_office_command,
                        timeout_seconds=settings.search_ocr_command_timeout_seconds,
                        max_pdf_bytes=settings.preview_office_max_pdf_bytes,
                    ),
                    complex_source_max_bytes=settings.search_complex_extract_max_bytes,
                    pdf_max_pages=settings.search_ocr_max_pages,
                ),
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
            event_types=[
                SEARCH_INDEX_REQUESTED,
                SEARCH_ACL_REBUILD_REQUESTED,
                SEARCH_EXTRACT_REQUESTED,
            ],
        )
        await session.commit()
        return result.to_dict()


class SearchOutboxPublisher:
    def __init__(
        self,
        *,
        index_service: SearchIndexService,
        extraction_service: SearchExtractionService | None = None,
        governance_repository: GovernanceRepository | None = None,
        fallback_publisher: OutboxPublisher,
    ) -> None:
        self.index_service = index_service
        self.extraction_service = extraction_service
        self.governance_repository = governance_repository
        self.fallback_publisher = fallback_publisher

    async def publish(self, event: OutboxEvent) -> None:
        if event.event_type == SEARCH_INDEX_REQUESTED:
            await self._publish_index_requested(event)
            return
        if event.event_type == SEARCH_ACL_REBUILD_REQUESTED:
            await self._publish_acl_rebuild_requested(event)
            return
        if event.event_type == SEARCH_EXTRACT_REQUESTED:
            await self._publish_extract_requested(event)
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
        if self.governance_repository is not None:
            parsed_resource_id = UUID(resource_id)
            permission_version = event.payload.get("permission_version")
            if not isinstance(permission_version, int):
                raise ValueError("search acl rebuild event missing permission_version")
            requested_by = _optional_uuid(event.payload.get("actor_id"))
            if scope == "space":
                space_id = parsed_resource_id
                root_node_id = None
            elif scope == "node":
                node = await self.governance_repository.get_node(
                    tenant_id=event.tenant_id,
                    node_id=parsed_resource_id,
                )
                if node is None:
                    return
                space_id = node.space_id
                root_node_id = node.id
            else:
                raise ValueError(f"unsupported search acl rebuild scope: {scope}")
            await self.governance_repository.create_or_refresh_permission_rebuild(
                tenant_id=event.tenant_id,
                space_id=space_id,
                root_node_id=root_node_id,
                scope=scope,
                permission_version=permission_version,
                requested_by=requested_by,
                request_id=_optional_string(event.payload.get("request_id")),
            )
            return
        await self.index_service.rebuild_acl_tokens(
            tenant_id=event.tenant_id,
            scope=scope,
            resource_id=UUID(resource_id),
        )

    async def _publish_extract_requested(self, event: OutboxEvent) -> None:
        if self.extraction_service is None:
            raise ValueError("search extraction service is not configured")
        version_id = event.payload.get("version_id")
        if not isinstance(version_id, str):
            raise ValueError("search extract event missing version_id")
        await self.extraction_service.extract_version(
            tenant_id=event.tenant_id,
            version_id=UUID(version_id),
        )


def _optional_uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
