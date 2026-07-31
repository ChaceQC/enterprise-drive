from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.audit.models import AuditLog
from app.modules.auth.models import Tenant, User
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
async def test_super_admin_can_filter_and_page_tenant_audit_logs(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    await login(client)
    member_id = await create_second_user(session_factory)
    fixture = await _seed_fixture_logs(
        session_factory,
        member_id=member_id,
    )

    first_page = await client.get(
        "/api/v1/admin/audit-logs",
        params={"action": "fixture.audit", "page_size": 2},
    )

    assert first_page.status_code == 200
    assert [item["id"] for item in first_page.json()["items"]] == [
        str(fixture["latest_id"]),
        str(fixture["middle_id"]),
    ]
    assert first_page.json()["next_cursor"] is not None
    assert all(
        item["tenant_id"] == str(fixture["tenant_id"]) for item in first_page.json()["items"]
    )

    second_page = await client.get(
        "/api/v1/admin/audit-logs",
        params={
            "action": "fixture.audit",
            "page_size": 2,
            "cursor": first_page.json()["next_cursor"],
        },
    )

    assert second_page.status_code == 200
    assert [item["id"] for item in second_page.json()["items"]] == [str(fixture["oldest_id"])]
    assert second_page.json()["next_cursor"] is None

    filtered = await client.get(
        "/api/v1/admin/audit-logs",
        headers={"X-Request-ID": "req_audit_filter"},
        params={
            "actor_id": str(fixture["admin_id"]),
            "actor_type": "user",
            "action": "fixture.audit",
            "resource_type": "node",
            "resource_id": str(fixture["shared_node_id"]),
            "result": "allowed",
            "risk_level": "medium",
            "request_id": "req_fixture_latest",
            "created_from": datetime(2026, 7, 31, 11, 30, tzinfo=UTC).isoformat(),
            "created_to": datetime(2026, 7, 31, 12, 30, tzinfo=UTC).isoformat(),
        },
    )

    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["items"]] == [str(fixture["latest_id"])]
    assert filtered.json()["items"][0]["metadata"] == {"fixture": "latest"}

    async with session_factory() as session:
        query_logs = list(
            (
                await session.execute(
                    select(AuditLog)
                    .where(AuditLog.action == "admin.audit_logs.queried")
                    .order_by(AuditLog.created_at, AuditLog.id)
                )
            )
            .scalars()
            .all()
        )

    assert len(query_logs) == 3
    filtered_query_log = next(log for log in query_logs if log.request_id == "req_audit_filter")
    assert filtered_query_log.result == "allowed"
    assert filtered_query_log.risk_level == "medium"
    assert filtered_query_log.metadata_json["returned_count"] == 1
    assert filtered_query_log.metadata_json["filters"]["actor_id"] == str(fixture["admin_id"])
    assert filtered_query_log.metadata_json["filters"]["resource_id"] == str(
        fixture["shared_node_id"]
    )


@pytest.mark.asyncio
async def test_non_super_admin_is_denied_and_query_is_audited(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    member_id = await create_second_user(session_factory)
    await login(client, username="member", password="member-password")

    response = await client.get(
        "/api/v1/admin/audit-logs",
        headers={"X-Request-ID": "req_audit_denied"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "ADMIN_REQUIRED"
    async with session_factory() as session:
        denied_log = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "admin.audit_logs.queried",
                    AuditLog.request_id == "req_audit_denied",
                )
            )
        ).scalar_one()

    assert denied_log.actor_id == member_id
    assert denied_log.result == "denied"
    assert denied_log.metadata_json["reason"] == "super_admin_required"


@pytest.mark.asyncio
async def test_admin_audit_query_rejects_invalid_time_range(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    await login(client)

    response = await client.get(
        "/api/v1/admin/audit-logs",
        headers={"X-Request-ID": "req_audit_invalid_range"},
        params={
            "created_from": datetime(2026, 7, 31, 13, 0, tzinfo=UTC).isoformat(),
            "created_to": datetime(2026, 7, 31, 12, 0, tzinfo=UTC).isoformat(),
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "AUDIT_TIME_RANGE_INVALID"
    async with session_factory() as session:
        denied_log = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "admin.audit_logs.queried",
                    AuditLog.request_id == "req_audit_invalid_range",
                )
            )
        ).scalar_one()

    assert denied_log.result == "denied"
    assert denied_log.metadata_json["reason"] == "invalid_time_range"


async def _seed_fixture_logs(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    member_id: UUID,
) -> dict[str, UUID]:
    shared_node_id = uuid4()
    other_node_id = uuid4()
    async with session_factory() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.slug == "default"))
        ).scalar_one()
        admin = (
            await session.execute(
                select(User).where(
                    User.tenant_id == tenant.id,
                    User.username == "admin",
                )
            )
        ).scalar_one()
        foreign_tenant = Tenant(slug="foreign", name="其他租户")
        session.add(foreign_tenant)
        await session.flush()

        latest = AuditLog(
            tenant_id=tenant.id,
            actor_id=admin.id,
            action="fixture.audit",
            resource_type="node",
            resource_id=shared_node_id,
            result="allowed",
            risk_level="medium",
            request_id="req_fixture_latest",
            metadata_json={"fixture": "latest"},
            created_at=datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
        )
        middle = AuditLog(
            tenant_id=tenant.id,
            actor_id=member_id,
            action="fixture.audit",
            resource_type="node",
            resource_id=shared_node_id,
            result="denied",
            risk_level="high",
            request_id="req_fixture_middle",
            metadata_json={"fixture": "middle"},
            created_at=datetime(2026, 7, 31, 11, 0, tzinfo=UTC),
        )
        oldest = AuditLog(
            tenant_id=tenant.id,
            actor_id=admin.id,
            action="fixture.audit",
            resource_type="node",
            resource_id=other_node_id,
            result="allowed",
            risk_level="low",
            request_id="req_fixture_oldest",
            metadata_json={"fixture": "oldest"},
            created_at=datetime(2026, 7, 31, 10, 0, tzinfo=UTC),
        )
        foreign = AuditLog(
            tenant_id=foreign_tenant.id,
            actor_id=None,
            actor_type="system",
            action="fixture.audit",
            resource_type="node",
            resource_id=shared_node_id,
            result="allowed",
            risk_level="low",
            request_id="req_fixture_foreign",
            metadata_json={"fixture": "foreign"},
            created_at=datetime(2026, 7, 31, 13, 0, tzinfo=UTC),
        )
        session.add_all([latest, middle, oldest, foreign])
        await session.commit()
        return {
            "tenant_id": tenant.id,
            "admin_id": admin.id,
            "shared_node_id": shared_node_id,
            "latest_id": latest.id,
            "middle_id": middle.id,
            "oldest_id": oldest.id,
        }
