from __future__ import annotations

import asyncio
import atexit
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import wraps
from time import perf_counter
from typing import ParamSpec, TypeVar

from fastapi import FastAPI
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)
from starlette.responses import Response

from app.core.config import Settings

API_METRICS_REGISTRY = CollectorRegistry()
METRICS_REGISTRY = API_METRICS_REGISTRY

http_requests_total = Counter(
    "http_requests_total",
    "HTTP 请求总数",
    ("method", "route", "status_code"),
    registry=API_METRICS_REGISTRY,
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP 请求处理耗时",
    ("method", "route"),
    registry=API_METRICS_REGISTRY,
)

upload_sessions_total = Counter(
    "upload_sessions_total",
    "上传会话数量",
    ("mode", "outcome"),
    registry=API_METRICS_REGISTRY,
)

upload_failures_total = Counter(
    "upload_failures_total",
    "上传失败数量",
    ("stage", "reason"),
    registry=API_METRICS_REGISTRY,
)

download_requests_total = Counter(
    "download_requests_total",
    "下载请求数量",
    ("channel", "outcome"),
    registry=API_METRICS_REGISTRY,
)

auth_security_events_total = Counter(
    "auth_security_events_total",
    "认证与账号安全事件数量",
    ("event", "outcome"),
    registry=API_METRICS_REGISTRY,
)

identity_provider_operations_total = Counter(
    "identity_provider_operations_total",
    "外部身份提供商操作数量",
    ("provider_type", "operation", "outcome"),
    registry=API_METRICS_REGISTRY,
)

ldap_sync_runs_total = Counter(
    "ldap_sync_runs_total",
    "LDAP 同步运行数量",
    ("mode", "outcome"),
    registry=API_METRICS_REGISTRY,
)

permission_decision_duration_seconds = Histogram(
    "permission_decision_duration_seconds",
    "权限判断耗时",
    ("scope", "action", "outcome"),
    registry=API_METRICS_REGISTRY,
)

search_index_lag_seconds = Gauge(
    "search_index_lag_seconds",
    "搜索索引待处理事件的最大延迟",
    registry=API_METRICS_REGISTRY,
    multiprocess_mode="livemostrecent",
)

outbox_pending_total = Gauge(
    "outbox_pending_total",
    "Outbox 各状态事件数量",
    ("status",),
    registry=API_METRICS_REGISTRY,
    multiprocess_mode="livemostrecent",
)

_OUTBOX_STATUSES = ("pending", "failed", "processing", "dead", "sent")
_MAX_LABEL_LENGTH = 128
P = ParamSpec("P")
R = TypeVar("R")


