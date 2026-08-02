"""add persisted file batch idempotency records

Revision ID: 20260801_0015
Revises: 20260801_0014
Create Date: 2026-08-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260801_0015"
down_revision = "20260801_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_batch_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_file_batch_operations_tenant_id",
        "file_batch_operations",
        ["tenant_id"],
    )
    op.create_index(
        "ix_file_batch_operations_user_id",
        "file_batch_operations",
        ["user_id"],
    )
    op.create_index(
        "uq_file_batch_operations_key",
        "file_batch_operations",
        ["tenant_id", "user_id", "operation", "idempotency_key_hash"],
        unique=True,
    )
    op.create_index(
        "idx_file_batch_operations_created",
        "file_batch_operations",
        ["tenant_id", "user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_file_batch_operations_created", table_name="file_batch_operations")
    op.drop_index("uq_file_batch_operations_key", table_name="file_batch_operations")
    op.drop_index("ix_file_batch_operations_user_id", table_name="file_batch_operations")
    op.drop_index("ix_file_batch_operations_tenant_id", table_name="file_batch_operations")
    op.drop_table("file_batch_operations")
