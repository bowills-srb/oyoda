"""039_operator_prebooking_queue_read_models

Persisted queue/read model for operator pre-booking inbox surfaces.
"""

from alembic import op


revision = "039_operator_prebooking_queue_read_models"
down_revision = "038_operator_dashboard_read_models"
branch_labels = None
depends_on = None


UP_SQL = """
CREATE TABLE IF NOT EXISTS operator_prebooking_queue_read_models (
    queue_item_id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                     UUID NOT NULL,
    draft_id                      TEXT NOT NULL,
    thread_id                     TEXT,
    source_message_id             TEXT,

    platform                      TEXT NOT NULL DEFAULT 'email',
    source_provider               TEXT,

    guest_name                    TEXT NOT NULL DEFAULT 'Guest',
    guest_email                   TEXT,
    message_text                  TEXT NOT NULL DEFAULT '',
    latest_guest_turn             TEXT NOT NULL DEFAULT '',
    prior_thread_context          TEXT,
    draft_text                    TEXT NOT NULL DEFAULT '',
    final_reply                   TEXT,

    intent                        TEXT NOT NULL DEFAULT 'general',
    asks_json                     JSONB NOT NULL DEFAULT '[]'::jsonb,
    policy_flags                  JSONB NOT NULL DEFAULT '[]'::jsonb,
    policy_warnings               JSONB NOT NULL DEFAULT '[]'::jsonb,
    prior_operator_commitments    JSONB NOT NULL DEFAULT '[]'::jsonb,

    property_external_id          TEXT NOT NULL DEFAULT '',
    property_name                 TEXT,
    property_binding_candidates   JSONB NOT NULL DEFAULT '[]'::jsonb,
    selected_property_code        TEXT,
    property_match_type           TEXT,

    route_outcome                 TEXT,
    draft_source                  TEXT,
    fallback_reason               TEXT,

    confidence                    NUMERIC(4,3) DEFAULT 0,
    latest_turn_confidence        NUMERIC(4,3),
    latest_turn_extracted         BOOLEAN NOT NULL DEFAULT FALSE,

    queue_status                  TEXT NOT NULL DEFAULT 'pending_review',
    review_status                 TEXT NOT NULL DEFAULT 'pending_review',
    assignment_status             TEXT NOT NULL DEFAULT 'unassigned',
    assigned_operator_id          UUID,
    assigned_team_key             TEXT,
    portfolio_key                 TEXT,

    received_at                   TIMESTAMPTZ,
    replied_at                    TIMESTAMPTZ,
    refreshed_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_operator_prebooking_queue UNIQUE (tenant_id, draft_id)
);

CREATE INDEX IF NOT EXISTS idx_prebooking_queue_tenant_received
    ON operator_prebooking_queue_read_models (tenant_id, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_prebooking_queue_tenant_status
    ON operator_prebooking_queue_read_models (tenant_id, review_status, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_prebooking_queue_tenant_property
    ON operator_prebooking_queue_read_models (tenant_id, property_external_id, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_prebooking_queue_assignment
    ON operator_prebooking_queue_read_models (tenant_id, assignment_status, assigned_team_key, assigned_operator_id);
"""


DOWN_SQL = """
DROP TABLE IF EXISTS operator_prebooking_queue_read_models CASCADE;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
