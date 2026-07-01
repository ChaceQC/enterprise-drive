from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utc_now
from app.modules.share.models import Share, ShareAccessLog, ShareItem, ShareRecipient


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
