from __future__ import annotations

import asyncio
from uuid import UUID

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.pagination import decode_page_cursor, encode_page_cursor
from app.core.security import ensure_utc, utc_now
from app.infrastructure.storage.base import StorageAdapter
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository
from app.modules.file.models import FileBlob, FileVersion, Node
from app.modules.file.repository import FileRepository
from app.modules.file_security.service import (
    DeliveryMode,
    FileSecurityDecision,
    FileSecurityService,
)
from app.modules.file_security.watermark import WatermarkRenderer, build_watermark_text
from app.modules.permission.actions import ACTION_SHARE
from app.modules.permission.service import PermissionService
from app.modules.share.constants import (
    SHARE_PERMISSION_DOWNLOAD,
    SHARE_STATUS_ACTIVE,
    SHARE_STATUS_DISABLED,
    SHARE_STATUS_EXPIRED,
    SHARE_STATUS_REVOKED,
    SHARE_TYPE_INTERNAL,
)
from app.modules.share.models import Share, ShareNotification
from app.modules.share.recipient_grants import ShareRecipientGrantService
from app.modules.share.repository import ShareRepository
from app.modules.share.schemas import (
    InternalShareDownloadResponse,
    InternalShareItem,
    InternalShareItemsResponse,
    ShareListItem,
    ShareListResponse,
    ShareNotificationItem,
    ShareNotificationListResponse,
    ShareNotificationReadResponse,
)


