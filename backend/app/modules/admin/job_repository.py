from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.pagination import PageCursor
from app.modules.admin.models import AdminJob


class AdminJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_job(
        self,
        *,
        tenant_id: UUID,
        kind: str,
        operation: str,
        created_by: UUID,
        parameters: dict[str, object],
    ) -> AdminJob:
        job = AdminJob(
            tenant_id=tenant_id,
            kind=kind,
            operation=operation,
            created_by=created_by,
            parameters_json=parameters,
            result_json={},
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def list_jobs(
        self,
        *,
        tenant_id: UUID,
        kind: str,
        status: str | None,
        operation: str | None,
        cursor: PageCursor | None,
        limit: int,
    ) -> list[AdminJob]:
        conditions = [AdminJob.tenant_id == tenant_id, AdminJob.kind == kind]
        if status is not None:
            conditions.append(AdminJob.status == status)
        if operation is not None:
            conditions.append(AdminJob.operation == operation)
        if cursor is not None:
            conditions.append(_before_cursor(AdminJob, cursor))
        result = await self.session.execute(
            select(AdminJob)
            .where(*conditions)
            .order_by(AdminJob.created_at.desc(), AdminJob.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_job(
        self,
        *,
        tenant_id: UUID,
        job_id: UUID,
        kind: str | None = None,
    ) -> AdminJob | None:
        conditions = [AdminJob.tenant_id == tenant_id, AdminJob.id == job_id]
        if kind is not None:
            conditions.append(AdminJob.kind == kind)
        result = await self.session.execute(select(AdminJob).where(*conditions))
        return result.scalar_one_or_none()

    async def get_job_for_update(
        self,
        *,
        job_id: UUID,
    ) -> AdminJob | None:
        result = await self.session.execute(
            select(AdminJob).where(AdminJob.id == job_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_pending_job_ids(
        self,
        *,
        kind: str,
        limit: int,
    ) -> list[UUID]:
        result = await self.session.execute(
            select(AdminJob.id)
            .where(AdminJob.kind == kind, AdminJob.status == "pending")
            .order_by(AdminJob.created_at, AdminJob.id)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_expired_export_jobs(
        self,
        *,
        before: datetime,
        limit: int,
        tenant_id: UUID | None = None,
    ) -> list[AdminJob]:
        conditions = [
            AdminJob.kind == "export",
            AdminJob.status == "succeeded",
            AdminJob.completed_at.is_not(None),
            AdminJob.completed_at < before,
            AdminJob.storage_key.is_not(None),
        ]
        if tenant_id is not None:
            conditions.append(AdminJob.tenant_id == tenant_id)
        result = await self.session.execute(
            select(AdminJob)
            .where(*conditions)
            .order_by(AdminJob.completed_at, AdminJob.id)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def flush(self) -> None:
        await self.session.flush()


def _before_cursor(
    model: type[AdminJob],
    cursor: PageCursor,
) -> ColumnElement[bool]:
    return or_(
        model.created_at < cursor.created_at,
        and_(model.created_at == cursor.created_at, model.id < cursor.item_id),
    )
