#!/usr/bin/env python3
"""
verify_review_gate.py — proof for #1: adversarial review before auto-send.

Proves the orchestrator gate itself (GuestMessageBrainOrchestrator
._review_before_auto_send), independent of the reviewer's LLM availability, by
stubbing the reviewer to return each verdict and asserting the resulting policy
action:
  - approve                 → AUTO_SEND (unchanged)
  - revise | human_review   → DRAFT_ONLY
  - block                   → ESCALATE
  - reviewer raises         → DRAFT_ONLY (fail-safe)

Also smoke-checks that the real reviewer is callable and approves a clean,
grounded draft on its heuristic path (no LLM keys needed).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.messaging_brain import orchestrator as orch_mod
from app.services.messaging_brain.grounding import response_reviewer as reviewer_mod
from app.services.messaging_brain.orchestrator import GuestMessageBrainOrchestrator
from app.services.orchestration.messaging_brain_contracts import (
    RecommendedAction,
    ResponsePolicyDecision,
)


def _auto_policy() -> ResponsePolicyDecision:
    return ResponsePolicyDecision(
        final_action=RecommendedAction.AUTO_SEND,
        confidence=1.0,
        reasons=["test"],
        approval_mode_at_decision="auto",
        blocking_escalation_id=None,
        module_events_to_dispatch=[],
    )


def _ctx():
    return SimpleNamespace(property_name="Sea Glass Cottage",
                           lifecycle=SimpleNamespace(value="in_stay"))


async def _run_gate_with_verdict(verdict=None, raises=False):
    """Stub the reviewer, run the orchestrator gate, return the resulting action."""
    async def _fake_review(**kwargs):
        if raises:
            raise RuntimeError("simulated reviewer outage")
        return SimpleNamespace(verdict=verdict, flags=["test_flag"], rationale="", reviewed_response="")

    original = reviewer_mod.review_concierge_response
    reviewer_mod.review_concierge_response = _fake_review
    try:
        orch = GuestMessageBrainOrchestrator.__new__(GuestMessageBrainOrchestrator)
        record = SimpleNamespace(notes=[], decisions=[])
        new_policy = await orch._review_before_auto_send(
            policy=_auto_policy(),
            message=SimpleNamespace(tenant_id="00000000-0000-0000-0000-000000000001", text="hi"),
            draft=SimpleNamespace(response_text="Check-in is 4 PM."),
            context=_ctx(),
            record=record,
        )
        return new_policy.final_action, record.notes
    finally:
        reviewer_mod.review_concierge_response = original


async def main() -> None:
    passed = failed = 0

    def ck(cond, label, extra=""):
        nonlocal passed, failed
        if cond:
            print(f"  PASS — {label}"); passed += 1
        else:
            print(f"  FAIL — {label}  {extra}"); failed += 1

    print("── gate downgrades AUTO_SEND on reviewer verdict ──")
    a, _ = await _run_gate_with_verdict("approve")
    ck(a == RecommendedAction.AUTO_SEND, "approve → AUTO_SEND (unchanged)", f">> {a}")
    a, _ = await _run_gate_with_verdict("revise")
    ck(a == RecommendedAction.DRAFT_ONLY, "revise → DRAFT_ONLY", f">> {a}")
    a, _ = await _run_gate_with_verdict("human_review")
    ck(a == RecommendedAction.DRAFT_ONLY, "human_review → DRAFT_ONLY", f">> {a}")
    a, _ = await _run_gate_with_verdict("block")
    ck(a == RecommendedAction.ESCALATE, "block → ESCALATE", f">> {a}")
    a, notes = await _run_gate_with_verdict(raises=True)
    ck(a == RecommendedAction.DRAFT_ONLY, "reviewer error → DRAFT_ONLY (fail-safe)", f">> {a}")
    ck(any("fail-safe" in n for n in notes), "fail-safe recorded in audit notes")

    print("── real reviewer smoke (heuristic path, no LLM keys) ──")
    clean = await reviewer_mod.review_concierge_response(
        guest_message="What time is check-in?",
        draft_response="Check-in is at 4:00 PM. Happy to help with anything else!",
        source_context="Check-in time: 4:00 PM.",
        lifecycle_stage="in_stay",
        property_name="Sea Glass Cottage",
    )
    ck(clean.verdict == "approve", "clean grounded draft → approve", f">> {clean.verdict}")
    print(f"    clean: verdict={clean.verdict} source={clean.review_source}")

    print(f"\n  REVIEW GATE (#1): {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
