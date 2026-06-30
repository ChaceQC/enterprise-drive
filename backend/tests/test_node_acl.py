from __future__ import annotations

import hashlib
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.file.models import Node
from tests.helpers import (
    add_space_member,
    create_folder,
    create_second_user,
    create_space,
    login,
    seed_admin,
)
from tests.helpers import (
    client as client,
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


def _zero_bytes_sha256(size_bytes: int) -> str:
    return hashlib.sha256(b"\x00" * size_bytes).hexdigest()


async def _complete_small_file(
    client: AsyncClient,
    token: str,
    *,
    space_id: str,
    parent_id: str,
    file_name: str,
) -> dict[str, str]:
    init_response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": token},
        json={
            "space_id": space_id,
            "parent_id": parent_id,
            "file_name": file_name,
            "size_bytes": 1024,
            "content_hash": _zero_bytes_sha256(1024),
            "hash_algo": "sha256",
            "mime_type": "text/plain",
        },
    )
    assert init_response.status_code == 201
    complete_response = await client.post(
        f"/api/v1/uploads/{init_response.json()['session_id']}/complete",
        headers={"X-CSRF-Token": token},
        json={"parts": [{"part_no": 1, "etag": "etag-1", "size_bytes": 1024}]},
    )
    assert complete_response.status_code == 200
    return dict(complete_response.json())


@pytest.mark.asyncio
async def test_acl_allow_grants_viewer_upload_and_delete_revokes_it(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    admin_token = await login(client)
    space = await create_space(client, admin_token, slug="acl-allow-upload")
    member_id = await create_second_user(session_factory)
    await add_space_member(
        session_factory,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        role="viewer",
    )

    viewer_token = await login(client, username="member", password="member-password")
    denied_response = await client.post(
        "/api/v1/files/folders",
        headers={"X-CSRF-Token": viewer_token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "name": "viewer-before-acl",
        },
    )
    assert denied_response.status_code == 404
    assert denied_response.json()["code"] == "SPACE_NOT_FOUND"

    admin_token = await login(client)
    create_acl_response = await client.post(
        f"/api/v1/files/{space['root_node_id']}/acl",
        headers={"X-CSRF-Token": admin_token, "X-Request-ID": "req_acl_create"},
        json={
            "subject_user_id": str(member_id),
            "effect": "allow",
            "actions": ["upload"],
            "inherit": True,
        },
    )
    list_acl_response = await client.get(
        f"/api/v1/files/{space['root_node_id']}/acl",
        headers={"X-CSRF-Token": admin_token},
    )
    assert create_acl_response.status_code == 201
    acl_entry_id = create_acl_response.json()["id"]
    assert list_acl_response.status_code == 200
    assert [item["id"] for item in list_acl_response.json()["items"]] == [acl_entry_id]

    viewer_token = await login(client, username="member", password="member-password")
    folder = await create_folder(
        client,
        viewer_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="viewer-after-acl",
    )
    assert folder["name"] == "viewer-after-acl"

    admin_token = await login(client)
    remove_acl_response = await client.delete(
        f"/api/v1/files/{space['root_node_id']}/acl/{acl_entry_id}",
        headers={"X-CSRF-Token": admin_token, "X-Request-ID": "req_acl_remove"},
    )
    assert remove_acl_response.status_code == 200

    viewer_token = await login(client, username="member", password="member-password")
    denied_again_response = await client.post(
        "/api/v1/files/folders",
        headers={"X-CSRF-Token": viewer_token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "name": "viewer-after-acl-removed",
        },
    )
    assert denied_again_response.status_code == 404
    assert denied_again_response.json()["code"] == "SPACE_NOT_FOUND"

    async with session_factory() as session:
        root = (
            await session.execute(select(Node).where(Node.id == UUID(str(space["root_node_id"]))))
        ).scalar_one()
        audit_actions = list((await session.execute(select(AuditLog.action))).scalars().all())
        permission_events = list(
            (
                await session.execute(
                    select(OutboxEvent).where(OutboxEvent.event_type == "permission.changed")
                )
            )
            .scalars()
            .all()
        )
    assert root.permission_version == 3
    assert "permission.node_acl.created" in audit_actions
    assert "permission.node_acl.removed" in audit_actions
    assert [event.payload["reason"] for event in permission_events] == [
        "node_acl_created",
        "node_acl_removed",
    ]
    assert {event.payload["scope"] for event in permission_events} == {"node"}
    assert permission_events[-1].payload["permission_version"] == 3
    assert permission_events[-1].payload["affected_user_id"] == str(member_id)


@pytest.mark.asyncio
async def test_acl_deny_overrides_role_and_inherit_controls_descendants(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    admin_token = await login(client)
    space = await create_space(client, admin_token, slug="acl-deny-upload")
    child = await create_folder(
        client,
        admin_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="child",
    )
    member_id = await create_second_user(session_factory)
    await add_space_member(
        session_factory,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        role="editor",
    )

    create_acl_response = await client.post(
        f"/api/v1/files/{space['root_node_id']}/acl",
        headers={"X-CSRF-Token": admin_token},
        json={
            "subject_user_id": str(member_id),
            "effect": "deny",
            "actions": ["upload"],
            "inherit": True,
        },
    )
    assert create_acl_response.status_code == 201
    acl_entry_id = create_acl_response.json()["id"]

    editor_token = await login(client, username="member", password="member-password")
    inherited_denied_response = await client.post(
        "/api/v1/files/folders",
        headers={"X-CSRF-Token": editor_token},
        json={
            "space_id": space["id"],
            "parent_id": child["id"],
            "name": "inherited-denied",
        },
    )
    assert inherited_denied_response.status_code == 404
    assert inherited_denied_response.json()["code"] == "SPACE_NOT_FOUND"

    admin_token = await login(client)
    update_acl_response = await client.patch(
        f"/api/v1/files/{space['root_node_id']}/acl/{acl_entry_id}",
        headers={"X-CSRF-Token": admin_token, "X-Request-ID": "req_acl_update"},
        json={"effect": "deny", "actions": ["upload"], "inherit": False},
    )
    assert update_acl_response.status_code == 200
    assert update_acl_response.json()["inherit"] is False

    editor_token = await login(client, username="member", password="member-password")
    allowed_child = await create_folder(
        client,
        editor_token,
        space_id=str(space["id"]),
        parent_id=str(child["id"]),
        name="inherit-disabled-allowed",
    )
    assert allowed_child["name"] == "inherit-disabled-allowed"

    root_denied_response = await client.post(
        "/api/v1/files/folders",
        headers={"X-CSRF-Token": editor_token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "name": "root-still-denied",
        },
    )
    assert root_denied_response.status_code == 404
    assert root_denied_response.json()["code"] == "SPACE_NOT_FOUND"

    async with session_factory() as session:
        updated_audit = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "permission.node_acl.updated")
            )
        ).scalar_one()
        changed_events = list(
            (
                await session.execute(
                    select(OutboxEvent).where(OutboxEvent.event_type == "permission.changed")
                )
            )
            .scalars()
            .all()
        )
        changed_event = next(
            event for event in changed_events if event.payload["reason"] == "node_acl_updated"
        )
    assert updated_audit.request_id == "req_acl_update"
    assert changed_event.payload["new_inherit"] is False


