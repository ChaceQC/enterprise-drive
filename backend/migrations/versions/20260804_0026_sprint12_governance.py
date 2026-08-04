"""add Sprint 12 lifecycle and permission rebuild governance

Revision ID: 20260804_0026
Revises: 20260804_0025
Create Date: 2026-08-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260804_0026"
down_revision = "20260804_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lifecycle_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "trash_retention_days",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
        sa.Column(
            "preview_retention_days",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
        sa.Column(
            "expire_uploads",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "expire_shares",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "cleanup_unreferenced_blobs",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "cleanup_orphaned_objects",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lifecycle_policies_tenant_id",
        "lifecycle_policies",
        ["tenant_id"],
    )
    op.create_index(
        "uq_lifecycle_policies_tenant",
        "lifecycle_policies",
        ["tenant_id"],
        unique=True,
    )
    op.create_index(
        "idx_lifecycle_policies_updated",
        "lifecycle_policies",
        ["updated_at", "id"],
    )

    op.create_table(
        "permission_rebuild_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("root_node_id", sa.Uuid(), nullable=True),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("scope_key", sa.String(length=96), nullable=False),
        sa.Column("permission_version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "snapshot_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("cursor_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cursor_node_id", sa.Uuid(), nullable=True),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indexed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "restart_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["root_node_id"],
            ["nodes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_permission_rebuild_operations_tenant_id",
        "permission_rebuild_operations",
        ["tenant_id"],
    )
    op.create_index(
        "ix_permission_rebuild_operations_space_id",
        "permission_rebuild_operations",
        ["space_id"],
    )
    op.create_index(
        "ix_permission_rebuild_operations_root_node_id",
        "permission_rebuild_operations",
        ["root_node_id"],
    )
    op.create_index(
        "idx_permission_rebuild_pending",
        "permission_rebuild_operations",
        ["status", "created_at", "id"],
    )
    op.create_index(
        "idx_permission_rebuild_tenant_created",
        "permission_rebuild_operations",
        ["tenant_id", "created_at", "id"],
    )
    op.create_index(
        "uq_permission_rebuild_active_scope",
        "permission_rebuild_operations",
        ["tenant_id", "scope_key"],
        unique=True,
        postgresql_where=sa.text("status in ('pending', 'running')"),
        sqlite_where=sa.text("status in ('pending', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_permission_rebuild_active_scope",
        table_name="permission_rebuild_operations",
    )
    op.drop_index(
        "idx_permission_rebuild_tenant_created",
        table_name="permission_rebuild_operations",
    )
    op.drop_index(
        "idx_permission_rebuild_pending",
        table_name="permission_rebuild_operations",
    )
    op.drop_index(
        "ix_permission_rebuild_operations_root_node_id",
        table_name="permission_rebuild_operations",
    )
    op.drop_index(
        "ix_permission_rebuild_operations_space_id",
        table_name="permission_rebuild_operations",
    )
    op.drop_index(
        "ix_permission_rebuild_operations_tenant_id",
        table_name="permission_rebuild_operations",
    )
    op.drop_table("permission_rebuild_operations")

    op.drop_index(
        "idx_lifecycle_policies_updated",
        table_name="lifecycle_policies",
    )
    op.drop_index(
        "uq_lifecycle_policies_tenant",
        table_name="lifecycle_policies",
    )
    op.drop_index(
        "ix_lifecycle_policies_tenant_id",
        table_name="lifecycle_policies",
    )
    op.drop_table("lifecycle_policies")
