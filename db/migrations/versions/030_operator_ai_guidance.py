"""030_operator_ai_guidance

Adds a free-form "House Rules & AI Guidance" text bucket per operator.

The operator writes natural-language guidance like:
    - "Offer 20% off for stays of 7+ nights booked directly."
    - "We don't allow pets under any circumstance."
    - "Check-out is 11am sharp. No late checkouts unless pre-approved."
    - "Our cleaning fee is non-negotiable even for repeat guests."

This text is injected verbatim into the AI's system prompt when drafting
replies to guest inquiries, so the model writes responses consistent with
how the operator actually runs their business.

Design choices:
  - Single text blob (not structured rules) because operators think in
    plain language and every business is different. Structured rules would
    require us to predict every field an operator might want to set.
  - One row per company (company_id is UNIQUE). Easy upsert from the
    settings endpoint; no version history for now — if the operator wants
    to revert they re-type it.
  - `updated_by` captures who made the last change so a team of operators
    can see whose policy is currently live.
  - 8k character cap is intentionally generous but not unlimited — a
    runaway operator can't accidentally blow up every single AI call.

Why not a JSONB structured object?
  Because we want operators to write guidance the way they'd explain their
  business to a new employee. Treating this as prose is the point — the
  LLM reads prose natively. Structured fields would constrain what they
  can say.

Revision ID: 030_operator_ai_guidance
Revises: 029_password_reset_tokens
"""

from alembic import op


revision = "030_operator_ai_guidance"
down_revision = "029_password_reset_tokens"
branch_labels = None
depends_on = None


UP_SQL = """
CREATE TABLE IF NOT EXISTS operator_ai_guidance (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL UNIQUE,

    -- Free-form guidance text, capped at 8000 chars to keep AI prompts sane.
    -- NULL/empty means "no operator guidance" — drafts use defaults only.
    guidance_text   TEXT NOT NULL DEFAULT '',

    -- Who last edited this. NULL on initial seed, populated by the endpoint.
    updated_by      TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT guidance_text_size_ok CHECK (length(guidance_text) <= 8000)
);

-- Lookup by company_id is the only access pattern.
CREATE INDEX IF NOT EXISTS idx_ai_guidance_company
    ON operator_ai_guidance (company_id);
"""


DOWN_SQL = """
DROP TABLE IF EXISTS operator_ai_guidance CASCADE;
"""


def upgrade():
    op.execute(UP_SQL)


def downgrade():
    op.execute(DOWN_SQL)
