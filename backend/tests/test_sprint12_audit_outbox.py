from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import utc_now
from app.infrastructure.storage.testing import InMemoryStorageAdapter
from app.modules.audit.archive import archive_retained_audit_logs
from app.modules.audit.dispatcher import (
    OutboxDispatcher,
    OutboxPublishError,
)
from app.modules.audit.external import HttpAuditPublisher
from app.modules.audit.models import AuditArchive, AuditLog, OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.audit.signing import sign_content
from app.modules.auth.models import Tenant, User
from tests.helpers import client as client
from tests.helpers import login, seed_admin
from tests.helpers import session_factory as session_factory
from tests.helpers import settings as settings
from tests.helpers import storage_adapter as storage_adapter


class _ClassifyingPublisher:
    async def publish(self, event: OutboxEvent) -> None:
        if event.event_type.endswith("permanent"):
            raise OutboxPublishError(kind="permanent", code="invalid_payload")
        raise OutboxPublishError(kind="transient", code="dependency_timeout")


@pytest.mark.asyncio
async def test_outbox_classification_jitter_and_permanent_dead_letter(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        tenant = Tenant(slug="outbox-classification", name="Outbox 分类租户")
        session.add(tenant)
        await session.flush()
        transient = OutboxEvent(
            tenant_id=tenant.id,
            event_type="audit.fixture.transient",
            aggregate_type="audit_log",
            aggregate_id=uuid4(),
            payload={"audit_log_id": str(uuid4())},
        )
        permanent = OutboxEvent(
            tenant_id=tenant.id,
            event_type="audit.fixture.permanent",
            aggregate_type="audit_log",
            aggregate_id=uuid4(),
            payload={"audit_log_id": str(uuid4())},
        )
        session.add_all([transient, permanent])
        await session.flush()
        started_at = utc_now()

        result = await OutboxDispatcher(
            repository=AuditRepository(session),
            publisher=_ClassifyingPublisher(),
            max_retries=3,
            retry_max_delay_seconds=60,
            retry_jitter_ratio=0.25,
            random_value=lambda: 1.0,
        ).dispatch_pending(batch_size=10)
        finished_at = utc_now()

        assert result.to_dict() == {
            "claimed": 2,
            "sent": 0,
            "failed": 1,
            "dead": 1,
        }
        assert transient.status == "failed"
        assert transient.retry_count == 1
        assert transient.last_error_kind == "transient"
        assert transient.last_error_code == "dependency_timeout"
        assert started_at + timedelta(seconds=1.2) <= transient.next_retry_at
        assert transient.next_retry_at <= finished_at + timedelta(seconds=1.4)
        assert permanent.status == "dead"
        assert permanent.retry_count == 1
        assert permanent.last_error_kind == "permanent"
        assert permanent.last_error_code == "invalid_payload"
        assert permanent.dead_at is not None


@pytest.mark.asyncio
async def test_http_audit_publisher_signs_body_and_classifies_http_failures(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        tenant = Tenant(slug="audit-http", name="审计投递租户")
        session.add(tenant)
        await session.flush()
        audit_log = AuditLog(
            id=uuid4(),
            tenant_id=tenant.id,
            action="fixture.external_delivery",
            resource_type="fixture",
            result="allowed",
            risk_level="medium",
            metadata_json={"value": "visible"},
        )
        event = OutboxEvent(
            tenant_id=tenant.id,
            event_type="audit.fixture.external_delivery",
            aggregate_type="audit_log",
            aggregate_id=audit_log.id,
            payload={"audit_log_id": str(audit_log.id)},
        )
        session.add_all([audit_log, event])
        await session.flush()

        received: dict[str, object] = {}

        def success_handler(request: httpx.Request) -> httpx.Response:
            body = request.content
            received["body"] = json.loads(body)
            received["signature"] = request.headers["X-Drive-Audit-Signature"]
            expected = hmac.new(b"delivery-key", body, hashlib.sha256).hexdigest()
            assert received["signature"] == f"sha256={expected}"
            assert request.headers["X-Drive-Audit-Key-ID"] == "delivery-key-1"
            return httpx.Response(202)

        publisher = HttpAuditPublisher(
            repository=AuditRepository(session),
            endpoint_url="https://audit.example.test/events",
            hmac_key="delivery-key",
            key_id="delivery-key-1",
            timeout_seconds=1,
            transport=httpx.MockTransport(success_handler),
        )
        await publisher.publish(event)
        assert received["body"]["action"] == "fixture.external_delivery"  # type: ignore[index]

        def failure_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422)

        permanent_publisher = HttpAuditPublisher(
            repository=AuditRepository(session),
            endpoint_url="https://audit.example.test/events",
            hmac_key="delivery-key",
            key_id="delivery-key-1",
            timeout_seconds=1,
            transport=httpx.MockTransport(failure_handler),
        )
        with pytest.raises(OutboxPublishError) as captured:
            await permanent_publisher.publish(event)
        assert captured.value.kind == "permanent"
        assert captured.value.code == "external_http_422"


@pytest.mark.asyncio
async def test_admin_dead_letter_query_governance_and_idempotent_replay(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    now = utc_now()
    async with session_factory() as session:
        admin = (
            await session.execute(select(User).where(User.username == settings.admin_username))
        ).scalar_one()
        event = OutboxEvent(
            tenant_id=admin.tenant_id,
            event_type="audit.fixture.dead",
            aggregate_type="audit_log",
            aggregate_id=uuid4(),
            payload={
                "audit_log_id": str(uuid4()),
                "secret_value": "must-not-be-returned",
            },
            status="dead",
            retry_count=3,
            last_error_kind="permanent",
            last_error_code="invalid_payload",
            last_failed_at=now,
            dead_at=now,
        )
        archive = AuditArchive(
            tenant_id=admin.tenant_id,
            period_start=datetime(2025, 1, 1, tzinfo=UTC),
            period_end=datetime(2025, 2, 1, tzinfo=UTC),
            status="succeeded",
            row_count=2,
            content_sha256="a" * 64,
            signature_algorithm="hmac-sha256",
            signature_key_id="archive-key",
        )
        foreign_tenant = Tenant(slug="foreign-outbox", name="其他租户")
        session.add(foreign_tenant)
        await session.flush()
        foreign_event = OutboxEvent(
            tenant_id=foreign_tenant.id,
            event_type="audit.fixture.foreign",
            aggregate_type="audit_log",
            aggregate_id=uuid4(),
            payload={"audit_log_id": str(uuid4())},
            status="dead",
            retry_count=1,
            last_error_kind="transient",
            last_error_code="dependency_timeout",
            last_failed_at=now,
            dead_at=now,
        )
        session.add_all([event, archive, foreign_event])
        await session.commit()
        event_id = event.id

    governance = await client.get("/api/v1/admin/audit/governance")
    listing = await client.get(
        "/api/v1/admin/outbox/dead-letters",
        params={"error_kind": "permanent"},
    )
    detail = await client.get(f"/api/v1/admin/outbox/dead-letters/{event_id}")
    assert governance.status_code == 200
    assert governance.json()["outbox_dead"] == 1
    assert governance.json()["archives_total"] == 1
    assert governance.json()["recent_archives"][0]["signature_key_id"] == "archive-key"
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()["items"]] == [str(event_id)]
    assert listing.json()["items"][0]["payload_keys"] == [
        "audit_log_id",
        "secret_value",
    ]
    assert "must-not-be-returned" not in listing.text
    assert detail.status_code == 200
    assert detail.json()["last_error_code"] == "invalid_payload"

    replay = await client.post(
        f"/api/v1/admin/outbox/dead-letters/{event_id}/replay",
        headers={"X-CSRF-Token": csrf_token},
    )
    duplicate = await client.post(
        f"/api/v1/admin/outbox/dead-letters/{event_id}/replay",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["event"]["status"] == "pending"
    assert replay.json()["event"]["replay_count"] == 1
    assert duplicate.status_code == 200
    assert duplicate.json()["replayed"] is False
    assert duplicate.json()["event"]["replay_count"] == 1

    after_replay = await client.get("/api/v1/admin/outbox/dead-letters")
    assert after_replay.status_code == 200
    assert after_replay.json()["items"] == []


@pytest.mark.asyncio
async def test_audit_retention_archive_is_signed_before_source_deletion(
    session_factory: async_sessionmaker[AsyncSession],
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    signing_key = "archive-signing-key"
    async with session_factory() as session:
        tenant = Tenant(slug="archive-tenant", name="审计归档租户")
        session.add(tenant)
        await session.flush()
        session.add_all(
            [
                AuditLog(
                    id=uuid4(),
                    tenant_id=tenant.id,
                    action="fixture.archive.first",
                    resource_type="fixture",
                    result="allowed",
                    risk_level="low",
                    metadata_json={"sequence": 1},
                    created_at=datetime(2025, 1, 5, tzinfo=UTC),
                ),
                AuditLog(
                    id=uuid4(),
                    tenant_id=tenant.id,
                    action="fixture.archive.second",
                    resource_type="fixture",
                    result="allowed",
                    risk_level="low",
                    metadata_json={"sequence": 2},
                    created_at=datetime(2025, 1, 20, tzinfo=UTC),
                ),
            ]
        )
        await session.commit()
        tenant_id = tenant.id

        result = await archive_retained_audit_logs(
            session=session,
            storage=storage_adapter,
            bucket="archive-bucket",
            retention_days=365,
            max_rows=100,
            delete_source=True,
            signing_key=signing_key,
            signing_key_id="archive-key-1",
            tenant_id=tenant_id,
            reference_at=datetime(2026, 8, 4, tzinfo=UTC),
        )

        assert result["archives_created"] == 1
        assert result["rows_archived"] == 2
        assert result["source_rows_deleted"] == 2
        archive = (
            await session.execute(select(AuditArchive).where(AuditArchive.tenant_id == tenant_id))
        ).scalar_one()
        remaining = (
            (await session.execute(select(AuditLog).where(AuditLog.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
        assert remaining == []
        assert archive.status == "succeeded"
        assert archive.source_deleted_at is not None
        assert archive.storage_key is not None
        content = storage_adapter.object_contents[("archive-bucket", archive.storage_key)]
        expected_signature = sign_content(
            content=content,
            key=signing_key,
            key_id="archive-key-1",
            purpose="audit-archive",
        )
        assert archive.content_sha256 == expected_signature.content_sha256
        assert archive.signature_value == expected_signature.value
        assert archive.signature_key_id == "archive-key-1"
