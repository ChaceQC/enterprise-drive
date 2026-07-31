from __future__ import annotations

import atexit
import os
from typing import Any

from prometheus_client import (
    CollectorRegistry,
    Counter,
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


def worker_metrics_registry_for_exposition() -> CollectorRegistry:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        return registry
    return WORKER_METRICS_REGISTRY


def start_worker_metrics_server(*, port: int) -> tuple[Any, Any] | None:
    if port <= 0:
        return None
    return start_http_server(
        port,
        addr="0.0.0.0",
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