@pytest.mark.asyncio
async def test_acl_deny_download_hides_file_and_records_denied_audit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    admin_token = await login(client)
    space = await create_space(client, admin_token, slug="acl-deny-download")
    completed = await _complete_small_file(
        client,
        admin_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="acl-download.txt",
    )
    member_id = await create_second_user(session_factory)
    await add_space_member(
        session_factory,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        role="viewer",
    )

    create_acl_response = await client.post(
        f"/api/v1/files/{space['root_node_id']}/acl",
        headers={"X-CSRF-Token": admin_token},
        json={
            "subject_user_id": str(member_id),
            "effect": "deny",
            "actions": ["download"],
            "inherit": True,
        },
    )
    assert create_acl_response.status_code == 201

    viewer_token = await login(client, username="member", password="member-password")
    download_response = await client.get(
        f"/api/v1/files/{completed['node_id']}/download",
        headers={"X-CSRF-Token": viewer_token, "X-Request-ID": "req_acl_download_denied"},
    )
    assert download_response.status_code == 404
    assert download_response.json()["code"] == "NODE_NOT_FOUND"

    async with session_factory() as session:
        denied_audit = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.action == "file.downloaded", AuditLog.result == "denied")
                .order_by(AuditLog.created_at.desc())
            )
        ).scalar_one()
    assert denied_audit.request_id == "req_acl_download_denied"
    assert denied_audit.metadata_json["reason"] == "permission_denied"
