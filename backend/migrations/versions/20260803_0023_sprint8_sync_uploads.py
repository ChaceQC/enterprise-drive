"""add Sprint 8 version-targeted upload sessions

Revision ID: 20260803_0023
Revises: 20260803_0022
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0023"
down_revision: str | None = "20260803_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "upload_sessions",
        sa.Column("target_node_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "upload_sessions",
        sa.Column("expected_current_version_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_upload_sessions_target_node_id_nodes",
        "upload_sessions",
        "nodes",
        ["target_node_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_upload_sessions_expected_version_file_versions",
        "upload_sessions",
        "file_versions",
        ["expected_current_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_upload_sessions_target_node_id",
        "upload_sessions",
        ["target_node_id"],
    )
    op.create_check_constraint(
        "ck_upload_sessions_version_target_pair",
        "upload_sessions",
        (
            "(target_node_id is null and expected_current_version_id is null) "
            "or (target_node_id is not null and expected_current_version_id is not null)"
        ),
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_upload_sessions_version_target_pair",
        "upload_sessions",
        type_="check",
    )
    op.drop_index("ix_upload_sessions_target_node_id", table_name="upload_sessions")
    op.drop_constraint(
        "fk_upload_sessions_expected_version_file_versions",
        "upload_sessions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_upload_sessions_target_node_id_nodes",
        "upload_sessions",
        type_="foreignkey",
    )
    op.drop_column("upload_sessions", "expected_current_version_id")
    op.drop_column("upload_sessions", "target_node_id")
