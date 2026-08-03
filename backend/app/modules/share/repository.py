from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PageCursor
from app.core.security import utc_now
from app.modules.auth.models import User
from app.modules.file.models import FileBlob, FileVersion, Node
from app.modules.org.models import DepartmentMember, UserGroupMember
from app.modules.share.models import (
    Share,
    ShareAccessLog,
    ShareItem,
    ShareNotification,
    ShareRecipient,
    ShareRecipientGrant,
)


class ShareRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_share(
        self,
        *,
        tenant_id: UUID,
        share_type: str,
        created_by: UUID,
        root_node_id: UUID,
        permission: str,
        token_hash: str | None = None,
        passcode_hash: str | None = None,
        expires_at: datetime | None = None,
        max_views: int | None = None,
        max_downloads: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Share:
        share = Share(
            tenant_id=tenant_id,
            share_type=share_type,
            token_hash=token_hash,
            passcode_hash=passcode_hash,
            created_by=created_by,
            root_node_id=root_node_id,
            permission=permission,
            expires_at=expires_at,
            max_views=max_views,
            max_downloads=max_downloads,
            metadata_json=metadata or {},
        )
        self.session.add(share)
        await self.session.flush()
        return share

    async def add_item(self, *, tenant_id: UUID, share_id: UUID, node_id: UUID) -> ShareItem:
        item = ShareItem(tenant_id=tenant_id, share_id=share_id, node_id=node_id)
        self.session.add(item)
        await self.session.flush()
        return item

    async def add_recipient(
        self,
        *,
        tenant_id: UUID,
        share_id: UUID,
        subject_type: str,
        subject_id: UUID,
    ) -> ShareRecipient:
        recipient = ShareRecipient(
            tenant_id=tenant_id,
            share_id=share_id,
            subject_type=subject_type,
            subject_id=subject_id,
        )
        self.session.add(recipient)
        await self.session.flush()
        return recipient

    async def get_share(self, *, tenant_id: UUID, share_id: UUID) -> Share | None:
        result = await self.session.execute(
            select(Share).where(Share.tenant_id == tenant_id, Share.id == share_id)
        )
        return result.scalar_one_or_none()

    async def get_external_share_by_token_hash(
        self,
        *,
        tenant_id: UUID,
        token_hash: str,
    ) -> Share | None:
        result = await self.session.execute(
            select(Share).where(
                Share.tenant_id == tenant_id,
                Share.share_type == "external",
                Share.token_hash == token_hash,
            )
        )
        return result.scalar_one_or_none()

    async def consume_external_view(self, *, tenant_id: UUID, share_id: UUID) -> bool:
        now = utc_now()
        result = await self.session.execute(
            update(Share)
            .where(
                Share.tenant_id == tenant_id,
                Share.id == share_id,
                Share.share_type == "external",
                Share.status == "active",
                or_(Share.expires_at.is_(None), Share.expires_at > now),
                or_(Share.max_views.is_(None), Share.view_count < Share.max_views),
            )
            .values(view_count=Share.view_count + 1)
            .returning(Share.id)
        )
        return result.scalar_one_or_none() is not None

    async def consume_external_download(self, *, tenant_id: UUID, share_id: UUID) -> bool:
        now = utc_now()
        result = await self.session.execute(
            update(Share)
            .where(
                Share.tenant_id == tenant_id,
                Share.id == share_id,
                Share.share_type == "external",
                Share.status == "active",
                or_(Share.expires_at.is_(None), Share.expires_at > now),
                or_(Share.max_downloads.is_(None), Share.download_count < Share.max_downloads),
            )
            .values(download_count=Share.download_count + 1)
            .returning(Share.id)
        )
        return result.scalar_one_or_none() is not None

    async def has_item(self, *, tenant_id: UUID, share_id: UUID, node_id: UUID) -> bool:
        result = await self.session.execute(
            select(ShareItem.id).where(
                ShareItem.tenant_id == tenant_id,
                ShareItem.share_id == share_id,
                ShareItem.node_id == node_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def list_items(self, *, tenant_id: UUID, share_id: UUID) -> list[ShareItem]:
        result = await self.session.execute(
            select(ShareItem).where(
                ShareItem.tenant_id == tenant_id,
                ShareItem.share_id == share_id,
            )
        )
        return list(result.scalars().all())

    async def list_recipients(self, *, tenant_id: UUID, share_id: UUID) -> list[ShareRecipient]:
        result = await self.session.execute(
            select(ShareRecipient).where(
                ShareRecipient.tenant_id == tenant_id,
                ShareRecipient.share_id == share_id,
            )
        )
        return list(result.scalars().all())

    async def list_recipient_grants(
        self,
        *,
        tenant_id: UUID,
        share_id: UUID,
    ) -> list[ShareRecipientGrant]:
        result = await self.session.execute(
            select(ShareRecipientGrant).where(
                ShareRecipientGrant.tenant_id == tenant_id,
                ShareRecipientGrant.share_id == share_id,
            )
        )
        return list(result.scalars().all())

    async def activate_recipient_grant(
        self,
        *,
        tenant_id: UUID,
        share_id: UUID,
        user_id: UUID,
        now: datetime,
    ) -> ShareRecipientGrant:
        result = await self.session.execute(
            select(ShareRecipientGrant).where(
                ShareRecipientGrant.tenant_id == tenant_id,
                ShareRecipientGrant.share_id == share_id,
                ShareRecipientGrant.user_id == user_id,
            )
        )
        grant = result.scalar_one_or_none()
        if grant is None:
            grant = ShareRecipientGrant(
                tenant_id=tenant_id,
                share_id=share_id,
                user_id=user_id,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            self.session.add(grant)
        else:
            grant.is_active = True
            grant.revoked_at = None
            grant.updated_at = now
        await self.session.flush()
        return grant

    async def deactivate_recipient_grant(
        self,
        *,
        tenant_id: UUID,
        share_id: UUID,
        user_id: UUID,
        now: datetime,
    ) -> None:
        await self.session.execute(
            update(ShareRecipientGrant)
            .where(
                ShareRecipientGrant.tenant_id == tenant_id,
                ShareRecipientGrant.share_id == share_id,
                ShareRecipientGrant.user_id == user_id,
                ShareRecipientGrant.is_active.is_(True),
            )
            .values(is_active=False, revoked_at=now, updated_at=now)
        )

    async def has_active_recipient_grant(
        self,
        *,
        tenant_id: UUID,
        share_id: UUID,
        user_id: UUID,
    ) -> bool:
        result = await self.session.execute(
            select(ShareRecipientGrant.id).where(
                ShareRecipientGrant.tenant_id == tenant_id,
                ShareRecipientGrant.share_id == share_id,
                ShareRecipientGrant.user_id == user_id,
                ShareRecipientGrant.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none() is not None

    async def list_internal_share_ids_for_subject(
        self,
        *,
        tenant_id: UUID,
        subject_type: str,
        subject_id: UUID,
    ) -> list[UUID]:
        result = await self.session.execute(
            select(Share.id)
            .join(
                ShareRecipient,
                and_(
                    ShareRecipient.tenant_id == Share.tenant_id,
                    ShareRecipient.share_id == Share.id,
                ),
            )
            .where(
                Share.tenant_id == tenant_id,
                Share.share_type == "internal",
                ShareRecipient.subject_type == subject_type,
                ShareRecipient.subject_id == subject_id,
            )
            .order_by(Share.created_at, Share.id)
        )
        return list(result.scalars().all())

    async def list_internal_share_ids_related_to_user(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
    ) -> list[UUID]:
        department_ids = list(
            (
                await self.session.execute(
                    select(DepartmentMember.department_id).where(
                        DepartmentMember.tenant_id == tenant_id,
                        DepartmentMember.user_id == user_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        group_ids = list(
            (
                await self.session.execute(
                    select(UserGroupMember.group_id).where(
                        UserGroupMember.tenant_id == tenant_id,
                        UserGroupMember.user_id == user_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        subject_filters = [
            and_(
                ShareRecipient.subject_type == "user",
                ShareRecipient.subject_id == user_id,
            )
        ]
        if department_ids:
            subject_filters.append(
                and_(
                    ShareRecipient.subject_type == "department",
                    ShareRecipient.subject_id.in_(department_ids),
                )
            )
        if group_ids:
            subject_filters.append(
                and_(
                    ShareRecipient.subject_type == "group",
                    ShareRecipient.subject_id.in_(group_ids),
                )
            )
        result = await self.session.execute(
            select(Share.id)
            .join(
                ShareRecipient,
                and_(
                    ShareRecipient.tenant_id == Share.tenant_id,
                    ShareRecipient.share_id == Share.id,
                ),
            )
            .where(
                Share.tenant_id == tenant_id,
                Share.share_type == "internal",
                or_(*subject_filters),
            )
            .distinct()
            .order_by(Share.id)
        )
        share_ids = set(result.scalars().all())
        grant_result = await self.session.execute(
            select(ShareRecipientGrant.share_id).where(
                ShareRecipientGrant.tenant_id == tenant_id,
                ShareRecipientGrant.user_id == user_id,
            )
        )
        share_ids.update(grant_result.scalars().all())
        return sorted(share_ids, key=str)

    async def activate_share_notification(
        self,
        *,
        tenant_id: UUID,
        share_id: UUID,
        user_id: UUID,
        notification_type: str,
        now: datetime,
    ) -> ShareNotification:
        result = await self.session.execute(
            select(ShareNotification).where(
                ShareNotification.tenant_id == tenant_id,
                ShareNotification.share_id == share_id,
                ShareNotification.user_id == user_id,
                ShareNotification.notification_type == notification_type,
            )
        )
        notification = result.scalar_one_or_none()
        if notification is None:
            notification = ShareNotification(
                tenant_id=tenant_id,
                share_id=share_id,
                user_id=user_id,
                notification_type=notification_type,
                created_at=now,
                updated_at=now,
            )
            self.session.add(notification)
        elif notification.invalidated_at is not None:
            notification.is_read = False
            notification.read_at = None
            notification.invalidated_at = None
            notification.created_at = now
            notification.updated_at = now
        await self.session.flush()
        return notification

    async def invalidate_share_notification(
        self,
        *,
        tenant_id: UUID,
        share_id: UUID,
        user_id: UUID,
        notification_type: str,
        now: datetime,
    ) -> None:
        await self.session.execute(
            update(ShareNotification)
            .where(
                ShareNotification.tenant_id == tenant_id,
                ShareNotification.share_id == share_id,
                ShareNotification.user_id == user_id,
                ShareNotification.notification_type == notification_type,
                ShareNotification.invalidated_at.is_(None),
            )
            .values(invalidated_at=now, updated_at=now)
        )

    async def list_created_shares(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        cursor: PageCursor | None,
        limit: int,
    ) -> list[tuple[Share, User, Node]]:
        query = (
            select(Share, User, Node)
            .join(
                User,
                and_(User.tenant_id == Share.tenant_id, User.id == Share.created_by),
            )
            .join(
                Node,
                and_(Node.tenant_id == Share.tenant_id, Node.id == Share.root_node_id),
            )
            .where(
                Share.tenant_id == tenant_id,
                Share.created_by == user_id,
            )
        )
        if cursor is not None:
            query = query.where(
                or_(
                    Share.created_at < cursor.created_at,
                    and_(
                        Share.created_at == cursor.created_at,
                        Share.id < cursor.item_id,
                    ),
                )
            )
        result = await self.session.execute(
            query.order_by(Share.created_at.desc(), Share.id.desc()).limit(limit)
        )
        return [(row[0], row[1], row[2]) for row in result.all()]

    async def list_received_shares(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        cursor: PageCursor | None,
        limit: int,
    ) -> list[tuple[Share, User, Node]]:
        query = (
            select(Share, User, Node)
            .join(
                ShareRecipientGrant,
                and_(
                    ShareRecipientGrant.tenant_id == Share.tenant_id,
                    ShareRecipientGrant.share_id == Share.id,
                ),
            )
            .join(
                User,
                and_(User.tenant_id == Share.tenant_id, User.id == Share.created_by),
            )
            .join(
                Node,
                and_(Node.tenant_id == Share.tenant_id, Node.id == Share.root_node_id),
            )
            .where(
                Share.tenant_id == tenant_id,
                Share.share_type == "internal",
                ShareRecipientGrant.user_id == user_id,
                ShareRecipientGrant.is_active.is_(True),
            )
        )
        if cursor is not None:
            query = query.where(
                or_(
                    Share.created_at < cursor.created_at,
                    and_(
                        Share.created_at == cursor.created_at,
                        Share.id < cursor.item_id,
                    ),
                )
            )
        result = await self.session.execute(
            query.order_by(Share.created_at.desc(), Share.id.desc()).limit(limit)
        )
        return [(row[0], row[1], row[2]) for row in result.all()]

    async def list_items_with_nodes(
        self,
        *,
        tenant_id: UUID,
        share_id: UUID,
    ) -> list[tuple[ShareItem, Node, FileVersion | None, FileBlob | None]]:
        result = await self.session.execute(
            select(ShareItem, Node, FileVersion, FileBlob)
            .join(
                Node,
                and_(Node.tenant_id == ShareItem.tenant_id, Node.id == ShareItem.node_id),
            )
            .outerjoin(
                FileVersion,
                and_(
                    FileVersion.tenant_id == Node.tenant_id,
                    FileVersion.id == Node.current_version_id,
                ),
            )
            .outerjoin(
                FileBlob,
                and_(
                    FileBlob.tenant_id == FileVersion.tenant_id,
                    FileBlob.id == FileVersion.blob_id,
                ),
            )
            .where(
                ShareItem.tenant_id == tenant_id,
                ShareItem.share_id == share_id,
            )
            .order_by(ShareItem.created_at, ShareItem.id)
        )
        return [(row[0], row[1], row[2], row[3]) for row in result.all()]

    async def list_notifications(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        unread_only: bool,
        cursor: PageCursor | None,
        limit: int,
    ) -> list[tuple[ShareNotification, Share, User, Node]]:
        query = (
            select(ShareNotification, Share, User, Node)
            .join(
                Share,
                and_(
                    Share.tenant_id == ShareNotification.tenant_id,
                    Share.id == ShareNotification.share_id,
                ),
            )
            .join(
                User,
                and_(User.tenant_id == Share.tenant_id, User.id == Share.created_by),
            )
            .join(
                Node,
                and_(Node.tenant_id == Share.tenant_id, Node.id == Share.root_node_id),
            )
            .where(
                ShareNotification.tenant_id == tenant_id,
                ShareNotification.user_id == user_id,
            )
        )
        if unread_only:
            query = query.where(ShareNotification.is_read.is_(False))
        if cursor is not None:
            query = query.where(
                or_(
                    ShareNotification.created_at < cursor.created_at,
                    and_(
                        ShareNotification.created_at == cursor.created_at,
                        ShareNotification.id < cursor.item_id,
                    ),
                )
            )
        result = await self.session.execute(
            query.order_by(
                ShareNotification.created_at.desc(),
                ShareNotification.id.desc(),
            ).limit(limit)
        )
        return [(row[0], row[1], row[2], row[3]) for row in result.all()]

    async def mark_notification_read(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        notification_id: UUID,
    ) -> ShareNotification | None:
        result = await self.session.execute(
            select(ShareNotification).where(
                ShareNotification.tenant_id == tenant_id,
                ShareNotification.user_id == user_id,
                ShareNotification.id == notification_id,
            )
        )
        notification = result.scalar_one_or_none()
        if notification is None:
            return None
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = utc_now()
            notification.updated_at = notification.read_at
            await self.session.flush()
        return notification

    async def consume_internal_view(self, *, tenant_id: UUID, share_id: UUID) -> bool:
        now = utc_now()
        result = await self.session.execute(
            update(Share)
            .where(
                Share.tenant_id == tenant_id,
                Share.id == share_id,
                Share.share_type == "internal",
                Share.status == "active",
                or_(Share.expires_at.is_(None), Share.expires_at > now),
                or_(Share.max_views.is_(None), Share.view_count < Share.max_views),
            )
            .values(view_count=Share.view_count + 1)
            .returning(Share.id)
        )
        return result.scalar_one_or_none() is not None

    async def consume_internal_download(self, *, tenant_id: UUID, share_id: UUID) -> bool:
        now = utc_now()
        result = await self.session.execute(
            update(Share)
            .where(
                Share.tenant_id == tenant_id,
                Share.id == share_id,
                Share.share_type == "internal",
                Share.status == "active",
                or_(Share.expires_at.is_(None), Share.expires_at > now),
                or_(Share.max_downloads.is_(None), Share.download_count < Share.max_downloads),
            )
            .values(download_count=Share.download_count + 1)
            .returning(Share.id)
        )
        return result.scalar_one_or_none() is not None

    async def list_expired_active_shares(
        self,
        *,
        tenant_id: UUID,
        limit: int,
    ) -> list[Share]:
        result = await self.session.execute(
            select(Share)
            .where(
                Share.tenant_id == tenant_id,
                Share.status == "active",
                Share.expires_at.is_not(None),
                Share.expires_at <= utc_now(),
            )
            .order_by(Share.expires_at, Share.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def revoke_share(
        self,
        *,
        tenant_id: UUID,
        share_id: UUID,
        revoked_by: UUID,
    ) -> bool:
        result = await self.session.execute(
            update(Share)
            .where(
                Share.tenant_id == tenant_id,
                Share.id == share_id,
                Share.status == "active",
            )
            .values(
                status="revoked",
                revoked_at=utc_now(),
                revoked_by=revoked_by,
            )
            .returning(Share.id)
        )
        return result.scalar_one_or_none() is not None

    async def add_access_log(
        self,
        *,
        tenant_id: UUID,
        share_id: UUID,
        actor_id: UUID | None,
        actor_type: str,
        action: str,
        result: str,
        ip: str | None = None,
        user_agent: str | None = None,
        bytes_sent: int = 0,
    ) -> ShareAccessLog:
        access_log = ShareAccessLog(
            tenant_id=tenant_id,
            share_id=share_id,
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            result=result,
            ip=ip,
            user_agent=user_agent,
            bytes_sent=bytes_sent,
        )
        self.session.add(access_log)
        await self.session.flush()
        return access_log

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
