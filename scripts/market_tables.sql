-- market_tables.sql
-- Run this in Supabase SQL Editor to create market events infrastructure
-- Safe to re-run (IF NOT EXISTS throughout)

-- ── Market Registry ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS market_registry (
    market_id               TEXT PRIMARY KEY,
    market_name             TEXT NOT NULL,
    state_code              TEXT NOT NULL,
    center_lat              FLOAT NOT NULL,
    center_lng              FLOAT NOT NULL,
    radius_miles            FLOAT NOT NULL DEFAULT 15.0,
    scrape_enabled          BOOLEAN NOT NULL DEFAULT true,
    scrape_interval_hours   INTEGER NOT NULL DEFAULT 24,
    last_scraped_at         TIMESTAMPTZ,
    last_scrape_status      TEXT,
    last_scrape_event_count INTEGER NOT NULL DEFAULT 0,
    sources_config          JSONB NOT NULL DEFAULT '{}',
    operator_ids            JSONB NOT NULL DEFAULT '[]',
    timezone                TEXT NOT NULL DEFAULT 'America/Chicago',
    notes                   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Market Events ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS market_events (
    event_id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market_id               TEXT NOT NULL,
    market_name             TEXT NOT NULL,
    title                   TEXT NOT NULL,
    description             TEXT,
    category                TEXT,
    tags                    JSONB NOT NULL DEFAULT '[]',
    start_date              DATE NOT NULL,
    end_date                DATE NOT NULL,
    start_time              TEXT,
    end_time                TEXT,
    is_multi_day            BOOLEAN NOT NULL DEFAULT false,
    is_recurring            BOOLEAN NOT NULL DEFAULT false,
    recurrence_rule         TEXT,
    venue_name              TEXT,
    venue_address           TEXT,
    venue_lat               FLOAT,
    venue_lng               FLOAT,
    estimated_attendance    INTEGER,
    demand_radius_miles     FLOAT NOT NULL DEFAULT 15.0,
    demand_impact_score     FLOAT,
    source                  TEXT NOT NULL,
    source_id               TEXT,
    source_url              TEXT,
    ticket_url              TEXT,
    ticket_price_range      TEXT,
    is_free                 BOOLEAN NOT NULL DEFAULT false,
    is_active               BOOLEAN NOT NULL DEFAULT true,
    rag_indexed_at          TIMESTAMPTZ,
    rag_knowledge_id        TEXT,
    scraped_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_market_events_market_id
    ON market_events (market_id);

CREATE INDEX IF NOT EXISTS idx_market_events_start_date
    ON market_events (start_date);

CREATE INDEX IF NOT EXISTS idx_market_events_category
    ON market_events (category);

CREATE UNIQUE INDEX IF NOT EXISTS idx_market_events_source_dedup
    ON market_events (market_id, source, source_id)
    WHERE source_id IS NOT NULL;

-- ── Concierge Knowledge table (if not already created by migration 018) ───────
CREATE TABLE IF NOT EXISTS concierge_knowledge (
    knowledge_id            TEXT PRIMARY KEY,
    tenant_id               UUID,
    property_external_id    TEXT,
    category                TEXT NOT NULL DEFAULT 'general',
    question                TEXT NOT NULL,
    answer                  TEXT NOT NULL,
    confidence              FLOAT NOT NULL DEFAULT 0.85,
    source                  TEXT,
    valid_from              DATE,
    valid_until             DATE,
    is_active               BOOLEAN NOT NULL DEFAULT true,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_concierge_knowledge_property
    ON concierge_knowledge (property_external_id)
    WHERE property_external_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_concierge_knowledge_category
    ON concierge_knowledge (category);

CREATE INDEX IF NOT EXISTS idx_concierge_knowledge_valid
    ON concierge_knowledge (valid_until)
    WHERE is_active = true;

-- ── Seed 30A market ───────────────────────────────────────────────────────────
INSERT INTO market_registry (
    market_id, market_name, state_code,
    center_lat, center_lng, radius_miles,
    scrape_enabled, scrape_interval_hours,
    sources_config, timezone
) VALUES (
    '30a_fl',
    '30A Beaches, FL',
    'FL',
    30.2833, -86.0167, 15.0,
    true, 24,
    '{
        "eventbrite":        {"enabled": true},
        "visitflorida":      {"enabled": true},
        "visitwaltoncounty": {"enabled": true},
        "30a_com":           {"enabled": true}
    }',
    'America/Chicago'
) ON CONFLICT (market_id) DO NOTHING;

-- ── Seed Destin market (nearby, worth including) ──────────────────────────────
INSERT INTO market_registry (
    market_id, market_name, state_code,
    center_lat, center_lng, radius_miles,
    scrape_enabled, scrape_interval_hours,
    sources_config, timezone
) VALUES (
    'destin_fl',
    'Destin, FL',
    'FL',
    30.3935, -86.4958, 12.0,
    true, 48,
    '{
        "eventbrite":   {"enabled": true},
        "visitflorida": {"enabled": true},
        "visitdestin":  {"enabled": true}
    }',
    'America/Chicago'
) ON CONFLICT (market_id) DO NOTHING;
