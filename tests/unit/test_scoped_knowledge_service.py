from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.services.messaging_brain.knowledge.scoped_knowledge_service import (
    EffectiveKnowledgeResult,
    ScopedKnowledgeService,
    ScopedKnowledgeEntry,
    _compute_question_key,
    project_to_legacy_concierge_knowledge_shape,
)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, handlers):
        self._handlers = handlers
        self.executed = []
        self.flushes = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append((sql, params or {}))
        for predicate, result in self._handlers:
            if predicate(sql):
                value = result(sql, params or {}) if callable(result) else result
                return _FakeResult(value)
        raise AssertionError(f"Unexpected SQL: {sql}")

    async def flush(self):
        self.flushes += 1


def test_compute_question_key_falls_back_when_stopwords_only():
    assert _compute_question_key("the and if") == "the and if"
    assert _compute_question_key("  What   is  WiFi?  ") == "wifi"


def test_write_scoped_knowledge_rejects_bad_scope_type():
    with pytest.raises(ValueError, match="unsupported scope_type"):
        asyncio.run(
            ScopedKnowledgeService().write_scoped_knowledge(
                session=_FakeSession([]),
                tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
                user_id=UUID("00000000-0000-0000-0000-000000000002"),
                scope_type="region",
                scope_target_id=UUID("00000000-0000-0000-0000-000000000003"),
                topic_id="pool_heating_cost",
                question_text="How much is pool heating?",
                answer_text="$50/day",
                tags=["pool"],
                source="operator_gap_fill",
                metadata={},
            )
        )


def test_write_scoped_knowledge_rejects_unknown_topic():
    with pytest.raises(ValueError, match="unknown topic_id"):
        asyncio.run(
            ScopedKnowledgeService().write_scoped_knowledge(
                session=_FakeSession([]),
                tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
                user_id=UUID("00000000-0000-0000-0000-000000000002"),
                scope_type="property",
                scope_target_id=UUID("00000000-0000-0000-0000-000000000003"),
                topic_id="unknown_topic",
                question_text="How much is pool heating?",
                answer_text="$50/day",
                tags=["pool"],
                source="operator_gap_fill",
                metadata={},
            )
        )


