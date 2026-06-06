"""Ship I: pre-booking KB retry fields.

Adds:
- pre_booking_inquiries.blocked_by_gap_topics (text[])
- pre_booking_inquiries.triggered_by (text)
- operator_prebooking_queue_read_models.blocked_by_gap_topics (jsonb)
- operator_prebooking_queue_read_models.triggered_by (text)
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql


revision = "083_ship_i_kb_retry_fields"
down_revision = "082_knowledge_gap_drafts"
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

    pbi_cols = _column_names(bind, "pre_booking_inquiries")
    if "blocked_by_gap_topics" not in pbi_cols:
        op.add_column(
            "pre_booking_inquiries",
            sa.Column(
                "blocked_by_gap_topics",
                postgresql.ARRAY(sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::text[]"),
            ),
        )
    if "triggered_by" not in pbi_cols:
        op.add_column(
            "pre_booking_inquiries",
            sa.Column("triggered_by", sa.Text(), nullable=True),
        )

    queue_cols = _column_names(bind, "operator_prebooking_queue_read_models")
    if queue_cols:
        if "blocked_by_gap_topics" not in queue_cols:
            op.add_column(
                "operator_prebooking_queue_read_models",
                sa.Column(
                    "blocked_by_gap_topics",
                    postgresql.JSONB(astext_type=sa.Text()),
                    nullable=False,
                    server_default=text("'[]'::jsonb"),
                ),
            )
        if "triggered_by" not in queue_cols:
            op.add_column(
                "operator_prebooking_queue_read_models",
                sa.Column("triggered_by", sa.Text(), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    queue_cols = _column_names(bind, "operator_prebooking_queue_read_models")
    if "triggered_by" in queue_cols:
        op.drop_column("operator_prebooking_queue_read_models", "triggered_by")
    if "blocked_by_gap_topics" in queue_cols:
        op.drop_column("operator_prebooking_queue_read_models", "blocked_by_gap_topics")

    pbi_cols = _column_names(bind, "pre_booking_inquiries")
    if "triggered_by" in pbi_cols:
        op.drop_column("pre_booking_inquiries", "triggered_by")
    if "blocked_by_gap_topics" in pbi_cols:
        op.drop_column("pre_booking_inquiries", "blocked_by_gap_topics")
