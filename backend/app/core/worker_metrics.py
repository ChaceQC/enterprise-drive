from __future__ import annotations

import atexit
import os
from typing import Any

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    multiprocess,
    start_http_server,
)

WORKER_METRICS_REGISTRY = CollectorRegistry()

worker_tasks_total = Counter(
    "worker_tasks_total",
    "Worker 任务数量",
    ("task", "queue", "status"),
    registry=WORKER_METRICS_REGISTRY,
)

worker_task_duration_seconds = Histogram(
    "worker_task_duration_seconds",
    "Worker 任务耗时",
    ("task", "queue"),
    registry=WORKER_METRICS_REGISTRY,
)

identity_provider_operations_total = Counter(
    "identity_provider_operations_total",
    "外部身份提供商操作数量",
    ("provider_type", "operation", "outcome"),
    registry=WORKER_METRICS_REGISTRY,
)

ldap_sync_runs_total = Counter(
    "ldap_sync_runs_total",
    "LDAP 同步运行数量",
    ("mode", "outcome"),
    registry=WORKER_METRICS_REGISTRY,
)

preview_failures_total = Counter(
    "preview_failures_total",
    "预览失败数",
    ("status", "reason"),
    registry=WORKER_METRICS_REGISTRY,
)

orphan_object_cleanup_total = Counter(
    "orphan_object_cleanup_total",
    "孤儿最终对象扫描和清理计数",
    ("status",),
    registry=WORKER_METRICS_REGISTRY,
)

trash_cleanup_total = Counter(
    "trash_cleanup_total",
    "回收站保留期扫描和清理计数",
    ("status",),
    registry=WORKER_METRICS_REGISTRY,
)

trash_cleanup_released_bytes_total = Counter(
    "trash_cleanup_released_bytes_total",
    "回收站保留期清理释放的容量字节数",
    registry=WORKER_METRICS_REGISTRY,
)

preview_artifact_cleanup_total = Counter(
    "preview_artifact_cleanup_total",
    "预览产物生命周期扫描和清理计数",
    ("status",),
    registry=WORKER_METRICS_REGISTRY,
)

maintenance_task_consecutive_failures = Gauge(
    "maintenance_task_consecutive_failures",
    "维护任务当前连续失败次数",
    ("task",),
    registry=WORKER_METRICS_REGISTRY,
    multiprocess_mode="livemostrecent",
)

maintenance_task_alert_active = Gauge(
    "maintenance_task_alert_active",
    "维护任务连续失败告警状态",
    ("task",),
    registry=WORKER_METRICS_REGISTRY,
    multiprocess_mode="livemostrecent",
)

maintenance_task_stale = Gauge(
    "maintenance_task_stale",
    "维护任务是否超过允许执行间隔仍未完成",
    ("task",),
    registry=WORKER_METRICS_REGISTRY,
    multiprocess_mode="livemostrecent",
)

maintenance_task_last_success_timestamp_seconds = Gauge(
    "maintenance_task_last_success_timestamp_seconds",
    "维护任务最近一次成功时间 Unix timestamp",
    ("task",),
    registry=WORKER_METRICS_REGISTRY,
    multiprocess_mode="livemostrecent",
)

maintenance_task_last_failure_timestamp_seconds = Gauge(
    "maintenance_task_last_failure_timestamp_seconds",
    "维护任务最近一次失败时间 Unix timestamp",
    ("task",),
    registry=WORKER_METRICS_REGISTRY,
    multiprocess_mode="livemostrecent",
)

maintenance_task_last_finished_timestamp_seconds = Gauge(
    "maintenance_task_last_finished_timestamp_seconds",
    "维护任务最近一次完成时间 Unix timestamp",
    ("task",),
    registry=WORKER_METRICS_REGISTRY,
    multiprocess_mode="livemostrecent",
)

maintenance_task_result_total = Counter(
    "maintenance_task_result_total",
    "维护任务返回结果中的累计计数",
    ("task", "metric"),
    registry=WORKER_METRICS_REGISTRY,
)

_MAX_LABEL_LENGTH = 128


