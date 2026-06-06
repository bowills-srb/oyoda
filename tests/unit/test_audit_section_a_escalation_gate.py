"""
Audit Section A — Gating checks for brain-pathway closeout.

Tests in this file correspond 1:1 with the check IDs in
docs/architecture/OYVODA_AUDIT_BRAIN_CLOSEOUT_AND_PARLOA_FIN.md.

Discipline (held all arc): mocked tests passing is NOT a pass here.
_detect_escalation is NEVER stubbed. Every A2 scenario builds real
AgentDecision objects whose risk_flags are pulled from the escalation
agent's own exported constants (ABSOLUTE_HARD_STOP_RISK_FLAGS,
HARD_ESCALATION_RISK_FLAGS). That is what makes these tests prove the
producer/consumer compose correctly — a broken import or flag-string
drift would be caught here, not hidden.

autonomy_evaluate IS mocked in A2 scenarios (patched to return AUTO_SEND)
because the escalation override must fire BEFORE the gate is consulted.
Returning AUTO_SEND from the gate makes each A2 test more adversarial:
it proves escalation fires even when the gate would have allowed it.

A1 — import resolves (no cycle)
A2 — escalation hard-stop fires on the real flag path
A3 — regression: fix did NOT break normal auto-send
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.messaging.autonomy_gate import AutonomyDecision, GateResult
from app.services.messaging.identity_resolver import GuestIdentityResolution
from app.services.messaging_brain.agents.escalation_agent import (
    ABSOLUTE_HARD_STOP_RISK_FLAGS,
    HARD_ESCALATION_RISK_FLAGS,
    _FLAG_COMPLAINT,
    _FLAG_EMOTIONAL_DISTRESS,
    _FLAG_EMERGENCY,
)
from app.services.messaging_brain.agents.response_policy_agent import ResponsePolicyAgent
from app.services.orchestration.messaging_brain_contracts import (
    AgentDecision,
    GuestContextBundle,
    InboundGuestMessage,
    MessagingLifecycle,
    RecommendedAction,
)

# ── Shared fixtures ────────────────────────────────────────────────────────────

_TENANT_ID = "e07980b2-a990-4b24-91d1-c8cb71ab70e1"  # Beach Habitats
_PROPERTY_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # representative auto-mode property


def _identified_message(tenant_id: str = _TENANT_ID, property_id: str = _PROPERTY_ID) -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id="audit-msg-1",
        tenant_id=tenant_id,
        channel="sms",
        source_provider="twilio",
        text="There is water flooding into the unit",
        guest_name="Guest",
        identity=GuestIdentityResolution(
            state="identified",
            reservation_id="res-audit-1",
            session_token="tok_audit",
            resolution_source="session_token",
            confidence=0.99,
        ),
        property_id=property_id,
        property_code="BH001",
        lifecycle=MessagingLifecycle.IN_STAY,
    )


def _anonymous_message() -> InboundGuestMessage:
    msg = _identified_message()
    msg = msg.model_copy(update={"identity": GuestIdentityResolution(state="anonymous")})
    return msg


def _context(property_id: str = _PROPERTY_ID) -> GuestContextBundle:
    return GuestContextBundle(
        tenant_id=_TENANT_ID,
        property_id=property_id,
        property_code="BH001",
        lifecycle=MessagingLifecycle.IN_STAY,
        property_facts={},
        property_knowledge={},
        guidebook_knowledge={},
        guidebook_richness={},
        guidebook_evidence=[],
        learned_preferences_block="",
        operator_policies={},
        operator_guidance="",
        reservation_facts={},
        house_rules={},
        access_info={},
        maintenance_status={},
        local_guidebook_facts={},
        market_signals={},
        prior_guest_messages=[],
        operator_commitments=[],
        evidence_keys=[],
        missing_context=[],
    )


def _decision_with_flags(*flags: str, confidence: float = 0.95) -> AgentDecision:
    """Build a real AgentDecision carrying the given risk_flags. Do NOT mock
    _detect_escalation — let it run against this object so the flag import
    and composition are exercised end-to-end."""
    return AgentDecision(
        agent_name="EscalationAgent",
        intent_topic="emergency",
        confidence=confidence,
        answer_summary="audit test decision",
        risk_flags=list(flags),
        recommended_action=RecommendedAction.ESCALATE,
    )


def _clean_decision(confidence: float = 1.0) -> AgentDecision:
    """A normal decision with no escalation flags — represents a well-handled inquiry."""
    return AgentDecision(
        agent_name="GeneralAgent",
        intent_topic="general",
        confidence=confidence,
        answer_summary="clean answer",
        risk_flags=[],
        recommended_action=RecommendedAction.AUTO_SEND,
    )


def _gate_returns_auto_send() -> AsyncMock:
    """The gate would have said AUTO_SEND. Used in A2 to prove escalation
    fires unconditionally — even when the gate would have allowed it."""
    return AsyncMock(
        return_value=GateResult(
            decision=AutonomyDecision.AUTO_SEND,
            reason="auto mode, high confidence",
            approval_mode_at_decision="auto",
        )
    )


def _gate_returns_review() -> AsyncMock:
    return AsyncMock(
        return_value=GateResult(
            decision=AutonomyDecision.REVIEW,
            reason="review mode",
            approval_mode_at_decision="required",
        )
    )


# ── A1: Import resolves ────────────────────────────────────────────────────────


def test_a1_response_policy_agent_imports_without_cycle():
    """A1: escalation_agent → response_policy_agent import chain resolves at runtime.
    A failure here is an import cycle or missing constant — gates everything else."""
    mod = importlib.import_module(
        "app.services.messaging_brain.agents.response_policy_agent"
    )
    assert hasattr(mod, "ABSOLUTE_HARD_STOP_RISK_FLAGS")
    assert hasattr(mod, "HARD_ESCALATION_RISK_FLAGS")
    # Confirm the imported sets are the same objects as the escalation agent's exports
    # (i.e. no re-declaration, no drift).
    from app.services.messaging_brain.agents.response_policy_agent import (
        ABSOLUTE_HARD_STOP_RISK_FLAGS as policy_abs,
        HARD_ESCALATION_RISK_FLAGS as policy_hard,
    )
    assert policy_abs is ABSOLUTE_HARD_STOP_RISK_FLAGS, (
        "ABSOLUTE_HARD_STOP_RISK_FLAGS was re-declared in response_policy_agent — "
        "it must be the same object imported from escalation_agent."
    )
    assert policy_hard is HARD_ESCALATION_RISK_FLAGS, (
        "HARD_ESCALATION_RISK_FLAGS was re-declared in response_policy_agent — "
        "it must be the same object imported from escalation_agent."
    )


def test_a1_flag_constants_are_non_empty():
    """A1: both exported sets contain the flags they're documented to contain."""
    assert _FLAG_EMERGENCY in ABSOLUTE_HARD_STOP_RISK_FLAGS
    assert _FLAG_EMERGENCY in HARD_ESCALATION_RISK_FLAGS
    assert _FLAG_COMPLAINT in HARD_ESCALATION_RISK_FLAGS
    assert _FLAG_EMOTIONAL_DISTRESS in HARD_ESCALATION_RISK_FLAGS