def record_http_request(
    *,
    method: str,
    route: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    normalized_method = method.upper() if method else "UNKNOWN"
    normalized_route = route if route.startswith("/") else "unmatched"
    normalized_route = normalized_route[:_MAX_LABEL_LENGTH]
    http_requests_total.labels(
        method=normalized_method,
        route=normalized_route,
        status_code=str(status_code),
    ).inc()
    http_request_duration_seconds.labels(
        method=normalized_method,
        route=normalized_route,
    ).observe(max(duration_seconds, 0.0))


def record_upload_session(*, mode: str, outcome: str = "created") -> None:
    upload_sessions_total.labels(
        mode=_bounded_label(mode),
        outcome=_bounded_label(outcome),
    ).inc()


def record_upload_failure(*, stage: str, reason: str) -> None:
    upload_failures_total.labels(
        stage=_bounded_label(stage),
        reason=_bounded_label(reason),
    ).inc()


def record_download_request(*, channel: str, outcome: str) -> None:
    download_requests_total.labels(
        channel=_bounded_label(channel),
        outcome=_bounded_label(outcome),
    ).inc()


def record_auth_security_event(*, event: str, outcome: str) -> None:
    auth_security_events_total.labels(
        event=_bounded_label(event),
        outcome=_bounded_label(outcome),
    ).inc()


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


def record_permission_decision(
    *,
    scope: str,
    action: str,
    outcome: str,
    duration_seconds: float,
) -> None:
    permission_decision_duration_seconds.labels(
        scope=_bounded_label(scope),
        action=_bounded_label(action),
        outcome=_bounded_label(outcome),
    ).observe(max(duration_seconds, 0.0))


def instrument_permission_decision(
    *,
    scope: str,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            started_at = perf_counter()
            outcome = "error"
            action_value = kwargs.get("action", "batch")
            action = str(action_value) if isinstance(action_value, str) else "batch"
            try:
                result = await func(*args, **kwargs)
                outcome = _permission_outcome(result)
                return result
            finally:
                record_permission_decision(
                    scope=scope,
                    action=action,
                    outcome=outcome,
                    duration_seconds=perf_counter() - started_at,
                )

        return wrapped

    return decorator


def set_outbox_pending_metrics(counts: dict[str, int]) -> None:
    for status in _OUTBOX_STATUSES:
        outbox_pending_total.labels(status=status).set(max(int(counts.get(status, 0)), 0))


def set_search_index_lag(*, lag_seconds: float) -> None:
    search_index_lag_seconds.set(max(lag_seconds, 0.0))


def metrics_registry_for_exposition(
    local_registry: CollectorRegistry = API_METRICS_REGISTRY,
) -> CollectorRegistry:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        return registry
    return local_registry


async def refresh_database_metrics(settings: Settings) -> None:
    """Refresh gauges from PostgreSQL without making a scrape depend on database health."""

    if not settings.metrics_database_refresh_enabled or settings.environment == "test":
        return

    from sqlalchemy import func, select

    from app.core.security import ensure_utc
    from app.db.session import get_session_factory
    from app.modules.audit.models import OutboxEvent

    try:
        async with asyncio.timeout(settings.metrics_database_refresh_timeout_seconds):
            session_factory = get_session_factory()
            async with session_factory() as session:
                result = await session.execute(
                    select(OutboxEvent.status, func.count()).group_by(OutboxEvent.status)
                )
                counts = {
                    str(status): int(count) for status, count in result.all() if status is not None
                }
                set_outbox_pending_metrics(counts)

                oldest = await session.scalar(
                    select(func.min(OutboxEvent.created_at)).where(
                        OutboxEvent.event_type.like("search.%"),
                        OutboxEvent.status.in_(["pending", "failed", "processing"]),
                    )
                )
                if oldest is None:
                    set_search_index_lag(lag_seconds=0.0)
                else:
                    created_at = ensure_utc(oldest)
                    set_search_index_lag(
                        lag_seconds=max((datetime.now(UTC) - created_at).total_seconds(), 0.0)
                    )
    except Exception:
        # A metrics scrape must remain useful while PostgreSQL is restarting.
        return


def register_metrics_route(app: FastAPI, settings: Settings | None = None) -> None:
    app_settings = settings

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        if app_settings is not None:
            await refresh_database_metrics(app_settings)
        return Response(
            content=generate_latest(metrics_registry_for_exposition(API_METRICS_REGISTRY)),
            media_type=CONTENT_TYPE_LATEST,
        )


def _bounded_label(value: str, *, fallback: str = "unknown") -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    return (normalized or fallback)[:_MAX_LABEL_LENGTH]


def _permission_outcome(result: object) -> str:
    if isinstance(result, bool):
        return "allowed" if result else "denied"
    if isinstance(result, dict):
        decisions = [
            decision
            for node_permissions in result.values()
            if isinstance(node_permissions, dict)
            for decision in node_permissions.values()
            if isinstance(decision, bool)
        ]
        if not decisions or not any(decisions):
            return "denied"
        if all(decisions):
            return "allowed"
        return "mixed"
    return "completed"


def _mark_current_process_dead() -> None:
    if not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        return
    try:
        multiprocess.mark_process_dead(os.getpid())  # type: ignore[no-untyped-call]
    except OSError:
        return


if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
    atexit.register(_mark_current_process_dead)
