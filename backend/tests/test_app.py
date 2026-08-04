from __future__ import annotations

import json
import logging
import tomllib
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, use_span

from app import health as health_module
from app.core.config import Settings
from app.core.logging import JsonFormatter, reset_log_context, set_log_context
from app.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_VERSION = "0.6.0"


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
        "version": PROJECT_VERSION,
        "environment": "test",
    }


def test_project_version_is_consistent_across_runtime_and_desktop_contracts() -> None:
    backend_project = tomllib.loads(
        (PROJECT_ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    )
    desktop_workspace = tomllib.loads(
        (PROJECT_ROOT / "desktop" / "Cargo.toml").read_text(encoding="utf-8")
    )
    tauri_config = json.loads(
        (
            PROJECT_ROOT / "desktop" / "apps" / "drive-desktop" / "src-tauri" / "tauri.conf.json"
        ).read_text(encoding="utf-8")
    )
    contract_versions = {
        json.loads(path.read_text(encoding="utf-8"))["version"]
        for path in (
            PROJECT_ROOT / "desktop" / "contracts" / "sprint7-openapi.json",
            PROJECT_ROOT / "desktop" / "contracts" / "sprint8-openapi.json",
        )
    }

    assert {
        backend_project["project"]["version"],
        Settings.model_fields["app_version"].default,
        desktop_workspace["workspace"]["package"]["version"],
        tauri_config["version"],
        *contract_versions,
    } == {PROJECT_VERSION}


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
    assert "http_requests_total" in response.text
    assert "http_request_duration_seconds" in response.text
    assert "upload_sessions_total" in response.text
    assert "upload_failures_total" in response.text
    assert "download_requests_total" in response.text
    assert "permission_decision_duration_seconds" in response.text
    assert "search_index_lag_seconds" in response.text
    assert "outbox_pending_total" in response.text
    assert "worker_tasks_total" not in response.text
    assert "worker_task_duration_seconds" not in response.text
    assert "preview_failures_total" not in response.text
    assert "orphan_object_cleanup_total" not in response.text
    assert "trash_cleanup_total" not in response.text
    assert "trash_cleanup_released_bytes_total" not in response.text


@pytest.mark.asyncio
async def test_metrics_use_route_templates_and_exclude_metrics(client: AsyncClient) -> None:
    session_id = uuid4()
    await client.get("/api/v1/ping")
    await client.get(f"/api/v1/uploads/{session_id}")
    await client.get("/missing")
    response = await client.get("/metrics")

    assert (
        'http_requests_total{method="GET",route="/api/v1/ping",status_code="200"}' in response.text
    )
    assert (
        'http_requests_total{method="GET",route="/api/v1/uploads/{session_id}",'
        'status_code="401"}' in response.text
    )
    assert str(session_id) not in response.text
    assert 'http_requests_total{method="GET",route="unmatched",status_code="404"}' in response.text
    assert 'route="/metrics"' not in response.text


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


def test_json_formatter_correlates_request_and_trace_context() -> None:
    record = logging.LogRecord(
        name="enterprise_drive.http",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request completed",
        args=(),
        exc_info=None,
    )
    context_token = set_log_context(
        request_id="req_trace",
        tenant_id="tenant_fixture",
        user_id="user_fixture",
    )
    span = NonRecordingSpan(
        SpanContext(
            trace_id=0x1234567890ABCDEF1234567890ABCDEF,
            span_id=0x1234567890ABCDEF,
            is_remote=False,
            trace_flags=TraceFlags(0x01),
        )
    )
    try:
        with use_span(span, end_on_exit=False):
            payload = json.loads(
                JsonFormatter(
                    service="enterprise-drive-api",
                    environment="test",
                ).format(record)
            )
    finally:
        reset_log_context(context_token)

    assert payload["service"] == "enterprise-drive-api"
    assert payload["env"] == "test"
    assert payload["request_id"] == "req_trace"
    assert payload["tenant_id"] == "tenant_fixture"
    assert payload["user_id"] == "user_fixture"
    assert payload["trace_id"] == "1234567890abcdef1234567890abcdef"
    assert payload["span_id"] == "1234567890abcdef"