# ── A2: Escalation hard-stop works ────────────────────────────────────────────
# _detect_escalation is NEVER mocked. Risk flags are pulled from the real
# exported constants — the exact sets the policy agent imports.


@pytest.mark.asyncio
async def test_a2a_emergency_on_auto_mode_high_confidence_returns_escalate():
    """A2a: THE keystone.
    Emergency flag on an auto-mode, high-confidence property MUST return ESCALATE.
    This is the exact failure the bug allowed. Gate is patched to AUTO_SEND to
    prove escalation fires unconditionally — it does NOT depend on gate result."""
    agent = ResponsePolicyAgent()
    with patch(
        "app.services.messaging_brain.agents.response_policy_agent.autonomy_evaluate",
        new=_gate_returns_auto_send(),
    ):
        result = await agent.evaluate(
            message=_identified_message(),
            context=_context(),
            decisions=[_decision_with_flags(_FLAG_EMERGENCY, confidence=0.95)],
            db_session=SimpleNamespace(),
        )

    assert result.final_action == RecommendedAction.ESCALATE, (
        f"A2a FAILED: emergency on auto-mode high-confidence property returned "
        f"{result.final_action} — this is the exact failure the bug allowed."
    )
    assert any(r.startswith("escalation override:") for r in result.reasons), (
        f"A2a: reason must start with 'escalation override:' but got: {result.reasons}"
    )
    assert _FLAG_EMERGENCY in " ".join(result.reasons), (
        f"A2a: escalation_emergency flag must appear in reason. Got: {result.reasons}"
    )


