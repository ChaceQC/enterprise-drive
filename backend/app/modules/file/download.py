from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import quote
from uuid import UUID

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.transfer_protocol import DRIVE_TRANSFER_PROTOCOL_HEADER, DRIVE_TRANSFER_PROTOCOL_V1
from app.infrastructure.storage.base import StorageAdapter
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.audit import record_node_event
from app.modules.file.download_range import resolve_download_range
from app.modules.file.models import FileBlob, FileVersion, Node
from app.modules.file.repository import FileRepository
from app.modules.file.schemas import FileDownloadUrlResponse
from app.modules.permission.actions import ACTION_DOWNLOAD
from app.modules.permission.service import PermissionService
from app.modules.space.repository import SpaceRepository


@dataclass(frozen=True, slots=True)
class DownloadSource:
    node: Node
    version: FileVersion
    blob: FileBlob


@dataclass(frozen=True, slots=True)
class FileProxyDownload:
    status_code: int
    media_type: str
    headers: dict[str, str]
    body: AsyncIterator[bytes]


class FileDownloadService:
    def __init__(
        self,
        *,
        repository: FileRepository,
        space_repository: SpaceRepository,
        permission_service: PermissionService,
        storage: StorageAdapter,
        settings: Settings,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.space_repository = space_repository
        self.permission_service = permission_service
        self.storage = storage
        self.settings = settings
        self.audit_service = audit_service

    async def create_download_url(
        self,
        *,
        current_user: User,
        node_id: UUID,
        audit_context: AuditContext | None = None,
    ) -> FileDownloadUrlResponse:
        source = await self._get_download_source(
            current_user=current_user,
            node_id=node_id,
            audit_context=audit_context,
        )

        presigned = await self.storage.presign_download(
            bucket=self.settings.s3_bucket,
            storage_key=source.blob.storage_key,
            filename=source.node.name,
            expires_in_seconds=self.settings.download_presign_expires_seconds,
        )
        await record_node_event(
            audit_service=self.audit_service,
            current_user=current_user,
            node=source.node,
            action="file.downloaded",
            audit_context=audit_context,
            metadata={
                "version_id": str(source.version.id),
                "blob_id": str(source.blob.id),
                "size_bytes": source.version.size_bytes,
                "delivery_mode": "presigned",
            },
        )
        await self.repository.commit()
        return FileDownloadUrlResponse(
            node_id=source.node.id,
            version_id=source.version.id,
            file_name=source.node.name,
            size_bytes=source.version.size_bytes,
            mime_type=source.version.mime_type or source.blob.mime_type,
            download_url=presigned.download_url,
            expires_at=presigned.expires_at,
            headers=presigned.headers,
        )

    async def create_proxy_download(
        self,
        *,
        current_user: User,
        node_id: UUID,
        range_header: str | None,
        audit_context: AuditContext | None = None,
    ) -> FileProxyDownload:
        source = await self._get_download_source(
            current_user=current_user,
            node_id=node_id,
            audit_context=audit_context,
        )
        try:
            byte_range = resolve_download_range(
                range_header,
                size_bytes=source.version.size_bytes,
                max_range_bytes=self.settings.download_proxy_max_range_bytes,
            )
        except ApiError as exc:
            await self._record_denied_download(
                current_user=current_user,
                resource_id=source.node.id,
                reason=exc.code.lower(),
                audit_context=audit_context,
                metadata={
                    "space_id": str(source.node.space_id),
                    "version_id": str(source.version.id),
                    "delivery_mode": "proxy",
                },
            )
            raise

        media_type = source.version.mime_type or source.blob.mime_type or "application/octet-stream"
        headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, no-store",
            "Content-Disposition": _content_disposition(source.node.name),
            "Content-Length": str(byte_range.length),
            "ETag": f'"{source.blob.content_hash}"',
            "X-Content-Type-Options": "nosniff",
            DRIVE_TRANSFER_PROTOCOL_HEADER: DRIVE_TRANSFER_PROTOCOL_V1,
        }
        if byte_range.partial:
            headers["Content-Range"] = byte_range.content_range

        await record_node_event(
            audit_service=self.audit_service,
            current_user=current_user,
            node=source.node,
            action="file.downloaded",
            audit_context=audit_context,
            metadata={
                "version_id": str(source.version.id),
                "blob_id": str(source.blob.id),
                "size_bytes": source.version.size_bytes,
                "delivery_mode": "proxy",
                "partial": byte_range.partial,
                "range_start": byte_range.start,
                "range_end": byte_range.end,
                "response_bytes": byte_range.length,
            },
        )
        await self.repository.commit()
        return FileProxyDownload(
            status_code=206 if byte_range.partial else 200,
            media_type=media_type,
            headers=headers,
            body=self.storage.stream_object(
                bucket=self.settings.s3_bucket,
                storage_key=source.blob.storage_key,
                offset=byte_range.start,
                length=byte_range.length,
                chunk_size=self.settings.download_proxy_chunk_size_bytes,
            ),
        )

    async def _get_download_source(
        self,
        *,
        current_user: User,
        node_id: UUID,
        audit_context: AuditContext | None,
    ) -> DownloadSource:
        node = await self._get_owned_file_node(
            current_user=current_user,
            node_id=node_id,
            audit_context=audit_context,
        )
        if node.current_version_id is None:
            await self._record_denied_download(
                current_user=current_user,
                resource_id=node.id,
                reason="current_version_missing",
                audit_context=audit_context,
                metadata={"space_id": str(node.space_id)},
            )
            raise ApiError("FILE_VERSION_NOT_FOUND", "文件当前版本不存在", status_code=404)

        version_blob = await self.repository.get_current_version_with_blob(
            tenant_id=current_user.tenant_id,
            node_id=node.id,
            version_id=node.current_version_id,
        )
        if version_blob is None:
            await self._record_denied_download(
                current_user=current_user,
                resource_id=node.id,
                reason="version_blob_missing",
                audit_context=audit_context,
                metadata={
                    "space_id": str(node.space_id),
                    "version_id": str(node.current_version_id),
                },
            )
            raise ApiError("FILE_VERSION_NOT_FOUND", "文件当前版本不存在", status_code=404)
        version, blob = version_blob
        if blob.status != "active":
            await self._record_denied_download(
                current_user=current_user,
                resource_id=node.id,
                reason="blob_not_active",
                audit_context=audit_context,
                metadata={
                    "space_id": str(node.space_id),
                    "version_id": str(version.id),
                },
            )
            raise ApiError("FILE_CONTENT_NOT_AVAILABLE", "文件内容暂不可用", status_code=409)
        return DownloadSource(node=node, version=version, blob=blob)

    async def _get_owned_file_node(
        self,
        *,
        current_user: User,
        node_id: UUID,
        audit_context: AuditContext | None,
    ) -> Node:
        node = await self.repository.get_node_by_id(
            tenant_id=current_user.tenant_id,
            node_id=node_id,
        )
        if node is None:
            await self._record_denied_download(
                current_user=current_user,
                resource_id=node_id,
                reason="node_missing_or_deleted",
                audit_context=audit_context,
            )
            raise ApiError("NODE_NOT_FOUND", "节点不存在或无权访问", status_code=404)
        await self._ensure_space_download_allowed(
            current_user=current_user,
            node=node,
            audit_context=audit_context,
        )
        if node.node_type != "file":
            await self._record_denied_download(
                current_user=current_user,
                resource_id=node.id,
                reason="node_not_file",
                audit_context=audit_context,
                metadata={"space_id": str(node.space_id), "node_type": node.node_type},
            )
            raise ApiError("NODE_NOT_FILE", "节点不是文件", status_code=400)
        return node

    async def _ensure_space_download_allowed(
        self,
        *,
        current_user: User,
        node: Node,
        audit_context: AuditContext | None,
    ) -> None:
        space = await self.space_repository.get_active_space(
            tenant_id=current_user.tenant_id,
            space_id=node.space_id,
        )
        node_path_ids = await self.repository.get_node_path_ids(
            tenant_id=current_user.tenant_id,
            space_id=node.space_id,
            node_id=node.id,
        )
        if space is None or node_path_ids is None:
            allowed = False
        else:
            allowed = await self.permission_service.can_access_node(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                space_id=node.space_id,
                action=ACTION_DOWNLOAD,
                node_path_ids=node_path_ids,
            )
        if not allowed:
            await self._record_denied_download(
                current_user=current_user,
                resource_id=node.id,
                reason="permission_denied",
                audit_context=audit_context,
                metadata={"space_id": str(node.space_id)},
            )
            raise ApiError("NODE_NOT_FOUND", "节点不存在或无权访问", status_code=404)

    async def _record_denied_download(
        self,
        *,
        current_user: User,
        resource_id: UUID,
        reason: str,
        audit_context: AuditContext | None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        if self.audit_service is None:
            return
        await self.audit_service.record(
            event=AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action="file.downloaded",
                resource_type="node",
                resource_id=resource_id,
                result="denied",
                risk_level="medium",
                metadata={"reason": reason, **(metadata or {})},
            ),
            context=audit_context or AuditContext(),
        )
        await self.repository.commit()


def _content_disposition(filename: str) -> str:
    safe_filename = filename.replace("/", "_").replace("\\", "_").replace('"', "_")
    ascii_filename = safe_filename.encode("ascii", "ignore").decode() or "download"
    return (
        f'attachment; filename="{ascii_filename}"; '
        f"filename*=UTF-8''{quote(safe_filename, safe='')}"
    )
