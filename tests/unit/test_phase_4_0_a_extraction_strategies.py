from __future__ import annotations

import asyncio
import re
from uuid import uuid4

import httpx
import pytest

from app.services.backfill.structured_property_backfill import (
    ANTHROPIC_MAX_RETRIES,
    FieldExtraction,
    StructuredPropertyBackfillRunner,
    _post_with_retry,
    _beach_access_type_from_text,
    _boolean_from_text,
    _coerce_numeric,
    _community_from_text,
    _extract_first_numeric,
    _extract_wifi_network_from_entries,
    _extract_wifi_network_from_text,
    _pet_friendly_from_text,
    _safe_json_loads,
    _waterfront_from_text,
)
from app.services.messaging_brain.knowledge.scoped_knowledge_service import ScopedKnowledgeEntry
from app.services.knowledge.vector_store import Document


def _entry(*, topic_id: str | None, question: str, answer: str) -> ScopedKnowledgeEntry:
    return ScopedKnowledgeEntry(
        knowledge_entry_id=uuid4(),
        tenant_id=uuid4(),
        scope_type="property",
        scope_target_id=uuid4(),
        topic_id=topic_id,
        question_text=question,
        question_key=question.lower(),
        answer_text=answer,
        tags=[],
        source="test",
        metadata={},
        created_by_user_id=None,
        version=1,
    )


def test_topic_tag_boolean_yes():
    assert _boolean_from_text("Yes, the property has a private pool for guests.") is True


def test_topic_tag_boolean_no():
    assert _boolean_from_text("No pool at this property.") is False


def test_topic_tag_boolean_ambiguous_shared_pool_is_positive():
    assert _boolean_from_text("Guests can use the shared community pool.") is True


def test_topic_tag_boolean_inverted_pet_policy():
    assert _pet_friendly_from_text("Pets are not allowed at this property.") is False


def test_regex_bedroom_extraction():
    entry = _entry(
        topic_id="sleeping_arrangement",
        question="How many bedrooms does the property have?",
        answer="This home has 3 bedrooms with king beds.",
    )
    import re

    value = _extract_first_numeric(
        [entry],
        regexes=(re.compile(r"\b(\d+)\s*(?:bedrooms?|br)\b", re.IGNORECASE),),
    )
    assert value == 3


def test_regex_max_guests_extraction():
    entry = _entry(
        topic_id="max_occupancy",
        question="What's the maximum occupancy?",
        answer="Sleeps up to 8 guests comfortably.",
    )
    import re

    value = _extract_first_numeric(
        [entry],
        regexes=(re.compile(r"\b(?:sleeps?|sleep up to|up to)\s*(\d+)\s*(?:guests?)?\b", re.IGNORECASE),),
    )
    assert value == 8


@pytest.mark.asyncio
async def test_llm_fallback_when_regex_fails():
    class _FakeLLM:
        model = "claude-haiku-4-5"

        async def extract_json(self, **kwargs):
            return {"value": 5, "confidence": 0.91, "reasoning": "explicit in prose"}, 0.0021, 1

    import re

    runner = StructuredPropertyBackfillRunner(session=None, llm_client=_FakeLLM())
    entry = _entry(
        topic_id="sleeping_arrangement",
        question="How many bedrooms does the property have?",
        answer="The upstairs layout includes two suites plus a bunk room and a downstairs guest room.",
    )
    extraction = await runner._extract_numeric_with_llm(
        output_field="bedrooms",
        topic_ids=("sleeping_arrangement",),
        topic_entries={"sleeping_arrangement": entry},
        freeform_entries=[],
        property_id=uuid4(),
        property_code="17LL",
        prompt_hint="Extract the integer bedroom count.",
        regexes=(re.compile(r"\b(\d+)\s*(?:bedrooms?|br)\b", re.IGNORECASE),),
        dry_run=True,
    )
    assert extraction.values == {"bedrooms": 5}
    assert extraction.llm_calls == 1
    assert extraction.audit["source"] == "llm_extract"


def test_topic_tag_enum_beach_access():
    assert _beach_access_type_from_text("Walk to beach in 2 minutes via the public walkover.") == "walk_to"


