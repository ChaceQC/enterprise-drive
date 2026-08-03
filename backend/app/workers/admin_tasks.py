from __future__ import annotations

import asyncio
import csv
import io
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import utc_now
from app.db.session import get_session_factory
from app.infrastructure.queue.celery_app import celery_app
from app.infrastructure.storage.s3 import S3StorageAdapter
from app.modules.admin.job_repository import AdminJobRepository
from app.modules.admin.models import AdminJob
from app.modules.audit.models import AuditLog
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.models import Node
from app.modules.permission.models import SpaceMember
from app.modules.quota.models import QuotaAccount
from app.modules.space.models import Space
from app.workers.file_tasks import (
    _cleanup_expired_trash,
    _cleanup_orphaned_objects,
    _cleanup_unreferenced_blobs,
    _process_tree_operations,
)
from app.workers.preview_tasks import _cleanup_preview_artifacts
from app.workers.quota_tasks import _reconcile_space_usage
from app.workers.share_tasks import _expire_shares
from app.workers.upload_tasks import _expire_upload_sessions


class AdminExportRowLimitExceededError(ValueError):
    pass


def execute_maintenance_run(job_id: str) -> dict[str, object]:
    return asyncio.run(_execute_maintenance_run(job_id=UUID(job_id)))


def generate_export(job_id: str) -> dict[str, object]:
    return asyncio.run(_generate_export(job_id=UUID(job_id)))


def cleanup_expired_exports(
    limit: int = 100,
    tenant_id: str | None = None,
) -> dict[str, int]:
    return asyncio.run(
        _cleanup_expired_exports(
            limit=limit,
            tenant_id=UUID(tenant_id) if tenant_id else None,
        )
    )


celery_app.task(name="admin.execute_maintenance_run")(execute_maintenance_run)
celery_app.task(name="admin.generate_export")(generate_export)
celery_app.task(name="admin.cleanup_expired_exports")(cleanup_expired_exports)


async def _execute_maintenance_run(*, job_id: UUID) -> dict[str, object]:
    job = await _start_job(job_id=job_id, kind="maintenance")
    if job is None:
        return {"status": "skipped", "reason": "job_not_runnable"}
    try:
        result = await _run_maintenance_operation(
            operation=job.operation,
            parameters=job.parameters_json,
        )
    except Exception as exc:
        await _finish_job_failed(
            job_id=job.id,
            error_code="ADMIN_MAINTENANCE_RUN_FAILED",
            error_message=type(exc).__name__,
        )
        raise
    await _finish_job_succeeded(job_id=job.id, result=result)
    return result


async def _generate_export(*, job_id: UUID) -> dict[str, object]:
    settings = get_settings()
    job = await _start_job(job_id=job_id, kind="export")
    if job is None:
        return {"status": "skipped", "reason": "job_not_runnable"}
    try:
        content, row_count = await _export_csv(
            tenant_id=job.tenant_id,
            resource=job.operation,
            filters=_filters(job),
            max_rows=settings.admin_export_max_rows,
        )
        file_name = _export_file_name(resource=job.operation, job_id=job.id)
        storage_key = f"exports/{job.tenant_id}/{job.id}/{file_name}"
        storage = S3StorageAdapter(settings=settings)
        await storage.put_object_bytes(
            bucket=settings.s3_bucket,
            storage_key=storage_key,
            content=content,
            content_type="text/csv; charset=utf-8",
        )
    except AdminExportRowLimitExceededError as exc:
        await _finish_job_failed(
            job_id=job.id,
            error_code="ADMIN_EXPORT_ROW_LIMIT_EXCEEDED",
            error_message=str(exc),
        )
        raise
    except Exception as exc:
        await _finish_job_failed(
            job_id=job.id,
            error_code="ADMIN_EXPORT_GENERATION_FAILED",
            error_message=type(exc).__name__,
        )
        raise
    await _finish_export_succeeded(
        job_id=job.id,
        result={"row_count": row_count},
        bucket=settings.s3_bucket,
        storage_key=storage_key,
        file_name=file_name,
        size_bytes=len(content),
    )
    return {"row_count": row_count, "size_bytes": len(content)}


