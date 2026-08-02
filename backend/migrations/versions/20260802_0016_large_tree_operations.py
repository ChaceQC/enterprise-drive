"""add resumable large tree operations

Revision ID: 20260802_0016
Revises: 20260801_0015
Create Date: 2026-08-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260802_0016"
down_revision = "20260801_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("nodes", sa.Column("deleted_root_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_nodes_deleted_root_id_nodes",
        "nodes",
        "nodes",
        ["deleted_root_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_nodes_deleted_root_id", "nodes", ["deleted_root_id"])
    op.create_index(
        "idx_nodes_tree_operation",
        "nodes",
        ["tenant_id", "deleted_root_id", "is_deleted", "id"],
    )

    op.create_table(
        "file_tree_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("target_parent_id", sa.Uuid(), nullable=True),
        sa.Column("target_name", sa.String(length=255), nullable=True),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("released_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_file_tree_operations_tenant_id",
        "file_tree_operations",
        ["tenant_id"],
    )
    op.create_index(
        "ix_file_tree_operations_user_id",
        "file_tree_operations",
        ["user_id"],
    )
    op.create_index(
        "ix_file_tree_operations_space_id",
        "file_tree_operations",
        ["space_id"],
    )
    op.create_index(
        "ix_file_tree_operations_node_id",
        "file_tree_operations",
        ["node_id"],
    )
    op.create_index(
        "idx_file_tree_operations_pending",
        "file_tree_operations",
        ["status", "created_at", "id"],
    )
    op.create_index(
        "uq_file_tree_operations_active_node",
        "file_tree_operations",
        ["tenant_id", "node_id"],
        unique=True,
        postgresql_where=sa.text("status in ('pending', 'running')"),
        sqlite_where=sa.text("status in ('pending', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_file_tree_operations_active_node",
        table_name="file_tree_operations",
    )
    op.drop_index("idx_file_tree_operations_pending", table_name="file_tree_operations")
    op.drop_index("ix_file_tree_operations_node_id", table_name="file_tree_operations")
    op.drop_index("ix_file_tree_operations_space_id", table_name="file_tree_operations")
    op.drop_index("ix_file_tree_operations_user_id", table_name="file_tree_operations")
    op.drop_index("ix_file_tree_operations_tenant_id", table_name="file_tree_operations")
    op.drop_table("file_tree_operations")

    op.drop_index("idx_nodes_tree_operation", table_name="nodes")
    op.drop_index("ix_nodes_deleted_root_id", table_name="nodes")
    op.drop_constraint("fk_nodes_deleted_root_id_nodes", "nodes", type_="foreignkey")
    op.drop_column("nodes", "deleted_root_id")
