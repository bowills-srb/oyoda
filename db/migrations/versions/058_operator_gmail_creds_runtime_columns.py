"""058_operator_gmail_creds_runtime_columns

Adopt runtime-created operator_gmail_creds heartbeat columns into Alembic.

These columns already exist in production today, but they are currently
created by runtime DDL inside
app/services/integrations/gmail_inbox_poller.py. This migration is
intentionally adoptive and idempotent: it uses IF NOT EXISTS so it
succeeds against the current live schema while also making future
environments Alembic-managed rather than runtime-managed.

Columns adopted:

  - last_polled_at
  - last_poll_success
  - last_poll_summary
  - last_poll_error
  - last_messages_found
  - last_new_pending_inquiries
  - last_query_mode

Revision ID: 058_operator_gmail_creds_runtime_columns
Revises: 057_canonical_property_runtime_tables_to_alembic
Create Date: 2026-05-08
"""

from alembic import op


revision = "058_operator_gmail_creds_runtime_columns"
down_revision = "057_canonical_property_runtime_tables_to_alembic"
branch_labels = None
depends_on = None


UP_STATEMENTS = [
    """
    ALTER TABLE operator_gmail_creds
    ADD COLUMN IF NOT EXISTS last_polled_at TIMESTAMPTZ
    """,
    """
    ALTER TABLE operator_gmail_creds
    ADD COLUMN IF NOT EXISTS last_poll_success BOOLEAN
    """,
    """
    ALTER TABLE operator_gmail_creds
    ADD COLUMN IF NOT EXISTS last_poll_summary TEXT
    """,
    """
    ALTER TABLE operator_gmail_creds
    ADD COLUMN IF NOT EXISTS last_poll_error TEXT
    """,
    """
    ALTER TABLE operator_gmail_creds
    ADD COLUMN IF NOT EXISTS last_messages_found INTEGER
    """,
    """
    ALTER TABLE operator_gmail_creds
    ADD COLUMN IF NOT EXISTS last_new_pending_inquiries INTEGER
    """,
    """
    ALTER TABLE operator_gmail_creds
    ADD COLUMN IF NOT EXISTS last_query_mode TEXT
    """,
]


DOWN_STATEMENTS = [
    """
    ALTER TABLE operator_gmail_creds
    DROP COLUMN IF EXISTS last_query_mode
    """,
    """
    ALTER TABLE operator_gmail_creds
    DROP COLUMN IF EXISTS last_new_pending_inquiries
    """,
    """
    ALTER TABLE operator_gmail_creds
    DROP COLUMN IF EXISTS last_messages_found
    """,
    """
    ALTER TABLE operator_gmail_creds
    DROP COLUMN IF EXISTS last_poll_error
    """,
    """
    ALTER TABLE operator_gmail_creds
    DROP COLUMN IF EXISTS last_poll_summary
    """,
    """
    ALTER TABLE operator_gmail_creds
    DROP COLUMN IF EXISTS last_poll_success
    """,
    """
    ALTER TABLE operator_gmail_creds
    DROP COLUMN IF EXISTS last_polled_at
    """,
]


def upgrade() -> None:
    # Railway re-runs `alembic upgrade head` during every deploy. Keep
    # adoptive migrations split into cheap idempotent statements so a
    # no-op re-run does not hit deploy-time statement timeouts.
    for statement in UP_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWN_STATEMENTS:
        op.execute(statement)
