from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import health as health_module
from app.core.config import Settings
from app.core.logging import JsonFormatter
from app.main import create_app


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    settings = Settings(
        environment="test",
        cors_origins=[],
        trusted_hosts=["testserver"],
        secret_key="test-secret",
        database_url="sqlite+aiosqlite:///:memory:",
    )
    transport = ASGITransport(app=create_app(settings))
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_healthz(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "企业网盘",
        "version": "0.4.0",
        "environment": "test",
    }


@pytest.mark.asyncio
async def test_readyz(client: AsyncClient) -> None:
    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"] == {"database": "ready"}


@pytest.mark.asyncio
async def test_readyz_returns_503_when_database_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_database_check(settings: Settings) -> None:
        raise ConnectionError(settings.database_url)

    monkeypatch.setattr(health_module, "_check_database_ready", fail_database_check)
    settings = Settings(
        environment="test",
        cors_origins=[],
        trusted_hosts=["testserver"],
        secret_key="test-secret",
        database_url="sqlite+aiosqlite:///:memory:",
    )
    transport = ASGITransport(app=create_app(settings))
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        response = await test_client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"] == {"database": "unavailable"}


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_prometheus_text(client: AsyncClient) -> None:
    response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "preview_failures_total" in response.text
    assert "orphan_object_cleanup_total" in response.text


@pytest.mark.asyncio
async def test_request_id_is_reused(client: AsyncClient) -> None:
    response = await client.get("/api/v1/ping", headers={"X-Request-ID": "req_test"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req_test"
    assert response.json() == {"message": "pong", "request_id": "req_test"}


@pytest.mark.asyncio
async def test_not_found_uses_unified_error_response(client: AsyncClient) -> None:
    response = await client.get("/missing", headers={"X-Request-ID": "req_missing"})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "req_missing"
    assert response.json() == {
        "code": "NOT_FOUND",
        "message": "资源不存在",
        "request_id": "req_missing",
    }


def test_json_formatter_preserves_extra_fields() -> None:
    record = logging.LogRecord(
        name="enterprise_drive.preview",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="preview render finished without artifact",
        args=(),
        exc_info=None,
    )
    record.preview_status = "unsupported"
    record.preview_reason = "office_renderer_missing"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "preview render finished without artifact"
    assert payload["preview_status"] == "unsupported"
    assert payload["preview_reason"] == "office_renderer_missing"
