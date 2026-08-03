from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.quota.models import QuotaAccount, QuotaPolicy
from tests.helpers import (
    client as client,
)
from tests.helpers import (
    create_second_user,
    create_space,
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
async def test_super_admin_manages_quota_accounts_and_policies(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="admin-quota")
    tenant_id = UUID(str(space["tenant_id"]))
    space_id = UUID(str(space["id"]))

    update_space = await client.put(
        f"/api/v1/admin/quotas/accounts/space/{space_id}",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "limit_bytes": 8192,
            "expected_limit_bytes": settings.default_space_quota_bytes,
        },
    )
    assert update_space.status_code == 200
    assert update_space.json()["limit_bytes"] == 8192

    stale_update = await client.put(
        f"/api/v1/admin/quotas/accounts/space/{space_id}",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "limit_bytes": 16384,
            "expected_limit_bytes": settings.default_space_quota_bytes,
        },
    )
    assert stale_update.status_code == 409
    assert stale_update.json()["code"] == "QUOTA_ACCOUNT_CHANGED"

    create_tenant_account = await client.put(
        f"/api/v1/admin/quotas/accounts/tenant/{tenant_id}",
        headers={"X-CSRF-Token": csrf_token},
        json={"limit_bytes": 4096},
    )
    assert create_tenant_account.status_code == 200
    assert create_tenant_account.json()["owner_type"] == "tenant"

    create_policy = await client.post(
        "/api/v1/admin/quotas/policies",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "name": "密级文件",
            "priority": 10,
            "limit_bytes": 4096,
            "max_file_size_bytes": 512,
            "extensions": ["SECRET", ".secret"],
        },
    )
    assert create_policy.status_code == 201
    policy_id = UUID(create_policy.json()["id"])
    assert create_policy.json()["extensions"] == [".secret"]
    assert create_policy.json()["used_bytes"] == 0

    update_policy = await client.patch(
        f"/api/v1/admin/quotas/policies/{policy_id}",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "expected_limit_bytes": 4096,
            "limit_bytes": 8192,
            "max_file_size_bytes": 1024,
            "mime_prefixes": ["application/pdf"],
        },
    )
    assert update_policy.status_code == 200
    assert update_policy.json()["limit_bytes"] == 8192
    assert update_policy.json()["mime_prefixes"] == ["application/pdf"]

    account_list = await client.get(
        "/api/v1/admin/quotas/accounts",
        params={"owner_type": "policy", "owner_id": str(policy_id)},
    )
    assert account_list.status_code == 200
    assert account_list.json()["items"][0]["limit_bytes"] == 8192

    policy_list = await client.get(
        "/api/v1/admin/quotas/policies",
        params={"name": "密级", "is_active": True},
    )
    assert policy_list.status_code == 200
    assert [item["id"] for item in policy_list.json()["items"]] == [str(policy_id)]

    deactivate = await client.delete(
        f"/api/v1/admin/quotas/policies/{policy_id}",
        headers={"X-CSRF-Token": csrf_token},
        params={"expected_limit_bytes": 8192},
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    async with session_factory() as session:
        policy = (
            await session.execute(select(QuotaPolicy).where(QuotaPolicy.id == policy_id))
        ).scalar_one()
        policy_account = (
            await session.execute(
                select(QuotaAccount).where(
                    QuotaAccount.owner_type == "policy",
                    QuotaAccount.owner_id == policy_id,
                )
            )
        ).scalar_one()
        audit_actions = set(
            (
                await session.execute(
                    select(AuditLog.action).where(AuditLog.action.like("admin.quota%"))
                )
            )
            .scalars()
            .all()
        )

    assert policy.is_active is False
    assert policy_account.limit_bytes == 8192
    assert {
        "admin.quota_account.created",
        "admin.quota_account.updated",
        "admin.quota_accounts.queried",
        "admin.quota_policy.created",
        "admin.quota_policy.updated",
        "admin.quota_policy.deactivated",
        "admin.quota_policies.queried",
    }.issubset(audit_actions)


@pytest.mark.asyncio
async def test_admin_created_tenant_quota_is_enforced_when_default_is_disabled(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    settings.default_tenant_quota_bytes = 0
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="managed-tenant-quota")
    tenant_id = UUID(str(space["tenant_id"]))

    account_response = await client.put(
        f"/api/v1/admin/quotas/accounts/tenant/{tenant_id}",
        headers={"X-CSRF-Token": csrf_token},
        json={"limit_bytes": 512},
    )
    assert account_response.status_code == 200

    upload_response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "tenant-limit.bin",
            "size_bytes": 1024,
            "content_hash": "a" * 64,
            "hash_algo": "sha256",
        },
    )

    assert upload_response.status_code == 422
    assert upload_response.json()["code"] == "QUOTA_EXCEEDED"
    assert upload_response.json()["details"]["scope"] == "tenant"


@pytest.mark.asyncio
async def test_normal_user_is_denied_quota_management(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    member_id = await create_second_user(session_factory)
    await login(client, username="member", password="member-password")

    response = await client.get(
        "/api/v1/admin/quotas/accounts",
        headers={"X-Request-ID": "req_quota_admin_denied"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "ADMIN_REQUIRED"
    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.id == member_id))).scalar_one()
        audit = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "admin.quota_accounts.queried",
                    AuditLog.request_id == "req_quota_admin_denied",
                )
            )
        ).scalar_one()

    assert user.is_super_admin is False
    assert audit.actor_id == member_id
    assert audit.result == "denied"
