from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.security import ensure_utc, hash_token, utc_now, verify_password
from app.infrastructure.storage.base import StorageAdapter
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.file.repository import FileRepository
from app.modules.share.constants import (
    SHARE_PERMISSION_DOWNLOAD,
    SHARE_STATUS_ACTIVE,
    SHARE_STATUS_DISABLED,
    SHARE_STATUS_EXPIRED,
    SHARE_STATUS_REVOKED,
)
from app.modules.share.models import Share
from app.modules.share.repository import ShareRepository
from app.modules.share.schemas import ExternalShareDownloadResponse


class ShareExternalDownloadService:
    def __init__(
        self,
        *,
        repository: ShareRepository,
        file_repository: FileRepository,
        storage: StorageAdapter,
        settings: Settings,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.file_repository = file_repository
        self.storage = storage
        self.settings = settings
        self.audit_service = audit_service

    async def create_external_download_url(
        self,
        *,
        tenant_id: UUID,
        raw_token: str,
        node_id: UUID,
        passcode: str | None = None,
        audit_context: AuditContext | None = None,
    ) -> ExternalShareDownloadResponse:
        try:
            share = await self._get_external_share(
                tenant_id=tenant_id,
                raw_token=raw_token,
                passcode=passcode,
                audit_context=audit_context,
            )
            root_node = await self.file_repository.get_node_by_id(
                tenant_id=share.tenant_id,
                node_id=share.root_node_id,
            )
            if root_node is None:
                await self._raise_denied_download(
                    share=share,
                    audit_context=audit_context,
                    node_id=node_id,
                    error=ApiError("SHARE_ITEM_NOT_FOUND", "分享文件不存在", status_code=404),
                    metadata={"reason": "root_node_missing"},
                )

            await self._ensure_download_allowed(
                share=share,
                node_id=node_id,
                audit_context=audit_context,
            )
            node = await self.file_repository.get_node_by_id(
                tenant_id=share.tenant_id,
                node_id=node_id,
            )
            if node is None or node.space_id != root_node.space_id:
                await self._raise_denied_download(
                    share=share,
                    audit_context=audit_context,
                    node_id=node_id,
                    error=ApiError("SHARE_ITEM_NOT_FOUND", "分享文件不存在", status_code=404),
                    metadata={"reason": "node_missing_or_cross_space"},
                )
            if node.node_type != "file":
                await self._raise_denied_download(
                    share=share,
                    audit_context=audit_context,
                    node_id=node.id,
                    error=ApiError("SHARE_ITEM_NOT_FILE", "分享项不是文件", status_code=400),
                    metadata={"reason": "node_not_file"},
                )
            if node.current_version_id is None:
                await self._raise_denied_download(
                    share=share,
                    audit_context=audit_context,
                    node_id=node.id,
                    error=ApiError(
                        "FILE_VERSION_NOT_FOUND",
                        "文件当前版本不存在",
                        status_code=404,
                    ),
                    metadata={"reason": "current_version_missing"},
                )

            version_blob = await self.file_repository.get_current_version_with_blob(
                tenant_id=share.tenant_id,
                node_id=node.id,
                version_id=node.current_version_id,
            )
            if version_blob is None:
                await self._raise_denied_download(
                    share=share,
                    audit_context=audit_context,
                    node_id=node.id,
                    error=ApiError(
                        "FILE_VERSION_NOT_FOUND",
                        "文件当前版本不存在",
                        status_code=404,
                    ),
                    metadata={
                        "reason": "version_blob_missing",
                        "version_id": str(node.current_version_id),
                    },
                )

            consumed = await self.repository.consume_external_download(
                tenant_id=share.tenant_id,
                share_id=share.id,
            )
            if not consumed:
                refreshed_share = await self.repository.get_share(
                    tenant_id=share.tenant_id,
                    share_id=share.id,
                )
                await self._raise_denied_download(
                    share=refreshed_share or share,
                    audit_context=audit_context,
                    node_id=node.id,
                    error=self._external_share_error(
                        share=refreshed_share or share,
                        passcode=passcode,
                    )
                    or ApiError(
                        "SHARE_DOWNLOAD_LIMIT_EXCEEDED",
                        "分享下载次数已用尽",
                        status_code=410,
                    ),
                    metadata={"reason": "download_limit_or_state"},
                )

            version, blob = version_blob
            presigned = await self.storage.presign_download(
                bucket=self.settings.s3_bucket,
                storage_key=blob.storage_key,
                filename=node.name,
                expires_in_seconds=self.settings.download_presign_expires_seconds,
            )
            updated_share = await self.repository.get_share(
                tenant_id=share.tenant_id,
                share_id=share.id,
            )
            if updated_share is None:
                raise ApiError("SHARE_NOT_FOUND", "分享不存在", status_code=404)
            await self._record_download(
                share=updated_share,
                result="allowed",
                audit_context=audit_context,
                node_id=node.id,
                bytes_sent=version.size_bytes,
                metadata={
                    "version_id": str(version.id),
                    "blob_id": str(blob.id),
                    "size_bytes": version.size_bytes,
                },
            )
            await self.repository.commit()
            return ExternalShareDownloadResponse(
                share_id=updated_share.id,
                node_id=node.id,
                version_id=version.id,
                file_name=node.name,
                size_bytes=version.size_bytes,
                mime_type=version.mime_type or blob.mime_type,
                download_url=presigned.download_url,
                expires_at=presigned.expires_at,
                headers=presigned.headers,
                download_count=updated_share.download_count,
            )
        except ApiError:
            raise
        except Exception:
            await self.repository.rollback()
            raise

    async def _get_external_share(
        self,
        *,
        tenant_id: UUID,
        raw_token: str,
        passcode: str | None,
        audit_context: AuditContext | None,
    ) -> Share:
        share = await self.repository.get_external_share_by_token_hash(
            tenant_id=tenant_id,
            token_hash=hash_token(raw_token),
        )
        if share is None:
            raise ApiError("SHARE_NOT_FOUND", "分享不存在", status_code=404)
        access_error = self._external_share_error(share=share, passcode=passcode)
        if access_error is not None:
            await self._raise_denied_download(
                share=share,
                audit_context=audit_context,
                node_id=None,
                error=access_error,
                metadata={"reason": access_error.code},
            )
        return share

    async def _ensure_download_allowed(
        self,
        *,
        share: Share,
        node_id: UUID,
        audit_context: AuditContext | None,
    ) -> None:
        if share.permission != SHARE_PERMISSION_DOWNLOAD:
            await self._raise_denied_download(
                share=share,
                audit_context=audit_context,
                node_id=node_id,
                error=ApiError("SHARE_DOWNLOAD_FORBIDDEN", "分享不允许下载", status_code=403),
                metadata={"reason": "permission_not_download"},
            )
        if node_id == share.root_node_id:
            return
        if await self.repository.has_item(
            tenant_id=share.tenant_id,
            share_id=share.id,
            node_id=node_id,
        ):
            return
        await self._raise_denied_download(
            share=share,
            audit_context=audit_context,
            node_id=node_id,
            error=ApiError("SHARE_ITEM_NOT_FOUND", "分享文件不存在", status_code=404),
            metadata={"reason": "node_not_shared"},
        )

    def _external_share_error(self, *, share: Share, passcode: str | None) -> ApiError | None:
        if share.status == SHARE_STATUS_REVOKED:
            return ApiError("SHARE_REVOKED", "分享已撤销", status_code=410)
        if share.status in {SHARE_STATUS_DISABLED, SHARE_STATUS_EXPIRED}:
            return ApiError("SHARE_EXPIRED", "分享不可用或已过期", status_code=410)
        if share.status != SHARE_STATUS_ACTIVE:
            return ApiError("SHARE_REVOKED", "分享不可用", status_code=410)
        if share.expires_at is not None and ensure_utc(share.expires_at) <= utc_now():
            return ApiError("SHARE_EXPIRED", "分享已过期", status_code=410)
        if share.passcode_hash is not None and (
            passcode is None or not verify_password(passcode, share.passcode_hash)
        ):
            return ApiError("SHARE_PASSCODE_INVALID", "提取码不正确", status_code=403)
        return None

    async def _record_download(
        self,
        *,
        share: Share,
        result: str,
        audit_context: AuditContext | None,
        node_id: UUID | None,
        bytes_sent: int = 0,
        metadata: dict[str, object] | None = None,
    ) -> None:
        context = audit_context or AuditContext()
        await self.repository.add_access_log(
            tenant_id=share.tenant_id,
            share_id=share.id,
            actor_id=None,
            actor_type="external",
            action="download",
            result=result,
            ip=context.ip,
            user_agent=context.user_agent,
            bytes_sent=bytes_sent,
        )
        if self.audit_service is None:
            return
        await self.audit_service.record(
            event=AuditEvent(
                tenant_id=share.tenant_id,
                actor_id=None,
                actor_type="external",
                action="share.external.downloaded",
                resource_type="node" if node_id is not None else "share",
                resource_id=node_id or share.id,
                result=result,
                metadata={
                    "share_id": str(share.id),
                    "share_type": share.share_type,
                    "permission": share.permission,
                    "root_node_id": str(share.root_node_id),
                    **(metadata or {}),
                },
            ),
            context=context,
        )

    async def _raise_denied_download(
        self,
        *,
        share: Share,
        audit_context: AuditContext | None,
        node_id: UUID | None,
        error: ApiError,
        metadata: dict[str, object],
    ) -> NoReturn:
        await self._record_download(
            share=share,
            result="denied",
            audit_context=audit_context,
            node_id=node_id,
            metadata=metadata,
        )
        await self.repository.commit()
        raise error
