"""026_dashboard_tables

Adds the remaining tables the operator dashboard needs:

  1. vendor_categories    — operator-defined vendor category slots (restaurants,
                           watersports, etc.) with display icons + ordering
  2. vendors              — individual vendor records with priority ordering
                           inside each category; AI recommends by priority
  3. operator_settings    — per-operator/tenant key-value settings store for
                           AI confidence thresholds, notification preferences,
                           AI concierge name, etc. JSONB for flexibility
  4. operator_notifications — per-operator in-app notification feed shown in
                              the dashboard bell icon panel

All tables are tenant-scoped. `concierge_escalations` already exists from
migration 011/023 and is joined through `concierge_guest_sessions.token` to
get tenant_id, so no changes to escalations are needed here.

Revision ID: 026_dashboard_tables
Revises: 025_event_intel_fields
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "026_dashboard_tables"
down_revision = "025_event_intel_fields"
branch_labels = None
depends_on = None


UP_SQL = """
-- ─────────────────────────────────────────────────────────────────────────────
-- vendor_categories — operator-defined category slots
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vendor_categories (
    category_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    slug            TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    icon            TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, slug)
);
CREATE INDEX IF NOT EXISTS idx_vendor_cat_tenant
    ON vendor_categories (tenant_id, sort_order);

-- ─────────────────────────────────────────────────────────────────────────────
-- vendors — individual vendor records (priority-ordered within a category)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vendors (
    vendor_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    category_id     UUID REFERENCES vendor_categories(category_id) ON DELETE SET NULL,
    category_slug   TEXT NOT NULL,
    name            TEXT NOT NULL,
    phone           TEXT,
    website         TEXT,
    ai_script       TEXT,
    internal_notes  TEXT,
    priority        INTEGER NOT NULL DEFAULT 1,
    apply_scope     TEXT NOT NULL DEFAULT 'all',
    property_ids    JSONB NOT NULL DEFAULT '[]'::jsonb,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    referral_count  INTEGER NOT NULL DEFAULT 0,
    last_referred_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_vendors_tenant_cat
    ON vendors (tenant_id, category_slug, priority);
CREATE INDEX IF NOT EXISTS idx_vendors_tenant_active
    ON vendors (tenant_id, active);

-- ─────────────────────────────────────────────────────────────────────────────
-- operator_settings — key-value settings bag per operator/tenant
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS operator_settings (
    tenant_id       UUID PRIMARY KEY,
    operator_id     UUID NOT NULL,
    -- AI behavior thresholds
    prebooking_autosend_threshold  INTEGER NOT NULL DEFAULT 95,
    escalation_urgency_threshold   INTEGER NOT NULL DEFAULT 70,
    kb_gap_detection_threshold     INTEGER NOT NULL DEFAULT 40,
    -- AI identity
    ai_concierge_name  TEXT NOT NULL DEFAULT 'Your Concierge',
    -- Notification preferences (which events page the operator)
    notify_emergency        BOOLEAN NOT NULL DEFAULT TRUE,
    notify_maintenance      BOOLEAN NOT NULL DEFAULT TRUE,
    notify_prebooking       BOOLEAN NOT NULL DEFAULT TRUE,
    notify_kb_gaps          BOOLEAN NOT NULL DEFAULT FALSE,
    notify_weekly_analytics BOOLEAN NOT NULL DEFAULT TRUE,
    -- KB gap suppressed categories
    kb_suppressed_categories JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- AI paused (danger zone)
    ai_paused        BOOLEAN NOT NULL DEFAULT FALSE,
    ai_paused_at     TIMESTAMPTZ,
    -- Catch-all extension bag
    extra            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- operator_notifications — in-app bell-icon notification feed
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS operator_notifications (
    notification_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL,
    kind             TEXT NOT NULL,
    severity         TEXT NOT NULL DEFAULT 'info',
    title            TEXT NOT NULL,
    body             TEXT,
    link_target      TEXT,
    link_label       TEXT,
    read_at          TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_op_notif_tenant_created
    ON operator_notifications (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_op_notif_tenant_unread
    ON operator_notifications (tenant_id, read_at)
    WHERE read_at IS NULL;
"""


DOWN_SQL = """
DROP TABLE IF EXISTS operator_notifications CASCADE;
DROP TABLE IF EXISTS operator_settings CASCADE;
DROP TABLE IF EXISTS vendors CASCADE;
DROP TABLE IF EXISTS vendor_categories CASCADE;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
