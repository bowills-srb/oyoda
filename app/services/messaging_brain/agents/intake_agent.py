"""
intake_agent.py — First-pass intent classifier for the messaging brain.

Wraps the existing app/services/agents/router_agent.py::ConciergeRouter
and translates its 7-route output into the brain's two-axis
MessageClassification (intent_type + intent_topic + urgency).

Why wrap ConciergeRouter rather than reimplement?
  - It's the same keyword logic the legacy /concierge/message endpoint
    already uses — keeping them aligned means the brain and legacy
    paths classify identically. That's a precondition for the flag-OFF
    behavior in 1.3b being identical to today.
  - It's already well-tested and battle-hardened against real guest
    messages (Hurricane keyword sets, late-checkout phrasing variants,
    etc.).
  - Phase 4+ swaps in an LLM-based classifier; the IntakeAgent shape
    doesn't need to change for that.

Translation table (full version in docs/PHASE_1_3_SEAM_MAP.md):

  ConciergeRouter Route   →  (intent_type, intent_topic, urgency, review)
  ─────────────────────────────────────────────────────────────────────
  ESCALATE_URGENT         →  PROBLEM, emergency, EMERGENCY, True
  ESCALATE_HIGH (refund)  →  PROBLEM, complaint, HIGH, False
  ESCALATE_HIGH (other)   →  PROBLEM, maintenance, HIGH, False
  ESCALATE_HIGH (length)  →  REQUEST, general, HIGH, True
  ESCALATE_EQ             →  PROBLEM, complaint, HIGH, True
  QUICK_ANSWER            →  QUESTION, access, MEDIUM, False
  PMS_QUERY (late ck)     →  REQUEST, late_checkout, MEDIUM, False
  PMS_QUERY (other)       →  QUESTION, booking_inquiry, MEDIUM, False
  KNOWLEDGE_LOOKUP (rules)→  QUESTION, house_rules, LOW, False
  KNOWLEDGE_LOOKUP (local)→  QUESTION, local_recommendation, LOW, False
  KNOWLEDGE_LOOKUP (other)→  QUESTION, general, LOW, False
  LLM_GENERAL             →  QUESTION, general, MEDIUM, False
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Callable

from app.services.agents.emotional_intelligence.eq_analyzer import (
    get_eq_analyzer,
)
from app.services.agents.router_agent import (
    ConciergeRouter,
    Route,
    RoutingDecision,
)
from app.services.orchestration.messaging_brain_contracts import (
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    Urgency,
)

logger = logging.getLogger(__name__)


# Confidence per route. Calibrated to roughly match how confident the
# legacy keyword classifier should be: emergency keywords = high
# confidence; LLM fallback = low.
_ROUTE_CONFIDENCE: dict[Route, float] = {
    Route.ESCALATE_URGENT: 0.92,
    Route.ESCALATE_HIGH:   0.88,
    Route.ESCALATE_EQ:     0.85,
    Route.QUICK_ANSWER:    0.88,
    Route.PMS_QUERY:       0.80,
    Route.KNOWLEDGE_LOOKUP: 0.75,
    Route.LLM_GENERAL:     0.55,
}

# Sub-keyword sets used to disambiguate ConciergeRouter's coarser routes
# into our finer-grained topics. These are intentionally lowercased
# substrings that match against the matched_keyword from the router.

_COMPLAINT_SUBKEYWORDS = frozenset({
    "refund", "compensation", "money back",
    "disgusting", "unacceptable", "filthy", "dirty",
})

_LATE_CHECKOUT_SUBKEYWORDS = frozenset({
    "late checkout", "early check-in", "extend my stay", "extra night",
    "extend", "later checkout",
})

_HOUSE_RULES_SUBKEYWORDS = frozenset({
    "pet", "smoke", "rule", "quiet", "trash", "rules", "smoking",
})

_LOCAL_RECOMMENDATION_SUBKEYWORDS = frozenset({
    "restaurant", "eat", "food", "dining", "breakfast", "lunch", "dinner",
    "coffee", "bar", "seafood", "pizza", "recommend",
    "activity", "activities", "things to do", "fun",
    "near", "nearby", "around", "local",
    "kayak", "paddleboard", "bike", "rental", "umbrella", "beach chair",
})


def _matches_any(needle: str, haystack: frozenset[str]) -> bool:
    """Case-insensitive substring match against a set of subkeywords."""
    n = (needle or "").lower()
    return any(sub in n for sub in haystack)


class IntakeAgent:
    """Classifies an inbound message via ConciergeRouter and translates
    the result into a MessageClassification.

    Stateless. Construct once, reuse. Each .classify() call constructs
    a per-message ConciergeRouter (which is cheap — it just stores a
    couple of references and runs keyword regex).
    """

    name = "IntakeAgent"

    def __init__(
        self,
        *,
        eq_analyzer: Any | None = None,
        router_factory: Callable[..., ConciergeRouter] = ConciergeRouter,
    ) -> None:
        # Session 7: enable the router's built-in EQ second pass. The
        # router only escalates on UrgencyLevel.CRISIS, so this remains
        # conservative rather than widening the routing surface.
        self._eq = eq_analyzer if eq_analyzer is not None else get_eq_analyzer()
        self._router_factory = router_factory

    async def classify(
        self,
        message: InboundGuestMessage,
        *,
        db_session: Any = None,  # unused for keyword classifier; reserved for LLM in Phase 4
    ) -> MessageClassification:
        """Run ConciergeRouter and translate to MessageClassification."""
        # Build the minimal context shim ConciergeRouter expects.
        # Only .property_code and .operator_id are accessed (with
        # getattr defaults), so this is sufficient.
        ctx = SimpleNamespace(
            property_code=message.property_code or "unknown",
            operator_id=message.tenant_id,
        )
        router = self._router_factory(
            context=ctx,
            eq_analyzer=self._eq,
            watch=None,         # Phase 1.3: no Watch logging from brain
            session_id=message.message_id,
        )

        try:
            decision = await router.route(message.text or "")
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.exception("[IntakeAgent] ConciergeRouter.route raised: %s", exc)
            return MessageClassification(
                intent_type=IntentType.QUESTION,
                intent_topic="general",
                confidence=0.30,
                urgency=Urgency.MEDIUM,
                reason=f"router error: {type(exc).__name__}",
            )

        return self._translate(decision)

    # ── Translation ─────────────────────────────────────────────────────────

    def _translate(self, decision: RoutingDecision) -> MessageClassification:
        """Map a ConciergeRouter RoutingDecision → MessageClassification."""
        confidence = _ROUTE_CONFIDENCE.get(decision.route, 0.50)
        trigger = decision.trigger or ""

        # Route → (intent_type, intent_topic, urgency, requires_human_review)
        if decision.route == Route.ESCALATE_URGENT:
            intent_type = IntentType.PROBLEM
            intent_topic = "emergency"
            urgency = Urgency.EMERGENCY
            review = True

        elif decision.route == Route.ESCALATE_HIGH:
            # Special case: long-conversation escalation
            if trigger == "conversation_length":
                intent_type = IntentType.REQUEST
                intent_topic = "general"
                urgency = Urgency.HIGH
                review = True
            elif _matches_any(trigger, _COMPLAINT_SUBKEYWORDS):
                intent_type = IntentType.PROBLEM
                intent_topic = "complaint"
                urgency = Urgency.HIGH
                review = False
            else:
                # Default: maintenance (broken, leak, ac, pest, etc.)
                intent_type = IntentType.PROBLEM
                intent_topic = "maintenance"
                urgency = Urgency.HIGH
                review = False

        elif decision.route == Route.ESCALATE_EQ:
            intent_type = IntentType.PROBLEM
            intent_topic = "complaint"
            urgency = Urgency.HIGH
            review = True

        elif decision.route == Route.QUICK_ANSWER:
            intent_type = IntentType.QUESTION
            intent_topic = "access"
            urgency = Urgency.MEDIUM
            review = False

        elif decision.route == Route.PMS_QUERY:
            if _matches_any(trigger, _LATE_CHECKOUT_SUBKEYWORDS):
                intent_type = IntentType.REQUEST
                intent_topic = "late_checkout"
                urgency = Urgency.MEDIUM
                review = False
            else:
                intent_type = IntentType.QUESTION
                intent_topic = "booking_inquiry"
                urgency = Urgency.MEDIUM
                review = False

        elif decision.route == Route.KNOWLEDGE_LOOKUP:
            if _matches_any(trigger, _HOUSE_RULES_SUBKEYWORDS):
                intent_type = IntentType.QUESTION
                intent_topic = "house_rules"
                urgency = Urgency.LOW
                review = False
            elif _matches_any(trigger, _LOCAL_RECOMMENDATION_SUBKEYWORDS):
                intent_type = IntentType.QUESTION
                intent_topic = "local_recommendation"
                urgency = Urgency.LOW
                review = False
            else:
                intent_type = IntentType.QUESTION
                intent_topic = "general"
                urgency = Urgency.LOW
                review = False

        else:  # LLM_GENERAL or any unknown
            intent_type = IntentType.QUESTION
            intent_topic = "general"
            urgency = Urgency.MEDIUM
            review = False

        return MessageClassification(
            intent_type=intent_type,
            intent_topic=intent_topic,
            confidence=confidence,
            urgency=urgency,
            requires_human_review=review,
            reason=decision.reason or f"routed via {decision.route.value}",
            matched_keyword=decision.trigger,
            matched_route=decision.route.value,
        )
