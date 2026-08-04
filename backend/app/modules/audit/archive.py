from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.storage.base import StorageAdapter
from app.modules.audit.models import AuditArchive, AuditLog
from app.modules.audit.signing import sign_content


class AuditArchiveRowLimitExceededError(ValueError):
    pass


async def archive_retained_audit_logs(
    *,
    session: AsyncSession,
    storage: StorageAdapter,
    bucket: str,
    retention_days: int,
    max_rows: int,
    delete_source: bool,
    signing_key: str,
    signing_key_id: str,
    tenant_id: UUID | None = None,
    reference_at: datetime | None = None,
) -> dict[str, object]:
    now = _as_utc(reference_at or datetime.now(UTC))
    cutoff = now - timedelta(days=retention_days)
    tenant_ids = await _eligible_tenant_ids(
        session=session,
        cutoff=cutoff,
        tenant_id=tenant_id,
    )
    archives_created = 0
    rows_archived = 0
    source_rows_deleted = 0
    skipped = 0
    for candidate_tenant_id in tenant_ids:
        archive_result = await _archive_next_month(
            session=session,
            storage=storage,
            bucket=bucket,
            tenant_id=candidate_tenant_id,
            cutoff=cutoff,
            max_rows=max_rows,
            delete_source=delete_source,
            signing_key=signing_key,
            signing_key_id=signing_key_id,
        )
        if archive_result is None:
            skipped += 1
            continue
        archives_created += 1
        rows_archived += archive_result["row_count"]
        source_rows_deleted += archive_result["source_rows_deleted"]
    return {
        "tenants_scanned": len(tenant_ids),
        "archives_created": archives_created,
        "rows_archived": rows_archived,
        "source_rows_deleted": source_rows_deleted,
        "skipped": skipped,
    }


async def _archive_next_month(
    *,
    session: AsyncSession,
    storage: StorageAdapter,
    bucket: str,
    tenant_id: UUID,
    cutoff: datetime,
    max_rows: int,
    delete_source: bool,
    signing_key: str,
    signing_key_id: str,
) -> dict[str, int] | None:
    earliest = (
        await session.execute(
            select(func.min(AuditLog.created_at)).where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.created_at < cutoff,
            )
        )
    ).scalar_one()
    if earliest is None:
        return None
    period_start = _month_start(_as_utc(earliest))
    period_end = _next_month(period_start)
    if period_end > cutoff:
        return None

    existing = (
        await session.execute(
            select(AuditArchive)
            .where(
                AuditArchive.tenant_id == tenant_id,
                AuditArchive.period_start == period_start,
                AuditArchive.period_end == period_end,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None and existing.status == "succeeded":
        return None
    archive = existing or AuditArchive(
        id=uuid4(),
        tenant_id=tenant_id,
        period_start=period_start,
        period_end=period_end,
    )
    if existing is None:
        session.add(archive)
    archive.status = "running"
    archive.delete_source = delete_source
    archive.error_code = None
    archive.error_message = None
    await session.flush()

    logs = list(
        (
            await session.execute(
                select(AuditLog)
                .where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.created_at >= period_start,
                    AuditLog.created_at < period_end,
                )
                .order_by(AuditLog.created_at, AuditLog.id)
                .limit(max_rows + 1)
            )
        )
        .scalars()
        .all()
    )
    if len(logs) > max_rows:
        archive.status = "failed"
        archive.error_code = "AUDIT_ARCHIVE_ROW_LIMIT_EXCEEDED"
        archive.error_message = f"archive month exceeds configured maximum rows: {max_rows}"
        archive.updated_at = datetime.now(UTC)
        await session.commit()
        raise AuditArchiveRowLimitExceededError(archive.error_message)
    if not logs:
        archive.status = "failed"
        archive.error_code = "AUDIT_ARCHIVE_EMPTY"
        archive.error_message = "no audit rows found for selected archive month"
        archive.updated_at = datetime.now(UTC)
        await session.commit()
        return None

    content = _audit_csv(logs)
    signature = sign_content(
        content=content,
        key=signing_key,
        key_id=signing_key_id,
        purpose="audit-archive",
    )
    file_name = f"audit-{period_start:%Y-%m}-{archive.id}.csv"
    storage_key = f"audit-archives/{tenant_id}/{period_start:%Y/%m}/{file_name}"
    try:
        await storage.put_object_bytes(
            bucket=bucket,
            storage_key=storage_key,
            content=content,
            content_type="text/csv; charset=utf-8",
        )
    except Exception as exc:
        archive.status = "failed"
        archive.error_code = "AUDIT_ARCHIVE_STORAGE_FAILED"
        archive.error_message = type(exc).__name__
        archive.updated_at = datetime.now(UTC)
        await session.commit()
        raise

    deleted_rows = 0
    if delete_source:
        delete_result = await session.execute(
            delete(AuditLog)
            .where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.created_at >= period_start,
                AuditLog.created_at < period_end,
            )
            .execution_options(synchronize_session=False)
        )
        deleted_rows = int(getattr(delete_result, "rowcount", 0) or 0)
        archive.source_deleted_at = datetime.now(UTC)

    archive.status = "succeeded"
    archive.row_count = len(logs)
    archive.storage_bucket = bucket
    archive.storage_key = storage_key
    archive.file_name = file_name
    archive.size_bytes = len(content)
    archive.content_sha256 = signature.content_sha256
    archive.signature_algorithm = signature.algorithm
    archive.signature_key_id = signature.key_id
    archive.signature_value = signature.value
    archive.updated_at = datetime.now(UTC)
    await session.commit()
    return {
        "row_count": len(logs),
        "source_rows_deleted": deleted_rows,
    }


async def _eligible_tenant_ids(
    *,
    session: AsyncSession,
    cutoff: datetime,
    tenant_id: UUID | None,
) -> list[UUID]:
    if tenant_id is not None:
        return [tenant_id]
    result = await session.execute(
        select(AuditLog.tenant_id)
        .where(AuditLog.created_at < cutoff)
        .distinct()
        .order_by(AuditLog.tenant_id)
    )
    return list(result.scalars().all())


def _audit_csv(logs: list[AuditLog]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "id",
            "tenant_id",
            "actor_id",
            "actor_type",
            "action",
            "resource_type",
            "resource_id",
            "result",
            "risk_level",
            "request_id",
            "ip",
            "user_agent",
            "metadata_json",
            "created_at",
        ]
    )
    for log in logs:
        writer.writerow(
            [
                log.id,
                log.tenant_id,
                log.actor_id,
                log.actor_type,
                log.action,
                log.resource_type,
                log.resource_id,
                log.result,
                log.risk_level,
                log.request_id,
                log.ip,
                log.user_agent,
                json.dumps(
                    log.metadata_json,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                log.created_at.isoformat(),
            ]
        )
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def _month_start(value: datetime) -> datetime:
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(value: datetime) -> datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1)
    return value.replace(month=value.month + 1)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
