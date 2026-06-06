"""087_queue_read_model_confidence_split: mirror confidence_split columns into queue read model.

Migration 086_confidence_split added four columns to pre_booking_inquiries:
  - intent_confidence    (numeric, nullable)
  - draft_confidence     (numeric, nullable)
  - confidence_source    (enum, not null)
  - review_verdict       (enum, nullable)

The operator dashboard reads from operator_prebooking_queue_read_models for
fallback reads when the live join fails, AND that table is the seam where
the dashboard's display layer sources its row state. Without these columns
on the read model, the dashboard has no way to render "Held by review" vs
"Brain composed" vs "Knowledge gap blocked" — it would have to guess from
draft_text emptiness, which is exactly the kind of inferring-state-from-
content that the confidence split was meant to eliminate.

This migration mirrors the four pre_booking_inquiries columns into the
read model. Reuses the existing enum types from migration 086.

The queue service (PrebookingQueueService._persist_rows) will be updated
in the same commit to populate these columns when it syncs draft rows.

Notes:
- intent_confidence and draft_confidence use numeric here rather than the
  source table's numeric(4,3) because the read model has historically
  used loose numeric for confidence; matching that pattern.
- confidence_source is nullable here, unlike the source table where it's
  required. Read model rows can predate the column being populated; we
  don't want a NOT NULL constraint that fails the persist on legacy rows.
  The dashboard treats NULL confidence_source as "unknown / pre-split".
- review_verdict is nullable matching the source table.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql


revision = "087_queue_read_model_confidence_split"
down_revision = "086_confidence_split"
branch_labels = None
depends_on = None


# Reference the enums created by migration 086. create_type=False because
# the types already exist in the database; we just want references for
# column type declarations.
CONFIDENCE_SOURCE_ENUM = postgresql.ENUM(
    "model_composer",
    "held_for_review",
    "exception_fallback",
    "gap_blocked",
    "deterministic_known_fact",
    "intent_only",
    name="confidence_source",
    create_type=False,
)

REVIEW_VERDICT_ENUM = postgresql.ENUM(
    "pass",
    "revise",
    "hold",
    name="review_verdict",
    create_type=False,
)


def _column_names(bind, table_name: str) -> set[str]:
    inspector = inspect(bind)
    try:
        return {col["name"] for col in inspector.get_columns(table_name)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    queue_cols = _column_names(bind, "operator_prebooking_queue_read_models")

    # Bail safely if the queue read model table doesn't exist yet in this
    # environment. The dashboard tolerates a missing table; this migration
    # should too.
    if not queue_cols:
        return

    if "intent_confidence" not in queue_cols:
        op.add_column(
            "operator_prebooking_queue_read_models",
            sa.Column("intent_confidence", sa.Numeric(4, 3), nullable=True),
        )

    if "draft_confidence" not in queue_cols:
        op.add_column(
            "operator_prebooking_queue_read_models",
            sa.Column("draft_confidence", sa.Numeric(4, 3), nullable=True),
        )

    if "confidence_source" not in queue_cols:
        op.add_column(
            "operator_prebooking_queue_read_models",
            sa.Column(
                "confidence_source",
                CONFIDENCE_SOURCE_ENUM,
                nullable=True,
            ),
        )

    if "review_verdict" not in queue_cols:
        op.add_column(
            "operator_prebooking_queue_read_models",
            sa.Column(
                "review_verdict",
                REVIEW_VERDICT_ENUM,
                nullable=True,
            ),
        )

    # Backfill from pre_booking_inquiries. Only fills rows where the
    # corresponding source row has data — leaves NULL elsewhere, which is
    # the right "unknown" signal for the dashboard.
    bind.execute(
        text(
            """
            UPDATE operator_prebooking_queue_read_models AS q
            SET
                intent_confidence = pbi.intent_confidence,
                draft_confidence = pbi.draft_confidence,
                confidence_source = pbi.confidence_source,
                review_verdict = pbi.review_verdict
            FROM pre_booking_inquiries pbi
            WHERE pbi.draft_id = q.draft_id
              AND pbi.tenant_id = q.tenant_id
              AND (
                  q.intent_confidence IS NULL
                  OR q.draft_confidence IS NULL
                  OR q.confidence_source IS NULL
                  OR q.review_verdict IS NULL
              )
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    queue_cols = _column_names(bind, "operator_prebooking_queue_read_models")

    if "review_verdict" in queue_cols:
        op.drop_column("operator_prebooking_queue_read_models", "review_verdict")
    if "confidence_source" in queue_cols:
        op.drop_column("operator_prebooking_queue_read_models", "confidence_source")
    if "draft_confidence" in queue_cols:
        op.drop_column("operator_prebooking_queue_read_models", "draft_confidence")
    if "intent_confidence" in queue_cols:
        op.drop_column("operator_prebooking_queue_read_models", "intent_confidence")
