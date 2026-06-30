"""create upload session tables

Revision ID: 20260630_0004
Revises: 20260630_0003
Create Date: 2026-06-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260630_0004"
down_revision = "20260630_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=False),
        sa.Column("uploader_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("hash_algo", sa.String(length=16), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("storage_bucket", sa.String(length=128), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("provider_upload_id", sa.String(length=255), nullable=True),
        sa.Column("part_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("total_parts", sa.Integer(), nullable=False),
        sa.Column("completed_node_id", sa.Uuid(), nullable=True),
        sa.Column("completed_version_id", sa.Uuid(), nullable=True),
        sa.Column("completed_blob_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["parent_id"], ["nodes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_upload_sessions_tenant_id", "upload_sessions", ["tenant_id"])
    op.create_index("ix_upload_sessions_space_id", "upload_sessions", ["space_id"])
    op.create_index("ix_upload_sessions_parent_id", "upload_sessions", ["parent_id"])
    op.create_index("ix_upload_sessions_uploader_id", "upload_sessions", ["uploader_id"])
    op.create_index(
        "idx_upload_sessions_uploader",
        "upload_sessions",
        ["tenant_id", "uploader_id", "status"],
    )
    op.create_index("idx_upload_sessions_expires", "upload_sessions", ["status", "expires_at"])

    op.create_table(
        "upload_parts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("upload_session_id", sa.Uuid(), nullable=False),
        sa.Column("part_no", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("etag", sa.String(length=255), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["upload_session_id"], ["upload_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_upload_parts_tenant_id", "upload_parts", ["tenant_id"])
    op.create_index("ix_upload_parts_upload_session_id", "upload_parts", ["upload_session_id"])
    op.create_index(
        "uq_upload_parts_session_no",
        "upload_parts",
        ["upload_session_id", "part_no"],
        unique=True,
    )
    op.create_index(
        "idx_upload_parts_session",
        "upload_parts",
        ["tenant_id", "upload_session_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_upload_parts_session", table_name="upload_parts")
    op.drop_index("uq_upload_parts_session_no", table_name="upload_parts")
    op.drop_index("ix_upload_parts_upload_session_id", table_name="upload_parts")
    op.drop_index("ix_upload_parts_tenant_id", table_name="upload_parts")
    op.drop_table("upload_parts")
    op.drop_index("idx_upload_sessions_expires", table_name="upload_sessions")
    op.drop_index("idx_upload_sessions_uploader", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_uploader_id", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_parent_id", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_space_id", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_tenant_id", table_name="upload_sessions")
    op.drop_table("upload_sessions")