async def _cleanup_expired_exports(
    *,
    limit: int,
    tenant_id: UUID | None = None,
) -> dict[str, int]:
    settings = get_settings()
    storage = S3StorageAdapter(settings=settings)
    session_factory = get_session_factory()
    result = {"scanned": 0, "expired": 0, "storage_errors": 0}
    cutoff = datetime.now(UTC) - timedelta(days=settings.admin_export_retention_days)
    async with session_factory() as session:
        repository = AdminJobRepository(session)
        jobs = await repository.list_expired_export_jobs(
            before=cutoff,
            limit=limit,
            tenant_id=tenant_id,
        )
        candidates = [
            (job.id, job.storage_bucket, job.storage_key)
            for job in jobs
            if job.storage_bucket is not None and job.storage_key is not None
        ]
    result["scanned"] = len(candidates)
    for job_id, storage_bucket, storage_key in candidates:
        try:
            await storage.delete_object(
                bucket=storage_bucket,
                storage_key=storage_key,
            )
        except Exception:
            result["storage_errors"] += 1
            continue
        async with session_factory() as session:
            repository = AdminJobRepository(session)
            job = await repository.get_job_for_update(job_id=job_id)
            if (
                job is None
                or job.kind != "export"
                or job.status != "succeeded"
                or job.completed_at is None
                or _as_utc(job.completed_at) >= cutoff
                or job.storage_bucket != storage_bucket
                or job.storage_key != storage_key
            ):
                await repository.rollback()
                continue
            job.status = "expired"
            job.storage_bucket = None
            job.storage_key = None
            job.result_json = {**job.result_json, "expired_at": utc_now().isoformat()}
            job.version += 1
            await _record_export_expired(session=session, job=job)
            await repository.commit()
            result["expired"] += 1
    return result


async def _start_job(*, job_id: UUID, kind: str) -> AdminJob | None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        repository = AdminJobRepository(session)
        job = await repository.get_job_for_update(job_id=job_id)
        if job is None or job.kind != kind or job.status != "pending":
            await repository.rollback()
            return None
        job.status = "running"
        job.started_at = utc_now()
        job.version += 1
        await repository.commit()
        return job


async def _finish_job_succeeded(*, job_id: UUID, result: dict[str, object]) -> None:
    await _finish_job(
        job_id=job_id,
        status="succeeded",
        result=result,
        error_code=None,
        error_message=None,
    )


async def _finish_job_failed(*, job_id: UUID, error_code: str, error_message: str) -> None:
    await _finish_job(
        job_id=job_id,
        status="failed",
        result={},
        error_code=error_code,
        error_message=error_message,
    )


