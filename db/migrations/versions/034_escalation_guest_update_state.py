"""034_escalation_guest_update_state

Adds explicit guest update coordination state to escalations.

Revision ID: 034_escalation_guest_update_state
Revises: 033_escalation_watcher_notifications
"""

from alembic import op


revision = "034_escalation_guest_update_state"
down_revision = "033_escalation_watcher_notifications"
branch_labels = None
depends_on = None


UP_SQL = """
ALTER TABLE concierge_escalations
    ADD COLUMN IF NOT EXISTS guest_update_status TEXT,
    ADD COLUMN IF NOT EXISTS guest_update_due_at TIMESTAMPTZ;
"""


DOWN_SQL = """
ALTER TABLE concierge_escalations
    DROP COLUMN IF EXISTS guest_update_due_at,
    DROP COLUMN IF EXISTS guest_update_status;
"""


def upgrade():
    op.execute(UP_SQL)


def downgrade():
    op.execute(DOWN_SQL)
