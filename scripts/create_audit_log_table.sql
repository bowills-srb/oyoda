-- create_audit_log_table.sql
-- Run in Supabase SQL editor to persist security audit events to DB
-- Replaces the ephemeral /tmp/oyvoda_audit.jsonl file on Railway

CREATE TABLE IF NOT EXISTS security_audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id        TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Actor
    actor_id        TEXT NOT NULL,
    actor_type      TEXT NOT NULL DEFAULT 'operator',

    -- Action
    action          TEXT NOT NULL,
    resource_type   TEXT NOT NULL DEFAULT '',
    resource_id     TEXT NOT NULL DEFAULT '',

    -- Outcome
    success         BOOLEAN NOT NULL DEFAULT TRUE,
    reason          TEXT NOT NULL DEFAULT '',

    -- Context (never store PII here)
    ip_address      TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',

    -- Indexes
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_actor        ON security_audit_log (actor_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_event_type   ON security_audit_log (event_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp    ON security_audit_log (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_success      ON security_audit_log (success, timestamp DESC) WHERE success = false;

-- Data retention: auto-delete records older than 7 years (SOC 2 / PCI-DSS)
-- Uncomment and schedule via pg_cron or a Celery beat task:
-- DELETE FROM security_audit_log WHERE created_at < NOW() - INTERVAL '7 years';

COMMENT ON TABLE security_audit_log IS
'Immutable security audit log. Never update or delete rows manually. '
'All operator logins, approvals, rejections, and payment events are recorded here. '
'Required for SOC 2 CC7 (system operations) and PCI-DSS Requirement 10.';
