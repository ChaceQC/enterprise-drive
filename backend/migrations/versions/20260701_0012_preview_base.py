"""create preview base tables

Revision ID: 20260701_0012
Revises: 20260701_0011
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260701_0012"
down_revision = "20260701_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "file_versions",
        sa.Column("preview_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "file_versions",
        sa.Column("preview_error", sa.String(length=255), nullable=True),
    )
    op.execute("update file_versions set preview_status = 'pending' where preview_status is null")
    op.alter_column("file_versions", "preview_status", nullable=False)

    op.create_table(
        "preview_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_type", sa.String(length=32), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["file_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_preview_artifacts_tenant_id", "preview_artifacts", ["tenant_id"])
    op.create_index("ix_preview_artifacts_node_id", "preview_artifacts", ["node_id"])
    op.create_index("ix_preview_artifacts_version_id", "preview_artifacts", ["version_id"])
    op.create_index(
        "uq_preview_artifacts_kind",
        "preview_artifacts",
        ["tenant_id", "version_id", "artifact_type"],
        unique=True,
    )
    op.create_index(
        "idx_preview_artifacts_node",
        "preview_artifacts",
        ["tenant_id", "node_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_preview_artifacts_node", table_name="preview_artifacts")
    op.drop_index("uq_preview_artifacts_kind", table_name="preview_artifacts")
    op.drop_index("ix_preview_artifacts_version_id", table_name="preview_artifacts")
    op.drop_index("ix_preview_artifacts_node_id", table_name="preview_artifacts")
    op.drop_index("ix_preview_artifacts_tenant_id", table_name="preview_artifacts")
    op.drop_table("preview_artifacts")
    op.drop_column("file_versions", "preview_error")
    op.drop_column("file_versions", "preview_status")
