"""044_operator_workflow_handoffs

Durable handoff records for owner/internal and accounting workflow follow-through.
"""

from alembic import op


revision = "044_operator_workflow_handoffs"
down_revision = "043_operator_stay_workflow_read_models"
branch_labels = None
depends_on = None


UP_SQL = """
CREATE TABLE IF NOT EXISTS operator_workflow_handoffs (
    handoff_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL,
    workflow_type         TEXT NOT NULL,
    workflow_ref          TEXT NOT NULL,
    handoff_type          TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'open',
    priority              TEXT NOT NULL DEFAULT 'medium',
    property_code         TEXT,
    assignee_user_id      TEXT,
    assignee_label        TEXT,
    subject               TEXT NOT NULL DEFAULT '',
    body                  TEXT NOT NULL DEFAULT '',
    payload_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
    resolution_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at             TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_operator_workflow_handoffs_tenant_open
    ON operator_workflow_handoffs (tenant_id, workflow_type, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_operator_workflow_handoffs_workflow
    ON operator_workflow_handoffs (tenant_id, workflow_type, workflow_ref, updated_at DESC);
"""


DOWN_SQL = """
DROP TABLE IF EXISTS operator_workflow_handoffs CASCADE;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
