"""create share base tables

Revision ID: 20260701_0011
Revises: 20260701_0010
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260701_0011"
down_revision = "20260701_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shares",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("share_type", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=True),
        sa.Column("passcode_hash", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("root_node_id", sa.Uuid(), nullable=False),
        sa.Column("permission", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_views", sa.Integer(), nullable=True),
        sa.Column("max_downloads", sa.Integer(), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("download_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint("share_type in ('internal', 'external')", name="ck_shares_type"),
        sa.CheckConstraint(
            "permission in ('preview', 'download')",
            name="ck_shares_permission",
        ),
        sa.CheckConstraint(
            "status in ('active', 'expired', 'revoked', 'disabled')",
            name="ck_shares_status",
        ),
        sa.CheckConstraint("max_views is null or max_views > 0", name="ck_shares_max_views"),
        sa.CheckConstraint(
            "max_downloads is null or max_downloads > 0",
            name="ck_shares_max_downloads",
        ),
        sa.CheckConstraint(
            "(share_type = 'external' and token_hash is not null) "
            "or (share_type = 'internal' and token_hash is null)",
            name="ck_shares_token_by_type",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["root_node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shares_tenant_id", "shares", ["tenant_id"])
    op.create_index("ix_shares_created_by", "shares", ["created_by"])
    op.create_index("ix_shares_root_node_id", "shares", ["root_node_id"])
    op.create_index("idx_shares_creator", "shares", ["tenant_id", "created_by", "created_at"])
    op.create_index("idx_shares_status", "shares", ["tenant_id", "status", "expires_at"])
    op.create_index(
        "idx_shares_external_token_hash",
        "shares",
        ["token_hash"],
        unique=True,
        postgresql_where=sa.text("share_type = 'external' and token_hash is not null"),
    )

    op.create_table(
        "share_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("share_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["share_id"], ["shares.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_share_items_tenant_id", "share_items", ["tenant_id"])
    op.create_index("ix_share_items_share_id", "share_items", ["share_id"])
    op.create_index("ix_share_items_node_id", "share_items", ["node_id"])
    op.create_index(
        "uq_share_items_node",
        "share_items",
        ["tenant_id", "share_id", "node_id"],
        unique=True,
    )
    op.create_index("idx_share_items_share", "share_items", ["tenant_id", "share_id"])

    op.create_table(
        "share_recipients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("share_id", sa.Uuid(), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "subject_type in ('user', 'department', 'group')",
            name="ck_share_recipients_subject_type",
        ),
        sa.ForeignKeyConstraint(["share_id"], ["shares.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_share_recipients_tenant_id", "share_recipients", ["tenant_id"])
    op.create_index("ix_share_recipients_share_id", "share_recipients", ["share_id"])
    op.create_index(
        "uq_share_recipients_subject",
        "share_recipients",
        ["tenant_id", "share_id", "subject_type", "subject_id"],
        unique=True,
    )
    op.create_index(
        "idx_share_recipients_subject",
        "share_recipients",
        ["tenant_id", "subject_type", "subject_id"],
    )

    op.create_table(
        "share_access_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("share_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("bytes_sent", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["share_id"], ["shares.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_share_access_logs_tenant_id", "share_access_logs", ["tenant_id"])
    op.create_index("ix_share_access_logs_share_id", "share_access_logs", ["share_id"])
    op.create_index("ix_share_access_logs_actor_id", "share_access_logs", ["actor_id"])
    op.create_index(
        "idx_share_access_logs_share",
        "share_access_logs",
        ["tenant_id", "share_id", "created_at"],
    )
    op.create_index(
        "idx_share_access_logs_actor",
        "share_access_logs",
        ["tenant_id", "actor_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_share_access_logs_actor", table_name="share_access_logs")
    op.drop_index("idx_share_access_logs_share", table_name="share_access_logs")
    op.drop_index("ix_share_access_logs_actor_id", table_name="share_access_logs")
    op.drop_index("ix_share_access_logs_share_id", table_name="share_access_logs")
    op.drop_index("ix_share_access_logs_tenant_id", table_name="share_access_logs")
    op.drop_table("share_access_logs")

    op.drop_index("idx_share_recipients_subject", table_name="share_recipients")
    op.drop_index("uq_share_recipients_subject", table_name="share_recipients")
    op.drop_index("ix_share_recipients_share_id", table_name="share_recipients")
    op.drop_index("ix_share_recipients_tenant_id", table_name="share_recipients")
    op.drop_table("share_recipients")

    op.drop_index("idx_share_items_share", table_name="share_items")
    op.drop_index("uq_share_items_node", table_name="share_items")
    op.drop_index("ix_share_items_node_id", table_name="share_items")
    op.drop_index("ix_share_items_share_id", table_name="share_items")
    op.drop_index("ix_share_items_tenant_id", table_name="share_items")
    op.drop_table("share_items")

    op.drop_index("idx_shares_external_token_hash", table_name="shares")
    op.drop_index("idx_shares_status", table_name="shares")
    op.drop_index("idx_shares_creator", table_name="shares")
    op.drop_index("ix_shares_root_node_id", table_name="shares")
    op.drop_index("ix_shares_created_by", table_name="shares")
    op.drop_index("ix_shares_tenant_id", table_name="shares")
    op.drop_table("shares")
