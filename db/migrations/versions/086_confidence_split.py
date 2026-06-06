"""086_confidence_split: separate intent/draft confidence and add review verdict.

Phase 1 of the confidence cleanup. The current `pre_booking_inquiries.confidence`
column is overloaded — two pipelines write to it with two different meanings:

  1. The legacy deterministic classifier writes an intent-classification
     confidence (clamped 0.10..0.95) into it.
  2. The brain bridge overrides it with the ResponsePolicyAgent aggregate
     (mean of routed specialist confidences — soon to become min()).

Operators see one number that means different things depending on which
pipeline produced the row. The autonomy threshold gate compares against
this overloaded number. The "Taylor Molina 10%" support case was a
legacy-fallback floor being misread as "AI is 10% sure of the reply."

This migration splits the signal into three explicit columns:

  intent_confidence     — classifier's confidence about WHAT the message
                          is asking. Range 0..1, nullable.

  draft_confidence      — confidence about the DRAFT being a sendable
                          reply. From the brain composer / policy
                          aggregation. Range 0..1, nullable. The autonomy
                          threshold gate will operate ONLY on this column
                          going forward; NULL means "cannot auto-send."

  confidence_source     — explicit tag identifying which writer produced
                          the draft_confidence. Six values for now; see
                          enum below.

And adds one new column capturing the reviewer's verdict separately:

  review_verdict        — pass | revise | hold | NULL. Captures whether
                          the adversarial reviewer accepted the draft as
                          written, polished it, or held it. Lets us
                          compute brain-calibration stats later: how
                          often does the brain report high confidence on
                          drafts that downstream review catches?

Backfill strategy:
  - All existing rows get intent_confidence = current confidence value.
  - All existing rows get draft_confidence = NULL. The dashboard will
    surface these as "Intent-only" until they age out.
  - All existing rows get confidence_source = 'intent_only'. This is the
    explicit "this was written before the split" marker.
  - All existing rows get review_verdict = NULL (no reviewer ran).
  - The legacy `confidence` column stays in place for now. Phase 1 write
    paths will dual-write to BOTH columns so a rollback doesn't drop
    data. A later migration retires the legacy column once we have
    several weeks of clean dual-write data.

Confidence source vocabulary (locked):
  model_composer            — brain composer wrote it, reviewer passed
                              or polished. The healthy path.
  held_for_review           — brain wrote it, reviewer held it. Draft
                              text not shown to operator; no auto-send.
  exception_fallback        — brain raised; legacy exception path saved
                              the row. To be retired after instrumentation.
  gap_blocked               — knowledge gap held the inquiry before a
                              draft could be composed.
  deterministic_known_fact  — RESERVED for the future pre-brain
                              deterministic prefilter that answers
                              known-fact questions directly. No writes
                              today; schema is ready.
  intent_only               — backfill marker for pre-migration rows.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql


revision = "086_confidence_split"
down_revision = "085_queue_read_model_autonomy_decision"
branch_labels = None
depends_on = None


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


def _enum_exists(bind, enum_name: str) -> bool:
    result = bind.execute(
        text(
            """
            SELECT 1
            FROM pg_type
            WHERE typname = :enum_name
            LIMIT 1
            """
        ),
        {"enum_name": enum_name},
    ).scalar()
    return bool(result)


def upgrade() -> None:
    bind = op.get_bind()

    # Create the enums first if they don't already exist. Both are scoped
    # to this migration; nothing else references them yet.
    if not _enum_exists(bind, "confidence_source"):
        CONFIDENCE_SOURCE_ENUM.create(bind, checkfirst=True)
    if not _enum_exists(bind, "review_verdict"):
        REVIEW_VERDICT_ENUM.create(bind, checkfirst=True)

    pbi_cols = _column_names(bind, "pre_booking_inquiries")

    # intent_confidence: nullable, range 0..1. Backfilled below.
    if "intent_confidence" not in pbi_cols:
        op.add_column(
            "pre_booking_inquiries",
            sa.Column("intent_confidence", sa.Numeric(4, 3), nullable=True),
        )

    # draft_confidence: nullable, range 0..1. Stays NULL on backfill —
    # legacy rows do not have a brain draft confidence to assign.
    if "draft_confidence" not in pbi_cols:
        op.add_column(
            "pre_booking_inquiries",
            sa.Column("draft_confidence", sa.Numeric(4, 3), nullable=True),
        )

    # confidence_source: required after backfill. Default 'intent_only'
    # only during the initial migration; later inserts must set it
    # explicitly. We strip the server_default after the backfill.
    if "confidence_source" not in pbi_cols:
        op.add_column(
            "pre_booking_inquiries",
            sa.Column(
                "confidence_source",
                CONFIDENCE_SOURCE_ENUM,
                nullable=False,
                server_default=sa.text("'intent_only'::confidence_source"),
            ),
        )

    # review_verdict: nullable. NULL = reviewer didn't run (legacy rows,
    # or future rows where the brain raised before review).
    if "review_verdict" not in pbi_cols:
        op.add_column(
            "pre_booking_inquiries",
            sa.Column(
                "review_verdict",
                REVIEW_VERDICT_ENUM,
                nullable=True,
            ),
        )

    # Backfill: every existing row gets its current confidence value
    # copied into intent_confidence. This is the most accurate
    # historical statement — the existing column's primary usage today
    # is the classifier value for legacy-path rows, and the brain-path
    # rows had it overridden with a brain aggregate that lives in the
    # same numeric range.
    #
    # We do NOT try to retroactively distinguish which writer produced
    # which historical row. confidence_source = 'intent_only' for all
    # backfilled rows is the honest signal: "we don't know which
    # pipeline wrote this, treat it as classifier-only."
    bind.execute(
        text(
            """
            UPDATE pre_booking_inquiries
            SET intent_confidence = confidence
            WHERE intent_confidence IS NULL
              AND confidence IS NOT NULL
            """
        )
    )

    # Drop the server_default on confidence_source. Future inserts must
    # provide a value explicitly. This forces every write path to
    # declare which writer it represents, which is the whole point.
    op.alter_column(
        "pre_booking_inquiries",
        "confidence_source",
        server_default=None,
        existing_type=CONFIDENCE_SOURCE_ENUM,
        existing_nullable=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    pbi_cols = _column_names(bind, "pre_booking_inquiries")

    if "review_verdict" in pbi_cols:
        op.drop_column("pre_booking_inquiries", "review_verdict")
    if "confidence_source" in pbi_cols:
        op.drop_column("pre_booking_inquiries", "confidence_source")
    if "draft_confidence" in pbi_cols:
        op.drop_column("pre_booking_inquiries", "draft_confidence")
    if "intent_confidence" in pbi_cols:
        op.drop_column("pre_booking_inquiries", "intent_confidence")

    if _enum_exists(bind, "review_verdict"):
        REVIEW_VERDICT_ENUM.drop(bind, checkfirst=True)
    if _enum_exists(bind, "confidence_source"):
        CONFIDENCE_SOURCE_ENUM.drop(bind, checkfirst=True)
