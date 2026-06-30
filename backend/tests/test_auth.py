from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.errors import ApiError
from app.core.config import Settings, get_settings
from app.core.security import hash_token
from app.db.base import Base
from app.db.session import get_db_session
from app.main import create_app
from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditContext
from app.modules.audit.service import AuditService
from app.modules.auth.models import AuthSession
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService


@pytest.fixture
def auth_settings() -> Settings:
    return Settings(
        environment="test",
        secret_key="test-secret",
        trusted_hosts=["testserver"],
        cors_origins=[],
        database_url="sqlite+aiosqlite:///:memory:",
        admin_password="admin-password",
        session_days=30,
    )


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    yield async_sessionmaker(engine, expire_on_commit=False)

    await engine.dispose()


@pytest_asyncio.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as db_session:
        yield db_session


@pytest_asyncio.fixture
async def auth_service(session: AsyncSession, auth_settings: Settings) -> AuthService:
    return AuthService(
        repository=AuthRepository(session),
        settings=auth_settings,
        audit_service=AuditService(repository=AuditRepository(session)),
    )


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
    auth_settings: Settings,
) -> AsyncIterator[AsyncClient]:
    app = create_app(auth_settings)

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as db_session:
            yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_settings] = lambda: auth_settings

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_seed_admin_is_idempotent(auth_service: AuthService) -> None:
    first_result = await auth_service.seed_admin()
    second_result = await auth_service.seed_admin()

    assert first_result.tenant_created is True
    assert first_result.user_created is True
    assert second_result.tenant_created is False
    assert second_result.user_created is False


@pytest.mark.asyncio
async def test_login_and_rotate_session(auth_service: AuthService) -> None:
    await auth_service.seed_admin()
    login_response = await auth_service.login(
        tenant_slug="default",
        username="admin",
        password="admin-password",
        audit_context=AuditContext(request_id="req_login"),
    )

    rotate_response = await auth_service.rotate_session(
        session_token=login_response.session_token,
        csrf_token=login_response.csrf_token,
        audit_context=AuditContext(request_id="req_rotate"),
    )

    assert login_response.session_token
    assert login_response.csrf_token
    assert login_response.response.user.username == "admin"
    assert rotate_response.session_token != login_response.session_token
    assert rotate_response.csrf_token != login_response.csrf_token


@pytest.mark.asyncio
async def test_reusing_rotated_session_revokes_family(
    auth_service: AuthService,
    session: AsyncSession,
) -> None:
    await auth_service.seed_admin()
    login_response = await auth_service.login(
        tenant_slug="default",
        username="admin",
        password="admin-password",
    )
    rotate_response = await auth_service.rotate_session(
        session_token=login_response.session_token,
        csrf_token=login_response.csrf_token,
    )

    with pytest.raises(ApiError) as exc_info:
        await auth_service.rotate_session(
            session_token=login_response.session_token,
            csrf_token=login_response.csrf_token,
        )

    assert exc_info.value.code == "SESSION_REUSED"

    new_token_hash = hash_token(rotate_response.session_token)
    stored_new_token = await AuthRepository(session).get_auth_session_by_token_hash(new_token_hash)
    assert isinstance(stored_new_token, AuthSession)
    assert stored_new_token.revoked_reason == "reuse_detected"


@pytest.mark.asyncio
async def test_auth_events_write_audit_log_and_outbox(
    auth_service: AuthService,
    session: AsyncSession,
) -> None:
    await auth_service.seed_admin()
    login_response = await auth_service.login(
        tenant_slug="default",
        username="admin",
        password="admin-password",
        audit_context=AuditContext(request_id="req_audit", ip="127.0.0.1"),
    )
    await auth_service.rotate_session(
        session_token=login_response.session_token,
        csrf_token=login_response.csrf_token,
        audit_context=AuditContext(request_id="req_rotate"),
    )

    audit_logs = (
        (await session.execute(select(AuditLog).order_by(AuditLog.created_at, AuditLog.action)))
        .scalars()
        .all()
    )
    outbox_events = (await session.execute(select(OutboxEvent))).scalars().all()

    assert [log.action for log in audit_logs] == ["auth.login", "auth.session.rotated"]
    assert [log.result for log in audit_logs] == ["allowed", "allowed"]
    assert audit_logs[0].request_id == "req_audit"
    assert len(outbox_events) == 2
    assert {event.event_type for event in outbox_events} == {
        "audit.auth.login",
        "audit.auth.session.rotated",
    }


@pytest.mark.asyncio
async def test_failed_login_writes_denied_audit(
    auth_service: AuthService,
    session: AsyncSession,
) -> None:
    await auth_service.seed_admin()

    with pytest.raises(ApiError):
        await auth_service.login(
            tenant_slug="default",
            username="admin",
            password="wrong-password",
            audit_context=AuditContext(request_id="req_bad_login"),
        )

    audit_log = (await session.execute(select(AuditLog))).scalar_one()
    outbox_event = (await session.execute(select(OutboxEvent))).scalar_one()

    assert audit_log.action == "auth.login"
    assert audit_log.result == "denied"
    assert audit_log.risk_level == "medium"
    assert audit_log.request_id == "req_bad_login"
    assert outbox_event.event_type == "audit.auth.login"


@pytest.mark.asyncio
async def test_auth_api_login_rotate_me_and_logout_with_cookie_session(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    auth_settings: Settings,
) -> None:
    async with session_factory() as seed_session:
        service = AuthService(
            repository=AuthRepository(seed_session),
            settings=auth_settings,
            audit_service=AuditService(repository=AuditRepository(seed_session)),
        )
        await service.seed_admin()

    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "default",
            "username": "admin",
            "password": "admin-password",
        },
    )
    assert login_response.status_code == 200
    login_payload = login_response.json()
    assert login_payload["authenticated"] is True
    assert login_payload["user"]["username"] == "admin"
    assert "access_token" not in login_payload
    assert "session_token" not in login_payload
    assert client.cookies.get("drive_session") is not None
    csrf_token = client.cookies.get("drive_csrf")
    assert csrf_token is not None
    set_cookie_headers = login_response.headers.get_list("set-cookie")
    assert any("drive_session=" in header and "HttpOnly" in header for header in set_cookie_headers)
    assert any(
        "drive_csrf=" in header and "HttpOnly" not in header for header in set_cookie_headers
    )

    me_response = await client.get("/api/v1/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["username"] == "admin"

    missing_csrf_response = await client.post("/api/v1/auth/session/rotate")
    assert missing_csrf_response.status_code == 403
    assert missing_csrf_response.json()["code"] == "CSRF_TOKEN_INVALID"

    rotate_response = await client.post(
        "/api/v1/auth/session/rotate",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert rotate_response.status_code == 200
    assert rotate_response.json()["authenticated"] is True
    rotated_csrf_token = client.cookies.get("drive_csrf")
    assert rotated_csrf_token is not None
    assert rotated_csrf_token != csrf_token

    logout_response = await client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": rotated_csrf_token},
    )
    assert logout_response.status_code == 200
    assert logout_response.json() == {"authenticated": False}

    logged_out_response = await client.get("/api/v1/auth/me")
    assert logged_out_response.status_code == 401
