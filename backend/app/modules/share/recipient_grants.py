from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.core.security import ensure_utc, utc_now
from app.modules.auth.repository import AuthRepository
from app.modules.org.service import OrgService
from app.modules.share.constants import (
    SHARE_RECIPIENT_DEPARTMENT,
    SHARE_RECIPIENT_GROUP,
    SHARE_RECIPIENT_USER,
    SHARE_STATUS_ACTIVE,
    SHARE_TYPE_INTERNAL,
)
from app.modules.share.models import Share, ShareRecipient
from app.modules.share.repository import ShareRepository

SHARE_NOTIFICATION_RECEIVED = "share_received"


@dataclass(frozen=True)
class RecipientReconciliationResult:
    share_id: UUID
    desired_users: int
    activated: int
    deactivated: int


class ShareRecipientGrantService:
    def __init__(
        self,
        *,
        repository: ShareRepository,
        auth_repository: AuthRepository,
        org_service: OrgService,
    ) -> None:
        self.repository = repository
        self.auth_repository = auth_repository
        self.org_service = org_service

    async def validate_recipient(
        self,
        *,
        tenant_id: UUID,
        subject_type: str,
        subject_id: UUID,
    ) -> None:
        if subject_type == SHARE_RECIPIENT_USER:
            user = await self.auth_repository.get_user_by_id(
                tenant_id=tenant_id,
                user_id=subject_id,
            )
            if user is None or not user.is_active:
                raise ValueError("recipient_user_not_found")
            return
        if subject_type == SHARE_RECIPIENT_DEPARTMENT:
            if (
                await self.org_service.get_active_department(
                    tenant_id=tenant_id,
                    department_id=subject_id,
                )
                is None
            ):
                raise ValueError("recipient_department_not_found")
            return
        if subject_type == SHARE_RECIPIENT_GROUP:
            if (
                await self.org_service.get_active_user_group(
                    tenant_id=tenant_id,
                    group_id=subject_id,
                )
                is None
            ):
                raise ValueError("recipient_group_not_found")
            return
        raise ValueError("recipient_type_invalid")

    async def reconcile_share(
        self,
        *,
        tenant_id: UUID,
        share_id: UUID,
    ) -> RecipientReconciliationResult:
        share = await self.repository.get_share(tenant_id=tenant_id, share_id=share_id)
        if share is None or share.share_type != SHARE_TYPE_INTERNAL:
            return RecipientReconciliationResult(
                share_id=share_id,
                desired_users=0,
                activated=0,
                deactivated=0,
            )
        recipients = await self.repository.list_recipients(
            tenant_id=tenant_id,
            share_id=share_id,
        )
        desired_user_ids = (
            await self._resolve_user_ids(tenant_id=tenant_id, recipients=recipients)
            if _share_is_available(share)
            else set()
        )
        grants = {
            grant.user_id: grant
            for grant in await self.repository.list_recipient_grants(
                tenant_id=tenant_id,
                share_id=share_id,
            )
        }
        activated = 0
        deactivated = 0
        now = utc_now()
        for user_id in sorted(desired_user_ids, key=str):
            grant = grants.get(user_id)
            if grant is None or not grant.is_active:
                await self.repository.activate_recipient_grant(
                    tenant_id=tenant_id,
                    share_id=share_id,
                    user_id=user_id,
                    now=now,
                )
                activated += 1
            await self.repository.activate_share_notification(
                tenant_id=tenant_id,
                share_id=share_id,
                user_id=user_id,
                notification_type=SHARE_NOTIFICATION_RECEIVED,
                now=now,
            )
        for user_id, grant in grants.items():
            if not grant.is_active or user_id in desired_user_ids:
                continue
            await self.repository.deactivate_recipient_grant(
                tenant_id=tenant_id,
                share_id=share_id,
                user_id=user_id,
                now=now,
            )
            await self.repository.invalidate_share_notification(
                tenant_id=tenant_id,
                share_id=share_id,
                user_id=user_id,
                notification_type=SHARE_NOTIFICATION_RECEIVED,
                now=now,
            )
            deactivated += 1
        return RecipientReconciliationResult(
            share_id=share_id,
            desired_users=len(desired_user_ids),
            activated=activated,
            deactivated=deactivated,
        )

    async def reconcile_subject(
        self,
        *,
        tenant_id: UUID,
        subject_type: str,
        subject_id: UUID,
    ) -> list[RecipientReconciliationResult]:
        share_ids = await self.repository.list_internal_share_ids_for_subject(
            tenant_id=tenant_id,
            subject_type=subject_type,
            subject_id=subject_id,
        )
        return [
            await self.reconcile_share(tenant_id=tenant_id, share_id=share_id)
            for share_id in share_ids
        ]

    async def reconcile_user(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
    ) -> list[RecipientReconciliationResult]:
        share_ids = await self.repository.list_internal_share_ids_related_to_user(
            tenant_id=tenant_id,
            user_id=user_id,
        )
        return [
            await self.reconcile_share(tenant_id=tenant_id, share_id=share_id)
            for share_id in share_ids
        ]

    async def user_is_current_recipient(
        self,
        *,
        share: Share,
        user_id: UUID,
    ) -> bool:
        if not _share_is_available(share):
            return False
        recipients = await self.repository.list_recipients(
            tenant_id=share.tenant_id,
            share_id=share.id,
        )
        desired_user_ids = await self._resolve_user_ids(
            tenant_id=share.tenant_id,
            recipients=recipients,
        )
        return user_id in desired_user_ids

    async def _resolve_user_ids(
        self,
        *,
        tenant_id: UUID,
        recipients: list[ShareRecipient],
    ) -> set[UUID]:
        user_ids: set[UUID] = set()
        for recipient in recipients:
            if recipient.subject_type == SHARE_RECIPIENT_USER:
                user = await self.auth_repository.get_user_by_id(
                    tenant_id=tenant_id,
                    user_id=recipient.subject_id,
                )
                if user is not None and user.is_active:
                    user_ids.add(user.id)
                continue
            if recipient.subject_type == SHARE_RECIPIENT_DEPARTMENT:
                user_ids.update(
                    await self.org_service.list_active_department_member_user_ids(
                        tenant_id=tenant_id,
                        department_id=recipient.subject_id,
                    )
                )
                continue
            if recipient.subject_type == SHARE_RECIPIENT_GROUP:
                user_ids.update(
                    await self.org_service.list_active_group_member_user_ids(
                        tenant_id=tenant_id,
                        group_id=recipient.subject_id,
                    )
                )
        return user_ids


def _share_is_available(share: Share) -> bool:
    if share.status != SHARE_STATUS_ACTIVE:
        return False
    return share.expires_at is None or ensure_utc(share.expires_at) > utc_now()
