from __future__ import annotations

import math
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.security import ensure_utc, utc_now
from app.infrastructure.storage.base import StorageAdapter
from app.modules.audit.schemas import AuditContext
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.models import Node
from app.modules.file.repository import FileRepository
from app.modules.file.validators import node_name_conflict_error, normalize_node_name
from app.modules.quota.service import QuotaService
from app.modules.space.repository import SpaceRepository
from app.modules.upload.audit import (
    instant_upload_metadata,
    multipart_upload_metadata,
    record_upload_event,
)
from app.modules.upload.models import UploadSession
from app.modules.upload.repository import UploadRepository
from app.modules.upload.schemas import (
    InitUploadResponse,
    InstantUploadResponse,
    MultipartUploadResponse,
    UploadPartUrlResponse,
    UploadSessionStatusResponse,
)


class UploadService:
    def __init__(
        self,
        *,
        repository: UploadRepository,
        file_repository: FileRepository,
        space_repository: SpaceRepository,
        quota_service: QuotaService,
        storage: StorageAdapter,
        settings: Settings,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.file_repository = file_repository
        self.space_repository = space_repository
        self.quota_service = quota_service
        self.storage = storage
        self.settings = settings
        self.audit_service = audit_service

    async def init_upload(
        self,
        *,
        current_user: User,
        space_id: UUID,
        parent_id: UUID,
        file_name: str,
        size_bytes: int,
        content_hash: str,
        hash_algo: str,
        mime_type: str | None,
        audit_context: AuditContext | None = None,
    ) -> InitUploadResponse:
        parent = await self._get_owned_parent_folder(
            current_user=current_user,
            space_id=space_id,
            parent_id=parent_id,
        )
        normalized_name = normalize_node_name(file_name)
        await self._ensure_name_available(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
            parent_id=parent.id,
            normalized_name=normalized_name,
        )
        await self.quota_service.ensure_space_capacity(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
            size_bytes=size_bytes,
        )

        existing_blob = await self.repository.get_blob_by_hash(
            tenant_id=current_user.tenant_id,
            hash_algo=hash_algo,
            content_hash=content_hash,
            size_bytes=size_bytes,
        )
        if existing_blob is not None:
            return await self._instant_upload(
                current_user=current_user,
                parent=parent,
                file_name=normalized_name,
                normalized_name=normalized_name,
                blob_id=existing_blob.id,
                size_bytes=size_bytes,
                mime_type=mime_type or existing_blob.mime_type,
                audit_context=audit_context,
            )

        return await self._create_multipart_upload(
            current_user=current_user,
            parent=parent,
            file_name=normalized_name,
            normalized_name=normalized_name,
            size_bytes=size_bytes,
            content_hash=content_hash,
            hash_algo=hash_algo,
            mime_type=mime_type,
            audit_context=audit_context,
        )

    async def get_upload_status(
        self,
        *,
        current_user: User,
        session_id: UUID,
    ) -> UploadSessionStatusResponse:
        upload_session = await self._get_upload_session(
            current_user=current_user,
            session_id=session_id,
        )
        uploaded_parts = await self.repository.list_uploaded_part_numbers(
            tenant_id=current_user.tenant_id,
            upload_session_id=upload_session.id,
        )
        return UploadSessionStatusResponse(
            session_id=upload_session.id,
            status=upload_session.status,
            file_name=upload_session.file_name,
            size_bytes=upload_session.size_bytes,
            part_size_bytes=upload_session.part_size_bytes,
            total_parts=upload_session.total_parts,
            uploaded_parts=uploaded_parts,
            expires_at=upload_session.expires_at,
            completed_node_id=upload_session.completed_node_id,
            completed_version_id=upload_session.completed_version_id,
        )

    async def presign_upload_part(
        self,
        *,
        current_user: User,
        session_id: UUID,
        part_no: int,
    ) -> UploadPartUrlResponse:
        upload_session = await self._get_upload_session(
            current_user=current_user,
            session_id=session_id,
        )
        if upload_session.status not in {"initiated", "uploading"}:
            raise ApiError("UPLOAD_NOT_ACTIVE", "上传会话不可继续上传", status_code=409)
        if ensure_utc(upload_session.expires_at) <= utc_now():
            upload_session.status = "expired"
            await self.repository.commit()
            raise ApiError("UPLOAD_SESSION_EXPIRED", "上传会话已过期", status_code=410)
        if part_no < 1 or part_no > upload_session.total_parts:
            raise ApiError("UPLOAD_PART_INVALID", "分片编号不合法", status_code=422)
        if upload_session.provider_upload_id is None:
            raise ApiError("UPLOAD_SESSION_INVALID", "上传会话缺少对象存储会话", status_code=500)

        upload_session.status = "uploading"
        await self.repository.flush()
        presigned = await self.storage.presign_upload_part(
            bucket=upload_session.storage_bucket,
            storage_key=upload_session.storage_key,
            provider_upload_id=upload_session.provider_upload_id,
            part_no=part_no,
            expires_in_seconds=self.settings.upload_presign_expires_seconds,
        )
        await self.repository.commit()
        return UploadPartUrlResponse(
            part_no=presigned.part_no,
            upload_url=presigned.upload_url,
            expires_at=presigned.expires_at,
            headers=presigned.headers,
        )

    async def _instant_upload(
        self,
        *,
        current_user: User,
        parent: Node,
        file_name: str,
        normalized_name: str,
        blob_id: UUID,
        size_bytes: int,
        mime_type: str | None,
        audit_context: AuditContext | None,
    ) -> InstantUploadResponse:
        try:
            node = await self.repository.create_file_node(
                tenant_id=current_user.tenant_id,
                space_id=parent.space_id,
                parent_id=parent.id,
                owner_id=current_user.id,
                name=file_name,
                normalized_name=normalized_name,
            )
            version = await self.repository.create_file_version(
                tenant_id=current_user.tenant_id,
                node_id=node.id,
                blob_id=blob_id,
                version_no=1,
                size_bytes=size_bytes,
                mime_type=mime_type,
                created_by=current_user.id,
            )
            await self.repository.increment_blob_ref_count(
                tenant_id=current_user.tenant_id,
                blob_id=blob_id,
            )
            node.current_version_id = version.id
            await self.quota_service.reserve_file_version(
                tenant_id=current_user.tenant_id,
                space_id=parent.space_id,
                version_id=version.id,
                size_bytes=size_bytes,
            )
            await self.repository.flush()
            await record_upload_event(
                audit_service=self.audit_service,
                current_user=current_user,
                action="upload.instant",
                resource_id=node.id,
                audit_context=audit_context,
                metadata=instant_upload_metadata(node=node, blob_id=blob_id),
            )
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise node_name_conflict_error() from exc

        return InstantUploadResponse(node_id=node.id, version_id=version.id, blob_id=blob_id)

    async def _create_multipart_upload(
        self,
        *,
        current_user: User,
        parent: Node,
        file_name: str,
        normalized_name: str,
        size_bytes: int,
        content_hash: str,
        hash_algo: str,
        mime_type: str | None,
        audit_context: AuditContext | None,
    ) -> MultipartUploadResponse:
        part_size = self.settings.upload_part_size_bytes
        total_parts = math.ceil(size_bytes / part_size)
        expires_at = utc_now() + timedelta(minutes=self.settings.upload_session_ttl_minutes)
        storage_key = build_upload_storage_key(
            tenant_id=current_user.tenant_id,
            upload_session_hint=content_hash,
        )
        multipart_upload = await self.storage.create_multipart_upload(
            bucket=self.settings.s3_bucket,
            storage_key=storage_key,
            content_type=mime_type,
        )
        try:
            upload_session = await self.repository.create_upload_session(
                tenant_id=current_user.tenant_id,
                space_id=parent.space_id,
                parent_id=parent.id,
                uploader_id=current_user.id,
                file_name=file_name,
                normalized_name=normalized_name,
                size_bytes=size_bytes,
                content_hash=content_hash,
                hash_algo=hash_algo,
                mime_type=mime_type,
                storage_bucket=self.settings.s3_bucket,
                storage_key=storage_key,
                provider_upload_id=multipart_upload.provider_upload_id,
                part_size_bytes=part_size,
                total_parts=total_parts,
                expires_at=expires_at,
            )
            await record_upload_event(
                audit_service=self.audit_service,
                current_user=current_user,
                action="upload.initialized",
                resource_id=upload_session.id,
                audit_context=audit_context,
                metadata=multipart_upload_metadata(upload_session=upload_session),
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            await self.storage.abort_multipart_upload(
                bucket=self.settings.s3_bucket,
                storage_key=storage_key,
                provider_upload_id=multipart_upload.provider_upload_id,
            )
            raise
        return MultipartUploadResponse(
            session_id=upload_session.id,
            part_size_bytes=upload_session.part_size_bytes,
            total_parts=upload_session.total_parts,
            expires_at=upload_session.expires_at,
        )

    async def _get_owned_parent_folder(
        self,
        *,
        current_user: User,
        space_id: UUID,
        parent_id: UUID,
    ) -> Node:
        space = await self.space_repository.get_owned_active_space(
            tenant_id=current_user.tenant_id,
            owner_id=current_user.id,
            space_id=space_id,
        )
        if space is None:
            raise ApiError("SPACE_NOT_FOUND", "空间不存在或无权访问", status_code=404)
        parent = await self.file_repository.get_node(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
            node_id=parent_id,
        )
        if parent is None:
            raise ApiError("PARENT_NOT_FOUND", "父目录不存在或无权访问", status_code=404)
        if parent.node_type != "folder":
            raise ApiError("PARENT_NOT_FOLDER", "父节点不是文件夹", status_code=400)
        return parent

    async def _ensure_name_available(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        parent_id: UUID,
        normalized_name: str,
    ) -> None:
        existing_sibling = await self.file_repository.get_sibling_by_name(
            tenant_id=tenant_id,
            space_id=space_id,
            parent_id=parent_id,
            normalized_name=normalized_name,
        )
        if existing_sibling is not None:
            raise node_name_conflict_error()

    async def _get_upload_session(
        self,
        *,
        current_user: User,
        session_id: UUID,
    ) -> UploadSession:
        upload_session = await self.repository.get_upload_session(
            tenant_id=current_user.tenant_id,
            uploader_id=current_user.id,
            session_id=session_id,
        )
        if upload_session is None:
            raise ApiError("UPLOAD_SESSION_NOT_FOUND", "上传会话不存在或无权访问", status_code=404)
        return upload_session


def build_upload_storage_key(*, tenant_id: UUID, upload_session_hint: str) -> str:
    safe_hint = upload_session_hint.lower().replace(":", "-")[:48]
    return f"uploads/{tenant_id}/{safe_hint}/{uuid4()}"
