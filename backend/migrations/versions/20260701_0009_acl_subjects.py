"""extend acl subject types

Revision ID: 20260701_0009
Revises: 20260701_0008
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260701_0009"
down_revision = "20260701_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_acl_entries_subject_type", "acl_entries", type_="check")
    op.create_check_constraint(
        "ck_acl_entries_subject_type",
        "acl_entries",
        sa.text("subject_type in ('user', 'department', 'group')"),
    )


def downgrade() -> None:
    op.drop_constraint("ck_acl_entries_subject_type", "acl_entries", type_="check")
    op.create_check_constraint(
        "ck_acl_entries_subject_type",
        "acl_entries",
        sa.text("subject_type in ('user')"),
    )
