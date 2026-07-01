from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

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
        "version": "0.1.0",
        "environment": "test",
    }


@pytest.mark.asyncio
async def test_readyz(client: AsyncClient) -> None:
    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


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