async def _finish_job(
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
            return
        job.status = status
        job.result_json = result
        job.error_code = error_code
        job.error_message = error_message
        job.completed_at = utc_now()
        job.version += 1
        await _record_job_completion(session=session, job=job)
        await repository.commit()


async def _finish_export_succeeded(
    *,
    job_id: UUID,
    result: dict[str, object],
    bucket: str,
    storage_key: str,
    file_name: str,
    size_bytes: int,
) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        repository = AdminJobRepository(session)
        job = await repository.get_job_for_update(job_id=job_id)
        if job is None:
            return
        job.status = "succeeded"
        job.result_json = result
        job.storage_bucket = bucket
        job.storage_key = storage_key
        job.file_name = file_name
        job.content_type = "text/csv; charset=utf-8"
        job.size_bytes = size_bytes
        job.completed_at = utc_now()
        job.version += 1
        await _record_job_completion(session=session, job=job)
        await repository.commit()


async def _record_job_completion(*, session: AsyncSession, job: AdminJob) -> None:
    audit_service = AuditService(repository=AuditRepository(session))
    await audit_service.record(
        event=AuditEvent(
            tenant_id=job.tenant_id,
            actor_id=job.created_by,
            action=f"admin.{job.kind}_job.{job.status}",
            resource_type=f"{job.kind}_job",
            resource_id=job.id,
            result="allowed" if job.status == "succeeded" else "denied",
            risk_level="high",
            metadata={
                "operation": job.operation,
                "error_code": job.error_code,
                "result": _audit_result_summary(job.result_json),
            },
        ),
        context=AuditContext(),
    )


async def _record_export_expired(*, session: AsyncSession, job: AdminJob) -> None:
    audit_service = AuditService(repository=AuditRepository(session))
    await audit_service.record(
        event=AuditEvent(
            tenant_id=job.tenant_id,
            actor_id=job.created_by,
            action="admin.export.expired",
            resource_type="export_job",
            resource_id=job.id,
            result="allowed",
            risk_level="medium",
            metadata={
                "operation": job.operation,
                "file_name": job.file_name,
                "size_bytes": job.size_bytes,
            },
        ),
        context=AuditContext(),
    )


async def _run_maintenance_operation(
    *,
    operation: str,
    parameters: dict[str, object],
) -> dict[str, object]:
    tenant_id = _uuid_parameter(parameters, "tenant_id")
    limit = _int_parameter(parameters, "limit", 100)
    request_id = _str_parameter(parameters, "request_id")
    if operation == "upload.expire_sessions":
        return dict(
            await _expire_upload_sessions(
                tenant_id=tenant_id,
                limit=limit,
                request_id=request_id,
            )
        )
    if operation == "file.cleanup_expired_trash":
        return dict(
            await _cleanup_expired_trash(
                tenant_id=tenant_id,
                limit=limit,
                retention_days=_optional_int_parameter(parameters, "retention_days"),
                request_id=request_id,
            )
        )
    if operation == "share.expire_shares":
        return dict(
            await _expire_shares(
                tenant_id=tenant_id,
                limit=limit,
                request_id=request_id,
            )
        )
    if operation == "preview.cleanup_artifacts":
        return await _cleanup_preview_artifacts(
            tenant_id=tenant_id,
            limit=limit,
            retention_days=_optional_int_parameter(parameters, "retention_days"),
            dry_run=_bool_parameter(parameters, "dry_run", True),
            request_id=request_id,
            scan_all=_bool_parameter(parameters, "scan_all", True),
        )
    if operation == "file.process_tree_operations":
        return dict(await _process_tree_operations(limit=limit, tenant_id=tenant_id))
    if operation == "file.cleanup_unreferenced_blobs":
        return dict(
            await _cleanup_unreferenced_blobs(
                tenant_id=tenant_id,
                limit=limit,
                request_id=request_id,
            )
        )
    if operation == "file.cleanup_orphaned_objects":
        return await _cleanup_orphaned_objects(
            tenant_id=tenant_id,
            limit=limit,
            dry_run=_bool_parameter(parameters, "dry_run", True),
            request_id=request_id,
            scan_all=_bool_parameter(parameters, "scan_all", True),
        )
    if operation == "quota.reconcile_space_usage":
        return await _reconcile_space_usage(
            tenant_id=tenant_id,
            limit=limit,
            repair=_bool_parameter(parameters, "repair", False),
            request_id=request_id,
            scan_all=_bool_parameter(parameters, "scan_all", True),
        )
    if operation == "admin.cleanup_expired_exports":
        return dict(await _cleanup_expired_exports(limit=limit, tenant_id=tenant_id))
    raise ValueError(f"unsupported maintenance operation: {operation}")


async def _export_csv(
    *,
    tenant_id: UUID,
    resource: str,
    filters: dict[str, object],
    max_rows: int,
) -> tuple[bytes, int]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        if resource == "audit_logs":
            headers, rows = await _audit_rows(
                session=session,
                tenant_id=tenant_id,
                filters=filters,
                max_rows=max_rows,
            )
        elif resource == "spaces":
            headers, rows = await _space_rows(
                session=session,
                tenant_id=tenant_id,
                filters=filters,
                max_rows=max_rows,
            )
        elif resource == "users":
            headers, rows = await _user_rows(
                session=session,
                tenant_id=tenant_id,
                filters=filters,
                max_rows=max_rows,
            )
        else:
            raise ValueError(f"unsupported export resource: {resource}")
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows([_safe_csv_cell(value) for value in row] for row in rows)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8"), len(rows)


async def _audit_rows(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    filters: dict[str, object],
    max_rows: int,
) -> tuple[list[str], list[list[object]]]:
    conditions = [AuditLog.tenant_id == tenant_id]
    for key in ("action", "result", "risk_level"):
        value = filters.get(key)
        if isinstance(value, str):
            conditions.append(getattr(AuditLog, key) == value)
    created_from = _datetime_filter(filters.get("created_from"))
    created_to = _datetime_filter(filters.get("created_to"))
    if created_from is not None:
        conditions.append(AuditLog.created_at >= created_from)
    if created_to is not None:
        conditions.append(AuditLog.created_at <= created_to)
    result = await session.execute(
        select(AuditLog)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(max_rows + 1)
    )
    logs = list(result.scalars().all())
    _raise_if_export_too_large(resource="audit_logs", count=len(logs), max_rows=max_rows)
    return (
        [
            "id",
            "actor_id",
            "actor_type",
            "action",
            "resource_type",
            "resource_id",
            "result",
            "risk_level",
            "request_id",
            "created_at",
        ],
        [
            [
                log.id,
                log.actor_id,
                log.actor_type,
                log.action,
                log.resource_type,
                log.resource_id,
                log.result,
                log.risk_level,
                log.request_id,
                log.created_at.isoformat(),
            ]
            for log in logs
        ],
    )


async def _space_rows(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    filters: dict[str, object],
    max_rows: int,
) -> tuple[list[str], list[list[object]]]:
    member_counts = (
        select(SpaceMember.space_id, func.count(SpaceMember.id).label("member_count"))
        .where(SpaceMember.tenant_id == tenant_id)
        .group_by(SpaceMember.space_id)
        .subquery()
    )
    node_counts = (
        select(Node.space_id, func.count(Node.id).label("node_count"))
        .where(Node.tenant_id == tenant_id)
        .group_by(Node.space_id)
        .subquery()
    )
    conditions = [Space.tenant_id == tenant_id]
    if isinstance(filters.get("is_active"), bool):
        conditions.append(Space.is_active.is_(filters["is_active"]))
    if isinstance(filters.get("space_type"), str):
        conditions.append(Space.space_type == filters["space_type"])
    result = await session.execute(
        select(
            Space,
            func.coalesce(member_counts.c.member_count, 0),
            func.coalesce(node_counts.c.node_count, 0),
            func.coalesce(QuotaAccount.used_bytes, 0),
            func.coalesce(QuotaAccount.limit_bytes, 0),
        )
        .outerjoin(member_counts, member_counts.c.space_id == Space.id)
        .outerjoin(node_counts, node_counts.c.space_id == Space.id)
        .outerjoin(
            QuotaAccount,
            and_(
                QuotaAccount.tenant_id == Space.tenant_id,
                QuotaAccount.owner_type == "space",
                QuotaAccount.owner_id == Space.id,
            ),
        )
        .where(*conditions)
        .order_by(Space.created_at.desc(), Space.id.desc())
        .limit(max_rows + 1)
    )
    rows = result.all()
    _raise_if_export_too_large(resource="spaces", count=len(rows), max_rows=max_rows)
    return (
        [
            "id",
            "owner_id",
            "slug",
            "name",
            "space_type",
            "is_active",
            "version",
            "permission_version",
            "member_count",
            "node_count",
            "used_bytes",
            "limit_bytes",
            "created_at",
        ],
        [
            [
                space.id,
                space.owner_id,
                space.slug,
                space.name,
                space.space_type,
                space.is_active,
                space.version,
                space.permission_version,
                member_count,
                node_count,
                used_bytes,
                limit_bytes,
                space.created_at.isoformat(),
            ]
            for space, member_count, node_count, used_bytes, limit_bytes in rows
        ],
    )


async def _user_rows(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    filters: dict[str, object],
    max_rows: int,
) -> tuple[list[str], list[list[object]]]:
    conditions = [User.tenant_id == tenant_id]
    if isinstance(filters.get("is_active"), bool):
        conditions.append(User.is_active.is_(filters["is_active"]))
    if isinstance(filters.get("is_super_admin"), bool):
        conditions.append(User.is_super_admin.is_(filters["is_super_admin"]))
    result = await session.execute(
        select(User)
        .where(*conditions)
        .order_by(User.created_at.desc(), User.id.desc())
        .limit(max_rows + 1)
    )
    users = list(result.scalars().all())
    _raise_if_export_too_large(resource="users", count=len(users), max_rows=max_rows)
    return (
        [
            "id",
            "username",
            "email",
            "display_name",
            "is_active",
            "is_super_admin",
            "must_change_password",
            "version",
            "created_at",
        ],
        [
            [
                user.id,
                user.username,
                user.email,
                user.display_name,
                user.is_active,
                user.is_super_admin,
                user.must_change_password,
                user.version,
                user.created_at.isoformat(),
            ]
            for user in users
        ],
    )


def _filters(job: AdminJob) -> dict[str, object]:
    value = job.parameters_json.get("filters")
    return dict(value) if isinstance(value, dict) else {}


def _export_file_name(*, resource: str, job_id: UUID) -> str:
    return f"{resource}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{job_id}.csv"


def _raise_if_export_too_large(*, resource: str, count: int, max_rows: int) -> None:
    if count > max_rows:
        raise AdminExportRowLimitExceededError(
            f"{resource} export exceeds configured maximum rows: {max_rows}"
        )


def _safe_csv_cell(value: object) -> object:
    if not isinstance(value, str):
        return value
    candidate = value.lstrip(" \t\r\n")
    if candidate.startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def _audit_result_summary(result: dict[str, object]) -> dict[str, object]:
    summary: dict[str, object] = {}
    for key, value in result.items():
        if value is None or isinstance(value, (bool, int, float, str)):
            summary[key] = value
        elif isinstance(value, list):
            summary[f"{key}_count"] = len(value)
        elif isinstance(value, dict):
            summary[f"{key}_keys"] = sorted(str(item) for item in value)[:100]
    return summary


def _uuid_parameter(parameters: dict[str, object], name: str) -> UUID | None:
    value = parameters.get(name)
    return UUID(value) if isinstance(value, str) and value else None


def _str_parameter(parameters: dict[str, object], name: str) -> str | None:
    value = parameters.get(name)
    return value if isinstance(value, str) and value else None


def _int_parameter(parameters: dict[str, object], name: str, default: int) -> int:
    value = parameters.get(name)
    return value if isinstance(value, int) else default


def _optional_int_parameter(parameters: dict[str, object], name: str) -> int | None:
    value = parameters.get(name)
    return value if isinstance(value, int) else None


def _bool_parameter(parameters: dict[str, object], name: str, default: bool) -> bool:
    value = parameters.get(name)
    return value if isinstance(value, bool) else default


def _datetime_filter(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
