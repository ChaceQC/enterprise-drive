from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(
        environment="test",
        cors_origins=[],
        trusted_hosts=["testserver"],
        secret_key="test-secret",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "企业网盘",
        "version": "0.1.0",
        "environment": "test",
    }


def test_readyz(client: TestClient) -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_request_id_is_reused(client: TestClient) -> None:
    response = client.get("/api/v1/ping", headers={"X-Request-ID": "req_test"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req_test"
    assert response.json() == {"message": "pong", "request_id": "req_test"}


def test_not_found_uses_unified_error_response(client: TestClient) -> None:
    response = client.get("/missing", headers={"X-Request-ID": "req_missing"})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "req_missing"
    assert response.json() == {
        "code": "NOT_FOUND",
        "message": "资源不存在",
        "request_id": "req_missing",
    }
