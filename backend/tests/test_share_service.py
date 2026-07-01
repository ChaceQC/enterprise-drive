from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.security import hash_token, verify_password
from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditContext
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.models import FileBlob
from app.modules.file.repository import FileRepository
from app.modules.org.repository import OrgRepository
from app.modules.org.service import OrgService
from app.modules.permission.repository import PermissionRepository
from app.modules.permission.service import PermissionService
from app.modules.share.constants import SHARE_TYPE_EXTERNAL, SHARE_TYPE_INTERNAL
from app.modules.share.models import Share, ShareItem, ShareRecipient
from app.modules.share.repository import ShareRepository
from app.modules.share.schemas import ShareRecipientInput
from app.modules.share.service import ShareService
from tests.helpers import add_space_member, create_second_user, create_space, login, seed_admin
from tests.helpers import client as client
from tests.helpers import session_factory as session_factory
from tests.helpers import settings as settings
from tests.helpers import storage_adapter as storage_adapter


def build_share_service(
    session: AsyncSession,
    *,
    audit_service: AuditService | None = None,
) -> ShareService:
    return ShareService(
        repository=ShareRepository(session),
        file_repository=FileRepository(session),
        permission_service=PermissionService(
            repository=PermissionRepository(session),
            org_service=OrgService(repository=OrgRepository(session)),
        ),
        audit_service=audit_service,
    )


async def create_instant_file(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    token: str,
    *,
    tenant_id: str,
    space_id: str,
    parent_id: str,
    file_name: str,
    content_hash: str,
    size_bytes: int = 128,
) -> dict[str, object]:
    async with session_factory() as session:
        session.add(
            FileBlob(
                tenant_id=UUID(tenant_id),
                hash_algo="sha256",
                content_hash=content_hash,
                size_bytes=size_bytes,
                storage_key=f"objects/test/{content_hash[:2]}/{content_hash}",
                mime_type="text/plain",
                ref_count=0,
            )
        )
        await session.commit()

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": token},
        json={
            "space_id": space_id,
            "parent_id": parent_id,
            "file_name": file_name,
            "size_bytes": size_bytes,
            "content_hash": content_hash,
            "hash_algo": "sha256",
            "mime_type": "text/plain",
        },
    )
    assert response.status_code == 201
    return dict(response.json())


@pytest.mark.asyncio
async def test_create_external_share_stores_hashes_and_audit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="external-share-space")
    file_payload = await create_instant_file(
        client,
        session_factory,
        token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="外链文件.txt",
        content_hash="a" * 64,
    )
    node_id = UUID(file_payload["node_id"])

    async with session_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        service = build_share_service(
            session,
            audit_service=AuditService(repository=AuditRepository(session)),
        )
        result = await service.create_share(
            current_user=user,
            share_type=SHARE_TYPE_EXTERNAL,
            root_node_id=node_id,
            passcode="123456",
            max_views=5,
            max_downloads=2,
            audit_context=AuditContext(request_id="req_share_external"),
        )

    assert result.raw_token is not None
    async with session_factory() as session:
        share = (await session.execute(select(Share))).scalar_one()
        item = (await session.execute(select(ShareItem))).scalar_one()
        recipients = (await session.execute(select(ShareRecipient))).scalars().all()
        audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "share.created"))
        ).scalar_one()
        outbox_event = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.event_type == "audit.share.created")
            )
        ).scalar_one()

    assert share.share_type == "external"
    assert share.token_hash == hash_token(result.raw_token)
    assert result.raw_token not in {share.token_hash, share.passcode_hash}
    assert share.passcode_hash is not None
    assert verify_password("123456", share.passcode_hash)
    assert share.max_views == 5
    assert share.max_downloads == 2
    assert item.node_id == node_id
    assert recipients == []
    assert audit.request_id == "req_share_external"
    assert audit.metadata_json["has_passcode"] is True
    assert audit.metadata_json["item_count"] == 1
    assert outbox_event.aggregate_id == audit.id


@pytest.mark.asyncio
async def test_create_internal_share_requires_and_stores_recipients(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="internal-share-space")
    file_payload = await create_instant_file(
        client,
        session_factory,
        token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="内部分享.txt",
        content_hash="b" * 64,
    )
    node_id = UUID(file_payload["node_id"])

    async with session_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        service = build_share_service(session)
        with pytest.raises(ApiError) as missing_recipient_error:
            await service.create_share(
                current_user=user,
                share_type=SHARE_TYPE_INTERNAL,
                root_node_id=node_id,
            )
        await session.rollback()
        user = (await session.execute(select(User))).scalar_one()

        result = await service.create_share(
            current_user=user,
            share_type=SHARE_TYPE_INTERNAL,
            root_node_id=node_id,
            recipients=[
                ShareRecipientInput(subject_type="user", subject_id=user.id),
            ],
        )

    assert missing_recipient_error.value.code == "SHARE_RECIPIENT_REQUIRED"
    assert result.raw_token is None
    async with session_factory() as session:
        share = (await session.execute(select(Share))).scalar_one()
        recipient = (await session.execute(select(ShareRecipient))).scalar_one()

    assert share.share_type == "internal"
    assert share.token_hash is None
    assert recipient.subject_type == "user"
    assert recipient.subject_id == user.id


