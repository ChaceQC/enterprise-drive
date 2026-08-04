from __future__ import annotations

import asyncio
import json
import os
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path
from time import perf_counter

import httpx
import pytest
import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.skipif(
    os.environ.get("DRIVE_RUN_SPRINT12_MATRIX") != "1",
    reason="Sprint 12 full dependency matrix is opt-in",
)


@pytest.mark.asyncio
async def test_full_dependency_fault_and_recovery_matrix() -> None:
    probes = {
        "postgres": _probe_postgres,
        "redis": _probe_redis,
        "minio": _probe_minio,
        "opensearch": _probe_opensearch,
    }
    containers = {
        "postgres": _required_env("DRIVE_TEST_POSTGRES_CONTAINER"),
        "redis": _required_env("DRIVE_TEST_REDIS_CONTAINER"),
        "minio": _required_env("DRIVE_TEST_MINIO_CONTAINER"),
        "opensearch": _required_env("DRIVE_TEST_OPENSEARCH_CONTAINER"),
    }
    report: dict[str, object] = {"dependencies": {}, "faults": []}

    for name, probe in probes.items():
        await _wait_for(probe, timeout_seconds=180)
        dependency_report = report["dependencies"]
        assert isinstance(dependency_report, dict)
        dependency_report[name] = {"initial": "healthy"}

    for name in ("redis", "opensearch", "minio", "postgres"):
        probe = probes[name]
        container = containers[name]
        started_at = perf_counter()
        _docker("stop", container)
        try:
            await _wait_for_failure(probe, timeout_seconds=30)
        finally:
            _docker("start", container)
        await _wait_for(probe, timeout_seconds=180)
        faults = report["faults"]
        assert isinstance(faults, list)
        faults.append(
            {
                "dependency": name,
                "failure_detected": True,
                "recovered": True,
                "duration_seconds": round(perf_counter() - started_at, 3),
            }
        )

    for probe in probes.values():
        await probe()
    report["final_state"] = "healthy"
    _write_report(report)


async def _probe_postgres() -> None:
    engine = create_async_engine(_required_env("DRIVE_TEST_POSTGRES_URL"))
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(text("select 1")) == 1
    finally:
        await engine.dispose()


async def _probe_redis() -> None:
    client = redis.from_url(
        _required_env("DRIVE_TEST_REDIS_URL"),
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        assert await client.ping()
    finally:
        await client.aclose()


async def _probe_minio() -> None:
    async with httpx.AsyncClient(timeout=2) as client:
        response = await client.get(
            f"{_required_env('DRIVE_TEST_MINIO_ENDPOINT').rstrip('/')}/minio/health/live"
        )
        response.raise_for_status()


async def _probe_opensearch() -> None:
    async with httpx.AsyncClient(timeout=2) as client:
        response = await client.get(
            f"{_required_env('DRIVE_TEST_OPENSEARCH_URL').rstrip('/')}/_cluster/health"
        )
        response.raise_for_status()
        payload = response.json()
        assert payload["status"] in {"green", "yellow"}


async def _wait_for(
    probe: Callable[[], Awaitable[None]],
    *,
    timeout_seconds: float,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_error: Exception | None = None
    while asyncio.get_running_loop().time() < deadline:
        try:
            await probe()
            return
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(1)
    raise AssertionError(f"dependency did not recover: {type(last_error).__name__}")


async def _wait_for_failure(
    probe: Callable[[], Awaitable[None]],
    *,
    timeout_seconds: float,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        try:
            await probe()
        except Exception:
            return
        await asyncio.sleep(0.5)
    raise AssertionError("fault injection did not make dependency unavailable")


def _docker(command: str, container: str) -> None:
    subprocess.run(
        ["docker", command, container],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise AssertionError(f"missing required environment variable: {name}")
    return value


def _write_report(report: dict[str, object]) -> None:
    output = os.environ.get("DRIVE_SPRINT12_MATRIX_REPORT", "").strip()
    if not output:
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
