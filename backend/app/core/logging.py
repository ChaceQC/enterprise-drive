from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

from app.core.config import Settings

_DEFAULT_LOG_RECORD_KEYS = frozenset(logging.makeLogRecord({}).__dict__)
_LOG_CONTEXT: ContextVar[dict[str, object] | None] = ContextVar(
    "enterprise_drive_log_context",
    default=None,
)


def set_log_context(**fields: object) -> Token[dict[str, object] | None]:
    context = dict(_LOG_CONTEXT.get() or {})
    context.update(fields)
    return _LOG_CONTEXT.set(context)


def update_log_context(**fields: object) -> None:
    context = dict(_LOG_CONTEXT.get() or {})
    context.update(fields)
    _LOG_CONTEXT.set(context)


def reset_log_context(token: Token[dict[str, object] | None]) -> None:
    _LOG_CONTEXT.reset(token)


def get_log_context() -> dict[str, object]:
    return dict(_LOG_CONTEXT.get() or {})


class JsonFormatter(logging.Formatter):
    def __init__(
        self,
        *,
        service: str = "enterprise-drive-api",
        environment: str = "local",
    ) -> None:
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        log_context = get_log_context()
        span_context = trace.get_current_span().get_span_context()
        trace_id = f"{span_context.trace_id:032x}" if span_context.is_valid else None
        span_id = f"{span_context.span_id:016x}" if span_context.is_valid else None
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service,
            "env": self.environment,
            "request_id": log_context.get("request_id"),
            "task_id": log_context.get("task_id"),
            "trace_id": trace_id,
            "span_id": span_id,
            "tenant_id": log_context.get("tenant_id"),
            "user_id": log_context.get("user_id"),
            "module": record.name,
            "action": log_context.get("action"),
            "resource_type": log_context.get("resource_type"),
            "resource_id": log_context.get("resource_id"),
            "status": log_context.get("status"),
            "latency_ms": log_context.get("latency_ms"),
        }

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _DEFAULT_LOG_RECORD_KEYS and not key.startswith("_")
        }
        if extra:
            payload.update(extra)

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter(
            service=settings.service_name,
            environment=settings.environment,
        )
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level.upper())
