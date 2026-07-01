"""add file version search extraction state

Revision ID: 20260701_0010
Revises: 20260701_0009
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260701_0010"
down_revision = "20260701_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "file_versions",
        sa.Column(
            "search_status",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "file_versions",
        sa.Column("search_error", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "file_versions",
        sa.Column("search_text", sa.Text(), nullable=True),
    )
    op.execute("update file_versions set search_status = 'pending' where search_status is null")
    op.alter_column("file_versions", "search_status", nullable=False)


def downgrade() -> None:
    op.drop_column("file_versions", "search_text")
    op.drop_column("file_versions", "search_error")
    op.drop_column("file_versions", "search_status")
