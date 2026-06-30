"""create permission base tables

Revision ID: 20260701_0006
Revises: 20260630_0005
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260701_0006"
down_revision = "20260630_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "space_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "role in ('owner', 'admin', 'editor', 'viewer')",
            name="ck_space_members_role",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_space_members_tenant_id", "space_members", ["tenant_id"])
    op.create_index("ix_space_members_space_id", "space_members", ["space_id"])
    op.create_index("ix_space_members_user_id", "space_members", ["user_id"])
    op.create_index(
        "uq_space_members_user",
        "space_members",
        ["tenant_id", "space_id", "user_id"],
        unique=True,
    )
    op.create_index(
        "idx_space_members_user",
        "space_members",
        ["tenant_id", "user_id", "role"],
    )
    op.create_index(
        "idx_space_members_space_role",
        "space_members",
        ["tenant_id", "space_id", "role"],
    )


def downgrade() -> None:
    op.drop_index("idx_space_members_space_role", table_name="space_members")
    op.drop_index("idx_space_members_user", table_name="space_members")
    op.drop_index("uq_space_members_user", table_name="space_members")
    op.drop_index("ix_space_members_user_id", table_name="space_members")
    op.drop_index("ix_space_members_space_id", table_name="space_members")
    op.drop_index("ix_space_members_tenant_id", table_name="space_members")
    op.drop_table("space_members")
