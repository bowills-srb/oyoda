"""048_operator_property_assets

Property asset registry plus richer ETA fields for operator work orders.
"""

from alembic import op


revision = "048_operator_property_assets"
down_revision = "047_operator_work_orders"
branch_labels = None
depends_on = None


UP_SQL = """
ALTER TABLE operator_work_orders
    ADD COLUMN IF NOT EXISTS eta_visibility_mode TEXT NOT NULL DEFAULT 'estimated',
    ADD COLUMN IF NOT EXISTS tracking_url TEXT,
    ADD COLUMN IF NOT EXISTS last_known_distance_text TEXT,
    ADD COLUMN IF NOT EXISTS asset_id UUID;

CREATE TABLE IF NOT EXISTS operator_property_assets (
    asset_id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                   UUID NOT NULL,
    property_code               TEXT NOT NULL,
    asset_type                  TEXT NOT NULL,
    asset_name                  TEXT NOT NULL,
    manufacturer                TEXT,
    model_number                TEXT,
    serial_number               TEXT,
    install_vendor_id           UUID,
    install_vendor_name         TEXT,
    install_date                DATE,
    warranty_scope              TEXT NOT NULL DEFAULT 'none',
    warranty_provider           TEXT,
    warranty_start_date         DATE,
    warranty_end_date           DATE,
    parts_warranty_end_date     DATE,
    labor_warranty_end_date     DATE,
    status                      TEXT NOT NULL DEFAULT 'active',
    condition_state             TEXT NOT NULL DEFAULT 'good',
    useful_life_years           INTEGER,
    last_service_at             TIMESTAMPTZ,
    last_work_order_id          UUID,
    notes                       TEXT NOT NULL DEFAULT '',
    metadata_json               JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_operator_property_assets_property
    ON operator_property_assets (tenant_id, property_code, asset_type, updated_at DESC);
"""


DOWN_SQL = """
DROP TABLE IF EXISTS operator_property_assets CASCADE;
ALTER TABLE operator_work_orders
    DROP COLUMN IF EXISTS asset_id,
    DROP COLUMN IF EXISTS last_known_distance_text,
    DROP COLUMN IF EXISTS tracking_url,
    DROP COLUMN IF EXISTS eta_visibility_mode;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
