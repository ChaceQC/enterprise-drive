from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    and_,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import utc_now
from app.db.base import Base


class FileBlob(Base):
    __tablename__ = "file_blobs"
    __table_args__ = (
        Index("idx_file_blobs_cleanup", "tenant_id", "status", "ref_count", "created_at"),
        Index(
            "uq_file_blobs_hash",
            "tenant_id",
            "hash_algo",
            "content_hash",
            "size_bytes",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hash_algo: Mapped[str] = mapped_column(String(16), nullable=False, default="sha256")
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ref_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    space_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("nodes.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    node_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    permission_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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
        Index(
            "uq_nodes_sibling_name",
            "tenant_id",
            "space_id",
            "parent_id",
            func.lower(normalized_name),
            unique=True,
            postgresql_where=and_(is_deleted.is_(False), parent_id.is_not(None)),
            sqlite_where=and_(is_deleted.is_(False), parent_id.is_not(None)),
        ),
        Index(
            "uq_nodes_space_root",
            "tenant_id",
            "space_id",
            unique=True,
            postgresql_where=and_(is_deleted.is_(False), parent_id.is_(None)),
            sqlite_where=and_(is_deleted.is_(False), parent_id.is_(None)),
        ),
        Index("idx_nodes_list", "tenant_id", "space_id", "parent_id", "is_deleted"),
        Index("idx_nodes_updated", "tenant_id", "space_id", "updated_at"),
        Index("idx_nodes_trash_cleanup", "tenant_id", "is_deleted", "deleted_at", "id"),
    )


class FileVersion(Base):
    __tablename__ = "file_versions"
    __table_args__ = (
        Index("uq_file_versions_no", "tenant_id", "node_id", "version_no", unique=True),
        Index("idx_file_versions_created", "tenant_id", "node_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    blob_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("file_blobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preview_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    preview_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    search_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    search_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    search_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
