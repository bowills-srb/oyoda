"""
late_checkout_agent.py — Decision-side handler for arrival timing requests.

Ship L scope:
  - Handles the `late_checkout` topic already emitted by IntakeAgent for
    late checkout and early check-in style asks.
  - Reuses the existing operator-policy context instead of introducing a
    parallel permission system.
  - Keeps the same conservative policy stance as the rest of the Brain's
    reactive specialists: recommend DRAFT_ONLY and let the policy gate make
    the final call.

This agent deliberately does NOT auto-approve operational requests. Without
reservation-turnover state in the Brain runtime, the safe posture is:
  - surface any explicit operator policy we do have
  - otherwise acknowledge the request and queue it for review
"""

from __future__ import annotations

import re
from typing import Any, Optional

from app.services.orchestration.messaging_brain_contracts import (
    AgentDecision,
    GuestContextBundle,
    InboundGuestMessage,
    MessageClassification,
    RecommendedAction,
)

_POLICY_CONFIDENCE = 0.68
_DEFAULT_CONFIDENCE = 0.55

_EARLY_CHECKIN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bearly check[\s-]?in\b", re.IGNORECASE),
    re.compile(r"\bearly arrival\b", re.IGNORECASE),
    re.compile(r"\barrive early\b", re.IGNORECASE),
    re.compile(r"\bcome early\b", re.IGNORECASE),
)

_LATE_CHECKOUT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\blate check[\s-]?out\b", re.IGNORECASE),
    re.compile(r"\bcheckout late\b", re.IGNORECASE),
    re.compile(r"\bstay later\b", re.IGNORECASE),
    re.compile(r"\bextend checkout\b", re.IGNORECASE),
)


def _matches_any(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    if not text:
        return False
    return any(pattern.search(text) for pattern in patterns)


class LateCheckoutAgent:
    """Brain specialist for late checkout + early check-in requests."""

    name = "LateCheckoutAgent"
    handles_topics = ("late_checkout",)

    def eligible_for_identity(self, identity_state: str) -> bool:
        return str(identity_state or "").strip().lower() == "identified"

    async def run(
        self,
        *,
        message: InboundGuestMessage,
        classification: MessageClassification,
        context: GuestContextBundle,
        db_session: Any = None,
    ) -> AgentDecision:
        text = message.text or ""
        if _matches_any(text, _EARLY_CHECKIN_PATTERNS):
            return self._handle_early_checkin(context=context)
        return self._handle_late_checkout(context=context)

    def _handle_early_checkin(self, *, context: GuestContextBundle) -> AgentDecision:
        policies = context.operator_policies or {}
        evidence = self._cite_evidence(
            context,
            "operator_policies.early_checkin_available",
            "operator_policies.early_checkin_earliest",
            "operator_policies.early_checkin_fee",
            "operator_policies.early_checkin_subject_to_availability",
            "property_facts.check_in_time",
        )
        standard_checkin = context.property_facts.get("check_in_time")

        if policies.get("_authored"):
            if not policies.get("early_checkin_available", False):
                draft = "Early check-in is not currently offered."
            else:
                earliest = policies.get("early_checkin_earliest") or "the earlier approved time"
                draft = f"Early check-in may be available from {earliest}"
                fee = policies.get("early_checkin_fee")
                if fee not in (None, "", 0, 0.0):
                    draft += f" for a ${float(fee):.0f} fee"
                if policies.get("early_checkin_subject_to_availability", True):
                    draft += ", subject to availability"
                draft += "."
                if standard_checkin:
                    draft += f" Standard check-in is {standard_checkin}."
            return AgentDecision(
                agent_name=self.name,
                intent_topic="late_checkout",
                confidence=_POLICY_CONFIDENCE,
                answer_summary="answered early check-in request from operator policies",
                evidence_used=evidence,
                risk_flags=["arrival_timing_review"],
                recommended_action=RecommendedAction.DRAFT_ONLY,
                draft_text=draft,
                module_events=[],
            )

        draft = (
            "I'd be happy to check on early check-in availability. "
            "Let me confirm the timing and get back to you shortly."
        )
        if standard_checkin:
            draft += f" Standard check-in is {standard_checkin}."
        return AgentDecision(
            agent_name=self.name,
            intent_topic="late_checkout",
            confidence=_DEFAULT_CONFIDENCE,
            answer_summary="queued early check-in request for operator review",
            evidence_used=evidence,
            missing_info=["arrival_timing_requires_operational_review"],
            risk_flags=["arrival_timing_review"],
            recommended_action=RecommendedAction.DRAFT_ONLY,
            draft_text=draft,
            module_events=[],
        )

    def _handle_late_checkout(self, *, context: GuestContextBundle) -> AgentDecision:
        policies = context.operator_policies or {}
        evidence = self._cite_evidence(
            context,
            "operator_policies.late_checkout_available",
            "operator_policies.late_checkout_max_time",
            "operator_policies.late_checkout_fee",
            "operator_policies.late_checkout_requires_approval",
            "property_facts.check_out_time",
        )
        standard_checkout = context.property_facts.get("check_out_time")

        if policies.get("_authored"):
            if not policies.get("late_checkout_available", False):
                draft = "Late checkout is not currently offered."
            else:
                latest = policies.get("late_checkout_max_time") or "the approved time"
                draft = f"Late checkout may be available until {latest}"
                fee = policies.get("late_checkout_fee")
                if fee not in (None, "", 0, 0.0):
                    draft += f" for a ${float(fee):.0f} fee"
                if policies.get("late_checkout_requires_approval", False):
                    draft += ", and it requires approval"
                draft += "."
                if standard_checkout:
                    draft += f" Standard check-out is {standard_checkout}."
            return AgentDecision(
                agent_name=self.name,
                intent_topic="late_checkout",
                confidence=_POLICY_CONFIDENCE,
                answer_summary="answered late checkout request from operator policies",
                evidence_used=evidence,
                risk_flags=["arrival_timing_review"],
                recommended_action=RecommendedAction.DRAFT_ONLY,
                draft_text=draft,
                module_events=[],
            )

        draft = (
            "I'd be happy to check on late checkout availability. "
            "Let me confirm what we can offer and follow up shortly."
        )
        if standard_checkout:
            draft += f" Standard check-out is {standard_checkout}."
        return AgentDecision(
            agent_name=self.name,
            intent_topic="late_checkout",
            confidence=_DEFAULT_CONFIDENCE,
            answer_summary="queued late checkout request for operator review",
            evidence_used=evidence,
            missing_info=["arrival_timing_requires_operational_review"],
            risk_flags=["arrival_timing_review"],
            recommended_action=RecommendedAction.DRAFT_ONLY,
            draft_text=draft,
            module_events=[],
        )

    @staticmethod
    def _cite_evidence(context: GuestContextBundle, *keys: str) -> list[str]:
        available = set(context.evidence_keys or [])
        return [key for key in keys if key in available]
