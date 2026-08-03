from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PageCursor
from app.modules.file_security.models import FileSecurityPolicy


class FileSecurityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active_policies(self, *, tenant_id: UUID) -> list[FileSecurityPolicy]:
        result = await self.session.execute(
            select(FileSecurityPolicy)
            .where(
                FileSecurityPolicy.tenant_id == tenant_id,
                FileSecurityPolicy.is_active.is_(True),
            )
            .order_by(
                FileSecurityPolicy.priority,
                FileSecurityPolicy.created_at,
                FileSecurityPolicy.id,
            )
        )
        return list(result.scalars().all())

    async def list_policies(
        self,
        *,
        tenant_id: UUID,
        is_active: bool | None,
        classification: str | None,
        name: str | None,
        limit: int,
        cursor: PageCursor | None,
    ) -> list[FileSecurityPolicy]:
        conditions = [FileSecurityPolicy.tenant_id == tenant_id]
        if is_active is not None:
            conditions.append(FileSecurityPolicy.is_active.is_(is_active))
        if classification is not None:
            conditions.append(FileSecurityPolicy.classification == classification)
        if name is not None:
            conditions.append(func.lower(FileSecurityPolicy.name).contains(name.casefold()))
        if cursor is not None:
            conditions.append(
                or_(
                    FileSecurityPolicy.created_at < cursor.created_at,
                    and_(
                        FileSecurityPolicy.created_at == cursor.created_at,
                        FileSecurityPolicy.id < cursor.item_id,
                    ),
                )
            )
        result = await self.session.execute(
            select(FileSecurityPolicy)
            .where(*conditions)
            .order_by(
                FileSecurityPolicy.created_at.desc(),
                FileSecurityPolicy.id.desc(),
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_policy_for_update(
        self,
        *,
        tenant_id: UUID,
        policy_id: UUID,
    ) -> FileSecurityPolicy | None:
        result = await self.session.execute(
            select(FileSecurityPolicy)
            .where(
                FileSecurityPolicy.tenant_id == tenant_id,
                FileSecurityPolicy.id == policy_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def create_policy(
        self,
        *,
        tenant_id: UUID,
        name: str,
        priority: int,
        classification: str,
        download_mode: str,
        extensions: list[str],
        mime_prefixes: list[str],
        dlp_keywords: list[str],
        dlp_action: str,
        fail_closed: bool,
        watermark_text: str | None,
        is_active: bool,
    ) -> FileSecurityPolicy:
        policy = FileSecurityPolicy(
            tenant_id=tenant_id,
            name=name,
            priority=priority,
            classification=classification,
            download_mode=download_mode,
            extensions=extensions,
            mime_prefixes=mime_prefixes,
            dlp_keywords=dlp_keywords,
            dlp_action=dlp_action,
            fail_closed=fail_closed,
            watermark_text=watermark_text,
            is_active=is_active,
        )
        self.session.add(policy)
        await self.session.flush()
        return policy

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
