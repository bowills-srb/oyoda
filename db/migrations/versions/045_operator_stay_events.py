"""Add operator stay events.

Revision ID: 045_operator_stay_events
Revises: 044_operator_workflow_handoffs
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "045_operator_stay_events"
down_revision = "044_operator_workflow_handoffs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operator_stay_events",
        sa.Column("stay_event_id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_token", sa.Text(), nullable=True),
        sa.Column("property_code", sa.Text(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_domain", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="completed"),
        sa.Column("source", sa.Text(), nullable=False, server_default="operator"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index(
        "ix_operator_stay_events_tenant_session",
        "operator_stay_events",
        ["tenant_id", "session_id", "occurred_at"],
    )
    op.create_index(
        "ix_operator_stay_events_tenant_property",
        "operator_stay_events",
        ["tenant_id", "property_code", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_operator_stay_events_tenant_property", table_name="operator_stay_events")
    op.drop_index("ix_operator_stay_events_tenant_session", table_name="operator_stay_events")
    op.drop_table("operator_stay_events")
