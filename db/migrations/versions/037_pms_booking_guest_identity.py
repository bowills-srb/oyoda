"""037_pms_booking_guest_identity

Add guest identity fields to the canonical PMS booking cache so future
message/session matching can use reservation data without provider-specific
queries in the operator path.
"""

from alembic import op


revision = "037_pms_booking_guest_identity"
down_revision = "036_message_normalizations"
branch_labels = None
depends_on = None


UP_SQL = """
ALTER TABLE pms_bookings
    ADD COLUMN IF NOT EXISTS guest_first_name TEXT,
    ADD COLUMN IF NOT EXISTS guest_last_name  TEXT,
    ADD COLUMN IF NOT EXISTS guest_email      TEXT,
    ADD COLUMN IF NOT EXISTS guest_phone      TEXT;

CREATE INDEX IF NOT EXISTS idx_pms_bookings_guest_email
    ON pms_bookings (company_id, guest_email)
    WHERE guest_email IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_pms_bookings_guest_phone
    ON pms_bookings (company_id, guest_phone)
    WHERE guest_phone IS NOT NULL;
"""


DOWN_SQL = """
DROP INDEX IF EXISTS idx_pms_bookings_guest_email;
DROP INDEX IF EXISTS idx_pms_bookings_guest_phone;

ALTER TABLE pms_bookings
    DROP COLUMN IF EXISTS guest_first_name,
    DROP COLUMN IF EXISTS guest_last_name,
    DROP COLUMN IF EXISTS guest_email,
    DROP COLUMN IF EXISTS guest_phone;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
