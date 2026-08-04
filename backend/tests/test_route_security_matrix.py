from __future__ import annotations

from collections.abc import Iterable

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.main import create_app
from tests.helpers import client as client
from tests.helpers import create_second_user, login, seed_admin
from tests.helpers import session_factory as session_factory
from tests.helpers import settings as settings
from tests.helpers import storage_adapter as storage_adapter
from tests.security_route_matrix import ROUTE_SECURITY_MATRIX, SecurityRouteCase

_HTTP_METHODS = frozenset({"DELETE", "GET", "PATCH", "POST", "PUT"})


def _openapi_route_keys(app: FastAPI) -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method.upper() in _HTTP_METHODS
    }


def _matrix_route_keys(cases: Iterable[SecurityRouteCase]) -> set[tuple[str, str]]:
    return {case.route_key for case in cases}


def test_route_security_matrix_exactly_matches_runtime_openapi(settings: Settings) -> None:
    matrix_keys = _matrix_route_keys(ROUTE_SECURITY_MATRIX)
    openapi_keys = _openapi_route_keys(create_app(settings))

    assert len(ROUTE_SECURITY_MATRIX) == 134
    assert len(matrix_keys) == len(ROUTE_SECURITY_MATRIX)
    assert matrix_keys == openapi_keys
    assert len(matrix_keys - {("GET", "/api/v1/ping"), ("POST", "/api/v1/auth/login")}) == 132


def test_route_security_matrix_metadata_is_consistent() -> None:
    for case in ROUTE_SECURITY_MATRIX:
        assert case.method in _HTTP_METHODS
        assert case.template_path.startswith("/api/v1/")
        assert case.request_path.startswith("/api/v1/")

        if case.csrf_mode == "required":
            assert case.method in {"DELETE", "PATCH", "POST", "PUT"}
            assert case.access_mode in {"session", "admin"}
        if case.access_mode == "admin":
            assert case.authorization == "super_admin"
        if case.access_mode == "public":
            assert case.authorization in {"anonymous", "external_share"}
        if case.access_mode == "device":
            assert case.authorization == "device_session"
        if case.tenant_scope == "resource":
            assert case.access_mode in {"session", "admin"}


@pytest.mark.parametrize(
    "case",
    ROUTE_SECURITY_MATRIX,
    ids=[case.id for case in ROUTE_SECURITY_MATRIX],
)
@pytest.mark.asyncio
async def test_anonymous_access_matches_route_security_matrix(
    client: AsyncClient,
    case: SecurityRouteCase,
) -> None:
    response = await client.request(
        case.method,
        case.request_path,
        params=case.query or None,
        headers=case.headers or None,
        json=case.json_body,
    )

    assert response.status_code == case.anonymous_status
    if case.anonymous_code is None:
        return
    assert response.json()["code"] == case.anonymous_code


@pytest.mark.asyncio
async def test_authenticated_mutations_require_csrf(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    await login(client)
    csrf_cases = [case for case in ROUTE_SECURITY_MATRIX if case.csrf_mode == "required"]

    assert len(csrf_cases) == 71
    for case in csrf_cases:
        response = await client.request(
            case.method,
            case.request_path,
            params=case.query or None,
            headers=case.headers or None,
            json=case.json_body,
        )
        assert response.status_code == 403, case.id
        assert response.json()["code"] == "CSRF_TOKEN_INVALID", case.id


@pytest.mark.asyncio
async def test_logout_requires_csrf_only_when_a_session_cookie_exists(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)

    missing_csrf_response = await client.post("/api/v1/auth/logout")
    authenticated_response = await client.get("/api/v1/auth/me")
    logout_response = await client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert missing_csrf_response.status_code == 403
    assert missing_csrf_response.json()["code"] == "CSRF_TOKEN_INVALID"
    assert authenticated_response.status_code == 200
    assert logout_response.status_code == 200


@pytest.mark.asyncio
async def test_authenticated_read_routes_pass_the_identity_gate(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    await login(client)
    read_cases = [
        case
        for case in ROUTE_SECURITY_MATRIX
        if case.access_mode in {"session", "admin"} and case.csrf_mode == "none"
    ]

    assert len(read_cases) == 52
    for case in read_cases:
        response = await client.request(
            case.method,
            case.request_path,
            params=case.query or None,
            headers=case.headers or None,
            json=case.json_body,
        )
        assert response.status_code != 401, case.id
        assert response.json().get("code") != "AUTH_REQUIRED", case.id


@pytest.mark.asyncio
async def test_normal_user_is_denied_the_admin_route(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    await create_second_user(session_factory)
    await login(client, username="member", password="member-password")

    response = await client.get("/api/v1/admin/audit-logs")

    assert response.status_code == 403
    assert response.json()["code"] == "ADMIN_REQUIRED"
