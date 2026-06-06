"""
Signal Store SQL Schema - The Canonical Contract.

This is the ONLY place market intelligence lives.

Phase 0.1 of Master Refactor Plan:
- Lock the Signal contract
- Lock the SignalBundle
- Everything downstream consumes this

CRITICAL: This schema is the contract. Do not modify without versioning.
"""

from alembic import op
import sqlalchemy as sa

# =============================================================================
# Alembic revision identifiers
# =============================================================================
revision = "001_signals_table"
down_revision = None
branch_labels = None
depends_on = None

# =============================================================================
# CANONICAL SIGNAL TABLE (Contract v1.0.0)
# =============================================================================

SIGNAL_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS signals (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    signal_type TEXT NOT NULL,
    scope TEXT NOT NULL,
    geo_id TEXT,
    property_id UUID,

    value DOUBLE PRECISION NOT NULL,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    weight_hint DOUBLE PRECISION,

    source TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    time_window TEXT NOT NULL,

    metadata JSONB,
    version TEXT NOT NULL,

    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_signals_geo_type
    ON signals (geo_id, signal_type);

CREATE INDEX IF NOT EXISTS idx_signals_property_type
    ON signals (property_id, signal_type);

CREATE INDEX IF NOT EXISTS idx_signals_tenant
    ON signals (tenant_id);

CREATE INDEX IF NOT EXISTS idx_signals_detected_at
    ON signals (detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_signals_geo_type_time
    ON signals (tenant_id, geo_id, signal_type, detected_at DESC);
"""

# =============================================================================
# Migration entrypoints
# =============================================================================

def upgrade():
    op.execute(sa.text(SIGNAL_TABLE_DDL))


def downgrade():
    op.execute("DROP TABLE IF EXISTS signals CASCADE")
