"""090_operator_autonomy_snapshots: append-only portfolio autonomy history.

WHAT THIS MIGRATION DOES:

  Creates operator_autonomy_snapshots — one row per tenant per calendar day,
  accumulating indefinitely. This is the OPPOSITE of operator_dashboard_read_models
  (which keeps only the latest row per tenant with ON CONFLICT UPDATE). Here,
  old rows STAY so trend queries ("52% → 84% over 6 months") are possible.

  The calendar cost of not starting: history cannot be backfilled. Every day
  this table exists, the trend window grows by one point.

SCHEMA:
  portfolio_score: 0..1 (float), the directional posture score. NOT presented
    as a percentage to operators without rounding; stored with full precision
    for tuning.
  domain_bands: {
      inquiry: {score: float, band: "Autonomous|Developing|Emerging"},
      guest_ops: "Developing",
      maintenance: "Emerging",
      turnover: "Emerging"
    }
    Inquiry is the only "computed" domain in v1. Others carry band words, never
    fabricated numbers (same discipline as Home hero placeholder and Property
    Readiness coverage labels).
  components: {readiness: float, escalation: float, behavior: "neutral"}
    Stored for transparency and tuning — lets us verify each input's
    contribution without re-running the scoring query.

IDEMPOTENCY:
  UNIQUE (tenant_id, snapshot_date) with ON CONFLICT DO UPDATE means:
    - Re-running the job same day overwrites that day's row (idempotent).
    - Running on different days accumulates history.

Revision ID: 090_operator_autonomy_snapshots
Revises: 089_operator_learning_tables
"""
from typing import Union

from alembic import op


revision: str = "090_operator_autonomy_snapshots"
down_revision: Union[str, None] = "089_operator_learning_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS operator_autonomy_snapshots (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

            -- tenant_id stores operator_accounts.tenant_id (the canonical UUID).
            -- NOT operator_accounts.id. Join on tenant_id, never on id.
            tenant_id       UUID        NOT NULL,

            snapshot_date   DATE        NOT NULL,

            -- Directional portfolio score: 0.0 (no coverage/high pressure)
            -- to 1.0 (full coverage/low pressure). Communicated as posture,
            -- not precision — do not present to operators as a hard percentage
            -- without appropriate hedging language.
            portfolio_score NUMERIC,

            -- Per-domain bands.
            -- inquiry: {score: float, band: "Autonomous"|"Developing"|"Emerging"}
            -- guest_ops/maintenance/turnover: band word only (not fabricated nums)
            domain_bands    JSONB       NOT NULL DEFAULT '{}',

            -- Score component breakdown for transparency and future tuning.
            -- {readiness: float, escalation: float, behavior: "neutral"}
            components      JSONB       NOT NULL DEFAULT '{}',

            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            -- One row per tenant per day. Re-running same day overwrites;
            -- different days accumulate. History is the point.
            UNIQUE (tenant_id, snapshot_date)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_autonomy_snapshots_tenant_date
            ON operator_autonomy_snapshots (tenant_id, snapshot_date DESC)
        """
    )
    op.execute(
        """
        COMMENT ON TABLE operator_autonomy_snapshots IS
        'Append-only portfolio autonomy history. One row per tenant per day. '
        'UNIQUE (tenant_id, snapshot_date) keeps reruns idempotent while '
        'accumulating a trend. DO NOT truncate or overwrite old rows.'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_autonomy_snapshots_tenant_date")
    op.execute("DROP TABLE IF EXISTS operator_autonomy_snapshots CASCADE")
