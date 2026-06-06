"""040_operator_scope_foundation

Portfolio and member scope foundation for large operators.
"""

from alembic import op


revision = "040_operator_scope_foundation"
down_revision = "039_operator_prebooking_queue_read_models"
branch_labels = None
depends_on = None


UP_SQL = """
CREATE TABLE IF NOT EXISTS operator_portfolios (
    portfolio_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL,
    operator_id      UUID NOT NULL,
    portfolio_key    TEXT NOT NULL,
    display_name     TEXT NOT NULL,
    description      TEXT,
    active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, portfolio_key)
);

CREATE INDEX IF NOT EXISTS idx_operator_portfolios_tenant_active
    ON operator_portfolios (tenant_id, active, display_name);

CREATE TABLE IF NOT EXISTS operator_portfolio_properties (
    portfolio_property_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL,
    portfolio_id          UUID NOT NULL REFERENCES operator_portfolios(portfolio_id) ON DELETE CASCADE,
    property_external_id  TEXT NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (portfolio_id, property_external_id)
);

CREATE INDEX IF NOT EXISTS idx_operator_portfolio_props_tenant_property
    ON operator_portfolio_properties (tenant_id, property_external_id);

CREATE TABLE IF NOT EXISTS operator_member_scopes (
    scope_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID NOT NULL,
    member_user_id        UUID NOT NULL,
    scope_type            TEXT NOT NULL DEFAULT 'property',
    portfolio_id          UUID REFERENCES operator_portfolios(portfolio_id) ON DELETE CASCADE,
    property_external_id  TEXT,
    can_view              BOOLEAN NOT NULL DEFAULT TRUE,
    can_assign            BOOLEAN NOT NULL DEFAULT FALSE,
    can_manage_vendors    BOOLEAN NOT NULL DEFAULT FALSE,
    can_manage_settings   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_operator_member_scopes_tenant_member
    ON operator_member_scopes (tenant_id, member_user_id, scope_type);
"""


DOWN_SQL = """
DROP TABLE IF EXISTS operator_member_scopes CASCADE;
DROP TABLE IF EXISTS operator_portfolio_properties CASCADE;
DROP TABLE IF EXISTS operator_portfolios CASCADE;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
