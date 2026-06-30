from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.auth.models import Tenant, User
from app.modules.org.models import Department, DepartmentMember, UserGroup, UserGroupMember
from app.modules.org.repository import OrgRepository
from tests.helpers import (
    seed_admin,
)
from tests.helpers import (
    session_factory as session_factory,
)
from tests.helpers import (
    settings as settings,
)


@pytest.mark.asyncio
async def test_org_repository_creates_departments_groups_and_memberships(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)

    async with session_factory() as session:
        tenant = (await session.execute(select(Tenant))).scalar_one()
        user = (await session.execute(select(User))).scalar_one()
        repository = OrgRepository(session)
        root = await repository.create_department(
            tenant_id=tenant.id,
            name="总部",
            path="/总部",
        )
        child = await repository.create_department(
            tenant_id=tenant.id,
            parent_id=root.id,
            name="研发部",
            path="/总部/研发部",
            sort_order=10,
        )
        disabled = await repository.create_department(
            tenant_id=tenant.id,
            name="停用部门",
            path="/停用部门",
        )
        disabled.status = "disabled"
        group = await repository.create_user_group(
            tenant_id=tenant.id,
            slug="product-reviewers",
            name="产品评审组",
        )
        disabled_group = await repository.create_user_group(
            tenant_id=tenant.id,
            slug="disabled-group",
            name="停用用户组",
        )
        disabled_group.status = "disabled"
        await repository.add_department_member(
            tenant_id=tenant.id,
            department_id=root.id,
            user_id=user.id,
        )
        await repository.add_department_member(
            tenant_id=tenant.id,
            department_id=child.id,
            user_id=user.id,
        )
        await repository.add_department_member(
            tenant_id=tenant.id,
            department_id=disabled.id,
            user_id=user.id,
        )
        await repository.add_user_group_member(
            tenant_id=tenant.id,
            group_id=group.id,
            user_id=user.id,
        )
        await repository.add_user_group_member(
            tenant_id=tenant.id,
            group_id=disabled_group.id,
            user_id=user.id,
        )
        await repository.commit()

    async with session_factory() as session:
        tenant = (await session.execute(select(Tenant))).scalar_one()
        user = (await session.execute(select(User))).scalar_one()
        repository = OrgRepository(session)

        department_ids = await repository.list_user_department_ids(
            tenant_id=tenant.id,
            user_id=user.id,
        )
        group_ids = await repository.list_user_group_ids(
            tenant_id=tenant.id,
            user_id=user.id,
        )
        department_count = len((await session.execute(select(Department))).scalars().all())
        department_members = (await session.execute(select(DepartmentMember))).scalars().all()
        user_groups = (await session.execute(select(UserGroup))).scalars().all()
        group_members = (await session.execute(select(UserGroupMember))).scalars().all()

    assert department_count == 3
    assert len(department_members) == 3
    assert len(user_groups) == 2
    assert len(group_members) == 2
    assert len(department_ids) == 2
    assert len(group_ids) == 1


@pytest.mark.asyncio
async def test_org_unique_constraints_prevent_duplicate_memberships(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)

    async with session_factory() as session:
        tenant = (await session.execute(select(Tenant))).scalar_one()
        user = (await session.execute(select(User))).scalar_one()
        repository = OrgRepository(session)
        department = await repository.create_department(
            tenant_id=tenant.id,
            name="财务部",
            path="/财务部",
        )
        group = await repository.create_user_group(
            tenant_id=tenant.id,
            slug="finance",
            name="财务组",
        )
        await repository.add_department_member(
            tenant_id=tenant.id,
            department_id=department.id,
            user_id=user.id,
        )
        await repository.add_user_group_member(
            tenant_id=tenant.id,
            group_id=group.id,
            user_id=user.id,
        )
        await repository.commit()

    async with session_factory() as session:
        tenant = (await session.execute(select(Tenant))).scalar_one()
        user = (await session.execute(select(User))).scalar_one()
        department = (await session.execute(select(Department))).scalar_one()
        repository = OrgRepository(session)
        with pytest.raises(IntegrityError):
            await repository.add_department_member(
                tenant_id=tenant.id,
                department_id=department.id,
                user_id=user.id,
            )
        await repository.rollback()

    async with session_factory() as session:
        tenant = (await session.execute(select(Tenant))).scalar_one()
        user = (await session.execute(select(User))).scalar_one()
        group = (await session.execute(select(UserGroup))).scalar_one()
        repository = OrgRepository(session)
        with pytest.raises(IntegrityError):
            await repository.add_user_group_member(
                tenant_id=tenant.id,
                group_id=group.id,
                user_id=user.id,
            )
        await repository.rollback()
