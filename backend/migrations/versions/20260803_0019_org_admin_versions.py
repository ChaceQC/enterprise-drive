"""add optimistic versions for organization administration

Revision ID: 20260803_0019
Revises: 20260803_0018
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0019"
down_revision: str | None = "20260803_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table_name in ("users", "departments", "user_groups"):
        op.add_column(
            table_name,
            sa.Column("version", sa.Integer(), nullable=True),
        )
        op.execute(sa.text(f"update {table_name} set version = 1 where version is null"))
        op.alter_column(
            table_name,
            "version",
            existing_type=sa.Integer(),
            nullable=False,
        )

    op.create_index(
        "idx_users_admin_list",
        "users",
        ["tenant_id", "created_at", "id"],
    )
    op.create_index(
        "idx_departments_admin_list",
        "departments",
        ["tenant_id", "created_at", "id"],
    )
    op.create_index(
        "idx_user_groups_admin_list",
        "user_groups",
        ["tenant_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("idx_user_groups_admin_list", table_name="user_groups")
    op.drop_index("idx_departments_admin_list", table_name="departments")
    op.drop_index("idx_users_admin_list", table_name="users")

    for table_name in ("user_groups", "departments", "users"):
        op.drop_column(table_name, "version")
