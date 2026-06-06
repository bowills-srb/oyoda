"""032_escalation_coordination_fields

Adds watcher and guest-update note fields to concierge escalations so
operators can track who is kept in the loop and what was communicated.

Revision ID: 032_escalation_coordination_fields
Revises: 031_escalation_dispatch_fields
"""

from alembic import op


revision = "032_escalation_coordination_fields"
down_revision = "031_escalation_dispatch_fields"
branch_labels = None
depends_on = None


UP_SQL = """
ALTER TABLE concierge_escalations
    ADD COLUMN IF NOT EXISTS watchers JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS guest_update_note TEXT;
"""


DOWN_SQL = """
ALTER TABLE concierge_escalations
    DROP COLUMN IF EXISTS guest_update_note,
    DROP COLUMN IF EXISTS watchers;
"""


def upgrade():
    op.execute(UP_SQL)


def downgrade():
    op.execute(DOWN_SQL)
