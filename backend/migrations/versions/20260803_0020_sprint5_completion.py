"""complete Sprint 5 share recipients and preview lifecycle

Revision ID: 20260803_0020
Revises: 20260803_0019
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0020"
down_revision: str | None = "20260803_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "share_recipient_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("share_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["share_id"], ["shares.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_share_recipient_grants_tenant_id",
        "share_recipient_grants",
        ["tenant_id"],
    )
    op.create_index(
        "ix_share_recipient_grants_share_id",
        "share_recipient_grants",
        ["share_id"],
    )
    op.create_index(
        "ix_share_recipient_grants_user_id",
        "share_recipient_grants",
        ["user_id"],
    )
    op.create_index(
        "uq_share_recipient_grants_user",
        "share_recipient_grants",
        ["tenant_id", "share_id", "user_id"],
        unique=True,
    )
    op.create_index(
        "idx_share_recipient_grants_user_active",
        "share_recipient_grants",
        ["tenant_id", "user_id", "is_active", "created_at", "id"],
    )
    op.create_index(
        "idx_share_recipient_grants_share_active",
        "share_recipient_grants",
        ["tenant_id", "share_id", "is_active"],
    )

    op.create_table(
        "share_notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("share_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("notification_type", sa.String(length=32), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["share_id"], ["shares.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_share_notifications_tenant_id",
        "share_notifications",
        ["tenant_id"],
    )
    op.create_index(
        "ix_share_notifications_share_id",
        "share_notifications",
        ["share_id"],
    )
    op.create_index(
        "ix_share_notifications_user_id",
        "share_notifications",
        ["user_id"],
    )
    op.create_index(
        "uq_share_notifications_kind",
        "share_notifications",
        ["tenant_id", "share_id", "user_id", "notification_type"],
        unique=True,
    )
    op.create_index(
        "idx_share_notifications_user",
        "share_notifications",
        ["tenant_id", "user_id", "created_at", "id"],
    )
    op.create_index(
        "idx_share_notifications_unread",
        "share_notifications",
        ["tenant_id", "user_id", "is_read", "invalidated_at", "created_at", "id"],
    )

    op.add_column(
        "preview_artifacts",
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            "update preview_artifacts "
            "set last_accessed_at = created_at "
            "where last_accessed_at is null"
        )
    )
    op.alter_column(
        "preview_artifacts",
        "last_accessed_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.create_index(
        "idx_preview_artifacts_lifecycle",
        "preview_artifacts",
        ["tenant_id", "last_accessed_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("idx_preview_artifacts_lifecycle", table_name="preview_artifacts")
    op.drop_column("preview_artifacts", "last_accessed_at")

    op.drop_index("idx_share_notifications_unread", table_name="share_notifications")
    op.drop_index("idx_share_notifications_user", table_name="share_notifications")
    op.drop_index("uq_share_notifications_kind", table_name="share_notifications")
    op.drop_index("ix_share_notifications_user_id", table_name="share_notifications")
    op.drop_index("ix_share_notifications_share_id", table_name="share_notifications")
    op.drop_index("ix_share_notifications_tenant_id", table_name="share_notifications")
    op.drop_table("share_notifications")

    op.drop_index(
        "idx_share_recipient_grants_share_active",
        table_name="share_recipient_grants",
    )
    op.drop_index(
        "idx_share_recipient_grants_user_active",
        table_name="share_recipient_grants",
    )
    op.drop_index(
        "uq_share_recipient_grants_user",
        table_name="share_recipient_grants",
    )
    op.drop_index("ix_share_recipient_grants_user_id", table_name="share_recipient_grants")
    op.drop_index("ix_share_recipient_grants_share_id", table_name="share_recipient_grants")
    op.drop_index("ix_share_recipient_grants_tenant_id", table_name="share_recipient_grants")
    op.drop_table("share_recipient_grants")
