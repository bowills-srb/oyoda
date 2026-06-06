"""Ship S: add autonomy_decision to operator prebooking queue read model.

Adds:
- operator_prebooking_queue_read_models.autonomy_decision (text)

Notes:
- The read model only mirrors the live inquiry decision for fallback reads, so
  text is sufficient here; the source of truth remains
  pre_booking_inquiries.autonomy_decision.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "085_queue_read_model_autonomy_decision"
down_revision = "084_ship_s_autonomy_decision"
branch_labels = None
depends_on = None


def _column_names(bind, table_name: str) -> set[str]:
    inspector = inspect(bind)
    try:
        return {col["name"] for col in inspector.get_columns(table_name)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    queue_cols = _column_names(bind, "operator_prebooking_queue_read_models")
    if queue_cols and "autonomy_decision" not in queue_cols:
        op.add_column(
            "operator_prebooking_queue_read_models",
            sa.Column("autonomy_decision", sa.Text(), nullable=True, server_default=text("''")),
        )
        op.alter_column(
            "operator_prebooking_queue_read_models",
            "autonomy_decision",
            server_default=None,
            existing_type=sa.Text(),
        )


def downgrade() -> None:
    bind = op.get_bind()
    queue_cols = _column_names(bind, "operator_prebooking_queue_read_models")
    if "autonomy_decision" in queue_cols:
        op.drop_column("operator_prebooking_queue_read_models", "autonomy_decision")