class InternalShareService:
    def __init__(
        self,
        *,
        repository: ShareRepository,
        file_repository: FileRepository,
        auth_repository: AuthRepository,
        permission_service: PermissionService,
        recipient_grant_service: ShareRecipientGrantService,
        storage: StorageAdapter,
        settings: Settings,
        audit_service: AuditService | None = None,
        security_service: FileSecurityService | None = None,
        watermark_renderer: WatermarkRenderer | None = None,
    ) -> None:
        self.repository = repository
        self.file_repository = file_repository
        self.auth_repository = auth_repository
        self.permission_service = permission_service
        self.recipient_grant_service = recipient_grant_service
        self.storage = storage
        self.settings = settings
        self.audit_service = audit_service
        self.security_service = security_service
        self.watermark_renderer = watermark_renderer or WatermarkRenderer()

    async def list_created(
        self,
        *,
        current_user: User,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext | None,
    ) -> ShareListResponse:
        rows = await self.repository.list_created_shares(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            cursor=decode_page_cursor(self.settings, cursor),
            limit=page_size + 1,
        )
        page = rows[:page_size]
        response = ShareListResponse(
            items=[
                _share_list_item(share=share, creator=creator, root_node=root_node)
                for share, creator, root_node in page
            ],
            next_cursor=_next_share_cursor(self.settings, rows, page_size),
        )
        await self._record(
            current_user=current_user,
            share=None,
            action="share.created.listed",
            resource_id=current_user.id,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "returned_count": len(response.items),
                "has_next": response.next_cursor is not None,
            },
            resource_type="share",
        )
        await self.repository.commit()
        return response

    async def list_received(
        self,
        *,
        current_user: User,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext | None,
    ) -> ShareListResponse:
        await self.recipient_grant_service.reconcile_user(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
        )
        await self.repository.commit()
        rows = await self.repository.list_received_shares(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            cursor=decode_page_cursor(self.settings, cursor),
            limit=page_size + 1,
        )
        page = rows[:page_size]
        response = ShareListResponse(
            items=[
                _share_list_item(share=share, creator=creator, root_node=root_node)
                for share, creator, root_node in page
            ],
            next_cursor=_next_share_cursor(self.settings, rows, page_size),
        )
        await self._record(
            current_user=current_user,
            share=None,
            action="share.received.listed",
            resource_id=current_user.id,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "returned_count": len(response.items),
                "has_next": response.next_cursor is not None,
            },
            resource_type="share",
        )
        await self.repository.commit()
        return response

    async def list_items(
        self,
        *,
        current_user: User,
        share_id: UUID,
        audit_context: AuditContext | None,
    ) -> InternalShareItemsResponse:
        share = await self._get_internal_share(current_user=current_user, share_id=share_id)
        is_creator = share.created_by == current_user.id
        if not is_creator:
            await self._require_current_recipient(current_user=current_user, share=share)

        creator = await self._get_creator(share)
        root_node = await self._get_active_share_node(
            share=share,
            node_id=share.root_node_id,
        )
        await self._ensure_creator_can_share(share=share, creator=creator, node=root_node)
        rows = await self.repository.list_items_with_nodes(
            tenant_id=current_user.tenant_id,
            share_id=share.id,
        )
        items: list[InternalShareItem] = []
        for _, node, version, blob in rows:
            if node.is_deleted:
                continue
            await self._ensure_creator_can_share(
                share=share,
                creator=creator,
                node=node,
            )
            items.append(
                InternalShareItem(
                    node_id=node.id,
                    name=node.name,
                    node_type=node.node_type,
                    is_root=node.id == share.root_node_id,
                    current_version_id=node.current_version_id,
                    size_bytes=version.size_bytes if version is not None else None,
                    mime_type=(
                        version.mime_type or blob.mime_type
                        if version is not None and blob is not None
                        else version.mime_type
                        if version is not None
                        else None
                    ),
                )
            )
        if not is_creator:
            consumed = await self.repository.consume_internal_view(
                tenant_id=current_user.tenant_id,
                share_id=share.id,
            )
            if not consumed:
                refreshed = await self.repository.get_share(
                    tenant_id=current_user.tenant_id,
                    share_id=share.id,
                )
                raise _share_access_error(refreshed or share, view=True) or ApiError(
                    "SHARE_VIEW_LIMIT_EXCEEDED",
                    "分享访问次数已用尽",
                    status_code=410,
                )
            share = (
                await self.repository.get_share(
                    tenant_id=current_user.tenant_id,
                    share_id=share.id,
                )
                or share
            )
        await self.repository.add_access_log(
            tenant_id=share.tenant_id,
            share_id=share.id,
            actor_id=current_user.id,
            actor_type="user",
            action="view",
            result="allowed",
            ip=(audit_context or AuditContext()).ip,
            user_agent=(audit_context or AuditContext()).user_agent,
        )
        await self._record(
            current_user=current_user,
            share=share,
            action="share.internal.accessed",
            resource_id=share.id,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "access_role": "creator" if is_creator else "recipient",
                "item_count": len(items),
            },
        )
        await self.repository.commit()
        return InternalShareItemsResponse(
            share=_share_list_item(share=share, creator=creator, root_node=root_node),
            access_role="creator" if is_creator else "recipient",
            items=items,
        )

    async def create_download_url(
        self,
        *,
        current_user: User,
        share_id: UUID,
        node_id: UUID,
        delivery_mode: DeliveryMode,
        audit_context: AuditContext | None,
    ) -> InternalShareDownloadResponse:
        share = await self._get_internal_share(current_user=current_user, share_id=share_id)
        if share.created_by == current_user.id:
            raise ApiError(
                "SHARE_RECIPIENT_REQUIRED",
                "创建者请使用文件下载接口",
                status_code=409,
            )
        await self._require_current_recipient(current_user=current_user, share=share)
        if share.permission != SHARE_PERMISSION_DOWNLOAD:
            raise ApiError("SHARE_DOWNLOAD_FORBIDDEN", "该分享只允许预览", status_code=403)
        if not await self.repository.has_item(
            tenant_id=current_user.tenant_id,
            share_id=share.id,
            node_id=node_id,
        ):
            raise ApiError("SHARE_ITEM_NOT_FOUND", "分享文件不存在", status_code=404)

        creator = await self._get_creator(share)
        node = await self._get_active_share_node(share=share, node_id=node_id)
        await self._ensure_creator_can_share(share=share, creator=creator, node=node)
        if node.node_type != "file":
            raise ApiError("SHARE_ITEM_NOT_FILE", "分享项不是文件", status_code=400)
        if node.current_version_id is None:
            raise ApiError("FILE_VERSION_NOT_FOUND", "文件当前版本不存在", status_code=404)
        version_blob = await self.file_repository.get_current_version_with_blob(
            tenant_id=current_user.tenant_id,
            node_id=node.id,
            version_id=node.current_version_id,
        )
        if version_blob is None:
            raise ApiError("FILE_VERSION_NOT_FOUND", "文件当前版本不存在", status_code=404)
        version, blob = version_blob
        decision = await self._ensure_delivery_allowed(
            share=share,
            node=node,
            version=version,
            blob=blob,
            delivery_mode=delivery_mode,
        )

        rendered_content: bytes | None = None
        rendered_name = node.name
        rendered_mime = version.mime_type or blob.mime_type or "application/octet-stream"
        if delivery_mode == "watermark":
            if version.size_bytes > self.settings.watermark_max_source_bytes:
                raise ApiError(
                    "WATERMARK_SOURCE_TOO_LARGE",
                    "文件超过水印处理大小上限",
                    status_code=422,
                )
            source_content = await self.storage.read_object_bytes(
                bucket=self.settings.s3_bucket,
                storage_key=blob.storage_key,
                max_bytes=version.size_bytes,
            )
            rendered = await asyncio.to_thread(
                self.watermark_renderer.render,
                content=source_content,
                mime_type=rendered_mime,
                file_name=node.name,
                watermark_text=build_watermark_text(
                    template=decision.watermark_text if decision is not None else None,
                    user_label=current_user.display_name,
                    user_id=current_user.id,
                    tenant_id=current_user.tenant_id,
                    now=utc_now(),
                ),
            )
            rendered_content = rendered.content
            rendered_name = rendered.file_name
            rendered_mime = rendered.media_type

        consumed = await self.repository.consume_internal_download(
            tenant_id=current_user.tenant_id,
            share_id=share.id,
        )
        if not consumed:
            refreshed = await self.repository.get_share(
                tenant_id=current_user.tenant_id,
                share_id=share.id,
            )
            raise _share_access_error(refreshed or share, download=True) or ApiError(
                "SHARE_DOWNLOAD_LIMIT_EXCEEDED",
                "分享下载次数已用尽",
                status_code=410,
            )

        response_size = version.size_bytes
        storage_key = blob.storage_key
        if rendered_content is not None:
            response_size = len(rendered_content)
            storage_key = _internal_watermark_key(
                tenant_id=current_user.tenant_id,
                share_id=share.id,
                user_id=current_user.id,
                node_id=node.id,
                version_id=version.id,
            )
            await self.storage.put_object_bytes(
                bucket=self.settings.s3_bucket,
                storage_key=storage_key,
                content=rendered_content,
                content_type=rendered_mime,
            )
        presigned = await self.storage.presign_download(
            bucket=self.settings.s3_bucket,
            storage_key=storage_key,
            filename=rendered_name,
            expires_in_seconds=self.settings.download_presign_expires_seconds,
        )
        updated_share = (
            await self.repository.get_share(
                tenant_id=current_user.tenant_id,
                share_id=share.id,
            )
            or share
        )
        await self.repository.add_access_log(
            tenant_id=share.tenant_id,
            share_id=share.id,
            actor_id=current_user.id,
            actor_type="user",
            action="download",
            result="allowed",
            ip=(audit_context or AuditContext()).ip,
            user_agent=(audit_context or AuditContext()).user_agent,
            bytes_sent=response_size,
        )
        await self._record(
            current_user=current_user,
            share=share,
            action="share.internal.downloaded",
            resource_id=node.id,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "version_id": str(version.id),
                "blob_id": str(blob.id),
                "delivery_mode": delivery_mode,
                "size_bytes": response_size,
                **(decision.audit_metadata() if decision is not None else {}),
            },
            resource_type="node",
        )
        await self.repository.commit()
        return InternalShareDownloadResponse(
            share_id=share.id,
            node_id=node.id,
            version_id=version.id,
            file_name=rendered_name,
            size_bytes=response_size,
            mime_type=rendered_mime,
            download_url=presigned.download_url,
            expires_at=presigned.expires_at,
            headers=presigned.headers,
            download_count=updated_share.download_count,
        )

    async def list_notifications(
        self,
        *,
        current_user: User,
        unread_only: bool,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext | None,
    ) -> ShareNotificationListResponse:
        await self.recipient_grant_service.reconcile_user(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
        )
        await self.repository.commit()
        rows = await self.repository.list_notifications(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            unread_only=unread_only,
            cursor=decode_page_cursor(self.settings, cursor),
            limit=page_size + 1,
        )
        page = rows[:page_size]
        response = ShareNotificationListResponse(
            items=[
                ShareNotificationItem(
                    id=notification.id,
                    notification_type=notification.notification_type,
                    share_id=share.id,
                    root_node_id=root_node.id,
                    root_name=root_node.name,
                    created_by=creator.id,
                    creator_name=creator.display_name,
                    is_read=notification.is_read,
                    read_at=notification.read_at,
                    invalidated_at=notification.invalidated_at,
                    created_at=notification.created_at,
                )
                for notification, share, creator, root_node in page
            ],
            next_cursor=_next_notification_cursor(self.settings, rows, page_size),
        )
        await self._record(
            current_user=current_user,
            share=None,
            action="share.notifications.listed",
            resource_id=current_user.id,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "unread_only": unread_only,
                "returned_count": len(response.items),
                "has_next": response.next_cursor is not None,
            },
            resource_type="notification",
        )
        await self.repository.commit()
        return response

    async def mark_notification_read(
        self,
        *,
        current_user: User,
        notification_id: UUID,
        audit_context: AuditContext | None,
    ) -> ShareNotificationReadResponse:
        notification = await self.repository.mark_notification_read(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            notification_id=notification_id,
        )
        if notification is None:
            raise ApiError("NOTIFICATION_NOT_FOUND", "通知不存在", status_code=404)
        await self._record(
            current_user=current_user,
            share=None,
            action="share.notification.read",
            resource_id=notification.id,
            result="allowed",
            audit_context=audit_context,
            metadata={"share_id": str(notification.share_id)},
            resource_type="notification",
        )
        await self.repository.commit()
        assert notification.read_at is not None
        return ShareNotificationReadResponse(
            notification_id=notification.id,
            read_at=notification.read_at,
        )

    async def record_denied_request(
        self,
        *,
        current_user: User,
        share_id: UUID,
        action: str,
        error: ApiError,
        audit_context: AuditContext | None,
        node_id: UUID | None = None,
    ) -> None:
        share = await self.repository.get_share(
            tenant_id=current_user.tenant_id,
            share_id=share_id,
        )
        if share is not None:
            access_action = {
                "accessed": "view",
                "downloaded": "download",
            }.get(action, action)
            await self.repository.add_access_log(
                tenant_id=current_user.tenant_id,
                share_id=share.id,
                actor_id=current_user.id,
                actor_type="user",
                action=access_action,
                result="denied",
                ip=(audit_context or AuditContext()).ip,
                user_agent=(audit_context or AuditContext()).user_agent,
            )
        await self._record(
            current_user=current_user,
            share=share,
            action=f"share.internal.{action}",
            resource_id=node_id or share_id,
            result="denied",
            audit_context=audit_context,
            metadata={"reason": error.code.lower()},
            resource_type="node" if node_id is not None else "share",
        )
        await self.repository.commit()

    async def _get_internal_share(self, *, current_user: User, share_id: UUID) -> Share:
        share = await self.repository.get_share(
            tenant_id=current_user.tenant_id,
            share_id=share_id,
        )
        if share is None or share.share_type != SHARE_TYPE_INTERNAL:
            raise ApiError("SHARE_NOT_FOUND", "分享不存在或无权访问", status_code=404)
        if share.created_by != current_user.id:
            error = _share_access_error(share)
            if error is not None:
                raise error
        return share

    async def _require_current_recipient(self, *, current_user: User, share: Share) -> None:
        is_current = await self.recipient_grant_service.user_is_current_recipient(
            share=share,
            user_id=current_user.id,
        )
        has_grant = await self.repository.has_active_recipient_grant(
            tenant_id=current_user.tenant_id,
            share_id=share.id,
            user_id=current_user.id,
        )
        if is_current != has_grant:
            await self.recipient_grant_service.reconcile_share(
                tenant_id=current_user.tenant_id,
                share_id=share.id,
            )
            await self.repository.commit()
        if not is_current:
            raise ApiError("SHARE_NOT_FOUND", "分享不存在或无权访问", status_code=404)

    async def _get_creator(self, share: Share) -> User:
        creator = await self.auth_repository.get_user_by_id(
            tenant_id=share.tenant_id,
            user_id=share.created_by,
        )
        if creator is None or not creator.is_active:
            raise ApiError(
                "SHARE_SOURCE_PERMISSION_REVOKED",
                "分享创建者已不可用",
                status_code=410,
            )
        return creator

    async def _get_active_share_node(self, *, share: Share, node_id: UUID) -> Node:
        node = await self.file_repository.get_node_by_id(
            tenant_id=share.tenant_id,
            node_id=node_id,
        )
        if node is None or node.is_deleted:
            raise ApiError("SHARE_ITEM_NOT_FOUND", "分享文件不存在", status_code=404)
        root_node = await self.file_repository.get_node_by_id(
            tenant_id=share.tenant_id,
            node_id=share.root_node_id,
        )
        if root_node is None or root_node.is_deleted or node.space_id != root_node.space_id:
            raise ApiError("SHARE_ITEM_NOT_FOUND", "分享文件不存在", status_code=404)
        return node

    async def _ensure_creator_can_share(
        self,
        *,
        share: Share,
        creator: User,
        node: Node,
    ) -> None:
        node_path_ids = await self.file_repository.get_node_path_ids(
            tenant_id=share.tenant_id,
            space_id=node.space_id,
            node_id=node.id,
        )
        allowed = node_path_ids is not None and await self.permission_service.can_access_node(
            tenant_id=share.tenant_id,
            user_id=creator.id,
            space_id=node.space_id,
            action=ACTION_SHARE,
            node_path_ids=node_path_ids,
        )
        if not allowed:
            raise ApiError(
                "SHARE_SOURCE_PERMISSION_REVOKED",
                "分享来源权限已失效",
                status_code=410,
            )

    async def _ensure_delivery_allowed(
        self,
        *,
        share: Share,
        node: Node,
        version: FileVersion,
        blob: FileBlob,
        delivery_mode: DeliveryMode,
    ) -> FileSecurityDecision | None:
        if self.security_service is None:
            return None
        decision = await self.security_service.evaluate(
            tenant_id=share.tenant_id,
            file_name=node.name,
            mime_type=version.mime_type or blob.mime_type,
            version=version,
        )
        self.security_service.ensure_delivery(
            decision=decision,
            requested_mode=delivery_mode,
        )
        return decision

    async def _record(
        self,
        *,
        current_user: User,
        share: Share | None,
        action: str,
        resource_id: UUID,
        result: str,
        audit_context: AuditContext | None,
        metadata: dict[str, object],
        resource_type: str | None = None,
    ) -> None:
        if self.audit_service is None:
            return
        await self.audit_service.record(
            event=AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action=action,
                resource_type=resource_type or ("share" if share is not None else "notification"),
                resource_id=resource_id,
                result=result,
                metadata={
                    **({"share_id": str(share.id)} if share is not None else {}),
                    **metadata,
                },
            ),
            context=audit_context or AuditContext(),
        )


