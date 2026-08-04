from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def ensure_audit_partitions(
    *,
    session: AsyncSession,
    months_ahead: int,
    reference_at: datetime | None = None,
) -> dict[str, object]:
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return {"supported": False, "created": 0, "partitions": []}

    reference = _as_utc(reference_at or datetime.now(UTC))
    current_start = _month_start(reference)
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('audit.ensure_partitions'))"))
    created: list[str] = []
    for offset in range(months_ahead + 1):
        partition_start = _add_months(current_start, offset)
        partition_end = _add_months(current_start, offset + 1)
        partition_name = f"audit_logs_{partition_start:%Y%m}"
        existed = bool(
            (
                await session.execute(
                    text("SELECT to_regclass(:partition_name) IS NOT NULL"),
                    {"partition_name": partition_name},
                )
            ).scalar_one()
        )
        await session.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {partition_name} "
                "PARTITION OF audit_logs "
                f"FOR VALUES FROM ('{partition_start.isoformat()}') "
                f"TO ('{partition_end.isoformat()}')"
            )
        )
        if not existed:
            created.append(partition_name)
    await session.flush()
    return {
        "supported": True,
        "created": len(created),
        "partitions": created,
    }


def _month_start(value: datetime) -> datetime:
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _add_months(value: datetime, months: int) -> datetime:
    month_index = (value.month - 1) + months
    year = value.year + (month_index // 12)
    month = (month_index % 12) + 1
    return value.replace(year=year, month=month, day=1)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
