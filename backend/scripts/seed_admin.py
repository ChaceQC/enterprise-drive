from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService


async def main() -> None:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = AuthService(repository=AuthRepository(session), settings=settings)
        result = await service.seed_admin()

    print(
        "管理员 seed 完成："
        f"tenant={result.tenant_slug}, username={result.username}, "
        f"tenant_created={result.tenant_created}, user_created={result.user_created}"
    )


if __name__ == "__main__":
    asyncio.run(main())