@pytest.mark.asyncio
async def test_revoke_share_updates_status_and_audit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="revoke-share-space")
    file_payload = await create_instant_file(
        client,
        session_factory,
        token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="撤销分享.txt",
        content_hash="c" * 64,
    )

    async with session_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        service = build_share_service(
            session,
            audit_service=AuditService(repository=AuditRepository(session)),
        )
        result = await service.create_share(
            current_user=user,
            share_type=SHARE_TYPE_EXTERNAL,
            root_node_id=UUID(file_payload["node_id"]),
        )

    async with session_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        service = build_share_service(
            session,
            audit_service=AuditService(repository=AuditRepository(session)),
        )
        await service.revoke_share(
            current_user=user,
            share_id=result.id,
            audit_context=AuditContext(request_id="req_share_revoke"),
        )

    async with session_factory() as session:
        share = (await session.execute(select(Share))).scalar_one()
        audits = (
            (await session.execute(select(AuditLog).where(AuditLog.action == "share.revoked")))
            .scalars()
            .all()
        )
        revoke_outbox = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.event_type == "audit.share.revoked")
            )
        ).scalar_one()

    assert share.status == "revoked"
    assert share.revoked_by is not None
    assert share.revoked_at is not None
    assert len(audits) == 1
    assert audits[0].request_id == "req_share_revoke"
    assert revoke_outbox.aggregate_id == audits[0].id


@pytest.mark.asyncio
async def test_share_detail_and_revoke_only_allow_creator(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="share-owner-space")
    await create_second_user(session_factory)
    file_payload = await create_instant_file(
        client,
        session_factory,
        token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="分享归属.txt",
        content_hash="d" * 64,
    )

    async with session_factory() as session:
        creator = (await session.execute(select(User).where(User.username == "admin"))).scalar_one()
        service = build_share_service(session)
        result = await service.create_share(
            current_user=creator,
            share_type=SHARE_TYPE_EXTERNAL,
            root_node_id=UUID(file_payload["node_id"]),
        )

    async with session_factory() as session:
        other_user = (
            await session.execute(select(User).where(User.username == "member"))
        ).scalar_one()
        service = build_share_service(session)
        with pytest.raises(ApiError) as detail_error:
            await service.get_share_detail(current_user=other_user, share_id=result.id)
        with pytest.raises(ApiError) as revoke_error:
            await service.revoke_share(current_user=other_user, share_id=result.id)

    assert detail_error.value.code == "SHARE_NOT_FOUND"
    assert revoke_error.value.code == "SHARE_NOT_FOUND"
    async with session_factory() as session:
        share = (await session.execute(select(Share))).scalar_one()

    assert share.status == "active"


@pytest.mark.asyncio
async def test_create_share_requires_node_share_permission(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="share-permission-space")
    await create_second_user(session_factory)
    await add_space_member(
        session_factory,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        role="viewer",
    )
    file_payload = await create_instant_file(
        client,
        session_factory,
        token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="权限分享.txt",
        content_hash="e" * 64,
    )

    async with session_factory() as session:
        viewer = (await session.execute(select(User).where(User.username == "member"))).scalar_one()
        service = build_share_service(session)
        with pytest.raises(ApiError) as exc_info:
            await service.create_share(
                current_user=viewer,
                share_type=SHARE_TYPE_EXTERNAL,
                root_node_id=UUID(file_payload["node_id"]),
            )

    assert exc_info.value.code == "NODE_NOT_FOUND"


@pytest.mark.asyncio
async def test_create_share_rejects_item_from_other_space(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="share-item-space")
    other_space = await create_space(client, token, slug="share-item-other-space")
    root_file = await create_instant_file(
        client,
        session_factory,
        token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="分享范围.txt",
        content_hash="f" * 64,
    )
    other_file = await create_instant_file(
        client,
        session_factory,
        token,
        tenant_id=str(other_space["tenant_id"]),
        space_id=str(other_space["id"]),
        parent_id=str(other_space["root_node_id"]),
        file_name="跨空间.txt",
        content_hash="1" * 64,
    )

    async with session_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        service = build_share_service(session)
        with pytest.raises(ApiError) as exc_info:
            await service.create_share(
                current_user=user,
                share_type=SHARE_TYPE_EXTERNAL,
                root_node_id=UUID(root_file["node_id"]),
                item_node_ids=[UUID(other_file["node_id"])],
            )

    assert exc_info.value.code == "NODE_NOT_FOUND"
    async with session_factory() as session:
        shares = (await session.execute(select(Share))).scalars().all()
        items = (await session.execute(select(ShareItem))).scalars().all()

    assert shares == []
    assert items == []
