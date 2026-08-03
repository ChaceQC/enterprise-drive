from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

from app.core.config import Settings
from app.infrastructure.storage.base import StorageAdapter
from app.modules.search.extractors import (
    TextExtractionContext,
    TextExtractionError,
    TextExtractor,
    default_text_extractors,
)
from app.modules.search.indexer import SearchIndexService
from app.modules.search.repository import SearchRepository


@dataclass(frozen=True)
class SearchExtractionResult:
    status: str
    indexed: bool
    extracted_chars: int = 0
    reason: str | None = None


class SearchExtractionService:
    def __init__(
        self,
        *,
        repository: SearchRepository,
        index_service: SearchIndexService,
        storage: StorageAdapter,
        settings: Settings,
        max_bytes: int | None = None,
        max_chars: int | None = None,
        extractors: list[TextExtractor] | None = None,
    ) -> None:
        self.repository = repository
        self.index_service = index_service
        self.storage = storage
        self.settings = settings
        self.max_bytes = (
            max_bytes if max_bytes is not None else settings.search_text_extract_max_bytes
        )
        self.max_chars = max_chars if max_chars is not None else self.max_bytes
        self.extractors = extractors if extractors is not None else default_text_extractors()

    async def extract_version(
        self,
        *,
        tenant_id: UUID,
        version_id: UUID,
    ) -> SearchExtractionResult:
        record = await self.repository.get_version_blob_node(
            tenant_id=tenant_id,
            version_id=version_id,
        )
        if record is None:
            return SearchExtractionResult(status="missing", indexed=False, reason="version_missing")

        version, blob, node = record
        mime_type = (version.mime_type or blob.mime_type or "").split(";", 1)[0].strip().lower()
        context = TextExtractionContext(mime_type=mime_type, name=node.name)
        extractor = self._select_extractor(context)
        if extractor is None:
            await self.repository.set_version_search_state(
                tenant_id=tenant_id,
                version_id=version_id,
                status="skipped",
                text=None,
                error="unsupported_mime_type",
            )
            return SearchExtractionResult(
                status="skipped",
                indexed=False,
                reason="unsupported_mime_type",
            )

        source_limit = _extractor_source_limit(extractor, fallback=self.max_bytes)
        if blob.size_bytes > source_limit:
            await self.repository.set_version_search_state(
                tenant_id=tenant_id,
                version_id=version_id,
                status="skipped",
                text=None,
                error="file_too_large",
            )
            return SearchExtractionResult(
                status="skipped",
                indexed=False,
                reason="file_too_large",
            )

        await self.repository.set_version_search_state(
            tenant_id=tenant_id,
            version_id=version_id,
            status="extracting",
            text=None,
            error=None,
        )

        try:
            content_bytes = await self.storage.read_object_bytes(
                bucket=self.settings.s3_bucket,
                storage_key=blob.storage_key,
                max_bytes=source_limit,
            )
            text = await asyncio.to_thread(extractor.extract, content_bytes, context)
            if len(text) > self.max_chars:
                await self.repository.set_version_search_state(
                    tenant_id=tenant_id,
                    version_id=version_id,
                    status="skipped",
                    text=None,
                    error="extracted_text_too_large",
                )
                return SearchExtractionResult(
                    status="skipped",
                    indexed=False,
                    reason="extracted_text_too_large",
                )
        except TextExtractionError as exc:
            await self.repository.set_version_search_state(
                tenant_id=tenant_id,
                version_id=version_id,
                status=exc.status,
                text=None,
                error=exc.reason,
            )
            return SearchExtractionResult(status=exc.status, indexed=False, reason=exc.reason)
        except Exception:
            await self.repository.set_version_search_state(
                tenant_id=tenant_id,
                version_id=version_id,
                status="failed",
                text=None,
                error="storage_read_failed",
            )
            raise

        await self.repository.set_version_search_state(
            tenant_id=tenant_id,
            version_id=version_id,
            status="extracting",
            text=text,
            error=None,
        )
        try:
            indexed = await self.index_service.index_file(tenant_id=tenant_id, node_id=node.id)
        except Exception:
            await self.repository.set_version_search_state(
                tenant_id=tenant_id,
                version_id=version_id,
                status="failed",
                text=text,
                error="index_failed",
            )
            raise
        await self.repository.set_version_search_state(
            tenant_id=tenant_id,
            version_id=version_id,
            status="indexed",
            text=text,
            error=None,
        )
        return SearchExtractionResult(
            status="indexed",
            indexed=indexed,
            extracted_chars=len(text),
        )

    def _select_extractor(self, context: TextExtractionContext) -> TextExtractor | None:
        return next(
            (extractor for extractor in self.extractors if extractor.supports(context)), None
        )


def _extractor_source_limit(extractor: TextExtractor, *, fallback: int) -> int:
    configured = getattr(extractor, "max_source_bytes", None)
    return configured if isinstance(configured, int) and configured > 0 else fallback
