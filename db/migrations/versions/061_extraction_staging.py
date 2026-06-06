"""061_extraction_staging

Unified staging table for deterministic, LLM, and hybrid extraction
candidates before promotion into durable operator knowledge surfaces.
"""

from alembic import op


revision = "061_extraction_staging"
down_revision = "060_document_storage_foundation"
branch_labels = None
depends_on = None


UP_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS extraction_candidates (
        candidate_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id UUID NOT NULL,
        scope_type TEXT NOT NULL,
        scope_target_id UUID NOT NULL,
        source_type TEXT NOT NULL,
        source_document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
        source_url TEXT,
        extraction_method TEXT NOT NULL,
        candidate_type TEXT NOT NULL,
        proposed_question_text TEXT,
        proposed_question_key TEXT,
        proposed_answer_text TEXT,
        proposed_topic_id TEXT,
        proposed_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
        proposed_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        confidence NUMERIC(4,3) NOT NULL DEFAULT 0.0,
        evidence_excerpt TEXT,
        source_section TEXT,
        review_status TEXT NOT NULL DEFAULT 'pending',
        reviewed_by_user_id UUID,
        reviewed_at TIMESTAMPTZ,
        review_notes TEXT,
        promoted_to_table TEXT,
        promoted_to_id UUID,
        promoted_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_extraction_candidates_tenant_review_status
        ON extraction_candidates (tenant_id, review_status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_extraction_candidates_tenant_scope_target
        ON extraction_candidates (tenant_id, scope_type, scope_target_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_extraction_candidates_tenant_source_document
        ON extraction_candidates (tenant_id, source_document_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_extraction_candidates_tenant_type_status
        ON extraction_candidates (tenant_id, candidate_type, review_status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_extraction_candidates_question_key_scope_target
        ON extraction_candidates (proposed_question_key, scope_target_id)
    """,
]


DOWN_STATEMENTS = [
    "DROP INDEX IF EXISTS idx_extraction_candidates_question_key_scope_target",
    "DROP INDEX IF EXISTS idx_extraction_candidates_tenant_type_status",
    "DROP INDEX IF EXISTS idx_extraction_candidates_tenant_source_document",
    "DROP INDEX IF EXISTS idx_extraction_candidates_tenant_scope_target",
    "DROP INDEX IF EXISTS idx_extraction_candidates_tenant_review_status",
    "DROP TABLE IF EXISTS extraction_candidates CASCADE",
]


def upgrade() -> None:
    for statement in UP_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWN_STATEMENTS:
        op.execute(statement)
