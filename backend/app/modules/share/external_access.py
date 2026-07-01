from __future__ import annotations

from uuid import UUID

from app.api.errors import ApiError
from app.core.security import ensure_utc, hash_token, utc_now, verify_password
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.share.constants import (
    SHARE_STATUS_ACTIVE,
    SHARE_STATUS_DISABLED,
    SHARE_STATUS_EXPIRED,
    SHARE_STATUS_REVOKED,
)
from app.modules.share.models import Share
from app.modules.share.repository import ShareRepository
from app.modules.share.schemas import ExternalShareAccessResponse


class ShareExternalAccessService:
    def __init__(
        self,
        *,
        repository: ShareRepository,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service

    async def access_external_share(
        self,
        *,
        tenant_id: UUID,
        raw_token: str,
        passcode: str | None = None,
        audit_context: AuditContext | None = None,
    ) -> ExternalShareAccessResponse:
        share = await self.repository.get_external_share_by_token_hash(
            tenant_id=tenant_id,
            token_hash=hash_token(raw_token),
        )
        if share is None:
            raise ApiError("SHARE_NOT_FOUND", "分享不存在", status_code=404)

        try:
            access_error = self._external_access_error(share=share, passcode=passcode)
            if access_error is not None:
                await self._record_external_access(
                    share=share,
                    result="denied",
                    audit_context=audit_context,
                )
                await self.repository.commit()
                raise access_error

            consumed = await self.repository.consume_external_view(
                tenant_id=share.tenant_id,
                share_id=share.id,
            )
            if not consumed:
                refreshed_share = await self.repository.get_share(
                    tenant_id=share.tenant_id,
                    share_id=share.id,
                )
                await self._record_external_access(
                    share=refreshed_share or share,
                    result="denied",
                    audit_context=audit_context,
                )
                await self.repository.commit()
                raise self._external_access_error(
                    share=refreshed_share or share,
                    passcode=passcode,
                ) or ApiError(
                    "SHARE_VIEW_LIMIT_EXCEEDED",
                    "分享访问次数已用尽",
                    status_code=410,
                )

            share = await self.repository.get_share(
                tenant_id=share.tenant_id,
                share_id=share.id,
            )
            if share is None:
                raise ApiError("SHARE_NOT_FOUND", "分享不存在", status_code=404)
            items = await self.repository.list_items(
                tenant_id=share.tenant_id,
                share_id=share.id,
            )
            await self._record_external_access(
                share=share,
                result="allowed",
                audit_context=audit_context,
            )
            await self.repository.commit()
            return ExternalShareAccessResponse(
                share_id=share.id,
                root_node_id=share.root_node_id,
                permission=share.permission,
                expires_at=share.expires_at,
                max_views=share.max_views,
                max_downloads=share.max_downloads,
                view_count=share.view_count,
                download_count=share.download_count,
                item_node_ids=[item.node_id for item in items],
            )
        except ApiError:
            raise
        except Exception:
            await self.repository.rollback()
            raise

    def _external_access_error(self, *, share: Share, passcode: str | None) -> ApiError | None:
        if share.status == SHARE_STATUS_REVOKED:
            return ApiError("SHARE_REVOKED", "分享已撤销", status_code=410)
        if share.status in {SHARE_STATUS_DISABLED, SHARE_STATUS_EXPIRED}:
            return ApiError("SHARE_EXPIRED", "分享不可用或已过期", status_code=410)
        if share.status != SHARE_STATUS_ACTIVE:
            return ApiError("SHARE_REVOKED", "分享不可用", status_code=410)
        if share.expires_at is not None and ensure_utc(share.expires_at) <= utc_now():
            return ApiError("SHARE_EXPIRED", "分享已过期", status_code=410)
        if share.max_views is not None and share.view_count >= share.max_views:
            return ApiError("SHARE_VIEW_LIMIT_EXCEEDED", "分享访问次数已用尽", status_code=410)
        if share.passcode_hash is not None and (
            passcode is None or not verify_password(passcode, share.passcode_hash)
        ):
            return ApiError("SHARE_PASSCODE_INVALID", "提取码不正确", status_code=403)
        return None

    async def _record_external_access(
        self,
        *,
        share: Share,
        result: str,
        audit_context: AuditContext | None,
    ) -> None:
        context = audit_context or AuditContext()
        await self.repository.add_access_log(
            tenant_id=share.tenant_id,
            share_id=share.id,
            actor_id=None,
            actor_type="external",
            action="view",
            result=result,
            ip=context.ip,
            user_agent=context.user_agent,
        )
        if self.audit_service is None:
            return
        await self.audit_service.record(
            event=AuditEvent(
                tenant_id=share.tenant_id,
                actor_id=None,
                actor_type="external",
                action="share.external.accessed",
                resource_type="share",
                resource_id=share.id,
                result=result,
                metadata={
                    "share_type": share.share_type,
                    "permission": share.permission,
                    "root_node_id": str(share.root_node_id),
                },
            ),
            context=context,
        )
