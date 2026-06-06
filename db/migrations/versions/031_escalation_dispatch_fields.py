"""031_escalation_dispatch_fields

Adds dispatch-vendor tracking fields to concierge escalations so operators can
record who was dispatched, ETA, and whether the guest has been updated.

Revision ID: 031_escalation_dispatch_fields
Revises: 030_operator_ai_guidance
"""

from alembic import op


revision = "031_escalation_dispatch_fields"
down_revision = "030_operator_ai_guidance"
branch_labels = None
depends_on = None


UP_SQL = """
ALTER TABLE concierge_escalations
    ADD COLUMN IF NOT EXISTS vendor_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS vendor_phone VARCHAR(50),
    ADD COLUMN IF NOT EXISTS vendor_eta_minutes INTEGER,
    ADD COLUMN IF NOT EXISTS vendor_status VARCHAR(50),
    ADD COLUMN IF NOT EXISTS guest_updated_at TIMESTAMPTZ;
"""


DOWN_SQL = """
ALTER TABLE concierge_escalations
    DROP COLUMN IF EXISTS guest_updated_at,
    DROP COLUMN IF EXISTS vendor_status,
    DROP COLUMN IF EXISTS vendor_eta_minutes,
    DROP COLUMN IF EXISTS vendor_phone,
    DROP COLUMN IF EXISTS vendor_name;
"""


def upgrade():
    op.execute(UP_SQL)


def downgrade():
    op.execute(DOWN_SQL)
