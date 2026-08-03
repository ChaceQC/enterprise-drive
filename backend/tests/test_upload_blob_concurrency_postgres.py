from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.modules.auth.models import Tenant
from app.modules.file.models import FileBlob
from app.modules.upload.repository import UploadRepository

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def postgres_url() -> str:
    if os.getenv("DRIVE_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("set DRIVE_RUN_POSTGRES_TESTS=1 to run PostgreSQL integration tests")
    database_url = os.getenv("DRIVE_TEST_POSTGRES_URL")
    if not database_url:
        pytest.fail("DRIVE_TEST_POSTGRES_URL is required")
    return database_url


@pytest_asyncio.fixture
async def postgres_session_factory(
    postgres_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text("truncate table tenants cascade"))

    yield async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.execute(text("truncate table tenants cascade"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_same_hash_first_upload_race_reuses_one_blob(
    postgres_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with postgres_session_factory() as session:
        tenant = Tenant(slug="upload-race", name="上传竞争租户")
        session.add(tenant)
        await session.commit()
        tenant_id = tenant.id

    content_hash = "a" * 64

    async def resolve_reference() -> bool:
        async with postgres_session_factory() as session:
            repository = UploadRepository(session)
            resolution = await repository.resolve_file_blob_reference(
                tenant_id=tenant_id,
                hash_algo="sha256",
                content_hash=content_hash,
                size_bytes=1024,
                storage_key=f"objects/{tenant_id}/aa/{content_hash}",
                mime_type="application/octet-stream",
            )
            if not resolution.created:
                referenced = await repository.increment_blob_ref_count(
                    tenant_id=tenant_id,
                    blob_id=resolution.blob.id,
                )
                assert referenced is True
            await repository.commit()
            return resolution.created

    created_results = await asyncio.gather(resolve_reference(), resolve_reference())

    async with postgres_session_factory() as session:
        blob_count = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(FileBlob)
                    .where(
                        FileBlob.tenant_id == tenant_id,
                        FileBlob.content_hash == content_hash,
                    )
                )
            ).scalar_one()
        )
        blob = (
            await session.execute(
                select(FileBlob).where(
                    FileBlob.tenant_id == tenant_id,
                    FileBlob.content_hash == content_hash,
                )
            )
        ).scalar_one()

    assert sorted(created_results) == [False, True]
    assert blob_count == 1
    assert blob.ref_count == 2
