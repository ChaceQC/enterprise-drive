from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings

_DEFAULT_LOG_RECORD_KEYS = frozenset(logging.makeLogRecord({}).__dict__)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
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

        return json.dumps(payload, ensure_ascii=False)


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level.upper())
