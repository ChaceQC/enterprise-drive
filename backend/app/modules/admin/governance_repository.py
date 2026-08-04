from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.audit.models import AuditArchive, OutboxEvent
from app.modules.auth.models import User
from app.modules.file.models import FileVersion, Node
from app.modules.quota.models import QuotaAccount
from app.modules.share.models import Share
from app.modules.space.models import Space
from app.modules.upload.models import UploadSession


class AdminGovernanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def overview_stats(self, *, tenant_id: UUID) -> dict[str, int]:
        return {
            "users_total": await self._count(User, User.tenant_id == tenant_id),
            "users_active": await self._count(
                User,
                User.tenant_id == tenant_id,
                User.is_active.is_(True),
            ),
            "spaces_total": await self._count(Space, Space.tenant_id == tenant_id),
            "spaces_active": await self._count(
                Space,
                Space.tenant_id == tenant_id,
                Space.is_active.is_(True),
            ),
            "nodes_total": await self._count(Node, Node.tenant_id == tenant_id),
            "nodes_deleted": await self._count(
                Node,
                Node.tenant_id == tenant_id,
                Node.is_deleted.is_(True),
            ),
            "file_versions_total": await self._count(
                FileVersion,
                FileVersion.tenant_id == tenant_id,
            ),
            "stored_bytes": await self._sum(
                FileVersion.size_bytes,
                FileVersion.tenant_id == tenant_id,
            ),
            "quota_limit_bytes": await self._sum(
                QuotaAccount.limit_bytes,
                QuotaAccount.tenant_id == tenant_id,
                QuotaAccount.owner_type == "space",
            ),
            "quota_used_bytes": await self._sum(
                QuotaAccount.used_bytes,
                QuotaAccount.tenant_id == tenant_id,
                QuotaAccount.owner_type == "space",
            ),
            "active_shares": await self._count(
                Share,
                Share.tenant_id == tenant_id,
                Share.status == "active",
            ),
            "pending_uploads": await self._count(
                UploadSession,
                UploadSession.tenant_id == tenant_id,
                UploadSession.status.in_(["initiated", "uploading"]),
            ),
            "outbox_pending": await self._count(
                OutboxEvent,
                OutboxEvent.tenant_id == tenant_id,
                OutboxEvent.status.in_(["pending", "failed", "processing"]),
            ),
            "outbox_dead": await self._count(
                OutboxEvent,
                OutboxEvent.tenant_id == tenant_id,
                OutboxEvent.status == "dead",
            ),
        }

    async def audit_archive_stats(self, *, tenant_id: UUID) -> dict[str, Any]:
        result = await self.session.execute(
            select(
                func.count(AuditArchive.id),
                func.count(AuditArchive.id).filter(AuditArchive.status == "failed"),
                func.max(AuditArchive.updated_at).filter(AuditArchive.status == "succeeded"),
            ).where(AuditArchive.tenant_id == tenant_id)
        )
        total, failed, last_succeeded_at = result.one()
        return {
            "total": int(total or 0),
            "failed": int(failed or 0),
            "last_succeeded_at": last_succeeded_at,
        }

    async def list_recent_audit_archives(
        self,
        *,
        tenant_id: UUID,
        limit: int,
    ) -> list[AuditArchive]:
        result = await self.session.execute(
            select(AuditArchive)
            .where(AuditArchive.tenant_id == tenant_id)
            .order_by(AuditArchive.created_at.desc(), AuditArchive.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def _count(
        self,
        model: type[Any],
        *conditions: ColumnElement[bool],
    ) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(model).where(*conditions)
        )
        return int(result.scalar_one())

    async def _sum(
        self,
        column: Any,
        *conditions: ColumnElement[bool],
    ) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.sum(column), 0)).where(*conditions)
        )
        value: Any = result.scalar_one()
        return int(value)
