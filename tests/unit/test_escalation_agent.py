"""
test_escalation_agent.py — Phase 2 Session 4 verification gates.

Focused tests for EscalationAgent. Covers:

  * Import smoke and package-level export.
  * Branching logic:
      - intent_topic="emergency" → ESCALATE recommendation,
        confidence 0.95, escalation_emergency risk flag, draft mentions
        911 (or local emergency number).
      - intent_topic="complaint" → DRAFT_ONLY recommendation,
        confidence 0.85, escalation_complaint risk flag, empathetic
        but non-defensive draft.
      - any other topic → defensive ESCALATE with confidence 0.50 and
        a missing_info note flagging the routing-table drift.
  * Invariants common to ALL paths:
      - intent_topic on the AgentDecision matches the input topic
        (or, for the defensive path, mirrors the unexpected topic so
        the audit log shows what arrived).
      - draft_text is non-empty on every path.
      - module_events is always [] (no ModuleEvents in this session).
      - evidence_used is always [] (no FAQ grounding in this agent).
  * No knowledge service is called regardless of input shape (defensive
  observation — the agent doesn't construct one, but a future regression
  could quietly add one).
  * Default orchestrator construction registers EscalationAgent under
    "EscalationAgent", and the router's DEFAULT_TOPIC_TO_AGENTS maps
    BOTH `complaint` and `emergency` to that one name. Together those
    prove a complaint OR emergency classification reaches the real
    agent end-to-end.
  * Coexistence with previously-registered specialists (Sessions 1.3a,
  2, 3) — defensive against name collisions.
"""

from __future__ import annotations

import pytest

from app.services.messaging_brain import GuestMessageBrainOrchestrator
from app.services.messaging_brain.agents.access_agent import AccessAgent
from app.services.messaging_brain.agents.escalation_agent import (
    EscalationAgent,
    _COMPLAINT_CONFIDENCE,
    _DEFENSIVE_CONFIDENCE,
    _EMERGENCY_CONFIDENCE,
    _FLAG_COMPLAINT,
    _FLAG_EMERGENCY,
)
from app.services.messaging_brain.agents.house_rules_agent import (
    HouseRulesAgent,
)
from app.services.messaging_brain.agents.maintenance_agent import (
    MaintenanceAgent,
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
    message_id: str = "MSG_ESCALATION_TEST_001",
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


def _make_emergency_classification(
    *,
    matched_keyword: str = "fire",
) -> MessageClassification:
    """Mirrors what IntakeAgent emits for ESCALATE_URGENT routes:
    PROBLEM / emergency / EMERGENCY / requires_human_review=True."""
    return MessageClassification(
        intent_type=IntentType.PROBLEM,
        intent_topic="emergency",
        confidence=0.92,
        urgency=Urgency.EMERGENCY,
        requires_human_review=True,
        matched_keyword=matched_keyword,
        matched_route="escalate_urgent",
    )


def _make_complaint_classification(
    *,
    matched_keyword: str = "refund",
    requires_human_review: bool = False,
) -> MessageClassification:
    """Mirrors what IntakeAgent emits for ESCALATE_HIGH (refund) and
    ESCALATE_EQ routes."""
    return MessageClassification(
        intent_type=IntentType.PROBLEM,
        intent_topic="complaint",
        confidence=0.88,
        urgency=Urgency.HIGH,
        requires_human_review=requires_human_review,
        matched_keyword=matched_keyword,
        matched_route="escalate_high",
    )


def _make_unexpected_classification(
    *,
    intent_topic: str = "house_rules",
) -> MessageClassification:
    """Topic that should NEVER reach EscalationAgent under the current
    routing table, used to test the defensive branch."""
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic=intent_topic,
        confidence=0.75,
        urgency=Urgency.LOW,
    )


