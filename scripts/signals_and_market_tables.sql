-- signals_and_market_tables.sql
-- Run this in Supabase SQL Editor AFTER market_tables.sql
-- Creates signals table, concierge_knowledge, and market intelligence infrastructure
-- Safe to re-run (IF NOT EXISTS throughout)

-- ── Signals table (simplified -- no TimescaleDB required) ─────────────────────
-- Note: TimescaleDB is available on Supabase Pro. For free tier we use
-- standard PostgreSQL with good indexing. Upgrade later for hypertable.

CREATE TABLE IF NOT EXISTS signals (
    signal_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL,
    signal_type         TEXT NOT NULL,
    scope               TEXT NOT NULL,
    geo_id              TEXT,
    property_id         UUID,
    platform            TEXT,
    value               FLOAT NOT NULL,
    structured_value    JSONB,
    confidence          FLOAT NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    weight_hint         FLOAT DEFAULT 1.0,
    source              TEXT NOT NULL,
    detector_name       TEXT NOT NULL,
    detector_version    TEXT NOT NULL DEFAULT '1.0.0',
    detected_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    time_window         TEXT NOT NULL,
    valid_from          DATE,
    valid_until         DATE,
    decay_profile       TEXT DEFAULT 'stable',
    geo_sensitivity     TEXT DEFAULT 'local',
    metadata            JSONB DEFAULT '{}',
    schema_version      TEXT DEFAULT '1.0.0',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_signals_tenant ON signals(tenant_id);
CREATE INDEX IF NOT EXISTS ix_signals_geo_time ON signals(tenant_id, geo_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS ix_signals_type_time ON signals(tenant_id, signal_type, detected_at DESC);
CREATE INDEX IF NOT EXISTS ix_signals_scope ON signals(tenant_id, scope, detected_at DESC);
CREATE INDEX IF NOT EXISTS ix_signals_validity ON signals(valid_from, valid_until);
CREATE INDEX IF NOT EXISTS ix_signals_geo_type ON signals(geo_id, signal_type, detected_at DESC);

-- ── Concierge Knowledge (if not already created) ──────────────────────────────
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
    ON concierge_knowledge(property_external_id)
    WHERE property_external_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_concierge_knowledge_active_events
    ON concierge_knowledge(valid_until, is_active)
    WHERE is_active = true;

-- ── Market Intelligence View (for operator dashboard API) ─────────────────────
-- This view powers the "Market Intelligence" section of the operator app.
-- It joins signals + market_events to give a complete picture of what's
-- driving booking demand in the operator's market.

CREATE OR REPLACE VIEW market_intelligence_summary AS
SELECT
    mr.market_id,
    mr.market_name,
    mr.state_code,
    mr.last_scraped_at,
    mr.last_scrape_event_count,

    -- Upcoming events in the next 30 days
    COUNT(me.event_id) FILTER (
        WHERE me.start_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days'
        AND me.is_active = true
    ) AS events_next_30d,

    -- High-impact events (demand_impact_score > 0.7)
    COUNT(me.event_id) FILTER (
        WHERE me.start_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days'
        AND me.is_active = true
        AND me.demand_impact_score > 0.7
    ) AS high_impact_events_30d,

    -- Peak weekend (highest single-day event density)
    (
        SELECT me2.start_date
        FROM market_events me2
        WHERE me2.market_id = mr.market_id
          AND me2.start_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '60 days'
          AND me2.is_active = true
        GROUP BY me2.start_date
        ORDER BY COUNT(*) DESC, SUM(me2.demand_impact_score) DESC
        LIMIT 1
    ) AS peak_event_date,

    -- Average demand pressure score (from signals, last 7 days)
    (
        SELECT AVG(s.value * s.confidence)
        FROM signals s
        WHERE s.geo_id = mr.market_id
          AND s.signal_type = 'demand_pressure'
          AND s.detected_at > NOW() - INTERVAL '7 days'
    ) AS avg_demand_pressure,

    -- Category breakdown of upcoming events
    (
        SELECT jsonb_object_agg(category, cnt)
        FROM (
            SELECT me3.category, COUNT(*) as cnt
            FROM market_events me3
            WHERE me3.market_id = mr.market_id
              AND me3.start_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days'
              AND me3.is_active = true
            GROUP BY me3.category
            ORDER BY cnt DESC
        ) cat_counts
    ) AS event_categories,

    mr.sources_config,
    mr.scrape_interval_hours

FROM market_registry mr
LEFT JOIN market_events me ON me.market_id = mr.market_id
GROUP BY mr.market_id, mr.market_name, mr.state_code,
         mr.last_scraped_at, mr.last_scrape_event_count,
         mr.sources_config, mr.scrape_interval_hours;

-- ── Operator market linkage ───────────────────────────────────────────────────
-- Tracks which operators are in which markets for the dashboard
-- This is lightweight -- just maps company_id -> market_id
CREATE TABLE IF NOT EXISTS operator_market_links (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id  UUID NOT NULL,
    market_id   TEXT NOT NULL,
    linked_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(company_id, market_id)
);

CREATE INDEX IF NOT EXISTS idx_oml_company ON operator_market_links(company_id);

-- ── Seed first operator market link (30A) ─────────────────────────────────────
-- This will be replaced by the dynamic onboarding flow.
-- For now, hardcode the first operator to 30A.
-- Run pre_booking_setup.py to get the company_id, then update this.
-- INSERT INTO operator_market_links (company_id, market_id)
-- VALUES ('YOUR-COMPANY-UUID-HERE', '30a_fl')
-- ON CONFLICT DO NOTHING;
