"""add multidimensional quota policies

Revision ID: 20260801_0014
Revises: 20260731_0013
Create Date: 2026-08-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260801_0014"
down_revision = "20260731_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quota_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column("max_file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("extensions", sa.JSON(), nullable=False),
        sa.Column("mime_prefixes", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("limit_bytes >= 0", name="ck_quota_policies_limit_nonnegative"),
        sa.CheckConstraint(
            "max_file_size_bytes is null or max_file_size_bytes >= 0",
            name="ck_quota_policies_file_size_nonnegative",
        ),
    )
    op.create_index("ix_quota_policies_tenant_id", "quota_policies", ["tenant_id"])
    op.create_index(
        "idx_quota_policies_tenant_priority",
        "quota_policies",
        ["tenant_id", "is_active", "priority"],
    )


def downgrade() -> None:
    op.drop_index("idx_quota_policies_tenant_priority", table_name="quota_policies")
    op.drop_index("ix_quota_policies_tenant_id", table_name="quota_policies")
    op.drop_table("quota_policies")
