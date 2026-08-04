from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import hash_password
from app.modules.auth.repository import AuthRepository
from app.modules.org.repository import OrgRepository
from tests.helpers import client as client
from tests.helpers import login, seed_admin
from tests.helpers import session_factory as session_factory
from tests.helpers import settings as settings
from tests.helpers import storage_adapter as storage_adapter


@pytest.mark.asyncio
async def test_directory_queries_are_active_tenant_scoped_searchable_and_paginated(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    expected_ids = await _seed_directory_fixture(session_factory)
    await login(
        client,
        username="selector-alpha",
        password="directory-password",
    )

    cases = (
        (
            "/api/v1/directory/users",
            {"id", "username", "display_name"},
            expected_ids["users"],
        ),
        (
            "/api/v1/directory/departments",
            {"id", "name", "path"},
            expected_ids["departments"],
        ),
        (
            "/api/v1/directory/groups",
            {"id", "slug", "name"},
            expected_ids["groups"],
        ),
    )
    for path, response_keys, expected in cases:
        first_page = await client.get(
            path,
            params={"q": "SELECTOR", "page_size": 1},
        )
        assert first_page.status_code == 200
        first_payload = first_page.json()
        assert len(first_payload["items"]) == 1
        assert set(first_payload["items"][0]) == response_keys
        assert first_payload["next_cursor"] is not None

        second_page = await client.get(
            path,
            params={
                "q": "selector",
                "page_size": 1,
                "cursor": first_payload["next_cursor"],
            },
        )
        assert second_page.status_code == 200
        second_payload = second_page.json()
        assert len(second_payload["items"]) == 1
        assert second_payload["next_cursor"] is None
        assert {
            first_payload["items"][0]["id"],
            second_payload["items"][0]["id"],
        } == {str(item_id) for item_id in expected}

    invalid_cursor = await client.get(
        "/api/v1/directory/users",
        params={"cursor": "invalid"},
    )
    assert invalid_cursor.status_code == 400
    assert invalid_cursor.json()["code"] == "CURSOR_INVALID"


async def _seed_directory_fixture(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, set[UUID]]:
    async with session_factory() as session:
        auth_repository = AuthRepository(session)
        org_repository = OrgRepository(session)
        tenant = await auth_repository.get_tenant_by_slug("default")
        assert tenant is not None
        base_time = datetime(2026, 8, 4, 0, 0, tzinfo=UTC)

        first_user = await auth_repository.create_user(
            tenant_id=tenant.id,
            username="selector-alpha",
            email="selector-alpha@example.com",
            display_name="Selector Alpha",
            password_hash=hash_password("directory-password"),
        )
        first_user.created_at = base_time
        second_user = await auth_repository.create_user(
            tenant_id=tenant.id,
            username="selector-beta",
            email="selector-beta@example.com",
            display_name="Selector Beta",
            password_hash=hash_password("directory-password"),
        )
        second_user.created_at = base_time + timedelta(seconds=1)
        disabled_user = await auth_repository.create_user(
            tenant_id=tenant.id,
            username="selector-disabled",
            email="selector-disabled@example.com",
            display_name="Selector Disabled",
            password_hash=hash_password("directory-password"),
        )
        disabled_user.created_at = base_time + timedelta(seconds=2)
        disabled_user.is_active = False

        first_department = await org_repository.create_department(
            tenant_id=tenant.id,
            name="Selector 研发部",
            path="/Selector 研发部",
        )
        first_department.created_at = base_time
        second_department = await org_repository.create_department(
            tenant_id=tenant.id,
            name="Selector 财务部",
            path="/Selector 财务部",
        )
        second_department.created_at = base_time + timedelta(seconds=1)
        disabled_department = await org_repository.create_department(
            tenant_id=tenant.id,
            name="Selector 停用部门",
            path="/Selector 停用部门",
        )
        disabled_department.created_at = base_time + timedelta(seconds=2)
        disabled_department.status = "disabled"

        first_group = await org_repository.create_user_group(
            tenant_id=tenant.id,
            slug="selector-alpha",
            name="Selector Alpha 组",
        )
        first_group.created_at = base_time
        second_group = await org_repository.create_user_group(
            tenant_id=tenant.id,
            slug="selector-beta",
            name="Selector Beta 组",
        )
        second_group.created_at = base_time + timedelta(seconds=1)
        disabled_group = await org_repository.create_user_group(
            tenant_id=tenant.id,
            slug="selector-disabled",
            name="Selector 停用组",
        )
        disabled_group.created_at = base_time + timedelta(seconds=2)
        disabled_group.status = "disabled"

        foreign_tenant = await auth_repository.create_tenant(
            slug="selector-foreign",
            name="Selector 外部租户",
        )
        foreign_user = await auth_repository.create_user(
            tenant_id=foreign_tenant.id,
            username="selector-foreign",
            email="selector-foreign@example.com",
            display_name="Selector Foreign",
            password_hash=hash_password("directory-password"),
        )
        foreign_user.created_at = base_time + timedelta(seconds=3)
        foreign_department = await org_repository.create_department(
            tenant_id=foreign_tenant.id,
            name="Selector 外部部门",
            path="/Selector 外部部门",
        )
        foreign_department.created_at = base_time + timedelta(seconds=3)
        foreign_group = await org_repository.create_user_group(
            tenant_id=foreign_tenant.id,
            slug="selector-foreign",
            name="Selector 外部组",
        )
        foreign_group.created_at = base_time + timedelta(seconds=3)

        await session.commit()
        return {
            "users": {first_user.id, second_user.id},
            "departments": {first_department.id, second_department.id},
            "groups": {first_group.id, second_group.id},
        }
