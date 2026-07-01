from __future__ import annotations

from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, generate_latest
from starlette.responses import Response

METRICS_REGISTRY = CollectorRegistry()

preview_failures_total = Counter(
    "preview_failures_total",
    "预览失败数",
    ("status", "reason"),
    registry=METRICS_REGISTRY,
)


def record_preview_failure(*, status: str, reason: str) -> None:
    preview_failures_total.labels(status=status, reason=reason).inc()


def register_metrics_route(app: FastAPI) -> None:
    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(
            content=generate_latest(METRICS_REGISTRY),
            media_type=CONTENT_TYPE_LATEST,
        )
