-- Supabase prereqs: tables that migration_018 depends on via ALTER TABLE
-- Safe to re-run (IF NOT EXISTS throughout)

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS knowledge_embeddings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content     TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS concierge_escalations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_token   TEXT,
    property_code   TEXT NOT NULL DEFAULT '',
    reason          TEXT NOT NULL DEFAULT 'unknown',
    priority        TEXT NOT NULL DEFAULT 'medium',
    status          TEXT NOT NULL DEFAULT 'open',
    summary         TEXT,
    guest_name      TEXT,
    property_name   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS concierge_guest_sessions (
    session_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL,
    token               TEXT UNIQUE NOT NULL,
    property_id         UUID,
    property_code       TEXT NOT NULL,
    property_name       TEXT NOT NULL,
    guest_name          TEXT NOT NULL,
    guest_phone         TEXT,
    guest_email         TEXT,
    num_guests          INTEGER DEFAULT 1,
    check_in            DATE NOT NULL,
    check_out           DATE NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active',
    phase               TEXT NOT NULL DEFAULT 'pre_arrival',
    conversation_count  INTEGER DEFAULT 0,
    last_message_at     TIMESTAMPTZ,
    pms_synced_at       TIMESTAMPTZ,
    property_context    JSONB NOT NULL DEFAULT '{}',
    operator_id         TEXT,
    reservation_id      TEXT,
    feedback_rating     INTEGER,
    feedback_text       TEXT,
    feedback_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
