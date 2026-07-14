from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings


def create_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    engine_options: dict[str, object] = {"pool_pre_ping": True}
    if settings.database_pool_mode == "null":
        engine_options["poolclass"] = NullPool
    else:
        engine_options.update(
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout_seconds,
        )
    engine = create_async_engine(settings.database_url, **engine_options)
    return async_sessionmaker(engine, expire_on_commit=False)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return create_session_factory(get_settings())


async def get_db_session() -> AsyncIterator[AsyncSession]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session
