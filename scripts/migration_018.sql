-- =============================================================================
-- migration_018.sql — Pre-Booking Pipeline
-- Safe to re-run: all statements use IF NOT EXISTS / ON CONFLICT DO NOTHING
-- Run via: psql $DATABASE_URL -f scripts/migration_018.sql
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. COMPANIES — operator identity
-- =============================================================================
CREATE TABLE IF NOT EXISTS companies (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             TEXT NOT NULL,
    code             TEXT UNIQUE,
    concierge_name   TEXT DEFAULT 'Coral',
    support_phone    TEXT,
    support_email    TEXT,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 2. OPERATOR FEATURE FLAGS — staged rollout gates
-- =============================================================================
CREATE TABLE IF NOT EXISTS operator_feature_flags (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID,
    property_code   TEXT,
    flag_name       TEXT NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT FALSE,
    enabled_at      TIMESTAMPTZ,
    enabled_by      TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_operator_feature_flags
        UNIQUE NULLS NOT DISTINCT (company_id, property_code, flag_name)
);

CREATE INDEX IF NOT EXISTS idx_flags_company
    ON operator_feature_flags (company_id, flag_name);
CREATE INDEX IF NOT EXISTS idx_flags_property
    ON operator_feature_flags (property_code, flag_name);

-- =============================================================================
-- 3. PMS LISTINGS — Escapia property records
-- =============================================================================
CREATE TABLE IF NOT EXISTS pms_listings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL,
    external_id     TEXT NOT NULL,
    pms_provider    TEXT NOT NULL DEFAULT 'escapia',
    property_name   TEXT,
    address_line1   TEXT,
    address_line2   TEXT,
    city            TEXT,
    state           TEXT,
    postal_code     TEXT,
    country         TEXT DEFAULT 'US',
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    bedrooms        INTEGER DEFAULT 0,
    bathrooms       NUMERIC(4,1) DEFAULT 0,
    max_guests      INTEGER,
    square_footage  INTEGER,
    property_type   TEXT DEFAULT 'single_family',
    has_pool        BOOLEAN DEFAULT FALSE,
    pool_heated     BOOLEAN DEFAULT FALSE,
    has_hot_tub     BOOLEAN DEFAULT FALSE,
    has_waterfront  BOOLEAN DEFAULT FALSE,
    waterfront_type TEXT,
    beach_access    TEXT,
    pet_friendly    BOOLEAN DEFAULT FALSE,
    has_garage      BOOLEAN DEFAULT FALSE,
    has_ev_charger  BOOLEAN DEFAULT FALSE,
    has_game_room   BOOLEAN DEFAULT FALSE,
    has_home_theater BOOLEAN DEFAULT FALSE,
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
-- 4. PMS BOOKINGS — confirmed reservations
-- =============================================================================
CREATE TABLE IF NOT EXISTS pms_bookings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL,
    listing_id      UUID REFERENCES pms_listings(id),
    external_id     TEXT NOT NULL,
    external_listing_id TEXT,
    check_in        DATE NOT NULL,
    check_out       DATE NOT NULL,
    nights          INTEGER NOT NULL DEFAULT 1,
    total_amount    NUMERIC(10,2),
    nightly_rate    NUMERIC(10,2),
    cleaning_fee    NUMERIC(10,2),
    taxes           NUMERIC(10,2),
    guest_count     INTEGER DEFAULT 1,
    booking_channel TEXT DEFAULT 'direct',
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
-- 5. OPERATOR SYNC LOG — PMS sync audit trail
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
-- 6. LISTING ID ALIASES — handles renamed/migrated listing IDs
-- =============================================================================
CREATE TABLE IF NOT EXISTS listing_id_aliases (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id            UUID NOT NULL,
    alias_external_id     TEXT NOT NULL,
    canonical_external_id TEXT NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, alias_external_id)
);

