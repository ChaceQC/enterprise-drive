from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.security import create_session_token, ensure_utc, hash_token, utc_now
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.auth.schemas import UserProfileResponse
from app.modules.auth.service import AuthService
from app.modules.device.models import DesktopDevice, DeviceSession
from app.modules.device.repository import DeviceRepository
from app.modules.device.schemas import (
    DeviceListResponse,
    DeviceResponse,
    DeviceRevokeResponse,
    DeviceSessionResponse,
)


@dataclass(frozen=True)
class AuthenticatedDevice:
    user: User
    device: DesktopDevice
    session: DeviceSession


class DeviceSessionService:
    def __init__(
        self,
        *,
        repository: DeviceRepository,
        auth_service: AuthService,
        settings: Settings,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.auth_service = auth_service
        self.settings = settings
        self.audit_service = audit_service

    async def register(
        self,
        *,
        tenant_slug: str,
        username: str,
        password: str,
        installation_id: UUID,
        device_name: str,
        platform: str,
        client_version: str,
        audit_context: AuditContext | None = None,
    ) -> DeviceSessionResponse:
        user = await self.auth_service.authenticate_password(
            tenant_slug=tenant_slug,
            username=username,
            password=password,
            audit_action="auth.device.register",
            allow_password_change_required=False,
            audit_context=audit_context,
        )
        now = utc_now()
        installation_id_hash = hash_token(str(installation_id))
        device = await self.repository.get_device_by_installation_hash(
            tenant_id=user.tenant_id,
            user_id=user.id,
            installation_id_hash=installation_id_hash,
        )
        if device is None:
            device = await self.repository.create_device(
                tenant_id=user.tenant_id,
                user_id=user.id,
                installation_id_hash=installation_id_hash,
                name=device_name.strip(),
                platform=platform,
                client_version=client_version,
                now=now,
            )
        else:
            await self.repository.revoke_device_sessions(
                tenant_id=user.tenant_id,
                user_id=user.id,
                device_id=device.id,
                revoked_at=now,
                reason="device_reauthenticated",
            )
            device.name = device_name.strip()
            device.platform = platform
            device.client_version = client_version
            device.status = "active"
            device.last_seen_at = now
            device.revoked_at = None
            device.revoked_reason = None

        response = await self._issue_session(user=user, device=device, family_id=uuid4())
        await self._record_event(
            AuditEvent(
                tenant_id=user.tenant_id,
                actor_id=user.id,
                action="auth.device.registered",
                resource_type="desktop_device",
                resource_id=device.id,
                result="allowed",
                metadata={
                    "platform": platform,
                    "client_version": client_version,
                },
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        return response

    async def rotate(
        self,
        *,
        raw_token: str,
        client_version: str | None,
        audit_context: AuditContext | None = None,
    ) -> DeviceSessionResponse:
        stored_session = await self.repository.get_session_by_token_hash(hash_token(raw_token))
        now = utc_now()
        if stored_session is None:
            raise ApiError("DEVICE_SESSION_INVALID", "设备会话无效", status_code=401)

        if stored_session.revoked_at is not None or stored_session.replaced_by_id is not None:
            await self.repository.revoke_session_family(
                family_id=stored_session.family_id,
                revoked_at=now,
                reason="reuse_detected",
            )
            await self._record_event(
                AuditEvent(
                    tenant_id=stored_session.tenant_id,
                    actor_id=stored_session.user_id,
                    action="auth.device.session_reused",
                    resource_type="device_session",
                    resource_id=stored_session.id,
                    result="denied",
                    risk_level="high",
                    metadata={"family_id": str(stored_session.family_id)},
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
            raise ApiError("DEVICE_SESSION_REUSED", "设备会话已失效", status_code=401)

        if ensure_utc(stored_session.expires_at) <= now:
            await self.repository.revoke_session_family(
                family_id=stored_session.family_id,
                revoked_at=now,
                reason="expired",
            )
            await self.repository.commit()
            raise ApiError("DEVICE_SESSION_EXPIRED", "设备会话已过期", status_code=401)

        authenticated = await self._load_active_identity(stored_session)
        if client_version is not None:
            authenticated.device.client_version = client_version
        authenticated.device.last_seen_at = now
        response = await self._issue_session(
            user=authenticated.user,
            device=authenticated.device,
            family_id=stored_session.family_id,
        )
        new_session = await self.repository.get_session_by_token_hash(
            hash_token(response.access_token)
        )
        if new_session is None:
            raise ApiError("DEVICE_SESSION_INVALID", "设备会话创建失败", status_code=500)
        await self.repository.mark_session_rotated(
            old_session_id=stored_session.id,
            new_session_id=new_session.id,
            used_at=now,
        )
        await self._record_event(
            AuditEvent(
                tenant_id=stored_session.tenant_id,
                actor_id=stored_session.user_id,
                action="auth.device.session_rotated",
                resource_type="device_session",
                resource_id=stored_session.id,
                result="allowed",
                metadata={"device_id": str(stored_session.device_id)},
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        return response

    async def authenticate(self, *, raw_token: str) -> AuthenticatedDevice:
        stored_session = await self.repository.get_session_by_token_hash(hash_token(raw_token))
        if stored_session is None:
            raise ApiError("DEVICE_SESSION_INVALID", "设备会话无效", status_code=401)
        if stored_session.revoked_at is not None or stored_session.replaced_by_id is not None:
            raise ApiError("DEVICE_SESSION_REVOKED", "设备会话已吊销", status_code=401)
        if ensure_utc(stored_session.expires_at) <= utc_now():
            raise ApiError("DEVICE_SESSION_EXPIRED", "设备会话已过期", status_code=401)
        return await self._load_active_identity(stored_session)

    async def list_devices(
        self,
        *,
        current_user: User,
        current_device_id: UUID | None,
    ) -> DeviceListResponse:
        devices = await self.repository.list_devices(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
        )
        return DeviceListResponse(
            items=[
                self._device_response(device, current=device.id == current_device_id)
                for device in devices
            ]
        )

    async def revoke_device(
        self,
        *,
        current_user: User,
        device_id: UUID,
        audit_context: AuditContext | None = None,
    ) -> DeviceRevokeResponse:
        device = await self.repository.get_device(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            device_id=device_id,
        )
        if device is None:
            raise ApiError("DEVICE_NOT_FOUND", "设备不存在或无权访问", status_code=404)
        now = utc_now()
        device.status = "revoked"
        device.revoked_at = now
        device.revoked_reason = "user_revoked"
        await self.repository.revoke_device_sessions(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            device_id=device.id,
            revoked_at=now,
            reason="user_revoked",
        )
        await self._record_event(
            AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action="auth.device.revoked",
                resource_type="desktop_device",
                resource_id=device.id,
                result="allowed",
                metadata={},
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        return DeviceRevokeResponse(revoked_device_ids=[device.id])

    async def revoke_all(
        self,
        *,
        current_user: User,
        audit_context: AuditContext | None = None,
    ) -> DeviceRevokeResponse:
        devices = await self.repository.list_devices(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
        )
        now = utc_now()
        revoked_ids = [device.id for device in devices if device.status != "revoked"]
        for device in devices:
            device.status = "revoked"
            device.revoked_at = now
            device.revoked_reason = "user_revoked_all"
        await self.repository.revoke_all_sessions(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            revoked_at=now,
            reason="user_revoked_all",
        )
        await self._record_event(
            AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action="auth.device.revoked_all",
                resource_type="user",
                resource_id=current_user.id,
                result="allowed",
                metadata={"revoked_count": len(revoked_ids)},
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        return DeviceRevokeResponse(revoked_device_ids=revoked_ids)

    async def _issue_session(
        self,
        *,
        user: User,
        device: DesktopDevice,
        family_id: UUID,
    ) -> DeviceSessionResponse:
        raw_token = create_session_token()
        expires_at = utc_now() + timedelta(hours=self.settings.device_session_hours)
        await self.repository.create_session(
            tenant_id=user.tenant_id,
            user_id=user.id,
            device_id=device.id,
            family_id=family_id,
            token_hash=hash_token(raw_token),
            expires_at=expires_at,
        )
        return DeviceSessionResponse(
            access_token=raw_token,
            expires_at=expires_at,
            device=self._device_response(device, current=True),
            user=self._profile_response(user),
        )

    async def _load_active_identity(
        self,
        stored_session: DeviceSession,
    ) -> AuthenticatedDevice:
        device = await self.repository.get_device(
            tenant_id=stored_session.tenant_id,
            user_id=stored_session.user_id,
            device_id=stored_session.device_id,
        )
        user = await self.auth_service.get_active_user(
            tenant_id=stored_session.tenant_id,
            user_id=stored_session.user_id,
        )
        if device is None or device.status != "active" or user is None:
            raise ApiError("DEVICE_SESSION_REVOKED", "设备会话已吊销", status_code=401)
        return AuthenticatedDevice(user=user, device=device, session=stored_session)

    @staticmethod
    def _device_response(device: DesktopDevice, *, current: bool) -> DeviceResponse:
        return DeviceResponse.model_validate(device).model_copy(update={"current": current})

    @staticmethod
    def _profile_response(user: User) -> UserProfileResponse:
        return UserProfileResponse(
            id=user.id,
            tenant_id=user.tenant_id,
            username=user.username,
            email=user.email,
            display_name=user.display_name,
            is_super_admin=user.is_super_admin,
            must_change_password=user.must_change_password,
        )

    async def _record_event(
        self,
        event: AuditEvent,
        *,
        audit_context: AuditContext | None,
    ) -> None:
        if self.audit_service is None:
            return
        await self.audit_service.record(event=event, context=audit_context or AuditContext())
