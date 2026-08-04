from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.infrastructure.captcha.base import CaptchaContext
from app.modules.audit.models import AuditLog
from app.modules.auth.models import AuthSession, User
from app.modules.device.models import DeviceSession
from tests.helpers import client as client
from tests.helpers import create_second_user, login, seed_admin
from tests.helpers import session_factory as session_factory
from tests.helpers import settings as settings
from tests.helpers import storage_adapter as storage_adapter

_MEMBER_PASSWORD = "Member-Password-2026!"
_RESET_PASSWORD = "Reset-Password-2026!"
_CHANGED_PASSWORD = "Changed-Password-2026!"


class StaticCaptchaVerifier:
    enabled = True

    def __init__(self) -> None:
        self.calls: list[tuple[str | None, CaptchaContext]] = []

    async def verify(
        self,
        *,
        token: str | None,
        context: CaptchaContext,
    ) -> bool:
        self.calls.append((token, context))
        return token == "captcha-ok"


@pytest.fixture
def captcha_verifier() -> StaticCaptchaVerifier:
    return StaticCaptchaVerifier()


def _configure_account_security(settings: Settings) -> None:
    settings.login_failure_lock_threshold = 3
    settings.login_failure_window_seconds = 300
    settings.login_lock_seconds = 60
    settings.login_delay_base_seconds = 0
    settings.login_delay_max_seconds = 0
    settings.login_captcha_after_failures = 1
    settings.password_min_length = 12
    settings.password_require_uppercase = True
    settings.password_require_lowercase = True
    settings.password_require_digit = True
    settings.password_require_special = True


@pytest.mark.asyncio
async def test_failed_login_requires_captcha_locks_and_admin_unlocks(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    captcha_verifier: StaticCaptchaVerifier,
) -> None:
    _configure_account_security(settings)
    await seed_admin(session_factory, settings)
    member_id = await create_second_user(session_factory, password=_MEMBER_PASSWORD)
    payload = {
        "tenant_slug": "default",
        "username": "member",
        "password": "wrong-password",
    }

    first = await client.post("/api/v1/auth/login", json=payload)
    captcha_required = await client.post("/api/v1/auth/login", json=payload)
    second = await client.post(
        "/api/v1/auth/login",
        json={**payload, "captcha_token": "captcha-ok"},
    )
    locked = await client.post(
        "/api/v1/auth/login",
        json={**payload, "captcha_token": "captcha-ok"},
    )
    correct_while_locked = await client.post(
        "/api/v1/auth/login",
        json={
            **payload,
            "password": _MEMBER_PASSWORD,
            "captcha_token": "captcha-ok",
        },
    )

    assert first.status_code == 401
    assert captcha_required.status_code == 403
    assert captcha_required.json()["code"] == "CAPTCHA_REQUIRED"
    assert second.status_code == 401
    assert locked.status_code == 423
    assert locked.json()["code"] == "ACCOUNT_LOCKED"
    assert correct_while_locked.status_code == 423
    assert [token for token, _ in captcha_verifier.calls] == [
        None,
        "captcha-ok",
        "captcha-ok",
    ]

    async with session_factory() as session:
        member = await session.get(User, member_id)
        assert member is not None
        assert member.failed_login_attempts == 3
        assert member.locked_until is not None
        assert member.lock_reason == "failed_login_threshold"
        member_version = member.version

    admin_csrf = await login(client)
    unlocked = await client.post(
        f"/api/v1/admin/users/{member_id}/unlock",
        headers={"X-CSRF-Token": admin_csrf},
        json={"expected_version": member_version},
    )
    assert unlocked.status_code == 200
    assert unlocked.json()["failed_login_attempts"] == 0
    assert unlocked.json()["locked"] is False

    member_login = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "default",
            "username": "member",
            "password": _MEMBER_PASSWORD,
        },
    )
    assert member_login.status_code == 200

    async with session_factory() as session:
        audit_actions = set(
            (
                await session.execute(
                    select(AuditLog.action).where(
                        AuditLog.action.in_({"auth.account.locked", "admin.user.unlocked"})
                    )
                )
            )
            .scalars()
            .all()
        )
    assert audit_actions == {"auth.account.locked", "admin.user.unlocked"}


