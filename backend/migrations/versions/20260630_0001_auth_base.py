"""create auth base tables

Revision ID: 20260630_0001
Revises:
Create Date: 2026-06-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260630_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("permission_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_super_admin", sa.Boolean(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.execute("create unique index uq_users_username on users(tenant_id, lower(username))")
    op.execute(
        "create unique index uq_users_email on users(tenant_id, lower(email)) "
        "where email is not null"
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column("replaced_by_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=64), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_sessions_tenant_id", "auth_sessions", ["tenant_id"])
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index(
        "idx_auth_sessions_family",
        "auth_sessions",
        ["tenant_id", "family_id"],
    )
    op.create_index(
        "uq_auth_sessions_token_hash",
        "auth_sessions",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_index("idx_auth_sessions_family", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_tenant_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.execute("drop index uq_users_email")
    op.execute("drop index uq_users_username")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_table("users")
    op.drop_table("tenants")
