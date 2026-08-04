"""add Sprint 11 identity and account security state

Revision ID: 20260804_0024
Revises: 20260803_0023
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260804_0024"
down_revision: str | None = "20260803_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type() -> sa.types.TypeEngine[object]:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("local_password_enabled", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("failed_login_attempts", sa.Integer(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("last_failed_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("lock_reason", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            "update users set local_password_enabled = true where local_password_enabled is null"
        )
    )
    op.execute(
        sa.text("update users set failed_login_attempts = 0 where failed_login_attempts is null")
    )
    op.execute(
        sa.text(
            "update users set password_changed_at = "
            "coalesce(password_changed_at, updated_at, now())"
        )
    )
    op.alter_column("users", "local_password_enabled", existing_type=sa.Boolean(), nullable=False)
    op.alter_column("users", "failed_login_attempts", existing_type=sa.Integer(), nullable=False)

    op.add_column("auth_sessions", sa.Column("ip", sa.String(length=64), nullable=True))
    op.add_column("auth_sessions", sa.Column("user_agent", sa.String(length=512), nullable=True))
    op.add_column(
        "auth_sessions",
        sa.Column("auth_method", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "auth_sessions",
        sa.Column("oidc_provider_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "auth_sessions",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(sa.text("update auth_sessions set auth_method = 'local' where auth_method is null"))
    op.execute(
        sa.text("update auth_sessions set last_seen_at = coalesce(last_seen_at, created_at, now())")
    )
    op.alter_column(
        "auth_sessions",
        "auth_method",
        existing_type=sa.String(length=32),
        nullable=False,
    )
    op.alter_column(
        "auth_sessions",
        "last_seen_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.create_index(
        "idx_auth_sessions_user_active",
        "auth_sessions",
        ["tenant_id", "user_id", "revoked_at", "expires_at"],
    )

    op.create_table(
        "oidc_providers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("issuer_url", sa.String(length=2048), nullable=False),
        sa.Column("client_id", sa.String(length=512), nullable=False),
        sa.Column("client_secret_ref", sa.String(length=1024), nullable=True),
        sa.Column("scopes", _json_type(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_oidc_providers_tenant_id", "oidc_providers", ["tenant_id"])
    op.create_index(
        "uq_oidc_providers_slug",
        "oidc_providers",
        ["tenant_id", "slug"],
        unique=True,
    )
    op.create_index(
        "idx_oidc_providers_enabled",
        "oidc_providers",
        ["tenant_id", "enabled", "created_at", "id"],
    )

    op.create_table(
        "oidc_flows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("nonce_hash", sa.String(length=64), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("redirect_uri", sa.String(length=2048), nullable=False),
        sa.Column("redirect_path", sa.String(length=1024), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("purpose in ('login', 'bind')", name="ck_oidc_flows_purpose"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_id"], ["oidc_providers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_oidc_flows_tenant_id", "oidc_flows", ["tenant_id"])
    op.create_index("ix_oidc_flows_provider_id", "oidc_flows", ["provider_id"])
    op.create_index("ix_oidc_flows_user_id", "oidc_flows", ["user_id"])
    op.create_index("uq_oidc_flows_state_hash", "oidc_flows", ["state_hash"], unique=True)
    op.create_index(
        "idx_oidc_flows_expiry",
        "oidc_flows",
        ["expires_at", "consumed_at"],
    )

    op.create_table(
        "oidc_identity_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=2048), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_id"], ["oidc_providers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_oidc_identity_links_tenant_id", "oidc_identity_links", ["tenant_id"])
    op.create_index("ix_oidc_identity_links_provider_id", "oidc_identity_links", ["provider_id"])
    op.create_index("ix_oidc_identity_links_user_id", "oidc_identity_links", ["user_id"])
    op.create_index(
        "uq_oidc_identity_links_subject",
        "oidc_identity_links",
        ["tenant_id", "issuer", "subject"],
        unique=True,
    )
    op.create_index(
        "uq_oidc_identity_links_provider_user",
        "oidc_identity_links",
        ["tenant_id", "provider_id", "user_id"],
        unique=True,
    )

    op.create_table(
        "ldap_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("server_url", sa.String(length=2048), nullable=False),
        sa.Column("base_dn", sa.String(length=2048), nullable=False),
        sa.Column("bind_dn", sa.String(length=2048), nullable=True),
        sa.Column("bind_password_ref", sa.String(length=1024), nullable=True),
        sa.Column("user_base_dn", sa.String(length=2048), nullable=False),
        sa.Column("user_filter", sa.String(length=2048), nullable=False),
        sa.Column("department_base_dn", sa.String(length=2048), nullable=True),
        sa.Column("department_filter", sa.String(length=2048), nullable=True),
        sa.Column("group_base_dn", sa.String(length=2048), nullable=True),
        sa.Column("group_filter", sa.String(length=2048), nullable=True),
        sa.Column("attribute_mapping", _json_type(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("sync_cursor", sa.String(length=128), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ldap_sources_tenant_id", "ldap_sources", ["tenant_id"])
    op.create_index("uq_ldap_sources_slug", "ldap_sources", ["tenant_id", "slug"], unique=True)
    op.create_index(
        "idx_ldap_sources_enabled",
        "ldap_sources",
        ["tenant_id", "enabled", "created_at", "id"],
    )

    op.create_table(
        "ldap_sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("cursor_before", sa.String(length=128), nullable=True),
        sa.Column("cursor_after", sa.String(length=128), nullable=True),
        sa.Column("stats", _json_type(), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "mode in ('dry_run', 'full', 'incremental')",
            name="ck_ldap_sync_runs_mode",
        ),
        sa.CheckConstraint(
            "status in ('queued', 'running', 'succeeded', 'failed')",
            name="ck_ldap_sync_runs_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["ldap_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ldap_sync_runs_tenant_id", "ldap_sync_runs", ["tenant_id"])
    op.create_index("ix_ldap_sync_runs_source_id", "ldap_sync_runs", ["source_id"])
    op.create_index(
        "uq_ldap_sync_runs_active_source",
        "ldap_sync_runs",
        ["source_id"],
        unique=True,
        postgresql_where=sa.text("status in ('queued', 'running')"),
    )
    op.create_index(
        "idx_ldap_sync_runs_source",
        "ldap_sync_runs",
        ["tenant_id", "source_id", "created_at", "id"],
    )

    op.create_table(
        "ldap_object_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("object_type", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=False),
        sa.Column("local_object_id", sa.Uuid(), nullable=False),
        sa.Column("authoritative", sa.Boolean(), nullable=False),
        sa.Column("sync_state", sa.String(length=16), nullable=False),
        sa.Column("last_seen_run_id", sa.Uuid(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attribute_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "object_type in ('user', 'department', 'group')",
            name="ck_ldap_object_bindings_type",
        ),
        sa.CheckConstraint(
            "sync_state in ('active', 'disabled', 'missing', 'conflict')",
            name="ck_ldap_object_bindings_state",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["ldap_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["last_seen_run_id"],
            ["ldap_sync_runs.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ldap_object_bindings_tenant_id", "ldap_object_bindings", ["tenant_id"])
    op.create_index("ix_ldap_object_bindings_source_id", "ldap_object_bindings", ["source_id"])
    op.create_index(
        "uq_ldap_object_bindings_external",
        "ldap_object_bindings",
        ["tenant_id", "source_id", "object_type", "external_id"],
        unique=True,
    )
    op.create_index(
        "uq_ldap_object_bindings_local",
        "ldap_object_bindings",
        ["tenant_id", "source_id", "object_type", "local_object_id"],
        unique=True,
    )

    op.create_table(
        "ldap_sync_conflicts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("object_type", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("details", _json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "object_type in ('user', 'department', 'group', 'membership')",
            name="ck_ldap_sync_conflicts_type",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["ldap_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["ldap_sync_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ldap_sync_conflicts_tenant_id", "ldap_sync_conflicts", ["tenant_id"])
    op.create_index("ix_ldap_sync_conflicts_source_id", "ldap_sync_conflicts", ["source_id"])
    op.create_index("ix_ldap_sync_conflicts_run_id", "ldap_sync_conflicts", ["run_id"])
    op.create_index(
        "idx_ldap_sync_conflicts_run",
        "ldap_sync_conflicts",
        ["tenant_id", "run_id", "created_at", "id"],
    )

    op.create_table(
        "ldap_membership_relations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("relation_type", sa.String(length=16), nullable=False),
        sa.Column("container_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("core_edge_managed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "relation_type in ('department', 'group')",
            name="ck_ldap_membership_relations_type",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_ldap_membership_relations_edge",
        "ldap_membership_relations",
        ["tenant_id", "relation_type", "container_id", "user_id"],
        unique=True,
    )

    op.create_table(
        "ldap_membership_claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("relation_id", sa.Uuid(), nullable=False),
        sa.Column("external_container_id", sa.String(length=512), nullable=False),
        sa.Column("external_user_id", sa.String(length=512), nullable=False),
        sa.Column("last_seen_run_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["ldap_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["relation_id"],
            ["ldap_membership_relations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["last_seen_run_id"], ["ldap_sync_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ldap_membership_claims_tenant_id", "ldap_membership_claims", ["tenant_id"])
    op.create_index("ix_ldap_membership_claims_source_id", "ldap_membership_claims", ["source_id"])
    op.create_index(
        "ix_ldap_membership_claims_relation_id",
        "ldap_membership_claims",
        ["relation_id"],
    )
    op.create_index(
        "uq_ldap_membership_claims_source",
        "ldap_membership_claims",
        ["source_id", "relation_id"],
        unique=True,
    )
    op.create_index(
        "idx_ldap_membership_claims_seen",
        "ldap_membership_claims",
        ["source_id", "last_seen_run_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_ldap_membership_claims_seen", table_name="ldap_membership_claims")
    op.drop_index("uq_ldap_membership_claims_source", table_name="ldap_membership_claims")
    op.drop_index("ix_ldap_membership_claims_relation_id", table_name="ldap_membership_claims")
    op.drop_index("ix_ldap_membership_claims_source_id", table_name="ldap_membership_claims")
    op.drop_index("ix_ldap_membership_claims_tenant_id", table_name="ldap_membership_claims")
    op.drop_table("ldap_membership_claims")

    op.drop_index("uq_ldap_membership_relations_edge", table_name="ldap_membership_relations")
    op.drop_table("ldap_membership_relations")

    op.drop_index("idx_ldap_sync_conflicts_run", table_name="ldap_sync_conflicts")
    op.drop_index("ix_ldap_sync_conflicts_run_id", table_name="ldap_sync_conflicts")
    op.drop_index("ix_ldap_sync_conflicts_source_id", table_name="ldap_sync_conflicts")
    op.drop_index("ix_ldap_sync_conflicts_tenant_id", table_name="ldap_sync_conflicts")
    op.drop_table("ldap_sync_conflicts")

    op.drop_index("uq_ldap_object_bindings_local", table_name="ldap_object_bindings")
    op.drop_index("uq_ldap_object_bindings_external", table_name="ldap_object_bindings")
    op.drop_index("ix_ldap_object_bindings_source_id", table_name="ldap_object_bindings")
    op.drop_index("ix_ldap_object_bindings_tenant_id", table_name="ldap_object_bindings")
    op.drop_table("ldap_object_bindings")

    op.drop_index("idx_ldap_sync_runs_source", table_name="ldap_sync_runs")
    op.drop_index("uq_ldap_sync_runs_active_source", table_name="ldap_sync_runs")
    op.drop_index("ix_ldap_sync_runs_source_id", table_name="ldap_sync_runs")
    op.drop_index("ix_ldap_sync_runs_tenant_id", table_name="ldap_sync_runs")
    op.drop_table("ldap_sync_runs")

    op.drop_index("idx_ldap_sources_enabled", table_name="ldap_sources")
    op.drop_index("uq_ldap_sources_slug", table_name="ldap_sources")
    op.drop_index("ix_ldap_sources_tenant_id", table_name="ldap_sources")
    op.drop_table("ldap_sources")

    op.drop_index("uq_oidc_identity_links_provider_user", table_name="oidc_identity_links")
    op.drop_index("uq_oidc_identity_links_subject", table_name="oidc_identity_links")
    op.drop_index("ix_oidc_identity_links_user_id", table_name="oidc_identity_links")
    op.drop_index("ix_oidc_identity_links_provider_id", table_name="oidc_identity_links")
    op.drop_index("ix_oidc_identity_links_tenant_id", table_name="oidc_identity_links")
    op.drop_table("oidc_identity_links")

    op.drop_index("idx_oidc_flows_expiry", table_name="oidc_flows")
    op.drop_index("uq_oidc_flows_state_hash", table_name="oidc_flows")
    op.drop_index("ix_oidc_flows_user_id", table_name="oidc_flows")
    op.drop_index("ix_oidc_flows_provider_id", table_name="oidc_flows")
    op.drop_index("ix_oidc_flows_tenant_id", table_name="oidc_flows")
    op.drop_table("oidc_flows")

    op.drop_index("idx_oidc_providers_enabled", table_name="oidc_providers")
    op.drop_index("uq_oidc_providers_slug", table_name="oidc_providers")
    op.drop_index("ix_oidc_providers_tenant_id", table_name="oidc_providers")
    op.drop_table("oidc_providers")

    op.drop_index("idx_auth_sessions_user_active", table_name="auth_sessions")
    op.drop_column("auth_sessions", "last_seen_at")
    op.drop_column("auth_sessions", "oidc_provider_id")
    op.drop_column("auth_sessions", "auth_method")
    op.drop_column("auth_sessions", "user_agent")
    op.drop_column("auth_sessions", "ip")

    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "lock_reason")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "last_failed_login_at")
    op.drop_column("users", "failed_login_attempts")
    op.drop_column("users", "local_password_enabled")