def test_skip_already_populated_field():
    runner = StructuredPropertyBackfillRunner(session=None)
    audit = {}
    assert runner._should_write_column("bedrooms", 4, audit) is False
    assert runner._should_write_column("parking_instructions", "Driveway for 2 cars", audit) is False


def test_idempotency_for_boolean_audited_field():
    runner = StructuredPropertyBackfillRunner(session=None)
    audit = {"has_pool": {"value": True, "source": "topic_tag_boolean"}}
    assert runner._should_write_column("has_pool", False, audit) is False


def test_wifi_network_extraction_from_faq_entries():
    wifi_entry = _entry(
        topic_id=None,
        question="What is the WiFi network?",
        answer="WiFi Network: BEACHHOUSE-5G. Password is on the fridge magnet.",
    )
    assert _extract_wifi_network_from_entries([wifi_entry]) == "BEACHHOUSE-5G"


def test_community_extraction_from_local_area_text():
    assert _community_from_text("Located in WaterColor just steps from the beach club.") == "watercolor"


def test_numeric_coercion_handles_half_bath():
    assert _coerce_numeric("3.5") == 3.5


def test_safe_json_loads_strips_markdown_fences():
    payload = """```json
{"value": 3, "confidence": "high", "reasoning": "explicit"}
```"""
    assert _safe_json_loads(payload) == {"value": 3, "confidence": "high", "reasoning": "explicit"}


def test_safe_json_loads_extracts_json_from_prose():
    payload = 'Here you go: {"value": true, "confidence": "low", "reasoning": "best guess"}'
    assert _safe_json_loads(payload) == {"value": True, "confidence": "low", "reasoning": "best guess"}


@pytest.mark.asyncio
async def test_unified_extraction_tier_1_topic_deterministic():
    runner = StructuredPropertyBackfillRunner(session=None)
    topic_entry = _entry(topic_id="pool_access", question="Pool?", answer="Yes, there is a private pool.")
    extraction = await runner._extract_field_unified(
        field_name="has_pool",
        target_columns=("has_pool",),
        topic_ids=("pool_access",),
        deterministic_fn=lambda text: True if "pool" in text.lower() else None,
        is_boolean=True,
        property_row={"id": uuid4(), "property_code": "17LL"},
        topic_entries={"pool_access": topic_entry},
        freeform_entries=[],
        dry_run=True,
    )
    assert extraction.values == {"has_pool": True}
    assert extraction.audit["source"] == "topic_tag_deterministic"


@pytest.mark.asyncio
async def test_unified_extraction_tier_2_freeform_deterministic():
    runner = StructuredPropertyBackfillRunner(session=None)
    freeform = [_entry(topic_id=None, question="Pets", answer="Sorry, no pets are allowed at this property.")]
    extraction = await runner._extract_field_unified(
        field_name="pet_friendly",
        target_columns=("pets_allowed",),
        topic_ids=("pet_policy", "pet_fee"),
        deterministic_fn=_pet_friendly_from_text,
        is_boolean=True,
        property_row={"id": uuid4(), "property_code": "17LL"},
        topic_entries={},
        freeform_entries=freeform,
        dry_run=True,
    )
    assert extraction.values == {"pets_allowed": False}
    assert extraction.audit["source"] == "freeform_keyword_deterministic"


@pytest.mark.asyncio
async def test_unified_extraction_tier_3_vector_then_llm():
    class _FakeLLM:
        model = "claude-haiku-4-5"

        async def extract_json(self, **kwargs):
            return {"value": 3, "confidence": "high", "reasoning": "vector chunk says 3 bedrooms"}, 0.001, 1

    runner = StructuredPropertyBackfillRunner(session=None, llm_client=_FakeLLM())

    async def _fake_retrieve_vector_chunks(**kwargs):
        return [
            Document(
                content="This home features 3 bedrooms and spacious common areas.",
                metadata={"tenant_id": str(uuid4()), "property_code": "17LL", "doc_type": "property_info"},
                doc_id="doc-1",
                score=0.91,
            )
        ]

    runner._retrieve_vector_chunks = _fake_retrieve_vector_chunks
    extraction = await runner._extract_field_unified(
        field_name="bedrooms",
        target_columns=("bedrooms",),
        topic_ids=("sleeping_arrangement",),
        deterministic_fn=None,
        regexes=(re.compile(r"\b(\d+)\s*(?:bedrooms?|br)\b", re.IGNORECASE),),
        is_numeric=True,
        property_row={"id": uuid4(), "property_code": "17LL"},
        topic_entries={},
        freeform_entries=[],
        dry_run=True,
    )
    assert extraction.values == {"bedrooms": 3}
    assert extraction.audit["source"] == "vector_then_llm"
    assert extraction.audit["vector_chunks_used"] == ["doc-1"]


