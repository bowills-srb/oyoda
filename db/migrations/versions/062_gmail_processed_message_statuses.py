"""062_gmail_processed_message_statuses

Track terminal and retryable inbox-processing outcomes so dead-end
messages stop re-triggering LLM parsing forever.
"""

from alembic import op


revision = "062_gmail_processed_message_statuses"
down_revision = "061_extraction_staging"
branch_labels = None
depends_on = None


UP_STATEMENTS = [
    """
    ALTER TABLE gmail_processed_messages
        ADD COLUMN IF NOT EXISTS processing_status TEXT NOT NULL DEFAULT 'processed'
    """,
    """
    ALTER TABLE gmail_processed_messages
        ADD COLUMN IF NOT EXISTS failure_count INTEGER NOT NULL DEFAULT 0
    """,
    """
    ALTER TABLE gmail_processed_messages
        ADD COLUMN IF NOT EXISTS last_failure_reason TEXT
    """,
    """
    ALTER TABLE gmail_processed_messages
        ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    """,
    """
    ALTER TABLE gmail_processed_messages
        ADD COLUMN IF NOT EXISTS last_attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_gmail_processed_op_status
        ON gmail_processed_messages (operator_id, processing_status, processed_at DESC)
    """,
]


DOWN_STATEMENTS = [
    "DROP INDEX IF EXISTS idx_gmail_processed_op_status",
    "ALTER TABLE gmail_processed_messages DROP COLUMN IF EXISTS last_attempted_at",
    "ALTER TABLE gmail_processed_messages DROP COLUMN IF EXISTS first_seen_at",
    "ALTER TABLE gmail_processed_messages DROP COLUMN IF EXISTS last_failure_reason",
    "ALTER TABLE gmail_processed_messages DROP COLUMN IF EXISTS failure_count",
    "ALTER TABLE gmail_processed_messages DROP COLUMN IF EXISTS processing_status",
]


def upgrade() -> None:
    for statement in UP_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWN_STATEMENTS:
        op.execute(statement)
