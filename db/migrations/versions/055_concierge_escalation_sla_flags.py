"""055_concierge_escalation_sla_flags

Add SLA breach marker columns to concierge_escalations.

These fields are already referenced by the escalation handoff agent and
operator escalation workflow read paths:

  - ack_sla_breached
  - resolve_sla_breached

The intended semantics in current application code are boolean flags,
not timestamps. `_stamp_breach()` writes `TRUE` when a breach is
detected, and read sites aggregate/count them as booleans.

Revision ID: 055_concierge_escalation_sla_flags
Revises: 054_message_normalizations_composer_metadata
Create Date: 2026-05-07
"""

from alembic import op
import sqlalchemy as sa


revision = "055_concierge_escalation_sla_flags"
down_revision = "054_message_normalizations_composer_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "concierge_escalations",
        sa.Column(
            "ack_sla_breached",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "concierge_escalations",
        sa.Column(
            "resolve_sla_breached",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("concierge_escalations", "resolve_sla_breached")
    op.drop_column("concierge_escalations", "ack_sla_breached")
