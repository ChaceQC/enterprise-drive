from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.security import utc_now
from app.db.base import Base
from app.modules.permission.constants import ACL_EFFECT_ALLOW, SPACE_ROLE_VIEWER


class SpaceMember(Base):
    __tablename__ = "space_members"
    __table_args__ = (
        CheckConstraint(
            "role in ('owner', 'admin', 'editor', 'viewer')",
            name="ck_space_members_role",
        ),
        Index("uq_space_members_user", "tenant_id", "space_id", "user_id", unique=True),
        Index("idx_space_members_user", "tenant_id", "user_id", "role"),
        Index("idx_space_members_space_role", "tenant_id", "space_id", "role"),
    )

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
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=SPACE_ROLE_VIEWER)
    created_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
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


class AclEntry(Base):
    __tablename__ = "acl_entries"
    __table_args__ = (
        CheckConstraint(
            "subject_type in ('user', 'department', 'group')",
            name="ck_acl_entries_subject_type",
        ),
        CheckConstraint("effect in ('allow', 'deny')", name="ck_acl_entries_effect"),
        Index(
            "uq_acl_entries_subject_effect",
            "tenant_id",
            "node_id",
            "subject_type",
            "subject_id",
            "effect",
            unique=True,
        ),
        Index("idx_acl_entries_node_subject", "tenant_id", "node_id", "subject_type", "subject_id"),
        Index("idx_acl_entries_subject", "tenant_id", "subject_type", "subject_id"),
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
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    effect: Mapped[str] = mapped_column(String(16), nullable=False, default=ACL_EFFECT_ALLOW)
    actions: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
    )
    inherit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
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
