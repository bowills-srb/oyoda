"""018_pre_booking_pipeline.py

Single migration covering every table the pre-booking pipeline depends on.
Run this before starting the Celery workers or the first Escapia sync.

Execution order matters — tables with foreign keys come after their parents.

Tables created:
  1.  companies                         — operator identity (if not exists)
  2.  operator_feature_flags            — staged rollout gates
  3.  pms_listings                      — Escapia property records (keyed to external_id)
  4.  pms_bookings                      — confirmed reservation records
  5.  operator_sync_log                 — PMS sync audit trail
  6.  listing_id_aliases                — handles renamed/migrated listing IDs
  7.  escapia_message_history           — full historical message archive
  8.  message_orphan_queue              — unresolvable listing IDs awaiting resolution
  9.  pre_booking_inquiries             — inquiry drafts, approval workflow, learning signal
  10. operator_pre_booking_policies     — per-operator auto-send configuration
  11. property_rollout_phases           — staged rollout phase tracker
  12. property_rollout_history          — phase transition audit trail
  13. operator_learned_preferences      — distilled AI behavior preferences
  14. operator_draft_events             — raw edit event log
  15. platform_learning_events          — anonymized cross-operator signal
  16. platform_intelligence             — nightly aggregated market intelligence
  17. gate_code_deliveries              — gate code delivery audit log
  18. operator_alert_contacts           — who gets which alert type
  19. operator_alert_acks               — escalation chain ack tracking
  20. operator_alert_log                — alert message text for re-send on escalation

Columns added to existing tables:
  - concierge_guest_sessions: property_external_id, booking_channel,
                              guest_count (if missing), gate_code_last_requested
  - pre_booking_inquiries:    resolution_note, send_decision

Fields explained inline below.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "018_pre_booking_pipeline"
down_revision = "017"
branch_labels = None
depends_on = None

SQL = """

