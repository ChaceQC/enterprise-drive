from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

PING_METRIC_PATTERN = re.compile(
    r'http_requests_total\{method="GET",route="/api/v1/ping",status_code="200"\} '
    r"(?P<count>[0-9.]+)"
)
WORKER_SUCCESS_METRIC = (
    'worker_tasks_total{queue="maintenance",status="success",task="upload.expire_sessions"}'
)
REQUIRED_API_METRICS = (
    "http_requests_total",
    "http_request_duration_seconds",
    "upload_sessions_total",
    "upload_failures_total",
    "download_requests_total",
    "permission_decision_duration_seconds",
    "search_index_lag_seconds",
    "outbox_pending_total",
)
WORKER_ONLY_METRICS = (
    "worker_tasks_total",
    "worker_task_duration_seconds",
    "preview_failures_total",
    "orphan_object_cleanup_total",
    "trash_cleanup_total",
    "trash_cleanup_released_bytes_total",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="使用真实 Docker 验证 BE-027 可观测性")
    parser.add_argument(
        "--image",
        default="enterprise-drive-backend:windows-local",
        help="待验证的后端 runtime image",
    )
    parser.add_argument("--postgres-image", default="postgres:16-bookworm")
    parser.add_argument("--redis-image", default="redis:7.4-alpine")
    parser.add_argument("--ping-count", type=int, default=24)
    args = parser.parse_args()

    docker = _docker_executable()
    suffix = uuid4().hex[:10]
    network = f"drive-observability-{suffix}"
    postgres = f"drive-observability-postgres-{suffix}"
    redis = f"drive-observability-redis-{suffix}"
    api = f"drive-observability-api-{suffix}"
    worker = f"drive-observability-worker-{suffix}"
    containers = [worker, api, redis, postgres]

    try:
        _run(docker, "network", "create", network)
        _start_postgres(
            docker=docker,
            name=postgres,
            network=network,
            image=args.postgres_image,
        )
        _start_redis(
            docker=docker,
            name=redis,
            network=network,
            image=args.redis_image,
        )
        _run_migrations(
            docker=docker,
            network=network,
            image=args.image,
        )

        api_port = _start_api(
            docker=docker,
            name=api,
            network=network,
            image=args.image,
        )
        _wait_http(f"http://127.0.0.1:{api_port}/healthz")
        for index in range(args.ping_count):
            _http_get(
                f"http://127.0.0.1:{api_port}/api/v1/ping",
                headers={
                    "Host": "localhost",
                    "X-Request-ID": f"req_docker_smoke_{index}",
                },
            )
        metric_process_files = int(
            _run(
                docker,
                "exec",
                api,
                "sh",
                "-lc",
                ("find /tmp/enterprise-drive/prometheus -name 'gauge_livemostrecent_*.db' | wc -l"),
            ).stdout.strip()
        )
        if metric_process_files < 2:
            raise RuntimeError(
                f"expected at least two API gauge metric process files, got {metric_process_files}"
            )
        _run(
            docker,
            "exec",
            api,
            "python",
            "-c",
            (
                "from app.core.metrics import "
                "record_download_request,record_permission_decision,"
                "record_upload_failure,record_upload_session;"
                "record_upload_session(mode='multipart',outcome='created');"
                "record_upload_failure(stage='complete',reason='smoke_fixture');"
                "record_download_request(channel='internal',outcome='allowed');"
                "record_permission_decision("
                "scope='node',action='download',outcome='allowed',duration_seconds=0.001)"
            ),
        )
        api_metrics = _http_get(
            f"http://127.0.0.1:{api_port}/metrics",
            headers={"Host": "localhost"},
        )
        for metric_name in REQUIRED_API_METRICS:
            if metric_name not in api_metrics:
                raise RuntimeError(f"API metrics missing {metric_name}")
        for metric_name in WORKER_ONLY_METRICS:
            if metric_name in api_metrics:
                raise RuntimeError(f"API metrics unexpectedly include Worker metric {metric_name}")
        ping_match = PING_METRIC_PATTERN.search(api_metrics)
        if ping_match is None:
            raise RuntimeError("API metrics missing templated ping counter")
        observed_ping_count = int(float(ping_match.group("count")))
        if observed_ping_count < args.ping_count:
            raise RuntimeError(
                f"multiprocess ping counter too small: {observed_ping_count} < {args.ping_count}"
            )
        api_log = _find_json_log(
            docker=docker,
            container=api,
            message="HTTP 请求完成",
            field="route",
            value="/api/v1/ping",
        )
        if not api_log.get("trace_id") or not api_log.get("span_id"):
            raise RuntimeError("API request log is missing trace correlation")
        if api_log.get("service") != "enterprise-drive-api-smoke":
            raise RuntimeError("API request log is missing the configured service name")
        if api_log.get("env") != "production":
            raise RuntimeError("API request log is missing the configured environment")
        if not str(api_log.get("request_id", "")).startswith("req_docker_smoke_"):
            raise RuntimeError("API request log is missing request_id correlation")

        worker_port = _start_worker(
            docker=docker,
            name=worker,
            network=network,
            image=args.image,
        )
        _wait_http(f"http://127.0.0.1:{worker_port}/metrics")
        _run(
            docker,
            "exec",
            worker,
            "python",
            "-c",
            (
                "from app.infrastructure.queue.celery_app import celery_app;"
                "result=celery_app.send_task("
                "'upload.expire_sessions',kwargs={'limit': 1},queue='maintenance');"
                "print(result.id)"
            ),
        )
        worker_metrics = _wait_metric(
            url=f"http://127.0.0.1:{worker_port}/metrics",
            expected=WORKER_SUCCESS_METRIC,
        )
        if "worker_task_duration_seconds_count" not in worker_metrics:
            raise RuntimeError("Worker duration histogram is missing")
        for metric_name in REQUIRED_API_METRICS:
            if metric_name in worker_metrics:
                raise RuntimeError(f"Worker metrics unexpectedly include API metric {metric_name}")
        worker_log = _find_json_log(
            docker=docker,
            container=worker,
            message="Worker 任务完成",
            field="task",
            value="upload.expire_sessions",
        )
        if not worker_log.get("trace_id") or not worker_log.get("span_id"):
            raise RuntimeError("Worker task log is missing trace correlation")
        if worker_log.get("service") != "enterprise-drive-worker-smoke":
            raise RuntimeError("Worker task log is missing the configured service name")
        if not worker_log.get("task_id"):
            raise RuntimeError("Worker task log is missing task_id correlation")

        print(
            json.dumps(
                {
                    "api_port": api_port,
                    "api_ping_count": observed_ping_count,
                    "api_metric_process_files": metric_process_files,
                    "api_trace_id": api_log["trace_id"],
                    "metric_registry_isolation": "passed",
                    "worker_port": worker_port,
                    "worker_task_status": "success",
                    "worker_trace_id": worker_log["trace_id"],
                },
                ensure_ascii=False,
            )
        )
    finally:
        for container in containers:
            _run(docker, "rm", "-f", container, check=False)
        _run(docker, "network", "rm", network, check=False)


