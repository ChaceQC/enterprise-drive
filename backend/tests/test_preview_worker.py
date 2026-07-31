from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.core.worker_metrics import WORKER_METRICS_REGISTRY
from app.infrastructure.queue import celery_app as celery_module
from app.modules.audit.dispatcher import OutboxPublisher
from app.modules.audit.models import OutboxEvent
from app.modules.preview.events import PREVIEW_RENDER_REQUESTED
from app.modules.preview.renderer import PreviewRenderResult
from app.workers.preview_tasks import PreviewOutboxPublisher


def test_preview_dispatch_task_uses_configured_resource_limits() -> None:
    settings = Settings(
        preview_task_soft_time_limit_seconds=11,
        preview_task_time_limit_seconds=17,
        preview_task_rate_limit="5/m",
    )

    annotations = celery_module._task_annotations(settings)

    assert annotations["preview.dispatch_outbox"] == {
        "soft_time_limit": 11,
        "time_limit": 17,
        "rate_limit": "5/m",
    }


@pytest.mark.asyncio
async def test_preview_publisher_logs_terminal_non_ready_result(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant_id = uuid4()
    version_id = uuid4()
    event = _preview_event(tenant_id=tenant_id, version_id=version_id)
    publisher = PreviewOutboxPublisher(
        render_service=_FakePreviewRenderService(
            result=PreviewRenderResult(status="unsupported", reason="office_renderer_missing")
        ),
        fallback_publisher=_NoopPublisher(),
    )

    with caplog.at_level("WARNING", logger="enterprise_drive.preview"):
        await publisher.publish(event)

    record = caplog.records[0]
    extra = record.__dict__
    assert record.message == "preview render finished without artifact"
    assert extra["event_id"] == str(event.id)
    assert extra["tenant_id"] == str(tenant_id)
    assert extra["version_id"] == str(version_id)
    assert extra["preview_status"] == "unsupported"
    assert extra["preview_reason"] == "office_renderer_missing"
    assert (
        _preview_failure_sample_value(status="unsupported", reason="office_renderer_missing") >= 1
    )


@pytest.mark.asyncio
async def test_preview_publisher_logs_retryable_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant_id = uuid4()
    version_id = uuid4()
    event = _preview_event(tenant_id=tenant_id, version_id=version_id)
    event.retry_count = 2
    publisher = PreviewOutboxPublisher(
        render_service=_FailingPreviewRenderService(),
        fallback_publisher=_NoopPublisher(),
    )

    with (
        caplog.at_level("ERROR", logger="enterprise_drive.preview"),
        pytest.raises(RuntimeError, match="render failed"),
    ):
        await publisher.publish(event)

    record = caplog.records[0]
    extra = record.__dict__
    assert record.message == "preview render failed and will be retried by outbox"
    assert extra["event_id"] == str(event.id)
    assert extra["tenant_id"] == str(tenant_id)
    assert extra["version_id"] == str(version_id)
    assert extra["retry_count"] == 2
    assert _preview_failure_sample_value(status="failed", reason="exception") >= 1


def _preview_event(*, tenant_id: UUID, version_id: UUID) -> OutboxEvent:
    return OutboxEvent(
        tenant_id=tenant_id,
        event_type=PREVIEW_RENDER_REQUESTED,
        aggregate_type="file_version",
        aggregate_id=version_id,
        payload={"version_id": str(version_id)},
    )


class _FakePreviewRenderService:
    def __init__(self, *, result: PreviewRenderResult) -> None:
        self.result = result

    async def render_version(self, *, tenant_id: UUID, version_id: UUID) -> PreviewRenderResult:
        return self.result


class _FailingPreviewRenderService:
    async def render_version(self, *, tenant_id: UUID, version_id: UUID) -> PreviewRenderResult:
        raise RuntimeError("render failed")


class _NoopPublisher(OutboxPublisher):
    async def publish(self, event: OutboxEvent) -> None:
        return None


def _preview_failure_sample_value(*, status: str, reason: str) -> float:
    for metric in WORKER_METRICS_REGISTRY.collect():
        if metric.name != "preview_failures":
            continue
        for sample in metric.samples:
            if sample.name == "preview_failures_total" and sample.labels == {
                "status": status,
                "reason": reason,
            }:
                return float(sample.value)
    return 0.0
