"""
test_context_builder_agent_faq.py — Phase 2 Session 1 verification gates.

Focused tests for the ContextBuilderAgent FAQ-list enhancement.

The Phase 2 seam map specifies that ContextBuilderAgent must expose the
full FAQ list at `property_knowledge.faq` (not just `faq_count`) so that
downstream specialists — HouseRulesAgent, AccessAgent, and later
specialists — can ground answers without a second knowledge-service
call. This file pins that contract:

  * Backward-compat: faq_count and HVAC synthetic facts still surface,
    so the AC-slice path is unchanged.
  * New surface: property_knowledge.faq is a sanitized list of
    {question, answer, [category], [source]} dicts and is also listed in
    evidence_keys.
  * Sanitization: malformed entries are dropped, fields are truncated,
    and the list is capped to bound bundle size.
  * Empty/missing FAQ: the new key is absent and is NOT in evidence_keys
    (we don't want specialists citing a key that points at nothing).
  * Proactive parity: build_for_proactive surfaces the same FAQ list.

The legacy knowledge object (_LegacyKnowledgeCompat) duck-types `.facts`,
`.faq`, `.sections`, so these tests use a small fake of that shape rather
than touching the real ConciergeKnowledgeService or the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.messaging_brain.agents.context_builder_agent import (
    ContextBuilderAgent,
    _FAQ_FIELD_MAX_CHARS,
    _FAQ_LIST_MAX_ENTRIES,
)
from app.services.orchestration.messaging_brain_contracts import (
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    OutboundIntent,
    Urgency,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fakes & helpers
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class _LegacyKnowledgeFake:
    """Minimal stand-in for ConciergeKnowledgeService._LegacyKnowledgeCompat.

    Mirrors the duck-type contract ContextBuilderAgent reads:
      .facts (dict), .faq (list), .sections (dict).
    """
    property_external_id: Optional[str] = None
    facts: dict = field(default_factory=dict)
    sections: dict = field(default_factory=dict)
    faq: list = field(default_factory=list)


def _make_inbound(
    text: str = "what time is check in?",
    tenant_id: str = "11111111-1111-1111-1111-111111111111",
    property_code: str = "GULF_VIEW_204",
) -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id="MSG_FAQ_TEST_001",
        tenant_id=tenant_id,
        channel="sms",
        source_provider="twilio",
        text=text,
        guest_phone="+18505551234",
        property_code=property_code,
    )


def _make_classification(
    intent_type: IntentType = IntentType.QUESTION,
    intent_topic: str = "general",
) -> MessageClassification:
    return MessageClassification(
        intent_type=intent_type,
        intent_topic=intent_topic,
        confidence=0.8,
        urgency=Urgency.LOW,
    )


def _make_outbound(
    tenant_id: str = "11111111-1111-1111-1111-111111111111",
    property_code: str = "GULF_VIEW_204",
) -> OutboundIntent:
    return OutboundIntent(
        tenant_id=tenant_id,
        trigger_type="system_pre_arrival",
        property_code=property_code,
    )


def _agent_with_knowledge(knowledge: Optional[_LegacyKnowledgeFake]) -> ContextBuilderAgent:
    """Construct a ContextBuilderAgent whose knowledge service is mocked
    to return the given knowledge object."""
    fake_service = MagicMock()
    fake_service.get_for_property = AsyncMock(return_value=knowledge)
    return ContextBuilderAgent(knowledge_service=fake_service)


# ─────────────────────────────────────────────────────────────────────────────
# Import smoke test (called out in the seam-map expected tests)
# ─────────────────────────────────────────────────────────────────────────────


def test_context_builder_module_imports_cleanly():
    """The module imports and exposes ContextBuilderAgent + the cap
    constants. If this fails, every downstream test will fail — having
    a focused smoke test isolates module-level import errors."""
    from app.services.messaging_brain.agents import context_builder_agent

    assert hasattr(context_builder_agent, "ContextBuilderAgent")
    assert context_builder_agent._FAQ_LIST_MAX_ENTRIES > 0
    assert context_builder_agent._FAQ_FIELD_MAX_CHARS > 0


# ─────────────────────────────────────────────────────────────────────────────
# Backward compatibility — Phase 1.3 behavior preserved
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_faq_count_still_surfaces_when_faq_present():
    """faq_count and its evidence key must still appear so the existing
    AC-slice pipeline and any consumers built on the old summary signal
    keep working unchanged."""
    knowledge = _LegacyKnowledgeFake(
        faq=[
            {"question": "How does the AC work?",
             "answer": "Thermostat is in the hallway. Set to 72°F."},
        ],
    )
    agent = _agent_with_knowledge(knowledge)

    bundle = await agent.build(
        _make_inbound(), _make_classification(), db_session=MagicMock(),
    )

    assert bundle.property_knowledge.get("faq_count") == 1
    assert "property_knowledge.faq_count" in bundle.evidence_keys


@pytest.mark.asyncio
async def test_hvac_synthetic_fact_still_surfaces():
    """The AC-slice depends on property_facts.hvac_info being derived
    from FAQ entries that mention HVAC terms. The new full-FAQ surface
    must not displace that synthetic fact."""
    knowledge = _LegacyKnowledgeFake(
        faq=[
            {"question": "How does the AC work?",
             "answer": "Thermostat is in the hallway. Set to 72°F."},
            {"question": "Is there a grill?",
             "answer": "Yes, gas grill on the back deck."},
        ],
    )
    agent = _agent_with_knowledge(knowledge)

    bundle = await agent.build(
        _make_inbound(), _make_classification(), db_session=MagicMock(),
    )

    assert "hvac_info" in bundle.property_facts
    assert "property_facts.hvac_info" in bundle.evidence_keys
    # Only the HVAC entry — the grill entry is not a hit.
    hvac_entries = bundle.property_facts["hvac_info"]
    assert len(hvac_entries) == 1
    assert "thermostat" in hvac_entries[0]["answer"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# New behavior — full FAQ list surfaced
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_faq_list_surfaced_in_property_knowledge():
    """The headline contract: the full normalized FAQ list shows up at
    property_knowledge.faq and is registered in evidence_keys so
    downstream specialists may cite it."""
    knowledge = _LegacyKnowledgeFake(
        faq=[
            {"question": "Are pets allowed?",
             "answer": "Sorry, no pets."},
            {"question": "Where do we park?",
             "answer": "Two spaces in the driveway, no street parking."},
            {"question": "Is there a pool?",
             "answer": "Community pool, open 8am–10pm."},
        ],
    )
    agent = _agent_with_knowledge(knowledge)

    bundle = await agent.build(
        _make_inbound(), _make_classification(), db_session=MagicMock(),
    )

    surfaced = bundle.property_knowledge.get("faq")
    assert isinstance(surfaced, list)
    assert len(surfaced) == 3
    assert "property_knowledge.faq" in bundle.evidence_keys

    # Every surfaced entry has at minimum question + answer, both non-empty.
    for entry in surfaced:
        assert entry["question"]
        assert entry["answer"]

    # Ordering is preserved from the underlying knowledge object.
    assert surfaced[0]["question"] == "Are pets allowed?"
    assert surfaced[2]["question"] == "Is there a pool?"


@pytest.mark.asyncio
async def test_faq_list_passthrough_fields_preserved():
    """category and source on FAQ entries are preserved when present.
    Other fields (confidence, usage_count, created_by, etc.) are dropped
    so the in-context shape stays narrow and predictable."""
    knowledge = _LegacyKnowledgeFake(
        faq=[
            {
                "question": "Are pets allowed?",
                "answer": "Sorry, no pets.",
                "category": "house_rules",
                "source": "operator_dashboard",
                "confidence": 0.92,
                "usage_count": 14,
                "created_by": "operator_dashboard",
            },
        ],
    )
    agent = _agent_with_knowledge(knowledge)

    bundle = await agent.build(
        _make_inbound(), _make_classification(), db_session=MagicMock(),
    )

    surfaced = bundle.property_knowledge["faq"]
    assert len(surfaced) == 1
    entry = surfaced[0]
    # Whitelisted fields preserved
    assert entry["category"] == "house_rules"
    assert entry["source"] == "operator_dashboard"
    # Non-whitelisted fields dropped
    assert "confidence" not in entry
    assert "usage_count" not in entry
    assert "created_by" not in entry


@pytest.mark.asyncio
async def test_faq_list_skips_malformed_and_empty_entries():
    """The normalizer must defend against malformed import data:
    non-dict entries, missing question/answer, blank strings — all
    dropped silently rather than corrupting the bundle."""
    knowledge = _LegacyKnowledgeFake(
        faq=[
            {"question": "Valid Q", "answer": "Valid A"},
            "not a dict",                                 # dropped
            None,                                         # dropped
            {"question": "no answer here"},               # dropped
            {"answer": "no question here"},               # dropped
            {"question": "", "answer": "blank q"},        # dropped
            {"question": "blank a", "answer": ""},        # dropped
            {"question": "   ", "answer": "whitespace q"}, # dropped
            {"question": "Another valid", "answer": "Yes"},
        ],
    )
    agent = _agent_with_knowledge(knowledge)

    bundle = await agent.build(
        _make_inbound(), _make_classification(), db_session=MagicMock(),
    )

    surfaced = bundle.property_knowledge["faq"]
    assert len(surfaced) == 2
    assert surfaced[0]["question"] == "Valid Q"
    assert surfaced[1]["question"] == "Another valid"

    # faq_count reflects the raw input length, not the normalized length —
    # it's a measurement of the underlying knowledge object, not of what
    # we surfaced. This is intentional so the count stays comparable
    # across enhancements to the normalizer.
    assert bundle.property_knowledge["faq_count"] == 9


@pytest.mark.asyncio
async def test_faq_list_truncates_overly_long_fields():
    """Question and answer fields longer than the cap are truncated to
    bound the size of the bundle and audit row."""
    long_q = "Q" * (_FAQ_FIELD_MAX_CHARS + 500)
    long_a = "A" * (_FAQ_FIELD_MAX_CHARS + 500)
    knowledge = _LegacyKnowledgeFake(
        faq=[{"question": long_q, "answer": long_a}],
    )
    agent = _agent_with_knowledge(knowledge)

    bundle = await agent.build(
        _make_inbound(), _make_classification(), db_session=MagicMock(),
    )

    entry = bundle.property_knowledge["faq"][0]
    assert len(entry["question"]) == _FAQ_FIELD_MAX_CHARS
    assert len(entry["answer"]) == _FAQ_FIELD_MAX_CHARS


@pytest.mark.asyncio
async def test_faq_list_capped_at_max_entries():
    """Operators with very large knowledge bases shouldn't blow up the
    bundle — only the first N entries are surfaced."""
    oversized = [
        {"question": f"Q{i}", "answer": f"A{i}"}
        for i in range(_FAQ_LIST_MAX_ENTRIES + 25)
    ]
    knowledge = _LegacyKnowledgeFake(faq=oversized)
    agent = _agent_with_knowledge(knowledge)

    bundle = await agent.build(
        _make_inbound(), _make_classification(), db_session=MagicMock(),
    )

    surfaced = bundle.property_knowledge["faq"]
    assert len(surfaced) == _FAQ_LIST_MAX_ENTRIES
    # Order preserved — we kept the first N, not a random slice.
    assert surfaced[0]["question"] == "Q0"
    assert surfaced[-1]["question"] == f"Q{_FAQ_LIST_MAX_ENTRIES - 1}"
    # faq_count still reflects the true total so consumers can detect
    # truncation if they care.
    assert bundle.property_knowledge["faq_count"] == _FAQ_LIST_MAX_ENTRIES + 25


# ─────────────────────────────────────────────────────────────────────────────
# Empty / missing FAQ — the new key must NOT appear when there's nothing
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_faq_key_when_knowledge_has_empty_faq_list():
    """An empty FAQ list must not surface property_knowledge.faq, and
    the evidence key must not appear. Specialists rely on the evidence
    contract — citing a key that points at nothing would be a
    grounding-violation footgun."""
    knowledge = _LegacyKnowledgeFake(faq=[])
    agent = _agent_with_knowledge(knowledge)

    bundle = await agent.build(
        _make_inbound(), _make_classification(), db_session=MagicMock(),
    )

    assert "faq" not in bundle.property_knowledge
    assert "faq_count" not in bundle.property_knowledge
    assert "property_knowledge.faq" not in bundle.evidence_keys
    assert "property_knowledge.faq_count" not in bundle.evidence_keys


@pytest.mark.asyncio
async def test_no_faq_key_when_all_entries_are_malformed():
    """If the input FAQ list has entries but every one is malformed
    (no q/a, blank strings), faq_count still appears (it's a raw
    measurement) but property_knowledge.faq does NOT, and its evidence
    key is NOT registered. Specialists must not cite an empty list."""
    knowledge = _LegacyKnowledgeFake(
        faq=[
            "not a dict",
            {"question": "", "answer": ""},
            {"question": "   "},
        ],
    )
    agent = _agent_with_knowledge(knowledge)

    bundle = await agent.build(
        _make_inbound(), _make_classification(), db_session=MagicMock(),
    )

    assert bundle.property_knowledge.get("faq_count") == 3
    assert "faq" not in bundle.property_knowledge
    assert "property_knowledge.faq" not in bundle.evidence_keys


@pytest.mark.asyncio
async def test_no_faq_key_when_knowledge_load_fails():
    """If the knowledge service raises, the bundle should be empty —
    no faq, no faq_count, missing_context populated. Same fail-open
    behavior as Phase 1.3."""
    fake_service = MagicMock()
    fake_service.get_for_property = AsyncMock(
        side_effect=RuntimeError("connection lost"),
    )
    agent = ContextBuilderAgent(knowledge_service=fake_service)

    bundle = await agent.build(
        _make_inbound(), _make_classification(), db_session=MagicMock(),
    )

    assert "faq" not in bundle.property_knowledge
    assert "property_knowledge.faq" not in bundle.evidence_keys
    assert any("knowledge_load_failed" in m for m in bundle.missing_context)


@pytest.mark.asyncio
async def test_no_faq_key_when_no_knowledge_for_property():
    """If get_for_property returns None (no row), the bundle is empty
    and missing_context flags it."""
    agent = _agent_with_knowledge(None)

    bundle = await agent.build(
        _make_inbound(), _make_classification(), db_session=MagicMock(),
    )

    assert "faq" not in bundle.property_knowledge
    assert "property_knowledge.faq" not in bundle.evidence_keys
    assert "no_knowledge_for_property" in bundle.missing_context


# ─────────────────────────────────────────────────────────────────────────────
# Proactive entry point parity
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_proactive_build_also_surfaces_full_faq_list():
    """build_for_proactive must mirror the inbound enhancement so
    proactive specialists (welcome, pre-arrival, etc.) can also cite
    FAQ entries when grounding their drafts."""
    knowledge = _LegacyKnowledgeFake(
        faq=[
            {"question": "What's check-in time?",
             "answer": "4pm; door code arrives 24h before."},
            {"question": "Is there a grill?",
             "answer": "Yes, gas grill on back deck."},
        ],
    )
    agent = _agent_with_knowledge(knowledge)

    bundle = await agent.build_for_proactive(
        _make_outbound(), db_session=MagicMock(),
    )

    surfaced = bundle.property_knowledge.get("faq")
    assert isinstance(surfaced, list)
    assert len(surfaced) == 2
    assert "property_knowledge.faq" in bundle.evidence_keys
    assert bundle.property_knowledge["faq_count"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Step 4: end-to-end rich-context wiring
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def rich_context_off(monkeypatch):
    """Force MESSAGING_BRAIN_RICH_CONTEXT off explicitly."""
    from app.services.messaging_brain.agents import context_builder_agent

    monkeypatch.setattr(
        context_builder_agent,
        "is_messaging_brain_rich_context_enabled",
        AsyncMock(return_value=False),
    )


@pytest.fixture
def rich_context_on(monkeypatch):
    """Force MESSAGING_BRAIN_RICH_CONTEXT on for this test."""
    from app.services.messaging_brain.agents import context_builder_agent

    monkeypatch.setattr(
        context_builder_agent,
        "is_messaging_brain_rich_context_enabled",
        AsyncMock(return_value=True),
    )


def _knowledge_with_full_content() -> _LegacyKnowledgeFake:
    """Knowledge object rich enough to drive the rich-context helpers."""
    return _LegacyKnowledgeFake(
        facts={
            "check_in_time": "4pm",
            "check_out_time": "10am",
            "wifi_password": "abc123",
        },
        sections={
            "parking": "Two spaces in the driveway.",
            "pool": "Community pool, open 8am-10pm.",
        },
        faq=[
            {"question": "Are pets allowed?", "answer": "No pets allowed."},
            {"question": "Is there wifi?", "answer": "Yes, password is abc123."},
        ],
    )


@pytest.mark.asyncio
async def test_build_inbound_flag_off_leaves_rich_fields_empty(rich_context_off):
    """With the flag off, the three rich-context fields default to empty."""
    knowledge = _knowledge_with_full_content()
    agent = _agent_with_knowledge(knowledge)

    bundle = await agent.build(
        _make_inbound(), _make_classification(), db_session=MagicMock(),
    )

    assert bundle.guidebook_richness == {}
    assert bundle.guidebook_evidence == []
    assert bundle.learned_preferences_block == ""
    assert "guidebook_richness" not in bundle.evidence_keys
    assert "guidebook_evidence" not in bundle.evidence_keys
    assert "learned_preferences_block" not in bundle.evidence_keys


@pytest.mark.asyncio
async def test_build_inbound_flag_on_populates_all_three_fields(
    rich_context_on, monkeypatch,
):
    """With the flag on, all three fields populate from helper return values."""
    expected_richness = {
        "score": 0.55,
        "label": "medium",
        "summary": "Guidebook richness: medium",
    }
    expected_evidence = [
        {"source": "facts", "label": "wifi_password", "text": "abc123", "score": 2},
    ]
    expected_preferences = "Operator prefers casual tone for amenity questions."

    from app.services.messaging_brain.agents import context_builder_agent

    monkeypatch.setattr(
        context_builder_agent,
        "assess_prebooking_knowledge_richness",
        MagicMock(return_value=expected_richness),
    )
    monkeypatch.setattr(
        context_builder_agent,
        "retrieve_prebooking_property_evidence",
        MagicMock(return_value=expected_evidence),
    )
    monkeypatch.setattr(
        context_builder_agent,
        "build_preference_context",
        AsyncMock(return_value=expected_preferences),
    )

    knowledge = _knowledge_with_full_content()
    agent = _agent_with_knowledge(knowledge)

    bundle = await agent.build(
        _make_inbound(), _make_classification(), db_session=MagicMock(),
    )

    assert bundle.guidebook_richness == expected_richness
    assert bundle.guidebook_evidence == expected_evidence
    assert bundle.learned_preferences_block == expected_preferences
    assert "guidebook_richness" in bundle.evidence_keys
    assert "guidebook_evidence" in bundle.evidence_keys
    assert "learned_preferences_block" in bundle.evidence_keys


@pytest.mark.asyncio
async def test_build_inbound_flag_on_passes_message_text_to_evidence(
    rich_context_on, monkeypatch,
):
    """The inbound message.text flows into retrieve_prebooking_property_evidence."""
    ev_mock = MagicMock(return_value=[])
    from app.services.messaging_brain.agents import context_builder_agent

    monkeypatch.setattr(
        context_builder_agent,
        "assess_prebooking_knowledge_richness",
        MagicMock(return_value={"score": 0.0, "label": "none", "summary": "..."}),
    )
    monkeypatch.setattr(
        context_builder_agent,
        "retrieve_prebooking_property_evidence",
        ev_mock,
    )
    monkeypatch.setattr(
        context_builder_agent,
        "build_preference_context",
        AsyncMock(return_value=""),
    )

    agent = _agent_with_knowledge(_knowledge_with_full_content())
    inbound = _make_inbound(text="what is the wifi password please")

    await agent.build(inbound, _make_classification(), db_session=MagicMock())

    ev_mock.assert_called_once()
    assert ev_mock.call_args.kwargs["message"] == "what is the wifi password please"


@pytest.mark.asyncio
async def test_build_inbound_flag_on_passes_intent_topic_to_preference(
    rich_context_on, monkeypatch,
):
    """The classification.intent_topic flows into build_preference_context."""
    pref_mock = AsyncMock(return_value="block")
    from app.services.messaging_brain.agents import context_builder_agent

    monkeypatch.setattr(
        context_builder_agent,
        "assess_prebooking_knowledge_richness",
        MagicMock(return_value={"score": 0.5, "label": "medium", "summary": "..."}),
    )
    monkeypatch.setattr(
        context_builder_agent,
        "retrieve_prebooking_property_evidence",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        context_builder_agent,
        "build_preference_context",
        pref_mock,
    )

    agent = _agent_with_knowledge(_knowledge_with_full_content())
    classification = _make_classification(intent_topic="amenities")

    await agent.build(_make_inbound(), classification, db_session=MagicMock())

    pref_mock.assert_awaited_once()
    assert pref_mock.await_args.kwargs["intent"] == "amenities"


@pytest.mark.asyncio
async def test_build_inbound_flag_on_db_session_none_leaves_rich_fields_empty(
    rich_context_on,
):
    """db_session=None short-circuits the rich-context path."""
    agent = _agent_with_knowledge(_knowledge_with_full_content())

    bundle = await agent.build(
        _make_inbound(), _make_classification(), db_session=None,
    )

    assert bundle.guidebook_richness == {}
    assert bundle.guidebook_evidence == []
    assert bundle.learned_preferences_block == ""


@pytest.mark.asyncio
async def test_build_for_proactive_flag_off_leaves_rich_fields_empty(
    rich_context_off,
):
    """Proactive: flag off leaves all rich-context fields empty."""
    agent = _agent_with_knowledge(_knowledge_with_full_content())

    bundle = await agent.build_for_proactive(_make_outbound(), db_session=MagicMock())

    assert bundle.guidebook_richness == {}
    assert bundle.guidebook_evidence == []
    assert bundle.learned_preferences_block == ""


@pytest.mark.asyncio
async def test_build_for_proactive_flag_on_populates_richness_and_preferences(
    rich_context_on, monkeypatch,
):
    """Proactive: richness and preferences populate; evidence stays empty."""
    expected_richness = {"score": 0.55, "label": "medium", "summary": "..."}
    expected_preferences = "Operator preferences for pre-arrival messaging."

    from app.services.messaging_brain.agents import context_builder_agent

    monkeypatch.setattr(
        context_builder_agent,
        "assess_prebooking_knowledge_richness",
        MagicMock(return_value=expected_richness),
    )
    monkeypatch.setattr(
        context_builder_agent,
        "build_preference_context",
        AsyncMock(return_value=expected_preferences),
    )

    agent = _agent_with_knowledge(_knowledge_with_full_content())

    bundle = await agent.build_for_proactive(_make_outbound(), db_session=MagicMock())

    assert bundle.guidebook_richness == expected_richness
    assert bundle.guidebook_evidence == []
    assert bundle.learned_preferences_block == expected_preferences
    assert "guidebook_richness" in bundle.evidence_keys
    assert "guidebook_evidence" not in bundle.evidence_keys
    assert "learned_preferences_block" in bundle.evidence_keys


@pytest.mark.asyncio
async def test_build_for_proactive_flag_on_passes_trigger_type_to_preference(
    rich_context_on, monkeypatch,
):
    """OutboundIntent.trigger_type flows into build_preference_context."""
    pref_mock = AsyncMock(return_value="block")
    from app.services.messaging_brain.agents import context_builder_agent

    monkeypatch.setattr(
        context_builder_agent,
        "assess_prebooking_knowledge_richness",
        MagicMock(return_value={"score": 0.5, "label": "medium", "summary": "..."}),
    )
    monkeypatch.setattr(
        context_builder_agent,
        "build_preference_context",
        pref_mock,
    )

    agent = _agent_with_knowledge(_knowledge_with_full_content())
    outbound = _make_outbound()

    await agent.build_for_proactive(outbound, db_session=MagicMock())

    pref_mock.assert_awaited_once()
    assert pref_mock.await_args.kwargs["intent"] == "system_pre_arrival"


@pytest.mark.asyncio
async def test_build_inbound_preference_failure_does_not_break_other_fields(
    rich_context_on, monkeypatch,
):
    """Preference failure leaves preferences empty but richness/evidence intact."""
    expected_richness = {"score": 0.5, "label": "medium", "summary": "..."}
    expected_evidence = [{"source": "facts", "label": "x", "text": "y", "score": 1}]

    from app.services.messaging_brain.agents import context_builder_agent

    monkeypatch.setattr(
        context_builder_agent,
        "assess_prebooking_knowledge_richness",
        MagicMock(return_value=expected_richness),
    )
    monkeypatch.setattr(
        context_builder_agent,
        "retrieve_prebooking_property_evidence",
        MagicMock(return_value=expected_evidence),
    )
    monkeypatch.setattr(
        context_builder_agent,
        "build_preference_context",
        AsyncMock(side_effect=RuntimeError("preference service unavailable")),
    )

    agent = _agent_with_knowledge(_knowledge_with_full_content())

    bundle = await agent.build(
        _make_inbound(), _make_classification(), db_session=MagicMock(),
    )

    assert bundle.guidebook_richness == expected_richness
    assert bundle.guidebook_evidence == expected_evidence
    assert bundle.learned_preferences_block == ""
    assert "guidebook_richness" in bundle.evidence_keys
    assert "guidebook_evidence" in bundle.evidence_keys
    assert "learned_preferences_block" not in bundle.evidence_keys


@pytest.mark.asyncio
async def test_build_inbound_existing_faq_behavior_unchanged_when_rich_on(
    rich_context_on, monkeypatch,
):
    """Turning rich context on must not disturb the existing FAQ contract."""
    from app.services.messaging_brain.agents import context_builder_agent

    monkeypatch.setattr(
        context_builder_agent,
        "assess_prebooking_knowledge_richness",
        MagicMock(return_value={"score": 0.5, "label": "medium", "summary": "..."}),
    )
    monkeypatch.setattr(
        context_builder_agent,
        "retrieve_prebooking_property_evidence",
        MagicMock(return_value=[]),
    )
    monkeypatch.setattr(
        context_builder_agent,
        "build_preference_context",
        AsyncMock(return_value=""),
    )

    knowledge = _LegacyKnowledgeFake(
        faq=[
            {"question": "Are pets allowed?", "answer": "Sorry, no pets."},
            {"question": "Where do we park?", "answer": "Two spaces."},
            {"question": "Is there a pool?", "answer": "Community pool."},
        ],
    )
    agent = _agent_with_knowledge(knowledge)

    bundle = await agent.build(
        _make_inbound(), _make_classification(), db_session=MagicMock(),
    )

    surfaced = bundle.property_knowledge.get("faq")
    assert isinstance(surfaced, list)
    assert len(surfaced) == 3
    assert "property_knowledge.faq" in bundle.evidence_keys
    assert surfaced[0]["question"] == "Are pets allowed?"
