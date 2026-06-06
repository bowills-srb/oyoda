"""027_messaging_architecture

Introduces the unified messaging data model described in
docs/MESSAGING_ARCHITECTURE.md. This is a purely additive migration —
existing tables (pre_booking_inquiries, concierge_guest_sessions,
concierge_messages, concierge_escalations) are untouched and keep
working. The new tables give us a channel-agnostic conversation model
that spans pre-booking, in-stay, and post-stay with per-property AI
autonomy controls.

Tables added:

  conversations            One per guest identity. Spans multiple bookings
                           (group bookings = 1 conversation w/ N bookings).
                           Stage derived from current booking dates.

  conversation_bookings    Each booking attached to a conversation. Zero
                           bookings = pre-booking inquiry. 2+ bookings =
                           group booking (coordinator renting a block).

  channels                 Connected inbound/outbound endpoints per
                           operator. Gmail, Outlook, PMS messaging APIs
                           (Guesty/Track/Hostaway), RCS, SMS, web chat.

  messages                 Channel-agnostic inbound/outbound messages.
                           Every message has a channel_id and channel_ref
                           for reply routing.

  drafts                   AI-generated reply candidates. Status flow:
                           pending_review -> approved/edited/rejected/auto_sent.
                           approval_mode captured at draft time for audit
                           (so operator autonomy changes don't rewrite history).

  property_ai_autonomy     Per-property, per-stage review-vs-auto toggle.
                           MVP has one row per property with stage='all';
                           future migration will split per-stage.

  conversation_escalations Channel-aware escalations that replace the
                           session-token-scoped concierge_escalations for
                           new conversations. Legacy escalations keep
                           working through concierge_escalations.

Migration strategy:
  Non-breaking. Existing code paths continue. Gmail poller adds a
  dual-write shim (in the code layer, not here) so new inbound messages
  land in both old tables (pre_booking_inquiries) and new tables
  (conversations + messages + drafts). A backfill script will populate
  historical rows. Once all read paths are migrated to the new tables,
  dual-write is removed and old tables archived (not in this migration).

Revision ID: 027_messaging_architecture
Revises: 026_dashboard_tables
"""

from alembic import op
import sqlalchemy as sa


revision = "027_messaging_architecture"
down_revision = "026_dashboard_tables"
branch_labels = None
depends_on = None