def test_write_scoped_knowledge_creates_property_entry_with_topic():
    session = _FakeSession(
        [
            (lambda sql: "pg_advisory_xact_lock" in sql, []),
            (lambda sql: "FROM concierge_scoped_knowledge" in sql and "topic_id = :topic_id" in sql, []),
            (
                lambda sql: "INSERT INTO concierge_scoped_knowledge (" in sql,
                [SimpleNamespace(knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000010"))],
            ),
            (lambda sql: "INSERT INTO concierge_scoped_knowledge_history" in sql, []),
        ]
    )

    result = asyncio.run(
        ScopedKnowledgeService().write_scoped_knowledge(
            session=session,
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
            user_id=UUID("00000000-0000-0000-0000-000000000002"),
            scope_type="property",
            scope_target_id=UUID("00000000-0000-0000-0000-000000000003"),
            topic_id="pool_heating_cost",
            question_text="How much is pool heating?",
            answer_text="$50/day extra",
            tags=["pool", "heating"],
            source="operator_gap_fill",
            metadata={"source_gap_id": "gap-1"},
        )
    )

    assert result.status == "created"
    assert result.scope_type == "property"
    assert result.topic_id == "pool_heating_cost"
    assert result.version == 1
    _, insert_params = next(
        (sql, params) for sql, params in session.executed if "INSERT INTO concierge_scoped_knowledge (" in sql
    )
    assert insert_params["scope_type"] == "property"
    assert insert_params["topic_id"] == "pool_heating_cost"
    assert "pool_heating_cost" in json.loads(insert_params["tags"])
    metadata = json.loads(insert_params["metadata"])
    assert metadata["source_gap_id"] == "gap-1"
    assert metadata["scope_type"] == "property"
    assert metadata["created_by_user_id"] == "00000000-0000-0000-0000-000000000002"
    assert session.flushes == 1


def test_write_scoped_knowledge_creates_tenant_entry_without_topic():
    session = _FakeSession(
        [
            (lambda sql: "pg_advisory_xact_lock" in sql, []),
            (lambda sql: "FROM concierge_scoped_knowledge" in sql and "topic_id IS NULL" in sql, []),
            (
                lambda sql: "INSERT INTO concierge_scoped_knowledge (" in sql,
                [SimpleNamespace(knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000011"))],
            ),
            (lambda sql: "INSERT INTO concierge_scoped_knowledge_history" in sql, []),
        ]
    )

    result = asyncio.run(
        ScopedKnowledgeService().write_scoped_knowledge(
            session=session,
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
            user_id=UUID("00000000-0000-0000-0000-000000000002"),
            scope_type="tenant",
            scope_target_id=UUID("00000000-0000-0000-0000-000000000001"),
            topic_id=None,
            question_text="  What is the wifi password?  ",
            answer_text=" See guidebook. ",
            tags=["wifi"],
            source="dashboard_kb",
            metadata={},
        )
    )

    assert result.status == "created"
    assert result.scope_type == "tenant"
    assert result.topic_id is None
    assert result.question_key == "password wifi"


def test_write_scoped_knowledge_accepts_property_group_scope():
    session = _FakeSession(
        [
            (lambda sql: "pg_advisory_xact_lock" in sql, []),
            (lambda sql: "FROM concierge_scoped_knowledge" in sql and "topic_id = :topic_id" in sql, []),
            (
                lambda sql: "INSERT INTO concierge_scoped_knowledge (" in sql,
                [SimpleNamespace(knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000012"))],
            ),
            (lambda sql: "INSERT INTO concierge_scoped_knowledge_history" in sql, []),
        ]
    )

    result = asyncio.run(
        ScopedKnowledgeService().write_scoped_knowledge(
            session=session,
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
            user_id=UUID("00000000-0000-0000-0000-000000000002"),
            scope_type="property_group",
            scope_target_id=UUID("00000000-0000-0000-0000-000000000003"),
            topic_id="pet_policy",
            question_text="Are pets allowed in this complex?",
            answer_text="Dogs allowed with approval.",
            tags=["pet_policy"],
            source="dashboard_kb",
            metadata={},
        )
    )

    assert result.status == "created"
    assert result.scope_type == "property_group"


def test_write_scoped_knowledge_updates_existing_topic_entry_and_archives_history():
    existing = SimpleNamespace(
        knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000020"),
        topic_id="pool_heating_cost",
        question_text="How much is pool heating?",
        question_key="cost heating pool",
        answer_text="$40/day",
        metadata={
            "created_at": "2026-05-08T00:00:00+00:00",
            "created_by_user_id": "00000000-0000-0000-0000-000000000099",
            "version": 1,
        },
        version=1,
        created_at=None,
    )
    session = _FakeSession(
        [
            (lambda sql: "pg_advisory_xact_lock" in sql, []),
            (lambda sql: "FROM concierge_scoped_knowledge" in sql and "topic_id = :topic_id" in sql, [existing]),
            (lambda sql: "INSERT INTO concierge_scoped_knowledge_history" in sql, []),
            (lambda sql: "UPDATE concierge_scoped_knowledge" in sql, []),
        ]
    )

    result = asyncio.run(
        ScopedKnowledgeService().write_scoped_knowledge(
            session=session,
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
            user_id=UUID("00000000-0000-0000-0000-000000000002"),
            scope_type="property",
            scope_target_id=UUID("00000000-0000-0000-0000-000000000003"),
            topic_id="pool_heating_cost",
            question_text="How much is pool heating?",
            answer_text="$55/day",
            tags=["pool"],
            source="operator_gap_fill",
            metadata={"source_gap_id": "gap-2"},
        )
    )

    assert result.status == "updated"
    assert result.previous_version_archived is True
    assert result.version == 2
    history_params = session.executed[2][1]
    assert history_params["previous_answer_text"] == "$40/day"
    update_params = next(
        params for sql, params in session.executed if "UPDATE concierge_scoped_knowledge" in sql
    )
    metadata = json.loads(update_params["metadata"])
    assert metadata["source_gap_id"] == "gap-2"
    assert metadata["version"] == 2


def test_write_scoped_knowledge_updates_existing_question_key_entry():
    existing = SimpleNamespace(
        knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000021"),
        topic_id=None,
        question_text="What is the wifi password?",
        question_key="password wifi",
        answer_text="Old answer",
        metadata={"created_at": "2026-05-08T00:00:00+00:00", "version": 2},
        version=2,
        created_at=None,
    )
    session = _FakeSession(
        [
            (lambda sql: "pg_advisory_xact_lock" in sql, []),
            (lambda sql: "FROM concierge_scoped_knowledge" in sql and "topic_id IS NULL" in sql, [existing]),
            (lambda sql: "INSERT INTO concierge_scoped_knowledge_history" in sql, []),
            (lambda sql: "UPDATE concierge_scoped_knowledge" in sql, []),
        ]
    )

    result = asyncio.run(
        ScopedKnowledgeService().write_scoped_knowledge(
            session=session,
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
            user_id=UUID("00000000-0000-0000-0000-000000000002"),
            scope_type="tenant",
            scope_target_id=UUID("00000000-0000-0000-0000-000000000001"),
            topic_id=None,
            question_text="What is the wifi password?",
            answer_text="New answer",
            tags=["wifi"],
            source="dashboard_kb",
            metadata={},
        )
    )

    assert result.status == "updated"
    assert result.version == 3


def test_write_scoped_knowledge_normalizes_question_key_edge_cases():
    session = _FakeSession(
        [
            (lambda sql: "pg_advisory_xact_lock" in sql, []),
            (lambda sql: "FROM concierge_scoped_knowledge" in sql and "topic_id IS NULL" in sql, []),
            (
                lambda sql: "INSERT INTO concierge_scoped_knowledge (" in sql,
                [SimpleNamespace(knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000030"))],
            ),
            (lambda sql: "INSERT INTO concierge_scoped_knowledge_history" in sql, []),
        ]
    )

    result = asyncio.run(
        ScopedKnowledgeService().write_scoped_knowledge(
            session=session,
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
            user_id=UUID("00000000-0000-0000-0000-000000000002"),
            scope_type="tenant",
            scope_target_id=UUID("00000000-0000-0000-0000-000000000001"),
            topic_id=None,
            question_text="the and if",
            answer_text="Fallback key works",
            tags=[],
            source="dashboard_kb",
            metadata={},
        )
    )

    assert result.question_key == "the and if"


def test_write_scoped_knowledge_last_write_wins_for_serialized_calls():
    service = ScopedKnowledgeService()
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    user_id = UUID("00000000-0000-0000-0000-000000000002")
    scope_target_id = UUID("00000000-0000-0000-0000-000000000003")
    created = SimpleNamespace(knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000050"))
    existing = SimpleNamespace(
        knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000050"),
        topic_id="pool_heating_cost",
        question_text="How much is pool heating?",
        question_key="cost heating pool",
        answer_text="$50/day",
        metadata={"created_at": "2026-05-08T00:00:00+00:00", "version": 1},
        version=1,
        created_at=None,
    )
    select_calls = {"count": 0}

    def _select_result(sql, _params):
        select_calls["count"] += 1
        return [] if select_calls["count"] == 1 else [existing]

    session = _FakeSession(
        [
            (lambda sql: "pg_advisory_xact_lock" in sql, []),
            (lambda sql: "FROM concierge_scoped_knowledge" in sql and "topic_id = :topic_id" in sql, _select_result),
            (lambda sql: "INSERT INTO concierge_scoped_knowledge (" in sql, [created]),
            (lambda sql: "INSERT INTO concierge_scoped_knowledge_history" in sql, []),
            (lambda sql: "UPDATE concierge_scoped_knowledge" in sql, []),
        ]
    )

    first = asyncio.run(
        service.write_scoped_knowledge(
            session=session,
            tenant_id=tenant_id,
            user_id=user_id,
            scope_type="property",
            scope_target_id=scope_target_id,
            topic_id="pool_heating_cost",
            question_text="How much is pool heating?",
            answer_text="$50/day",
            tags=["pool"],
            source="operator_gap_fill",
            metadata={},
        )
    )
    second = asyncio.run(
        service.write_scoped_knowledge(
            session=session,
            tenant_id=tenant_id,
            user_id=user_id,
            scope_type="property",
            scope_target_id=scope_target_id,
            topic_id="pool_heating_cost",
            question_text="How much is pool heating?",
            answer_text="$60/day",
            tags=["pool"],
            source="operator_gap_fill",
            metadata={},
        )
    )

    assert first.status == "created"
    assert second.status == "updated"
    assert second.version == 2


def test_get_effective_knowledge_for_property_merges_property_and_tenant_scopes():
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    property_id = UUID("00000000-0000-0000-0000-000000000003")
    tenant_topic = SimpleNamespace(
        knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000101"),
        tenant_id=str(tenant_id),
        scope_type="tenant",
        scope_target_id=str(tenant_id),
        topic_id="pool_heating_cost",
        question_text="How much is pool heating?",
        question_key="cost heating pool",
        answer_text="$40/day",
        tags='["pool"]',
        source="dashboard_kb",
        metadata='{"origin":"tenant"}',
        created_by_user_id=str(UUID("00000000-0000-0000-0000-000000000002")),
        version=1,
        is_active=True,
    )
    tenant_freeform = SimpleNamespace(
        knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000102"),
        tenant_id=str(tenant_id),
        scope_type="tenant",
        scope_target_id=str(tenant_id),
        topic_id=None,
        question_text="What is the wifi password?",
        question_key="password wifi",
        answer_text="See guidebook.",
        tags='["wifi"]',
        source="dashboard_kb",
        metadata='{"origin":"tenant"}',
        created_by_user_id=None,
        version=1,
        is_active=True,
    )
    property_topic = SimpleNamespace(
        knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000103"),
        tenant_id=str(tenant_id),
        scope_type="property",
        scope_target_id=str(property_id),
        topic_id="pool_heating_cost",
        question_text="How much is pool heating at this home?",
        question_key="cost heating home pool",
        answer_text="$55/day",
        tags='["pool","pool_heating_cost"]',
        source="operator_gap_fill",
        metadata='{"origin":"property"}',
        created_by_user_id=str(UUID("00000000-0000-0000-0000-000000000002")),
        version=2,
        is_active=True,
    )
    property_freeform = SimpleNamespace(
        knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000104"),
        tenant_id=str(tenant_id),
        scope_type="property",
        scope_target_id=str(property_id),
        topic_id=None,
        question_text="Where do we park?",
        question_key="park",
        answer_text="In the driveway.",
        tags='["parking"]',
        source="legacy_concierge_knowledge",
        metadata='{"origin":"property"}',
        created_by_user_id=None,
        version=1,
        is_active=True,
    )
    inactive_entry = SimpleNamespace(
        knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000105"),
        tenant_id=str(tenant_id),
        scope_type="property",
        scope_target_id=str(property_id),
        topic_id="pet_policy",
        question_text="Pets?",
        question_key="pets",
        answer_text="No pets.",
        tags='["pet_policy"]',
        source="legacy_concierge_knowledge",
        metadata='{}',
        created_by_user_id=None,
        version=1,
        is_active=False,
    )
    session = _FakeSession(
        [
            (
                lambda sql: "FROM concierge_scoped_knowledge" in sql and "scope_type = :scope_type" in sql,
                lambda _sql, params: [property_topic, property_freeform, inactive_entry]
                if params["scope_type"] == "property"
                else [tenant_topic, tenant_freeform],
            )
        ]
    )

    result = asyncio.run(
        ScopedKnowledgeService().get_effective_knowledge_for_property(
            session=session,
            tenant_id=tenant_id,
            property_id=property_id,
        )
    )

    assert result.retrieval_source == "unified"
    assert result.effective_by_topic["pool_heating_cost"].answer_text == "$55/day"
    assert [entry.question_text for entry in result.effective_freeform_faq] == [
        "Where do we park?",
        "What is the wifi password?",
    ]
    assert [item.scope_origin for item in result.all_entries_with_provenance] == [
        "tenant",
        "tenant",
        "property",
        "property",
    ]


def test_get_effective_knowledge_for_property_merges_tenant_groups_then_property():
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    property_id = UUID("00000000-0000-0000-0000-000000000003")
    group_id = UUID("00000000-0000-0000-0000-000000000010")
    tenant_topic = SimpleNamespace(
        knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000101"),
        tenant_id=str(tenant_id),
        scope_type="tenant",
        scope_target_id=str(tenant_id),
        topic_id="pet_policy",
        question_text="Are pets allowed?",
        question_key="pets allowed",
        answer_text="Tenant says no pets.",
        tags='["pet_policy"]',
        source="dashboard_kb",
        metadata='{"origin":"tenant"}',
        created_by_user_id=None,
        version=1,
        is_active=True,
    )
    group_topic = SimpleNamespace(
        knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000102"),
        tenant_id=str(tenant_id),
        scope_type="property_group",
        scope_target_id=str(group_id),
        topic_id="pet_policy",
        question_text="Are pets allowed in this complex?",
        question_key="pets allowed complex",
        answer_text="Group says dogs allowed with approval.",
        tags='["pet_policy"]',
        source="dashboard_kb",
        metadata='{"origin":"group"}',
        created_by_user_id=None,
        version=1,
        is_active=True,
    )
    property_topic = SimpleNamespace(
        knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000103"),
        tenant_id=str(tenant_id),
        scope_type="property",
        scope_target_id=str(property_id),
        topic_id="pet_policy",
        question_text="Are pets allowed at this unit?",
        question_key="pets allowed unit",
        answer_text="Property says no pets.",
        tags='["pet_policy"]',
        source="dashboard_kb",
        metadata='{"origin":"property"}',
        created_by_user_id=None,
        version=1,
        is_active=True,
    )
    group_freeform = SimpleNamespace(
        knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000104"),
        tenant_id=str(tenant_id),
        scope_type="property_group",
        scope_target_id=str(group_id),
        topic_id=None,
        question_text="Where do we park in this complex?",
        question_key="park complex",
        answer_text="Use the garage level.",
        tags='["parking"]',
        source="dashboard_kb",
        metadata='{"origin":"group"}',
        created_by_user_id=None,
        version=1,
        is_active=True,
    )
    property_freeform = SimpleNamespace(
        knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000105"),
        tenant_id=str(tenant_id),
        scope_type="property",
        scope_target_id=str(property_id),
        topic_id=None,
        question_text="Where do we park at the unit?",
        question_key="park unit",
        answer_text="Park in the driveway.",
        tags='["parking"]',
        source="dashboard_kb",
        metadata='{"origin":"property"}',
        created_by_user_id=None,
        version=1,
        is_active=True,
    )
    tenant_freeform = SimpleNamespace(
        knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000106"),
        tenant_id=str(tenant_id),
        scope_type="tenant",
        scope_target_id=str(tenant_id),
        topic_id=None,
        question_text="What is the support phone?",
        question_key="support phone",
        answer_text="Call the main office.",
        tags='["support"]',
        source="dashboard_kb",
        metadata='{"origin":"tenant"}',
        created_by_user_id=None,
        version=1,
        is_active=True,
    )
    session = _FakeSession(
        [
            (
                lambda sql: "FROM property_group_memberships" in sql,
                [SimpleNamespace(property_group_id=group_id)],
            ),
            (
                lambda sql: "FROM concierge_scoped_knowledge" in sql and "scope_type = :scope_type" in sql,
                lambda _sql, params: (
                    [tenant_topic, tenant_freeform]
                    if params["scope_type"] == "tenant"
                    else [group_topic, group_freeform]
                    if params["scope_type"] == "property_group"
                    else [property_topic, property_freeform]
                ),
            ),
        ]
    )

    result = asyncio.run(
        ScopedKnowledgeService().get_effective_knowledge_for_property(
            session=session,
            tenant_id=tenant_id,
            property_id=property_id,
        )
    )

    assert result.effective_by_topic["pet_policy"].answer_text == "Property says no pets."
    assert [entry.question_text for entry in result.effective_freeform_faq] == [
        "Where do we park at the unit?",
        "Where do we park in this complex?",
        "What is the support phone?",
    ]
    assert [item.scope_origin for item in result.all_entries_with_provenance] == [
        "tenant",
        "tenant",
        "property_group",
        "property_group",
        "property",
        "property",
    ]


def test_group_lookup_failure_degrades_gracefully(caplog):
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    property_id = UUID("00000000-0000-0000-0000-000000000003")
    property_topic = SimpleNamespace(
        knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000103"),
        tenant_id=str(tenant_id),
        scope_type="property",
        scope_target_id=str(property_id),
        topic_id="pet_policy",
        question_text="Are pets allowed at this unit?",
        question_key="pets allowed unit",
        answer_text="Property says no pets.",
        tags='["pet_policy"]',
        source="dashboard_kb",
        metadata='{"origin":"property"}',
        created_by_user_id=None,
        version=1,
        is_active=True,
    )
    session = _FakeSession(
        [
            (
                lambda sql: "FROM property_group_memberships" in sql,
                lambda _sql, _params: (_ for _ in ()).throw(RuntimeError("boom")),
            ),
            (
                lambda sql: "FROM concierge_scoped_knowledge" in sql and "scope_type = :scope_type" in sql,
                lambda _sql, params: [property_topic] if params["scope_type"] == "property" else [],
            ),
        ]
    )

    result = asyncio.run(
        ScopedKnowledgeService().get_effective_knowledge_for_property(
            session=session,
            tenant_id=tenant_id,
            property_id=property_id,
        )
    )

    assert result.effective_by_topic["pet_policy"].answer_text == "Property says no pets."
    assert "group membership lookup failed" in caplog.text


def test_get_effective_knowledge_for_property_returns_empty_unified_when_no_entries_exist():
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    property_id = UUID("00000000-0000-0000-0000-000000000003")
    session = _FakeSession(
        [
            (
                lambda sql: "FROM concierge_scoped_knowledge" in sql and "scope_type = :scope_type" in sql,
                [],
            ),
        ]
    )

    result = asyncio.run(
        ScopedKnowledgeService().get_effective_knowledge_for_property(
            session=session,
            tenant_id=tenant_id,
            property_id=property_id,
        )
    )

    assert result.retrieval_source == "unified"
    assert result.effective_by_topic == {}
    assert result.effective_freeform_faq == []
    assert result.all_entries_with_provenance == []


def test_project_to_legacy_concierge_knowledge_shape_preserves_topics_and_tags():
    entry_topic = ScopedKnowledgeEntry(
        knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000201"),
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        scope_type="property",
        scope_target_id=UUID("00000000-0000-0000-0000-000000000003"),
        topic_id="pet_policy",
        question_text="Do you allow dogs?",
        question_key="allow dogs",
        answer_text="Dogs allowed with approval.",
        tags=["pets"],
        source="operator_gap_fill",
        metadata={},
        created_by_user_id=None,
        version=1,
    )
    entry_freeform = ScopedKnowledgeEntry(
        knowledge_entry_id=UUID("00000000-0000-0000-0000-000000000202"),
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        scope_type="tenant",
        scope_target_id=UUID("00000000-0000-0000-0000-000000000001"),
        topic_id=None,
        question_text="Where do we park?",
        question_key="park",
        answer_text="Use the driveway.",
        tags=["parking"],
        source="dashboard_kb",
        metadata={},
        created_by_user_id=None,
        version=1,
    )
    result = EffectiveKnowledgeResult(
        effective_by_topic={"pet_policy": entry_topic},
        effective_freeform_faq=[entry_freeform],
        all_entries_with_provenance=[],
        retrieval_source="unified",
    )

    projected = project_to_legacy_concierge_knowledge_shape(result)

    assert projected["facts"]["pet_policy"] == "Dogs allowed with approval."
    assert projected["sections"] == {}
    assert projected["faq"][0]["topic"] == "pet_policy"
    assert "pet_policy" in projected["faq"][0]["tags"]
    assert projected["faq"][1]["question"] == "Where do we park?"
