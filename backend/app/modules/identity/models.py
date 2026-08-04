from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import utc_now
from app.db.base import Base


class OidcProvider(Base):
    __tablename__ = "oidc_providers"
    __table_args__ = (
        Index("uq_oidc_providers_slug", "tenant_id", "slug", unique=True),
        Index("idx_oidc_providers_enabled", "tenant_id", "enabled", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    issuer_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    client_id: Mapped[str] = mapped_column(String(512), nullable=False)
    client_secret_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=lambda: ["openid"])
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class OidcFlow(Base):
    __tablename__ = "oidc_flows"
    __table_args__ = (
        CheckConstraint("purpose in ('login', 'bind')", name="ck_oidc_flows_purpose"),
        Index("uq_oidc_flows_state_hash", "state_hash", unique=True),
        Index("idx_oidc_flows_expiry", "expires_at", "consumed_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("oidc_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    nonce_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    redirect_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class OidcIdentityLink(Base):
    __tablename__ = "oidc_identity_links"
    __table_args__ = (
        Index(
            "uq_oidc_identity_links_subject",
            "tenant_id",
            "issuer",
            "subject",
            unique=True,
        ),
        Index(
            "uq_oidc_identity_links_provider_user",
            "tenant_id",
            "provider_id",
            "user_id",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("oidc_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    issuer: Mapped[str] = mapped_column(String(2048), nullable=False)
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LdapSource(Base):
    __tablename__ = "ldap_sources"
    __table_args__ = (
        Index("uq_ldap_sources_slug", "tenant_id", "slug", unique=True),
        Index("idx_ldap_sources_enabled", "tenant_id", "enabled", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    server_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    base_dn: Mapped[str] = mapped_column(String(2048), nullable=False)
    bind_dn: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    bind_password_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    user_base_dn: Mapped[str] = mapped_column(String(2048), nullable=False)
    user_filter: Mapped[str] = mapped_column(String(2048), nullable=False)
    department_base_dn: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    department_filter: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    group_base_dn: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    group_filter: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    attribute_mapping: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sync_cursor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class LdapSyncRun(Base):
    __tablename__ = "ldap_sync_runs"
    __table_args__ = (
        CheckConstraint(
            "mode in ('dry_run', 'full', 'incremental')",
            name="ck_ldap_sync_runs_mode",
        ),
        CheckConstraint(
            "status in ('queued', 'running', 'succeeded', 'failed')",
            name="ck_ldap_sync_runs_status",
        ),
        Index(
            "uq_ldap_sync_runs_active_source",
            "source_id",
            unique=True,
            postgresql_where=text("status in ('queued', 'running')"),
            sqlite_where=text("status in ('queued', 'running')"),
        ),
        Index("idx_ldap_sync_runs_source", "tenant_id", "source_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ldap_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requested_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    cursor_before: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cursor_after: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stats: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class LdapObjectBinding(Base):
    __tablename__ = "ldap_object_bindings"
    __table_args__ = (
        CheckConstraint(
            "object_type in ('user', 'department', 'group')",
            name="ck_ldap_object_bindings_type",
        ),
        CheckConstraint(
            "sync_state in ('active', 'disabled', 'missing', 'conflict')",
            name="ck_ldap_object_bindings_state",
        ),
        Index(
            "uq_ldap_object_bindings_external",
            "tenant_id",
            "source_id",
            "object_type",
            "external_id",
            unique=True,
        ),
        Index(
            "uq_ldap_object_bindings_local",
            "tenant_id",
            "source_id",
            "object_type",
            "local_object_id",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ldap_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    object_type: Mapped[str] = mapped_column(String(16), nullable=False)
    external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    local_object_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sync_state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    last_seen_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ldap_sync_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attribute_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class LdapSyncConflict(Base):
    __tablename__ = "ldap_sync_conflicts"
    __table_args__ = (
        CheckConstraint(
            "object_type in ('user', 'department', 'group', 'membership')",
            name="ck_ldap_sync_conflicts_type",
        ),
        Index("idx_ldap_sync_conflicts_run", "tenant_id", "run_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ldap_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ldap_sync_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    object_type: Mapped[str] = mapped_column(String(16), nullable=False)
    external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class LdapMembershipRelation(Base):
    __tablename__ = "ldap_membership_relations"
    __table_args__ = (
        CheckConstraint(
            "relation_type in ('department', 'group')",
            name="ck_ldap_membership_relations_type",
        ),
        Index(
            "uq_ldap_membership_relations_edge",
            "tenant_id",
            "relation_type",
            "container_id",
            "user_id",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation_type: Mapped[str] = mapped_column(String(16), nullable=False)
    container_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    core_edge_managed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class LdapMembershipClaim(Base):
    __tablename__ = "ldap_membership_claims"
    __table_args__ = (
        Index(
            "uq_ldap_membership_claims_source",
            "source_id",
            "relation_id",
            unique=True,
        ),
        Index("idx_ldap_membership_claims_seen", "source_id", "last_seen_run_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ldap_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ldap_membership_relations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_container_id: Mapped[str] = mapped_column(String(512), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(512), nullable=False)
    last_seen_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("ldap_sync_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