@pytest.mark.asyncio
async def test_vector_retrieval_failure_falls_back_gracefully():
    class _FakeLLM:
        model = "claude-haiku-4-5"

        async def extract_json(self, **kwargs):
            return {"value": None, "confidence": "low", "reasoning": "not present"}, 0.0, 1

    runner = StructuredPropertyBackfillRunner(session=None, llm_client=_FakeLLM())

    async def _fake_retrieve_vector_chunks(**kwargs):
        raise RuntimeError("vector unavailable")

    runner._retrieve_vector_chunks = _fake_retrieve_vector_chunks
    extraction = await runner._extract_field_unified(
        field_name="bedrooms",
        target_columns=("bedrooms",),
        topic_ids=("sleeping_arrangement",),
        deterministic_fn=None,
        regexes=(re.compile(r"\b(\d+)\s*(?:bedrooms?|br)\b", re.IGNORECASE),),
        is_numeric=True,
        property_row={"id": uuid4(), "property_code": "17LL"},
        topic_entries={},
        freeform_entries=[],
        dry_run=True,
    )
    assert extraction.values == {}


@pytest.mark.asyncio
async def test_pets_allowed_freeform_fallback():
    runner = StructuredPropertyBackfillRunner(session=None)
    freeform = [_entry(topic_id=None, question="Pet policy", answer="No pets allowed at this home.")]
    extraction = await runner._extract_field_unified(
        field_name="pet_friendly",
        target_columns=("pets_allowed",),
        topic_ids=("pet_policy", "pet_fee"),
        deterministic_fn=_pet_friendly_from_text,
        is_boolean=True,
        property_row={"id": uuid4(), "property_code": "17LL"},
        topic_entries={},
        freeform_entries=freeform,
        dry_run=True,
    )
    assert extraction.values == {"pets_allowed": False}


@pytest.mark.asyncio
async def test_bedrooms_via_vector_then_llm():
    class _FakeLLM:
        model = "claude-haiku-4-5"

        async def extract_json(self, **kwargs):
            return {"value": 3, "confidence": "medium", "reasoning": "described in chunk"}, 0.0012, 1

    runner = StructuredPropertyBackfillRunner(session=None, llm_client=_FakeLLM())

    async def _fake_retrieve_vector_chunks(**kwargs):
        return [
            Document(
                content="Sleeping arrangements include a primary king suite, queen guest room, and bunk room.",
                metadata={"tenant_id": str(uuid4()), "property_code": "17LL", "doc_type": "property_info"},
                doc_id="doc-bedrooms",
                score=0.88,
            )
        ]

    runner._retrieve_vector_chunks = _fake_retrieve_vector_chunks
    extraction = await runner._extract_field_unified(
        field_name="bedrooms",
        target_columns=("bedrooms",),
        topic_ids=("sleeping_arrangement",),
        deterministic_fn=None,
        regexes=(),
        is_numeric=True,
        property_row={"id": uuid4(), "property_code": "17LL"},
        topic_entries={},
        freeform_entries=[],
        dry_run=True,
    )
    assert extraction.values == {"bedrooms": 3}
    assert extraction.audit["vector_chunks_used"] == ["doc-bedrooms"]


