-- Migration 015: Experiment / Prompt Ops — variant assignment log
--
-- Persists which variant each session was assigned to.
-- In-process VariantMetrics are in-memory and reset on restart;
-- this table lets you reconstruct per-variant rates from Watch Layer
-- events after a restart, and lets the operator dashboard show
-- historical assignment breakdowns without needing a metrics backend.
--
-- Rollback: DROP TABLE experiment_assignments;

-- ── Assignment log ────────────────────────────────────────────────────────────
-- One row per session (upsert-safe — session_token is UNIQUE).
-- Written once at VoicePod creation.  Never updated after creation.

CREATE TABLE IF NOT EXISTS experiment_assignments (
    id                  BIGSERIAL PRIMARY KEY,

    session_token       TEXT        NOT NULL,
    variant_id          TEXT        NOT NULL,         -- "control" or candidate slug
    is_control          BOOLEAN     NOT NULL DEFAULT TRUE,

    -- Snapshot of the variant state at assignment time
    canary_pct          NUMERIC(5,2) NOT NULL DEFAULT 0,
    has_prompt_override BOOLEAN     NOT NULL DEFAULT FALSE,
    config_overrides    JSONB       NOT NULL DEFAULT '{}',

    -- Session context (denormalized for query convenience)
    operator_id         TEXT,
    property_code       TEXT,

    assigned_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_experiment_assignments_session UNIQUE (session_token)
);

-- Indexes for dashboard queries
CREATE INDEX IF NOT EXISTS idx_exp_assignments_variant
    ON experiment_assignments (variant_id, assigned_at DESC);

CREATE INDEX IF NOT EXISTS idx_exp_assignments_operator
    ON experiment_assignments (operator_id, assigned_at DESC);

CREATE INDEX IF NOT EXISTS idx_exp_assignments_property
    ON experiment_assignments (property_code, assigned_at DESC);

-- ── Variant audit log ─────────────────────────────────────────────────────────
-- Immutable record of every pause/resume/register event.
-- Written by the API layer so actions are auditable even after server restart.

CREATE TABLE IF NOT EXISTS experiment_variant_events (
    id              BIGSERIAL PRIMARY KEY,
    variant_id      TEXT        NOT NULL,
    event_type      TEXT        NOT NULL, -- "registered", "paused", "resumed", "auto_paused"
    reason          TEXT,
    operator        TEXT,                 -- who triggered it (null = auto)
    metric          TEXT,                 -- for auto_pause: which metric tripped
    metric_value    NUMERIC(8,4),
    ratio_vs_control NUMERIC(8,4),
    threshold       NUMERIC(8,4),
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exp_variant_events_variant
    ON experiment_variant_events (variant_id, occurred_at DESC);
