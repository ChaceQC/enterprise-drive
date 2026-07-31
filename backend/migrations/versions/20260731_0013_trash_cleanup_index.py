"""add trash cleanup index

Revision ID: 20260731_0013
Revises: 20260701_0012
Create Date: 2026-07-31
"""

from __future__ import annotations

from alembic import op

revision = "20260731_0013"
down_revision = "20260701_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_nodes_trash_cleanup",
        "nodes",
        ["tenant_id", "is_deleted", "deleted_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("idx_nodes_trash_cleanup", table_name="nodes")