@pytest.mark.asyncio
async def test_closed_world_default_writes_false_when_no_evidence():
    class _FakeLLM:
        model = "claude-haiku-4-5"

        async def extract_json(self, **kwargs):
            return {"value": None, "confidence": "high", "reasoning": "no mention"}, 0.001, 1

    runner = StructuredPropertyBackfillRunner(session=None, llm_client=_FakeLLM())

    async def _fake_retrieve_vector_chunks(**kwargs):
        return []

    runner._retrieve_vector_chunks = _fake_retrieve_vector_chunks
    extraction = await runner._extract_field_unified(
        field_name="has_hot_tub",
        target_columns=("has_hot_tub",),
        topic_ids=("hot_tub_access",),
        deterministic_fn=_boolean_from_text,
        is_boolean=True,
        property_row={"id": uuid4(), "property_code": "17LL"},
        topic_entries={},
        freeform_entries=[],
        dry_run=True,
    )
    assert extraction.values == {"has_hot_tub": False}
    assert extraction.audit["source"] == "closed_world_default"


@pytest.mark.asyncio
async def test_closed_world_default_applied_after_llm_returns_null():
    class _FakeLLM:
        model = "claude-haiku-4-5"

        async def extract_json(self, **kwargs):
            return {"value": None, "confidence": "low", "reasoning": "not addressed"}, 0.001, 1

    runner = StructuredPropertyBackfillRunner(session=None, llm_client=_FakeLLM())

    async def _fake_retrieve_vector_chunks(**kwargs):
        return [
            Document(
                content="Guests can access the neighborhood pool and nearby beach club.",
                metadata={"tenant_id": str(uuid4()), "property_code": "17LL", "doc_type": "property_info"},
                doc_id="doc-hot-tub",
                score=0.71,
            )
        ]

    runner._retrieve_vector_chunks = _fake_retrieve_vector_chunks
    extraction = await runner._extract_field_unified(
        field_name="has_hot_tub",
        target_columns=("has_hot_tub",),
        topic_ids=("hot_tub_access",),
        deterministic_fn=_boolean_from_text,
        is_boolean=True,
        property_row={"id": uuid4(), "property_code": "17LL"},
        topic_entries={},
        freeform_entries=[],
        dry_run=True,
    )
    assert extraction.values == {"has_hot_tub": False}
    assert extraction.audit["source"] == "closed_world_default"
    assert extraction.audit["llm_response"]["value"] is None


@pytest.mark.asyncio
async def test_closed_world_not_applied_to_numeric_fields():
    class _FakeLLM:
        model = "claude-haiku-4-5"

        async def extract_json(self, **kwargs):
            return {"value": None, "confidence": "low", "reasoning": "not present"}, 0.0, 1

    runner = StructuredPropertyBackfillRunner(session=None, llm_client=_FakeLLM())

    async def _fake_retrieve_vector_chunks(**kwargs):
        return []

    runner._retrieve_vector_chunks = _fake_retrieve_vector_chunks
    extraction = await runner._extract_field_unified(
        field_name="bedrooms",
        target_columns=("bedrooms",),
        topic_ids=("sleeping_arrangement",),
        deterministic_fn=None,
        regexes=(re.compile(r"\b(\d+)\s*(?:bedrooms?|br)\b", re.IGNORECASE),),
        is_numeric=True,
        property_row={"id": uuid4(), "property_code": "17LL"},
        topic_entries={},
        freeform_entries=[],
        dry_run=True,
    )
    assert extraction.values == {}


@pytest.mark.asyncio
async def test_closed_world_not_applied_to_text_fields():
    class _FakeLLM:
        model = "claude-haiku-4-5"

        async def extract_json(self, **kwargs):
            return {"value": None, "confidence": "low", "reasoning": "not present"}, 0.0, 1

    runner = StructuredPropertyBackfillRunner(session=None, llm_client=_FakeLLM())

    async def _fake_retrieve_vector_chunks(**kwargs):
        return []

    runner._retrieve_vector_chunks = _fake_retrieve_vector_chunks
    extraction = await runner._extract_field_unified(
        field_name="wifi_network",
        target_columns=("wifi_network",),
        topic_ids=("wifi_access",),
        deterministic_fn=_extract_wifi_network_from_text,
        is_text=True,
        property_row={"id": uuid4(), "property_code": "17LL"},
        topic_entries={},
        freeform_entries=[],
        dry_run=True,
    )
    assert extraction.values == {}