def _share_list_item(*, share: Share, creator: User, root_node: Node) -> ShareListItem:
    effective_status = _effective_status(share)
    return ShareListItem(
        id=share.id,
        share_type=share.share_type,
        root_node_id=share.root_node_id,
        root_name=root_node.name,
        root_node_type=root_node.node_type,
        permission=share.permission,
        status=effective_status,
        created_by=share.created_by,
        creator_name=creator.display_name,
        expires_at=share.expires_at,
        max_views=share.max_views,
        max_downloads=share.max_downloads,
        view_count=share.view_count,
        download_count=share.download_count,
        created_at=share.created_at,
        available=effective_status == SHARE_STATUS_ACTIVE,
    )


def _effective_status(share: Share) -> str:
    if (
        share.status == SHARE_STATUS_ACTIVE
        and share.expires_at is not None
        and ensure_utc(share.expires_at) <= utc_now()
    ):
        return SHARE_STATUS_EXPIRED
    return share.status


def _share_access_error(
    share: Share,
    *,
    view: bool = False,
    download: bool = False,
) -> ApiError | None:
    if share.status == SHARE_STATUS_REVOKED:
        return ApiError("SHARE_REVOKED", "分享已撤销", status_code=410)
    if share.status in {SHARE_STATUS_DISABLED, SHARE_STATUS_EXPIRED}:
        return ApiError("SHARE_EXPIRED", "分享不可用或已过期", status_code=410)
    if share.status != SHARE_STATUS_ACTIVE:
        return ApiError("SHARE_REVOKED", "分享不可用", status_code=410)
    if share.expires_at is not None and ensure_utc(share.expires_at) <= utc_now():
        return ApiError("SHARE_EXPIRED", "分享已过期", status_code=410)
    if view and share.max_views is not None and share.view_count >= share.max_views:
        return ApiError("SHARE_VIEW_LIMIT_EXCEEDED", "分享访问次数已用尽", status_code=410)
    if download and share.max_downloads is not None and share.download_count >= share.max_downloads:
        return ApiError(
            "SHARE_DOWNLOAD_LIMIT_EXCEEDED",
            "分享下载次数已用尽",
            status_code=410,
        )
    return None


def _next_share_cursor(
    settings: Settings,
    rows: list[tuple[Share, User, Node]],
    page_size: int,
) -> str | None:
    if len(rows) <= page_size:
        return None
    share = rows[page_size - 1][0]
    return encode_page_cursor(settings, created_at=share.created_at, item_id=share.id)


def _next_notification_cursor(
    settings: Settings,
    rows: list[tuple[ShareNotification, Share, User, Node]],
    page_size: int,
) -> str | None:
    if len(rows) <= page_size:
        return None
    notification = rows[page_size - 1][0]
    return encode_page_cursor(
        settings,
        created_at=notification.created_at,
        item_id=notification.id,
    )


def _internal_watermark_key(
    *,
    tenant_id: UUID,
    share_id: UUID,
    user_id: UUID,
    node_id: UUID,
    version_id: UUID,
) -> str:
    return (
        f"derived/internal-share-watermarks/{tenant_id}/{share_id}/"
        f"{user_id}/{node_id}/{version_id}/watermark"
    )
