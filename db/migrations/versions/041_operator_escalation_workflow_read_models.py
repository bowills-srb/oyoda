"""041_operator_escalation_workflow_read_models

Persisted workflow read model for escalation and maintenance execution.
"""

from alembic import op


revision = "041_operator_escalation_workflow_read_models"
down_revision = "040_operator_scope_foundation"
branch_labels = None
depends_on = None


UP_SQL = """
CREATE TABLE IF NOT EXISTS operator_escalation_workflow_read_models (
    ticket_id                TEXT PRIMARY KEY,
    tenant_id                UUID NOT NULL,
    session_token            TEXT NOT NULL DEFAULT '',
    property_code            TEXT NOT NULL DEFAULT '',
    workflow_stage           TEXT NOT NULL DEFAULT 'detected',
    owner_state              TEXT,
    vendor_state             TEXT,
    guest_update_state       TEXT,
    workflow_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
    refreshed_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_operator_escalation_workflows_tenant_stage
    ON operator_escalation_workflow_read_models (tenant_id, workflow_stage, refreshed_at DESC);

CREATE INDEX IF NOT EXISTS idx_operator_escalation_workflows_tenant_property
    ON operator_escalation_workflow_read_models (tenant_id, property_code, refreshed_at DESC);
"""


DOWN_SQL = """
DROP TABLE IF EXISTS operator_escalation_workflow_read_models CASCADE;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