UP_SQL = """
-- ═════════════════════════════════════════════════════════════════════════
-- conversations — one per guest identity
-- ═════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id              UUID NOT NULL,

    -- Guest identity (any field can resolve a guest to this conversation)
    guest_email            TEXT,
    guest_phone            TEXT,
    guest_name             TEXT,
    pms_guest_id           TEXT,

    -- Lifecycle
    stage                  TEXT NOT NULL DEFAULT 'pre_booking',
        -- pre_booking | booked_pre_arrival | in_stay | post_stay | archived
    stage_derived_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status                 TEXT NOT NULL DEFAULT 'active',
        -- active | archived

    -- Current primary booking context (denormalized from conversation_bookings
    -- for fast list queries; conversation_bookings is source of truth)
    current_booking_id     UUID,
    current_property_id    UUID REFERENCES properties(id),
    current_check_in       DATE,
    current_check_out      DATE,

    -- Metadata
    first_message_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_message_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT conv_stage_valid CHECK (stage IN (
        'pre_booking', 'booked_pre_arrival', 'in_stay', 'post_stay', 'archived'
    )),
    CONSTRAINT conv_status_valid CHECK (status IN ('active', 'archived'))
);

CREATE INDEX IF NOT EXISTS idx_conv_tenant_stage
    ON conversations (tenant_id, stage, last_message_at DESC);
CREATE INDEX IF NOT EXISTS idx_conv_tenant_status
    ON conversations (tenant_id, status, last_message_at DESC);
CREATE INDEX IF NOT EXISTS idx_conv_email
    ON conversations (tenant_id, LOWER(guest_email))
    WHERE guest_email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conv_phone
    ON conversations (tenant_id, guest_phone)
    WHERE guest_phone IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conv_pms_guest
    ON conversations (tenant_id, pms_guest_id)
    WHERE pms_guest_id IS NOT NULL;


-- ═════════════════════════════════════════════════════════════════════════
-- conversation_bookings — one row per booking attached to a conversation
-- ═════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS conversation_bookings (
    booking_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id        UUID NOT NULL
        REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    tenant_id              UUID NOT NULL,

    -- Property linkage — property_id is FK, property_external_id is fallback
    -- when the PMS ref hasn't been resolved to an internal property row yet
    property_id            UUID REFERENCES properties(id),
    property_external_id   TEXT,

    -- PMS reference — external reservation ID (Escapia, Guesty, Vrbo, etc.)
    pms_booking_id         TEXT,
    booking_channel        TEXT,  -- vrbo | airbnb | direct | escapia | ...

    -- Dates + party
    check_in               DATE NOT NULL,
    check_out              DATE NOT NULL,
    num_guests             INTEGER,

    -- Lifecycle
    status                 TEXT NOT NULL DEFAULT 'confirmed',
        -- confirmed | cancelled | completed | pending

    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT cb_status_valid CHECK (status IN (
        'confirmed', 'cancelled', 'completed', 'pending'
    )),
    CONSTRAINT cb_dates_valid CHECK (check_out >= check_in)
);

CREATE INDEX IF NOT EXISTS idx_cb_conv
    ON conversation_bookings (conversation_id, check_in);
CREATE INDEX IF NOT EXISTS idx_cb_pms_booking
    ON conversation_bookings (tenant_id, pms_booking_id)
    WHERE pms_booking_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cb_property_dates
    ON conversation_bookings (property_id, check_in, check_out)
    WHERE property_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_cb_pms_booking_per_tenant
    ON conversation_bookings (tenant_id, pms_booking_id)
    WHERE pms_booking_id IS NOT NULL;


-- ═════════════════════════════════════════════════════════════════════════
-- channels — connected inbound/outbound endpoints per operator
-- ═════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS channels (
    channel_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id              UUID NOT NULL,
    channel_type           TEXT NOT NULL,
        -- gmail | outlook | pms_guesty | pms_track | pms_hostaway
        -- | pms_escapia_workaround | rcs | sms | web_chat | voice
    display_name           TEXT,  -- "Lanier's Gmail", "Guesty Messaging"

    -- Encrypted credentials (refresh tokens, API keys). App layer encrypts
    -- before insert; DB stores ciphertext. Empty {} until configured.
    credentials            JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Direction flags — some channels are inbound-only (forwarded email),
    -- some are outbound-only (RCS broadcast), most are both.
    inbound_enabled        BOOLEAN NOT NULL DEFAULT TRUE,
    outbound_enabled       BOOLEAN NOT NULL DEFAULT TRUE,

    status                 TEXT NOT NULL DEFAULT 'active',
        -- active | error | disabled

    last_polled_at         TIMESTAMPTZ,
    last_error             TEXT,
    config                 JSONB NOT NULL DEFAULT '{}'::jsonb,
        -- channel-specific config (poll interval, label filter, etc.)

    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ch_status_valid CHECK (status IN ('active', 'error', 'disabled'))
);

CREATE INDEX IF NOT EXISTS idx_ch_tenant_status
    ON channels (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_ch_type
    ON channels (tenant_id, channel_type);


-- ═════════════════════════════════════════════════════════════════════════
-- messages — channel-agnostic inbound/outbound messages
-- ═════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS messages (
    message_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id        UUID NOT NULL
        REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    channel_id             UUID REFERENCES channels(channel_id),
        -- Nullable until we backfill channel rows; new code paths must set it.

    direction              TEXT NOT NULL,
        -- inbound | outbound

    body                   TEXT NOT NULL,
    subject                TEXT,  -- email-style, nullable for SMS/RCS

    -- Channel-specific reference for reply routing. Shape depends on channel:
    --   gmail:    {thread_id, message_id, in_reply_to}
    --   guesty:   {conversation_id, message_id}
    --   rcs/sms:  {provider_message_id}
    channel_reference      JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Who sent it (internal attribution; guest-facing identity is always
    -- the operator company name)
    author                 TEXT,
        -- 'guest' | 'ai' | '<team_member_email>'

    -- Reply linkage — points to the message this one responds to
    in_reply_to_message_id UUID REFERENCES messages(message_id),

    -- AI processing (on inbound messages that triggered draft generation)
    detected_intent        TEXT,
    detected_urgency       TEXT,
    was_quick_answer       BOOLEAN,
    response_time_ms       INTEGER,

    -- Draft linkage (on outbound messages that came from a draft)
    draft_id               UUID,  -- forward ref; FK added after drafts table

    sent_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT msg_direction_valid CHECK (direction IN ('inbound', 'outbound'))
);

CREATE INDEX IF NOT EXISTS idx_msg_conv_sent
    ON messages (conversation_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_msg_channel_ref
    ON messages USING GIN (channel_reference);
CREATE INDEX IF NOT EXISTS idx_msg_direction_created
    ON messages (direction, created_at DESC);


-- ═════════════════════════════════════════════════════════════════════════
-- drafts — AI-generated reply candidates
-- ═════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS drafts (
    draft_id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id            UUID NOT NULL
        REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    triggered_by_message_id    UUID NOT NULL
        REFERENCES messages(message_id),

    draft_text                 TEXT NOT NULL,
    intent                     TEXT NOT NULL DEFAULT 'general',
    confidence                 NUMERIC(4,3) NOT NULL DEFAULT 0,
    policy_flags               JSONB NOT NULL DEFAULT '[]'::jsonb,
    policy_warnings            JSONB NOT NULL DEFAULT '[]'::jsonb,

    status                     TEXT NOT NULL DEFAULT 'pending_review',
        -- pending_review | approved | edited | rejected | auto_sent | superseded
        -- | blocked_by_escalation (new: held because escalation was created)

    -- approval_mode captured AT DRAFT TIME so audit log is correct even if
    -- operator changes their autonomy setting later.
    approval_mode              TEXT NOT NULL DEFAULT 'required',
        -- required | auto

    send_decision              TEXT DEFAULT 'review',
        -- send_now | review | hold

    -- What actually went out (may differ from draft_text if operator edited)
    final_text                 TEXT,
    reviewed_by                TEXT,
    reviewed_at                TIMESTAMPTZ,
    sent_at                    TIMESTAMPTZ,
    sent_message_id            UUID REFERENCES messages(message_id),

    -- Escalation linkage — if the inbound message also triggered an
    -- escalation, the draft is held. escalation_blocking_id lets operators
    -- see WHY the draft is blocked. Cleared when escalation resolves or
    -- operator explicitly approves.
    escalation_blocking_id     UUID,  -- FK added after conversation_escalations

    -- Playbook hook — future migration adds response_playbooks table. This
    -- column is populated when a playbook trigger matched (e.g. "checkout
    -- tomorrow + no future booking -> offer 20% discount"). For v1 this
    -- stays NULL; playbook evaluation plugs in here without schema changes.
    playbook_triggered         TEXT,
    playbook_context           JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT draft_status_valid CHECK (status IN (
        'pending_review', 'approved', 'edited', 'rejected',
        'auto_sent', 'superseded', 'blocked_by_escalation'
    )),
    CONSTRAINT draft_approval_mode_valid CHECK (approval_mode IN ('required', 'auto'))
);

CREATE INDEX IF NOT EXISTS idx_draft_conv_created
    ON drafts (conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_draft_pending
    ON drafts (status) WHERE status = 'pending_review';
CREATE INDEX IF NOT EXISTS idx_draft_trigger
    ON drafts (triggered_by_message_id);

-- Now that drafts exists, back-fill the forward-reference FK on messages
ALTER TABLE messages
    ADD CONSTRAINT fk_msg_draft FOREIGN KEY (draft_id)
    REFERENCES drafts(draft_id) ON DELETE SET NULL;


-- ═════════════════════════════════════════════════════════════════════════
-- property_ai_autonomy — per-property AI review vs. auto-send
-- ═════════════════════════════════════════════════════════════════════════
-- MVP: one row per property with stage='all' (applies to every stage).
-- Future: split into per-stage rows (pre_booking, booked_pre_arrival,
-- in_stay, post_stay) for finer control. The PK already supports this.
CREATE TABLE IF NOT EXISTS property_ai_autonomy (
    property_id                UUID NOT NULL
        REFERENCES properties(id) ON DELETE CASCADE,
    tenant_id                  UUID NOT NULL,
    stage                      TEXT NOT NULL DEFAULT 'all',
        -- all | pre_booking | booked_pre_arrival | in_stay | post_stay

    approval_mode              TEXT NOT NULL DEFAULT 'required',
        -- required | auto

    -- Confidence required for auto-send. Default 0.95 is conservative.
    min_confidence_for_auto    NUMERIC(3,2) NOT NULL DEFAULT 0.95,

    -- Tracking for eligibility gating ("can this property go auto yet?")
    auto_enabled_at            TIMESTAMPTZ,
    auto_enabled_by            TEXT,

    -- Guardrails (future: enforce at toggle time). Shape:
    --   {"min_reviewed_drafts_last_7d": 10, "max_edits_pct": 0.20}
    guardrails                 JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (property_id, stage),

    CONSTRAINT paa_approval_mode_valid CHECK (approval_mode IN ('required', 'auto')),
    CONSTRAINT paa_stage_valid CHECK (stage IN (
        'all', 'pre_booking', 'booked_pre_arrival', 'in_stay', 'post_stay'
    )),
    CONSTRAINT paa_confidence_range CHECK (
        min_confidence_for_auto >= 0 AND min_confidence_for_auto <= 1
    )
);

CREATE INDEX IF NOT EXISTS idx_paa_tenant
    ON property_ai_autonomy (tenant_id);


-- ═════════════════════════════════════════════════════════════════════════
-- conversation_escalations — channel-aware escalations
-- ═════════════════════════════════════════════════════════════════════════
-- Legacy concierge_escalations (session-token-scoped) keeps working.
-- New escalations (pre-booking, multi-channel, etc.) use this table.
-- Both tables read by the Escalations view for a unified operator inbox.
CREATE TABLE IF NOT EXISTS conversation_escalations (
    escalation_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id            UUID NOT NULL
        REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    tenant_id                  UUID NOT NULL,

    -- The message that triggered the escalation (optional — could be a
    -- playbook-driven escalation with no triggering inbound)
    triggered_by_message_id    UUID REFERENCES messages(message_id),

    -- Which stage the conversation was in when this was raised (captured
    -- at creation; doesn't change if stage advances later)
    stage_at_creation          TEXT NOT NULL,

    -- Classification
    reason                     TEXT NOT NULL,
        -- refund_request | damage_claim | cancellation | emergency
        -- | ai_uncertainty | policy_question | off_topic | other
    priority                   TEXT NOT NULL DEFAULT 'medium',
        -- low | medium | high | critical
    status                     TEXT NOT NULL DEFAULT 'pending',
        -- pending | acknowledged | resolved

    summary                    TEXT,
    last_message               TEXT,

    -- Assignment + resolution
    assigned_to                TEXT,
    acknowledged_at            TIMESTAMPTZ,
    resolved_at                TIMESTAMPTZ,
    resolution_notes           TEXT,

    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ce_priority_valid CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT ce_status_valid CHECK (status IN ('pending', 'acknowledged', 'resolved'))
);

CREATE INDEX IF NOT EXISTS idx_ce_tenant_status
    ON conversation_escalations (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ce_conv
    ON conversation_escalations (conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ce_trigger_msg
    ON conversation_escalations (triggered_by_message_id)
    WHERE triggered_by_message_id IS NOT NULL;

-- Back-fill draft FK now that the escalations table exists
ALTER TABLE drafts
    ADD CONSTRAINT fk_draft_escalation FOREIGN KEY (escalation_blocking_id)
    REFERENCES conversation_escalations(escalation_id) ON DELETE SET NULL;


-- ═════════════════════════════════════════════════════════════════════════
-- Keep conversations.current_booking_id in sync when conversation_bookings
-- changes. The denormalized fields on conversations drive fast list queries;
-- the source of truth stays in conversation_bookings.
-- ═════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION sync_conversation_current_booking()
RETURNS TRIGGER AS $$
BEGIN
    -- Pick the most relevant booking: prefer the currently-active (today
    -- between check_in and check_out), else the next upcoming, else the
    -- most recent past. Ignore cancelled.
    UPDATE conversations c
    SET
        current_booking_id  = b.booking_id,
        current_property_id = b.property_id,
        current_check_in    = b.check_in,
        current_check_out   = b.check_out,
        updated_at          = NOW()
    FROM (
        SELECT
            booking_id, property_id, check_in, check_out,
            conversation_id
        FROM conversation_bookings
        WHERE conversation_id = COALESCE(NEW.conversation_id, OLD.conversation_id)
          AND status != 'cancelled'
        ORDER BY
            CASE
                WHEN CURRENT_DATE BETWEEN check_in AND check_out THEN 0  -- in-stay
                WHEN check_in >= CURRENT_DATE THEN 1                      -- upcoming
                ELSE 2                                                    -- past
            END,
            ABS(EXTRACT(EPOCH FROM (check_in::timestamp - NOW())))::bigint
        LIMIT 1
    ) b
    WHERE c.conversation_id = b.conversation_id;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_sync_conversation_current_booking ON conversation_bookings;
CREATE TRIGGER tr_sync_conversation_current_booking
    AFTER INSERT OR UPDATE OR DELETE ON conversation_bookings
    FOR EACH ROW EXECUTE FUNCTION sync_conversation_current_booking();
"""


DOWN_SQL = """
-- Drop in reverse order of dependencies
DROP TRIGGER IF EXISTS tr_sync_conversation_current_booking ON conversation_bookings;
DROP FUNCTION IF EXISTS sync_conversation_current_booking();

ALTER TABLE drafts DROP CONSTRAINT IF EXISTS fk_draft_escalation;
ALTER TABLE messages DROP CONSTRAINT IF EXISTS fk_msg_draft;

DROP TABLE IF EXISTS conversation_escalations CASCADE;
DROP TABLE IF EXISTS property_ai_autonomy CASCADE;
DROP TABLE IF EXISTS drafts CASCADE;
DROP TABLE IF EXISTS messages CASCADE;
DROP TABLE IF EXISTS channels CASCADE;
DROP TABLE IF EXISTS conversation_bookings CASCADE;
DROP TABLE IF EXISTS conversations CASCADE;
"""


def upgrade():
    op.execute(UP_SQL)


def downgrade():
    op.execute(DOWN_SQL)
