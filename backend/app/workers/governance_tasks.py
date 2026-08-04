from __future__ import annotations

import asyncio
from uuid import UUID

from app.core.config import get_settings
from app.core.security import utc_now
from app.db.session import get_session_factory
from app.infrastructure.queue.celery_app import celery_app
from app.infrastructure.search.opensearch import OpenSearchIndexAdapter
from app.modules.admin.job_repository import AdminJobRepository
from app.modules.admin.models import AdminJob
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.governance.permission_rebuild import PermissionRebuildProcessor
from app.modules.governance.repository import GovernanceRepository
from app.modules.search.indexer import SearchIndexService
from app.modules.search.repository import SearchRepository
from app.workers.file_tasks import (
    _cleanup_expired_trash,
    _cleanup_orphaned_objects,
    _cleanup_unreferenced_blobs,
)
from app.workers.preview_tasks import _cleanup_preview_artifacts
from app.workers.share_tasks import _expire_shares
from app.workers.upload_tasks import _expire_upload_sessions


def process_permission_rebuilds(
    limit: int = 100,
    tenant_id: str | None = None,
) -> dict[str, int]:
    return asyncio.run(
        _process_permission_rebuilds(
            limit=limit,
            tenant_id=UUID(tenant_id) if tenant_id else None,
        )
    )


def run_lifecycle_policy(job_id: str) -> dict[str, object]:
    return asyncio.run(_run_lifecycle_policy(job_id=UUID(job_id)))


celery_app.task(name="governance.process_permission_rebuilds")(process_permission_rebuilds)
celery_app.task(name="governance.run_lifecycle_policy")(run_lifecycle_policy)


async def _process_permission_rebuilds(
    *,
    limit: int,
    tenant_id: UUID | None,
) -> dict[str, int]:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        repository = GovernanceRepository(session)
        return await PermissionRebuildProcessor(
            repository=repository,
            index_service=SearchIndexService(
                repository=SearchRepository(session),
                index_adapter=OpenSearchIndexAdapter(settings=settings),
            ),
            audit_service=AuditService(repository=AuditRepository(session)),
            batch_size=settings.file_tree_operation_batch_size,
        ).process_pending(limit=limit, tenant_id=tenant_id)


async def _run_lifecycle_policy(*, job_id: UUID) -> dict[str, object]:
    job = await _start_governance_job(job_id=job_id)
    if job is None:
        return {"status": "skipped", "reason": "job_not_runnable"}
    try:
        result = await _execute_lifecycle_policy(job=job)
    except Exception as exc:
        await _finish_governance_job(
            job_id=job.id,
            status="failed",
            result={},
            error_code="LIFECYCLE_RUN_FAILED",
            error_message=type(exc).__name__,
        )
        raise
    await _finish_governance_job(
        job_id=job.id,
        status="succeeded",
        result=result,
        error_code=None,
        error_message=None,
    )
    return result


async def _execute_lifecycle_policy(*, job: AdminJob) -> dict[str, object]:
    parameters = job.parameters_json
    tenant_id = UUID(str(parameters["tenant_id"]))
    limit = _as_int(parameters.get("limit"), default=100)
    dry_run = bool(parameters.get("dry_run", True))
    request_id = _optional_str(parameters.get("request_id"))
    trash_retention_days = _as_int(
        parameters.get("trash_retention_days"),
        default=30,
    )
    preview_retention_days = _as_int(
        parameters.get("preview_retention_days"),
        default=30,
    )

    result: dict[str, object] = {
        "dry_run": dry_run,
        "policy_version": _as_int(parameters.get("policy_version"), default=1),
    }
    if dry_run:
        session_factory = get_session_factory()
        async with session_factory() as session:
            result["database_candidates"] = await GovernanceRepository(
                session
            ).lifecycle_dry_run_counts(
                tenant_id=tenant_id,
                trash_retention_days=trash_retention_days,
                preview_retention_days=preview_retention_days,
            )
    else:
        if bool(parameters.get("expire_uploads", True)):
            result["uploads"] = dict(
                await _expire_upload_sessions(
                    tenant_id=tenant_id,
                    limit=limit,
                    request_id=request_id,
                )
            )
        result["trash"] = dict(
            await _cleanup_expired_trash(
                tenant_id=tenant_id,
                limit=limit,
                retention_days=trash_retention_days,
                request_id=request_id,
            )
        )
        if bool(parameters.get("expire_shares", True)):
            result["shares"] = dict(
                await _expire_shares(
                    tenant_id=tenant_id,
                    limit=limit,
                    request_id=request_id,
                )
            )

    result["preview"] = await _cleanup_preview_artifacts(
        tenant_id=tenant_id,
        limit=limit,
        retention_days=preview_retention_days,
        dry_run=dry_run,
        request_id=request_id,
        scan_all=True,
    )
    if bool(parameters.get("cleanup_unreferenced_blobs", True)):
        if dry_run:
            # database_candidates 已提供待处理数量；不删除对象。
            result["unreferenced_blobs"] = {
                "dry_run": True,
                "candidate_count": _candidate_count(
                    result,
                    "unreferenced_blobs",
                ),
            }
        else:
            result["unreferenced_blobs"] = dict(
                await _cleanup_unreferenced_blobs(
                    tenant_id=tenant_id,
                    limit=limit,
                    request_id=request_id,
                )
            )
    if bool(parameters.get("cleanup_orphaned_objects", False)):
        result["orphaned_objects"] = await _cleanup_orphaned_objects(
            tenant_id=tenant_id,
            limit=limit,
            dry_run=dry_run,
            request_id=request_id,
            scan_all=True,
        )
    return result


async def _start_governance_job(*, job_id: UUID) -> AdminJob | None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        repository = AdminJobRepository(session)
        job = await repository.get_job_for_update(job_id=job_id)
        if (
            job is None
            or job.kind != "governance"
            or job.operation != "lifecycle.run_policy"
            or job.status != "pending"
        ):
            await repository.rollback()
            return None
        job.status = "running"
        job.started_at = utc_now()
        job.version += 1
        await repository.commit()
        return job


async def _finish_governance_job(
    *,
    job_id: UUID,
    status: str,
    result: dict[str, object],
    error_code: str | None,
    error_message: str | None,
) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        repository = AdminJobRepository(session)
        job = await repository.get_job_for_update(job_id=job_id)
        if job is None:
            await repository.rollback()
            return
        job.status = status
        job.result_json = result
        job.error_code = error_code
        job.error_message = error_message
        job.completed_at = utc_now()
        job.version += 1
        audit_service = AuditService(repository=AuditRepository(session))
        await audit_service.record(
            event=AuditEvent(
                tenant_id=job.tenant_id,
                actor_id=job.created_by,
                action=f"admin.lifecycle_run.{status}",
                resource_type="lifecycle_run",
                resource_id=job.id,
                result="allowed" if status == "succeeded" else "failed",
                risk_level="high",
                metadata={
                    "error_code": error_code,
                    "dry_run": bool(job.parameters_json.get("dry_run", True)),
                    "policy_version": _as_int(
                        job.parameters_json.get("policy_version"),
                        default=1,
                    ),
                },
            ),
            context=AuditContext(request_id=_optional_str(job.parameters_json.get("request_id"))),
        )
        await repository.commit()


def _candidate_count(result: dict[str, object], key: str) -> int:
    counts = result.get("database_candidates")
    if not isinstance(counts, dict):
        return 0
    value = counts.get(key, 0)
    return int(value) if isinstance(value, int) else 0


def _optional_str(value: object) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _as_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default
