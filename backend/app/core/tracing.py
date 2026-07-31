from __future__ import annotations

from threading import Lock
from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from app.core.config import Settings

_TRACER_PROVIDER: TracerProvider | None = None
_TRACING_LOCK = Lock()


def get_tracer_provider() -> TracerProvider | None:
    return _TRACER_PROVIDER


def configure_tracing(settings: Settings) -> TracerProvider | None:
    """Create one process-wide provider and keep exporter choice configuration-driven."""

    global _TRACER_PROVIDER
    if not settings.tracing_enabled:
        return None

    with _TRACING_LOCK:
        if _TRACER_PROVIDER is not None:
            return _TRACER_PROVIDER

        current_provider = trace.get_tracer_provider()
        if isinstance(current_provider, TracerProvider):
            _TRACER_PROVIDER = current_provider
            return current_provider

        resource = Resource.create(
            {
                "service.name": settings.service_name,
                "service.version": settings.app_version,
                "deployment.environment.name": settings.environment,
            }
        )
        provider = TracerProvider(
            sampler=ParentBased(TraceIdRatioBased(settings.tracing_sample_ratio)),
            resource=resource,
        )
        exporter = _build_exporter(settings)
        if exporter is not None:
            provider.add_span_processor(
                BatchSpanProcessor(
                    exporter,
                    export_timeout_millis=int(settings.tracing_export_timeout_seconds * 1000),
                )
            )
        trace.set_tracer_provider(provider)
        _TRACER_PROVIDER = provider
        return provider


def instrument_fastapi_app(app: FastAPI, settings: Settings) -> None:
    provider = configure_tracing(settings)
    if provider is None:
        return
    if getattr(app, "_is_instrumented_by_opentelemetry", False):
        return
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls=settings.tracing_excluded_urls or None,
        exclude_spans=["receive", "send"],
    )


def _build_exporter(settings: Settings) -> SpanExporter | None:
    if settings.tracing_exporter == "none":
        return None
    if settings.tracing_exporter == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        return ConsoleSpanExporter()
    if settings.tracing_exporter == "otlp_http":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        kwargs: dict[str, Any] = {
            "timeout": settings.tracing_export_timeout_seconds,
        }
        if settings.tracing_otlp_endpoint:
            kwargs["endpoint"] = settings.tracing_otlp_endpoint
        if settings.tracing_otlp_headers:
            kwargs["headers"] = settings.tracing_otlp_headers
        return OTLPSpanExporter(**kwargs)
    raise ValueError(f"unsupported tracing exporter: {settings.tracing_exporter}")