@pytest.mark.asyncio
async def test_forced_password_change_blocks_business_and_revokes_current_session(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    _configure_account_security(settings)
    await seed_admin(session_factory, settings)
    member_id = await create_second_user(session_factory, password=_MEMBER_PASSWORD)
    async with session_factory() as session:
        member = await session.get(User, member_id)
        assert member is not None
        member.must_change_password = True
        await session.commit()

    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "default",
            "username": "member",
            "password": _MEMBER_PASSWORD,
        },
    )
    assert login_response.status_code == 200
    csrf_token = client.cookies.get(settings.csrf_cookie_name)
    assert csrf_token is not None

    blocked = await client.get("/api/v1/device-sessions")
    profile = await client.get("/api/v1/auth/me")
    policy = await client.get("/api/v1/auth/password/policy")
    changed = await client.post(
        "/api/v1/auth/password/change",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "current_password": _MEMBER_PASSWORD,
            "new_password": _CHANGED_PASSWORD,
        },
    )

    assert blocked.status_code == 403
    assert blocked.json()["code"] == "PASSWORD_CHANGE_REQUIRED"
    assert profile.status_code == 200
    assert profile.json()["must_change_password"] is True
    assert policy.status_code == 200
    assert policy.json()["require_special"] is True
    assert changed.status_code == 200
    assert changed.json()["reauthentication_required"] is True
    assert client.cookies.get(settings.session_cookie_name) is None

    old_password = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "default",
            "username": "member",
            "password": _MEMBER_PASSWORD,
        },
    )
    new_password = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "default",
            "username": "member",
            "password": _CHANGED_PASSWORD,
        },
    )
    assert old_password.status_code == 401
    assert new_password.status_code == 200

    async with session_factory() as session:
        member = await session.get(User, member_id)
        assert member is not None
        assert member.must_change_password is False
        assert member.password_changed_at is not None
        revoked = (
            (
                await session.execute(
                    select(AuthSession).where(
                        AuthSession.user_id == member_id,
                        AuthSession.revoked_reason == "password_changed",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(revoked) == 1


@pytest.mark.asyncio
async def test_user_lists_and_revokes_only_owned_browser_sessions(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    _configure_account_security(settings)
    await seed_admin(session_factory, settings)
    member_id = await create_second_user(session_factory, password=_MEMBER_PASSWORD)

    await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "default",
            "username": "member",
            "password": _MEMBER_PASSWORD,
        },
    )
    await client.post(
        "/api/v1/auth/login",
        headers={"User-Agent": "second-browser"},
        json={
            "tenant_slug": "default",
            "username": "member",
            "password": _MEMBER_PASSWORD,
        },
    )
    member_session_token = client.cookies.get(settings.session_cookie_name)
    member_csrf = client.cookies.get(settings.csrf_cookie_name)
    assert member_session_token is not None
    assert member_csrf is not None

    sessions = await client.get("/api/v1/auth/sessions")
    assert sessions.status_code == 200
    assert len(sessions.json()["items"]) == 2
    current = next(item for item in sessions.json()["items"] if item["current"])
    other = next(item for item in sessions.json()["items"] if not item["current"])
    assert current["user_agent"] == "second-browser"

    await login(client)
    async with session_factory() as session:
        admin_session_id = (
            (
                await session.execute(
                    select(AuthSession.id)
                    .join(User, User.id == AuthSession.user_id)
                    .where(
                        User.username == settings.admin_username,
                        AuthSession.revoked_at.is_(None),
                    )
                    .order_by(AuthSession.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
    assert admin_session_id is not None

    client.cookies.clear()
    client.cookies.set(
        settings.session_cookie_name,
        member_session_token,
        domain="testserver.local",
        path="/",
    )
    client.cookies.set(
        settings.csrf_cookie_name,
        member_csrf,
        domain="testserver.local",
        path="/",
    )
    foreign = await client.delete(
        f"/api/v1/auth/sessions/{admin_session_id}",
        headers={"X-CSRF-Token": member_csrf},
    )
    revoked_other = await client.delete(
        f"/api/v1/auth/sessions/{other['id']}",
        headers={"X-CSRF-Token": member_csrf},
    )
    assert foreign.status_code == 404
    assert revoked_other.status_code == 200
    assert revoked_other.json()["current_session_revoked"] is False
    assert client.cookies.get(settings.session_cookie_name) == member_session_token

    revoked_current = await client.delete(
        f"/api/v1/auth/sessions/{current['id']}",
        headers={"X-CSRF-Token": member_csrf},
    )
    assert revoked_current.status_code == 200
    assert revoked_current.json()["current_session_revoked"] is True
    assert client.cookies.get(settings.session_cookie_name) is None

    async with session_factory() as session:
        active_member_sessions = (
            (
                await session.execute(
                    select(AuthSession).where(
                        AuthSession.user_id == member_id,
                        AuthSession.revoked_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
    assert active_member_sessions == []


@pytest.mark.asyncio
async def test_admin_password_reset_revokes_browser_and_device_sessions(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    _configure_account_security(settings)
    await seed_admin(session_factory, settings)
    member_id = await create_second_user(session_factory, password=_MEMBER_PASSWORD)

    member_login = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "default",
            "username": "member",
            "password": _MEMBER_PASSWORD,
        },
    )
    assert member_login.status_code == 200
    member_session = client.cookies.get(settings.session_cookie_name)
    member_csrf = client.cookies.get(settings.csrf_cookie_name)
    assert member_session is not None
    assert member_csrf is not None

    device = await client.post(
        "/api/v1/device-sessions/register",
        json={
            "tenant_slug": "default",
            "username": "member",
            "password": _MEMBER_PASSWORD,
            "installation_id": str(uuid4()),
            "device_name": "Sprint 11 device",
            "platform": "windows",
            "client_version": "0.8.0",
        },
    )
    assert device.status_code == 200
    device_token = device.json()["access_token"]

    admin_csrf = await login(client)
    async with session_factory() as session:
        member = await session.get(User, member_id)
        assert member is not None
        member_version = member.version

    weak_reset = await client.post(
        f"/api/v1/admin/users/{member_id}/password-reset",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "expected_version": member_version,
            "new_password": "lowercase-password-2026!",
        },
    )
    reset = await client.post(
        f"/api/v1/admin/users/{member_id}/password-reset",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "expected_version": member_version,
            "new_password": _RESET_PASSWORD,
        },
    )
    assert weak_reset.status_code == 422
    assert weak_reset.json()["code"] == "PASSWORD_POLICY_VIOLATION"
    assert reset.status_code == 200
    assert reset.json()["must_change_password"] is True

    client.cookies.clear()
    client.cookies.set(
        settings.session_cookie_name,
        member_session,
        domain="testserver.local",
        path="/",
    )
    client.cookies.set(
        settings.csrf_cookie_name,
        member_csrf,
        domain="testserver.local",
        path="/",
    )
    old_browser_session = await client.get("/api/v1/auth/me")
    old_device_session = await client.get(
        "/api/v1/device-sessions",
        headers={"Authorization": f"Device {device_token}"},
    )
    assert old_browser_session.status_code == 401
    assert old_device_session.status_code == 401

    reset_login = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "default",
            "username": "member",
            "password": _RESET_PASSWORD,
        },
    )
    assert reset_login.status_code == 200
    assert reset_login.json()["user"]["must_change_password"] is True
    forced_change = await client.get("/api/v1/device-sessions")
    assert forced_change.status_code == 403
    assert forced_change.json()["code"] == "PASSWORD_CHANGE_REQUIRED"

    async with session_factory() as session:
        browser_revocations = (
            (
                await session.execute(
                    select(AuthSession).where(
                        AuthSession.user_id == UUID(str(member_id)),
                        AuthSession.revoked_reason == "admin_password_reset",
                    )
                )
            )
            .scalars()
            .all()
        )
        device_revocations = (
            (
                await session.execute(
                    select(DeviceSession).where(
                        DeviceSession.user_id == UUID(str(member_id)),
                        DeviceSession.revoked_reason == "admin_password_reset",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert browser_revocations
    assert device_revocations