def record_worker_task(
    *,
    task: str,
    queue: str,
    status: str,
    duration_seconds: float,
) -> None:
    normalized_task = _bounded_label(task)
    normalized_queue = _bounded_label(queue)
    worker_tasks_total.labels(
        task=normalized_task,
        queue=normalized_queue,
        status=_bounded_label(status),
    ).inc()
    worker_task_duration_seconds.labels(
        task=normalized_task,
        queue=normalized_queue,
    ).observe(max(duration_seconds, 0.0))


def record_identity_provider_operation(
    *,
    provider_type: str,
    operation: str,
    outcome: str,
) -> None:
    identity_provider_operations_total.labels(
        provider_type=_bounded_label(provider_type),
        operation=_bounded_label(operation),
        outcome=_bounded_label(outcome),
    ).inc()


def record_ldap_sync_run(*, mode: str, outcome: str) -> None:
    ldap_sync_runs_total.labels(
        mode=_bounded_label(mode),
        outcome=_bounded_label(outcome),
    ).inc()


def record_preview_failure(*, status: str, reason: str) -> None:
    preview_failures_total.labels(
        status=_bounded_label(status),
        reason=_bounded_label(reason),
    ).inc()


def record_orphan_object_cleanup(*, status: str, count: int = 1) -> None:
    if count <= 0:
        return
    orphan_object_cleanup_total.labels(status=_bounded_label(status)).inc(count)


def record_trash_cleanup(*, status: str, count: int = 1) -> None:
    if count <= 0:
        return
    trash_cleanup_total.labels(status=_bounded_label(status)).inc(count)


def record_trash_cleanup_released_bytes(*, size_bytes: int) -> None:
    if size_bytes <= 0:
        return
    trash_cleanup_released_bytes_total.inc(size_bytes)


def record_preview_artifact_cleanup(*, status: str, count: int = 1) -> None:
    if count <= 0:
        return
    preview_artifact_cleanup_total.labels(status=_bounded_label(status)).inc(count)


def set_maintenance_task_health(
    *,
    task: str,
    consecutive_failures: int,
    alert_active: bool,
    stale: bool,
    last_finished_at: float,
    last_success_at: float,
    last_failure_at: float,
) -> None:
    normalized_task = _bounded_label(task)
    maintenance_task_consecutive_failures.labels(task=normalized_task).set(
        max(consecutive_failures, 0)
    )
    maintenance_task_alert_active.labels(task=normalized_task).set(1 if alert_active else 0)
    maintenance_task_stale.labels(task=normalized_task).set(1 if stale else 0)
    maintenance_task_last_finished_timestamp_seconds.labels(task=normalized_task).set(
        max(last_finished_at, 0.0)
    )
    maintenance_task_last_success_timestamp_seconds.labels(task=normalized_task).set(
        max(last_success_at, 0.0)
    )
    maintenance_task_last_failure_timestamp_seconds.labels(task=normalized_task).set(
        max(last_failure_at, 0.0)
    )


def record_maintenance_task_result_metrics(*, task: str, result: object) -> None:
    if not isinstance(result, dict):
        return
    normalized_task = _bounded_label(task)
    for key, value in result.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            continue
        metric = _bounded_label(str(key))
        maintenance_task_result_total.labels(task=normalized_task, metric=metric).inc(value)


def worker_metrics_registry_for_exposition() -> CollectorRegistry:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        return registry
    return WORKER_METRICS_REGISTRY


def start_worker_metrics_server(*, port: int) -> tuple[Any, Any] | None:
    if port <= 0:
        return None
    # Worker metrics 只监听 Compose 内部网络，正式编排不发布宿主端口。
    return start_http_server(
        port,
        addr="0.0.0.0",  # nosec B104
        registry=worker_metrics_registry_for_exposition(),
    )


def _bounded_label(value: str, *, fallback: str = "unknown") -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    return (normalized or fallback)[:_MAX_LABEL_LENGTH]


def _mark_current_process_dead() -> None:
    if not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        return
    try:
        multiprocess.mark_process_dead(os.getpid())  # type: ignore[no-untyped-call]
    except OSError:
        return


if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
    atexit.register(_mark_current_process_dead)