-- =============================================================================
-- 1. COMPANIES
--    The operator identity record. One row per onboarded STR operator.
--    company_id is the UUID used everywhere else as the tenant anchor.
-- =============================================================================
CREATE TABLE IF NOT EXISTS companies (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             TEXT NOT NULL,                 -- "Gulf View Rentals LLC"
    code             TEXT UNIQUE,                   -- Short slug used in URLs
    concierge_name   TEXT DEFAULT 'Coral',          -- AI persona name
    support_phone    TEXT,                          -- Operator's guest-facing support number
    support_email    TEXT,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =============================================================================
-- 2. OPERATOR FEATURE FLAGS
--    Controls which features are live for which property/operator.
--    The staged rollout system writes to this table when a phase is entered.
--    The pre-booking pipeline reads it before processing any message.
--
--    Key flags used by pre-booking:
--      oyvoda_enabled        — master switch; if FALSE nothing runs
--      pre_booking_ai        — AI drafting active for this property
--      pre_booking_single    — single-shot mode; cleared after first use
-- =============================================================================
CREATE TABLE IF NOT EXISTS operator_feature_flags (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID,                          -- NULL = platform-wide default
    property_code   TEXT,                          -- NULL = all properties for this operator
    flag_name       TEXT NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT FALSE,
    enabled_at      TIMESTAMPTZ,
    enabled_by      TEXT,                          -- 'operator' | 'admin' | 'rollout_system'
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One row per (company, property, flag) combination.
    -- NULLS NOT DISTINCT treats two NULLs as equal for the unique constraint.
    CONSTRAINT uq_operator_feature_flags
        UNIQUE NULLS NOT DISTINCT (company_id, property_code, flag_name)
);

CREATE INDEX IF NOT EXISTS idx_flags_company
    ON operator_feature_flags (company_id, flag_name);
CREATE INDEX IF NOT EXISTS idx_flags_property
    ON operator_feature_flags (property_code, flag_name);


-- =============================================================================
-- 3. PMS LISTINGS
--    One row per Escapia listing. external_id is the Escapia listing ID —
--    this is the stable anchor used everywhere. Property names change; IDs don't.
--
--    Populated by: pms_ingest_worker.run_pms_ingest()
--    Read by: inquiry polling task (to load property_data for AI draft)
--             gate code service (property_external_id lookup)
--             stale detector (thread → listing resolution)
-- =============================================================================
CREATE TABLE IF NOT EXISTS pms_listings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL,
    external_id     TEXT NOT NULL,                 -- Escapia listing ID (stable)
    pms_provider    TEXT NOT NULL DEFAULT 'escapia',

    -- Location
    property_name   TEXT,
    address_line1   TEXT,
    address_line2   TEXT,
    city            TEXT,
    state           TEXT,
    postal_code     TEXT,
    country         TEXT DEFAULT 'US',
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,

    -- Property details used by AI draft generator
    bedrooms        INTEGER DEFAULT 0,
    bathrooms       NUMERIC(4,1) DEFAULT 0,
    max_guests      INTEGER,                       -- For group_size policy check
    square_footage  INTEGER,
    property_type   TEXT DEFAULT 'single_family',

    -- Amenities used by AI draft for amenity inquiries
    has_pool        BOOLEAN DEFAULT FALSE,
    pool_heated     BOOLEAN DEFAULT FALSE,         -- Relevant for pool_heat upsell
    has_hot_tub     BOOLEAN DEFAULT FALSE,
    has_waterfront  BOOLEAN DEFAULT FALSE,
    waterfront_type TEXT,                          -- gulf | ocean | lake | bay
    beach_access    TEXT,                          -- private | public | none
    pet_friendly    BOOLEAN DEFAULT FALSE,         -- Drives pet_policy flag in policy checker
    has_garage      BOOLEAN DEFAULT FALSE,
    has_ev_charger  BOOLEAN DEFAULT FALSE,
    has_game_room   BOOLEAN DEFAULT FALSE,
    has_home_theater BOOLEAN DEFAULT FALSE,

    -- Status
    is_active       BOOLEAN DEFAULT TRUE,
    listing_status  TEXT DEFAULT 'active',
    last_synced_at  TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (company_id, external_id, pms_provider)
);

CREATE INDEX IF NOT EXISTS idx_listings_company
    ON pms_listings (company_id, is_active);


-- =============================================================================
-- 4. PMS BOOKINGS
--    Confirmed reservations. Used to:
--      - create concierge sessions for arriving guests
--      - check extend-stay eligibility (next_guest arriving?)
--      - gate code window validation (check_in / check_out dates)
-- =============================================================================
CREATE TABLE IF NOT EXISTS pms_bookings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL,
    listing_id      UUID REFERENCES pms_listings(id),  -- Internal FK
    external_id     TEXT NOT NULL,                     -- Escapia reservation ID
    external_listing_id TEXT,                           -- Escapia listing ID (pre-join)

    check_in        DATE NOT NULL,
    check_out       DATE NOT NULL,
    nights          INTEGER NOT NULL DEFAULT 1,

    total_amount    NUMERIC(10,2),
    nightly_rate    NUMERIC(10,2),
    cleaning_fee    NUMERIC(10,2),
    taxes           NUMERIC(10,2),

    guest_count     INTEGER DEFAULT 1,
    booking_channel TEXT DEFAULT 'direct',            -- vrbo | airbnb | direct
    status          TEXT DEFAULT 'confirmed',

    booked_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (company_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_bookings_checkin
    ON pms_bookings (company_id, check_in)
    WHERE status = 'confirmed';


-- =============================================================================
-- 5. OPERATOR SYNC LOG
--    Written after every PMS ingest run (success or failure).
--    Used by: GET /operators/{id}/sync-status endpoint
-- =============================================================================
CREATE TABLE IF NOT EXISTS operator_sync_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL,
    provider        TEXT NOT NULL,
    success         BOOLEAN NOT NULL,
    listings_synced INTEGER DEFAULT 0,
    bookings_synced INTEGER DEFAULT 0,
    error_message   TEXT,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =============================================================================
-- 6. LISTING ID ALIASES
--    Maps old/alternative Escapia listing IDs to the canonical external_id.
--    Created automatically when a fuzzy match resolves a listing.
--    Prevents the same fuzzy-match work on every poll cycle.
-- =============================================================================
CREATE TABLE IF NOT EXISTS listing_id_aliases (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id           UUID NOT NULL,
    alias_external_id    TEXT NOT NULL,    -- Incoming (possibly old or formatted differently)
    canonical_external_id TEXT NOT NULL,  -- Matches pms_listings.external_id
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, alias_external_id)
);


