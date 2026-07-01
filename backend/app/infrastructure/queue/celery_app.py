from __future__ import annotations

from celery import Celery  # type: ignore[import-untyped]

from app.core.config import Settings, get_settings

settings = get_settings()


def _task_annotations(settings: Settings) -> dict[str, dict[str, int | str]]:
    return {
        "preview.dispatch_outbox": {
            "soft_time_limit": settings.preview_task_soft_time_limit_seconds,
            "time_limit": settings.preview_task_time_limit_seconds,
            "rate_limit": settings.preview_task_rate_limit,
        },
    }


celery_app = Celery(
    "enterprise_drive",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.audit_tasks",
        "app.workers.file_tasks",
        "app.workers.permission_tasks",
        "app.workers.preview_tasks",
        "app.workers.search_tasks",
        "app.workers.upload_tasks",
        "app.workers.quota_tasks",
    ],
)

celery_app.conf.update(
    task_default_queue="maintenance",
    task_routes={
        "audit.dispatch_outbox": {"queue": "audit"},
        "permission.invalidate_cache": {"queue": "permission"},
        "preview.dispatch_outbox": {"queue": "preview"},
        "search.dispatch_outbox": {"queue": "search"},
        "file.cleanup_unreferenced_blobs": {"queue": "maintenance"},
        "upload.expire_sessions": {"queue": "maintenance"},
        "quota.reconcile_space_usage": {"queue": "maintenance"},
    },
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_annotations=_task_annotations(settings),
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
