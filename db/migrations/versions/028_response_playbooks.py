"""028_response_playbooks

Adds operator-trainable playbook tables on top of the messaging architecture
from migration 027. Operators can explicitly teach the AI things like:

  "If a guest asks about extending their stay on a checkout day with no
  booking behind them, offer 20 percent off the extra night."

These supplement (don't replace) the self-learning LEARN layer.

Three kinds of playbooks, discriminated by `kind`:

  faq_rule          "If guest asks about X, the answer is Y."
                    Augments the KB during draft generation.

  conditional_rule  "If [condition] then [action]."
                    The 20-percent-discount example.
                    Action kinds: offer_template | draft_injection
                                  | escalation | no_op.

  proactive_touch   Scheduled outbound keyed to booking timeline offset
                    plus optional external conditions (weather, events,
                    beach flags). Materialized into scheduled_touchpoints
                    when a booking is created/updated.

scheduled_touchpoints is the queue table the send worker reads. It gets
populated by the scheduler (which walks proactive_touch playbooks against
conversation_bookings) and drained by the send worker.

Revision ID: 028_response_playbooks
Revises: 027_messaging_architecture
"""

from alembic import op


revision = "028_response_playbooks"
down_revision = "027_messaging_architecture"
branch_labels = None
depends_on = None


UP_SQL = """
-- Operator-trained rules + proactive touchpoints
CREATE TABLE IF NOT EXISTS response_playbooks (
    playbook_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id              UUID NOT NULL,
    kind                   TEXT NOT NULL,
        -- faq_rule | conditional_rule | proactive_touch
    name                   TEXT NOT NULL,
    description            TEXT,

    -- Natural-language form the operator typed. Kept verbatim so the
    -- operator can re-edit even after parsing.
    operator_text          TEXT NOT NULL,

    -- Parsed, structured form. Shape depends on kind:
    --   faq_rule:         {trigger: {intent, keywords}, answer: "..."}
    --   conditional_rule: {when: {stage, booking_condition, timing},
    --                      then: {action_type, template, params}}
    --   proactive_touch:  {schedule: {offset_hours, relative_to},
    --                      conditions: [...], template: "..."}
    trigger                JSONB NOT NULL DEFAULT '{}'::jsonb,
    action                 JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Scope: [] = applies to all properties for this tenant
    property_ids           JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Lifecycle
    active                 BOOLEAN NOT NULL DEFAULT TRUE,
    created_by             TEXT,
    last_triggered_at      TIMESTAMPTZ,
    trigger_count          INTEGER NOT NULL DEFAULT 0,

    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT pb_kind_valid CHECK (kind IN (
        'faq_rule', 'conditional_rule', 'proactive_touch'
    ))
);

CREATE INDEX IF NOT EXISTS idx_pb_tenant_kind_active
    ON response_playbooks (tenant_id, kind, active);
CREATE INDEX IF NOT EXISTS idx_pb_tenant_active
    ON response_playbooks (tenant_id, active) WHERE active = TRUE;


-- Materialized instances of proactive_touch playbooks
CREATE TABLE IF NOT EXISTS scheduled_touchpoints (
    touchpoint_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id              UUID NOT NULL,
    conversation_id        UUID NOT NULL
        REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    booking_id             UUID
        REFERENCES conversation_bookings(booking_id) ON DELETE CASCADE,
    playbook_id            UUID NOT NULL
        REFERENCES response_playbooks(playbook_id) ON DELETE CASCADE,

    -- When it should fire
    fire_at                TIMESTAMPTZ NOT NULL,

    -- Rendered from template + booking context at send time
    rendered_body          TEXT,

    -- Lifecycle
    status                 TEXT NOT NULL DEFAULT 'pending',
        -- pending | sent | cancelled | superseded
    sent_message_id        UUID REFERENCES messages(message_id),
    sent_at                TIMESTAMPTZ,
    cancelled_reason       TEXT,

    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT st_status_valid CHECK (status IN (
        'pending', 'sent', 'cancelled', 'superseded'
    ))
);

CREATE INDEX IF NOT EXISTS idx_st_fire
    ON scheduled_touchpoints (status, fire_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_st_conv
    ON scheduled_touchpoints (conversation_id, fire_at);
CREATE INDEX IF NOT EXISTS idx_st_booking
    ON scheduled_touchpoints (booking_id) WHERE booking_id IS NOT NULL;
"""


DOWN_SQL = """
DROP TABLE IF EXISTS scheduled_touchpoints CASCADE;
DROP TABLE IF EXISTS response_playbooks CASCADE;
"""


def upgrade():
    op.execute(UP_SQL)


def downgrade():
    op.execute(DOWN_SQL)