-- =============================================================================
-- 7. ESCAPIA MESSAGE HISTORY — full historical archive
-- =============================================================================
CREATE TABLE IF NOT EXISTS escapia_message_history (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id           TEXT NOT NULL,
    thread_id            TEXT NOT NULL,
    company_id           UUID NOT NULL,
    listing_external_id  TEXT NOT NULL,
    direction            TEXT NOT NULL DEFAULT 'guest_to_host',
    sender_name          TEXT,
    body                 TEXT NOT NULL,
    platform             TEXT NOT NULL DEFAULT 'unknown',
    reservation_id       TEXT,
    status               TEXT NOT NULL DEFAULT 'historical',
    our_draft_id         TEXT,
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
-- 8. MESSAGE ORPHAN QUEUE — unresolvable listing IDs
-- =============================================================================
CREATE TABLE IF NOT EXISTS message_orphan_queue (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id            UUID NOT NULL,
    unresolved_listing_id TEXT NOT NULL,
    thread_id             TEXT NOT NULL,
    message_id            TEXT NOT NULL,
    platform              TEXT,
    guest_name            TEXT,
    message_text          TEXT,
    raw_payload           TEXT,
    status                TEXT NOT NULL DEFAULT 'unresolved',
    resolved_listing_id   TEXT,
    resolved_by           TEXT,
    resolved_at           TIMESTAMPTZ,
    resolution_note       TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_orphan_company_status
    ON message_orphan_queue (company_id, status)
    WHERE status = 'unresolved';

-- =============================================================================
-- 9. PRE_BOOKING_INQUIRIES — central approval workflow table
-- =============================================================================
CREATE TABLE IF NOT EXISTS pre_booking_inquiries (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id             TEXT UNIQUE NOT NULL,
    thread_id            TEXT NOT NULL,
    message_id           TEXT NOT NULL DEFAULT '',
    company_id           UUID,
    platform             TEXT NOT NULL DEFAULT 'unknown',
    guest_name           TEXT NOT NULL,
    message_text         TEXT NOT NULL,
    requested_check_in   DATE,
    requested_check_out  DATE,
    requested_guests     INTEGER,
    property_external_id TEXT NOT NULL DEFAULT '',
    intent               TEXT NOT NULL DEFAULT 'general',
    confidence           NUMERIC(4,3) DEFAULT 0,
    draft_text           TEXT NOT NULL,
    policy_flags         JSONB DEFAULT '[]',
    policy_warnings      JSONB DEFAULT '[]',
    status               TEXT NOT NULL DEFAULT 'pending_review',
    send_decision        TEXT DEFAULT 'review',
    approval_mode        TEXT DEFAULT 'required',
    final_reply          TEXT,
    replied_at           TIMESTAMPTZ,
    resolution_note      TEXT,
    was_edited           BOOLEAN DEFAULT FALSE,
    edit_analysis        JSONB,
    received_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
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
-- 10. OPERATOR PRE-BOOKING POLICIES — auto-send configuration
-- =============================================================================
CREATE TABLE IF NOT EXISTS operator_pre_booking_policies (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id               UUID NOT NULL UNIQUE,
    auto_send_threshold      NUMERIC(4,3) DEFAULT 0.75,
    auto_send_on_timeout     BOOLEAN DEFAULT TRUE,
    review_window_hours      INTEGER DEFAULT 2,
    flag_pricing_inquiries   BOOLEAN DEFAULT TRUE,
    flag_pet_inquiries       BOOLEAN DEFAULT FALSE,
    platform_learning_opt_in BOOLEAN DEFAULT TRUE,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 11. PROPERTY ROLLOUT PHASES — staged rollout tracker
-- =============================================================================
CREATE TABLE IF NOT EXISTS property_rollout_phases (
    id                   UUID DEFAULT gen_random_uuid(),
    company_id           UUID NOT NULL,
    property_id          TEXT NOT NULL,
    phase                TEXT NOT NULL DEFAULT 'inactive',
    approval_mode        TEXT NOT NULL DEFAULT 'required',
    approval_mode_set_by TEXT,
    approval_mode_set_at TIMESTAMPTZ,
    entered_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    criteria_met_at      TIMESTAMPTZ,
    advanced_at          TIMESTAMPTZ,
    advanced_by          TEXT,
    metrics_snapshot     JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_property_rollout UNIQUE (company_id, property_id)
);

CREATE INDEX IF NOT EXISTS idx_rollout_company
    ON property_rollout_phases (company_id, phase);

-- =============================================================================
-- 12. PROPERTY ROLLOUT HISTORY — audit trail
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
-- 13. OPERATOR LEARNED PREFERENCES — distilled AI behavior rules
-- =============================================================================
CREATE TABLE IF NOT EXISTS operator_learned_preferences (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id           UUID NOT NULL,
    property_external_id TEXT,
    intent               TEXT NOT NULL,
    edit_type            TEXT NOT NULL,
    scope                TEXT NOT NULL DEFAULT 'property',
    instruction          TEXT NOT NULL,
    example_edit         TEXT,
    observation_count    INTEGER NOT NULL DEFAULT 1,
    confidence           NUMERIC(5,4) NOT NULL DEFAULT 0.0,
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_preferences_lookup
    ON operator_learned_preferences (company_id, intent, is_active)
    WHERE is_active = TRUE;

-- =============================================================================
-- 14. OPERATOR DRAFT EVENTS — full audit log of approve/edit/reject
-- =============================================================================
CREATE TABLE IF NOT EXISTS operator_draft_events (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id           UUID NOT NULL,
    draft_id             TEXT NOT NULL,
    intent               TEXT NOT NULL,
    property_external_id TEXT,
    event_type           TEXT NOT NULL,
    original_draft       TEXT,
    edited_text          TEXT,
    edit_type            TEXT,
    similarity_score     NUMERIC(5,4),
    added_phrases        JSONB DEFAULT '[]',
    price_signals        JSONB DEFAULT '[]',
    policy_signals       JSONB DEFAULT '[]',
    property_facts       JSONB DEFAULT '[]',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_draft_events_company
    ON operator_draft_events (company_id, intent, created_at DESC);

-- =============================================================================
-- 15. PLATFORM LEARNING EVENTS — anonymous cross-operator signal
-- =============================================================================
CREATE TABLE IF NOT EXISTS platform_learning_events (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intent            TEXT NOT NULL,
    edit_type         TEXT NOT NULL,
    has_price_signal  BOOLEAN DEFAULT FALSE,
    has_policy_signal BOOLEAN DEFAULT FALSE,
    has_property_fact BOOLEAN DEFAULT FALSE,
    market            TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_platform_events_intent
    ON platform_learning_events (intent, edit_type, created_at DESC);

-- =============================================================================
-- 16. PLATFORM INTELLIGENCE — nightly aggregated market intelligence
-- =============================================================================
CREATE TABLE IF NOT EXISTS platform_intelligence (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intent            TEXT NOT NULL,
    edit_type         TEXT NOT NULL,
    market            TEXT,
    intelligence_text TEXT NOT NULL,
    sample_count      INTEGER NOT NULL DEFAULT 0,
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    last_updated      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (intent, edit_type, market)
);

-- =============================================================================
-- 17. GATE CODE DELIVERIES — audit log (last 3 chars only, never full code)
-- =============================================================================
CREATE TABLE IF NOT EXISTS gate_code_deliveries (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_token        TEXT NOT NULL,
    property_external_id TEXT NOT NULL,
    code_suffix          TEXT NOT NULL,
    guest_name           TEXT NOT NULL,
    check_in             DATE NOT NULL,
    check_out            DATE NOT NULL,
    delivered_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gate_code_property
    ON gate_code_deliveries (property_external_id, check_in DESC);

-- =============================================================================
-- 18. OPERATOR ALERT CONTACTS — who gets which alert for which property
-- =============================================================================
CREATE TABLE IF NOT EXISTS operator_alert_contacts (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id                 UUID NOT NULL,
    alert_type                 TEXT NOT NULL,
    property_code              TEXT,
    contact_name               TEXT NOT NULL,
    contact_phone              TEXT,
    contact_email              TEXT,
    is_primary                 BOOLEAN DEFAULT TRUE,
    escalation_order           INT DEFAULT 1,
    escalation_timeout_minutes INT DEFAULT 30,
    active_hours_start         TIME,
    active_hours_end           TIME,
    is_available               BOOLEAN DEFAULT TRUE,
    unavailable_until          TIMESTAMPTZ,
    redirect_to_id             UUID REFERENCES operator_alert_contacts(id),
    notes                      TEXT,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_contacts_company
    ON operator_alert_contacts (company_id, alert_type);
CREATE INDEX IF NOT EXISTS idx_alert_contacts_property
    ON operator_alert_contacts (property_code, alert_type);

-- =============================================================================
-- 19. OPERATOR ALERT ACKS — escalation chain ack tracking
-- =============================================================================
CREATE TABLE IF NOT EXISTS operator_alert_acks (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id     TEXT NOT NULL,
    contact_id   UUID NOT NULL REFERENCES operator_alert_contacts(id),
    company_id   UUID NOT NULL,
    alert_type   TEXT NOT NULL,
    sent_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ack_deadline TIMESTAMPTZ NOT NULL,
    acked        BOOLEAN NOT NULL DEFAULT FALSE,
    acked_at     TIMESTAMPTZ,
    escalated    BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE(alert_id, contact_id)
);

CREATE INDEX IF NOT EXISTS idx_acks_deadline
    ON operator_alert_acks (acked, escalated, ack_deadline)
    WHERE acked = FALSE AND escalated = FALSE;

-- =============================================================================
-- 20. OPERATOR ALERT LOG — original message text for escalation re-send
-- =============================================================================
CREATE TABLE IF NOT EXISTS operator_alert_log (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id      TEXT UNIQUE NOT NULL,
    company_id    UUID NOT NULL,
    alert_type    TEXT NOT NULL,
    property_code TEXT,
    message       TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- COLUMNS ADDED TO EXISTING TABLES (safe to re-run)
-- =============================================================================

ALTER TABLE concierge_guest_sessions
    ADD COLUMN IF NOT EXISTS property_external_id        TEXT,
    ADD COLUMN IF NOT EXISTS booking_channel             TEXT DEFAULT 'direct',
    ADD COLUMN IF NOT EXISTS gate_code_last_requested    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS company_id                  UUID;

CREATE INDEX IF NOT EXISTS idx_sessions_company_external
    ON concierge_guest_sessions (company_id, property_external_id)
    WHERE company_id IS NOT NULL;

-- =============================================================================
-- PROPERTY INCIDENT LOG — for in-stay issues (washing machine scenario)
-- Covered by existing concierge_escalations table but adding
-- a dedicated property_incidents table for operational tracking.
-- =============================================================================
CREATE TABLE IF NOT EXISTS property_incidents (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id           UUID NOT NULL,
    property_external_id TEXT NOT NULL,
    session_token        TEXT,                          -- Link to guest session if active
    escalation_ticket_id TEXT,                          -- Link to concierge_escalations

    incident_type        TEXT NOT NULL DEFAULT 'maintenance',
    -- maintenance | safety | cleanliness | complaint | other

    priority             TEXT NOT NULL DEFAULT 'high',
    -- urgent | high | medium | low

    title                TEXT NOT NULL,                 -- "Washing machine not working"
    description          TEXT,
    guest_name           TEXT,
    guest_phone          TEXT,

    -- Compensation tracking
    compensation_requested BOOLEAN DEFAULT FALSE,
    compensation_amount    NUMERIC(10,2),               -- Dollar amount if offered
    compensation_type      TEXT,                        -- refund | credit | gift | none
    compensation_notes     TEXT,
    compensation_approved_by TEXT,
    compensation_approved_at TIMESTAMPTZ,

    -- Resolution
    status               TEXT NOT NULL DEFAULT 'open',
    -- open | acknowledged | in_progress | resolved | closed

    vendor_name          TEXT,                          -- Who was dispatched
    vendor_eta_minutes   INTEGER,
    resolved_at          TIMESTAMPTZ,
    resolution_summary   TEXT,

    -- Operator notes
    operator_notes       TEXT,

    reported_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_incidents_property
    ON property_incidents (property_external_id, reported_at DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_company_status
    ON property_incidents (company_id, status)
    WHERE status IN ('open', 'acknowledged', 'in_progress');

COMMIT;
-- Migration 018 complete.
-- Column additions to concierge_guest_sessions are applied by run_migration_018.py
-- after Alembic creates that table.
