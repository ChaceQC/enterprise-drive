from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file.models import FileBlob, FileVersion, Node
from app.modules.upload.models import UploadPart, UploadSession


@dataclass(frozen=True)
class BlobReferenceResolution:
    blob: FileBlob
    created: bool


class UploadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_blob_by_hash(
        self,
        *,
        tenant_id: UUID,
        hash_algo: str,
        content_hash: str,
        size_bytes: int,
    ) -> FileBlob | None:
        result = await self.session.execute(
            select(FileBlob).where(
                FileBlob.tenant_id == tenant_id,
                FileBlob.hash_algo == hash_algo,
                FileBlob.content_hash == content_hash,
                FileBlob.size_bytes == size_bytes,
                FileBlob.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def get_blob_by_hash_any_status(
        self,
        *,
        tenant_id: UUID,
        hash_algo: str,
        content_hash: str,
        size_bytes: int,
    ) -> FileBlob | None:
        result = await self.session.execute(
            select(FileBlob).where(
                FileBlob.tenant_id == tenant_id,
                FileBlob.hash_algo == hash_algo,
                FileBlob.content_hash == content_hash,
                FileBlob.size_bytes == size_bytes,
            )
        )
        return result.scalar_one_or_none()

    async def create_file_node(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        parent_id: UUID,
        owner_id: UUID,
        name: str,
        normalized_name: str,
    ) -> Node:
        node = Node(
            tenant_id=tenant_id,
            space_id=space_id,
            parent_id=parent_id,
            owner_id=owner_id,
            node_type="file",
            name=name,
            normalized_name=normalized_name,
        )
        self.session.add(node)
        await self.session.flush()
        return node

    async def create_file_version(
        self,
        *,
        tenant_id: UUID,
        node_id: UUID,
        blob_id: UUID,
        version_no: int,
        size_bytes: int,
        mime_type: str | None,
        created_by: UUID,
    ) -> FileVersion:
        version = FileVersion(
            tenant_id=tenant_id,
            node_id=node_id,
            blob_id=blob_id,
            version_no=version_no,
            size_bytes=size_bytes,
            mime_type=mime_type,
            created_by=created_by,
        )
        self.session.add(version)
        await self.session.flush()
        return version

    async def increment_blob_ref_count(self, *, tenant_id: UUID, blob_id: UUID) -> bool:
        result = await self.session.execute(
            update(FileBlob)
            .where(
                FileBlob.tenant_id == tenant_id,
                FileBlob.id == blob_id,
                FileBlob.status == "active",
            )
            .values(ref_count=FileBlob.ref_count + 1)
            .returning(FileBlob.id)
        )
        return result.scalar_one_or_none() is not None

    async def create_file_blob(
        self,
        *,
        tenant_id: UUID,
        hash_algo: str,
        content_hash: str,
        size_bytes: int,
        storage_key: str,
        mime_type: str | None,
        ref_count: int,
    ) -> FileBlob:
        blob = FileBlob(
            tenant_id=tenant_id,
            hash_algo=hash_algo,
            content_hash=content_hash,
            size_bytes=size_bytes,
            storage_key=storage_key,
            mime_type=mime_type,
            ref_count=ref_count,
            status="active",
        )
        self.session.add(blob)
        await self.session.flush()
        return blob

    async def resolve_file_blob_reference(
        self,
        *,
        tenant_id: UUID,
        hash_algo: str,
        content_hash: str,
        size_bytes: int,
        storage_key: str,
        mime_type: str | None,
    ) -> BlobReferenceResolution:
        existing = await self.get_blob_by_hash_any_status(
            tenant_id=tenant_id,
            hash_algo=hash_algo,
            content_hash=content_hash,
            size_bytes=size_bytes,
        )
        if existing is not None:
            return BlobReferenceResolution(blob=existing, created=False)

        try:
            async with self.session.begin_nested():
                created = await self.create_file_blob(
                    tenant_id=tenant_id,
                    hash_algo=hash_algo,
                    content_hash=content_hash,
                    size_bytes=size_bytes,
                    storage_key=storage_key,
                    mime_type=mime_type,
                    ref_count=1,
                )
            return BlobReferenceResolution(blob=created, created=True)
        except IntegrityError as exc:
            existing = await self.get_blob_by_hash_any_status(
                tenant_id=tenant_id,
                hash_algo=hash_algo,
                content_hash=content_hash,
                size_bytes=size_bytes,
            )
            if existing is None:
                raise RuntimeError("file blob creation race did not resolve") from exc
            return BlobReferenceResolution(blob=existing, created=False)

    async def create_upload_session(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        parent_id: UUID,
        uploader_id: UUID,
        file_name: str,
        normalized_name: str,
        size_bytes: int,
        content_hash: str,
        hash_algo: str,
        mime_type: str | None,
        storage_bucket: str,
        storage_key: str,
        provider_upload_id: str,
        part_size_bytes: int,
        total_parts: int,
        expires_at: datetime,
    ) -> UploadSession:
        upload_session = UploadSession(
            tenant_id=tenant_id,
            space_id=space_id,
            parent_id=parent_id,
            uploader_id=uploader_id,
            file_name=file_name,
            normalized_name=normalized_name,
            size_bytes=size_bytes,
            content_hash=content_hash,
            hash_algo=hash_algo,
            mime_type=mime_type,
            status="initiated",
            storage_bucket=storage_bucket,
            storage_key=storage_key,
            provider_upload_id=provider_upload_id,
            part_size_bytes=part_size_bytes,
            total_parts=total_parts,
            expires_at=expires_at,
        )
        self.session.add(upload_session)
        await self.session.flush()
        return upload_session

    async def get_upload_session(
        self,
        *,
        tenant_id: UUID,
        uploader_id: UUID,
        session_id: UUID,
    ) -> UploadSession | None:
        result = await self.session.execute(
            select(UploadSession).where(
                UploadSession.tenant_id == tenant_id,
                UploadSession.uploader_id == uploader_id,
                UploadSession.id == session_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_upload_session_for_update(
        self,
        *,
        tenant_id: UUID,
        uploader_id: UUID,
        session_id: UUID,
    ) -> UploadSession | None:
        result = await self.session.execute(
            select(UploadSession)
            .where(
                UploadSession.tenant_id == tenant_id,
                UploadSession.uploader_id == uploader_id,
                UploadSession.id == session_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_upload_session_for_update_by_id(
        self,
        *,
        tenant_id: UUID,
        session_id: UUID,
    ) -> UploadSession | None:
        result = await self.session.execute(
            select(UploadSession)
            .where(
                UploadSession.tenant_id == tenant_id,
                UploadSession.id == session_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_expired_active_upload_session_ids(
        self,
        *,
        tenant_id: UUID,
        cutoff: datetime,
        limit: int,
    ) -> list[UUID]:
        result = await self.session.execute(
            select(UploadSession.id)
            .where(
                UploadSession.tenant_id == tenant_id,
                UploadSession.status.in_(["initiated", "uploading", "completing"]),
                UploadSession.expires_at <= cutoff,
            )
            .order_by(UploadSession.expires_at, UploadSession.id)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_uploaded_part_numbers(
        self,
        *,
        tenant_id: UUID,
        upload_session_id: UUID,
    ) -> list[int]:
        result = await self.session.execute(
            select(UploadPart.part_no)
            .where(
                UploadPart.tenant_id == tenant_id,
                UploadPart.upload_session_id == upload_session_id,
                UploadPart.uploaded_at.is_not(None),
            )
            .order_by(UploadPart.part_no)
        )
        return [int(part_no) for part_no in result.scalars().all()]

    async def record_uploaded_parts(
        self,
        *,
        tenant_id: UUID,
        upload_session_id: UUID,
        parts: list[tuple[int, str, int | None]],
        uploaded_at: datetime,
    ) -> None:
        part_numbers = [part_no for part_no, _, _ in parts]
        existing_result = await self.session.execute(
            select(UploadPart).where(
                UploadPart.tenant_id == tenant_id,
                UploadPart.upload_session_id == upload_session_id,
                UploadPart.part_no.in_(part_numbers),
            )
        )
        existing_parts = {part.part_no: part for part in existing_result.scalars().all()}

        for part_no, etag, size_bytes in parts:
            upload_part = existing_parts.get(part_no)
            if upload_part is None:
                self.session.add(
                    UploadPart(
                        tenant_id=tenant_id,
                        upload_session_id=upload_session_id,
                        part_no=part_no,
                        size_bytes=size_bytes,
                        etag=etag,
                        uploaded_at=uploaded_at,
                    )
                )
                continue
            upload_part.size_bytes = size_bytes
            upload_part.etag = etag
            upload_part.uploaded_at = uploaded_at
        await self.session.flush()

    async def flush(self) -> None:
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
