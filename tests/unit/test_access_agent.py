"""
test_access_agent.py — Phase 2 Session 3 verification gates.

Focused tests for AccessAgent. Covers:

  * Import smoke and package-level export.
  * Direct-fact path (the headline new shape vs HouseRulesAgent):
      - wifi from property_facts.wifi
      - check_in from property_facts.check_in
      - check_out from property_facts.check_out
      - direct fact preferred over FAQ when both are available
      - direct-fact key detected but value missing → FAQ fallback
      - missing_info notes the absent property_facts key when only FAQ
        produced an answer
  * FAQ fallback path:
      - door codes / parking / generic "how do I get in" answered via
        ConciergeKnowledgeService.best_faq_answer
      - confidence band reflects local match score
      - FAQ list present but no match → no_match decision
      - knowledge_service.best_faq_answer raises → fail-open
  * No-context path (no FAQ list, no direct fact value).
  * Door-code risk flag invariants:
      - access_credential_answer set on door-code questions regardless
        of which path produced the answer
      - access_credential_answer NOT set on wifi/check-in questions
      - flag is set even when no answer is produced (it's a property
        of the question, not the answer — same pattern as
        house_rules_edge_case)
  * Evidence contract:
      - cites property_facts.{wifi,check_in,check_out} only when present
        in context.evidence_keys
      - cites property_knowledge.faq only when present in evidence_keys
      - never cites both keys for a single decision (only one path runs)
  * No ModuleEvents are ever emitted (per Phase 2 seam map).
  * Recommended action is DRAFT_ONLY across the board (Phase 2
    learning phase; auto-send eligibility is a future session).
  * Default orchestrator construction registers AccessAgent under
    its expected name so the router's "access" topic resolves to
    the real agent rather than the stub.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from app.services.messaging_brain import GuestMessageBrainOrchestrator
from app.services.messaging_brain.agents.access_agent import (
    AccessAgent,
    _DIRECT_FACT_CONFIDENCE,
    _FAQ_STRONG_CONFIDENCE,
    _FAQ_WEAK_CONFIDENCE,
    _NO_MATCH_CONFIDENCE,
    _matches_any,
    _DOOR_CODE_PATTERNS,
    _WIFI_PATTERNS,
    _CHECK_IN_PATTERNS,
    _CHECK_OUT_PATTERNS,
    _score_faq_match,
)
from app.services.orchestration.messaging_brain_contracts import (
    GuestContextBundle,
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    MessagingLifecycle,
    RecommendedAction,
    Urgency,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_inbound(
    text: str,
    *,
    message_id: str = "MSG_ACCESS_TEST_001",
    tenant_id: str = "11111111-1111-1111-1111-111111111111",
    property_code: str = "GULF_VIEW_204",
) -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id=message_id,
        tenant_id=tenant_id,
        channel="sms",
        source_provider="twilio",
        text=text,
        guest_phone="+18505551234",
        property_code=property_code,
    )


def _make_classification() -> MessageClassification:
    """Access classification per the IntakeAgent translation table:
    QUICK_ANSWER → QUESTION/access/MEDIUM."""
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic="access",
        confidence=0.88,
        urgency=Urgency.MEDIUM,
    )


def _make_context(
    *,
    facts: Optional[Dict[str, Any]] = None,
    faq: Optional[List[Dict[str, Any]]] = None,
    include_fact_evidence_keys: bool = True,
    include_faq_evidence_key: bool = True,
) -> GuestContextBundle:
    """Build a context bundle that mimics what ContextBuilderAgent
    produces post-Session 1: structured facts at property_facts, FAQ
    list at property_knowledge.faq, both registered in evidence_keys
    when populated.
    """
    property_facts: Dict[str, Any] = {}
    property_knowledge: Dict[str, Any] = {}
    evidence_keys: List[str] = []

    if facts:
        for key, value in facts.items():
            property_facts[key] = value
            if include_fact_evidence_keys:
                evidence_keys.append(f"property_facts.{key}")

    if faq is not None:
        property_knowledge["faq_count"] = len(faq)
        evidence_keys.append("property_knowledge.faq_count")
        property_knowledge["faq"] = list(faq)
        if include_faq_evidence_key:
            evidence_keys.append("property_knowledge.faq")

    return GuestContextBundle(
        tenant_id="11111111-1111-1111-1111-111111111111",
        property_code="GULF_VIEW_204",
        lifecycle=MessagingLifecycle.IN_STAY,
        property_facts=property_facts,
        property_knowledge=property_knowledge,
        evidence_keys=evidence_keys,
    )


def _agent_with_answer(answer: Optional[str]) -> AccessAgent:
    """AccessAgent whose injected knowledge_service returns a fixed
    best_faq_answer result. Tests assert on the resulting decision."""
    fake = MagicMock()
    fake.best_faq_answer = MagicMock(return_value=answer)
    return AccessAgent(knowledge_service=fake)


def _agent_with_raising_service() -> AccessAgent:
    fake = MagicMock()
    fake.best_faq_answer = MagicMock(side_effect=RuntimeError("boom"))
    return AccessAgent(knowledge_service=fake)


# ─────────────────────────────────────────────────────────────────────────────
# Import smoke
# ─────────────────────────────────────────────────────────────────────────────


def test_access_agent_module_imports_cleanly():
    """Module imports and exposes the AccessAgent class with the
    expected public surface."""
    from app.services.messaging_brain.agents import access_agent

    assert hasattr(access_agent, "AccessAgent")
    agent = access_agent.AccessAgent()
    assert agent.name == "AccessAgent"
    assert agent.handles_topics == ("access",)


def test_access_agent_exported_from_package():
    """AccessAgent is reachable from the package surface."""
    from app.services.messaging_brain import AccessAgent as A1
    from app.services.messaging_brain.agents import AccessAgent as A2

    assert A1 is A2 is AccessAgent


# ─────────────────────────────────────────────────────────────────────────────
# Direct-fact-key detection (regex parity)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "What's the wifi password?",
        "How do I connect to the internet?",
        "Is there a network name?",
        "Can I get the WI-FI?",
    ],
)
def test_wifi_patterns_match_typical_phrasings(text: str):
    assert _matches_any(text, _WIFI_PATTERNS) is True


@pytest.mark.parametrize(
    "text",
    [
        "What time is check-in?",
        "When can we arrive?",
        "What's checkin time?",
        "When can I get there?",
    ],
)
def test_check_in_patterns_match_typical_phrasings(text: str):
    assert _matches_any(text, _CHECK_IN_PATTERNS) is True


@pytest.mark.parametrize(
    "text",
    [
        "What time is checkout?",
        "When do we leave?",
        "What's check-out?",
    ],
)
def test_check_out_patterns_match_typical_phrasings(text: str):
    assert _matches_any(text, _CHECK_OUT_PATTERNS) is True


@pytest.mark.parametrize(
    "text",
    [
        "What's the door code?",
        "How do we get in?",
        "Where's the lockbox?",
        "What's the keypad combo?",
        "Is there an entry code?",
        "Where do I find the key?",
        "What's the gate code?",
        "How do I enter the property?",
    ],
)
def test_door_code_patterns_match_typical_phrasings(text: str):
    assert _matches_any(text, _DOOR_CODE_PATTERNS) is True


@pytest.mark.parametrize(
    "text",
    [
        # False-positive guards — words that contain access substrings
        # but are not access questions.
        "I'd like a keyboard for working remotely.",  # "key" in keyboard
        "The pool is encoded with chlorine.",          # "code" in encoded
        "Looking for outdoor furniture.",              # "door" in outdoor
        "Mickey Mouse posters on the wall.",           # "key" in Mickey
    ],
)
def test_door_code_patterns_reject_false_positives(text: str):
    """Word-boundary regex must keep door-code matchers from firing on
    unrelated words. If this test ever fails, a real guest could trip
    the access_credential_answer flag on a totally unrelated question
    and produce noisy operator review queues."""
    assert _matches_any(text, _DOOR_CODE_PATTERNS) is False, (
        f"false positive on: {text!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Direct-fact path
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wifi_question_uses_property_fact_directly():
    """A wifi question with property_facts.wifi populated answers from
    the structured fact, with high confidence. The FAQ is never
    consulted — even if it would have matched."""
    agent = _agent_with_answer("FAQ should NOT be used")
    context = _make_context(
        facts={"wifi": "GuestNet / pass: beach123"},
        # FAQ also present, but the direct path takes precedence.
        faq=[{"question": "wifi?", "answer": "from FAQ — wrong path"}],
    )

    decision = await agent.run(
        message=_make_inbound("What's the wifi password?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.confidence == pytest.approx(_DIRECT_FACT_CONFIDENCE)
    assert "GuestNet / pass: beach123" in decision.draft_text
    # The FAQ short-circuit fires before best_faq_answer is consulted.
    agent._knowledge.best_faq_answer.assert_not_called()
    assert decision.evidence_used == ["property_facts.wifi"]
    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY


@pytest.mark.asyncio
async def test_check_in_question_uses_property_fact_directly():
    agent = _agent_with_answer(None)
    context = _make_context(facts={"check_in": "4:00 PM"})

    decision = await agent.run(
        message=_make_inbound("What time is check-in?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.confidence == pytest.approx(_DIRECT_FACT_CONFIDENCE)
    assert "4:00 PM" in decision.draft_text
    assert decision.evidence_used == ["property_facts.check_in"]
    assert "house_rules_edge_case" not in decision.risk_flags


@pytest.mark.asyncio
async def test_check_out_question_uses_property_fact_directly():
    agent = _agent_with_answer(None)
    context = _make_context(facts={"check_out": "10:00 AM"})

    decision = await agent.run(
        message=_make_inbound("What time is checkout?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.confidence == pytest.approx(_DIRECT_FACT_CONFIDENCE)
    assert "10:00 AM" in decision.draft_text
    assert decision.evidence_used == ["property_facts.check_out"]


@pytest.mark.asyncio
async def test_direct_fact_takes_precedence_over_faq():
    """When BOTH a direct fact and an FAQ entry are available for the
    same question, the direct fact wins. This is the contract that
    keeps wifi/check-in/check-out at high confidence when the
    operator has authored them as structured facts, even if FAQ
    entries also exist."""
    agent = _agent_with_answer("from FAQ")
    context = _make_context(
        facts={"check_in": "4 PM"},
        faq=[{"question": "What time is check-in?",
              "answer": "Different answer from FAQ"}],
    )

    decision = await agent.run(
        message=_make_inbound("What time is check-in?"),
        classification=_make_classification(),
        context=context,
    )

    assert "4 PM" in decision.draft_text
    assert "from FAQ" not in decision.draft_text
    assert decision.confidence == pytest.approx(_DIRECT_FACT_CONFIDENCE)
    assert decision.evidence_used == ["property_facts.check_in"]
    agent._knowledge.best_faq_answer.assert_not_called()


@pytest.mark.asyncio
async def test_direct_fact_key_recognized_but_value_missing_falls_back_to_faq():
    """The agent recognizes the question is about wifi but the
    operator hasn't populated property_facts.wifi yet. We fall through
    to the FAQ path. missing_info should NOT prematurely flag the
    direct-fact gap when the FAQ found an answer — the gap is only
    interesting when the question went unanswered."""
    agent = _agent_with_answer("Wifi: GuestNet / pass: beach123")
    context = _make_context(
        facts={},  # no wifi populated
        faq=[{"question": "What's the wifi?",
              "answer": "Wifi: GuestNet / pass: beach123"}],
    )

    decision = await agent.run(
        message=_make_inbound("What's the wifi password?"),
        classification=_make_classification(),
        context=context,
    )

    # Answered via FAQ.
    assert decision.draft_text == "Wifi: GuestNet / pass: beach123"
    # Confidence reflects the FAQ band, not the direct-fact band.
    assert decision.confidence in (
        pytest.approx(_FAQ_STRONG_CONFIDENCE),
        pytest.approx(_FAQ_WEAK_CONFIDENCE),
    )
    assert decision.evidence_used == ["property_knowledge.faq"]
    # We did call the knowledge service for this one.
    agent._knowledge.best_faq_answer.assert_called_once()


@pytest.mark.asyncio
async def test_direct_fact_key_recognized_value_missing_no_faq_match_flags_gap():
    """When direct fact value is missing AND FAQ produced no match,
    the audit should record both gaps in missing_info so the operator
    sees what we'd have liked: the direct fact key AND a FAQ entry
    for this question."""
    agent = _agent_with_answer(None)  # no FAQ match
    context = _make_context(
        facts={},  # no wifi populated
        faq=[{"question": "Where do we park?", "answer": "Driveway only."}],
    )

    decision = await agent.run(
        message=_make_inbound("What's the wifi password?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.confidence == pytest.approx(_NO_MATCH_CONFIDENCE)
    assert "property_facts.wifi" in decision.missing_info
    assert "faq_match_for_question" in decision.missing_info


# ─────────────────────────────────────────────────────────────────────────────
# FAQ fallback path
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_door_code_question_answered_via_faq():
    """Door codes don't have a direct-fact slot — they live in FAQ.
    Confidence sits in the FAQ band, not the direct-fact band."""
    faq = [
        {"question": "What's the door code?",
         "answer": "Door code is 4827 — works on the front keypad."},
    ]
    agent = _agent_with_answer(
        "Door code is 4827 — works on the front keypad."
    )
    context = _make_context(faq=faq)

    decision = await agent.run(
        message=_make_inbound("What's the door code?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.draft_text == (
        "Door code is 4827 — works on the front keypad."
    )
    assert decision.confidence in (
        pytest.approx(_FAQ_STRONG_CONFIDENCE),
        pytest.approx(_FAQ_WEAK_CONFIDENCE),
    )
    assert decision.evidence_used == ["property_knowledge.faq"]


@pytest.mark.asyncio
async def test_parking_question_answered_via_faq():
    """Parking is a forward-looking AccessAgent topic per the seam map.
    Today it doesn't classify as access (it goes through KNOWLEDGE_LOOKUP),
    but if a parking question DOES land here we want it answered from FAQ."""
    faq = [
        {"question": "Where do we park?",
         "answer": "Two spaces in the driveway, no street parking."},
    ]
    agent = _agent_with_answer(
        "Two spaces in the driveway, no street parking."
    )
    context = _make_context(faq=faq)

    decision = await agent.run(
        message=_make_inbound("Where do we park?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.draft_text == (
        "Two spaces in the driveway, no street parking."
    )
    # No door-code flag for a parking question.
    assert "access_credential_answer" not in decision.risk_flags


@pytest.mark.asyncio
async def test_faq_present_but_no_match_returns_no_match_decision():
    """FAQ list present, no entry matches → no_match path. We still
    cite property_knowledge.faq as evidence (we did consult it)."""
    faq = [
        {"question": "Where do we park?", "answer": "Driveway only."},
    ]
    agent = _agent_with_answer(None)
    context = _make_context(faq=faq)

    decision = await agent.run(
        message=_make_inbound("Where is the seashell museum?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.confidence == pytest.approx(_NO_MATCH_CONFIDENCE)
    assert decision.evidence_used == ["property_knowledge.faq"]
    assert "faq_match_for_question" in decision.missing_info


@pytest.mark.asyncio
async def test_knowledge_service_exception_falls_back_to_no_match():
    """If best_faq_answer raises, the agent must fail open."""
    faq = [{"question": "What's the door code?", "answer": "1234"}]
    agent = _agent_with_raising_service()
    context = _make_context(faq=faq)

    decision = await agent.run(
        message=_make_inbound("What's the door code?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert decision.confidence == pytest.approx(_NO_MATCH_CONFIDENCE)
    # Door-code risk flag still set even though we failed to answer.
    assert "access_credential_answer" in decision.risk_flags


# ─────────────────────────────────────────────────────────────────────────────
# No-context path
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_faq_and_no_direct_fact_returns_holding_draft():
    """Neither FAQ list nor a direct property_facts value is available.
    The agent defers with a holding draft and missing_info populated."""
    agent = _agent_with_answer("never called")
    context = _make_context(faq=None, facts={})  # nothing at all

    decision = await agent.run(
        message=_make_inbound("How do we get in?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert decision.confidence == pytest.approx(_NO_MATCH_CONFIDENCE)
    assert "property_knowledge.faq" in decision.missing_info
    # When there's no FAQ at all, the knowledge service is not consulted.
    agent._knowledge.best_faq_answer.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Door-code risk flag invariants
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_door_code_question_via_faq_carries_risk_flag():
    """Door code answered via FAQ — flag is set."""
    faq = [{"question": "What's the door code?", "answer": "1234"}]
    agent = _agent_with_answer("1234")
    context = _make_context(faq=faq)

    decision = await agent.run(
        message=_make_inbound("What's the door code?"),
        classification=_make_classification(),
        context=context,
    )

    assert "access_credential_answer" in decision.risk_flags


@pytest.mark.asyncio
async def test_wifi_question_does_not_carry_door_code_flag():
    """Wifi is not credential-physical-access. Flag must NOT be set."""
    agent = _agent_with_answer(None)
    context = _make_context(facts={"wifi": "GuestNet / pass: beach123"})

    decision = await agent.run(
        message=_make_inbound("What's the wifi password?"),
        classification=_make_classification(),
        context=context,
    )

    assert "access_credential_answer" not in decision.risk_flags


@pytest.mark.asyncio
async def test_check_in_question_does_not_carry_door_code_flag():
    agent = _agent_with_answer(None)
    context = _make_context(facts={"check_in": "4 PM"})

    decision = await agent.run(
        message=_make_inbound("What time is check-in?"),
        classification=_make_classification(),
        context=context,
    )

    assert "access_credential_answer" not in decision.risk_flags


@pytest.mark.asyncio
async def test_door_code_flag_set_even_on_no_match():
    """The flag is a property of the question, not the answer.
    Same pattern as house_rules_edge_case from Session 2."""
    agent = _agent_with_answer(None)
    context = _make_context(faq=[
        {"question": "Where do we park?", "answer": "Driveway."},
    ])

    decision = await agent.run(
        message=_make_inbound("What's the door code?"),
        classification=_make_classification(),
        context=context,
    )

    assert "access_credential_answer" in decision.risk_flags
    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY


@pytest.mark.asyncio
async def test_door_code_flag_set_even_with_no_context():
    """Door-code question + empty bundle → still flagged."""
    agent = _agent_with_answer("never called")
    context = _make_context(faq=None, facts={})

    decision = await agent.run(
        message=_make_inbound("How do we get in?"),
        classification=_make_classification(),
        context=context,
    )

    assert "access_credential_answer" in decision.risk_flags


# ─────────────────────────────────────────────────────────────────────────────
# Evidence contract
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evidence_keys_strict_subset_for_direct_fact_path():
    """When the bundle has property_facts.wifi but didn't register the
    evidence key, the agent must NOT cite it.

    This pins the strict-subset rule: the agent never invents an
    evidence key the orchestrator would reject."""
    agent = _agent_with_answer(None)
    context = _make_context(
        facts={"wifi": "GuestNet"},
        include_fact_evidence_keys=False,  # value present, key not registered
    )

    decision = await agent.run(
        message=_make_inbound("What's the wifi password?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.evidence_used == []
    assert set(decision.evidence_used).issubset(set(context.evidence_keys))


@pytest.mark.asyncio
async def test_evidence_keys_strict_subset_for_faq_path():
    """Same strict-subset rule for the FAQ path."""
    faq = [{"question": "Door code?", "answer": "1234"}]
    agent = _agent_with_answer("1234")
    context = _make_context(faq=faq, include_faq_evidence_key=False)

    decision = await agent.run(
        message=_make_inbound("What's the door code?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.evidence_used == []


@pytest.mark.asyncio
async def test_only_one_evidence_path_cited_per_decision():
    """A given decision cites either property_facts.X OR
    property_knowledge.faq, never both. The two paths are mutually
    exclusive in the agent — direct fact short-circuits before FAQ is
    consulted, and FAQ runs only if direct fact didn't apply.

    This invariant matters for downstream consumers reasoning about
    where the answer came from. If we ever emit both, that's a bug."""
    # Direct-fact path
    agent = _agent_with_answer(None)
    ctx = _make_context(
        facts={"wifi": "GuestNet"},
        faq=[{"question": "wifi?", "answer": "GuestNet"}],
    )
    decision = await agent.run(
        message=_make_inbound("What's the wifi?"),
        classification=_make_classification(),
        context=ctx,
    )
    assert decision.evidence_used == ["property_facts.wifi"]
    assert "property_knowledge.faq" not in decision.evidence_used

    # FAQ path
    agent2 = _agent_with_answer("1234")
    ctx2 = _make_context(
        faq=[{"question": "door code?", "answer": "1234"}],
    )
    decision2 = await agent2.run(
        message=_make_inbound("What's the door code?"),
        classification=_make_classification(),
        context=ctx2,
    )
    assert decision2.evidence_used == ["property_knowledge.faq"]
    assert all(
        not k.startswith("property_facts.")
        for k in decision2.evidence_used
    )


