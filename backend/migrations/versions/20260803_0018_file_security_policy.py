"""create file security policy table

Revision ID: 20260803_0018
Revises: 20260803_0017
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0018"
down_revision: str | None = "20260803_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "file_security_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("download_mode", sa.String(length=32), nullable=False),
        sa.Column("extensions", sa.JSON(), nullable=False),
        sa.Column("mime_prefixes", sa.JSON(), nullable=False),
        sa.Column("dlp_keywords", sa.JSON(), nullable=False),
        sa.Column("dlp_action", sa.String(length=16), nullable=False),
        sa.Column("fail_closed", sa.Boolean(), nullable=False),
        sa.Column("watermark_text", sa.String(length=256), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_file_security_policies_tenant_id",
        "file_security_policies",
        ["tenant_id"],
    )
    op.execute(
        "create unique index uq_file_security_policies_name "
        "on file_security_policies(tenant_id, lower(name))"
    )
    op.create_index(
        "idx_file_security_policies_match",
        "file_security_policies",
        ["tenant_id", "is_active", "priority", "id"],
    )


def downgrade() -> None:
    op.drop_index("idx_file_security_policies_match", table_name="file_security_policies")
    op.drop_index("uq_file_security_policies_name", table_name="file_security_policies")
    op.drop_index("ix_file_security_policies_tenant_id", table_name="file_security_policies")
    op.drop_table("file_security_policies")
