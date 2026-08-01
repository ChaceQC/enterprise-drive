from __future__ import annotations

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.infrastructure.preview.libreoffice import _normalize_extension
from app.infrastructure.storage.testing import InMemoryStorageAdapter
from app.main import create_app
from app.modules.file.models import FileBlob, FileVersion
from app.modules.preview.converters import PreviewRenderError
from app.modules.preview.models import PreviewArtifact
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
from tests.preview_helpers import (
    create_instant_uploaded_file,
    dispatch_preview_events,
)


async def _create_instant_file(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    csrf_token: str,
    *,
    tenant_id: str,
    space_id: str,
    parent_id: str,
    file_name: str,
    content_hash: str,
) -> dict[str, object]:
    async with session_factory() as session:
        session.add(
            FileBlob(
                tenant_id=UUID(tenant_id),
                hash_algo="sha256",
                content_hash=content_hash,
                size_bytes=128,
                storage_key=f"objects/security/{content_hash[:2]}/{content_hash}",
                mime_type="text/plain",
                ref_count=0,
            )
        )
        await session.commit()

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "space_id": space_id,
            "parent_id": parent_id,
            "file_name": file_name,
            "size_bytes": 128,
            "content_hash": content_hash,
            "hash_algo": "sha256",
            "mime_type": "text/plain",
        },
    )
    assert response.status_code == 201
    return dict(response.json())


@pytest.mark.asyncio
async def test_malformed_image_preview_is_terminal_without_artifact(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="security-malformed-image")
    tenant_id = UUID(str(space["tenant_id"]))
    _, version_id = await create_instant_uploaded_file(
        client=client,
        session_factory=session_factory,
        settings=settings,
        storage_adapter=storage_adapter,
        token=token,
        space=space,
        tenant_id=tenant_id,
        content=b"not-a-real-png",
        storage_key="objects/security/malformed-image",
        content_hash="a" * 64,
        file_name="malformed.png",
        mime_type="image/png",
    )

    await dispatch_preview_events(
        session_factory=session_factory,
        settings=settings,
        storage_adapter=storage_adapter,
    )

    async with session_factory() as session:
        version = await session.get(FileVersion, version_id)
        artifacts = (
            (
                await session.execute(
                    select(PreviewArtifact).where(PreviewArtifact.version_id == version_id)
                )
            )
            .scalars()
            .all()
        )

    assert version is not None
    assert version.preview_status == "failed"
    assert version.preview_error == "image_decode_failed"
    assert artifacts == []
    assert not any(
        key.startswith(f"previews/{tenant_id}/{version.node_id}/{version_id}/")
        for _, key in storage_adapter.object_contents
    )


@pytest.mark.asyncio
async def test_oversized_image_is_rejected_before_preview_read(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    settings.preview_max_source_bytes = 16
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="security-large-image")
    tenant_id = UUID(str(space["tenant_id"]))
    _, version_id = await create_instant_uploaded_file(
        client=client,
        session_factory=session_factory,
        settings=settings,
        storage_adapter=storage_adapter,
        token=token,
        space=space,
        tenant_id=tenant_id,
        content=b"x" * 17,
        storage_key="objects/security/large-image",
        content_hash="b" * 64,
        file_name="large.png",
        mime_type="image/png",
    )

    await dispatch_preview_events(
        session_factory=session_factory,
        settings=settings,
        storage_adapter=storage_adapter,
    )

    async with session_factory() as session:
        version = await session.get(FileVersion, version_id)
        artifacts = (
            (
                await session.execute(
                    select(PreviewArtifact).where(PreviewArtifact.version_id == version_id)
                )
            )
            .scalars()
            .all()
        )

    assert version is not None
    assert version.preview_status == "unsupported"
    assert version.preview_error == "file_too_large"
    assert artifacts == []


def test_office_extension_injection_is_rejected_before_process_start() -> None:
    with pytest.raises(PreviewRenderError) as exc_info:
        _normalize_extension(".docx;touch-pwned")

    assert exc_info.value.reason == "office_render_failed"
    assert "touch-pwned" not in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("file_name", ["../payload.docx", r"..\payload.docx", "payload\x00.docx"])
async def test_document_path_and_control_names_are_rejected(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    file_name: str,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug=f"security-document-{len(file_name)}")

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": file_name,
            "size_bytes": 1,
            "content_hash": "c" * 64,
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "NODE_NAME_INVALID"