@pytest.mark.asyncio
async def test_a2a_escalation_fires_before_gate_is_consulted():
    """A2a (variant): gate is never awaited when an escalation flag is present.
    Proves the override is unconditional — gate is not even called."""
    agent = ResponsePolicyAgent()
    gate_mock = _gate_returns_auto_send()
    with patch(
        "app.services.messaging_brain.agents.response_policy_agent.autonomy_evaluate",
        new=gate_mock,
    ):
        result = await agent.evaluate(
            message=_identified_message(),
            context=_context(),
            decisions=[_decision_with_flags(_FLAG_EMERGENCY)],
            db_session=SimpleNamespace(),
        )

    assert result.final_action == RecommendedAction.ESCALATE
    gate_mock.assert_not_awaited(), "Gate should never be consulted when escalation flag is present."


@pytest.mark.asyncio
async def test_a2b_complaint_flag_returns_escalate():
    """A2b: escalation_complaint flag → ESCALATE (overrides any gate result)."""
    agent = ResponsePolicyAgent()
    with patch(
        "app.services.messaging_brain.agents.response_policy_agent.autonomy_evaluate",
        new=_gate_returns_auto_send(),
    ):
        result = await agent.evaluate(
            message=_identified_message(),
            context=_context(),
            decisions=[_decision_with_flags(_FLAG_COMPLAINT)],
            db_session=SimpleNamespace(),
        )

    assert result.final_action == RecommendedAction.ESCALATE, (
        f"A2b FAILED: complaint flag returned {result.final_action}"
    )
    assert any("escalation override:" in r for r in result.reasons)


@pytest.mark.asyncio
async def test_a2c_emotional_distress_flag_returns_escalate():
    """A2c: escalation_emotional_distress flag → ESCALATE."""
    agent = ResponsePolicyAgent()
    with patch(
        "app.services.messaging_brain.agents.response_policy_agent.autonomy_evaluate",
        new=_gate_returns_auto_send(),
    ):
        result = await agent.evaluate(
            message=_identified_message(),
            context=_context(),
            decisions=[_decision_with_flags(_FLAG_EMOTIONAL_DISTRESS)],
            db_session=SimpleNamespace(),
        )

    assert result.final_action == RecommendedAction.ESCALATE, (
        f"A2c FAILED: emotional_distress flag returned {result.final_action}"
    )
    assert any("escalation override:" in r for r in result.reasons)


@pytest.mark.asyncio
async def test_a2d_specialist_recommended_escalate_with_no_risk_flag():
    """A2d: specialist recommended_action=ESCALATE with no risk flag → ESCALATE.
    Tests the third precedence tier in _detect_escalation."""
    agent = ResponsePolicyAgent()
    decision = AgentDecision(
        agent_name="EscalationAgent",
        intent_topic="emergency",
        confidence=0.95,
        answer_summary="specialist says escalate",
        risk_flags=[],  # no flag — only recommended_action
        recommended_action=RecommendedAction.ESCALATE,
    )
    with patch(
        "app.services.messaging_brain.agents.response_policy_agent.autonomy_evaluate",
        new=_gate_returns_auto_send(),
    ):
        result = await agent.evaluate(
            message=_identified_message(),
            context=_context(),
            decisions=[decision],
            db_session=SimpleNamespace(),
        )

    assert result.final_action == RecommendedAction.ESCALATE, (
        f"A2d FAILED: specialist ESCALATE recommendation returned {result.final_action}"
    )
    assert any("specialist(s) recommended ESCALATE" in r for r in result.reasons)


