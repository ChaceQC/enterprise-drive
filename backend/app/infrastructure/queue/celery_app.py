from __future__ import annotations

from celery import Celery  # type: ignore[import-untyped]

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "enterprise_drive",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.audit_tasks", "app.workers.upload_tasks"],
)

celery_app.conf.update(
    task_default_queue="maintenance",
    task_routes={
        "audit.dispatch_outbox": {"queue": "audit"},
        "upload.expire_sessions": {"queue": "maintenance"},
    },
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
