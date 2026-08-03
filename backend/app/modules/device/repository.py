from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.device.models import DesktopDevice, DeviceSession


class DeviceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_device_by_installation_hash(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        installation_id_hash: str,
    ) -> DesktopDevice | None:
        result = await self.session.execute(
            select(DesktopDevice).where(
                DesktopDevice.tenant_id == tenant_id,
                DesktopDevice.user_id == user_id,
                DesktopDevice.installation_id_hash == installation_id_hash,
            )
        )
        return result.scalar_one_or_none()

    async def get_device(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        device_id: UUID,
    ) -> DesktopDevice | None:
        result = await self.session.execute(
            select(DesktopDevice).where(
                DesktopDevice.tenant_id == tenant_id,
                DesktopDevice.user_id == user_id,
                DesktopDevice.id == device_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_device(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        installation_id_hash: str,
        name: str,
        platform: str,
        client_version: str,
        now: datetime,
    ) -> DesktopDevice:
        device = DesktopDevice(
            tenant_id=tenant_id,
            user_id=user_id,
            installation_id_hash=installation_id_hash,
            name=name,
            platform=platform,
            client_version=client_version,
            status="active",
            last_seen_at=now,
        )
        self.session.add(device)
        await self.session.flush()
        return device

    async def list_devices(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
    ) -> list[DesktopDevice]:
        result = await self.session.execute(
            select(DesktopDevice)
            .where(
                DesktopDevice.tenant_id == tenant_id,
                DesktopDevice.user_id == user_id,
            )
            .order_by(DesktopDevice.last_seen_at.desc(), DesktopDevice.id.desc())
        )
        return list(result.scalars().all())

    async def create_session(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        device_id: UUID,
        family_id: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> DeviceSession:
        device_session = DeviceSession(
            tenant_id=tenant_id,
            user_id=user_id,
            device_id=device_id,
            family_id=family_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.session.add(device_session)
        await self.session.flush()
        return device_session

    async def get_session_by_token_hash(self, token_hash: str) -> DeviceSession | None:
        result = await self.session.execute(
            select(DeviceSession).where(DeviceSession.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def mark_session_rotated(
        self,
        *,
        old_session_id: UUID,
        new_session_id: UUID,
        used_at: datetime,
    ) -> None:
        await self.session.execute(
            update(DeviceSession)
            .where(DeviceSession.id == old_session_id)
            .values(used_at=used_at, replaced_by_id=new_session_id)
        )

    async def revoke_session_family(
        self,
        *,
        family_id: UUID,
        revoked_at: datetime,
        reason: str,
    ) -> None:
        await self.session.execute(
            update(DeviceSession)
            .where(
                DeviceSession.family_id == family_id,
                DeviceSession.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at, revoked_reason=reason)
        )

    async def revoke_device_sessions(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        device_id: UUID,
        revoked_at: datetime,
        reason: str,
    ) -> None:
        await self.session.execute(
            update(DeviceSession)
            .where(
                DeviceSession.tenant_id == tenant_id,
                DeviceSession.user_id == user_id,
                DeviceSession.device_id == device_id,
                DeviceSession.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at, revoked_reason=reason)
        )

    async def revoke_all_sessions(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        revoked_at: datetime,
        reason: str,
    ) -> None:
        await self.session.execute(
            update(DeviceSession)
            .where(
                DeviceSession.tenant_id == tenant_id,
                DeviceSession.user_id == user_id,
                DeviceSession.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at, revoked_reason=reason)
        )

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
