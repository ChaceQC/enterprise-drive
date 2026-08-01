from __future__ import annotations

import logging
import os
from threading import Event, Thread
from time import perf_counter
from typing import Any

from celery import signals  # type: ignore[import-untyped]

from app.core.config import Settings
from app.core.logging import reset_log_context, set_log_context
from app.core.maintenance_health import (
    MaintenanceTaskHealth,
    is_task_stale,
    load_maintenance_task_health,
    record_maintenance_task_result,
)
from app.core.tracing import configure_tracing
from app.core.worker_metrics import (
    record_maintenance_task_result_metrics,
    record_worker_task,
    set_maintenance_task_health,
    start_worker_metrics_server,
)

logger = logging.getLogger("enterprise_drive.worker")

_REGISTERED = False
_SETTINGS: Settings | None = None
_METRICS_SERVER: Any | None = None
_TASK_STATES: dict[str, tuple[float, Any | None, str]] = {}
_MAINTENANCE_REFRESH_STOP = Event()
_MAINTENANCE_REFRESH_THREAD: Thread | None = None


def configure_worker_observability(settings: Settings) -> None:
    global _REGISTERED, _SETTINGS
    _SETTINGS = settings
    configure_tracing(settings)
    if _REGISTERED:
        return
    _REGISTERED = True

    signals.worker_ready.connect(_start_metrics_server, weak=False)
    signals.worker_shutdown.connect(_stop_metrics_server, weak=False)
    signals.worker_process_shutdown.connect(_mark_worker_process_dead, weak=False)
    signals.task_prerun.connect(_task_prerun, weak=False)
    signals.task_postrun.connect(_task_postrun, weak=False)

    try:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor

        provider = configure_tracing(settings)
        if provider is not None:
            CeleryInstrumentor().instrument(  # type: ignore[no-untyped-call]
                tracer_provider=provider
            )
    except ImportError:
        logger.warning("Celery tracing instrumentation dependency is unavailable")


def _start_metrics_server(**_: Any) -> None:
    global _MAINTENANCE_REFRESH_THREAD, _METRICS_SERVER
    settings = _SETTINGS
    if settings is None or settings.worker_metrics_port <= 0:
        return
    _METRICS_SERVER = start_worker_metrics_server(port=settings.worker_metrics_port)
    if "worker-maintenance" in settings.service_name:
        _refresh_maintenance_health_metrics(settings=settings)
        _MAINTENANCE_REFRESH_STOP.clear()
        _MAINTENANCE_REFRESH_THREAD = Thread(
            target=_maintenance_refresh_loop,
            kwargs={"settings": settings},
            name="maintenance-health-refresh",
            daemon=True,
        )
        _MAINTENANCE_REFRESH_THREAD.start()


def _stop_metrics_server(**_: Any) -> None:
    global _MAINTENANCE_REFRESH_THREAD
    _MAINTENANCE_REFRESH_STOP.set()
    refresh_thread = _MAINTENANCE_REFRESH_THREAD
    if refresh_thread is not None:
        refresh_thread.join(timeout=2)
        _MAINTENANCE_REFRESH_THREAD = None
    server_bundle = _METRICS_SERVER
    if server_bundle is None:
        return
    server, thread = server_bundle
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def _mark_worker_process_dead(pid: int | None = None, **_: Any) -> None:
    if not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        return
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(pid or os.getpid())  # type: ignore[no-untyped-call]


def _task_prerun(
    *,
    task_id: str | None = None,
    task: Any = None,
    kwargs: dict[str, Any] | None = None,
    **_: Any,
) -> None:
    if not task_id:
        return
    queue = _task_queue(task)
    task_kwargs = kwargs or {}
    request_id = task_kwargs.get("request_id")
    tenant_id = task_kwargs.get("tenant_id")
    resource_id = _task_resource_id(task_kwargs)
    token = set_log_context(
        task_id=task_id,
        request_id=request_id if isinstance(request_id, str) and request_id else None,
        tenant_id=str(tenant_id) if tenant_id else None,
        resource_id=resource_id,
    )
    _TASK_STATES[task_id] = (perf_counter(), token, queue)


def _task_postrun(
    *,
    task_id: str | None = None,
    task: Any = None,
    state: str | None = None,
    retval: Any = None,
    **_: Any,
) -> None:
    if not task_id:
        return
    started_at, context_token, queue = _TASK_STATES.pop(
        task_id,
        (perf_counter(), None, _task_queue(task)),
    )
    duration_seconds = max(perf_counter() - started_at, 0.0)
    task_name = _task_name(task)
    task_status = (state or "UNKNOWN").lower()
    record_worker_task(
        task=task_name,
        queue=queue,
        status=task_status,
        duration_seconds=duration_seconds,
    )
    settings = _SETTINGS
    if settings is not None and queue == "maintenance":
        health = record_maintenance_task_result(
            settings=settings,
            task_name=task_name,
            status=task_status,
        )
        if health is not None:
            _set_maintenance_health_metric(settings=settings, health=health)
        if task_status == "success":
            record_maintenance_task_result_metrics(task=task_name, result=retval)
    logger.info(
        "Worker 任务完成",
        extra={
            "action": "worker.task",
            "status": task_status,
            "latency_ms": round(duration_seconds * 1000, 3),
            "task": task_name,
            "task_id": task_id,
            "queue": queue,
        },
    )
    if context_token is not None:
        reset_log_context(context_token)


def _task_name(task: Any) -> str:
    name = getattr(task, "name", None)
    return str(name) if name else "unknown"


def _task_queue(task: Any) -> str:
    request = getattr(task, "request", None)
    delivery_info = getattr(request, "delivery_info", None) or {}
    queue = delivery_info.get("routing_key") or delivery_info.get("queue")
    return str(queue) if queue else "unknown"


def _task_resource_id(kwargs: dict[str, Any]) -> str | None:
    for key in ("resource_id", "node_id", "version_id", "space_id", "session_id"):
        value = kwargs.get(key)
        if value:
            return str(value)
    return None


def _refresh_maintenance_health_metrics(*, settings: Settings) -> None:
    for health in load_maintenance_task_health(settings=settings):
        _set_maintenance_health_metric(settings=settings, health=health)


def _set_maintenance_health_metric(
    *,
    settings: Settings,
    health: MaintenanceTaskHealth,
) -> None:
    set_maintenance_task_health(
        task=health.task_name,
        consecutive_failures=health.consecutive_failures,
        alert_active=health.alert_active,
        stale=is_task_stale(settings=settings, health=health),
        last_finished_at=health.last_finished_at,
        last_success_at=health.last_success_at,
        last_failure_at=health.last_failure_at,
    )


def _maintenance_refresh_loop(*, settings: Settings) -> None:
    while not _MAINTENANCE_REFRESH_STOP.wait(settings.maintenance_health_refresh_seconds):
        _refresh_maintenance_health_metrics(settings=settings)