# ── A3: Regression — fix did NOT break normal auto-send ───────────────────────


@pytest.mark.asyncio
async def test_a3a_clean_high_confidence_identified_auto_mode_returns_auto_send():
    """A3a: Normal identified message, auto mode, high confidence, NO escalation flag
    → AUTO_SEND. The fix must not over-escalate clean drafts."""
    agent = ResponsePolicyAgent()
    with patch(
        "app.services.messaging_brain.agents.response_policy_agent.autonomy_evaluate",
        new=_gate_returns_auto_send(),
    ):
        result = await agent.evaluate(
            message=_identified_message(),
            context=_context(),
            decisions=[_clean_decision(confidence=1.0)],
            db_session=SimpleNamespace(),
        )

    assert result.final_action == RecommendedAction.AUTO_SEND, (
        f"A3a FAILED: clean draft returned {result.final_action} — "
        f"fix is over-escalating and suppressing legitimate autonomy. "
        f"Reasons: {result.reasons}"
    )


@pytest.mark.asyncio
async def test_a3b_review_mode_returns_draft_only():
    """A3b: Review mode → DRAFT_ONLY (unchanged behavior)."""
    agent = ResponsePolicyAgent()
    with patch(
        "app.services.messaging_brain.agents.response_policy_agent.autonomy_evaluate",
        new=_gate_returns_review(),
    ):
        result = await agent.evaluate(
            message=_identified_message(),
            context=_context(),
            decisions=[_clean_decision(confidence=1.0)],
            db_session=SimpleNamespace(),
        )

    assert result.final_action == RecommendedAction.DRAFT_ONLY, (
        f"A3b FAILED: review mode returned {result.final_action}"
    )


@pytest.mark.asyncio
async def test_a3c_anonymous_identity_returns_escalate_no_flags():
    """A3c: Anonymous identity (no escalation flag) → ESCALATE. Pre-existing
    behavior intact — the identity check is upstream of the flag check."""
    agent = ResponsePolicyAgent()
    gate_mock = AsyncMock()
    with patch(
        "app.services.messaging_brain.agents.response_policy_agent.autonomy_evaluate",
        new=gate_mock,
    ):
        result = await agent.evaluate(
            message=_anonymous_message(),
            context=_context(),
            decisions=[_clean_decision(confidence=1.0)],
            db_session=SimpleNamespace(),
        )

    assert result.final_action == RecommendedAction.ESCALATE, (
        f"A3c FAILED: anonymous identity returned {result.final_action}"
    )
    gate_mock.assert_not_awaited(), "Gate must not be called for anonymous identity."


# ── A2 composition: all three flag tiers in one call ──────────────────────────


@pytest.mark.asyncio
async def test_a2_absolute_flag_takes_precedence_over_hard_flag():
    """Absolute hard-stop (emergency) takes precedence over hard-escalation (complaint).
    Both flags present — reason must cite the absolute flag, not just the hard flag."""
    agent = ResponsePolicyAgent()
    with patch(
        "app.services.messaging_brain.agents.response_policy_agent.autonomy_evaluate",
        new=_gate_returns_auto_send(),
    ):
        result = await agent.evaluate(
            message=_identified_message(),
            context=_context(),
            decisions=[_decision_with_flags(_FLAG_EMERGENCY, _FLAG_COMPLAINT)],
            db_session=SimpleNamespace(),
        )

    assert result.final_action == RecommendedAction.ESCALATE
    # Reason must name the absolute flag path (absolute hard-stop, not just "escalation risk flag")
    assert any("absolute hard-stop" in r for r in result.reasons), (
        f"Expected 'absolute hard-stop' in reasons when both flags present. Got: {result.reasons}"
    )
