"""035_operator_notification_recipients

Adds optional recipient scoping to operator notifications.

Revision ID: 035_operator_notification_recipients
Revises: 034_escalation_guest_update_state
"""

from alembic import op


revision = "035_operator_notification_recipients"
down_revision = "034_escalation_guest_update_state"
branch_labels = None
depends_on = None


UP_SQL = """
ALTER TABLE operator_notifications
    ADD COLUMN IF NOT EXISTS recipient_user_id UUID;

CREATE INDEX IF NOT EXISTS idx_op_notif_tenant_recipient_unread
    ON operator_notifications (tenant_id, recipient_user_id, read_at, created_at DESC);
"""


DOWN_SQL = """
DROP INDEX IF EXISTS idx_op_notif_tenant_recipient_unread;
ALTER TABLE operator_notifications
    DROP COLUMN IF EXISTS recipient_user_id;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
