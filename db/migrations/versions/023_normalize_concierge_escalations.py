"""Normalize concierge_escalations to the Alembic-managed schema.

The live table has ticket_id as UUID type but the app expects VARCHAR(50).
Since the table is empty in production, we drop and recreate cleanly.

Revision ID: 023_normalize_concierge_escalations
Revises: 022_merge_all_heads
"""

from alembic import op

revision = "023_normalize_concierge_escalations"
down_revision = "022_merge_all_heads"
branch_labels = None
depends_on = None

# Drop and recreate — table is empty in production so no data loss.
# This gives us a clean schema the app code expects.
UP_SQL = """
DROP TABLE IF EXISTS concierge_escalations CASCADE;

CREATE TABLE concierge_escalations (
    ticket_id             VARCHAR(50) PRIMARY KEY,
    session_token         VARCHAR(50) NOT NULL,
    guest_name            VARCHAR(255) NOT NULL,
    guest_phone           VARCHAR(50),
    guest_email           VARCHAR(255),
    property_name         VARCHAR(255) NOT NULL,
    property_code         VARCHAR(100) NOT NULL,
    reason                VARCHAR(50) NOT NULL,
    priority              VARCHAR(20) NOT NULL,
    status                VARCHAR(20) NOT NULL DEFAULT 'pending',
    summary               TEXT NOT NULL DEFAULT '',
    last_message          TEXT,
    conversation_history  JSONB NOT NULL DEFAULT '[]'::jsonb,
    assigned_to           VARCHAR(255),
    resolution_notes      TEXT,
    acknowledged_at       TIMESTAMPTZ,
    resolved_at           TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_escalation_session_token
    ON concierge_escalations (session_token);
CREATE INDEX ix_escalation_status_priority
    ON concierge_escalations (status, priority);
CREATE INDEX ix_escalation_property
    ON concierge_escalations (property_code);
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    pass
