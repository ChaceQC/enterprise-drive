from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utc_now
from app.modules.permission.constants import (
    ACL_SUBJECT_USER,
    SPACE_ROLE_OWNER,
    SPACE_ROLES,
)
from app.modules.permission.models import AclEntry, SpaceMember
from app.modules.permission.validators import validate_acl_entry
from app.modules.space.models import Space


class PermissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_space_member(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        user_id: UUID,
        role: str,
        created_by: UUID | None,
    ) -> SpaceMember:
        if role not in SPACE_ROLES:
            raise ValueError(f"unsupported space role: {role}")
        member = SpaceMember(
            tenant_id=tenant_id,
            space_id=space_id,
            user_id=user_id,
            role=role,
            created_by=created_by,
        )
        self.session.add(member)
        await self.session.flush()
        return member

    async def get_space_member(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        user_id: UUID,
    ) -> SpaceMember | None:
        result = await self.session.execute(
            select(SpaceMember).where(
                SpaceMember.tenant_id == tenant_id,
                SpaceMember.space_id == space_id,
                SpaceMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_space_members(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
    ) -> list[SpaceMember]:
        result = await self.session.execute(
            select(SpaceMember)
            .where(
                SpaceMember.tenant_id == tenant_id,
                SpaceMember.space_id == space_id,
            )
            .order_by(SpaceMember.created_at, SpaceMember.id)
        )
        return list(result.scalars().all())

    async def get_space_member_for_update(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        user_id: UUID,
    ) -> SpaceMember | None:
        result = await self.session.execute(
            select(SpaceMember)
            .where(
                SpaceMember.tenant_id == tenant_id,
                SpaceMember.space_id == space_id,
                SpaceMember.user_id == user_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def count_space_owners(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
    ) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(SpaceMember)
            .where(
                SpaceMember.tenant_id == tenant_id,
                SpaceMember.space_id == space_id,
                SpaceMember.role == SPACE_ROLE_OWNER,
            )
        )
        return int(result.scalar_one())

    async def update_space_member_role(
        self,
        *,
        member: SpaceMember,
        role: str,
    ) -> SpaceMember:
        if role not in SPACE_ROLES:
            raise ValueError(f"unsupported space role: {role}")
        member.role = role
        member.updated_at = utc_now()
        await self.session.flush()
        return member

    async def delete_space_member(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        user_id: UUID,
    ) -> None:
        await self.session.execute(
            delete(SpaceMember).where(
                SpaceMember.tenant_id == tenant_id,
                SpaceMember.space_id == space_id,
                SpaceMember.user_id == user_id,
            )
        )
        await self.session.flush()

    async def bump_space_permission_version(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
    ) -> int:
        await self.session.execute(
            update(Space)
            .where(Space.tenant_id == tenant_id, Space.id == space_id)
            .values(
                permission_version=Space.permission_version + 1,
                updated_at=utc_now(),
            )
        )
        await self.session.flush()
        result = await self.session.execute(
            select(Space.permission_version).where(
                Space.tenant_id == tenant_id,
                Space.id == space_id,
            )
        )
        return int(result.scalar_one())

    async def create_acl_entry(
        self,
        *,
        tenant_id: UUID,
        node_id: UUID,
        subject_id: UUID,
        effect: str,
        actions: list[str],
        inherit: bool,
        created_by: UUID,
    ) -> AclEntry:
        validate_acl_entry(effect=effect, actions=actions)
        entry = AclEntry(
            tenant_id=tenant_id,
            node_id=node_id,
            subject_type=ACL_SUBJECT_USER,
            subject_id=subject_id,
            effect=effect,
            actions=actions,
            inherit=inherit,
            created_by=created_by,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list_node_acl_entries(
        self,
        *,
        tenant_id: UUID,
        node_id: UUID,
    ) -> list[AclEntry]:
        result = await self.session.execute(
            select(AclEntry)
            .where(AclEntry.tenant_id == tenant_id, AclEntry.node_id == node_id)
            .order_by(AclEntry.created_at, AclEntry.id)
        )
        return list(result.scalars().all())

    async def get_acl_entry(
        self,
        *,
        tenant_id: UUID,
        node_id: UUID,
        entry_id: UUID,
    ) -> AclEntry | None:
        result = await self.session.execute(
            select(AclEntry).where(
                AclEntry.tenant_id == tenant_id,
                AclEntry.node_id == node_id,
                AclEntry.id == entry_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_acl_entry_for_update(
        self,
        *,
        tenant_id: UUID,
        node_id: UUID,
        entry_id: UUID,
    ) -> AclEntry | None:
        result = await self.session.execute(
            select(AclEntry)
            .where(
                AclEntry.tenant_id == tenant_id,
                AclEntry.node_id == node_id,
                AclEntry.id == entry_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def update_acl_entry(
        self,
        *,
        entry: AclEntry,
        effect: str,
        actions: list[str],
        inherit: bool,
    ) -> AclEntry:
        validate_acl_entry(effect=effect, actions=actions)
        entry.effect = effect
        entry.actions = actions
        entry.inherit = inherit
        entry.updated_at = utc_now()
        await self.session.flush()
        return entry

    async def delete_acl_entry(
        self,
        *,
        tenant_id: UUID,
        node_id: UUID,
        entry_id: UUID,
    ) -> None:
        await self.session.execute(
            delete(AclEntry).where(
                AclEntry.tenant_id == tenant_id,
                AclEntry.node_id == node_id,
                AclEntry.id == entry_id,
            )
        )
        await self.session.flush()

    async def list_user_acl_entries_for_nodes(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        node_ids: list[UUID],
    ) -> list[AclEntry]:
        if not node_ids:
            return []
        result = await self.session.execute(
            select(AclEntry).where(
                AclEntry.tenant_id == tenant_id,
                AclEntry.node_id.in_(node_ids),
                AclEntry.subject_type == ACL_SUBJECT_USER,
                AclEntry.subject_id == user_id,
            )
        )
        return list(result.scalars().all())

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
