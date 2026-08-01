from __future__ import annotations

from pathlib import Path

import pytest
from prometheus_client import generate_latest

from app.core import worker_observability
from app.core.config import Settings
from app.core.maintenance_health import MaintenanceTaskHealth, is_task_stale
from app.core.metrics import (
    API_METRICS_REGISTRY,
    instrument_permission_decision,
)
from app.core.tracing import _build_exporter
from app.core.worker_metrics import WORKER_METRICS_REGISTRY
from app.core.worker_observability import _task_postrun, _task_prerun
from scripts.runtime_entrypoint import prepare_prometheus_multiprocess_dir


class _TaskRequest:
    delivery_info = {"routing_key": "maintenance"}


class _Task:
    name = "file.cleanup_expired_trash"
    request = _TaskRequest()


def test_worker_signals_record_task_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(service_name="enterprise-drive-worker-maintenance")
    health = MaintenanceTaskHealth(
        task_name="file.cleanup_expired_trash",
        consecutive_failures=0,
        alert_active=False,
        last_status="success",
        last_finished_at=100.0,
        last_success_at=100.0,
        last_failure_at=0.0,
    )
    monkeypatch.setattr(worker_observability, "_SETTINGS", settings)
    monkeypatch.setattr(
        worker_observability,
        "record_maintenance_task_result",
        lambda **_: health,
    )
    task = _Task()
    _task_prerun(
        task_id="task_observability_fixture",
        task=task,
        kwargs={"request_id": "req_worker_fixture"},
    )
    _task_postrun(
        task_id="task_observability_fixture",
        task=task,
        state="SUCCESS",
        retval={"scanned": 2, "items": []},
    )

    metrics = generate_latest(WORKER_METRICS_REGISTRY).decode("utf-8")
    assert (
        'worker_tasks_total{queue="maintenance",status="success",'
        'task="file.cleanup_expired_trash"}' in metrics
    )
    assert (
        'worker_task_duration_seconds_count{queue="maintenance",'
        'task="file.cleanup_expired_trash"}' in metrics
    )
    assert 'maintenance_task_consecutive_failures{task="file.cleanup_expired_trash"} 0.0' in metrics
    assert (
        'maintenance_task_result_total{metric="scanned",'
        'task="file.cleanup_expired_trash"}' in metrics
    )


def test_maintenance_health_marks_overdue_task_stale() -> None:
    settings = Settings(
        trash_cleanup_interval_seconds=100,
        maintenance_alert_stale_intervals=3,
    )
    health = MaintenanceTaskHealth(
        task_name="file.cleanup_expired_trash",
        consecutive_failures=0,
        alert_active=False,
        last_status="success",
        last_finished_at=100.0,
        last_success_at=100.0,
        last_failure_at=0.0,
    )

    assert is_task_stale(settings=settings, health=health, now_timestamp=399.0) is False
    assert is_task_stale(settings=settings, health=health, now_timestamp=401.0) is True


@pytest.mark.asyncio
async def test_permission_instrumentation_records_allowed_outcome() -> None:
    @instrument_permission_decision(scope="fixture")
    async def allow(*, action: str) -> bool:
        return action == "download"

    assert await allow(action="download") is True

    metrics = generate_latest(API_METRICS_REGISTRY).decode("utf-8")
    assert (
        'permission_decision_duration_seconds_count{action="download",'
        'outcome="allowed",scope="fixture"}' in metrics
    )


def test_runtime_entrypoint_cleans_only_prometheus_db_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    metrics_dir = tmp_path / "prometheus"
    metrics_dir.mkdir()
    stale_metric = metrics_dir / "counter_123.db"
    preserved_file = metrics_dir / "keep.txt"
    stale_metric.write_bytes(b"stale")
    preserved_file.write_text("keep", encoding="utf-8")
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(metrics_dir))

    prepared = prepare_prometheus_multiprocess_dir()

    assert prepared == metrics_dir.resolve()
    assert not stale_metric.exists()
    assert preserved_file.read_text(encoding="utf-8") == "keep"


def test_runtime_entrypoint_ignores_unset_metrics_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)

    assert prepare_prometheus_multiprocess_dir() is None


def test_tracing_exporter_factories_are_configurable() -> None:
    console = _build_exporter(Settings(tracing_exporter="console"))
    otlp = _build_exporter(
        Settings(
            tracing_exporter="otlp_http",
            tracing_otlp_endpoint="http://collector:4318/v1/traces",
            tracing_otlp_headers={"authorization": "fixture"},
        )
    )

    assert type(console).__name__ == "ConsoleSpanExporter"
    assert type(otlp).__name__ == "OTLPSpanExporter"
