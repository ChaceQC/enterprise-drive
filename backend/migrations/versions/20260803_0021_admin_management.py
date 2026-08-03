"""add Sprint 6 administration jobs and space versions

Revision ID: 20260803_0021
Revises: 20260803_0020
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260803_0021"
down_revision: str | None = "20260803_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("spaces", sa.Column("version", sa.Integer(), nullable=True))
    op.execute(sa.text("update spaces set version = 1 where version is null"))
    op.alter_column(
        "spaces",
        "version",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_index(
        "idx_spaces_admin_list",
        "spaces",
        ["tenant_id", "created_at", "id"],
    )

    op.create_table(
        "admin_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "parameters_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
        sa.Column("storage_bucket", sa.String(length=128), nullable=True),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
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
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_jobs_tenant_id", "admin_jobs", ["tenant_id"])
    op.create_index("ix_admin_jobs_created_by", "admin_jobs", ["created_by"])
    op.create_index(
        "idx_admin_jobs_tenant_kind_created",
        "admin_jobs",
        ["tenant_id", "kind", "created_at", "id"],
    )
    op.create_index(
        "idx_admin_jobs_status",
        "admin_jobs",
        ["kind", "status", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("idx_admin_jobs_status", table_name="admin_jobs")
    op.drop_index("idx_admin_jobs_tenant_kind_created", table_name="admin_jobs")
    op.drop_index("ix_admin_jobs_created_by", table_name="admin_jobs")
    op.drop_index("ix_admin_jobs_tenant_id", table_name="admin_jobs")
    op.drop_table("admin_jobs")

    op.drop_index("idx_spaces_admin_list", table_name="spaces")
    op.drop_column("spaces", "version")
