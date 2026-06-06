"""033_escalation_watcher_notifications

Adds a timestamp for when escalation watchers were last notified.

Revision ID: 033_escalation_watcher_notifications
Revises: 032_escalation_coordination_fields
"""

from alembic import op


revision = "033_escalation_watcher_notifications"
down_revision = "032_escalation_coordination_fields"
branch_labels = None
depends_on = None


UP_SQL = """
ALTER TABLE concierge_escalations
    ADD COLUMN IF NOT EXISTS watchers_notified_at TIMESTAMPTZ;
"""


DOWN_SQL = """
ALTER TABLE concierge_escalations
    DROP COLUMN IF EXISTS watchers_notified_at;
"""


def upgrade():
    op.execute(UP_SQL)


def downgrade():
    op.execute(DOWN_SQL)
