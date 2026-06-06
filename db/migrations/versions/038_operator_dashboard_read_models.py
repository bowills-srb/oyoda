"""038_operator_dashboard_read_models

Persisted read models for operator dashboard surfaces.

This starts with the overview/dashboard-summary contract so the backend can
serve a cheap, canonical summary payload instead of recomputing all overview
counts on every request forever.
"""

from alembic import op


revision = "038_operator_dashboard_read_models"
down_revision = "037_pms_booking_guest_identity"
branch_labels = None
depends_on = None


UP_SQL = """
CREATE TABLE IF NOT EXISTS operator_dashboard_read_models (
    tenant_id      UUID PRIMARY KEY,
    summary_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    refreshed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_operator_dashboard_read_models_refreshed
    ON operator_dashboard_read_models (refreshed_at DESC);
"""


DOWN_SQL = """
DROP TABLE IF EXISTS operator_dashboard_read_models CASCADE;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
