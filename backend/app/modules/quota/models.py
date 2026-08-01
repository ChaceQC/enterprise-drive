from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import utc_now
from app.db.base import Base


class QuotaAccount(Base):
    __tablename__ = "quota_accounts"
    __table_args__ = (
        Index("uq_quota_accounts_owner", "tenant_id", "owner_type", "owner_id", unique=True),
        Index("idx_quota_accounts_owner", "tenant_id", "owner_type", "owner_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_type: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    limit_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class QuotaLedger(Base):
    __tablename__ = "quota_ledger"
    __table_args__ = (
        Index("idx_quota_ledger_account", "tenant_id", "account_id", "created_at"),
        Index("idx_quota_ledger_ref", "tenant_id", "ref_type", "ref_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("quota_accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    account_type: Mapped[str] = mapped_column(String(32), nullable=False)
    delta_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(64), nullable=False)
    ref_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class QuotaPolicy(Base):
    """按文件名后缀或 MIME 前缀选择的策略配额。"""

    __tablename__ = "quota_policies"
    __table_args__ = (
        Index("idx_quota_policies_tenant_priority", "tenant_id", "is_active", "priority"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    limit_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    extensions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    mime_prefixes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