def _docker_executable() -> str:
    configured = os.environ.get("DRIVE_TEST_DOCKER")
    if configured:
        return configured
    discovered = shutil.which("docker")
    if discovered:
        return discovered
    windows_default = Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe")
    if windows_default.is_file():
        return str(windows_default)
    raise RuntimeError("Docker executable was not found")


def _run(
    docker: str,
    *args: str,
    check: bool = True,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [docker, *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if check and result.returncode != 0:
        command = " ".join([docker, *args])
        raise RuntimeError(
            f"Docker command failed ({result.returncode}): {command}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _start_postgres(*, docker: str, name: str, network: str, image: str) -> None:
    _run(
        docker,
        "run",
        "-d",
        "--name",
        name,
        "--network",
        network,
        "--network-alias",
        "postgres",
        "-e",
        "POSTGRES_DB=enterprise_drive",
        "-e",
        "POSTGRES_USER=drive",
        "-e",
        "POSTGRES_PASSWORD=drive_test_password",
        image,
    )
    _wait_command(
        lambda: _run(
            docker,
            "exec",
            name,
            "pg_isready",
            "-U",
            "drive",
            "-d",
            "enterprise_drive",
            check=False,
        ),
        description="PostgreSQL readiness",
    )


def _start_redis(*, docker: str, name: str, network: str, image: str) -> None:
    _run(
        docker,
        "run",
        "-d",
        "--name",
        name,
        "--network",
        network,
        "--network-alias",
        "redis",
        image,
    )
    _wait_command(
        lambda: _run(docker, "exec", name, "redis-cli", "ping", check=False),
        description="Redis readiness",
        expected_stdout="PONG",
    )


def _run_migrations(*, docker: str, network: str, image: str) -> None:
    _run(
        docker,
        "run",
        "--rm",
        "--network",
        network,
        "-e",
        _database_url(),
        "-e",
        "DRIVE_SECRET_KEY=docker-smoke-secret",
        image,
        "alembic",
        "upgrade",
        "head",
        timeout=240,
    )


def _start_api(*, docker: str, name: str, network: str, image: str) -> int:
    _run(
        docker,
        "run",
        "-d",
        "--name",
        name,
        "--network",
        network,
        "-p",
        "127.0.0.1::18080",
        "-e",
        _database_url(),
        "-e",
        "DRIVE_SECRET_KEY=docker-smoke-secret",
        "-e",
        "DRIVE_ENVIRONMENT=production",
        "-e",
        "DRIVE_SERVICE_NAME=enterprise-drive-api-smoke",
        "-e",
        'DRIVE_TRUSTED_HOSTS=["localhost","127.0.0.1"]',
        "-e",
        "DRIVE_CORS_ORIGINS=[]",
        "-e",
        "DRIVE_TRACING_ENABLED=true",
        "-e",
        "DRIVE_TRACING_SAMPLE_RATIO=1.0",
        "-e",
        "DRIVE_TRACING_EXPORTER=none",
        "-e",
        "DRIVE_METRICS_DATABASE_REFRESH_TIMEOUT_SECONDS=2.0",
        "-e",
        "PROMETHEUS_MULTIPROC_DIR=/tmp/enterprise-drive/prometheus",
        image,
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "18080",
        "--workers",
        "2",
        "--no-server-header",
    )
    return _published_port(docker=docker, container=name, container_port=18080)


def _start_worker(*, docker: str, name: str, network: str, image: str) -> int:
    _run(
        docker,
        "run",
        "-d",
        "--name",
        name,
        "--network",
        network,
        "-p",
        "127.0.0.1::9100",
        "-e",
        _database_url(),
        "-e",
        "DRIVE_DATABASE_POOL_MODE=null",
        "-e",
        "DRIVE_REDIS_URL=redis://redis:6379/0",
        "-e",
        "DRIVE_CELERY_BROKER_URL=redis://redis:6379/1",
        "-e",
        "DRIVE_CELERY_RESULT_BACKEND=redis://redis:6379/2",
        "-e",
        "DRIVE_SECRET_KEY=docker-smoke-secret",
        "-e",
        "DRIVE_ENVIRONMENT=production",
        "-e",
        "DRIVE_SERVICE_NAME=enterprise-drive-worker-smoke",
        "-e",
        "DRIVE_WORKER_METRICS_PORT=9100",
        "-e",
        "DRIVE_TRACING_ENABLED=true",
        "-e",
        "DRIVE_TRACING_SAMPLE_RATIO=1.0",
        "-e",
        "DRIVE_TRACING_EXPORTER=none",
        "-e",
        "PROMETHEUS_MULTIPROC_DIR=/tmp/enterprise-drive/prometheus",
        image,
        "celery",
        "-A",
        "app.infrastructure.queue.celery_app",
        "worker",
        "--queues=maintenance",
        "--hostname=maintenance-smoke@%h",
        "--loglevel=INFO",
        "--concurrency=1",
        "--without-gossip",
        "--without-mingle",
        "--without-heartbeat",
    )
    return _published_port(docker=docker, container=name, container_port=9100)


def _database_url() -> str:
    return (
        "DRIVE_DATABASE_URL="
        "postgresql+asyncpg://drive:drive_test_password@postgres:5432/enterprise_drive"
    )


def _published_port(*, docker: str, container: str, container_port: int) -> int:
    output = _run(docker, "port", container, f"{container_port}/tcp").stdout.strip()
    if not output:
        raise RuntimeError(f"container {container} has no published port {container_port}")
    return int(output.rsplit(":", 1)[1])


def _wait_command(
    command: Any,
    *,
    description: str,
    expected_stdout: str | None = None,
    timeout_seconds: float = 60,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = command()
        stdout = result.stdout.strip()
        if result.returncode == 0 and (expected_stdout is None or stdout == expected_stdout):
            return
        time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {description}")


def _wait_http(url: str, *, timeout_seconds: float = 60) -> str:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            return _http_get(url, headers={"Host": "localhost"})
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {url}")


def _wait_metric(
    *,
    url: str,
    expected: str,
    timeout_seconds: float = 60,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    latest = ""
    while time.monotonic() < deadline:
        latest = _http_get(url)
        if expected in latest:
            return latest
        time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for metric: {expected}")


def _http_get(url: str, *, headers: dict[str, str] | None = None) -> str:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read().decode("utf-8")


def _find_json_log(
    *,
    docker: str,
    container: str,
    message: str,
    field: str,
    value: str,
) -> dict[str, Any]:
    output = _run(docker, "logs", container).stdout
    for line in reversed(output.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("message") == message and payload.get(field) == value:
            return payload
    raise RuntimeError(f"JSON log not found in {container}: {message}, {field}={value}")


if __name__ == "__main__":
    main()
