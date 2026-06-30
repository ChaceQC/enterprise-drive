"""create org base tables

Revision ID: 20260701_0008
Revises: 20260701_0007
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260701_0008"
down_revision = "20260701_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("path", sa.String(length=2048), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint("status in ('active', 'disabled')", name="ck_departments_status"),
        sa.ForeignKeyConstraint(["parent_id"], ["departments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_departments_tenant_id", "departments", ["tenant_id"])
    op.create_index("ix_departments_parent_id", "departments", ["parent_id"])
    op.create_index(
        "idx_departments_parent",
        "departments",
        ["tenant_id", "parent_id", "sort_order", "id"],
    )
    op.create_index("idx_departments_path", "departments", ["tenant_id", "path"], unique=True)

    op.create_table(
        "user_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint("status in ('active', 'disabled')", name="ck_user_groups_status"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_groups_tenant_id", "user_groups", ["tenant_id"])
    op.create_index("uq_user_groups_slug", "user_groups", ["tenant_id", "slug"], unique=True)
    op.create_index("idx_user_groups_status", "user_groups", ["tenant_id", "status"])

    op.create_table(
        "department_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_department_members_tenant_id", "department_members", ["tenant_id"])
    op.create_index(
        "ix_department_members_department_id",
        "department_members",
        ["department_id"],
    )
    op.create_index("ix_department_members_user_id", "department_members", ["user_id"])
    op.create_index(
        "uq_department_members_user",
        "department_members",
        ["tenant_id", "department_id", "user_id"],
        unique=True,
    )
    op.create_index(
        "idx_department_members_user",
        "department_members",
        ["tenant_id", "user_id", "department_id"],
    )

    op.create_table(
        "user_group_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["group_id"], ["user_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_group_members_tenant_id", "user_group_members", ["tenant_id"])
    op.create_index("ix_user_group_members_group_id", "user_group_members", ["group_id"])
    op.create_index("ix_user_group_members_user_id", "user_group_members", ["user_id"])
    op.create_index(
        "uq_user_group_members_user",
        "user_group_members",
        ["tenant_id", "group_id", "user_id"],
        unique=True,
    )
    op.create_index(
        "idx_user_group_members_user",
        "user_group_members",
        ["tenant_id", "user_id", "group_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_user_group_members_user", table_name="user_group_members")
    op.drop_index("uq_user_group_members_user", table_name="user_group_members")
    op.drop_index("ix_user_group_members_user_id", table_name="user_group_members")
    op.drop_index("ix_user_group_members_group_id", table_name="user_group_members")
    op.drop_index("ix_user_group_members_tenant_id", table_name="user_group_members")
    op.drop_table("user_group_members")
    op.drop_index("idx_department_members_user", table_name="department_members")
    op.drop_index("uq_department_members_user", table_name="department_members")
    op.drop_index("ix_department_members_user_id", table_name="department_members")
    op.drop_index("ix_department_members_department_id", table_name="department_members")
    op.drop_index("ix_department_members_tenant_id", table_name="department_members")
    op.drop_table("department_members")
    op.drop_index("idx_user_groups_status", table_name="user_groups")
    op.drop_index("uq_user_groups_slug", table_name="user_groups")
    op.drop_index("ix_user_groups_tenant_id", table_name="user_groups")
    op.drop_table("user_groups")
    op.drop_index("idx_departments_path", table_name="departments")
    op.drop_index("idx_departments_parent", table_name="departments")
    op.drop_index("ix_departments_parent_id", table_name="departments")
    op.drop_index("ix_departments_tenant_id", table_name="departments")
    op.drop_table("departments")
