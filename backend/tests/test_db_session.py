from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.db.session import create_session_factory


def test_null_pool_session_factory_can_be_reused_across_event_loops() -> None:
    session_factory = create_session_factory(
        Settings(
            environment="test",
            secret_key="test-secret",
            database_url="sqlite+aiosqlite:///:memory:",
            database_pool_mode="null",
        )
    )

    assert isinstance(session_factory.kw["bind"].pool, NullPool)
    assert asyncio.run(_select_one(session_factory)) == 1
    assert asyncio.run(_select_one(session_factory)) == 1
    asyncio.run(session_factory.kw["bind"].dispose())


async def _select_one(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        value = await session.scalar(text("SELECT 1"))
    assert isinstance(value, int)
    return value
