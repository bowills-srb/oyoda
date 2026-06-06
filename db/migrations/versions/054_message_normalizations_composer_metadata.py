"""message_normalizations_composer_metadata

Adds six columns to the existing message_normalizations table to capture
LLM composer audit metadata for the messaging brain (Session 12 / Phase
C of docs/IMPLEMENTATION_QUEUE_2026_05_05.md).

Design provenance: docs/SESSION_12_COMPOSER_DESIGN.md.

The columns:

  - composer_source: which path produced the composer candidate output
    ("llm_anthropic", "llm_groq", "llm_gemini", "fallback_concatenation",
    "fallback_empty"). Distinct from the existing draft_source column,
    which remains "messaging_brain" / "legacy_concierge" / etc. Decision A
    in the C2 design review: keep draft_source's coarse-grained semantics
    intact, add composer_source as a separate refinement.

  - composer_response_text: the candidate text the composer produced.
    Recorded even in shadow mode (when the operator-facing draft came
    from the brain concatenation fallback) so side-by-side compare is
    semantically real. This is the load-bearing field for shadow-mode
    validation.

  - composer_latency_ms: end-to-end composer latency including provider
    fallthroughs.

  - composer_input_tokens / composer_output_tokens: per-call token usage
    for cost tracking. Nullable because not all providers report tokens.

  - composer_notes: JSONB list of coercion notes, fallback reasons,
    evidence-violation warnings. Defaults to '[]' so a row with no
    composer activity reads cleanly.

All columns are nullable except composer_notes, which has a default.
A row where the composer did not run (composer flag off, or composer
flag on but pipeline error before compose) will have NULLs across the
five new TEXT/INTEGER columns and an empty array in composer_notes.
This matches the empty-string-is-no-op discipline used by
update_normalization_outcome (the persistence helper that callers
will use to populate these fields).

Revision ID: 054_message_normalizations_composer_metadata
Revises: 053_inbound_classifications
Create Date: 2026-05-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "054_message_normalizations_composer_metadata"
down_revision = "053_inbound_classifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "message_normalizations",
        sa.Column("composer_source", sa.Text(), nullable=True),
    )
    op.add_column(
        "message_normalizations",
        sa.Column("composer_response_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "message_normalizations",
        sa.Column("composer_latency_ms", sa.Integer(), nullable=True),
    )
    op.add_column(
        "message_normalizations",
        sa.Column("composer_input_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "message_normalizations",
        sa.Column("composer_output_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "message_normalizations",
        sa.Column(
            "composer_notes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("message_normalizations", "composer_notes")
    op.drop_column("message_normalizations", "composer_output_tokens")
    op.drop_column("message_normalizations", "composer_input_tokens")
    op.drop_column("message_normalizations", "composer_latency_ms")
    op.drop_column("message_normalizations", "composer_response_text")
    op.drop_column("message_normalizations", "composer_source")