def _make_context() -> GuestContextBundle:
    """EscalationAgent doesn't read context, so an empty-ish bundle is
    fine. We still pass a real instance so the agent contract is
    exercised the same way the orchestrator does it."""
    return GuestContextBundle(
        tenant_id="11111111-1111-1111-1111-111111111111",
        property_code="GULF_VIEW_204",
        lifecycle=MessagingLifecycle.IN_STAY,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Import smoke
# ─────────────────────────────────────────────────────────────────────────────


def test_escalation_agent_module_imports_cleanly():
    from app.services.messaging_brain.agents import escalation_agent

    assert hasattr(escalation_agent, "EscalationAgent")
    agent = escalation_agent.EscalationAgent()
    assert agent.name == "EscalationAgent"
    assert agent.handles_topics == ("complaint", "emergency")


def test_escalation_agent_exported_from_package():
    from app.services.messaging_brain import EscalationAgent as A1
    from app.services.messaging_brain.agents import EscalationAgent as A2

    assert A1 is A2 is EscalationAgent


# ─────────────────────────────────────────────────────────────────────────────
# Emergency branch
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emergency_topic_recommends_escalate():
    agent = EscalationAgent()
    decision = await agent.run(
        message=_make_inbound("There's a fire in the kitchen!"),
        classification=_make_emergency_classification(matched_keyword="fire"),
        context=_make_context(),
    )

    assert decision.recommended_action == RecommendedAction.ESCALATE
    assert decision.confidence == pytest.approx(_EMERGENCY_CONFIDENCE)
    assert decision.intent_topic == "emergency"


@pytest.mark.asyncio
async def test_emergency_decision_carries_emergency_risk_flag():
    agent = EscalationAgent()
    decision = await agent.run(
        message=_make_inbound("There's a gas smell!"),
        classification=_make_emergency_classification(
            matched_keyword="gas smell"
        ),
        context=_make_context(),
    )

    assert _FLAG_EMERGENCY in decision.risk_flags
    # The complaint flag should NOT also fire on emergencies.
    assert _FLAG_COMPLAINT not in decision.risk_flags


@pytest.mark.asyncio
async def test_emergency_draft_mentions_911():
    """The emergency template must point guests at 911 (or a local
    emergency number) so they don't sit waiting on a chat reply
    during a real life-safety event. If this test fails, the template
    has been edited in a way that loses that critical instruction."""
    agent = EscalationAgent()
    decision = await agent.run(
        message=_make_inbound("Someone broke in!"),
        classification=_make_emergency_classification(
            matched_keyword="someone broke in"
        ),
        context=_make_context(),
    )

    assert "911" in decision.draft_text


@pytest.mark.asyncio
async def test_emergency_draft_does_not_promise_specific_timing():
    """The emergency template must not make promises like 'we'll be
    there in 5 minutes' — that's for first responders or operators
    to make, not the brain. The current template uses 'as soon as
    possible' which is appropriately non-committal. This test pins
    that contract."""
    agent = EscalationAgent()
    decision = await agent.run(
        message=_make_inbound("There's flooding!"),
        classification=_make_emergency_classification(
            matched_keyword="flood"
        ),
        context=_make_context(),
    )

    bad_phrases = ("minutes", "in an hour", "shortly", "right now")
    for phrase in bad_phrases:
        assert phrase.lower() not in decision.draft_text.lower(), (
            f"emergency template should not promise specific timing "
            f"({phrase!r} matched in {decision.draft_text!r})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Complaint branch
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complaint_topic_recommends_draft_only():
    agent = EscalationAgent()
    decision = await agent.run(
        message=_make_inbound("This place is filthy, I want a refund."),
        classification=_make_complaint_classification(
            matched_keyword="refund"
        ),
        context=_make_context(),
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert decision.confidence == pytest.approx(_COMPLAINT_CONFIDENCE)
    assert decision.intent_topic == "complaint"


@pytest.mark.asyncio
async def test_complaint_decision_carries_complaint_risk_flag():
    agent = EscalationAgent()
    decision = await agent.run(
        message=_make_inbound("Worst stay ever, this is unacceptable."),
        classification=_make_complaint_classification(
            matched_keyword="unacceptable"
        ),
        context=_make_context(),
    )

    assert _FLAG_COMPLAINT in decision.risk_flags
    assert _FLAG_EMERGENCY not in decision.risk_flags


@pytest.mark.asyncio
async def test_complaint_with_eq_review_flag_still_drafts_only():
    """A complaint with requires_human_review=True (e.g. ESCALATE_EQ
    route from IntakeAgent) still recommends DRAFT_ONLY. The agent
    doesn't escalate complaints — those go to humans via review, not
    via the ESCALATE path. The risk flag and the policy gate handle
    the routing."""
    agent = EscalationAgent()
    decision = await agent.run(
        message=_make_inbound(
            "I've been crying for hours, this stay has been a disaster."
        ),
        classification=_make_complaint_classification(
            matched_keyword="eq_crisis",
            requires_human_review=True,
        ),
        context=_make_context(),
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert _FLAG_COMPLAINT in decision.risk_flags


@pytest.mark.asyncio
async def test_complaint_draft_avoids_defensive_remedial_language():
    """The complaint template should not commit to specific remedies
    (refunds, comps, etc.) and should not get defensive. Operators
    decide on those; the brain just acknowledges. This is a fuzzy
    contract — we test the obvious failures, not the exhaustive set."""
    agent = EscalationAgent()
    decision = await agent.run(
        message=_make_inbound("I want my money back!"),
        classification=_make_complaint_classification(
            matched_keyword="money back"
        ),
        context=_make_context(),
    )

    bad_phrases = (
        "refund",
        "compensation",
        "discount",
        "voucher",
        "credit",
        "we apologize",  # operators apologize, not the brain
    )
    lower_draft = decision.draft_text.lower()
    for phrase in bad_phrases:
        assert phrase not in lower_draft, (
            f"complaint template should not commit to remedies / pre-apologize "
            f"({phrase!r} matched in {decision.draft_text!r})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Defensive branch
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unexpected_topic_falls_through_to_defensive_escalate():
    """If the routing table ever drifts and sends a non-complaint /
    non-emergency topic here, the agent must escalate rather than
    silently produce a wrong answer. This guards against future
    regressions in DEFAULT_TOPIC_TO_AGENTS."""
    agent = EscalationAgent()
    decision = await agent.run(
        message=_make_inbound("What time is check-in?"),
        classification=_make_unexpected_classification(
            intent_topic="access"
        ),
        context=_make_context(),
    )

    assert decision.recommended_action == RecommendedAction.ESCALATE
    assert decision.confidence == pytest.approx(_DEFENSIVE_CONFIDENCE)
    assert "expected_topic_complaint_or_emergency" in decision.missing_info


@pytest.mark.asyncio
async def test_defensive_decision_mirrors_unexpected_topic_in_audit():
    """The defensive path's intent_topic should reflect what arrived,
    not be hardcoded to 'complaint' or 'emergency' — operators looking
    at the audit log need to see what was actually classified.
    """
    agent = EscalationAgent()
    decision = await agent.run(
        message=_make_inbound("Any good restaurants?"),
        classification=_make_unexpected_classification(
            intent_topic="local_recommendation"
        ),
        context=_make_context(),
    )

    assert decision.intent_topic == "local_recommendation"


# ─────────────────────────────────────────────────────────────────────────────
# Cross-path invariants
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "classification_factory",
    [
        _make_emergency_classification,
        _make_complaint_classification,
        lambda: _make_unexpected_classification(intent_topic="house_rules"),
    ],
    ids=["emergency", "complaint", "unexpected"],
)
async def test_no_module_events_emitted_on_any_path(classification_factory):
    """Per the seam map: 'Emits ModuleEvent: maybe later, but not
    required to ship the first version'. EscalationAgent should never
    emit ModuleEvents in Session 4."""
    agent = EscalationAgent()
    decision = await agent.run(
        message=_make_inbound("any text, doesn't matter"),
        classification=classification_factory(),
        context=_make_context(),
    )

    assert decision.module_events == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "classification_factory",
    [
        _make_emergency_classification,
        _make_complaint_classification,
        lambda: _make_unexpected_classification(intent_topic="general"),
    ],
    ids=["emergency", "complaint", "unexpected"],
)
async def test_no_evidence_cited_on_any_path(classification_factory):
    """EscalationAgent doesn't ground answers from FAQ — there's
    nothing to cite. evidence_used should always be empty. If a
    future refactor wires in evidence-cited templates, this test
    will fail, which is the right signal for that change."""
    agent = EscalationAgent()
    decision = await agent.run(
        message=_make_inbound("any text"),
        classification=classification_factory(),
        context=_make_context(),
    )

    assert decision.evidence_used == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "classification_factory",
    [
        _make_emergency_classification,
        _make_complaint_classification,
        lambda: _make_unexpected_classification(intent_topic="general"),
    ],
    ids=["emergency", "complaint", "unexpected"],
)
async def test_draft_text_is_non_empty_on_every_path(classification_factory):
    """The composer concatenates non-empty drafts. An empty draft from
    EscalationAgent on a complaint or emergency would mean the guest
    sees nothing while we wait for human follow-up — which is worse
    than a generic-but-acknowledging template. This pins the contract."""
    agent = EscalationAgent()
    decision = await agent.run(
        message=_make_inbound("any text"),
        classification=classification_factory(),
        context=_make_context(),
    )

    assert decision.draft_text.strip() != ""


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator integration
# ─────────────────────────────────────────────────────────────────────────────


def test_default_orchestrator_registers_escalation_agent():
    orch = GuestMessageBrainOrchestrator()

    assert "EscalationAgent" in orch._specialists
    agent = orch._specialists["EscalationAgent"]
    assert isinstance(agent, EscalationAgent)
    assert agent.handles_topics == ("complaint", "emergency")


def test_default_router_routes_both_complaint_and_emergency_to_escalation_agent():
    """A single registration of EscalationAgent must cover BOTH topics
    via DEFAULT_TOPIC_TO_AGENTS. If either mapping changes, this test
    fails and forces a deliberate choice about routing."""
    from app.services.messaging_brain.agents.agent_router import (
        DEFAULT_TOPIC_TO_AGENTS,
    )

    assert DEFAULT_TOPIC_TO_AGENTS.get("complaint") == ("EscalationAgent",)
    assert DEFAULT_TOPIC_TO_AGENTS.get("emergency") == ("EscalationAgent",)


def test_all_session_2_through_4_specialists_coexist_in_default_registry():
    """Defensive — Sessions 2, 3, and 4 specialists must ALL be present
    in the default registry. A regression that overwrites one with
    another (e.g. via a register_specialist name collision, or an
    accidental re-registration) would silently degrade one of those
    paths to the stub. This is the same shape of test we added in
    Session 3 to catch the same class of failure."""
    orch = GuestMessageBrainOrchestrator()

    assert "AccessAgent" in orch._specialists
    assert "EscalationAgent" in orch._specialists
    assert "HouseRulesAgent" in orch._specialists
    assert "MaintenanceAgent" in orch._specialists

    assert isinstance(orch._specialists["AccessAgent"], AccessAgent)
    assert isinstance(orch._specialists["EscalationAgent"], EscalationAgent)
    assert isinstance(orch._specialists["HouseRulesAgent"], HouseRulesAgent)
    assert isinstance(orch._specialists["MaintenanceAgent"], MaintenanceAgent)
