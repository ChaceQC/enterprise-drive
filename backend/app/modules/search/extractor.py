from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.core.config import Settings
from app.infrastructure.storage.base import StorageAdapter
from app.modules.search.indexer import SearchIndexService
from app.modules.search.repository import SearchRepository

_TEXT_MIME_TYPES = {
    "application/csv",
    "application/json",
    "application/ld+json",
    "application/xml",
    "application/yaml",
    "text/csv",
    "text/markdown",
    "text/plain",
    "text/tab-separated-values",
    "text/xml",
}
_TEXT_EXTENSIONS = {
    ".csv",
    ".json",
    ".log",
    ".md",
    ".markdown",
    ".txt",
    ".tsv",
    ".xml",
    ".yaml",
    ".yml",
}


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
    ) -> None:
        self.repository = repository
        self.index_service = index_service
        self.storage = storage
        self.settings = settings
        self.max_bytes = (
            max_bytes if max_bytes is not None else settings.search_text_extract_max_bytes
        )

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
        if not _is_supported_text(mime_type=mime_type, name=node.name):
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

        if blob.size_bytes > self.max_bytes:
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
                max_bytes=self.max_bytes,
            )
            text = _decode_text(content_bytes)
        except UnicodeDecodeError:
            await self.repository.set_version_search_state(
                tenant_id=tenant_id,
                version_id=version_id,
                status="failed",
                text=None,
                error="decode_failed",
            )
            return SearchExtractionResult(status="failed", indexed=False, reason="decode_failed")
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


def _is_supported_text(*, mime_type: str, name: str) -> bool:
    if mime_type.startswith("text/") or mime_type in _TEXT_MIME_TYPES:
        return True
    normalized_name = name.casefold()
    return any(normalized_name.endswith(extension) for extension in _TEXT_EXTENSIONS)


def _decode_text(content: bytes) -> str:
    text = content.decode("utf-8-sig")
    return text.replace("\x00", "")