@pytest.mark.asyncio
async def test_closed_world_loses_to_positive_evidence():
    runner = StructuredPropertyBackfillRunner(session=None)
    topic_entry = _entry(topic_id="hot_tub_access", question="Hot tub?", answer="Yes, there is a private hot tub.")
    extraction = await runner._extract_field_unified(
        field_name="has_hot_tub",
        target_columns=("has_hot_tub",),
        topic_ids=("hot_tub_access",),
        deterministic_fn=_boolean_from_text,
        is_boolean=True,
        property_row={"id": uuid4(), "property_code": "17LL"},
        topic_entries={"hot_tub_access": topic_entry},
        freeform_entries=[],
        dry_run=True,
    )
    assert extraction.values == {"has_hot_tub": True}
    assert extraction.audit["source"] == "topic_tag_deterministic"


@pytest.mark.asyncio
async def test_closed_world_audit_records_evidence_examined():
    class _FakeLLM:
        model = "claude-haiku-4-5"

        async def extract_json(self, **kwargs):
            return {"value": None, "confidence": "medium", "reasoning": "not addressed"}, 0.001, 1

    runner = StructuredPropertyBackfillRunner(session=None, llm_client=_FakeLLM())

    async def _fake_retrieve_vector_chunks(**kwargs):
        return [
            Document(
                content="No mention of pets here, only arrival details.",
                metadata={"tenant_id": str(uuid4()), "property_code": "17LL", "doc_type": "property_info"},
                doc_id="doc-pets",
                score=0.65,
            )
        ]

    runner._retrieve_vector_chunks = _fake_retrieve_vector_chunks
    extraction = await runner._extract_field_unified(
        field_name="pet_friendly",
        target_columns=("pets_allowed",),
        topic_ids=("pet_policy", "pet_fee"),
        deterministic_fn=_pet_friendly_from_text,
        is_boolean=True,
        property_row={"id": uuid4(), "property_code": "17LL"},
        topic_entries={},
        freeform_entries=[],
        dry_run=True,
    )
    assert extraction.values == {"pets_allowed": False}
    assert extraction.audit["source"] == "closed_world_default"
    assert "evidence_examined" in extraction.audit
    assert "vector_chunks_retrieved=1" in extraction.audit["evidence_examined"]


@pytest.mark.asyncio
async def test_pet_policy_falls_back_to_freeform():
    runner = StructuredPropertyBackfillRunner(session=None)
    freeform = [
        _entry(
            topic_id=None,
            question="Can we bring our dog?",
            answer="Sorry, no pets are allowed at this property.",
        )
    ]
    extraction = await runner._extract_pet_policy(
        topic_entries={},
        freeform_entries=freeform,
        property_id=uuid4(),
        property_code="17LL",
        dry_run=True,
    )
    assert extraction.values == {"pets_allowed": False}
    assert extraction.audit["source"] == "freeform_text_match"


@pytest.mark.asyncio
async def test_hot_tub_falls_back_to_freeform():
    runner = StructuredPropertyBackfillRunner(session=None)
    freeform = [
        _entry(
            topic_id=None,
            question="Property highlights",
            answer="The private hot tub is available for guest use year-round.",
        )
    ]
    extraction = await runner._extract_boolean_with_fallback(
        topic_id="hot_tub_access",
        output_field="has_hot_tub",
        topic_entries={},
        freeform_entries=freeform,
        property_id=uuid4(),
        property_code="17LL",
        prompt_hint="Does this property have a hot tub guests can use?",
        dry_run=True,
    )
    assert extraction.values == {"has_hot_tub": True}
    assert extraction.audit["source"] == "freeform_text_match"


def test_waterfront_unclear_returns_none():
    assert _waterfront_from_text("A lovely home near the coast with easy neighborhood access.") is None


