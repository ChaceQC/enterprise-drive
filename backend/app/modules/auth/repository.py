from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import AuthSession, Tenant, User


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_tenant_by_slug(self, slug: str) -> Tenant | None:
        result = await self.session.execute(select(Tenant).where(Tenant.slug == slug))
        return result.scalar_one_or_none()

    async def list_tenant_ids(self) -> list[UUID]:
        result = await self.session.execute(
            select(Tenant.id).order_by(Tenant.created_at, Tenant.id)
        )
        return list(result.scalars().all())

    async def create_tenant(self, *, slug: str, name: str) -> Tenant:
        tenant = Tenant(slug=slug, name=name)
        self.session.add(tenant)
        await self.session.flush()
        return tenant

    async def get_user_by_login(self, *, tenant_id: UUID, login: str) -> User | None:
        normalized_login = login.lower()
        result = await self.session.execute(
            select(User).where(
                User.tenant_id == tenant_id,
                or_(
                    func.lower(User.username) == normalized_login,
                    func.lower(User.email) == normalized_login,
                ),
            )
        )
        return result.scalar_one_or_none()

    async def get_user_by_id(self, *, tenant_id: UUID, user_id: UUID) -> User | None:
        result = await self.session.execute(
            select(User).where(User.tenant_id == tenant_id, User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def create_user(
        self,
        *,
        tenant_id: UUID,
        username: str,
        email: str | None,
        display_name: str,
        password_hash: str,
        is_super_admin: bool = False,
        must_change_password: bool = False,
    ) -> User:
        user = User(
            tenant_id=tenant_id,
            username=username,
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            is_super_admin=is_super_admin,
            must_change_password=must_change_password,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def create_auth_session(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        family_id: UUID,
        token_hash: str,
        csrf_token_hash: str,
        expires_at: datetime,
    ) -> AuthSession:
        auth_session = AuthSession(
            tenant_id=tenant_id,
            user_id=user_id,
            family_id=family_id,
            token_hash=token_hash,
            csrf_token_hash=csrf_token_hash,
            expires_at=expires_at,
        )
        self.session.add(auth_session)
        await self.session.flush()
        return auth_session

    async def get_auth_session_by_token_hash(self, token_hash: str) -> AuthSession | None:
        result = await self.session.execute(
            select(AuthSession).where(AuthSession.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def mark_auth_session_rotated(
        self,
        *,
        old_session_id: UUID,
        new_session_id: UUID,
        used_at: datetime,
    ) -> None:
        await self.session.execute(
            update(AuthSession)
            .where(AuthSession.id == old_session_id)
            .values(used_at=used_at, replaced_by_id=new_session_id)
        )

    async def revoke_auth_session_family(
        self,
        *,
        family_id: UUID,
        revoked_at: datetime,
        reason: str,
    ) -> None:
        await self.session.execute(
            update(AuthSession)
            .where(AuthSession.family_id == family_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=revoked_at, revoked_reason=reason)
        )

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
