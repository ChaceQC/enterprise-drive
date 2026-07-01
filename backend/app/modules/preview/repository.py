from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file.models import FileBlob, FileVersion, Node
from app.modules.preview.models import PreviewArtifact


class PreviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_version_blob_node(
        self,
        *,
        tenant_id: UUID,
        version_id: UUID,
    ) -> tuple[FileVersion, FileBlob, Node] | None:
        result = await self.session.execute(
            select(FileVersion, FileBlob, Node)
            .join(
                FileBlob,
                (FileBlob.tenant_id == FileVersion.tenant_id)
                & (FileBlob.id == FileVersion.blob_id),
            )
            .join(
                Node,
                (Node.tenant_id == FileVersion.tenant_id) & (Node.id == FileVersion.node_id),
            )
            .where(
                FileVersion.tenant_id == tenant_id,
                FileVersion.id == version_id,
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        return row[0], row[1], row[2]

    async def set_version_preview_state(
        self,
        *,
        tenant_id: UUID,
        version_id: UUID,
        status: str,
        error: str | None = None,
    ) -> None:
        result = await self.session.execute(
            select(FileVersion).where(
                FileVersion.tenant_id == tenant_id,
                FileVersion.id == version_id,
            )
        )
        version = result.scalar_one_or_none()
        if version is None:
            return
        version.preview_status = status
        version.preview_error = error
        await self.session.flush()

    async def upsert_artifact(
        self,
        *,
        tenant_id: UUID,
        node_id: UUID,
        version_id: UUID,
        artifact_type: str,
        mime_type: str,
        storage_key: str,
        size_bytes: int,
    ) -> PreviewArtifact:
        existing = await self.get_artifact(
            tenant_id=tenant_id,
            version_id=version_id,
            artifact_type=artifact_type,
        )
        if existing is not None:
            existing.node_id = node_id
            existing.mime_type = mime_type
            existing.storage_key = storage_key
            existing.size_bytes = size_bytes
            await self.session.flush()
            return existing
        artifact = PreviewArtifact(
            tenant_id=tenant_id,
            node_id=node_id,
            version_id=version_id,
            artifact_type=artifact_type,
            mime_type=mime_type,
            storage_key=storage_key,
            size_bytes=size_bytes,
        )
        self.session.add(artifact)
        await self.session.flush()
        return artifact

    async def get_artifact(
        self,
        *,
        tenant_id: UUID,
        version_id: UUID,
        artifact_type: str,
    ) -> PreviewArtifact | None:
        result = await self.session.execute(
            select(PreviewArtifact).where(
                PreviewArtifact.tenant_id == tenant_id,
                PreviewArtifact.version_id == version_id,
                PreviewArtifact.artifact_type == artifact_type,
            )
        )
        return result.scalar_one_or_none()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
