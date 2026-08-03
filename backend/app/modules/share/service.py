from __future__ import annotations

import secrets
from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.api.errors import ApiError
from app.core.security import ensure_utc, hash_password, hash_token
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository
from app.modules.file.models import Node
from app.modules.file.repository import FileRepository
from app.modules.org.repository import OrgRepository
from app.modules.org.service import OrgService
from app.modules.permission.actions import ACTION_SHARE
from app.modules.permission.service import PermissionService
from app.modules.share.constants import (
    SHARE_PERMISSION_DOWNLOAD,
    SHARE_PERMISSIONS,
    SHARE_RECIPIENT_TYPES,
    SHARE_TYPE_EXTERNAL,
    SHARE_TYPE_INTERNAL,
    SHARE_TYPES,
)
from app.modules.share.models import Share
from app.modules.share.recipient_grants import ShareRecipientGrantService
from app.modules.share.repository import ShareRepository
from app.modules.share.schemas import (
    CreateShareResult,
    ShareDetail,
    ShareRecipientInput,
)


class ShareService:
    def __init__(
        self,
        *,
        repository: ShareRepository,
        file_repository: FileRepository,
        permission_service: PermissionService,
        audit_service: AuditService | None = None,
        recipient_grant_service: ShareRecipientGrantService | None = None,
    ) -> None:
        self.repository = repository
        self.file_repository = file_repository
        self.permission_service = permission_service
        self.audit_service = audit_service
        self.recipient_grant_service = recipient_grant_service or ShareRecipientGrantService(
            repository=repository,
            auth_repository=AuthRepository(repository.session),
            org_service=OrgService(repository=OrgRepository(repository.session)),
        )

    async def create_share(
        self,
        *,
        current_user: User,
        share_type: str,
        root_node_id: UUID,
        permission: str = SHARE_PERMISSION_DOWNLOAD,
        item_node_ids: list[UUID] | None = None,
        recipients: list[ShareRecipientInput] | None = None,
        passcode: str | None = None,
        expires_at: datetime | None = None,
        max_views: int | None = None,
        max_downloads: int | None = None,
        audit_context: AuditContext | None = None,
    ) -> CreateShareResult:
        self._validate_create_request(
            share_type=share_type,
            permission=permission,
            recipients=recipients or [],
            max_views=max_views,
            max_downloads=max_downloads,
        )
        for recipient in recipients or []:
            try:
                await self.recipient_grant_service.validate_recipient(
                    tenant_id=current_user.tenant_id,
                    subject_type=recipient.subject_type,
                    subject_id=recipient.subject_id,
                )
            except ValueError as exc:
                raise ApiError(
                    "SHARE_RECIPIENT_NOT_FOUND",
                    "分享接收人不存在或不可用",
                    status_code=404,
                ) from exc
        root_node = await self.file_repository.get_node_by_id(
            tenant_id=current_user.tenant_id,
            node_id=root_node_id,
        )
        if root_node is None:
            raise ApiError("NODE_NOT_FOUND", "文件不存在或无权访问", status_code=404)
        await self._ensure_node_shareable(
            current_user=current_user,
            node=root_node,
            expected_space_id=root_node.space_id,
        )
        item_ids = _unique_node_ids([root_node_id, *(item_node_ids or [])])
        for item_node_id in item_ids:
            if item_node_id == root_node_id:
                continue
            item_node = await self.file_repository.get_node_by_id(
                tenant_id=current_user.tenant_id,
                node_id=item_node_id,
            )
            if item_node is None:
                raise ApiError("NODE_NOT_FOUND", "文件不存在或无权访问", status_code=404)
            await self._ensure_node_shareable(
                current_user=current_user,
                node=item_node,
                expected_space_id=root_node.space_id,
            )

        normalized_expires_at = ensure_utc(expires_at) if expires_at is not None else None
        raw_token = secrets.token_urlsafe(32) if share_type == SHARE_TYPE_EXTERNAL else None
        token_hash = hash_token(raw_token) if raw_token is not None else None
        passcode_hash = hash_password(passcode) if passcode else None

        try:
            share = await self.repository.create_share(
                tenant_id=current_user.tenant_id,
                share_type=share_type,
                created_by=current_user.id,
                root_node_id=root_node_id,
                permission=permission,
                token_hash=token_hash,
                passcode_hash=passcode_hash,
                expires_at=normalized_expires_at,
                max_views=max_views,
                max_downloads=max_downloads,
            )
            for node_id in item_ids:
                await self.repository.add_item(
                    tenant_id=current_user.tenant_id,
                    share_id=share.id,
                    node_id=node_id,
                )
            for recipient in recipients or []:
                await self.repository.add_recipient(
                    tenant_id=current_user.tenant_id,
                    share_id=share.id,
                    subject_type=recipient.subject_type,
                    subject_id=recipient.subject_id,
                )
            if share_type == SHARE_TYPE_INTERNAL:
                await self.recipient_grant_service.reconcile_share(
                    tenant_id=current_user.tenant_id,
                    share_id=share.id,
                )
            await self._record_share_created(
                current_user=current_user,
                share=share,
                item_count=len(item_ids),
                recipient_count=len(recipients or []),
                audit_context=audit_context,
            )
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise ApiError("SHARE_CONFLICT", "分享数据冲突", status_code=409) from exc
        except Exception:
            await self.repository.rollback()
            raise

        return CreateShareResult(
            id=share.id,
            share_type=share.share_type,
            root_node_id=share.root_node_id,
            permission=share.permission,
            status=share.status,
            expires_at=share.expires_at,
            max_views=share.max_views,
            max_downloads=share.max_downloads,
            raw_token=raw_token,
        )

    async def _ensure_node_shareable(
        self,
        *,
        current_user: User,
        node: Node,
        expected_space_id: UUID,
    ) -> None:
        if node.space_id != expected_space_id:
            raise ApiError("NODE_NOT_FOUND", "文件不存在或无权访问", status_code=404)
        node_path_ids = await self.file_repository.get_node_path_ids(
            tenant_id=current_user.tenant_id,
            space_id=node.space_id,
            node_id=node.id,
        )
        if node_path_ids is None:
            raise ApiError("NODE_NOT_FOUND", "文件不存在或无权访问", status_code=404)
        if not await self.permission_service.can_access_node(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            space_id=node.space_id,
            action=ACTION_SHARE,
            node_path_ids=node_path_ids,
        ):
            raise ApiError("NODE_NOT_FOUND", "文件不存在或无权访问", status_code=404)

    async def revoke_share(
        self,
        *,
        current_user: User,
        share_id: UUID,
        audit_context: AuditContext | None = None,
    ) -> None:
        share = await self.repository.get_share(
            tenant_id=current_user.tenant_id,
            share_id=share_id,
        )
        if share is None or share.created_by != current_user.id:
            raise ApiError("SHARE_NOT_FOUND", "分享不存在或无权访问", status_code=404)
        try:
            revoked = await self.repository.revoke_share(
                tenant_id=current_user.tenant_id,
                share_id=share_id,
                revoked_by=current_user.id,
            )
            if not revoked:
                raise ApiError("SHARE_NOT_ACTIVE", "分享不是可撤销状态", status_code=409)
            await self.recipient_grant_service.reconcile_share(
                tenant_id=current_user.tenant_id,
                share_id=share_id,
            )
            await self._record_share_revoked(
                current_user=current_user,
                share_id=share_id,
                audit_context=audit_context,
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise

    async def get_share_detail(self, *, current_user: User, share_id: UUID) -> ShareDetail:
        share = await self.repository.get_share(
            tenant_id=current_user.tenant_id,
            share_id=share_id,
        )
        if share is None or share.created_by != current_user.id:
            raise ApiError("SHARE_NOT_FOUND", "分享不存在或无权访问", status_code=404)
        return ShareDetail.model_validate(share)

    def _validate_create_request(
        self,
        *,
        share_type: str,
        permission: str,
        recipients: list[ShareRecipientInput],
        max_views: int | None,
        max_downloads: int | None,
    ) -> None:
        if share_type not in SHARE_TYPES:
            raise ApiError("SHARE_TYPE_INVALID", "分享类型不支持", status_code=422)
        if permission not in SHARE_PERMISSIONS:
            raise ApiError("SHARE_PERMISSION_INVALID", "分享权限不支持", status_code=422)
        if max_views is not None and max_views <= 0:
            raise ApiError("SHARE_LIMIT_INVALID", "访问次数限制必须大于 0", status_code=422)
        if max_downloads is not None and max_downloads <= 0:
            raise ApiError("SHARE_LIMIT_INVALID", "下载次数限制必须大于 0", status_code=422)
        if share_type == SHARE_TYPE_INTERNAL and not recipients:
            raise ApiError("SHARE_RECIPIENT_REQUIRED", "内部分享必须指定接收人", status_code=422)
        if share_type == SHARE_TYPE_EXTERNAL and recipients:
            raise ApiError("SHARE_RECIPIENT_INVALID", "外链分享不能指定内部接收人", status_code=422)
        for recipient in recipients:
            if recipient.subject_type not in SHARE_RECIPIENT_TYPES:
                raise ApiError("SHARE_RECIPIENT_INVALID", "分享接收人类型不支持", status_code=422)

    async def _record_share_created(
        self,
        *,
        current_user: User,
        share: Share,
        item_count: int,
        recipient_count: int,
        audit_context: AuditContext | None,
    ) -> None:
        if self.audit_service is None:
            return
        await self.audit_service.record(
            event=AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action="share.created",
                resource_type="share",
                resource_id=share.id,
                result="allowed",
                metadata={
                    "share_type": share.share_type,
                    "root_node_id": str(share.root_node_id),
                    "permission": share.permission,
                    "item_count": item_count,
                    "recipient_count": recipient_count,
                    "has_passcode": share.passcode_hash is not None,
                    "max_views": share.max_views,
                    "max_downloads": share.max_downloads,
                },
            ),
            context=audit_context or AuditContext(),
        )

    async def _record_share_revoked(
        self,
        *,
        current_user: User,
        share_id: UUID,
        audit_context: AuditContext | None,
    ) -> None:
        if self.audit_service is None:
            return
        await self.audit_service.record(
            event=AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action="share.revoked",
                resource_type="share",
                resource_id=share_id,
                result="allowed",
                metadata={},
            ),
            context=audit_context or AuditContext(),
        )


def _unique_node_ids(node_ids: list[UUID]) -> list[UUID]:
    seen: set[UUID] = set()
    result: list[UUID] = []
    for node_id in node_ids:
        if node_id in seen:
            continue
        seen.add(node_id)
        result.append(node_id)
    return result
