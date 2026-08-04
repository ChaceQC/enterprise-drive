from __future__ import annotations

import hashlib
import hmac
import json
from uuid import UUID

import httpx

from app.modules.audit.dispatcher import OutboxPublishError
from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.audit.repository import AuditRepository


class MisconfiguredAuditPublisher:
    async def publish(self, event: OutboxEvent) -> None:
        raise OutboxPublishError(
            kind="permanent",
            code="external_signing_key_missing",
        )


class HttpAuditPublisher:
    def __init__(
        self,
        *,
        repository: AuditRepository,
        endpoint_url: str,
        hmac_key: str,
        key_id: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.repository = repository
        self.endpoint_url = endpoint_url
        self.hmac_key = hmac_key
        self.key_id = key_id
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def publish(self, event: OutboxEvent) -> None:
        audit_log_id = _audit_log_id(event)
        audit_log = await self.repository.get_audit_log(
            audit_log_id=audit_log_id,
            tenant_id=event.tenant_id,
        )
        if audit_log is None:
            raise OutboxPublishError(
                kind="permanent",
                code="audit_log_not_found",
            )
        body = _delivery_body(audit_log)
        signature = hmac.new(
            self.hmac_key.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Drive-Audit-Event-ID": str(event.id),
            "X-Drive-Audit-Key-ID": self.key_id,
            "X-Drive-Audit-Signature": f"sha256={signature}",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    self.endpoint_url,
                    content=body,
                    headers=headers,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise OutboxPublishError(
                kind="transient",
                code="external_delivery_unavailable",
            ) from exc

        if 200 <= response.status_code < 300:
            return
        if response.status_code in {408, 425, 429} or response.status_code >= 500:
            raise OutboxPublishError(
                kind="transient",
                code=f"external_http_{response.status_code}",
            )
        raise OutboxPublishError(
            kind="permanent",
            code=f"external_http_{response.status_code}",
        )


def _audit_log_id(event: OutboxEvent) -> UUID:
    value = event.payload.get("audit_log_id")
    if not isinstance(value, str):
        raise OutboxPublishError(
            kind="permanent",
            code="audit_log_id_missing",
        )
    try:
        return UUID(value)
    except ValueError as exc:
        raise OutboxPublishError(
            kind="permanent",
            code="audit_log_id_invalid",
        ) from exc


def _delivery_body(audit_log: AuditLog) -> bytes:
    payload = {
        "id": str(audit_log.id),
        "tenant_id": str(audit_log.tenant_id),
        "actor_id": str(audit_log.actor_id) if audit_log.actor_id else None,
        "actor_type": audit_log.actor_type,
        "action": audit_log.action,
        "resource_type": audit_log.resource_type,
        "resource_id": str(audit_log.resource_id) if audit_log.resource_id else None,
        "result": audit_log.result,
        "risk_level": audit_log.risk_level,
        "request_id": audit_log.request_id,
        "ip": audit_log.ip,
        "user_agent": audit_log.user_agent,
        "metadata": audit_log.metadata_json,
        "created_at": audit_log.created_at.isoformat(),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
