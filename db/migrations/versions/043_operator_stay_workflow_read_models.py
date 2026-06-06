"""043_operator_stay_workflow_read_models

Persisted workflow read model for property-stay execution and orchestration.
"""

from alembic import op


revision = "043_operator_stay_workflow_read_models"
down_revision = "042_operator_workflow_action_queue"
branch_labels = None
depends_on = None


UP_SQL = """
CREATE TABLE IF NOT EXISTS operator_stay_workflow_read_models (
    session_id                UUID PRIMARY KEY,
    tenant_id                 UUID NOT NULL,
    session_token             TEXT NOT NULL DEFAULT '',
    property_code             TEXT NOT NULL DEFAULT '',
    workflow_stage            TEXT NOT NULL DEFAULT 'arrival_prep',
    phase                     TEXT,
    escalation_state          TEXT,
    guest_update_state        TEXT,
    workflow_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
    refreshed_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_operator_stay_workflows_tenant_stage
    ON operator_stay_workflow_read_models (tenant_id, workflow_stage, refreshed_at DESC);

CREATE INDEX IF NOT EXISTS idx_operator_stay_workflows_tenant_property
    ON operator_stay_workflow_read_models (tenant_id, property_code, refreshed_at DESC);
"""


DOWN_SQL = """
DROP TABLE IF EXISTS operator_stay_workflow_read_models CASCADE;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
