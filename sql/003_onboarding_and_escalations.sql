-- Migration 003: Onboarding sessions + DB-backed escalation tickets
-- Run this against your Postgres database before deploying

-- ─────────────────────────────────────────────────────────────────────────────
-- Operator onboarding sessions (persists conversational state across restarts)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS concierge_onboarding_sessions (
    session_id      TEXT        PRIMARY KEY,
    session_data    JSONB       NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_onboarding_sessions_updated
    ON concierge_onboarding_sessions (updated_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Escalation tickets (replaces in-memory EscalationService)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS concierge_escalation_tickets (
    ticket_id       TEXT        PRIMARY KEY,
    tenant_id       UUID        NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    session_token   TEXT,
    guest_name      TEXT        NOT NULL DEFAULT 'Unknown Guest',
    property_name   TEXT        NOT NULL DEFAULT 'Unknown Property',
    property_code   TEXT,
    -- Reason codes: maintenance, safety, complaint, guest_requested, repeated_failures
    reason          TEXT        NOT NULL,
    -- Priority: urgent, high, medium, low
    priority        TEXT        NOT NULL DEFAULT 'medium',
    -- Status: pending, acknowledged, resolved
    status          TEXT        NOT NULL DEFAULT 'pending',
    summary         TEXT        NOT NULL DEFAULT '',
    trigger_message TEXT,
    acknowledged_by TEXT,
    acknowledged_at TIMESTAMPTZ,
    resolved_by     TEXT,
    resolved_at     TIMESTAMPTZ,
    resolution_note TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_escalations_tenant_status
    ON concierge_escalation_tickets (tenant_id, status, priority);
CREATE INDEX IF NOT EXISTS idx_escalations_token
    ON concierge_escalation_tickets (session_token);
CREATE INDEX IF NOT EXISTS idx_escalations_created
    ON concierge_escalation_tickets (created_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Knowledge gaps: add session_token column if not present
-- (was added in earlier migrations but may be missing on some installs)
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE concierge_knowledge_gaps
    ADD COLUMN IF NOT EXISTS session_token TEXT;
