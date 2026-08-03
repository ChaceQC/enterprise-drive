"""add tenant-scoped quota policy name uniqueness

Revision ID: 20260803_0017
Revises: 20260802_0016
Create Date: 2026-08-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260803_0017"
down_revision: str | None = "20260802_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "create unique index uq_quota_policies_name on quota_policies(tenant_id, lower(name))"
    )


def downgrade() -> None:
    op.drop_index("uq_quota_policies_name", table_name="quota_policies")
