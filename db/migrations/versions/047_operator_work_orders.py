"""047_operator_work_orders

Durable vendor work orders tied to stay and escalation workflows.
"""

from alembic import op


revision = "047_operator_work_orders"
down_revision = "046_vendor_operational_metadata"
branch_labels = None
depends_on = None


UP_SQL = """
CREATE TABLE IF NOT EXISTS operator_work_orders (
    work_order_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                  UUID NOT NULL,
    workflow_type              TEXT NOT NULL,
    workflow_ref               TEXT NOT NULL,
    property_code              TEXT,
    vendor_id                  UUID,
    vendor_name                TEXT,
    vendor_phone               TEXT,
    issue_category             TEXT NOT NULL DEFAULT 'maintenance',
    status                     TEXT NOT NULL DEFAULT 'opened',
    priority                   TEXT NOT NULL DEFAULT 'medium',
    summary                    TEXT NOT NULL DEFAULT '',
    details                    TEXT NOT NULL DEFAULT '',
    dispatch_state             TEXT NOT NULL DEFAULT 'opened',
    eta_minutes                INTEGER,
    verification_state         TEXT NOT NULL DEFAULT 'pending',
    invoice_state              TEXT NOT NULL DEFAULT 'not_received',
    invoice_amount             NUMERIC(12,2),
    invoice_reference          TEXT,
    last_actor_label           TEXT,
    payload_json               JSONB NOT NULL DEFAULT '{}'::jsonb,
    resolution_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accepted_at                TIMESTAMPTZ,
    scheduled_at               TIMESTAMPTZ,
    completed_at               TIMESTAMPTZ,
    verified_at                TIMESTAMPTZ,
    closed_at                  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_operator_work_orders_tenant_open
    ON operator_work_orders (tenant_id, workflow_type, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_operator_work_orders_workflow
    ON operator_work_orders (tenant_id, workflow_type, workflow_ref, updated_at DESC);
"""


DOWN_SQL = """
DROP TABLE IF EXISTS operator_work_orders CASCADE;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
