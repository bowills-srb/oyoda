"""019_operator_auth.py

Creates the three tables that back the self-service operator auth system:

  1. operator_accounts      — one row per operator company (the tenant)
  2. operator_team_members  — employees/staff within an operator account
  3. operator_gmail_creds   — Gmail/Outlook OAuth credentials per operator

These tables were previously created at runtime via a startup migration that
failed silently. Moving them here ensures they exist before the app starts.

Revision ID: 019
Revises: 20260215_1620_aebd7d1703e3
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# Alembic revision identifiers
revision = "019"
down_revision = "aebd7d1703e3"
branch_labels = None
depends_on = None

# Raw SQL — keeps this readable and avoids ORM import issues at migration time
_UP = """
-- ─────────────────────────────────────────────────────────────────────────────
-- operator_accounts  (one row per STR operator company)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS operator_accounts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    email               TEXT NOT NULL UNIQUE,
    messaging_email     TEXT,
    email_provider      TEXT NOT NULL DEFAULT 'google',
    password_hash       TEXT NOT NULL,
    company_name        TEXT NOT NULL,
    owner_name          TEXT NOT NULL,
    phone               TEXT,
    pms                 TEXT NOT NULL DEFAULT 'escapia',
    property_count      INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'active',
    plan                TEXT NOT NULL DEFAULT 'growth',
    onboarding_complete BOOLEAN NOT NULL DEFAULT FALSE,
    stripe_customer_id  TEXT,
    stripe_subscription_id TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_op_accounts_email
    ON operator_accounts (email);
CREATE INDEX IF NOT EXISTS idx_op_accounts_tenant
    ON operator_accounts (tenant_id);
CREATE INDEX IF NOT EXISTS idx_op_accounts_status
    ON operator_accounts (status);

-- ─────────────────────────────────────────────────────────────────────────────
-- operator_team_members  (staff/managers within an operator account)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS operator_team_members (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id     UUID NOT NULL REFERENCES operator_accounts(id) ON DELETE CASCADE,
    tenant_id       UUID NOT NULL,
    email           TEXT NOT NULL,
    password_hash   TEXT,
    name            TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'staff',
    invite_token    TEXT UNIQUE,
    invite_expires  TIMESTAMPTZ,
    activated       BOOLEAN NOT NULL DEFAULT FALSE,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (operator_id, email)
);

CREATE INDEX IF NOT EXISTS idx_team_email
    ON operator_team_members (email);
CREATE INDEX IF NOT EXISTS idx_team_op
    ON operator_team_members (operator_id);
CREATE INDEX IF NOT EXISTS idx_team_invite
    ON operator_team_members (invite_token)
    WHERE invite_token IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- operator_gmail_creds  (OAuth refresh tokens for inbox polling)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS operator_gmail_creds (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id     UUID NOT NULL UNIQUE REFERENCES operator_accounts(id) ON DELETE CASCADE,
    tenant_id       UUID NOT NULL,
    watched_email   TEXT NOT NULL,
    refresh_token   TEXT NOT NULL,
    email_provider  TEXT NOT NULL DEFAULT 'google',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gmail_creds_op
    ON operator_gmail_creds (operator_id);
"""

_DOWN = """
DROP TABLE IF EXISTS operator_gmail_creds CASCADE;
DROP TABLE IF EXISTS operator_team_members CASCADE;
DROP TABLE IF EXISTS operator_accounts CASCADE;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
