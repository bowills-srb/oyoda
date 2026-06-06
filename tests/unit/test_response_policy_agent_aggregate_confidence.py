"""
test_response_policy_agent_aggregate_confidence.py

Locks the contract of ResponsePolicyAgent._aggregate_confidence after the
Phase 1 confidence cleanup change. Three behaviors must hold:

  1. Single real specialist → its confidence flows through unchanged.
  2. Multiple real specialists → min() across their confidences. The
     weakest real specialist gates the policy value; mean aggregation
     hides disagreement and we don't want it back.
  3. Stub specialists (orchestrator._StubSpecialistAgent marker in
     missing_info) are filtered out before aggregation. Incomplete
     coverage shouldn't tank confidence on rows where the real
     specialists were confident. A row with only stubs returns 0.0
     so the policy gate escalates it for operator attention.

These tests are intentionally cheap and direct — they call the static
method on AgentDecision instances rather than running the full
.evaluate() pipeline. The pipeline is exercised in
test_email_dispatch_prebooking_brain.py and friends; here we want to pin
the aggregation math itself.
"""

from __future__ import annotations

from app.services.messaging_brain.agents.response_policy_agent import (
    ResponsePolicyAgent,
)
from app.services.orchestration.messaging_brain_contracts import (
    AgentDecision,
    RecommendedAction,
)


# Source of truth for this sentinel is
# orchestrator._STUB_SPECIALIST_SENTINEL. ResponsePolicyAgent duplicates
# it as a module constant to avoid an agent→orchestrator import cycle.
# If that string ever changes in the orchestrator, this test will break
# loudly — which is the right behavior.
_STUB_SENTINEL = "__stub_specialist__"


def _real_decision(
    *,
    agent_name: str = "MaintenanceAgent",
    confidence: float = 0.85,
    intent_topic: str = "maintenance",
) -> AgentDecision:
    return AgentDecision(
        agent_name=agent_name,
        intent_topic=intent_topic,
        confidence=confidence,
        answer_summary="real specialist decision",
        evidence_used=[],
        missing_info=[],
        risk_flags=[],
        recommended_action=RecommendedAction.DRAFT_ONLY,
        draft_text="real draft",
        module_events=[],
    )


def _stub_decision(
    *,
    agent_name: str = "StubFooAgent",
    confidence: float = 0.10,
    intent_topic: str = "foo",
) -> AgentDecision:
    return AgentDecision(
        agent_name=agent_name,
        intent_topic=intent_topic,
        confidence=confidence,
        answer_summary="stub placeholder",
        evidence_used=[],
        missing_info=[_STUB_SENTINEL],
        risk_flags=[],
        recommended_action=RecommendedAction.DRAFT_ONLY,
        draft_text="stub draft",
        module_events=[],
    )


def test_empty_decision_list_returns_zero():
    assert ResponsePolicyAgent._aggregate_confidence([]) == 0.0


def test_single_real_specialist_returns_its_confidence_unchanged():
    d = _real_decision(confidence=0.92)
    assert ResponsePolicyAgent._aggregate_confidence([d]) == 0.92


def test_two_real_specialists_returns_minimum():
    high = _real_decision(agent_name="BookingInquiryAgent", confidence=0.85)
    low = _real_decision(agent_name="AccessAgent", confidence=0.55)
    # The mean would be 0.70; we explicitly want 0.55 so operators see
    # the weaker specialist's uncertainty rather than have it averaged
    # out.
    assert ResponsePolicyAgent._aggregate_confidence([high, low]) == 0.55


def test_three_real_specialists_returns_minimum():
    a = _real_decision(agent_name="A", confidence=0.91)
    b = _real_decision(agent_name="B", confidence=0.74)
    c = _real_decision(agent_name="C", confidence=0.62)
    assert ResponsePolicyAgent._aggregate_confidence([a, b, c]) == 0.62


def test_stub_specialist_filtered_real_specialist_confidence_preserved():
    real = _real_decision(confidence=0.88)
    stub = _stub_decision(confidence=0.10)
    # Without the filter min() would return 0.10 here. The filter
    # protects rows where one real specialist answered confidently and
    # the secondary topic happened to route through a stub.
    assert ResponsePolicyAgent._aggregate_confidence([real, stub]) == 0.88


def test_multiple_stubs_with_one_real_returns_real_confidence():
    real = _real_decision(confidence=0.79)
    stub1 = _stub_decision(agent_name="StubA", confidence=0.10)
    stub2 = _stub_decision(agent_name="StubB", confidence=0.10)
    assert ResponsePolicyAgent._aggregate_confidence([real, stub1, stub2]) == 0.79


def test_multiple_real_with_one_stub_returns_min_of_real_only():
    real_high = _real_decision(agent_name="A", confidence=0.85)
    real_low = _real_decision(agent_name="B", confidence=0.60)
    stub = _stub_decision(confidence=0.10)
    # min() should be 0.60 (the weaker real), not 0.10 (the stub).
    assert (
        ResponsePolicyAgent._aggregate_confidence([real_high, real_low, stub])
        == 0.60
    )


def test_all_stubs_returns_zero():
    s1 = _stub_decision(agent_name="StubA", confidence=0.10)
    s2 = _stub_decision(agent_name="StubB", confidence=0.10)
    # No real signal at all → 0.0 so the policy gate escalates the row.
    # A row that only ran stubs has no business auto-sending.
    assert ResponsePolicyAgent._aggregate_confidence([s1, s2]) == 0.0


def test_stub_filter_checks_missing_info_not_agent_name():
    # Defensive: a specialist named "StubBar" but without the sentinel
    # in missing_info is treated as real. The filter must use the
    # sentinel string in missing_info, not name-pattern matching.
    looks_stubby = _real_decision(
        agent_name="StubBar",
        confidence=0.71,
    )
    real = _real_decision(agent_name="MaintenanceAgent", confidence=0.83)
    assert ResponsePolicyAgent._aggregate_confidence([looks_stubby, real]) == 0.71
