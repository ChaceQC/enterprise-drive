from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from uuid import UUID

from PIL import Image, UnidentifiedImageError

from app.core.config import Settings
from app.infrastructure.storage.base import StorageAdapter
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
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.settings = settings
        self.max_source_bytes = (
            max_source_bytes if max_source_bytes is not None else settings.preview_max_source_bytes
        )
        self.max_side = max_side if max_side is not None else settings.preview_image_max_side

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
        if not _is_supported_image(mime_type=mime_type, name=node.name):
            await self.repository.set_version_preview_state(
                tenant_id=tenant_id,
                version_id=version_id,
                status="unsupported",
                error="unsupported_mime_type",
            )
            return PreviewRenderResult(status="unsupported", reason="unsupported_mime_type")

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
            rendered = _render_image_preview(source, max_side=self.max_side)
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
            await self.repository.set_version_preview_state(
                tenant_id=tenant_id,
                version_id=version_id,
                status="failed",
                error="image_decode_failed",
            )
            return PreviewRenderResult(status="failed", reason="image_decode_failed")
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


def _is_supported_image(*, mime_type: str, name: str) -> bool:
    if mime_type in _IMAGE_MIME_TYPES:
        return True
    normalized_name = name.casefold()
    return any(normalized_name.endswith(extension) for extension in _IMAGE_EXTENSIONS)


def _render_image_preview(source: bytes, *, max_side: int) -> bytes:
    with Image.open(BytesIO(source)) as image:
        preview = image.convert("RGBA")
        preview.thumbnail((max_side, max_side))
        output = BytesIO()
        preview.save(output, format="WEBP", quality=85, method=6)
        return output.getvalue()
