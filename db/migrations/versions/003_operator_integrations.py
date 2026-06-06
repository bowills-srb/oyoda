"""
003_operator_integrations

Adds tenant-scoped integration connection and sync telemetry tables.

Revision ID: 003_operator_integrations
Revises: 002_intelligence_artifacts
Create Date: 2026-02-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "003_operator_integrations"
down_revision = "002_intelligence_artifacts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "integration_connections",
        sa.Column("integration_connection_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="connected"),
        sa.Column("credential_ref", sa.String(255), nullable=False),
        sa.Column("settings", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "provider", name="uq_integration_tenant_provider"),
    )
    op.create_index(
        "ix_integration_tenant_provider",
        "integration_connections",
        ["tenant_id", "provider"],
    )
    op.create_index(
        "ix_integration_tenant_active",
        "integration_connections",
        ["tenant_id", "is_active"],
    )

    op.create_table(
        "integration_sync_jobs",
        sa.Column("sync_job_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("integration_connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("trigger", sa.String(30), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(30), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_pulled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("listings_pulled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bookings_pulled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("calendar_days_pulled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["integration_connection_id"],
            ["integration_connections.integration_connection_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_sync_jobs_tenant_started", "integration_sync_jobs", ["tenant_id", "started_at"])
    op.create_index("ix_sync_jobs_tenant_provider", "integration_sync_jobs", ["tenant_id", "provider"])
    op.create_index("ix_sync_jobs_status", "integration_sync_jobs", ["status"])

    op.create_table(
        "integration_raw_records",
        sa.Column("raw_record_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("integration_connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("record_type", sa.String(50), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["integration_connection_id"],
            ["integration_connections.integration_connection_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_raw_records_tenant_provider",
        "integration_raw_records",
        ["tenant_id", "provider", "record_type"],
    )
    op.create_index("ix_raw_records_observed", "integration_raw_records", ["observed_at"])
    op.create_index("ix_integration_raw_external_id", "integration_raw_records", ["external_id"])


def downgrade():
    op.drop_index("ix_integration_raw_external_id", table_name="integration_raw_records")
    op.drop_index("ix_raw_records_observed", table_name="integration_raw_records")
    op.drop_index("ix_raw_records_tenant_provider", table_name="integration_raw_records")
    op.drop_table("integration_raw_records")

    op.drop_index("ix_sync_jobs_status", table_name="integration_sync_jobs")
    op.drop_index("ix_sync_jobs_tenant_provider", table_name="integration_sync_jobs")
    op.drop_index("ix_sync_jobs_tenant_started", table_name="integration_sync_jobs")
    op.drop_table("integration_sync_jobs")

    op.drop_index("ix_integration_tenant_active", table_name="integration_connections")
    op.drop_index("ix_integration_tenant_provider", table_name="integration_connections")
    op.drop_table("integration_connections")
