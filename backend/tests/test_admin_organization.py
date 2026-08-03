from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import hash_password
from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.auth.models import AuthSession, Tenant, User
from app.modules.org.models import Department, UserGroup
from tests.helpers import (
    client as client,
)
from tests.helpers import (
    create_second_user,
    login,
    seed_admin,
)
from tests.helpers import (
    session_factory as session_factory,
)
from tests.helpers import (
    settings as settings,
)
from tests.helpers import (
    storage_adapter as storage_adapter,
)


@pytest.mark.asyncio
async def test_super_admin_manages_user_lifecycle_with_cursor_and_preconditions(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    admin_csrf = await login(client)

    alice = await _create_admin_user(
        client,
        admin_csrf,
        username="alice",
        email="ALICE@example.com",
        display_name="Alice",
    )
    bob = await _create_admin_user(
        client,
        admin_csrf,
        username="bob",
        email="bob@example.com",
        display_name="Bob",
    )

    first_page = await client.get(
        "/api/v1/admin/users",
        params={"page_size": 1, "is_active": True},
    )
    assert first_page.status_code == 200
    assert [item["id"] for item in first_page.json()["items"]] == [bob["id"]]
    assert first_page.json()["next_cursor"] is not None

    second_page = await client.get(
        "/api/v1/admin/users",
        params={
            "page_size": 1,
            "is_active": True,
            "cursor": first_page.json()["next_cursor"],
        },
    )
    assert second_page.status_code == 200
    assert [item["id"] for item in second_page.json()["items"]] == [alice["id"]]

    filtered = await client.get("/api/v1/admin/users", params={"q": "ALI"})
    detail = await client.get(f"/api/v1/admin/users/{alice['id']}")
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["items"]] == [alice["id"]]
    assert detail.status_code == 200
    assert detail.json()["email"] == "alice@example.com"

    updated = await client.patch(
        f"/api/v1/admin/users/{alice['id']}",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "expected_version": 1,
            "display_name": "Alice Updated",
            "must_change_password": False,
        },
    )
    stale = await client.patch(
        f"/api/v1/admin/users/{alice['id']}",
        headers={"X-CSRF-Token": admin_csrf},
        json={"expected_version": 1, "display_name": "Stale Update"},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["must_change_password"] is False
    assert stale.status_code == 409
    assert stale.json()["code"] == "ADMIN_USER_CHANGED"

    async with session_factory() as session:
        admin = (
            await session.execute(
                select(User).where(
                    User.username == "admin",
                    User.tenant_id == UUID(alice["tenant_id"]),
                )
            )
        ).scalar_one()
    last_admin = await client.delete(
        f"/api/v1/admin/users/{admin.id}",
        headers={"X-CSRF-Token": admin_csrf},
        params={"expected_version": admin.version},
    )
    assert last_admin.status_code == 409
    assert last_admin.json()["code"] == "LAST_ACTIVE_SUPER_ADMIN"

    alice_login = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "default",
            "username": "alice",
            "password": "alice-password-2026",
        },
    )
    assert alice_login.status_code == 200
    alice_session = alice_login.cookies.get(settings.session_cookie_name)
    alice_csrf = alice_login.cookies.get(settings.csrf_cookie_name)
    assert alice_session is not None
    assert alice_csrf is not None

    admin_csrf = await login(client)
    deactivated = await client.delete(
        f"/api/v1/admin/users/{alice['id']}",
        headers={"X-CSRF-Token": admin_csrf},
        params={"expected_version": 2},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert deactivated.json()["version"] == 3

    client.cookies.set(settings.session_cookie_name, alice_session, path="/")
    client.cookies.set(settings.csrf_cookie_name, alice_csrf, path="/")
    inactive_session = await client.get("/api/v1/auth/me")
    assert inactive_session.status_code == 401
    assert inactive_session.json()["code"] == "AUTH_REQUIRED"

    async with session_factory() as session:
        revoked_sessions = list(
            (
                await session.execute(
                    select(AuthSession).where(
                        AuthSession.user_id == UUID(alice["id"]),
                        AuthSession.revoked_reason == "admin_user_deactivated",
                    )
                )
            )
            .scalars()
            .all()
        )
        audit_actions = set(
            (
                await session.execute(
                    select(AuditLog.action).where(
                        AuditLog.action.in_(
                            {
                                "admin.users.queried",
                                "admin.user.viewed",
                                "admin.user.created",
                                "admin.user.updated",
                                "admin.user.deactivated",
                            }
                        )
                    )
                )
            )
            .scalars()
            .all()
        )

    assert revoked_sessions
    assert audit_actions == {
        "admin.users.queried",
        "admin.user.viewed",
        "admin.user.created",
        "admin.user.updated",
        "admin.user.deactivated",
    }


@pytest.mark.asyncio
async def test_super_admin_manages_department_tree_members_and_permission_events(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    member = await _create_admin_user(
        client,
        csrf_token,
        username="dept-member",
        email="dept-member@example.com",
        display_name="部门成员",
    )

    root = await _create_department(client, csrf_token, name="总部")
    child = await _create_department(
        client,
        csrf_token,
        name="研发部",
        parent_id=root["id"],
    )

    blocked = await client.delete(
        f"/api/v1/admin/departments/{root['id']}",
        headers={"X-CSRF-Token": csrf_token},
        params={"expected_version": 1},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "DEPARTMENT_HAS_ACTIVE_CHILDREN"

    renamed = await client.patch(
        f"/api/v1/admin/departments/{root['id']}",
        headers={"X-CSRF-Token": csrf_token},
        json={"expected_version": 1, "name": "集团总部"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["path"] == "/集团总部"
    assert renamed.json()["version"] == 2

    child_detail = await client.get(f"/api/v1/admin/departments/{child['id']}")
    assert child_detail.status_code == 200
    assert child_detail.json()["path"] == "/集团总部/研发部"
    assert child_detail.json()["version"] == 2

    cycle = await client.patch(
        f"/api/v1/admin/departments/{root['id']}",
        headers={"X-CSRF-Token": csrf_token},
        json={"expected_version": 2, "parent_id": child["id"]},
    )
    assert cycle.status_code == 409
    assert cycle.json()["code"] == "DEPARTMENT_CYCLE"

    added = await client.post(
        f"/api/v1/admin/departments/{child['id']}/members",
        headers={"X-CSRF-Token": csrf_token},
        json={"user_id": member["id"], "expected_version": 2},
    )
    assert added.status_code == 201
    assert added.json()["organization_version"] == 3

    member_list = await client.get(
        f"/api/v1/admin/departments/{child['id']}/members",
        params={"q": "DEPT"},
    )
    assert member_list.status_code == 200
    assert member_list.json()["organization_version"] == 3
    assert [item["user"]["id"] for item in member_list.json()["items"]] == [member["id"]]

    stale_remove = await client.delete(
        f"/api/v1/admin/departments/{child['id']}/members/{member['id']}",
        headers={"X-CSRF-Token": csrf_token},
        params={"expected_version": 2},
    )
    removed = await client.delete(
        f"/api/v1/admin/departments/{child['id']}/members/{member['id']}",
        headers={"X-CSRF-Token": csrf_token},
        params={"expected_version": 3},
    )
    assert stale_remove.status_code == 409
    assert stale_remove.json()["code"] == "DEPARTMENT_CHANGED"
    assert removed.status_code == 200
    assert removed.json()["organization_version"] == 4

    child_disabled = await client.delete(
        f"/api/v1/admin/departments/{child['id']}",
        headers={"X-CSRF-Token": csrf_token},
        params={"expected_version": 4},
    )
    root_disabled = await client.delete(
        f"/api/v1/admin/departments/{root['id']}",
        headers={"X-CSRF-Token": csrf_token},
        params={"expected_version": 2},
    )
    assert child_disabled.status_code == 200
    assert child_disabled.json()["status"] == "disabled"
    assert root_disabled.status_code == 200
    assert root_disabled.json()["status"] == "disabled"

    async with session_factory() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.slug == "default"))
        ).scalar_one()
        permission_events = list(
            (
                await session.execute(
                    select(OutboxEvent)
                    .where(OutboxEvent.event_type == "permission.changed")
                    .order_by(OutboxEvent.created_at, OutboxEvent.id)
                )
            )
            .scalars()
            .all()
        )

    assert tenant.permission_version == 5
    assert [event.payload["scope"] for event in permission_events] == [
        "tenant",
        "tenant",
        "tenant",
        "tenant",
    ]
    assert permission_events[0].payload["affected_user_id"] == member["id"]
    assert permission_events[1].payload["affected_user_id"] == member["id"]
    assert "affected_user_id" not in permission_events[2].payload


@pytest.mark.asyncio
async def test_super_admin_manages_groups_members_and_filters(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    member = await _create_admin_user(
        client,
        csrf_token,
        username="group-member",
        email="group-member@example.com",
        display_name="用户组成员",
    )

    reviewers = await _create_group(
        client,
        csrf_token,
        slug="reviewers",
        name="评审组",
    )
    await _create_group(client, csrf_token, slug="editors", name="编辑组")

    group_page = await client.get(
        "/api/v1/admin/groups",
        params={"page_size": 1, "status": "active"},
    )
    filtered = await client.get("/api/v1/admin/groups", params={"q": "review"})
    assert group_page.status_code == 200
    assert group_page.json()["next_cursor"] is not None
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["items"]] == [reviewers["id"]]

    added = await client.post(
        f"/api/v1/admin/groups/{reviewers['id']}/members",
        headers={"X-CSRF-Token": csrf_token},
        json={"user_id": member["id"], "expected_version": 1},
    )
    duplicate = await client.post(
        f"/api/v1/admin/groups/{reviewers['id']}/members",
        headers={"X-CSRF-Token": csrf_token},
        json={"user_id": member["id"], "expected_version": 2},
    )
    assert added.status_code == 201
    assert added.json()["organization_version"] == 2
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "GROUP_MEMBER_EXISTS"

    stale = await client.patch(
        f"/api/v1/admin/groups/{reviewers['id']}",
        headers={"X-CSRF-Token": csrf_token},
        json={"expected_version": 1, "name": "过期评审组"},
    )
    updated = await client.patch(
        f"/api/v1/admin/groups/{reviewers['id']}",
        headers={"X-CSRF-Token": csrf_token},
        json={"expected_version": 2, "name": "核心评审组"},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "GROUP_CHANGED"
    assert updated.status_code == 200
    assert updated.json()["version"] == 3

    members = await client.get(
        f"/api/v1/admin/groups/{reviewers['id']}/members",
        params={"q": "GROUP"},
    )
    assert members.status_code == 200
    assert members.json()["organization_version"] == 3
    assert [item["user"]["id"] for item in members.json()["items"]] == [member["id"]]

    disabled = await client.delete(
        f"/api/v1/admin/groups/{reviewers['id']}",
        headers={"X-CSRF-Token": csrf_token},
        params={"expected_version": 3},
    )
    blocked_add = await client.post(
        f"/api/v1/admin/groups/{reviewers['id']}/members",
        headers={"X-CSRF-Token": csrf_token},
        json={"user_id": member["id"], "expected_version": 4},
    )
    removed = await client.delete(
        f"/api/v1/admin/groups/{reviewers['id']}/members/{member['id']}",
        headers={"X-CSRF-Token": csrf_token},
        params={"expected_version": 4},
    )
    assert disabled.status_code == 200
    assert disabled.json()["version"] == 4
    assert blocked_add.status_code == 409
    assert blocked_add.json()["code"] == "GROUP_DISABLED"
    assert removed.status_code == 200
    assert removed.json()["organization_version"] == 5

    conflict = await client.post(
        "/api/v1/admin/groups",
        headers={"X-CSRF-Token": csrf_token},
        json={"slug": "reviewers", "name": "重复评审组"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "GROUP_SLUG_EXISTS"


@pytest.mark.asyncio
async def test_admin_organization_routes_enforce_admin_and_tenant_boundaries(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    await create_second_user(session_factory)
    async with session_factory() as session:
        foreign_tenant = Tenant(slug="foreign-org", name="外部组织租户")
        session.add(foreign_tenant)
        await session.flush()
        foreign_user = User(
            tenant_id=foreign_tenant.id,
            username="foreign-user",
            email="foreign-user@example.com",
            display_name="外部用户",
            password_hash=hash_password("foreign-password-2026"),
            is_super_admin=True,
        )
        foreign_department = Department(
            tenant_id=foreign_tenant.id,
            name="外部部门",
            path="/外部部门",
        )
        foreign_group = UserGroup(
            tenant_id=foreign_tenant.id,
            slug="foreign-group",
            name="外部用户组",
        )
        session.add_all([foreign_user, foreign_department, foreign_group])
        await session.commit()

    await login(client)
    user_response = await client.get(f"/api/v1/admin/users/{foreign_user.id}")
    department_response = await client.get(f"/api/v1/admin/departments/{foreign_department.id}")
    group_response = await client.get(f"/api/v1/admin/groups/{foreign_group.id}")
    assert user_response.status_code == 404
    assert user_response.json()["code"] == "ADMIN_USER_NOT_FOUND"
    assert department_response.status_code == 404
    assert department_response.json()["code"] == "DEPARTMENT_NOT_FOUND"
    assert group_response.status_code == 404
    assert group_response.json()["code"] == "GROUP_NOT_FOUND"

    member_csrf = await login(client, username="member", password="member-password")
    denied_read = await client.get("/api/v1/admin/users")
    denied_write = await client.post(
        "/api/v1/admin/departments",
        headers={"X-CSRF-Token": member_csrf},
        json={"name": "越权部门"},
    )
    assert denied_read.status_code == 403
    assert denied_read.json()["code"] == "ADMIN_REQUIRED"
    assert denied_write.status_code == 403
    assert denied_write.json()["code"] == "ADMIN_REQUIRED"


async def _create_admin_user(
    client: AsyncClient,
    csrf_token: str,
    *,
    username: str,
    email: str,
    display_name: str,
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/admin/users",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "username": username,
            "email": email,
            "display_name": display_name,
            "password": f"{username}-password-2026",
        },
    )
    assert response.status_code == 201
    return dict(response.json())


async def _create_department(
    client: AsyncClient,
    csrf_token: str,
    *,
    name: str,
    parent_id: object | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"name": name}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    response = await client.post(
        "/api/v1/admin/departments",
        headers={"X-CSRF-Token": csrf_token},
        json=payload,
    )
    assert response.status_code == 201
    return dict(response.json())


async def _create_group(
    client: AsyncClient,
    csrf_token: str,
    *,
    slug: str,
    name: str,
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/admin/groups",
        headers={"X-CSRF-Token": csrf_token},
        json={"slug": slug, "name": name},
    )
    assert response.status_code == 201
    return dict(response.json())
