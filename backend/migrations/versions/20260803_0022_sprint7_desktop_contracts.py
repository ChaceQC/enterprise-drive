"""add Sprint 7 device sessions and incremental sync contracts

Revision ID: 20260803_0022
Revises: 20260803_0021
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260803_0022"
down_revision: str | None = "20260803_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "desktop_devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("installation_id_hash", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("client_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=64), nullable=True),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_desktop_devices_tenant_id", "desktop_devices", ["tenant_id"])
    op.create_index("ix_desktop_devices_user_id", "desktop_devices", ["user_id"])
    op.create_index(
        "uq_desktop_devices_installation",
        "desktop_devices",
        ["tenant_id", "user_id", "installation_id_hash"],
        unique=True,
    )
    op.create_index(
        "idx_desktop_devices_user_created",
        "desktop_devices",
        ["tenant_id", "user_id", "created_at", "id"],
    )

    op.create_table(
        "device_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("replaced_by_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=64), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["desktop_devices.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_device_sessions_tenant_id", "device_sessions", ["tenant_id"])
    op.create_index("ix_device_sessions_user_id", "device_sessions", ["user_id"])
    op.create_index("ix_device_sessions_device_id", "device_sessions", ["device_id"])
    op.create_index(
        "uq_device_sessions_token_hash",
        "device_sessions",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "idx_device_sessions_family",
        "device_sessions",
        ["tenant_id", "family_id"],
    )
    op.create_index(
        "idx_device_sessions_device_active",
        "device_sessions",
        ["tenant_id", "device_id", "revoked_at", "expires_at"],
    )

    op.create_table(
        "client_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column(
            "response_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_client_operations_tenant_id", "client_operations", ["tenant_id"])
    op.create_index("ix_client_operations_user_id", "client_operations", ["user_id"])
    op.create_index(
        "uq_client_operations_key",
        "client_operations",
        ["tenant_id", "user_id", "operation_id"],
        unique=True,
    )
    op.create_index(
        "idx_client_operations_created",
        "client_operations",
        ["tenant_id", "user_id", "created_at"],
    )

    op.create_table(
        "sync_changes",
        sa.Column("sequence", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=True),
        sa.Column("node_id", sa.Uuid(), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("change_type", sa.String(length=32), nullable=False),
        sa.Column("node_type", sa.String(length=16), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("permission_version", sa.Integer(), nullable=True),
        sa.Column("tombstone", sa.Boolean(), nullable=False),
        sa.Column(
            "scope_node_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("client_operation_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("sequence"),
    )
    op.create_index("ix_sync_changes_tenant_id", "sync_changes", ["tenant_id"])
    op.create_index(
        "idx_sync_changes_tenant_space_sequence",
        "sync_changes",
        ["tenant_id", "space_id", "sequence"],
    )
    op.create_index(
        "idx_sync_changes_tenant_sequence",
        "sync_changes",
        ["tenant_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_index("idx_sync_changes_tenant_sequence", table_name="sync_changes")
    op.drop_index("idx_sync_changes_tenant_space_sequence", table_name="sync_changes")
    op.drop_index("ix_sync_changes_tenant_id", table_name="sync_changes")
    op.drop_table("sync_changes")

    op.drop_index("idx_client_operations_created", table_name="client_operations")
    op.drop_index("uq_client_operations_key", table_name="client_operations")
    op.drop_index("ix_client_operations_user_id", table_name="client_operations")
    op.drop_index("ix_client_operations_tenant_id", table_name="client_operations")
    op.drop_table("client_operations")

    op.drop_index("idx_device_sessions_device_active", table_name="device_sessions")
    op.drop_index("idx_device_sessions_family", table_name="device_sessions")
    op.drop_index("uq_device_sessions_token_hash", table_name="device_sessions")
    op.drop_index("ix_device_sessions_device_id", table_name="device_sessions")
    op.drop_index("ix_device_sessions_user_id", table_name="device_sessions")
    op.drop_index("ix_device_sessions_tenant_id", table_name="device_sessions")
    op.drop_table("device_sessions")

    op.drop_index("idx_desktop_devices_user_created", table_name="desktop_devices")
    op.drop_index("uq_desktop_devices_installation", table_name="desktop_devices")
    op.drop_index("ix_desktop_devices_user_id", table_name="desktop_devices")
    op.drop_index("ix_desktop_devices_tenant_id", table_name="desktop_devices")
    op.drop_table("desktop_devices")
