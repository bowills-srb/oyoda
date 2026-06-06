"""011_concierge_escalations

Create table for persisting escalation tickets.

Revision ID: 011
Revises: 010_operator_policies_markets
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "011"
down_revision = "010_operator_policies_markets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "concierge_escalations",
        sa.Column("ticket_id", sa.String(50), primary_key=True),
        sa.Column("session_token", sa.String(50), nullable=False),
        sa.Column("guest_name", sa.String(255), nullable=False),
        sa.Column("guest_phone", sa.String(50), nullable=True),
        sa.Column("guest_email", sa.String(255), nullable=True),
        sa.Column("property_name", sa.String(255), nullable=False),
        sa.Column("property_code", sa.String(100), nullable=False),
        sa.Column("reason", sa.String(50), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("last_message", sa.Text, nullable=True),
        sa.Column("conversation_history", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("assigned_to", sa.String(255), nullable=True),
        sa.Column("resolution_notes", sa.Text, nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()"), onupdate=sa.text("now()")),
    )
    op.create_index("ix_escalation_session_token", "concierge_escalations", ["session_token"])
    op.create_index("ix_escalation_status_priority", "concierge_escalations", ["status", "priority"])
    op.create_index("ix_escalation_property", "concierge_escalations", ["property_code"])


def downgrade() -> None:
    op.drop_table("concierge_escalations")
