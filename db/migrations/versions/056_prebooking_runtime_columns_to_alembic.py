"""056_prebooking_runtime_columns_to_alembic

Adopt runtime-created pre_booking_inquiries columns into Alembic.

These columns already exist in production, but they are not currently
represented in db/migrations/versions/. This migration is intentionally
adoptive and idempotent: it uses IF NOT EXISTS so it succeeds both
against the current live schema and against future environments where
the runtime DDL has been removed.

Columns adopted:

  - parser_source TEXT NULL
  - extracted_asks JSONB NULL DEFAULT '[]'::jsonb
  - platform_listing_id TEXT NULL
  - platform_unit_id TEXT NULL

Revision ID: 056_prebooking_runtime_columns_to_alembic
Revises: 055_concierge_escalation_sla_flags
Create Date: 2026-05-07
"""

from alembic import op


revision = "056_prebooking_runtime_columns_to_alembic"
down_revision = "055_concierge_escalation_sla_flags"
branch_labels = None
depends_on = None


UP_SQL = """
ALTER TABLE pre_booking_inquiries
    ADD COLUMN IF NOT EXISTS parser_source TEXT,
    ADD COLUMN IF NOT EXISTS extracted_asks JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS platform_listing_id TEXT,
    ADD COLUMN IF NOT EXISTS platform_unit_id TEXT;
"""


DOWN_SQL = """
ALTER TABLE pre_booking_inquiries
    DROP COLUMN IF EXISTS platform_unit_id,
    DROP COLUMN IF EXISTS platform_listing_id,
    DROP COLUMN IF EXISTS extracted_asks,
    DROP COLUMN IF EXISTS parser_source;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
