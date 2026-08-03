from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.pagination import decode_page_cursor, encode_page_cursor
from app.core.security import utc_now
from app.infrastructure.storage.base import StorageAdapter
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.audit import record_node_event
from app.modules.file.models import FileBlob, FileVersion, Node
from app.modules.file.repository import FileRepository
from app.modules.file.schemas import (
    FileDownloadUrlResponse,
    FileVersionListResponse,
    FileVersionResponse,
    FileVersionRollbackResponse,
)
from app.modules.file_security.service import FileSecurityDecision, FileSecurityService
from app.modules.permission.actions import ACTION_DOWNLOAD, ACTION_READ_META, ACTION_UPDATE
from app.modules.permission.service import PermissionService
from app.modules.preview.events import emit_preview_render_requested
from app.modules.quota.service import QuotaService
from app.modules.search.events import emit_search_extract_requested, emit_search_index_requested
from app.modules.space.repository import SpaceRepository


class FileVersionService:
    def __init__(
        self,
        *,
        repository: FileRepository,
        space_repository: SpaceRepository,
        permission_service: PermissionService,
        quota_service: QuotaService,
        storage: StorageAdapter,
        settings: Settings,
        audit_service: AuditService | None = None,
        security_service: FileSecurityService | None = None,
    ) -> None:
        self.repository = repository
        self.space_repository = space_repository
        self.permission_service = permission_service
        self.quota_service = quota_service
        self.storage = storage
        self.settings = settings
        self.audit_service = audit_service
        self.security_service = security_service

    async def list_versions(
        self,
        *,
        current_user: User,
        node_id: UUID,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext | None = None,
    ) -> FileVersionListResponse:
        node = await self._get_accessible_file(
            current_user=current_user,
            node_id=node_id,
            action=ACTION_READ_META,
        )
        versions = await self.repository.list_versions(
            tenant_id=current_user.tenant_id,
            node_id=node.id,
            limit=page_size + 1,
            cursor=decode_page_cursor(self.settings, cursor),
        )
        items = versions[:page_size]
        next_cursor = None
        if len(versions) > page_size and items:
            last_item = items[-1]
            next_cursor = encode_page_cursor(
                self.settings,
                created_at=last_item.created_at,
                item_id=last_item.id,
            )
        await record_node_event(
            audit_service=self.audit_service,
            current_user=current_user,
            node=node,
            action="file.versions.listed",
            audit_context=audit_context,
            metadata={"returned_count": len(items)},
        )
        await self.repository.commit()
        return FileVersionListResponse(
            node_id=node.id,
            current_version_id=node.current_version_id,
            items=[
                FileVersionResponse(
                    id=version.id,
                    node_id=version.node_id,
                    version_no=version.version_no,
                    size_bytes=version.size_bytes,
                    mime_type=version.mime_type,
                    created_by=version.created_by,
                    created_at=version.created_at,
                    is_current=version.id == node.current_version_id,
                )
                for version in items
            ],
            next_cursor=next_cursor,
        )

    async def create_version_download_url(
        self,
        *,
        current_user: User,
        node_id: UUID,
        version_id: UUID,
        audit_context: AuditContext | None = None,
    ) -> FileDownloadUrlResponse:
        node = await self._get_accessible_file(
            current_user=current_user,
            node_id=node_id,
            action=ACTION_DOWNLOAD,
        )
        version, blob = await self._get_version_blob(
            current_user=current_user,
            node=node,
            version_id=version_id,
        )
        security_decision = await self._ensure_version_delivery_allowed(
            current_user=current_user,
            node=node,
            version=version,
            blob=blob,
            audit_context=audit_context,
        )
        presigned = await self.storage.presign_download(
            bucket=self.settings.s3_bucket,
            storage_key=blob.storage_key,
            filename=node.name,
            expires_in_seconds=self.settings.download_presign_expires_seconds,
        )
        await record_node_event(
            audit_service=self.audit_service,
            current_user=current_user,
            node=node,
            action="file.version.downloaded",
            audit_context=audit_context,
            metadata={
                "version_id": str(version.id),
                "version_no": version.version_no,
                "blob_id": str(blob.id),
                "size_bytes": version.size_bytes,
                "delivery_mode": "presigned",
                **_security_metadata(security_decision),
            },
        )
        await self.repository.commit()
        return FileDownloadUrlResponse(
            node_id=node.id,
            version_id=version.id,
            file_name=node.name,
            size_bytes=version.size_bytes,
            hash_algo=blob.hash_algo,
            content_hash=blob.content_hash,
            mime_type=version.mime_type or blob.mime_type,
            download_url=presigned.download_url,
            expires_at=presigned.expires_at,
            headers=presigned.headers,
        )

    async def rollback_version(
        self,
        *,
        current_user: User,
        node_id: UUID,
        source_version_id: UUID,
        expected_current_version_id: UUID | None,
        audit_context: AuditContext | None = None,
    ) -> FileVersionRollbackResponse:
        node = await self.repository.get_node_by_id_for_update(
            tenant_id=current_user.tenant_id,
            node_id=node_id,
        )
        if node is None:
            raise ApiError("NODE_NOT_FOUND", "节点不存在或无权访问", status_code=404)
        await self._ensure_node_access(
            current_user=current_user,
            node=node,
            action=ACTION_UPDATE,
        )
        if node.node_type != "file":
            raise ApiError("NODE_NOT_FILE", "节点不是文件", status_code=400)
        if (
            expected_current_version_id is not None
            and node.current_version_id != expected_current_version_id
        ):
            raise ApiError(
                "FILE_VERSION_CONFLICT",
                "文件当前版本已变化",
                status_code=409,
                details={
                    "expected_current_version_id": str(expected_current_version_id),
                    "current_version_id": (
                        str(node.current_version_id) if node.current_version_id else None
                    ),
                },
            )

        source_version, blob = await self._get_version_blob(
            current_user=current_user,
            node=node,
            version_id=source_version_id,
        )
        previous_current_version_id = node.current_version_id
        try:
            version = await self.repository.create_file_version(
                tenant_id=current_user.tenant_id,
                node_id=node.id,
                blob_id=blob.id,
                version_no=await self.repository.next_version_no(
                    tenant_id=current_user.tenant_id,
                    node_id=node.id,
                ),
                size_bytes=source_version.size_bytes,
                mime_type=source_version.mime_type or blob.mime_type,
                created_by=current_user.id,
            )
            if not await self.repository.increment_blob_ref_count(
                tenant_id=current_user.tenant_id,
                blob_id=blob.id,
            ):
                raise ApiError("FILE_CONTENT_NOT_AVAILABLE", "文件内容暂不可用", status_code=409)
            await self.quota_service.reserve_file_version(
                tenant_id=current_user.tenant_id,
                space_id=node.space_id,
                version_id=version.id,
                size_bytes=version.size_bytes,
                user_id=current_user.id,
                file_name=node.name,
                mime_type=version.mime_type,
            )
            node.current_version_id = version.id
            node.updated_at = utc_now()
            await record_node_event(
                audit_service=self.audit_service,
                current_user=current_user,
                node=node,
                action="file.version.rolled_back",
                audit_context=audit_context,
                metadata={
                    "source_version_id": str(source_version.id),
                    "source_version_no": source_version.version_no,
                    "previous_current_version_id": (
                        str(previous_current_version_id)
                        if previous_current_version_id is not None
                        else None
                    ),
                    "new_version_id": str(version.id),
                    "new_version_no": version.version_no,
                    "blob_id": str(blob.id),
                },
            )
            await emit_search_index_requested(
                audit_service=self.audit_service,
                tenant_id=current_user.tenant_id,
                node_id=node.id,
                space_id=node.space_id,
                reason="file_version_rollback",
                metadata={
                    "source_version_id": str(source_version.id),
                    "new_version_id": str(version.id),
                },
            )
            await emit_search_extract_requested(
                audit_service=self.audit_service,
                tenant_id=current_user.tenant_id,
                node_id=node.id,
                version_id=version.id,
                blob_id=blob.id,
                reason="file_version_rollback",
            )
            await emit_preview_render_requested(
                audit_service=self.audit_service,
                tenant_id=current_user.tenant_id,
                node_id=node.id,
                version_id=version.id,
                blob_id=blob.id,
                reason="file_version_rollback",
            )
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise ApiError(
                "FILE_VERSION_CONFLICT",
                "文件版本创建冲突",
                status_code=409,
            ) from exc
        except Exception:
            await self.repository.rollback()
            raise

        return FileVersionRollbackResponse(
            node_id=node.id,
            source_version_id=source_version.id,
            new_version_id=version.id,
            version_no=version.version_no,
            current_version_id=version.id,
        )

    async def _get_accessible_file(
        self,
        *,
        current_user: User,
        node_id: UUID,
        action: str,
    ) -> Node:
        node = await self.repository.get_node_by_id(
            tenant_id=current_user.tenant_id,
            node_id=node_id,
        )
        if node is None:
            raise ApiError("NODE_NOT_FOUND", "节点不存在或无权访问", status_code=404)
        await self._ensure_node_access(
            current_user=current_user,
            node=node,
            action=action,
        )
        if node.node_type != "file":
            raise ApiError("NODE_NOT_FILE", "节点不是文件", status_code=400)
        return node

    async def _ensure_node_access(
        self,
        *,
        current_user: User,
        node: Node,
        action: str,
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
        allowed = (
            space is not None
            and node_path_ids is not None
            and await self.permission_service.can_access_node(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                space_id=node.space_id,
                action=action,
                node_path_ids=node_path_ids,
            )
        )
        if not allowed:
            raise ApiError("NODE_NOT_FOUND", "节点不存在或无权访问", status_code=404)

    async def _get_version_blob(
        self,
        *,
        current_user: User,
        node: Node,
        version_id: UUID,
    ) -> tuple[FileVersion, FileBlob]:
        version_blob = await self.repository.get_version_with_blob(
            tenant_id=current_user.tenant_id,
            node_id=node.id,
            version_id=version_id,
        )
        if version_blob is None:
            raise ApiError("FILE_VERSION_NOT_FOUND", "文件版本不存在", status_code=404)
        version, blob = version_blob
        if blob.status != "active":
            raise ApiError("FILE_CONTENT_NOT_AVAILABLE", "文件内容暂不可用", status_code=409)
        return version, blob

    async def _ensure_version_delivery_allowed(
        self,
        *,
        current_user: User,
        node: Node,
        version: FileVersion,
        blob: FileBlob,
        audit_context: AuditContext | None,
    ) -> FileSecurityDecision | None:
        if self.security_service is None:
            return None
        decision = await self.security_service.evaluate(
            tenant_id=current_user.tenant_id,
            file_name=node.name,
            mime_type=version.mime_type or blob.mime_type,
            version=version,
        )
        try:
            self.security_service.ensure_delivery(
                decision=decision,
                requested_mode="presigned",
            )
        except ApiError as exc:
            if self.audit_service is not None:
                await self.audit_service.record(
                    event=AuditEvent(
                        tenant_id=current_user.tenant_id,
                        actor_id=current_user.id,
                        action="file.version.downloaded",
                        resource_type="node",
                        resource_id=node.id,
                        result="denied",
                        risk_level="medium",
                        metadata={
                            "space_id": str(node.space_id),
                            "version_id": str(version.id),
                            "version_no": version.version_no,
                            "reason": exc.code.lower(),
                            **decision.audit_metadata(),
                        },
                    ),
                    context=audit_context or AuditContext(),
                )
                await self.repository.commit()
            raise
        return decision


def _security_metadata(decision: FileSecurityDecision | None) -> dict[str, object]:
    return decision.audit_metadata() if decision is not None else {}
