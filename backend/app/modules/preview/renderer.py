from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from uuid import UUID

from PIL import Image, UnidentifiedImageError

from app.core.config import Settings
from app.infrastructure.storage.base import StorageAdapter
from app.modules.preview.converters import (
    PdfPreviewConverter,
    PreviewRenderError,
    PreviewRenderTimeoutError,
    PreviewToolUnavailableError,
)
from app.modules.preview.repository import PreviewRepository
from app.modules.preview.storage_keys import build_preview_storage_key

_IMAGE_MIME_TYPES = {
    "image/bmp",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/webp",
}
_IMAGE_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
_PDF_MIME_TYPES = {"application/pdf"}
_PDF_EXTENSIONS = {".pdf"}


@dataclass(frozen=True)
class PreviewRenderResult:
    status: str
    artifact_id: UUID | None = None
    reason: str | None = None


class PreviewRenderService:
    def __init__(
        self,
        *,
        repository: PreviewRepository,
        storage: StorageAdapter,
        settings: Settings,
        max_source_bytes: int | None = None,
        max_side: int | None = None,
        pdf_converter: PdfPreviewConverter | None = None,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.settings = settings
        self.max_source_bytes = (
            max_source_bytes if max_source_bytes is not None else settings.preview_max_source_bytes
        )
        self.max_side = max_side if max_side is not None else settings.preview_image_max_side
        self.pdf_converter = pdf_converter

    async def render_version(
        self,
        *,
        tenant_id: UUID,
        version_id: UUID,
    ) -> PreviewRenderResult:
        record = await self.repository.get_version_blob_node(
            tenant_id=tenant_id,
            version_id=version_id,
        )
        if record is None:
            return PreviewRenderResult(status="missing", reason="version_missing")

        version, blob, node = record
        mime_type = (version.mime_type or blob.mime_type or "").split(";", 1)[0].strip().lower()
        preview_kind = _detect_preview_kind(mime_type=mime_type, name=node.name)
        if preview_kind is None:
            await self.repository.set_version_preview_state(
                tenant_id=tenant_id,
                version_id=version_id,
                status="unsupported",
                error="unsupported_mime_type",
            )
            return PreviewRenderResult(status="unsupported", reason="unsupported_mime_type")

        if preview_kind == "pdf" and self.pdf_converter is None:
            await self.repository.set_version_preview_state(
                tenant_id=tenant_id,
                version_id=version_id,
                status="unsupported",
                error="pdf_renderer_missing",
            )
            return PreviewRenderResult(status="unsupported", reason="pdf_renderer_missing")

        if blob.size_bytes > self.max_source_bytes:
            await self.repository.set_version_preview_state(
                tenant_id=tenant_id,
                version_id=version_id,
                status="unsupported",
                error="file_too_large",
            )
            return PreviewRenderResult(status="unsupported", reason="file_too_large")

        await self.repository.set_version_preview_state(
            tenant_id=tenant_id,
            version_id=version_id,
            status="processing",
            error=None,
        )

        try:
            source = await self.storage.read_object_bytes(
                bucket=self.settings.s3_bucket,
                storage_key=blob.storage_key,
                max_bytes=self.max_source_bytes,
            )
            rendered = await self._render_preview_image(
                source,
                preview_kind=preview_kind,
            )
            preview_key = build_preview_storage_key(
                tenant_id=tenant_id,
                node_id=node.id,
                version_id=version.id,
                artifact_type="image",
                extension="webp",
            )
            await self.storage.put_object_bytes(
                bucket=self.settings.s3_bucket,
                storage_key=preview_key,
                content=rendered,
                content_type="image/webp",
            )
        except UnidentifiedImageError:
            reason = (
                "image_decode_failed" if preview_kind == "image" else "pdf_preview_decode_failed"
            )
            await self.repository.set_version_preview_state(
                tenant_id=tenant_id,
                version_id=version_id,
                status="failed",
                error=reason,
            )
            return PreviewRenderResult(status="failed", reason=reason)
        except PreviewToolUnavailableError:
            await self.repository.set_version_preview_state(
                tenant_id=tenant_id,
                version_id=version_id,
                status="unsupported",
                error="pdf_renderer_missing",
            )
            return PreviewRenderResult(status="unsupported", reason="pdf_renderer_missing")
        except PreviewRenderTimeoutError:
            await self.repository.set_version_preview_state(
                tenant_id=tenant_id,
                version_id=version_id,
                status="failed",
                error="pdf_render_timeout",
            )
            raise
        except PreviewRenderError:
            await self.repository.set_version_preview_state(
                tenant_id=tenant_id,
                version_id=version_id,
                status="failed",
                error="pdf_render_failed",
            )
            raise
        except Exception:
            await self.repository.set_version_preview_state(
                tenant_id=tenant_id,
                version_id=version_id,
                status="failed",
                error="render_failed",
            )
            raise

        artifact = await self.repository.upsert_artifact(
            tenant_id=tenant_id,
            node_id=node.id,
            version_id=version.id,
            artifact_type="image",
            mime_type="image/webp",
            storage_key=preview_key,
            size_bytes=len(rendered),
        )
        await self.repository.set_version_preview_state(
            tenant_id=tenant_id,
            version_id=version_id,
            status="ready",
            error=None,
        )
        return PreviewRenderResult(status="ready", artifact_id=artifact.id)

    async def _render_preview_image(self, source: bytes, *, preview_kind: str) -> bytes:
        if preview_kind == "image":
            return _render_image_preview(source, max_side=self.max_side)
        if self.pdf_converter is None:
            raise PreviewToolUnavailableError("pdf renderer missing")
        page_image = await self.pdf_converter.render_first_page_png(source)
        return _render_image_preview(page_image, max_side=self.max_side)


def _detect_preview_kind(*, mime_type: str, name: str) -> str | None:
    if _is_supported_image(mime_type=mime_type, name=name):
        return "image"
    if _is_supported_pdf(mime_type=mime_type, name=name):
        return "pdf"
    return None


def _is_supported_image(*, mime_type: str, name: str) -> bool:
    if mime_type in _IMAGE_MIME_TYPES:
        return True
    normalized_name = name.casefold()
    return any(normalized_name.endswith(extension) for extension in _IMAGE_EXTENSIONS)


def _is_supported_pdf(*, mime_type: str, name: str) -> bool:
    if mime_type in _PDF_MIME_TYPES:
        return True
    normalized_name = name.casefold()
    return any(normalized_name.endswith(extension) for extension in _PDF_EXTENSIONS)


def _render_image_preview(source: bytes, *, max_side: int) -> bytes:
    with Image.open(BytesIO(source)) as image:
        preview = image.convert("RGBA")
        preview.thumbnail((max_side, max_side))
        output = BytesIO()
        preview.save(output, format="WEBP", quality=85, method=6)
        return output.getvalue()
