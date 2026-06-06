"""
response_policy_agent.py — Final auto_send / draft_only / escalate gate.

Wraps the existing autonomy_gate.evaluate() function and translates between
the brain's Pydantic contracts and the gate's UUID/string types.

Three concerns:
  1. Stage translation
       MessagingLifecycle (brain enum) → autonomy_gate stage strings
       Notably: PRE_ARRIVAL ↔ "booked_pre_arrival"  (different naming)
  2. Type conversions
       tenant_id: str → UUID
       property_id: Optional[str] → Optional[UUID]
  3. Decision translation
       AutonomyDecision.AUTO_SEND              → RecommendedAction.AUTO_SEND
       AutonomyDecision.REVIEW                 → RecommendedAction.DRAFT_ONLY
       AutonomyDecision.BLOCKED_BY_ESCALATION  → RecommendedAction.ESCALATE

Also aggregates specialist confidence (single specialist → their
confidence; multiple specialists → min so the weakest link gates the
final value) and collects every ModuleEvent emitted by the specialists
into module_events_to_dispatch — these are handed back to the
orchestrator which dispatches them to modules (unless the policy says
ESCALATE, in which case nothing is dispatched).

Phase 1.3: policy_warnings is always [] — no policy linter yet.
Phase 1.4+: feed in pre_booking_auto_send confidence checks, knowledge-gap
warnings, etc. The shape of this agent does not need to change for that.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional
from uuid import UUID

from app.services.messaging.autonomy_gate import (
    AutonomyDecision,
    GateResult,
    evaluate as autonomy_evaluate,
)
from app.services.messaging_brain.agents.escalation_agent import (
    ABSOLUTE_HARD_STOP_RISK_FLAGS,
    HARD_ESCALATION_RISK_FLAGS,
)
from app.services.messaging_brain.policy.platform_compliance import (
    PreBookingPolicyOutcome,
    apply_pre_booking_draft_source_policy,
    evaluate_pre_booking_policy,
)
from app.services.orchestration.messaging_brain_contracts import (
    AgentDecision,
    GuestContextBundle,
    InboundGuestMessage,
    MessagingLifecycle,
    ModuleEvent,
    RecommendedAction,
    ResponsePolicyDecision,
)

logger = logging.getLogger(__name__)

DEFAULT_AUTONOMY_THRESHOLD = 1.0


# Sentinel string used by the orchestrator's _StubSpecialistAgent to mark
# its missing_info. Kept as a duplicate literal here — not imported — to
# avoid creating an agent→orchestrator import cycle. Source of truth is
# orchestrator._STUB_SPECIALIST_SENTINEL; if that string ever changes, this
# constant must change with it. See _aggregate_confidence below for why
# we need it.
_STUB_SPECIALIST_SENTINEL = "__stub_specialist__"


# Stage translation table. autonomy_gate accepts:
#   "all" | "pre_booking" | "booked_pre_arrival" | "in_stay" | "post_stay"
# MessagingLifecycle uses simpler names. Map the difference here.
_LIFECYCLE_TO_GATE_STAGE: dict[MessagingLifecycle, str] = {
    MessagingLifecycle.PRE_BOOKING: "pre_booking",
    MessagingLifecycle.PRE_ARRIVAL: "booked_pre_arrival",
    MessagingLifecycle.IN_STAY: "in_stay",
    MessagingLifecycle.POST_STAY: "post_stay",
    MessagingLifecycle.OPS: "all",
    MessagingLifecycle.SYSTEM: "all",
}

# Decision translation table.
_DECISION_TO_ACTION: dict[AutonomyDecision, RecommendedAction] = {
    AutonomyDecision.AUTO_SEND: RecommendedAction.AUTO_SEND,
    AutonomyDecision.REVIEW: RecommendedAction.DRAFT_ONLY,
    AutonomyDecision.BLOCKED_BY_ESCALATION: RecommendedAction.ESCALATE,
}


def _try_uuid(value: Optional[str]) -> Optional[UUID]:
    """Best-effort UUID cast; returns None for invalid or empty input."""
    if not value:
        return None
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None


def _lifecycle_to_gate_stage(lifecycle: MessagingLifecycle) -> str:
    """Map brain lifecycle → autonomy_gate stage string. Defaults to 'all'."""
    return _LIFECYCLE_TO_GATE_STAGE.get(lifecycle, "all")


class ResponsePolicyAgent:
    """The final gate before a draft auto-sends, queues for review, or
    escalates. Wraps autonomy_gate.evaluate."""

    name = "ResponsePolicyAgent"

    def evaluate_pre_booking_policy(
        self,
        *,
        message: str,
        intent: str,
        confidence: float,
        requested_nights: Optional[int],
        requested_guests: Optional[int],
        property_data: dict[str, Any],
        operator_policies: dict[str, Any],
        auto_send_threshold: float,
        flag_pricing_inquiries: bool,
        flag_pet_inquiries: bool,
        approval_mode: str,
        missing_knowledge_topics: list[str],
    ) -> PreBookingPolicyOutcome:
        """Bridge legacy pre-booking policy checks through the brain layer."""
        return evaluate_pre_booking_policy(
            message=message,
            intent=intent,
            confidence=confidence,
            requested_nights=requested_nights,
            requested_guests=requested_guests,
            property_data=property_data,
            operator_policies=operator_policies,
            auto_send_threshold=auto_send_threshold,
            flag_pricing_inquiries=flag_pricing_inquiries,
            flag_pet_inquiries=flag_pet_inquiries,
            approval_mode=approval_mode,
            missing_knowledge_topics=missing_knowledge_topics,
        )

    def apply_pre_booking_draft_source_policy(
        self,
        *,
        outcome: PreBookingPolicyOutcome,
        draft_source: str,
        intent: str,
        message: str,
    ) -> PreBookingPolicyOutcome:
        """Bridge legacy draft-source hold policy through the brain layer."""
        return apply_pre_booking_draft_source_policy(
            outcome=outcome,
            draft_source=draft_source,
            intent=intent,
            message=message,
        )

    async def evaluate(
        self,
        *,
        message: InboundGuestMessage,
        context: GuestContextBundle,
        decisions: List[AgentDecision],
        db_session: Any,
    ) -> ResponsePolicyDecision:
        """Run policy evaluation and translate the result into the brain's
        ResponsePolicyDecision shape.

        Escalation is enforced here via _detect_escalation (brain-native
        risk-flag hard-stop), NOT via any escalation table lookup in the
        autonomy gate. The autonomy gate now only resolves per-property
        autonomy mode and confidence.
        """
        # ── Aggregate inputs ─────────────────────────────────────────────
        confidence = self._aggregate_confidence(decisions)
        module_events = self._collect_module_events(decisions)
        has_clarify = any(
            d.recommended_action == RecommendedAction.CLARIFY for d in decisions
        )
        identity_state = str(
            getattr(getattr(message, "identity", None), "state", "") or "pseudonymous"
        ).lower()

        if identity_state == "anonymous":
            return self._safe_escalate(
                module_events=module_events,
                reason="anonymous identity; cannot safely auto-send",
                confidence=confidence,
            )

        # ── Escalation hard-stop (brain-native, highest priority) ─────────
        # If any specialist raised an escalation risk flag or explicitly
        # recommended ESCALATE, force ESCALATE now — before the autonomy gate
        # is even consulted. This is unconditional: it does NOT depend on
        # confidence, autonomy mode, or the gate result. An
        # escalation_emergency flag can never auto-send. This is the sole
        # authoritative "escalations override everything" mechanism on the
        # brain path; it honors the brain's escalation decision
        # (AgentDecision risk_flags) directly.
        escalation_reason = self._detect_escalation(decisions)
        if escalation_reason is not None:
            logger.info(
                "[ResponsePolicyAgent] hard ESCALATE: %s", escalation_reason,
            )
            return self._safe_escalate(
                module_events=module_events,
                reason=f"escalation override: {escalation_reason}",
                confidence=confidence,
            )

        # ── Translate types and stage ────────────────────────────────────
        try:
            tenant_uuid = UUID(message.tenant_id)
        except (ValueError, AttributeError):
            logger.warning(
                "[ResponsePolicyAgent] invalid tenant_id %r — defaulting to ESCALATE",
                message.tenant_id,
            )
            return self._safe_escalate(
                module_events=module_events,
                reason="invalid tenant_id; cannot resolve autonomy",
                confidence=confidence,
            )

        property_uuid = _try_uuid(context.property_id)
        gate_stage = _lifecycle_to_gate_stage(context.lifecycle)

        # ── Call autonomy_gate ────────────────────────────────────────────
        try:
            gate_result: GateResult = await autonomy_evaluate(
                db_session,
                tenant_id=tenant_uuid,
                property_id=property_uuid,
                stage=gate_stage,
                confidence=confidence,
                policy_warnings=[],  # Phase 1.3: no warnings yet
            )
        except Exception as exc:  # noqa: BLE001
            # Fail safe: any gate failure → DRAFT_ONLY (operator reviews).
            # We do NOT escalate on gate failures because that creates
            # operator noise; the safe default is "review before send".
            logger.exception(
                "[ResponsePolicyAgent] autonomy_gate.evaluate raised: %s", exc,
            )
            return ResponsePolicyDecision(
                final_action=RecommendedAction.DRAFT_ONLY,
                confidence=confidence,
                reasons=[f"policy gate error: {type(exc).__name__}"],
                approval_mode_at_decision="required",
                blocking_escalation_id=None,
                module_events_to_dispatch=module_events,
            )

        # ── Translate the gate result ────────────────────────────────────
        final_action = _DECISION_TO_ACTION[gate_result.decision]
        blocking_id_str = (
            str(gate_result.blocking_escalation_id)
            if gate_result.blocking_escalation_id else None
        )
        reasons = [gate_result.reason] if gate_result.reason else []
        if final_action == RecommendedAction.AUTO_SEND and identity_state != "identified":
            final_action = RecommendedAction.DRAFT_ONLY
            reasons.append(f"identity state {identity_state} requires operator review")
        if (
            final_action == RecommendedAction.AUTO_SEND
            and confidence < DEFAULT_AUTONOMY_THRESHOLD
        ):
            final_action = RecommendedAction.DRAFT_ONLY
            reasons.append(
                f"confidence {confidence:.2f} below effective autonomy threshold "
                f"{DEFAULT_AUTONOMY_THRESHOLD:.2f}"
            )
        if has_clarify:
            reasons.append("One or more specialists recommend a clarifying follow-up question.")
        return ResponsePolicyDecision(
            final_action=final_action,
            confidence=confidence,
            reasons=reasons,
            approval_mode_at_decision=gate_result.approval_mode_at_decision,
            blocking_escalation_id=blocking_id_str,
            module_events_to_dispatch=module_events,
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _detect_escalation(decisions: List[AgentDecision]) -> Optional[str]:
        """Inspect specialist decisions for a brain-native escalation signal.

        This is the authoritative escalation override for the brain pathway.
        An escalation is expressed on the AgentDecision (risk_flags +
        recommended_action=ESCALATE), NOT as a persisted DB row — so the
        policy gate honors the decision directly. (The autonomy gate has no
        escalation table lookup; the former check_blocking_escalation read
        was removed. The separate concierge escalation system in
        concierge/escalation_service.py handles its own session-path
        escalations out-of-band and does not feed this decision.)

        Returns a human-readable reason string if any escalation signal is
        present, else None. Order of precedence:
          1. Any ABSOLUTE hard-stop risk flag (escalation_emergency) —
             unconditional ESCALATE, never auto-send under any circumstance.
          2. Any other hard-escalation risk flag (complaint, distress).
          3. Any specialist explicitly recommending ESCALATE.
        """
        # Collect all risk flags across decisions once.
        all_flags: set[str] = set()
        for d in decisions:
            for flag in (d.risk_flags or []):
                all_flags.add(str(flag))

        absolute = all_flags & ABSOLUTE_HARD_STOP_RISK_FLAGS
        if absolute:
            return f"absolute hard-stop risk flag(s): {', '.join(sorted(absolute))}"

        hard = all_flags & HARD_ESCALATION_RISK_FLAGS
        if hard:
            return f"escalation risk flag(s): {', '.join(sorted(hard))}"

        if any(d.recommended_action == RecommendedAction.ESCALATE for d in decisions):
            names = sorted(
                d.agent_name for d in decisions
                if d.recommended_action == RecommendedAction.ESCALATE
            )
            return f"specialist(s) recommended ESCALATE: {', '.join(names)}"

        return None

    @staticmethod
    def _aggregate_confidence(decisions: List[AgentDecision]) -> float:
        """Aggregate specialist decision confidences.

        Stub specialists are filtered out first. The orchestrator's
        _StubSpecialistAgent is a catch-all for topics whose real
        specialist hasn't been built yet; it returns a fixed 0.10 with
        the _STUB_SPECIALIST_SENTINEL in missing_info. Letting that
        0.10 enter the min() would tank confidence on every multi-
        specialist row that happened to route through a stub for a
        secondary topic, even when the primary specialist was confident.
        That's an artifact of incomplete coverage, not a real signal.

        After filtering:

          Single (real) specialist → its confidence unchanged. The
          common case in the selective router (one topic → one
          specialist); the right answer is to report exactly what that
          specialist said.

          Multiple (real) specialists → min(confidences). When the
          router fans out to a primary plus secondary topics, mean
          aggregation hides disagreement: a confident pricing
          specialist paired with an uncertain access specialist averages
          to \"medium\" when the right operator-facing signal is \"the
          access part is uncertain.\" min() makes the weakest real
          specialist the gating value. Operators can still see the
          per-specialist breakdown in audit; the headline number
          reflects the most uncertain participant.

        Phase 4 may move to weighted aggregation where each specialist
        reports a contribution_weight, but that requires extending
        AgentDecision. Until then, min() over non-stub decisions is the
        honest choice.

        No decisions at all, OR all decisions were stubs → 0.0. The
        policy gate will route the row to ESCALATE because there's no
        real specialist signal to evaluate. That's the correct behavior:
        a row with only stubs has no business auto-sending.
        """
        real_decisions = [
            d for d in decisions
            if _STUB_SPECIALIST_SENTINEL not in (d.missing_info or [])
        ]
        if not real_decisions:
            return 0.0
        if len(real_decisions) == 1:
            return real_decisions[0].confidence
        return min(d.confidence for d in real_decisions)

    @staticmethod
    def _collect_module_events(decisions: List[AgentDecision]) -> List[ModuleEvent]:
        """Flatten ModuleEvents from every specialist decision in order."""
        events: List[ModuleEvent] = []
        for d in decisions:
            events.extend(d.module_events)
        return events

    @staticmethod
    def _safe_escalate(
        *,
        module_events: List[ModuleEvent],
        reason: str,
        confidence: float,
    ) -> ResponsePolicyDecision:
        """Construct an ESCALATE decision when we can't run the real gate.

        Used for irrecoverable input errors (e.g. malformed tenant_id).
        Module events are still attached so the orchestrator can decide
        whether to dispatch them — though the orchestrator's current
        rule is "no dispatch on ESCALATE", which is the safe default.
        """
        return ResponsePolicyDecision(
            final_action=RecommendedAction.ESCALATE,
            confidence=confidence,
            reasons=[reason],
            approval_mode_at_decision="required",
            blocking_escalation_id=None,
            module_events_to_dispatch=module_events,
        )
