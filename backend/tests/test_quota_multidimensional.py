from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.file.models import FileBlob, Node
from app.modules.quota.models import QuotaAccount, QuotaLedger, QuotaPolicy
from tests.helpers import (
    client as client,
)
from tests.helpers import (
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


async def _seed_blob(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    size_bytes: int,
    content_hash: str,
) -> None:
    async with session_factory() as session:
        session.add(
            FileBlob(
                tenant_id=tenant_id,
                hash_algo="sha256",
                content_hash=content_hash,
                size_bytes=size_bytes,
                storage_key=f"objects/test/{content_hash[:2]}/{content_hash}",
                mime_type="application/octet-stream",
                ref_count=0,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_upload_reserves_and_releases_space_user_and_tenant_quota(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    settings.default_space_quota_bytes = 4096
    settings.default_user_quota_bytes = 1024
    settings.default_tenant_quota_bytes = 2048
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="quota-dimensions")
    tenant_id = UUID(str(space["tenant_id"]))
    await _seed_blob(
        session_factory,
        tenant_id=tenant_id,
        size_bytes=1024,
        content_hash="a" * 64,
    )

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "维度.txt",
            "size_bytes": 1024,
            "content_hash": "a" * 64,
            "hash_algo": "sha256",
        },
    )
    assert response.status_code == 201
    node_id = UUID(response.json()["node_id"])

    async with session_factory() as session:
        accounts = (
            (await session.execute(select(QuotaAccount).order_by(QuotaAccount.owner_type)))
            .scalars()
            .all()
        )
        ledgers = (await session.execute(select(QuotaLedger))).scalars().all()
    assert {account.owner_type for account in accounts} == {"space", "tenant", "user"}
    assert {account.used_bytes for account in accounts} == {1024}
    assert len(ledgers) == 3

    denied = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "第二个.txt",
            "size_bytes": 1024,
            "content_hash": "a" * 64,
            "hash_algo": "sha256",
        },
    )
    assert denied.status_code == 422
    assert denied.json()["code"] == "QUOTA_EXCEEDED"

    assert (
        await client.delete(
            f"/api/v1/files/{node_id}",
            headers={"X-CSRF-Token": csrf_token},
        )
    ).status_code == 200
    assert (
        await client.delete(
            f"/api/v1/files/{node_id}/purge",
            headers={"X-CSRF-Token": csrf_token},
        )
    ).status_code == 200

    async with session_factory() as session:
        accounts = (await session.execute(select(QuotaAccount))).scalars().all()
        ledgers = (await session.execute(select(QuotaLedger))).scalars().all()
        deleted_node = (
            await session.execute(select(Node).where(Node.id == node_id))
        ).scalar_one_or_none()
        assert deleted_node is None
    assert {account.used_bytes for account in accounts} == {0}
    assert len(ledgers) == 6
    assert sum(ledger.delta_bytes for ledger in ledgers) == 0


@pytest.mark.asyncio
async def test_quota_policy_rejects_matching_file_before_creating_usage(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="quota-policy")
    tenant_id = UUID(str(space["tenant_id"]))
    async with session_factory() as session:
        session.add(
            QuotaPolicy(
                tenant_id=tenant_id,
                name="密级文件",
                priority=1,
                limit_bytes=10 * 1024,
                max_file_size_bytes=512,
                extensions=[".secret"],
                mime_prefixes=[],
            )
        )
        await session.commit()

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "secret.secret",
            "size_bytes": 1024,
            "content_hash": "b" * 64,
            "hash_algo": "sha256",
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "QUOTA_POLICY_FILE_SIZE_EXCEEDED"

    async with session_factory() as session:
        policy_accounts = (
            (await session.execute(select(QuotaAccount).where(QuotaAccount.owner_type == "policy")))
            .scalars()
            .all()
        )
        ledgers = (await session.execute(select(QuotaLedger))).scalars().all()
    assert policy_accounts == []
    assert ledgers == []
