from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast

import redis

from app.core.config import Settings

logger = logging.getLogger("enterprise_drive.maintenance")

MAINTENANCE_TASK_INTERVAL_SECONDS: dict[str, str] = {
    "upload.expire_sessions": "upload_cleanup_interval_seconds",
    "file.cleanup_expired_trash": "trash_cleanup_interval_seconds",
    "share.expire_shares": "share_expiry_interval_seconds",
    "preview.cleanup_artifacts": "preview_cleanup_interval_seconds",
    "file.process_tree_operations": "file_tree_operation_interval_seconds",
    "file.cleanup_unreferenced_blobs": "blob_cleanup_interval_seconds",
    "file.cleanup_orphaned_objects": "orphan_object_scan_interval_seconds",
    "quota.reconcile_space_usage": "quota_reconciliation_interval_seconds",
    "admin.cleanup_expired_exports": "admin_export_cleanup_interval_seconds",
}

_RECORD_RESULT_LUA = """
local failures
if ARGV[2] == "success" then
  failures = 0
  redis.call("HSET", KEYS[1],
    "consecutive_failures", "0",
    "last_status", ARGV[2],
    "last_finished_at", ARGV[1],
    "last_success_at", ARGV[1],
    "alert_active", "0")
else
  failures = redis.call("HINCRBY", KEYS[1], "consecutive_failures", 1)
  local alert_active = "0"
  if failures >= tonumber(ARGV[3]) then
    alert_active = "1"
  end
  redis.call("HSET", KEYS[1],
    "last_status", ARGV[2],
    "last_finished_at", ARGV[1],
    "last_failure_at", ARGV[1],
    "alert_active", alert_active)
end
redis.call("EXPIRE", KEYS[1], ARGV[4])
return redis.call("HGETALL", KEYS[1])
"""


@dataclass(frozen=True, slots=True)
class MaintenanceTaskHealth:
    task_name: str
    consecutive_failures: int
    alert_active: bool
    last_status: str
    last_finished_at: float
    last_success_at: float
    last_failure_at: float


class MaintenanceHealthStore(Protocol):
    def record_result(self, *, task_name: str, status: str) -> MaintenanceTaskHealth: ...

    def load_all(self) -> list[MaintenanceTaskHealth]: ...

    def close(self) -> None: ...


class RedisMaintenanceHealthStore:
    def __init__(self, *, settings: Settings) -> None:
        self.settings = settings
        self._client = cast(
            Any,
            redis.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_timeout=settings.maintenance_state_redis_timeout_seconds,
                socket_connect_timeout=settings.maintenance_state_redis_timeout_seconds,
            ),
        )

    def record_result(self, *, task_name: str, status: str) -> MaintenanceTaskHealth:
        normalized_status = status.strip().lower() or "unknown"
        raw = self._client.eval(
            _RECORD_RESULT_LUA,
            1,
            self._key(task_name),
            str(datetime.now(UTC).timestamp()),
            normalized_status,
            self.settings.maintenance_alert_consecutive_failures,
            self.settings.maintenance_state_ttl_seconds,
        )
        return _decode_health(task_name=task_name, raw=raw)

    def load_all(self) -> list[MaintenanceTaskHealth]:
        task_names = list(MAINTENANCE_TASK_INTERVAL_SECONDS)
        with self._client.pipeline(transaction=False) as pipeline:
            for task_name in task_names:
                pipeline.hgetall(self._key(task_name))
            payloads = pipeline.execute()
        return [
            _decode_health(task_name=task_name, raw=raw)
            for task_name, raw in zip(task_names, payloads, strict=True)
        ]

    def close(self) -> None:
        self._client.close()

    def _key(self, task_name: str) -> str:
        return f"maintenance_health:{task_name}"


def record_maintenance_task_result(
    *,
    settings: Settings,
    task_name: str,
    status: str,
    store: MaintenanceHealthStore | None = None,
) -> MaintenanceTaskHealth | None:
    if task_name not in MAINTENANCE_TASK_INTERVAL_SECONDS:
        return None
    owned_store = store is None
    health_store = store
    try:
        if health_store is None:
            health_store = RedisMaintenanceHealthStore(settings=settings)
        health = health_store.record_result(task_name=task_name, status=status)
    except Exception:
        logger.exception(
            "维护任务状态写入失败",
            extra={"task": task_name, "status": status},
        )
        return None
    finally:
        if owned_store and health_store is not None:
            _close_store_quietly(health_store)

    if (
        health.alert_active
        and health.consecutive_failures == settings.maintenance_alert_consecutive_failures
    ):
        logger.error(
            "维护任务连续失败告警",
            extra={
                "action": "maintenance.alert",
                "task": task_name,
                "status": health.last_status,
                "consecutive_failures": health.consecutive_failures,
                "threshold": settings.maintenance_alert_consecutive_failures,
            },
        )
    return health


def load_maintenance_task_health(
    *,
    settings: Settings,
    store: MaintenanceHealthStore | None = None,
) -> list[MaintenanceTaskHealth]:
    owned_store = store is None
    health_store = store
    try:
        if health_store is None:
            health_store = RedisMaintenanceHealthStore(settings=settings)
        return health_store.load_all()
    except Exception:
        logger.exception("维护任务状态读取失败")
        return [
            MaintenanceTaskHealth(
                task_name=task_name,
                consecutive_failures=0,
                alert_active=False,
                last_status="unknown",
                last_finished_at=0.0,
                last_success_at=0.0,
                last_failure_at=0.0,
            )
            for task_name in MAINTENANCE_TASK_INTERVAL_SECONDS
        ]
    finally:
        if owned_store and health_store is not None:
            _close_store_quietly(health_store)


def expected_interval_seconds(*, settings: Settings, task_name: str) -> int:
    attribute_name = MAINTENANCE_TASK_INTERVAL_SECONDS[task_name]
    return int(getattr(settings, attribute_name))


def is_task_stale(
    *,
    settings: Settings,
    health: MaintenanceTaskHealth,
    now_timestamp: float | None = None,
) -> bool:
    if health.last_finished_at <= 0:
        return False
    current_timestamp = (
        now_timestamp if now_timestamp is not None else datetime.now(UTC).timestamp()
    )
    allowed_age = (
        expected_interval_seconds(settings=settings, task_name=health.task_name)
        * settings.maintenance_alert_stale_intervals
    )
    return current_timestamp - health.last_finished_at > allowed_age


def _decode_health(*, task_name: str, raw: Any) -> MaintenanceTaskHealth:
    payload = _decode_hash(raw)
    return MaintenanceTaskHealth(
        task_name=task_name,
        consecutive_failures=_int_value(payload.get("consecutive_failures")),
        alert_active=payload.get("alert_active") == "1",
        last_status=payload.get("last_status") or "unknown",
        last_finished_at=_float_value(payload.get("last_finished_at")),
        last_success_at=_float_value(payload.get("last_success_at")),
        last_failure_at=_float_value(payload.get("last_failure_at")),
    )


def _decode_hash(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    if isinstance(raw, list):
        return {str(raw[index]): str(raw[index + 1]) for index in range(0, len(raw) - 1, 2)}
    if isinstance(raw, str):
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(key): str(value) for key, value in parsed.items()}
    return {}


def _int_value(value: str | None) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


def _float_value(value: str | None) -> float:
    try:
        return float(value or 0)
    except ValueError:
        return 0.0


def _close_store_quietly(store: MaintenanceHealthStore) -> None:
    try:
        store.close()
    except Exception:
        logger.exception("维护任务状态连接关闭失败")
