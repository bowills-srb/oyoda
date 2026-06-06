from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


def _database_url() -> str | None:
    return os.getenv("TEST_ALEMBIC_DATABASE_URL", "").strip() or None


pytestmark = pytest.mark.skipif(
    not _database_url(),
    reason="TEST_ALEMBIC_DATABASE_URL not set for scoped knowledge schema test.",
)


def test_scoped_knowledge_tables_and_constraints_exist():
    engine = create_engine(_database_url())
    with engine.begin() as conn:
        tables = conn.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN (
                    'concierge_scoped_knowledge',
                    'concierge_scoped_knowledge_history'
                  )
                ORDER BY table_name
                """
            )
        ).scalars().all()
        assert tables == [
            "concierge_scoped_knowledge",
            "concierge_scoped_knowledge_history",
        ]

        scoped_columns = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'concierge_scoped_knowledge'
                ORDER BY ordinal_position
                """
            )
        ).scalars().all()
        history_columns = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'concierge_scoped_knowledge_history'
                ORDER BY ordinal_position
                """
            )
        ).scalars().all()

        indexes = conn.execute(
            text(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename IN (
                    'concierge_scoped_knowledge',
                    'concierge_scoped_knowledge_history'
                  )
                ORDER BY indexname
                """
            )
        ).scalars().all()

    assert scoped_columns == [
        "knowledge_entry_id",
        "tenant_id",
        "scope_type",
        "scope_target_id",
        "topic_id",
        "question_text",
        "question_key",
        "answer_text",
        "tags",
        "source",
        "metadata",
        "created_by_user_id",
        "created_at",
        "updated_at",
        "is_active",
        "version",
    ]
    assert history_columns == [
        "history_id",
        "knowledge_entry_id",
        "tenant_id",
        "version",
        "previous_question_text",
        "previous_answer_text",
        "previous_metadata",
        "changed_by_user_id",
        "change_type",
        "changed_at",
    ]
    assert "idx_scoped_knowledge_tenant_scope_target" in indexes
    assert "idx_scoped_knowledge_tenant_topic" in indexes
    assert "uq_scoped_knowledge_tenant_scope_topic" in indexes
    assert "uq_scoped_knowledge_tenant_scope_question_key" in indexes
    assert "idx_scoped_knowledge_history_entry" in indexes
    assert "idx_scoped_knowledge_history_tenant_changed" in indexes


def test_scoped_knowledge_unique_constraints_for_topic_and_question_key():
    engine = create_engine(_database_url())
    tenant_id = str(uuid.uuid4())
    scope_target_id = str(uuid.uuid4())

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO concierge_scoped_knowledge (
                    tenant_id,
                    scope_type,
                    scope_target_id,
                    topic_id,
                    question_text,
                    question_key,
                    answer_text,
                    tags,
                    source,
                    metadata
                ) VALUES (
                    :tenant_id,
                    'property',
                    :scope_target_id,
                    'pool_heating_cost',
                    'How much is pool heating?',
                    'how much is pool heating?',
                    '$50/day',
                    '["pool","heating"]'::jsonb,
                    'itest',
                    '{}'::jsonb
                )
                """
            ),
            {"tenant_id": tenant_id, "scope_target_id": scope_target_id},
        )

        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    """
                    INSERT INTO concierge_scoped_knowledge (
                        tenant_id,
                        scope_type,
                        scope_target_id,
                        topic_id,
                        question_text,
                        question_key,
                        answer_text,
                        tags,
                        source,
                        metadata
                    ) VALUES (
                        :tenant_id,
                        'property',
                        :scope_target_id,
                        'pool_heating_cost',
                        'Duplicate topic',
                        'duplicate topic',
                        '$75/day',
                        '[]'::jsonb,
                        'itest',
                        '{}'::jsonb
                    )
                    """
                ),
                {"tenant_id": tenant_id, "scope_target_id": scope_target_id},
            )

    tenant_id = str(uuid.uuid4())
    scope_target_id = str(uuid.uuid4())

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO concierge_scoped_knowledge (
                    tenant_id,
                    scope_type,
                    scope_target_id,
                    topic_id,
                    question_text,
                    question_key,
                    answer_text,
                    tags,
                    source,
                    metadata
                ) VALUES (
                    :tenant_id,
                    'tenant',
                    :scope_target_id,
                    NULL,
                    'What is the wifi password?',
                    'what is the wifi password?',
                    'See digital guidebook.',
                    '["wifi"]'::jsonb,
                    'itest',
                    '{}'::jsonb
                )
                """
            ),
            {"tenant_id": tenant_id, "scope_target_id": scope_target_id},
        )

        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    """
                    INSERT INTO concierge_scoped_knowledge (
                        tenant_id,
                        scope_type,
                        scope_target_id,
                        topic_id,
                        question_text,
                        question_key,
                        answer_text,
                        tags,
                        source,
                        metadata
                    ) VALUES (
                        :tenant_id,
                        'tenant',
                        :scope_target_id,
                        NULL,
                        'Duplicate wifi question',
                        'what is the wifi password?',
                        'Updated answer.',
                        '[]'::jsonb,
                        'itest',
                        '{}'::jsonb
                    )
                    """
                ),
                {"tenant_id": tenant_id, "scope_target_id": scope_target_id},
            )
