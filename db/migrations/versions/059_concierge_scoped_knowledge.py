"""059_concierge_scoped_knowledge

Adds unified scoped knowledge tables for property- and tenant-scoped
knowledge entries plus normalized history rows.

Revision ID: 059_concierge_scoped_knowledge
Revises: 058_operator_gmail_creds_runtime_columns
Create Date: 2026-05-08
"""

from alembic import op


revision = "059_concierge_scoped_knowledge"
down_revision = "058_operator_gmail_creds_runtime_columns"
branch_labels = None
depends_on = None


UP_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS concierge_scoped_knowledge (
        knowledge_entry_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id UUID NOT NULL,
        scope_type TEXT NOT NULL,
        scope_target_id UUID NOT NULL,
        topic_id TEXT,
        question_text TEXT NOT NULL,
        question_key TEXT NOT NULL,
        answer_text TEXT NOT NULL,
        tags JSONB NOT NULL DEFAULT '[]'::jsonb,
        source TEXT NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_by_user_id UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        version INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concierge_scoped_knowledge_history (
        history_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        knowledge_entry_id UUID NOT NULL REFERENCES concierge_scoped_knowledge(knowledge_entry_id) ON DELETE CASCADE,
        tenant_id UUID NOT NULL,
        version INTEGER NOT NULL,
        previous_question_text TEXT,
        previous_answer_text TEXT,
        previous_metadata JSONB,
        changed_by_user_id UUID,
        change_type TEXT NOT NULL,
        changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_scoped_knowledge_tenant_scope_target
        ON concierge_scoped_knowledge (tenant_id, scope_type, scope_target_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_scoped_knowledge_tenant_topic
        ON concierge_scoped_knowledge (tenant_id, topic_id)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_scoped_knowledge_tenant_scope_topic
        ON concierge_scoped_knowledge (tenant_id, scope_type, scope_target_id, topic_id)
        WHERE topic_id IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_scoped_knowledge_tenant_scope_question_key
        ON concierge_scoped_knowledge (tenant_id, scope_type, scope_target_id, question_key)
        WHERE topic_id IS NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_scoped_knowledge_history_entry
        ON concierge_scoped_knowledge_history (knowledge_entry_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_scoped_knowledge_history_tenant_changed
        ON concierge_scoped_knowledge_history (tenant_id, changed_at DESC)
    """,
]


DOWN_STATEMENTS = [
    "DROP INDEX IF EXISTS idx_scoped_knowledge_history_tenant_changed",
    "DROP INDEX IF EXISTS idx_scoped_knowledge_history_entry",
    "DROP INDEX IF EXISTS uq_scoped_knowledge_tenant_scope_question_key",
    "DROP INDEX IF EXISTS uq_scoped_knowledge_tenant_scope_topic",
    "DROP INDEX IF EXISTS idx_scoped_knowledge_tenant_topic",
    "DROP INDEX IF EXISTS idx_scoped_knowledge_tenant_scope_target",
    "DROP TABLE IF EXISTS concierge_scoped_knowledge_history CASCADE",
    "DROP TABLE IF EXISTS concierge_scoped_knowledge CASCADE",
]


def upgrade() -> None:
    for statement in UP_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWN_STATEMENTS:
        op.execute(statement)
