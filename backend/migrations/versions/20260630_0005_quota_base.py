"""create quota account and ledger tables

Revision ID: 20260630_0005
Revises: 20260630_0004
Create Date: 2026-06-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260630_0005"
down_revision = "20260630_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quota_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_type", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column("used_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quota_accounts_tenant_id", "quota_accounts", ["tenant_id"])
    op.create_index(
        "idx_quota_accounts_owner",
        "quota_accounts",
        ["tenant_id", "owner_type", "owner_id"],
    )
    op.create_index(
        "uq_quota_accounts_owner",
        "quota_accounts",
        ["tenant_id", "owner_type", "owner_id"],
        unique=True,
    )

    op.create_table(
        "quota_ledger",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("account_type", sa.String(length=32), nullable=False),
        sa.Column("delta_bytes", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("ref_type", sa.String(length=64), nullable=False),
        sa.Column("ref_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["account_id"], ["quota_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quota_ledger_tenant_id", "quota_ledger", ["tenant_id"])
    op.create_index("ix_quota_ledger_account_id", "quota_ledger", ["account_id"])
    op.create_index(
        "idx_quota_ledger_account",
        "quota_ledger",
        ["tenant_id", "account_id", "created_at"],
    )
    op.create_index(
        "idx_quota_ledger_ref",
        "quota_ledger",
        ["tenant_id", "ref_type", "ref_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_quota_ledger_ref", table_name="quota_ledger")
    op.drop_index("idx_quota_ledger_account", table_name="quota_ledger")
    op.drop_index("ix_quota_ledger_account_id", table_name="quota_ledger")
    op.drop_index("ix_quota_ledger_tenant_id", table_name="quota_ledger")
    op.drop_table("quota_ledger")
    op.drop_index("uq_quota_accounts_owner", table_name="quota_accounts")
    op.drop_index("idx_quota_accounts_owner", table_name="quota_accounts")
    op.drop_index("ix_quota_accounts_tenant_id", table_name="quota_accounts")
    op.drop_table("quota_accounts")
