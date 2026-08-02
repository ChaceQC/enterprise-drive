from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import hash_password
from app.modules.auth.models import Tenant, User
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
from tests.security_route_matrix import ROUTE_SECURITY_MATRIX, SecurityRouteCase


@dataclass(frozen=True, slots=True)
class ForeignFixture:
    tenant_id: UUID
    tenant_slug: str
    user_id: UUID
    space_id: UUID
    root_node_id: UUID
    folder_id: UUID
    deleted_folder_id: UUID
    file_node_id: UUID
    file_version_id: UUID
    share_id: UUID
    raw_token: str
    acl_entry_id: UUID
    upload_session_id: UUID


def _zero_bytes_sha256(size_bytes: int) -> str:
    return hashlib.sha256(b"\x00" * size_bytes).hexdigest()


async def _login_tenant(
    client: AsyncClient,
    *,
    tenant_slug: str,
    username: str,
    password: str,
) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": tenant_slug,
            "username": username,
            "password": password,
        },
    )
    assert response.status_code == 200
    csrf_token = response.cookies.get("drive_csrf")
    assert csrf_token is not None
    return csrf_token


async def _complete_small_file(
    client: AsyncClient,
    csrf_token: str,
    *,
    space_id: UUID,
    parent_id: UUID,
) -> dict[str, str]:
    response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "space_id": str(space_id),
            "parent_id": str(parent_id),
            "file_name": "foreign-file.txt",
            "size_bytes": 1024,
            "content_hash": _zero_bytes_sha256(1024),
            "mime_type": "text/plain",
        },
    )
    assert response.status_code == 201
    session_id = response.json()["session_id"]
    complete_response = await client.post(
        f"/api/v1/uploads/{session_id}/complete",
        headers={"X-CSRF-Token": csrf_token},
        json={"parts": [{"part_no": 1, "etag": "foreign-etag", "size_bytes": 1024}]},
    )
    assert complete_response.status_code == 200
    return dict(complete_response.json())


async def _prepare_foreign_fixture(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> ForeignFixture:
    tenant_slug = "foreign-matrix"
    async with session_factory() as session:
        tenant = Tenant(slug=tenant_slug, name="跨租户矩阵企业")
        session.add(tenant)
        await session.flush()
        user = User(
            tenant_id=tenant.id,
            username="foreign-admin",
            email="foreign-admin@example.com",
            display_name="跨租户管理员",
            password_hash=hash_password("foreign-admin-password"),
            is_super_admin=True,
        )
        session.add(user)
        await session.commit()
        tenant_id = tenant.id
        user_id = user.id

    foreign_csrf = await _login_tenant(
        client,
        tenant_slug=tenant_slug,
        username="foreign-admin",
        password="foreign-admin-password",
    )
    space = await create_space(client, foreign_csrf, slug="foreign-matrix-space")
    root_node_id = UUID(str(space["root_node_id"]))
    space_id = UUID(str(space["id"]))
    folder = await create_folder(
        client,
        foreign_csrf,
        space_id=str(space_id),
        parent_id=str(root_node_id),
        name="foreign-active-folder",
    )
    deleted_folder = await create_folder(
        client,
        foreign_csrf,
        space_id=str(space_id),
        parent_id=str(root_node_id),
        name="foreign-deleted-folder",
    )
    delete_response = await client.delete(
        f"/api/v1/files/{deleted_folder['id']}",
        headers={"X-CSRF-Token": foreign_csrf},
    )
    assert delete_response.status_code == 200

    completed = await _complete_small_file(
        client,
        foreign_csrf,
        space_id=space_id,
        parent_id=root_node_id,
    )
    file_node_id = UUID(completed["node_id"])
    file_version_id = UUID(completed["version_id"])

    acl_response = await client.post(
        f"/api/v1/files/{root_node_id}/acl",
        headers={"X-CSRF-Token": foreign_csrf},
        json={
            "subject_type": "user",
            "subject_id": str(user_id),
            "effect": "allow",
            "actions": ["read_meta"],
        },
    )
    assert acl_response.status_code == 201

    share_response = await client.post(
        "/api/v1/shares",
        headers={"X-CSRF-Token": foreign_csrf},
        json={
            "share_type": "external",
            "root_node_id": str(file_node_id),
            "permission": "download",
        },
    )
    assert share_response.status_code == 201
    share_payload = share_response.json()

    upload_response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": foreign_csrf},
        json={
            "space_id": str(space_id),
            "parent_id": str(root_node_id),
            "file_name": "foreign-pending.bin",
            "size_bytes": 1,
            "content_hash": "1" * 64,
        },
    )
    assert upload_response.status_code == 201
    assert upload_response.json()["mode"] == "multipart"

    return ForeignFixture(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        user_id=user_id,
        space_id=space_id,
        root_node_id=root_node_id,
        folder_id=UUID(str(folder["id"])),
        deleted_folder_id=UUID(str(deleted_folder["id"])),
        file_node_id=file_node_id,
        file_version_id=file_version_id,
        share_id=UUID(str(share_payload["id"])),
        raw_token=str(share_payload["raw_token"]),
        acl_entry_id=UUID(str(acl_response.json()["id"])),
        upload_session_id=UUID(str(upload_response.json()["session_id"])),
    )


