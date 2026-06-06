"""036_message_normalizations

Canonical normalization records for inbound concierge messages.

This is additive and shadow-mode friendly:
  - does not change current operator read paths
  - links to the long-term messaging schema when present
  - preserves parser output + observability for later backfills and audits
"""

from alembic import op


revision = "036_message_normalizations"
down_revision = "035_operator_notification_recipients"
branch_labels = None
depends_on = None


UP_SQL = """
CREATE TABLE IF NOT EXISTS message_normalizations (
    normalization_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                   UUID NOT NULL,
    message_id                  UUID REFERENCES messages(message_id) ON DELETE SET NULL,

    source_channel              TEXT NOT NULL,
    source_provider             TEXT,
    source_thread_id            TEXT,
    source_message_id           TEXT NOT NULL,

    sender_role                 TEXT NOT NULL DEFAULT 'guest',
    sender_display_name         TEXT,
    sender_address              TEXT,
    sent_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    raw_subject                 TEXT,
    latest_guest_turn           TEXT NOT NULL,
    prior_thread_context        TEXT,
    full_message_text           TEXT,

    structured_asks             JSONB NOT NULL DEFAULT '[]'::jsonb,
    prior_operator_commitments  JSONB NOT NULL DEFAULT '[]'::jsonb,
    property_binding_candidates JSONB NOT NULL DEFAULT '[]'::jsonb,
    channel_constraints         JSONB NOT NULL DEFAULT '{}'::jsonb,

    selected_property_code      TEXT,
    selected_property_match_type TEXT,

    parser_used                 TEXT,
    parser_version              TEXT NOT NULL DEFAULT 'v1',
    parser_notes                JSONB NOT NULL DEFAULT '[]'::jsonb,
    latest_turn_confidence      NUMERIC(4,3),
    latest_turn_extracted       BOOLEAN NOT NULL DEFAULT FALSE,

    route_outcome               TEXT,
    draft_source                TEXT,
    fallback_reason             TEXT,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_message_norm_source
        UNIQUE (tenant_id, source_channel, source_message_id)
);

CREATE INDEX IF NOT EXISTS idx_msg_norm_tenant_sent
    ON message_normalizations (tenant_id, sent_at DESC);

CREATE INDEX IF NOT EXISTS idx_msg_norm_tenant_route
    ON message_normalizations (tenant_id, route_outcome, sent_at DESC);

CREATE INDEX IF NOT EXISTS idx_msg_norm_property_match
    ON message_normalizations (tenant_id, selected_property_code, selected_property_match_type);
"""


DOWN_SQL = """
DROP TABLE IF EXISTS message_normalizations CASCADE;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
