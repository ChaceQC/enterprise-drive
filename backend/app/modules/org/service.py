from __future__ import annotations

from uuid import UUID

from app.modules.org.models import Department, UserGroup
from app.modules.org.repository import OrgRepository


class OrgService:
    def __init__(self, *, repository: OrgRepository) -> None:
        self.repository = repository

    async def list_user_department_ids(self, *, tenant_id: UUID, user_id: UUID) -> list[UUID]:
        return await self.repository.list_user_department_ids(
            tenant_id=tenant_id,
            user_id=user_id,
        )

    async def list_user_group_ids(self, *, tenant_id: UUID, user_id: UUID) -> list[UUID]:
        return await self.repository.list_user_group_ids(
            tenant_id=tenant_id,
            user_id=user_id,
        )

    async def get_active_department(
        self,
        *,
        tenant_id: UUID,
        department_id: UUID,
    ) -> Department | None:
        return await self.repository.get_active_department(
            tenant_id=tenant_id,
            department_id=department_id,
        )

    async def get_active_user_group(
        self,
        *,
        tenant_id: UUID,
        group_id: UUID,
    ) -> UserGroup | None:
        return await self.repository.get_active_user_group(
            tenant_id=tenant_id,
            group_id=group_id,
        )

    async def list_active_department_member_user_ids(
        self,
        *,
        tenant_id: UUID,
        department_id: UUID,
    ) -> list[UUID]:
        return await self.repository.list_active_department_member_user_ids(
            tenant_id=tenant_id,
            department_id=department_id,
        )

    async def list_active_group_member_user_ids(
        self,
        *,
        tenant_id: UUID,
        group_id: UUID,
    ) -> list[UUID]:
        return await self.repository.list_active_group_member_user_ids(
            tenant_id=tenant_id,
            group_id=group_id,
        )