# ─────────────────────────────────────────────────────────────────────────────
# Always-DRAFT_ONLY and never-emit-events invariants
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,facts,faq,best_answer",
    [
        # Direct fact
        ("What's the wifi?", {"wifi": "GuestNet"}, None, None),
        ("Check-in time?", {"check_in": "4 PM"}, None, None),
        # FAQ match
        ("What's the door code?", {},
         [{"question": "door code?", "answer": "1234"}],
         "1234"),
        # No match
        ("Where is the seashell museum?", {},
         [{"question": "Where do we park?", "answer": "Driveway."}],
         None),
        # No context
        ("How do we get in?", {}, None, None),
    ],
)
async def test_recommended_action_is_always_draft_only(
    text: str,
    facts: Dict[str, Any],
    faq: Optional[List[Dict[str, Any]]],
    best_answer: Optional[str],
):
    """Across every input shape, the agent recommends DRAFT_ONLY in
    Phase 2. Auto-send eligibility for high-confidence access answers
    (wifi, check-in time) is a future session — see the seam map's
    'Long-term target' section. Nothing in this agent should claim
    auto-send authority."""
    agent = _agent_with_answer(best_answer)
    context = _make_context(facts=facts, faq=faq)

    decision = await agent.run(
        message=_make_inbound(text),
        classification=_make_classification(),
        context=context,
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,facts,faq,best_answer",
    [
        ("What's the wifi?", {"wifi": "GuestNet"}, None, None),
        ("door code?", {},
         [{"question": "door code?", "answer": "1234"}], "1234"),
        ("Random question.", {}, [], None),
        ("How do we get in?", {}, None, None),
    ],
)
async def test_no_module_events_ever_emitted(
    text: str,
    facts: Dict[str, Any],
    faq: Optional[List[Dict[str, Any]]],
    best_answer: Optional[str],
):
    """Per the Phase 2 seam map: 'Emits ModuleEvent: no'. Access
    questions are pure conversation."""
    agent = _agent_with_answer(best_answer)
    context = _make_context(facts=facts, faq=faq)

    decision = await agent.run(
        message=_make_inbound(text),
        classification=_make_classification(),
        context=context,
    )

    assert decision.module_events == []
    assert decision.intent_topic == "access"