def _matrix_case(method: str, path: str) -> SecurityRouteCase:
    return next(case for case in ROUTE_SECURITY_MATRIX if case.route_key == (method, path))


@pytest.mark.asyncio
async def test_public_external_link_is_not_bound_to_an_internal_session(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    fixture = await _prepare_foreign_fixture(client, session_factory)
    client.cookies.clear()

    access_response = await client.post(
        "/api/v1/public/shares/access",
        json={"tenant_slug": fixture.tenant_slug, "raw_token": fixture.raw_token},
    )
    download_response = await client.post(
        "/api/v1/public/shares/download",
        json={
            "tenant_slug": fixture.tenant_slug,
            "raw_token": fixture.raw_token,
            "node_id": str(fixture.file_node_id),
        },
    )
    invalid_response = await client.post(
        "/api/v1/public/shares/access",
        json={"tenant_slug": fixture.tenant_slug, "raw_token": "f" * 32},
    )

    assert access_response.status_code == 200
    assert access_response.json()["share_id"] == str(fixture.share_id)
    assert download_response.status_code == 200
    assert download_response.json()["node_id"] == str(fixture.file_node_id)
    assert invalid_response.status_code == 404
    assert invalid_response.json()["code"] == "SHARE_NOT_FOUND"


@pytest.mark.asyncio
async def test_internal_routes_hide_foreign_tenant_resources(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    fixture = await _prepare_foreign_fixture(client, session_factory)
    default_csrf = await login(client)

    cases = {
        ("GET", "/api/v1/spaces/{space_id}/members"): (
            f"/api/v1/spaces/{fixture.space_id}/members",
            None,
        ),
        ("POST", "/api/v1/spaces/{space_id}/members"): (
            f"/api/v1/spaces/{fixture.space_id}/members",
            {"user_id": str(fixture.user_id), "role": "viewer"},
        ),
        ("PATCH", "/api/v1/spaces/{space_id}/members/{user_id}"): (
            f"/api/v1/spaces/{fixture.space_id}/members/{fixture.user_id}",
            {"role": "viewer"},
        ),
        ("DELETE", "/api/v1/spaces/{space_id}/members/{user_id}"): (
            f"/api/v1/spaces/{fixture.space_id}/members/{fixture.user_id}",
            None,
        ),
        ("GET", "/api/v1/files/{node_id}/acl"): (
            f"/api/v1/files/{fixture.root_node_id}/acl",
            None,
        ),
        ("POST", "/api/v1/files/{node_id}/acl"): (
            f"/api/v1/files/{fixture.root_node_id}/acl",
            {
                "subject_type": "user",
                "subject_id": str(fixture.user_id),
                "effect": "allow",
                "actions": ["read_meta"],
            },
        ),
        ("PATCH", "/api/v1/files/{node_id}/acl/{entry_id}"): (
            f"/api/v1/files/{fixture.root_node_id}/acl/{fixture.acl_entry_id}",
            {"effect": "allow", "actions": ["read_meta"]},
        ),
        ("DELETE", "/api/v1/files/{node_id}/acl/{entry_id}"): (
            f"/api/v1/files/{fixture.root_node_id}/acl/{fixture.acl_entry_id}",
            None,
        ),
        ("POST", "/api/v1/files/folders"): (
            "/api/v1/files/folders",
            {
                "space_id": str(fixture.space_id),
                "parent_id": str(fixture.root_node_id),
                "name": "x",
            },
        ),
        ("GET", "/api/v1/files"): (
            "/api/v1/files",
            None,
        ),
        ("GET", "/api/v1/files/trash"): (
            "/api/v1/files/trash",
            None,
        ),
        ("PATCH", "/api/v1/files/{node_id}"): (
            f"/api/v1/files/{fixture.folder_id}",
            {"name": "renamed-foreign"},
        ),
        ("DELETE", "/api/v1/files/{node_id}"): (
            f"/api/v1/files/{fixture.folder_id}",
            None,
        ),
        ("POST", "/api/v1/files/{node_id}/move"): (
            f"/api/v1/files/{fixture.folder_id}/move",
            {"target_parent_id": str(fixture.root_node_id)},
        ),
        ("POST", "/api/v1/files/batch-delete"): (
            "/api/v1/files/batch-delete",
            {"node_ids": [str(fixture.file_node_id)], "mode": "trash"},
        ),
        ("POST", "/api/v1/files/batch-move"): (
            "/api/v1/files/batch-move",
            {
                "node_ids": [str(fixture.file_node_id)],
                "target_parent_id": str(fixture.root_node_id),
            },
        ),
        ("POST", "/api/v1/files/batch-restore"): (
            "/api/v1/files/batch-restore",
            {
                "node_ids": [str(fixture.deleted_folder_id)],
                "target_parent_id": str(fixture.root_node_id),
            },
        ),
        ("POST", "/api/v1/files/batch-purge"): (
            "/api/v1/files/batch-purge",
            {"node_ids": [str(fixture.deleted_folder_id)]},
        ),
        ("DELETE", "/api/v1/files/{node_id}/purge"): (
            f"/api/v1/files/{fixture.deleted_folder_id}/purge",
            None,
        ),
        ("GET", "/api/v1/files/{node_id}/versions"): (
            f"/api/v1/files/{fixture.file_node_id}/versions",
            None,
        ),
        ("GET", "/api/v1/files/{node_id}/versions/{version_id}/download"): (
            f"/api/v1/files/{fixture.file_node_id}/versions/{fixture.file_version_id}/download",
            None,
        ),
        ("POST", "/api/v1/files/{node_id}/versions/{version_id}/rollback"): (
            f"/api/v1/files/{fixture.file_node_id}/versions/{fixture.file_version_id}/rollback",
            {},
        ),
        ("GET", "/api/v1/files/{node_id}/download"): (
            f"/api/v1/files/{fixture.file_node_id}/download",
            None,
        ),
        ("GET", "/api/v1/files/{node_id}/content"): (
            f"/api/v1/files/{fixture.file_node_id}/content",
            None,
        ),
        ("GET", "/api/v1/files/{node_id}/preview"): (
            f"/api/v1/files/{fixture.file_node_id}/preview",
            None,
        ),
        ("POST", "/api/v1/files/{node_id}/restore"): (
            f"/api/v1/files/{fixture.deleted_folder_id}/restore",
            {},
        ),
        ("POST", "/api/v1/shares"): (
            "/api/v1/shares",
            {"share_type": "external", "root_node_id": str(fixture.file_node_id)},
        ),
        ("GET", "/api/v1/shares/{share_id}"): (
            f"/api/v1/shares/{fixture.share_id}",
            None,
        ),
        ("POST", "/api/v1/shares/{share_id}/revoke"): (
            f"/api/v1/shares/{fixture.share_id}/revoke",
            None,
        ),
        ("POST", "/api/v1/uploads/init"): (
            "/api/v1/uploads/init",
            {
                "space_id": str(fixture.space_id),
                "parent_id": str(fixture.root_node_id),
                "file_name": "x.bin",
                "size_bytes": 1,
                "content_hash": "2" * 64,
            },
        ),
        ("GET", "/api/v1/uploads/{session_id}"): (
            f"/api/v1/uploads/{fixture.upload_session_id}",
            None,
        ),
        ("POST", "/api/v1/uploads/{session_id}/parts/{part_no}/presign"): (
            f"/api/v1/uploads/{fixture.upload_session_id}/parts/1/presign",
            None,
        ),
        ("POST", "/api/v1/uploads/{session_id}/complete"): (
            f"/api/v1/uploads/{fixture.upload_session_id}/complete",
            {"parts": [{"part_no": 1, "etag": "foreign"}]},
        ),
        ("POST", "/api/v1/uploads/{session_id}/abort"): (
            f"/api/v1/uploads/{fixture.upload_session_id}/abort",
            None,
        ),
    }

    expected_resource_keys = {
        case.route_key for case in ROUTE_SECURITY_MATRIX if case.tenant_scope == "resource"
    }
    assert set(cases) == expected_resource_keys

    for method, template_path in cases:
        case = _matrix_case(method, template_path)
        request_path, body = cases[(method, template_path)]
        query = (
            {"space_id": str(fixture.space_id)}
            if template_path in {"/api/v1/files", "/api/v1/files/trash"}
            else None
        )
        headers = dict(case.headers)
        if case.csrf_mode == "required":
            headers["X-CSRF-Token"] = default_csrf
        response = await client.request(
            method,
            request_path,
            params=query,
            headers=headers,
            json=body,
        )
        if template_path.startswith("/api/v1/files/batch-"):
            assert response.status_code == 200, case.id
            assert response.json()["results"][0]["status"] == "failed", case.id
            assert response.json()["results"][0]["code"] == "NODE_NOT_FOUND", case.id
        else:
            assert response.status_code == 404, case.id
            assert response.json()["code"] != "INTERNAL_ERROR", case.id

    spaces_response = await client.get("/api/v1/spaces")
    audit_response = await client.get("/api/v1/admin/audit-logs")
    assert spaces_response.status_code == 200
    assert fixture.space_id not in {UUID(item["id"]) for item in spaces_response.json()["items"]}
    assert audit_response.status_code == 200
    assert all(
        UUID(item["tenant_id"]) != fixture.tenant_id for item in audit_response.json()["items"]
    )


@pytest.mark.asyncio
async def test_active_session_loses_space_access_after_member_revocation(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    admin_csrf = await login(client)
    space = await create_space(client, admin_csrf, slug="revocation-matrix-space")
    member_id = await create_second_user(session_factory)
    await add_space_member(
        session_factory,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
    )

    member_login = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "default",
            "username": "member",
            "password": "member-password",
        },
    )
    assert member_login.status_code == 200
    member_session = member_login.cookies.get(settings.session_cookie_name)
    member_csrf = member_login.cookies.get(settings.csrf_cookie_name)
    assert member_session is not None
    assert member_csrf is not None

    before_revoke = await client.get("/api/v1/spaces")
    assert before_revoke.status_code == 200
    assert [item["id"] for item in before_revoke.json()["items"]] == [str(space["id"])]

    admin_csrf = await login(client)
    remove_response = await client.delete(
        f"/api/v1/spaces/{space['id']}/members/{member_id}",
        headers={"X-CSRF-Token": admin_csrf},
    )
    assert remove_response.status_code == 200

    client.cookies.set(settings.session_cookie_name, member_session, path="/")
    client.cookies.set(settings.csrf_cookie_name, member_csrf, path="/")
    after_revoke = await client.get("/api/v1/spaces")
    denied_write = await client.post(
        "/api/v1/files/folders",
        headers={"X-CSRF-Token": member_csrf},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "name": "revoked-write",
        },
    )

    assert after_revoke.status_code == 200
    assert after_revoke.json()["items"] == []
    assert denied_write.status_code == 404
    assert denied_write.json()["code"] == "SPACE_NOT_FOUND"
