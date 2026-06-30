"""create space and file metadata tables

Revision ID: 20260630_0003
Revises: 20260630_0002
Create Date: 2026-06-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260630_0003"
down_revision = "20260630_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "spaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("space_type", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("permission_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_spaces_tenant_id", "spaces", ["tenant_id"])
    op.create_index("ix_spaces_owner_id", "spaces", ["owner_id"])
    op.create_index(
        "idx_spaces_tenant_type_owner",
        "spaces",
        ["tenant_id", "space_type", "owner_id"],
    )
    op.create_index("uq_spaces_tenant_slug", "spaces", ["tenant_id", "slug"], unique=True)

    op.create_table(
        "file_blobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("hash_algo", sa.String(length=16), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("ref_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_file_blobs_tenant_id", "file_blobs", ["tenant_id"])
    op.create_index(
        "uq_file_blobs_hash",
        "file_blobs",
        ["tenant_id", "hash_algo", "content_hash", "size_bytes"],
        unique=True,
    )

    op.create_table(
        "nodes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("node_type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Uuid(), nullable=True),
        sa.Column("permission_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_id"], ["nodes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["space_id"], ["spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nodes_tenant_id", "nodes", ["tenant_id"])
    op.create_index("ix_nodes_space_id", "nodes", ["space_id"])
    op.create_index("ix_nodes_parent_id", "nodes", ["parent_id"])
    op.create_index("ix_nodes_owner_id", "nodes", ["owner_id"])
    op.create_index("idx_nodes_list", "nodes", ["tenant_id", "space_id", "parent_id", "is_deleted"])
    op.create_index("idx_nodes_updated", "nodes", ["tenant_id", "space_id", "updated_at"])
    op.execute(
        "create unique index uq_nodes_sibling_name "
        "on nodes(tenant_id, space_id, parent_id, lower(normalized_name)) "
        "where is_deleted = false and parent_id is not null"
    )
    op.execute(
        "create unique index uq_nodes_space_root "
        "on nodes(tenant_id, space_id) "
        "where is_deleted = false and parent_id is null"
    )

    op.create_table(
        "file_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("blob_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["blob_id"], ["file_blobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_file_versions_tenant_id", "file_versions", ["tenant_id"])
    op.create_index("ix_file_versions_node_id", "file_versions", ["node_id"])
    op.create_index("ix_file_versions_blob_id", "file_versions", ["blob_id"])
    op.create_index(
        "uq_file_versions_no",
        "file_versions",
        ["tenant_id", "node_id", "version_no"],
        unique=True,
    )
    op.create_index(
        "idx_file_versions_created",
        "file_versions",
        ["tenant_id", "node_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_file_versions_created", table_name="file_versions")
    op.drop_index("uq_file_versions_no", table_name="file_versions")
    op.drop_index("ix_file_versions_blob_id", table_name="file_versions")
    op.drop_index("ix_file_versions_node_id", table_name="file_versions")
    op.drop_index("ix_file_versions_tenant_id", table_name="file_versions")
    op.drop_table("file_versions")
    op.execute("drop index uq_nodes_space_root")
    op.execute("drop index uq_nodes_sibling_name")
    op.drop_index("idx_nodes_updated", table_name="nodes")
    op.drop_index("idx_nodes_list", table_name="nodes")
    op.drop_index("ix_nodes_owner_id", table_name="nodes")
    op.drop_index("ix_nodes_parent_id", table_name="nodes")
    op.drop_index("ix_nodes_space_id", table_name="nodes")
    op.drop_index("ix_nodes_tenant_id", table_name="nodes")
    op.drop_table("nodes")
    op.drop_index("uq_file_blobs_hash", table_name="file_blobs")
    op.drop_index("ix_file_blobs_tenant_id", table_name="file_blobs")
    op.drop_table("file_blobs")
    op.drop_index("uq_spaces_tenant_slug", table_name="spaces")
    op.drop_index("idx_spaces_tenant_type_owner", table_name="spaces")
    op.drop_index("ix_spaces_owner_id", table_name="spaces")
    op.drop_index("ix_spaces_tenant_id", table_name="spaces")
    op.drop_table("spaces")