-- =============================================================================
-- 7. ESCAPIA MESSAGE HISTORY
--    Full historical archive of all Escapia messages per listing.
--    Anchored to listing_external_id (NOT property_name — names change).
--
--    Populated by: HistoricalMessageImporter on first sync
--    Read by:      knowledge_service for FAQ signal extraction
--                  stale detector (was this thread already answered?)
--                  AI draft generator (historical context)
-- =============================================================================
CREATE TABLE IF NOT EXISTS escapia_message_history (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id           TEXT NOT NULL,
    thread_id            TEXT NOT NULL,
    company_id           UUID NOT NULL,

    -- THE STABLE ANCHOR. Never use property_name here.
    listing_external_id  TEXT NOT NULL,

    direction            TEXT NOT NULL DEFAULT 'guest_to_host',
    -- guest_to_host | host_to_guest | system

    sender_name          TEXT,
    body                 TEXT NOT NULL,
    platform             TEXT NOT NULL DEFAULT 'unknown',
    -- vrbo | airbnb | homeaway | direct | unknown

    reservation_id       TEXT,          -- Escapia reservation ID if post-booking message

    -- Processing state
    status               TEXT NOT NULL DEFAULT 'historical',
    -- historical | pending | draft_ready | replied | already_answered | superseded | orphaned

    our_draft_id         TEXT,          -- FK to pre_booking_inquiries.draft_id if we drafted
    resolution_note      TEXT,

    sent_at              TIMESTAMPTZ NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (message_id, listing_external_id)
);

