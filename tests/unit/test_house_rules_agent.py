"""
test_house_rules_agent.py — Phase 2 Session 2 verification gates.

Focused tests for HouseRulesAgent. Covers:

  * Import smoke (matches the convention from
    test_context_builder_agent_faq.py).
  * The four decision shapes:
      - matched FAQ                              → strong/weak confidence
      - FAQ list present but no match            → no_match decision
      - no FAQ surfaced                          → no_context decision
      - knowledge_service.best_faq_answer raises → fail-open
  * Edge-case behavior:
      - pet/smoking-style messages always recommend DRAFT_ONLY
      - confidence is capped at the edge-case ceiling
      - "house_rules_edge_case" appears in risk_flags
      - non-edge house-rules messages stay clean
  * Evidence contract:
      - cites property_knowledge.faq when bundle has it
      - never cites it when the bundle didn't surface it
        (which would be an evidence-violation under the orchestrator's
        strict-subset rule)
  * No ModuleEvents are ever emitted (per Phase 2 seam map).
  * Recommended action is DRAFT_ONLY across the board (per seam map's
    "should prefer DRAFT_ONLY over aggressive certainty on pet/smoking
    edge cases" — implemented globally for safety).
  * Default orchestrator construction registers HouseRulesAgent under
    its expected name so the router's "house_rules" topic resolves to
    the real agent rather than the stub.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from app.services.messaging_brain import GuestMessageBrainOrchestrator
from app.services.messaging_brain.agents.house_rules_agent import (
    HouseRulesAgent,
    _EDGE_CASE_CONFIDENCE_CAP,
    _NO_MATCH_CONFIDENCE,
    _STRONG_MATCH_CONFIDENCE,
    _WEAK_MATCH_CONFIDENCE,
    _is_edge_case,
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
    message_id: str = "MSG_HR_TEST_001",
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
    """House-rules classification per the IntakeAgent translation table:
    KNOWLEDGE_LOOKUP / pet/smoke/rule trigger → QUESTION/house_rules/LOW."""
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic="house_rules",
        confidence=0.75,
        urgency=Urgency.LOW,
    )


def _make_context(
    *,
    faq: Optional[List[Dict[str, Any]]] = None,
    include_faq_evidence_key: bool = True,
    facts: Optional[Dict[str, Any]] = None,
    include_fact_evidence_keys: bool = True,
) -> GuestContextBundle:
    """Build a context bundle that mimics what ContextBuilderAgent
    produces post-Session 1: property_knowledge.faq surfaced (when
    given) plus its evidence key.
    """
    property_knowledge: Dict[str, Any] = {}
    property_facts: Dict[str, Any] = {}
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


def _agent_with_answer(answer: Optional[str]) -> HouseRulesAgent:
    """HouseRulesAgent whose injected knowledge_service returns a fixed
    best_faq_answer result. Tests assert on the resulting decision."""
    fake = MagicMock()
    fake.best_faq_answer = MagicMock(return_value=answer)
    return HouseRulesAgent(knowledge_service=fake)


def _agent_with_raising_service() -> HouseRulesAgent:
    fake = MagicMock()
    fake.best_faq_answer = MagicMock(side_effect=RuntimeError("boom"))
    return HouseRulesAgent(knowledge_service=fake)


# ─────────────────────────────────────────────────────────────────────────────
# Import smoke
# ─────────────────────────────────────────────────────────────────────────────


def test_house_rules_agent_module_imports_cleanly():
    """Bare-bones import test. Catches module-level import errors and
    surface naming changes before any other test runs."""
    from app.services.messaging_brain.agents import house_rules_agent

    assert hasattr(house_rules_agent, "HouseRulesAgent")
    # Public surface the orchestrator/router/audit machinery rely on.
    agent = house_rules_agent.HouseRulesAgent()
    assert agent.name == "HouseRulesAgent"
    assert agent.handles_topics == ("house_rules",)


def test_house_rules_agent_exported_from_package():
    """HouseRulesAgent is reachable from the package surface.

    The orchestrator imports it directly, but external consumers (and
    test fixtures) often import from the package root. This pins both
    re-export sites at once."""
    from app.services.messaging_brain import HouseRulesAgent as HRA1
    from app.services.messaging_brain.agents import HouseRulesAgent as HRA2

    assert HRA1 is HRA2 is HouseRulesAgent


# ─────────────────────────────────────────────────────────────────────────────
# Edge-case detector
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "Are pets allowed?",
        "Can we bring our dog?",
        "Two cats okay?",
        "I have an emotional support animal — fine?",
        "Is smoking allowed on the deck?",
        "Can I vape inside?",
        "Where can we smoke a cigar?",
        "Is cannabis okay since it's legal here?",
        "Is weed cool?",
    ],
)
def test_edge_case_detector_catches_pet_and_smoking_phrasings(text: str):
    """Word-boundary regex must catch normal phrasings of the two
    edge-case topics across pets/animals and smoking/vaping/cannabis."""
    assert _is_edge_case(text) is True, f"failed to flag: {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        "What time is check-in?",
        "Where is the closest restaurant?",
        "Can we extend our stay?",
        "How does the pool gate open?",
        # False-positive guards — substrings of edge-case words inside
        # unrelated words must NOT trigger.
        "Where do we put the carpet cleaner?",   # "pet" inside "carpet"
        "Is there a smokestack on the chimney?",  # "smoke" inside "smokestack"
        "My catalog of questions for the host",   # "cat" inside "catalog"
        "Do you have a dogwood tree?",            # "dog" inside "dogwood"
    ],
)
def test_edge_case_detector_clean_for_non_edge_messages(text: str):
    """The detector must not over-trigger on unrelated text or on
    edge-case substrings inside other words. Word-boundary regex is
    what makes "carpet" / "smokestack" / "catalog" safe."""
    assert _is_edge_case(text) is False, f"false positive on: {text!r}"


# ─────────────────────────────────────────────────────────────────────────────
# Local lexical scorer parity
# ─────────────────────────────────────────────────────────────────────────────


def test_local_scorer_matches_strong_question_overlap():
    """A direct phrasing match on FAQ question tokens should score
    well above the strong-match floor used by the agent's confidence
    calibration."""
    faq = [
        {"question": "Are pets allowed?", "answer": "Sorry, no pets."},
    ]
    match, score = _score_faq_match("Are pets allowed in the house?", faq)
    assert match is not None
    assert match["question"] == "Are pets allowed?"
    assert score >= 0.65, f"expected strong score, got {score}"


def test_local_scorer_returns_none_when_no_overlap():
    """No question-token overlap → no match (matches the
    knowledge_service.best_faq_answer admission rule)."""
    faq = [
        {"question": "Are pets allowed?", "answer": "Sorry, no pets."},
    ]
    match, score = _score_faq_match("Where is the nearest seafood restaurant?", faq)
    assert match is None
    assert score == 0.0


def test_local_scorer_skips_malformed_entries():
    """Malformed entries (missing question or answer, non-dicts) must
    not blow up the scorer. They're silently skipped."""
    faq = [
        "not a dict",
        {"question": "no answer here"},                 # no answer field
        {"answer": "no question here"},                 # no question field
        {"question": "", "answer": "blank q"},          # blank question
        {"question": "Are pets allowed?", "answer": ""},  # blank answer
        {"question": "Are pets allowed?", "answer": "No pets."},  # valid
    ]
    match, score = _score_faq_match("Are pets allowed?", faq)
    assert match is not None
    assert match["answer"] == "No pets."
    assert score > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Matched-FAQ decisions (strong + weak)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_matched_decision_uses_faq_answer_text_as_draft():
    """When the knowledge service returns an answer, that text is the
    draft. The agent does not paraphrase — operator authoring stays the
    source of truth."""
    faq = [
        {"question": "Is there a parking permit?",
         "answer": "Yes — display the permit on the dashboard at all times."},
    ]
    agent = _agent_with_answer(
        "Yes — display the permit on the dashboard at all times.",
    )
    context = _make_context(faq=faq)

    decision = await agent.run(
        message=_make_inbound("Do we need a parking permit?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.draft_text == (
        "Yes — display the permit on the dashboard at all times."
    )
    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert decision.module_events == []


@pytest.mark.asyncio
async def test_matched_decision_strong_score_yields_strong_confidence():
    """A high-overlap match with no edge-case keywords gets the strong
    confidence band (~0.85)."""
    faq = [
        {"question": "Where do we put the trash?",
         "answer": "Bins are in the side yard, picked up Tuesdays."},
    ]
    agent = _agent_with_answer(
        "Bins are in the side yard, picked up Tuesdays.",
    )
    context = _make_context(faq=faq)

    decision = await agent.run(
        message=_make_inbound("Where do we put the trash bins?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.confidence == pytest.approx(_STRONG_MATCH_CONFIDENCE)
    assert "house_rules_edge_case" not in decision.risk_flags


@pytest.mark.asyncio
async def test_matched_decision_weak_score_yields_weak_confidence():
    """A borderline match (just over the floor) lands in the weak band."""
    faq = [
        {"question": "When are quiet hours? After 10pm please respect neighbors.",
         "answer": "Quiet hours are 10pm-8am."},
    ]
    # Single overlapping content word ("quiet") — score lands above
    # the 0.45 admission floor but below the 0.65 strong-match floor.
    agent = _agent_with_answer("Quiet hours are 10pm-8am.")
    context = _make_context(faq=faq)

    decision = await agent.run(
        message=_make_inbound("Quiet?"),
        classification=_make_classification(),
        context=context,
    )

    # Either the agent admits a weak match (and lands in the weak band)
    # or it rejects the match entirely. Both outcomes are acceptable —
    # what we're locking is "never the strong band on flimsy evidence".
    assert decision.confidence in (
        pytest.approx(_WEAK_MATCH_CONFIDENCE),
        pytest.approx(_NO_MATCH_CONFIDENCE),
    )


@pytest.mark.asyncio
async def test_matched_decision_cites_faq_evidence_key():
    """When the bundle surfaces property_knowledge.faq, the agent
    cites that key. The orchestrator's strict-subset check then
    passes (no evidence violation)."""
    faq = [{"question": "Quiet hours?", "answer": "10pm-8am."}]
    agent = _agent_with_answer("10pm-8am.")
    context = _make_context(faq=faq)

    decision = await agent.run(
        message=_make_inbound("What are the quiet hours?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.evidence_used == ["property_knowledge.faq"]
    # Sanity: the cited key really is in the bundle's evidence_keys.
    # If this ever fails the orchestrator's contract enforcer will log
    # an evidence-violation, so it's worth pinning here too.
    assert set(decision.evidence_used).issubset(set(context.evidence_keys))


@pytest.mark.asyncio
async def test_matched_decision_does_not_cite_faq_key_when_absent_from_bundle():
    """If the bundle has FAQ data but didn't register the
    property_knowledge.faq evidence key, the agent must NOT cite it.

    This pins the strict-subset rule: the agent never invents an
    evidence key the orchestrator would reject. Citing
    property_knowledge.faq when the bundle's evidence_keys don't list
    it would trigger an evidence-violation note in the audit log.
    """
    faq = [{"question": "Quiet hours?", "answer": "10pm-8am."}]
    agent = _agent_with_answer("10pm-8am.")
    # Build a bundle that has the FAQ data but is missing the evidence key.
    context = _make_context(faq=faq, include_faq_evidence_key=False)

    decision = await agent.run(
        message=_make_inbound("What are the quiet hours?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.evidence_used == []
    assert set(decision.evidence_used).issubset(set(context.evidence_keys))


# ─────────────────────────────────────────────────────────────────────────────
# Edge-case bias toward DRAFT_ONLY
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pet_question_with_strong_faq_match_is_capped_to_edge_case_band():
    """Pet questions now use the property_facts.pet_friendly workflow
    before FAQ matching. A concrete property-level deny should still
    stay capped and draft-only because it remains a high-liability
    edge case."""
    faq = [
        {"question": "Are pets allowed?",
         "answer": "Sorry, this is a no-pets property."},
    ]
    agent = _agent_with_answer("Sorry, this is a no-pets property.")
    context = _make_context(
        faq=faq,
        facts={"pet_friendly": False},
    )

    decision = await agent.run(
        message=_make_inbound("Are pets allowed?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.confidence == pytest.approx(_EDGE_CASE_CONFIDENCE_CAP)
    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert "house_rules_edge_case" in decision.risk_flags
    assert "does not allow pets" in decision.draft_text
    assert "property_facts.pet_friendly" in decision.evidence_used


@pytest.mark.asyncio
async def test_smoking_question_with_strong_match_is_capped_to_edge_case_band():
    """Same pattern as the pet test, for smoking. Pinned separately so
    a regression on either keyword family fails its own focused test."""
    faq = [
        {"question": "Can we smoke?",
         "answer": "No smoking anywhere on the property; $250 cleaning fee."},
    ]
    agent = _agent_with_answer(
        "No smoking anywhere on the property; $250 cleaning fee.",
    )
    context = _make_context(faq=faq)

    decision = await agent.run(
        message=_make_inbound("Can we smoke on the porch?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.confidence == pytest.approx(_EDGE_CASE_CONFIDENCE_CAP)
    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert "house_rules_edge_case" in decision.risk_flags


@pytest.mark.asyncio
async def test_non_edge_case_question_is_not_flagged_as_edge_case():
    """Trash/quiet/parking questions don't carry the edge-case risk
    flag. This is the negative companion to the pet/smoking tests so
    we don't accidentally over-broadcast the cautious-review signal."""
    faq = [
        {"question": "Where do we put the trash?",
         "answer": "Bins are in the side yard."},
    ]
    agent = _agent_with_answer("Bins are in the side yard.")
    context = _make_context(faq=faq)

    decision = await agent.run(
        message=_make_inbound("Where do we put the trash bins?"),
        classification=_make_classification(),
        context=context,
    )

    assert "house_rules_edge_case" not in decision.risk_flags
    assert decision.confidence == pytest.approx(_STRONG_MATCH_CONFIDENCE)


@pytest.mark.asyncio
async def test_pet_question_without_match_still_flags_edge_case():
    """Even when there's no FAQ match, a pet/smoking-flavored question
    still carries the edge-case risk flag. Operators should see the
    flag whether or not the agent had grounded knowledge to answer
    with — it's a property of the question, not the answer."""
    faq = [
        {"question": "Where do we park?", "answer": "Driveway only."},
    ]
    agent = _agent_with_answer(None)  # service returns no match
    context = _make_context(faq=faq)

    decision = await agent.run(
        message=_make_inbound("Are pets okay?"),
        classification=_make_classification(),
        context=context,
    )

    assert "house_rules_edge_case" in decision.risk_flags
    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY


# ─────────────────────────────────────────────────────────────────────────────
# No-match / no-context paths
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_faq_in_context_returns_holding_draft():
    """For pet questions, the current decision order checks
    property_facts.pet_friendly before FAQ context. If that property
    fact is missing, the agent defers immediately and records that
    authored gap."""
    agent = _agent_with_answer("never called")
    context = _make_context(faq=None)  # no FAQ at all

    decision = await agent.run(
        message=_make_inbound("Are pets allowed?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert decision.confidence == pytest.approx(_NO_MATCH_CONFIDENCE)
    assert "property_facts.pet_friendly" in decision.missing_info
    # When there's no FAQ at all, the knowledge service is not consulted —
    # the pet-policy branch exits before any FAQ lookup happens.
    agent._knowledge.best_faq_answer.assert_not_called()
    # Draft is the no-context placeholder, not a matched answer.
    assert "team" in decision.draft_text.lower()


@pytest.mark.asyncio
async def test_faq_present_but_no_match_still_cites_faq_evidence():
    """When the FAQ list exists but no entry matches, the agent has
    still consulted operator knowledge — that's worth recording in
    evidence_used. missing_info notes the specific gap so the audit
    log distinguishes "we looked and found nothing" from "we never
    looked"."""
    faq = [
        {"question": "Where do we park?", "answer": "Driveway only."},
    ]
    agent = _agent_with_answer(None)  # service returns no match
    context = _make_context(faq=faq)

    decision = await agent.run(
        message=_make_inbound("Where can I find the seashell museum?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert decision.evidence_used == ["property_knowledge.faq"]
    assert "faq_match_for_question" in decision.missing_info


@pytest.mark.asyncio
async def test_knowledge_service_exception_falls_back_to_no_match_draft():
    """If best_faq_answer raises, the agent must fail open — return
    a no-match draft, log the issue, and never let the exception
    surface to the orchestrator. (The orchestrator catches pipeline
    exceptions globally, but agents shouldn't lean on that.)"""
    faq = [{"question": "Quiet hours?", "answer": "10pm-8am."}]
    agent = _agent_with_raising_service()
    context = _make_context(faq=faq)

    # Should not raise.
    decision = await agent.run(
        message=_make_inbound("Quiet hours?"),
        classification=_make_classification(),
        context=context,
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert decision.confidence == pytest.approx(_NO_MATCH_CONFIDENCE)


# ─────────────────────────────────────────────────────────────────────────────
# Always-DRAFT_ONLY and never-emit-events invariants
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,faq,best_answer",
    [
        # Strong non-edge match
        ("Where do we put the trash bins?",
         [{"question": "Where do we put the trash?",
           "answer": "Bins are in the side yard."}],
         "Bins are in the side yard."),
        # Edge-case match
        ("Are pets allowed?",
         [{"question": "Are pets allowed?",
           "answer": "Sorry, no pets."}],
         "Sorry, no pets."),
        # No match
        ("Where is the seashell museum?",
         [{"question": "Where do we park?", "answer": "Driveway only."}],
         None),
        # No context FAQ at all
        ("Are pets allowed?", None, "never called"),
    ],
)
async def test_recommended_action_is_always_draft_only(
    text: str,
    faq: Optional[List[Dict[str, Any]]],
    best_answer: Optional[str],
):
    """Across every input shape, the agent recommends DRAFT_ONLY.

    The seam map's "DRAFT_ONLY over aggressive certainty" guidance
    points specifically at pet/smoking edge cases, but the agent
    extends it to all house-rules answers. The reasoning is asymmetric
    risk: the cost of a wrong house-rules answer (deposit dispute,
    eviction, fee assessment) far exceeds the cost of a one-touch
    operator approval. The policy gate may still upgrade to AUTO_SEND
    for operators in auto-send mode — that's by design — but the
    agent itself never endorses it."""
    agent = _agent_with_answer(best_answer)
    context = _make_context(faq=faq)

    decision = await agent.run(
        message=_make_inbound(text),
        classification=_make_classification(),
        context=context,
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,faq,best_answer",
    [
        ("Where do we put the trash?",
         [{"question": "Trash?", "answer": "Side yard."}],
         "Side yard."),
        ("Are pets allowed?",
         [{"question": "Pets?", "answer": "No pets."}],
         "No pets."),
        ("Random question.", [], None),
        ("Are pets allowed?", None, None),
    ],
)
async def test_no_module_events_ever_emitted(
    text: str,
    faq: Optional[List[Dict[str, Any]]],
    best_answer: Optional[str],
):
    """Per the Phase 2 seam map: 'Emits ModuleEvent: no'. House rules
    are pure conversation — no side effects, no module work. This
    invariant is what keeps the agent decoupled from the module
    registry; if it ever needs side effects, that's a signal to
    extract a module (Rule 4)."""
    agent = _agent_with_answer(best_answer)
    context = _make_context(faq=faq)

    decision = await agent.run(
        message=_make_inbound(text),
        classification=_make_classification(),
        context=context,
    )

    assert decision.module_events == []
    assert decision.intent_topic == "house_rules"


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator integration — registration shape
# ─────────────────────────────────────────────────────────────────────────────


def test_default_orchestrator_registers_house_rules_agent():
    """Default orchestrator construction registers HouseRulesAgent
    under its expected name. Without this, the router would resolve
    "house_rules" to the catch-all stub, which would silently degrade
    operator answers without anything obviously failing.

    This pins both:
      1. The registration happens.
      2. The instance is the real HouseRulesAgent (not, say, an
         accidentally-shadowed stub registered under the same name)."""
    orch = GuestMessageBrainOrchestrator()

    assert "HouseRulesAgent" in orch._specialists
    agent = orch._specialists["HouseRulesAgent"]
    assert isinstance(agent, HouseRulesAgent)
    assert agent.handles_topics == ("house_rules",)


def test_default_router_routes_house_rules_topic_to_house_rules_agent():
    """The router's default topic→agent table maps 'house_rules' to
    HouseRulesAgent. Together with the registration test above, this
    proves a house_rules classification will reach the real agent
    end-to-end."""
    from app.services.messaging_brain.agents.agent_router import (
        DEFAULT_TOPIC_TO_AGENTS,
    )

    assert "house_rules" in DEFAULT_TOPIC_TO_AGENTS
    assert DEFAULT_TOPIC_TO_AGENTS["house_rules"] == ("HouseRulesAgent",)