@pytest.mark.asyncio
async def test_boolean_llm_fallback():
    class _FakeLLM:
        model = "claude-haiku-4-5"

        async def extract_json(self, **kwargs):
            return {"value": True, "confidence": "medium", "reasoning": "mentions private hot tub"}, 0.001, 1

    runner = StructuredPropertyBackfillRunner(session=None, llm_client=_FakeLLM())
    freeform = [
        _entry(
            topic_id=None,
            question="What amenities does the home include?",
            answer="Guests often ask about the spa setup in the backyard.",
        )
    ]
    extraction = await runner._extract_boolean_with_llm(
        output_field="has_hot_tub",
        entries=freeform,
        property_id=uuid4(),
        property_code="17LL",
        prompt_hint="Does this property have a hot tub guests can use?",
        dry_run=True,
    )
    assert extraction.values == {"has_hot_tub": True}
    assert extraction.llm_calls == 1
    assert extraction.audit["source"] == "llm_extract"


@pytest.mark.asyncio
async def test_anthropic_429_with_retry_after_header_respects_wait(monkeypatch):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    responses = [
        httpx.Response(429, headers={"retry-after": "1"}, json={"error": {"type": "rate_limit"}}, request=request),
        httpx.Response(200, json={"ok": True}, request=request),
    ]
    sleep_calls: list[float] = []

    class _FakeClient:
        async def post(self, **kwargs):
            return responses.pop(0)

    async def _fake_sleep(seconds: float):
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.services.backfill.structured_property_backfill.random.uniform", lambda a, b: 0.0)
    monkeypatch.setattr("app.services.backfill.structured_property_backfill.asyncio.sleep", _fake_sleep)
    response = await _post_with_retry(_FakeClient(), url="https://api.anthropic.com/v1/messages")
    assert response.status_code == 200
    assert sleep_calls == [1.0]


@pytest.mark.asyncio
async def test_anthropic_429_without_retry_after_uses_exponential_backoff(monkeypatch):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    responses = [
        httpx.Response(429, json={"error": {"type": "rate_limit"}}, request=request),
        httpx.Response(429, json={"error": {"type": "rate_limit"}}, request=request),
        httpx.Response(429, json={"error": {"type": "rate_limit"}}, request=request),
        httpx.Response(200, json={"ok": True}, request=request),
    ]
    sleep_calls: list[float] = []

    class _FakeClient:
        async def post(self, **kwargs):
            return responses.pop(0)

    async def _fake_sleep(seconds: float):
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.services.backfill.structured_property_backfill.random.uniform", lambda a, b: 0.0)
    monkeypatch.setattr("app.services.backfill.structured_property_backfill.asyncio.sleep", _fake_sleep)
    response = await _post_with_retry(_FakeClient(), url="https://api.anthropic.com/v1/messages")
    assert response.status_code == 200
    assert sleep_calls == [2.0, 4.0, 8.0]


@pytest.mark.asyncio
async def test_anthropic_429_max_retries_exceeded_raises(monkeypatch):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    sleep_calls: list[float] = []

    class _FakeClient:
        async def post(self, **kwargs):
            return httpx.Response(429, json={"error": {"type": "rate_limit"}}, request=request)

    async def _fake_sleep(seconds: float):
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.services.backfill.structured_property_backfill.random.uniform", lambda a, b: 0.0)
    monkeypatch.setattr("app.services.backfill.structured_property_backfill.asyncio.sleep", _fake_sleep)
    with pytest.raises(RuntimeError):
        await _post_with_retry(_FakeClient(), url="https://api.anthropic.com/v1/messages")
    assert len(sleep_calls) == ANTHROPIC_MAX_RETRIES


@pytest.mark.asyncio
async def test_anthropic_500_does_not_retry(monkeypatch):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    sleep_calls: list[float] = []

    class _FakeClient:
        async def post(self, **kwargs):
            return httpx.Response(500, json={"error": {"type": "server_error"}}, request=request)

    async def _fake_sleep(seconds: float):
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.services.backfill.structured_property_backfill.asyncio.sleep", _fake_sleep)
    with pytest.raises(httpx.HTTPStatusError):
        await _post_with_retry(_FakeClient(), url="https://api.anthropic.com/v1/messages")
    assert sleep_calls == []
