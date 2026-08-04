from __future__ import annotations

import asyncio
from uuid import UUID

from app.core.config import get_settings
from app.core.worker_metrics import (
    record_identity_provider_operation,
    record_ldap_sync_run,
)
from app.db.session import get_session_factory
from app.infrastructure.identity.ldap import Ldap3ProviderAdapter
from app.infrastructure.identity.secrets import EnvironmentSecretResolver
from app.infrastructure.queue.celery_app import celery_app
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.identity.ldap_service import LdapIdentityService
from app.modules.identity.repository import IdentityRepository


def sync_ldap_run(run_id: str) -> dict[str, object]:
    try:
        return asyncio.run(_sync_ldap_run(run_id=UUID(run_id)))
    except Exception:
        record_identity_provider_operation(
            provider_type="ldap",
            operation="sync",
            outcome="failure",
        )
        record_ldap_sync_run(mode="unknown", outcome="failure")
        raise


celery_app.task(name="identity.sync_ldap")(sync_ldap_run)


async def _sync_ldap_run(*, run_id: UUID) -> dict[str, object]:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = LdapIdentityService(
            repository=IdentityRepository(session),
            provider_adapter=Ldap3ProviderAdapter(
                timeout_seconds=float(getattr(settings, "identity_http_timeout_seconds", 10.0))
            ),
            secret_resolver=EnvironmentSecretResolver(),
            settings=settings,
            audit_service=AuditService(repository=AuditRepository(session)),
        )
        result = await service.execute_run(run_id=run_id)
        outcome = "success" if result.status == "succeeded" else "failure"
        record_identity_provider_operation(
            provider_type="ldap",
            operation="sync",
            outcome=outcome,
        )
        record_ldap_sync_run(mode=result.mode, outcome=outcome)
        return {
            "run_id": str(result.id),
            "status": result.status,
            "stats": result.stats,
            "error_code": result.error_code,
        }
