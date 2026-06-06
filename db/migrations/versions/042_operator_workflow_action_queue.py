"""042_operator_workflow_action_queue

Persistent action queue for operator workflow execution.
"""

from alembic import op


revision = "042_operator_workflow_action_queue"
down_revision = "041_operator_escalation_workflow_read_models"
branch_labels = None
depends_on = None


UP_SQL = """
CREATE TABLE IF NOT EXISTS operator_workflow_action_queue (
    action_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL,
    workflow_type         TEXT NOT NULL DEFAULT 'escalation',
    workflow_ref          TEXT NOT NULL,
    action_type           TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'ready',
    priority              TEXT NOT NULL DEFAULT 'medium',
    property_code         TEXT,
    payload_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_json           JSONB NOT NULL DEFAULT '{}'::jsonb,
    due_at                TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at          TIMESTAMPTZ,
    UNIQUE (workflow_type, workflow_ref, action_type)
);

CREATE INDEX IF NOT EXISTS idx_operator_workflow_actions_tenant_status
    ON operator_workflow_action_queue (tenant_id, workflow_type, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_operator_workflow_actions_tenant_property
    ON operator_workflow_action_queue (tenant_id, property_code, status, updated_at DESC);
"""


DOWN_SQL = """
DROP TABLE IF EXISTS operator_workflow_action_queue CASCADE;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
