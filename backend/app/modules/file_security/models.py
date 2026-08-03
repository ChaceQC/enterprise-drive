from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import utc_now
from app.db.base import Base


class FileSecurityPolicy(Base):
    __tablename__ = "file_security_policies"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    classification: Mapped[str] = mapped_column(String(32), nullable=False, default="internal")
    download_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="presigned")
    extensions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    mime_prefixes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    dlp_keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    dlp_action: Mapped[str] = mapped_column(String(16), nullable=False, default="audit")
    fail_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    watermark_text: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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

    __table_args__ = (
        Index("uq_file_security_policies_name", "tenant_id", func.lower(name), unique=True),
        Index(
            "idx_file_security_policies_match",
            "tenant_id",
            "is_active",
            "priority",
            "id",
        ),
    )
