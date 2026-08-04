"""add Sprint 12 audit governance and outbox dead letters

Revision ID: 20260804_0025
Revises: 20260804_0024
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0025"
down_revision: str | None = "20260804_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _add_outbox_dead_letter_columns()
    _add_export_signature_columns()
    _create_audit_archives()

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _partition_audit_logs_postgresql()
    else:
        op.alter_column(
            "audit_logs",
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _unpartition_audit_logs_postgresql()

    op.drop_index("idx_audit_archives_status", table_name="audit_archives")
    op.drop_index("idx_audit_archives_tenant_created", table_name="audit_archives")
    op.drop_index("ix_audit_archives_tenant_id", table_name="audit_archives")
    op.drop_table("audit_archives")

    for column_name in (
        "signature_value",
        "signature_key_id",
        "signature_algorithm",
        "content_sha256",
    ):
        op.drop_column("admin_jobs", column_name)

    op.drop_index("idx_outbox_dead_letters", table_name="outbox_events")
    for column_name in (
        "last_replayed_by",
        "last_replayed_at",
        "replay_count",
        "dead_at",
        "last_failed_at",
        "last_error_code",
        "last_error_kind",
    ):
        op.drop_column("outbox_events", column_name)


def _add_outbox_dead_letter_columns() -> None:
    op.add_column(
        "outbox_events",
        sa.Column("last_error_kind", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("dead_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("replay_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "outbox_events",
        sa.Column("last_replayed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("last_replayed_by", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "idx_outbox_dead_letters",
        "outbox_events",
        ["tenant_id", "status", "dead_at", "created_at", "id"],
    )


def _add_export_signature_columns() -> None:
    op.add_column(
        "admin_jobs",
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "admin_jobs",
        sa.Column("signature_algorithm", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "admin_jobs",
        sa.Column("signature_key_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "admin_jobs",
        sa.Column("signature_value", sa.String(length=128), nullable=True),
    )


def _create_audit_archives() -> None:
    op.create_table(
        "audit_archives",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("storage_bucket", sa.String(length=128), nullable=True),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("signature_algorithm", sa.String(length=64), nullable=True),
        sa.Column("signature_key_id", sa.String(length=128), nullable=True),
        sa.Column("signature_value", sa.String(length=128), nullable=True),
        sa.Column("delete_source", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "period_start",
            "period_end",
            name="uq_audit_archives_tenant_period",
        ),
    )
    op.create_index("ix_audit_archives_tenant_id", "audit_archives", ["tenant_id"])
    op.create_index(
        "idx_audit_archives_tenant_created",
        "audit_archives",
        ["tenant_id", "created_at", "id"],
    )
    op.create_index(
        "idx_audit_archives_status",
        "audit_archives",
        ["status", "updated_at", "id"],
    )


def _partition_audit_logs_postgresql() -> None:
    op.execute("ALTER TABLE audit_logs RENAME TO audit_logs_legacy")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'audit_logs_pkey'
                  AND conrelid = 'audit_logs_legacy'::regclass
            ) THEN
                ALTER TABLE audit_logs_legacy
                    RENAME CONSTRAINT audit_logs_pkey TO audit_logs_legacy_pkey;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        ALTER TABLE audit_logs_legacy
            DROP CONSTRAINT IF EXISTS audit_logs_legacy_pkey
        """
    )
    for index_name in (
        "ix_audit_logs_tenant_id",
        "ix_audit_logs_actor_id",
        "ix_audit_logs_action",
        "ix_audit_logs_created_at",
        "idx_audit_actor_time",
        "idx_audit_resource_time",
    ):
        op.execute(sa.text(f"ALTER INDEX IF EXISTS {index_name} RENAME TO {index_name}_legacy"))
    op.execute(
        """
        UPDATE audit_logs_legacy
        SET created_at = now()
        WHERE created_at IS NULL
        """
    )
    op.execute("ALTER TABLE audit_logs_legacy ALTER COLUMN created_at SET NOT NULL")
    op.execute(
        """
        CREATE TABLE audit_logs (
            id uuid NOT NULL,
            tenant_id uuid NOT NULL,
            actor_id uuid NULL,
            actor_type varchar(32) NOT NULL,
            action varchar(128) NOT NULL,
            resource_type varchar(64) NOT NULL,
            resource_id uuid NULL,
            result varchar(32) NOT NULL,
            risk_level varchar(32) NOT NULL,
            request_id varchar(128) NULL,
            ip varchar(64) NULL,
            user_agent text NULL,
            metadata_json jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_audit_logs PRIMARY KEY (created_at, id),
            CONSTRAINT audit_logs_tenant_id_fkey
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
        ) PARTITION BY RANGE (created_at)
        """
    )
    op.execute(
        """
        DO $$
        DECLARE
            current_start timestamptz := date_trunc('month', now());
            partition_start timestamptz;
            partition_end timestamptz;
            partition_name text;
            offset_month integer;
        BEGIN
            FOR offset_month IN 0..6 LOOP
                partition_start := current_start + make_interval(months => offset_month);
                partition_end := current_start + make_interval(months => offset_month + 1);
                partition_name := 'audit_logs_' || to_char(partition_start, 'YYYYMM');
                EXECUTE format(
                    'CREATE TABLE IF NOT EXISTS %I PARTITION OF audit_logs '
                    'FOR VALUES FROM (%L) TO (%L)',
                    partition_name,
                    partition_start,
                    partition_end
                );
            END LOOP;
        END
        $$;
        """
    )
    op.execute(
        """
        INSERT INTO audit_logs (
            id, tenant_id, actor_id, actor_type, action, resource_type,
            resource_id, result, risk_level, request_id, ip, user_agent,
            metadata_json, created_at
        )
        SELECT
            id, tenant_id, actor_id, actor_type, action, resource_type,
            resource_id, result, risk_level, request_id, ip, user_agent,
            metadata_json, created_at
        FROM audit_logs_legacy
        WHERE created_at >= date_trunc('month', now())
        ON CONFLICT (created_at, id) DO NOTHING
        """
    )
    op.execute(
        """
        DELETE FROM audit_logs_legacy
        WHERE created_at >= date_trunc('month', now())
        """
    )
    op.execute(
        """
        DO $$
        DECLARE
            current_start timestamptz := date_trunc('month', now());
        BEGIN
            EXECUTE format(
                'ALTER TABLE audit_logs_legacy '
                'ADD CONSTRAINT audit_logs_legacy_partition_bound '
                'CHECK (created_at < %L::timestamptz) NOT VALID',
                current_start
            );
            ALTER TABLE audit_logs_legacy
                VALIDATE CONSTRAINT audit_logs_legacy_partition_bound;
            EXECUTE format(
                'ALTER TABLE audit_logs '
                'ATTACH PARTITION audit_logs_legacy '
                'FOR VALUES FROM (MINVALUE) TO (%L)',
                current_start
            );
        END
        $$;
        """
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index(
        "idx_audit_actor_time",
        "audit_logs",
        ["tenant_id", "actor_id", "created_at"],
    )
    op.create_index(
        "idx_audit_resource_time",
        "audit_logs",
        ["tenant_id", "resource_type", "resource_id", "created_at"],
    )


def _unpartition_audit_logs_postgresql() -> None:
    op.execute(
        """
        CREATE TABLE audit_logs_unpartitioned (
            id uuid NOT NULL,
            tenant_id uuid NOT NULL,
            actor_id uuid NULL,
            actor_type varchar(32) NOT NULL,
            action varchar(128) NOT NULL,
            resource_type varchar(64) NOT NULL,
            resource_id uuid NULL,
            result varchar(32) NOT NULL,
            risk_level varchar(32) NOT NULL,
            request_id varchar(128) NULL,
            ip varchar(64) NULL,
            user_agent text NULL,
            metadata_json jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT audit_logs_unpartitioned_pkey PRIMARY KEY (id),
            CONSTRAINT audit_logs_unpartitioned_tenant_id_fkey
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        INSERT INTO audit_logs_unpartitioned (
            id, tenant_id, actor_id, actor_type, action, resource_type,
            resource_id, result, risk_level, request_id, ip, user_agent,
            metadata_json, created_at
        )
        SELECT
            id, tenant_id, actor_id, actor_type, action, resource_type,
            resource_id, result, risk_level, request_id, ip, user_agent,
            metadata_json, created_at
        FROM audit_logs
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute("DROP TABLE audit_logs CASCADE")
    op.execute("ALTER TABLE audit_logs_unpartitioned RENAME TO audit_logs")
    op.execute(
        "ALTER TABLE audit_logs RENAME CONSTRAINT audit_logs_unpartitioned_pkey TO audit_logs_pkey"
    )
    op.execute(
        "ALTER TABLE audit_logs RENAME CONSTRAINT "
        "audit_logs_unpartitioned_tenant_id_fkey TO audit_logs_tenant_id_fkey"
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index(
        "idx_audit_actor_time",
        "audit_logs",
        ["tenant_id", "actor_id", "created_at"],
    )
    op.create_index(
        "idx_audit_resource_time",
        "audit_logs",
        ["tenant_id", "resource_type", "resource_id", "created_at"],
    )