CREATE INDEX IF NOT EXISTS idx_msg_history_listing
    ON escapia_message_history (listing_external_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_msg_history_thread
    ON escapia_message_history (thread_id, sent_at);
CREATE INDEX IF NOT EXISTS idx_msg_history_company
    ON escapia_message_history (company_id, status, created_at DESC);


-- =============================================================================
-- 8. MESSAGE ORPHAN QUEUE
--    Any message whose listing_id doesn't match a known pms_listings row.
--    Operator resolves via dashboard: link / resync / dismiss.
--
--    Populated by: OrphanMessageHandler.handle_orphan()
--    Read by:      GET /orphans endpoint (dashboard)
--    Auto-resolved by: OrphanMessageHandler.auto_resolve_after_sync()
-- =============================================================================
CREATE TABLE IF NOT EXISTS message_orphan_queue (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id           UUID NOT NULL,
    unresolved_listing_id TEXT NOT NULL,  -- What Escapia sent us (unknown ID)
    thread_id            TEXT NOT NULL,
    message_id           TEXT NOT NULL,
    platform             TEXT,
    guest_name           TEXT,
    message_text         TEXT,
    raw_payload          TEXT,           -- Full JSON for re-processing after resolution

    status               TEXT NOT NULL DEFAULT 'unresolved',
    -- unresolved | resolved_linked | auto_resolved | resync_triggered | irrelevant

    resolved_listing_id  TEXT,           -- Set when operator links to correct property
    resolved_by          TEXT,           -- 'operator' | 'auto_sync' | 'admin'
    resolved_at          TIMESTAMPTZ,
    resolution_note      TEXT,

    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_orphan_company_status
    ON message_orphan_queue (company_id, status)
    WHERE status = 'unresolved';


-- =============================================================================
-- 9. PRE_BOOKING_INQUIRIES
--    Central table for the entire pre-booking workflow.
--    Each row is one guest inquiry with its AI draft and approval state.
--
--    Lifecycle:
--      received → pending_review → approved/edited/rejected → replied
--                                                           → superseded (answered externally)
--
--    Key fields for pre-booking without SMS/RCS:
--      thread_id            — Escapia conversation thread (reply target)
--      platform             — vrbo | airbnb (determines reply routing)
--      draft_text           — AI-generated response text
--      status               — controls what shows in approval queue
--      send_decision        — what the auto-send engine decided (send_now/review/hold)
--      approval_mode        — required (operator must act) | auto (sends on confidence)
-- =============================================================================
CREATE TABLE IF NOT EXISTS pre_booking_inquiries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id        TEXT UNIQUE NOT NULL,           -- INQ-XXXXXXXX
    thread_id       TEXT NOT NULL,                  -- Escapia conversation thread ID
    message_id      TEXT NOT NULL DEFAULT '',       -- Individual message ID within thread
    company_id      UUID,

    -- Source
    platform        TEXT NOT NULL DEFAULT 'unknown',  -- vrbo | airbnb | homeaway | direct
    guest_name      TEXT NOT NULL,
    message_text    TEXT NOT NULL,

    -- Requested stay (if guest included dates)
    requested_check_in  DATE,
    requested_check_out DATE,
    requested_guests    INTEGER,

    -- Property (Escapia listing ID — NOT property name)
    property_external_id TEXT NOT NULL DEFAULT '',

    -- AI processing
    intent          TEXT NOT NULL DEFAULT 'general',
    -- availability | pet_policy | pricing | amenities | local_area | group_size | general

    confidence      NUMERIC(4,3) DEFAULT 0,         -- 0.0–1.0
    draft_text      TEXT NOT NULL,                  -- What the AI wrote
    policy_flags    JSONB DEFAULT '[]',             -- Informational notes
    policy_warnings JSONB DEFAULT '[]',             -- Things that might need attention

    -- Workflow state
    status          TEXT NOT NULL DEFAULT 'pending_review',
    -- pending_review | approved | edited | rejected | replied | superseded | already_answered

    send_decision   TEXT DEFAULT 'review',          -- send_now | review | hold (engine output)
    approval_mode   TEXT DEFAULT 'required',        -- required | auto (property-level setting)

    -- What was actually sent (may differ from draft_text if operator edited)
    final_reply     TEXT,
    replied_at      TIMESTAMPTZ,

    -- Stale/superseded tracking
    resolution_note TEXT,    -- e.g. "Answered externally in Escapia: 'Yes we allow pets'"

    -- Learning engine signal
    was_edited      BOOLEAN DEFAULT FALSE,          -- TRUE if operator changed the draft
    edit_analysis   JSONB,                          -- Output of EditAnalyzer if edited

    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (thread_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_inquiries_company_status
    ON pre_booking_inquiries (company_id, status)
    WHERE status = 'pending_review';
CREATE INDEX IF NOT EXISTS idx_inquiries_platform
    ON pre_booking_inquiries (platform, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_inquiries_property
    ON pre_booking_inquiries (property_external_id, created_at DESC);


-- =============================================================================
-- 10. OPERATOR PRE-BOOKING POLICIES
--     Per-operator configuration for auto-send behavior.
--     If no row exists for a company_id, platform defaults are used.
--
--     auto_send_threshold:    min confidence score to auto-send (0.0–1.0)
--     auto_send_on_timeout:   if TRUE, auto-sends after review_window_hours
--     flag_pricing_inquiries: if TRUE, pricing questions always go to review
--     flag_pet_inquiries:     if TRUE, pet questions always go to review
--     platform_learning_opt_in: if TRUE, anonymized edit signal fed to platform intelligence
-- =============================================================================
CREATE TABLE IF NOT EXISTS operator_pre_booking_policies (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id              UUID NOT NULL UNIQUE,
    auto_send_threshold     NUMERIC(4,3) DEFAULT 0.75,
    auto_send_on_timeout    BOOLEAN DEFAULT TRUE,
    review_window_hours     INTEGER DEFAULT 2,
    flag_pricing_inquiries  BOOLEAN DEFAULT TRUE,
    flag_pet_inquiries      BOOLEAN DEFAULT FALSE,
    platform_learning_opt_in BOOLEAN DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =============================================================================
-- 11. PROPERTY ROLLOUT PHASES
--     Current phase for each property in the staged rollout.
--     One row per property — updated in place as operator advances.
--
--     phase values (in order):
--       inactive → pre_booking_single → pre_booking_full →
--       post_booking_single → post_booking_full → full_property → full_operator
--
--     approval_mode is independent of phase:
--       required = every draft held for review (default on phase entry)
--       auto     = AI sends when confidence + policy clear
-- =============================================================================
CREATE TABLE IF NOT EXISTS property_rollout_phases (
    id              UUID DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL,
    property_id     TEXT NOT NULL,                 -- pms_listings.external_id

    phase           TEXT NOT NULL DEFAULT 'inactive',
    approval_mode   TEXT NOT NULL DEFAULT 'required',  -- required | auto
    approval_mode_set_by TEXT,
    approval_mode_set_at TIMESTAMPTZ,

    entered_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    criteria_met_at TIMESTAMPTZ,   -- When advance criteria were first satisfied
    advanced_at     TIMESTAMPTZ,   -- When operator actually advanced
    advanced_by     TEXT,          -- 'operator' | 'admin' | 'auto'
    metrics_snapshot JSONB,        -- Snapshot at time of phase entry

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_property_rollout UNIQUE (company_id, property_id)
);

CREATE INDEX IF NOT EXISTS idx_rollout_company
    ON property_rollout_phases (company_id, phase);


-- =============================================================================
-- 12. PROPERTY ROLLOUT HISTORY
--     Append-only audit trail of every phase transition.
--     Useful for troubleshooting and operator transparency.
-- =============================================================================
CREATE TABLE IF NOT EXISTS property_rollout_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL,
    property_id     TEXT NOT NULL,
    from_phase      TEXT,
    to_phase        TEXT NOT NULL,
    advanced_by     TEXT,
    approval_mode   TEXT,
    metrics_at_time JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =============================================================================
-- 13. OPERATOR LEARNED PREFERENCES
--     Distilled AI behavior rules inferred from operator edits.
--     The AI reads these before generating any draft.
--
--     scope:
--       property  = applies to one specific property
--       operator  = applies to all properties for this operator
--       (platform-scope lives in platform_intelligence, not here)
--
--     confidence grows with observation_count:
--       1 obs  = 0.0 (stored but not yet injected)
--       2 obs  = 0.5 (starts influencing drafts)
--       3 obs  = 0.67 (strong signal)
--       5 obs  = 0.80
-- =============================================================================
CREATE TABLE IF NOT EXISTS operator_learned_preferences (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id          UUID NOT NULL,
    property_external_id TEXT,          -- NULL = applies to all properties (operator scope)

    intent              TEXT NOT NULL,  -- Which inquiry intent this applies to
    edit_type           TEXT NOT NULL,  -- price_declined | fact_added | tone_softer | etc.
    scope               TEXT NOT NULL DEFAULT 'property',  -- property | operator

    instruction         TEXT NOT NULL,  -- The actual constraint injected into AI prompt
    example_edit        TEXT,           -- Anonymized sample showing what operator changed

    observation_count   INTEGER NOT NULL DEFAULT 1,
    confidence          NUMERIC(5,4) NOT NULL DEFAULT 0.0,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_preferences_lookup
    ON operator_learned_preferences (company_id, intent, is_active)
    WHERE is_active = TRUE;


-- =============================================================================
-- 14. OPERATOR DRAFT EVENTS
--     Full audit log of every operator action on a draft:
--       edited               — operator changed the text before sending
--       approved_unchanged   — operator sent the AI draft as-is (positive signal)
--       rejected             — operator rejected the draft entirely (negative signal)
--
--     The learning engine reads this table to build operator_learned_preferences.
-- =============================================================================
CREATE TABLE IF NOT EXISTS operator_draft_events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id          UUID NOT NULL,
    draft_id            TEXT NOT NULL,
    intent              TEXT NOT NULL,
    property_external_id TEXT,

    event_type          TEXT NOT NULL,  -- edited | approved_unchanged | rejected
    original_draft      TEXT,
    edited_text         TEXT,

    -- Extracted from diff analysis
    edit_type           TEXT,           -- Which EditType enum value
    similarity_score    NUMERIC(5,4),   -- 0.0–1.0, how similar original and edited are
    added_phrases       JSONB DEFAULT '[]',
    price_signals       JSONB DEFAULT '[]',
    policy_signals      JSONB DEFAULT '[]',
    property_facts      JSONB DEFAULT '[]',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_draft_events_company
    ON operator_draft_events (company_id, intent, created_at DESC);


-- =============================================================================
-- 15. PLATFORM LEARNING EVENTS
--     Anonymized cross-operator signal — NO operator IDs, NO property info.
--     Only: intent + edit_type + boolean flags for signal types + timestamp.
--     Used by nightly job to build platform_intelligence summaries.
-- =============================================================================
CREATE TABLE IF NOT EXISTS platform_learning_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intent      TEXT NOT NULL,
    edit_type   TEXT NOT NULL,
    has_price_signal    BOOLEAN DEFAULT FALSE,
    has_policy_signal   BOOLEAN DEFAULT FALSE,
    has_property_fact   BOOLEAN DEFAULT FALSE,
    market      TEXT,               -- Optional geo market label
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_platform_events_intent
    ON platform_learning_events (intent, edit_type, created_at DESC);


-- =============================================================================
-- 16. PLATFORM INTELLIGENCE
--     Aggregated summaries rebuilt nightly from platform_learning_events.
--     Injected into AI drafts as market context.
--     Example row: intent='pricing', edit_type='price_declined',
--       intelligence_text='Most operators respond firmly to pricing requests.'
-- =============================================================================
CREATE TABLE IF NOT EXISTS platform_intelligence (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intent              TEXT NOT NULL,
    edit_type           TEXT NOT NULL,
    market              TEXT,
    intelligence_text   TEXT NOT NULL,
    sample_count        INTEGER NOT NULL DEFAULT 0,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    last_updated        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (intent, edit_type, market)
);


-- =============================================================================
-- 17. GATE CODE DELIVERIES
--     Audit log every time a gate/door code was delivered to a guest.
--     We NEVER store the full code — only the last 3 chars for debugging.
--     The full code is fetched live from Escapia on each request.
-- =============================================================================
CREATE TABLE IF NOT EXISTS gate_code_deliveries (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_token        TEXT NOT NULL,             -- Concierge session token
    property_external_id TEXT NOT NULL,             -- Which property
    code_suffix          TEXT NOT NULL,             -- Last 3 chars only
    guest_name           TEXT NOT NULL,
    check_in             DATE NOT NULL,
    check_out            DATE NOT NULL,
    delivered_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gate_code_property
    ON gate_code_deliveries (property_external_id, check_in DESC);


-- =============================================================================
-- 18. OPERATOR ALERT CONTACTS
--     Who receives which type of alert for which property/operator.
--     Supports escalation chains (escalation_order), active hours,
--     vacation/OOO mode, and redirect-when-unavailable.
--
--     alert_type values:
--       maintenance | escalation | kb_gap | late_checkout_req |
--       extend_stay_req | pre_booking | safety | billing |
--       review_alert | system_notice | general
-- =============================================================================
CREATE TABLE IF NOT EXISTS operator_alert_contacts (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id                  UUID NOT NULL,
    alert_type                  TEXT NOT NULL,
    property_code               TEXT,           -- NULL = all properties

    contact_name                TEXT NOT NULL,
    contact_phone               TEXT,           -- E.164 format
    contact_email               TEXT,

    is_primary                  BOOLEAN DEFAULT TRUE,
    escalation_order            INT DEFAULT 1,  -- Lower = contacted first
    escalation_timeout_minutes  INT DEFAULT 30, -- Minutes before escalating to next

    -- Active hours (NULL = 24/7)
    active_hours_start          TIME,
    active_hours_end            TIME,

    -- Vacation / OOO
    is_available                BOOLEAN DEFAULT TRUE,
    unavailable_until           TIMESTAMPTZ,    -- Auto-restores when NOW() > this
    redirect_to_id              UUID REFERENCES operator_alert_contacts(id),

    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_contacts_company
    ON operator_alert_contacts (company_id, alert_type);
CREATE INDEX IF NOT EXISTS idx_alert_contacts_property
    ON operator_alert_contacts (property_code, alert_type);


-- =============================================================================
-- 19. OPERATOR ALERT ACKS
--     Tracks whether an alert was acknowledged within its timeout window.
--     The Celery beat task check_unacked_alerts reads this every 5 minutes
--     and fires to the next contact in the escalation chain if unacked.
-- =============================================================================
CREATE TABLE IF NOT EXISTS operator_alert_acks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id    TEXT NOT NULL,
    contact_id  UUID NOT NULL REFERENCES operator_alert_contacts(id),
    company_id  UUID NOT NULL,
    alert_type  TEXT NOT NULL,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ack_deadline TIMESTAMPTZ NOT NULL,             -- When we give up and escalate
    acked       BOOLEAN NOT NULL DEFAULT FALSE,
    acked_at    TIMESTAMPTZ,
    escalated   BOOLEAN NOT NULL DEFAULT FALSE,    -- TRUE = already fired to next contact
    UNIQUE(alert_id, contact_id)
);

CREATE INDEX IF NOT EXISTS idx_acks_deadline
    ON operator_alert_acks (acked, escalated, ack_deadline)
    WHERE acked = FALSE AND escalated = FALSE;


-- =============================================================================
-- 20. OPERATOR ALERT LOG
--     Stores the original message text so the escalation re-send can
--     include the full original context (not just "alert X was unacked").
-- =============================================================================
CREATE TABLE IF NOT EXISTS operator_alert_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id    TEXT UNIQUE NOT NULL,
    company_id  UUID NOT NULL,
    alert_type  TEXT NOT NULL,
    property_code TEXT,
    message     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =============================================================================
-- COLUMNS ADDED TO EXISTING TABLES
-- Using ADD COLUMN IF NOT EXISTS so these are safe to re-run.
-- =============================================================================

-- concierge_guest_sessions: link session to Escapia listing ID
-- (property_code stores the human name; property_external_id is the stable ID)
ALTER TABLE concierge_guest_sessions
    ADD COLUMN IF NOT EXISTS property_external_id TEXT,
    ADD COLUMN IF NOT EXISTS booking_channel       TEXT DEFAULT 'direct',
    ADD COLUMN IF NOT EXISTS gate_code_last_requested TIMESTAMPTZ;

-- Company ID on concierge sessions (needed for multi-operator queries)
ALTER TABLE concierge_guest_sessions
    ADD COLUMN IF NOT EXISTS company_id UUID;

CREATE INDEX IF NOT EXISTS idx_sessions_company_external
    ON concierge_guest_sessions (company_id, property_external_id)
    WHERE company_id IS NOT NULL;

"""


def upgrade() -> None:
    op.execute(SQL)


def downgrade() -> None:
    # This migration consolidates many legacy bootstrap tables and columns.
    # Downgrades are intentionally left as a no-op to avoid destructive loss
    # of production operator and inquiry data.
    pass
