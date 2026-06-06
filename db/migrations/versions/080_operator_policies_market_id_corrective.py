"""Phase 4.3-L.1: reconcile missing operator_policies market_id artifacts.

Production drift verification found that migration 017 was effectively
partially applied: market_registry and market_events exist, but
operator_policies.market_id and ix_operator_policies_market_id do not.

This migration adds the missing operator_policies artifacts defensively and
stops immediately if operator_policies contains data, since that would require
a separate data-migration brief.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "080_operator_policies_market_id_corrective"
down_revision = "079_pre_booking_inquiries_archive_columns"
branch_labels = None
depends_on = None


def _table_exists(bind: sa.engine.Connection, table_name: str) -> bool:
    return inspect(bind).has_table(table_name)


def _column_exists(bind: sa.engine.Connection, table_name: str, column_name: str) -> bool:
    inspector = inspect(bind)
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _index_exists(bind: sa.engine.Connection, table_name: str, index_name: str) -> bool:
    inspector = inspect(bind)
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "operator_policies"):
        raise RuntimeError("Phase 4.3-L.1 expects operator_policies to exist")

    row_count = bind.execute(sa.text("SELECT COUNT(*) FROM operator_policies")).scalar()
    if row_count and int(row_count) > 0:
        raise RuntimeError(
            f"operator_policies has {row_count} rows; "
            "Phase 4.3-L.1 requires a separate data-migration brief before applying schema reconciliation."
        )

    if not _column_exists(bind, "operator_policies", "market_id"):
        op.add_column(
            "operator_policies",
            sa.Column("market_id", sa.String(length=100), nullable=True),
        )

    if not _index_exists(bind, "operator_policies", "ix_operator_policies_market_id"):
        op.create_index(
            "ix_operator_policies_market_id",
            "operator_policies",
            ["market_id"],
            unique=False,
        )

    op.execute(
        sa.text(
            """
            COMMENT ON COLUMN operator_policies.operator_id IS
            'Deprecated transitional legacy identity column; tenant_id is the canonical key.'
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    if _index_exists(bind, "operator_policies", "ix_operator_policies_market_id"):
        op.drop_index("ix_operator_policies_market_id", table_name="operator_policies")

    if _column_exists(bind, "operator_policies", "market_id"):
        op.drop_column("operator_policies", "market_id")
