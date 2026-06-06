-- create_billing_tables.sql
-- Run in Supabase SQL editor to add Stripe billing columns and tables

-- Add Stripe columns to the operators/companies table
-- (adjust table name to match your actual operators table)

-- Operator billing state
ALTER TABLE concierge_guest_sessions
    ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT,
    ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT,
    ADD COLUMN IF NOT EXISTS billing_status TEXT DEFAULT 'trial',
    ADD COLUMN IF NOT EXISTS billing_plan TEXT DEFAULT 'base',
    ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS current_period_end TIMESTAMPTZ;

-- Standalone billing table (one row per operator)
CREATE TABLE IF NOT EXISTS operator_billing (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id             TEXT NOT NULL UNIQUE,    -- matches OPERATOR_1_ID env var
    company_id              UUID,
    email                   TEXT NOT NULL,
    company_name            TEXT,

    -- Stripe identifiers
    stripe_customer_id      TEXT UNIQUE,             -- cus_...
    stripe_subscription_id  TEXT UNIQUE,             -- sub_...

    -- Billing state
    billing_status          TEXT NOT NULL DEFAULT 'trial',
    -- Values: trial | active | past_due | cancelled | suspended

    billing_plan            TEXT NOT NULL DEFAULT 'base',
    -- Values: base | growth | enterprise

    unit_count              INTEGER NOT NULL DEFAULT 0,
    monthly_amount          NUMERIC(10,2) DEFAULT 299.00,

    -- Dates
    trial_ends_at           TIMESTAMPTZ,
    current_period_start    TIMESTAMPTZ,
    current_period_end      TIMESTAMPTZ,
    cancelled_at            TIMESTAMPTZ,

    -- Timestamps
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_billing_operator_id        ON operator_billing (operator_id);
CREATE INDEX IF NOT EXISTS idx_billing_stripe_customer    ON operator_billing (stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_billing_stripe_sub         ON operator_billing (stripe_subscription_id);
CREATE INDEX IF NOT EXISTS idx_billing_status             ON operator_billing (billing_status);

-- Invoice log (for dashboard billing history tab)
CREATE TABLE IF NOT EXISTS operator_invoices (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id         TEXT NOT NULL,
    stripe_invoice_id   TEXT NOT NULL UNIQUE,        -- in_...
    stripe_customer_id  TEXT,
    amount              NUMERIC(10,2) NOT NULL,
    currency            TEXT NOT NULL DEFAULT 'usd',
    status              TEXT NOT NULL,               -- paid | open | void | uncollectible
    invoice_url         TEXT,                        -- Stripe-hosted invoice PDF
    period_start        TIMESTAMPTZ,
    period_end          TIMESTAMPTZ,
    paid_at             TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_invoices_operator ON operator_invoices (operator_id, created_at DESC);

COMMENT ON TABLE operator_billing IS
'One row per Oyvoda operator. Tracks Stripe customer/subscription IDs and billing status. '
'Updated by Stripe webhooks via /api/v1/billing/webhook.';

COMMENT ON TABLE operator_invoices IS
'Invoice history synced from Stripe webhook events (invoice.paid, invoice.payment_failed). '
'Used by operator dashboard billing tab. Never store card numbers here.';
