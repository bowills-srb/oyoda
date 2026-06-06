"""
007_concierge_maintenance_events

Adds tenant-scoped maintenance event tracking for concierge escalations.

Revision ID: 007_concierge_maintenance_events
Revises: 006_concierge_global_faq
Create Date: 2026-02-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "007_concierge_maintenance_events"
down_revision = "006_concierge_global_faq"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "concierge_maintenance_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("property_external_id", sa.String(length=255), nullable=True),
        sa.Column("issue_text", sa.Text(), nullable=False),
        sa.Column("issue_key", sa.String(length=500), nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False, server_default="general"),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="concierge_auto"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("escalation_status", sa.String(length=20), nullable=False, server_default="none"),
        sa.Column("assigned_to", sa.String(length=255), nullable=True),
        sa.Column("reservation_id", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id",
            "property_external_id",
            "issue_key",
            "status",
            name="uq_concierge_maintenance_active_key",
        ),
    )

    op.create_index("ix_concierge_maintenance_events_tenant_id", "concierge_maintenance_events", ["tenant_id"])
    op.create_index("ix_concierge_maintenance_events_property_id", "concierge_maintenance_events", ["property_id"])
    op.create_index(
        "ix_concierge_maintenance_events_property_external_id",
        "concierge_maintenance_events",
        ["property_external_id"],
    )
    op.create_index(
        "ix_concierge_maintenance_tenant_status",
        "concierge_maintenance_events",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_concierge_maintenance_tenant_property",
        "concierge_maintenance_events",
        ["tenant_id", "property_external_id"],
    )
    op.create_index(
        "ix_concierge_maintenance_tenant_category",
        "concierge_maintenance_events",
        ["tenant_id", "category"],
    )
    op.create_index(
        "ix_concierge_maintenance_tenant_updated",
        "concierge_maintenance_events",
        ["tenant_id", "updated_at"],
    )


def downgrade():
    op.drop_index("ix_concierge_maintenance_tenant_updated", table_name="concierge_maintenance_events")
    op.drop_index("ix_concierge_maintenance_tenant_category", table_name="concierge_maintenance_events")
    op.drop_index("ix_concierge_maintenance_tenant_property", table_name="concierge_maintenance_events")
    op.drop_index("ix_concierge_maintenance_tenant_status", table_name="concierge_maintenance_events")
    op.drop_index("ix_concierge_maintenance_events_property_external_id", table_name="concierge_maintenance_events")
    op.drop_index("ix_concierge_maintenance_events_property_id", table_name="concierge_maintenance_events")
    op.drop_index("ix_concierge_maintenance_events_tenant_id", table_name="concierge_maintenance_events")
    op.drop_table("concierge_maintenance_events")