@pytest.mark.asyncio
async def test_range_header_does_not_bypass_download_authorization_or_url_policy(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    owner_token = await login(client)
    space = await create_space(client, owner_token, slug="security-range-download")
    tenant_id = UUID(str(space["tenant_id"]))
    node_id, _ = await create_instant_uploaded_file(
        client=client,
        session_factory=session_factory,
        settings=settings,
        storage_adapter=storage_adapter,
        token=owner_token,
        space=space,
        tenant_id=tenant_id,
        content=b"downloaded-content",
        storage_key="objects/security/range-file",
        content_hash="d" * 64,
        file_name="range.txt",
        mime_type="text/plain",
    )

    owner_response = await client.get(
        f"/api/v1/files/{node_id}/download",
        headers={"Range": "bytes=0-3"},
    )
    assert owner_response.status_code == 200
    download_url = owner_response.json()["download_url"]
    assert download_url.startswith("https://storage.test/")
    assert "@" not in download_url
    assert "drive_session" not in download_url
    assert "drive_csrf" not in download_url

    await create_second_user(session_factory)
    member_token = await login(client, username="member", password="member-password")
    denied_response = await client.get(
        f"/api/v1/files/{node_id}/download",
        headers={"Range": "bytes=0-3", "X-CSRF-Token": member_token},
    )

    assert denied_response.status_code == 404
    assert denied_response.json()["code"] == "NODE_NOT_FOUND"


@pytest.mark.asyncio
async def test_external_token_guessing_is_rate_limited_across_distinct_tokens(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    settings.rate_limit_enabled = True
    settings.share_external_access_rate_limit_count = 2
    settings.share_external_access_rate_limit_window_seconds = 60
    settings.share_external_download_rate_limit_count = 2
    settings.share_external_download_rate_limit_window_seconds = 60
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="security-share-guessing")
    file_payload = await _create_instant_file(
        client,
        session_factory,
        token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="guessing.txt",
        content_hash="e" * 64,
    )

    access_responses = [
        await client.post(
            "/api/v1/public/shares/access",
            json={"tenant_slug": "default", "raw_token": token_value},
        )
        for token_value in ("1" * 32, "2" * 32, "3" * 32)
    ]
    download_responses = [
        await client.post(
            "/api/v1/public/shares/download",
            json={
                "tenant_slug": "default",
                "raw_token": token_value,
                "node_id": file_payload["node_id"],
            },
        )
        for token_value in ("4" * 32, "5" * 32, "6" * 32)
    ]

    assert [response.status_code for response in access_responses] == [404, 404, 429]
    assert [response.status_code for response in download_responses] == [404, 404, 429]
    assert access_responses[-1].json()["details"]["action"] == "share.external_access"
    assert download_responses[-1].json()["details"]["action"] == "share.external_download"


@pytest.mark.asyncio
async def test_trusted_host_rejects_unknown_host_before_route_dispatch(settings: Settings) -> None:
    settings.trusted_hosts = ["drive.example.test"]
    app = create_app(settings)
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport, base_url="http://drive.example.test"
    ) as test_client:
        allowed_response = await test_client.get("/api/v1/ping")
        denied_response = await test_client.get(
            "/api/v1/ping",
            headers={"Host": "attacker.example.test"},
        )

    assert allowed_response.status_code == 200
    assert denied_response.status_code == 400
    assert "attacker.example.test" not in denied_response.text


@pytest.mark.asyncio
async def test_cors_preflight_allows_only_configured_origin(settings: Settings) -> None:
    settings.trusted_hosts = ["drive.example.test"]
    settings.cors_origins = ["https://app.example.test"]
    app = create_app(settings)
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport, base_url="http://drive.example.test"
    ) as test_client:
        allowed_response = await test_client.options(
            "/api/v1/ping",
            headers={
                "Origin": "https://app.example.test",
                "Access-Control-Request-Method": "GET",
            },
        )
        denied_response = await test_client.options(
            "/api/v1/ping",
            headers={
                "Origin": "https://attacker.example.test",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed_response.status_code == 200
    assert allowed_response.headers["access-control-allow-origin"] == "https://app.example.test"
    assert allowed_response.headers["access-control-allow-credentials"] == "true"
    assert denied_response.status_code == 400
    assert "access-control-allow-origin" not in denied_response.headers
