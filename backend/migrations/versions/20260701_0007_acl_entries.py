"""create acl entries table

Revision ID: 20260701_0007
Revises: 20260701_0006
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260701_0007"
down_revision = "20260701_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "acl_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("effect", sa.String(length=16), nullable=False),
        sa.Column("actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("inherit", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.CheckConstraint("subject_type in ('user')", name="ck_acl_entries_subject_type"),
        sa.CheckConstraint("effect in ('allow', 'deny')", name="ck_acl_entries_effect"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_acl_entries_tenant_id", "acl_entries", ["tenant_id"])
    op.create_index("ix_acl_entries_node_id", "acl_entries", ["node_id"])
    op.create_index(
        "uq_acl_entries_subject_effect",
        "acl_entries",
        ["tenant_id", "node_id", "subject_type", "subject_id", "effect"],
        unique=True,
    )
    op.create_index(
        "idx_acl_entries_node_subject",
        "acl_entries",
        ["tenant_id", "node_id", "subject_type", "subject_id"],
    )
    op.create_index(
        "idx_acl_entries_subject",
        "acl_entries",
        ["tenant_id", "subject_type", "subject_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_acl_entries_subject", table_name="acl_entries")
    op.drop_index("idx_acl_entries_node_subject", table_name="acl_entries")
    op.drop_index("uq_acl_entries_subject_effect", table_name="acl_entries")
    op.drop_index("ix_acl_entries_node_id", table_name="acl_entries")
    op.drop_index("ix_acl_entries_tenant_id", table_name="acl_entries")
    op.drop_table("acl_entries")
