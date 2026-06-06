"""091_operator_property_autonomy_snapshots: append-only per-property autonomy history.

Creates operator_property_autonomy_snapshots — one row per managed property per
tenant per calendar day. This is the per-property companion to
operator_autonomy_snapshots and powers the autonomy capstone surfaces.

Revision ID: 091_operator_property_autonomy_snapshots
Revises: 090_operator_autonomy_snapshots
"""
from typing import Union

from alembic import op


revision: str = "091_operator_property_autonomy_snapshots"
down_revision: Union[str, None] = "090_operator_autonomy_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS operator_property_autonomy_snapshots (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            property_id         UUID        NOT NULL,
            snapshot_date       DATE        NOT NULL,
            signal_status       TEXT        NOT NULL DEFAULT 'computed',
            inquiry_score       NUMERIC,
            inquiry_band        TEXT        NOT NULL DEFAULT 'Insufficient Signal',
            guest_ops_band      TEXT        NOT NULL DEFAULT 'Developing',
            maintenance_band    TEXT        NOT NULL DEFAULT 'Emerging',
            turnover_band       TEXT        NOT NULL DEFAULT 'Emerging',
            components          JSONB       NOT NULL DEFAULT '{}',
            metrics             JSONB       NOT NULL DEFAULT '{}',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, property_id, snapshot_date)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_property_autonomy_snapshots_tenant_date
            ON operator_property_autonomy_snapshots (tenant_id, snapshot_date DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_property_autonomy_snapshots_property_date
            ON operator_property_autonomy_snapshots (property_id, snapshot_date DESC)
        """
    )
    op.execute(
        """
        COMMENT ON TABLE operator_property_autonomy_snapshots IS
        'Append-only per-property autonomy history. One row per active managed '
        'property per tenant per day. Do not rewrite old rows; reruns overwrite '
        'the same day only via UNIQUE (tenant_id, property_id, snapshot_date).'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_property_autonomy_snapshots_property_date")
    op.execute("DROP INDEX IF EXISTS idx_property_autonomy_snapshots_tenant_date")
    op.execute("DROP TABLE IF EXISTS operator_property_autonomy_snapshots CASCADE")