# ─────────────────────────────────────────────────────────────────────────────
# Local lexical scorer parity (defensive — same scorer as HouseRulesAgent
# but lives in this module independently, so it deserves its own pin)
# ─────────────────────────────────────────────────────────────────────────────


def test_local_scorer_matches_strong_question_overlap():
    faq = [
        {"question": "What's the door code?", "answer": "It's 1234."},
    ]
    match, score = _score_faq_match("What is the door code please?", faq)
    assert match is not None
    assert score >= 0.45


def test_local_scorer_returns_none_when_no_overlap():
    faq = [
        {"question": "What's the door code?", "answer": "It's 1234."},
    ]
    match, score = _score_faq_match("Where can I find seafood restaurants?", faq)
    assert match is None
    assert score == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator integration — registration shape
# ─────────────────────────────────────────────────────────────────────────────


def test_default_orchestrator_registers_access_agent():
    """Default orchestrator construction registers AccessAgent under
    its expected name."""
    orch = GuestMessageBrainOrchestrator()

    assert "AccessAgent" in orch._specialists
    agent = orch._specialists["AccessAgent"]
    assert isinstance(agent, AccessAgent)
    assert agent.handles_topics == ("access",)


def test_default_router_routes_access_topic_to_access_agent():
    """The router's default topic→agent table maps 'access' to
    AccessAgent. Together with the registration test above, this proves
    an access classification will reach the real agent end-to-end."""
    from app.services.messaging_brain.agents.agent_router import (
        DEFAULT_TOPIC_TO_AGENTS,
    )

    assert "access" in DEFAULT_TOPIC_TO_AGENTS
    assert DEFAULT_TOPIC_TO_AGENTS["access"] == ("AccessAgent",)


def test_house_rules_and_access_agents_coexist_in_default_registry():
    """Defensive — Session 2 and Session 3 specialists must both be
    present in the default registry. A regression that overwrites
    one with the other (e.g. via a register_specialist name collision)
    would silently degrade one of the two paths."""
    orch = GuestMessageBrainOrchestrator()

    assert "AccessAgent" in orch._specialists
    assert "HouseRulesAgent" in orch._specialists
    assert "MaintenanceAgent" in orch._specialists

    from app.services.messaging_brain.agents.house_rules_agent import (
        HouseRulesAgent,
    )
    from app.services.messaging_brain.agents.maintenance_agent import (
        MaintenanceAgent,
    )

    assert isinstance(orch._specialists["AccessAgent"], AccessAgent)
    assert isinstance(orch._specialists["HouseRulesAgent"], HouseRulesAgent)
    assert isinstance(orch._specialists["MaintenanceAgent"], MaintenanceAgent)
