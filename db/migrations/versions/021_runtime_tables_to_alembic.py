"""Move remaining startup-created tables into Alembic-managed schema.

Revision ID: 021_runtime_tables_to_alembic
Revises: 020_merge_branches
"""

from alembic import op


revision = "021_runtime_tables_to_alembic"
down_revision = "020_merge_branches"
branch_labels = None
depends_on = None


SQL = """
-- ─────────────────────────────────────────────────────────────────────────────
-- Gmail inbox dedup + thread metadata
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS gmail_processed_messages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    gmail_message_id    TEXT NOT NULL,
    rfc_message_id      TEXT,
    operator_id         TEXT NOT NULL,
    processed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (gmail_message_id)
);

CREATE INDEX IF NOT EXISTS idx_gmail_processed_op
    ON gmail_processed_messages (operator_id, processed_at DESC);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'pre_booking_inquiries'
                     AND column_name = 'gmail_thread_id') THEN
        ALTER TABLE pre_booking_inquiries
            ADD COLUMN gmail_thread_id  TEXT,
            ADD COLUMN gmail_message_id TEXT,
            ADD COLUMN guest_email      TEXT,
            ADD COLUMN reply_via_gmail  BOOLEAN DEFAULT FALSE;
    END IF;
END $$;

-- ─────────────────────────────────────────────────────────────────────────────
-- Group session membership
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS guest_group_members (
    member_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID NOT NULL REFERENCES concierge_guest_sessions(session_id)
                            ON DELETE CASCADE,
    tenant_id           UUID NOT NULL,
    phone_number        TEXT NOT NULL,
    display_name        TEXT NOT NULL DEFAULT 'Guest',
    role                TEXT NOT NULL DEFAULT 'guest',
    message_count       INTEGER NOT NULL DEFAULT 0,
    last_message_at     TIMESTAMPTZ,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    joined_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uix_group_member_session_phone
    ON guest_group_members (session_id, phone_number);

CREATE INDEX IF NOT EXISTS idx_group_member_phone
    ON guest_group_members (phone_number)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_group_member_session
    ON guest_group_members (session_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'concierge_guest_sessions'
          AND column_name = 'group_join_token'
    ) THEN
        ALTER TABLE concierge_guest_sessions
            ADD COLUMN group_join_token TEXT UNIQUE;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'concierge_guest_sessions'
          AND column_name = 'group_member_count'
    ) THEN
        ALTER TABLE concierge_guest_sessions
            ADD COLUMN group_member_count INTEGER NOT NULL DEFAULT 0;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_sessions_join_token
    ON concierge_guest_sessions (group_join_token)
    WHERE group_join_token IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- Neighborhood source cache
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS neighborhood_sources (
    id                BIGSERIAL PRIMARY KEY,
    source_key        TEXT UNIQUE NOT NULL,
    neighborhood      TEXT NOT NULL,
    neighborhood_slug TEXT NOT NULL,
    market_id         TEXT NOT NULL,
    url               TEXT NOT NULL,
    domain            TEXT NOT NULL,
    label             TEXT,
    confidence        FLOAT DEFAULT 0.0,
    has_jsonld        BOOLEAN DEFAULT FALSE,
    has_event_cards   BOOLEAN DEFAULT FALSE,
    event_count_estimate INT DEFAULT 0,
    discovered_at     TIMESTAMPTZ DEFAULT NOW(),
    last_probed_at    TIMESTAMPTZ DEFAULT NOW(),
    is_valid          BOOLEAN DEFAULT TRUE,
    metadata          JSONB DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_neighborhood_sources_market
    ON neighborhood_sources (market_id);

CREATE INDEX IF NOT EXISTS idx_neighborhood_sources_slug
    ON neighborhood_sources (market_id, neighborhood_slug);
"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS neighborhood_sources CASCADE;")
    op.execute("DROP TABLE IF EXISTS guest_group_members CASCADE;")
    op.execute("DROP TABLE IF EXISTS gmail_processed_messages CASCADE;")
