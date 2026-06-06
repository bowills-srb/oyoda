"""
escalation_agent.py — Decision-side handler for guest complaints and emergencies.

Phase 2 Session 4 — see docs/PHASE_2_SEAM_MAP.md.

Scope:
  - Handles BOTH `complaint` and `emergency` topics with one agent that
    branches internally on the IntakeAgent classification. The router
    maps both topics to "EscalationAgent" so a single registration in
    the orchestrator covers both routes.
  - Does NOT ground answers from FAQ. The whole point of this agent is
    that the situation is too sensitive (complaint) or too urgent
    (emergency) to be answered from canned content. The agent's job is
    to acknowledge appropriately, set the correct risk flags, and
    recommend the right action — not to look anything up.
  - Does NOT emit ModuleEvents in this session. Per the seam map:
    "maybe later, but not required to ship the first version." Future
    sessions may add an escalation module for notification routing,
    SLA tracking, etc. Today the agent's output is decisional.

Branching logic:
  intent_topic="emergency"   → recommend ESCALATE, emergency template,
                                escalation_emergency risk flag
  intent_topic="complaint"   → recommend DRAFT_ONLY, complaint template,
                                escalation_complaint risk flag
  any other topic            → defensive ESCALATE with a note
                                (the router shouldn't send us these,
                                but we never get to be wrong here)

Empathy via templates:
  Real LLM-composed empathetic copy is a Phase 4+ task. For now we use
  conservative templates tuned for the two cases:
    - emergency: acknowledges without minimizing, says a human is
      being notified, and points to 911 if applicable. Does NOT
      promise specific timing or commit to action; that's for the
      operator (or first responders) to do.
    - complaint: acknowledges what was said, signals that a real
      human will respond personally, and avoids defensive or
      remedial language. Operators decide on tone, refunds, and
      compensation; the brain doesn't pretend to.
  The templates are deliberately minimal. The cost of a "still working
  on this" reply going out 30 seconds before an operator's real reply
  is much smaller than the cost of a generic-sounding canned response
  in either category.

EQ enrichment (Session 7) compatibility:
  When EQ enrichment lands, IntakeAgent will populate emotional-state
  signals on the classification (or on a future context surface).
  EscalationAgent should consume those when present, ignore them when
  absent. Today we read `classification.requires_human_review` and the
  `urgency` enum, both of which are populated; EQ-specific fields are
  forward-looked-for but optional. The agent's contract does not need
  to change for Session 7.

Policy-gate interaction (current limitation):
  The agent's `recommended_action=ESCALATE` is currently advisory.
  ResponsePolicyAgent (which wraps autonomy_gate) doesn't look at
  specialists' recommended_action directly — it computes its own
  AutonomyDecision based on per-property autonomy mode, aggregated
  confidence, and escalation-block lookups. So an emergency message
  classified by IntakeAgent will get high `urgency=EMERGENCY` and
  `requires_human_review=True`, which the policy gate's current
  behavior already routes to REVIEW/escalation, but not via this
  agent's recommendation. A future policy refinement should make
  `recommended_action=ESCALATE` from any specialist a hard force on
  the gate's final_action. See seam-map "Future work" notes.

  In the meantime, the high confidence we report on emergency
  decisions plus the escalation_emergency risk flag give the audit
  log enough signal that a real human review is non-optional, and
  shadow-mode operators can verify the brain is correctly identifying
  emergencies before flipping the live switch.

This stays compatible with the orchestrator's existing pipeline:
  - The agent's recommended_action is advisory; ResponsePolicyAgent
    has the final say.
  - The agent never writes to a DB. (Rule 4 from the 1.3 seam map:
    modules own the work, agents own the decision.)
  - When policy.final_action == ESCALATE, the orchestrator skips
    module dispatch entirely. This agent doesn't emit module events,
    so that's a no-op for us — but it's the right invariant.
"""

from __future__ import annotations

import logging
from typing import Any, List

from app.services.orchestration.messaging_brain_contracts import (
    AgentDecision,
    GuestContextBundle,
    InboundGuestMessage,
    MessageClassification,
    RecommendedAction,
    Urgency,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Confidence bands
#
# Calibrated to reflect "this agent is sure the message belongs in
# operator review" — not "this agent is sure what the right answer
# is". Confidence here drives the policy gate's REVIEW vs AUTO_SEND
# decision; we want it high enough that the gate doesn't accidentally
# treat a complaint as auto-sendable, but the actual correctness of
# the response is owed to the operator, not the confidence number.
# ─────────────────────────────────────────────────────────────────────────────

# Emergencies are unambiguous when classified — hurricane keywords,
# safety language, etc. High confidence is appropriate.
_EMERGENCY_CONFIDENCE = 0.95

# Complaints have more variance — refund-language complaints are
# unambiguous, but EQ-flagged complaints may be judgment calls.
# Slightly lower than emergency to reflect that.
_COMPLAINT_CONFIDENCE = 0.85

# Defensive default for anything else that lands on this agent
# (shouldn't happen given the routing table, but never zero-trust).
_DEFENSIVE_CONFIDENCE = 0.50


# ─────────────────────────────────────────────────────────────────────────────
# Risk flags
#
# These are the markers the audit log uses, and that future autonomy
# work must honor as hard blocks on auto-send. Same shape as
# `house_rules_edge_case` (Session 2) and `access_credential_answer`
# (Session 3).
# ─────────────────────────────────────────────────────────────────────────────

# Set when intent_topic="emergency". This is a hard-stop signal — no
# future autonomy work should ever auto-send when this flag is
# present, regardless of confidence, autonomy mode, or any other
# consideration. Same shape as the ADA carve-out for HouseRulesAgent.
_FLAG_EMERGENCY = "escalation_emergency"

# Set when intent_topic="complaint". Less absolute than the emergency
# flag, but still a "review-first by policy" marker. Operators get to
# decide on tone, refund, compensation; the brain shouldn't pretend
# to know the right answer.
_FLAG_COMPLAINT = "escalation_complaint"

# Reserved for Session 7 (EQ enrichment): set when EQ analysis reports
# high emotional intensity on a complaint. The agent doesn't compute
# this today, but the field exists in the agent's risk_flag vocabulary
# so Session 7 can populate it without a contract change.
_FLAG_EMOTIONAL_DISTRESS = "escalation_emotional_distress"

# PUBLIC, EXPORTED single source of truth for the escalation risk flags that
# downstream policy MUST treat as hard ESCALATE signals. Derived directly from
# the flag constants above so it can never drift from what this agent actually
# sets on its AgentDecisions. ResponsePolicyAgent imports THIS — it does not
# re-declare the strings. _FLAG_EMERGENCY is the absolute hard-stop (never
# auto-send, any confidence/mode); the others are review-first by policy.
HARD_ESCALATION_RISK_FLAGS = frozenset({
    _FLAG_EMERGENCY,
    _FLAG_COMPLAINT,
    _FLAG_EMOTIONAL_DISTRESS,
})

# The subset that is an ABSOLUTE hard-stop: never auto-send regardless of
# confidence or autonomy mode. Kept separate so policy can treat emergency
# more strictly than complaint if needed.
ABSOLUTE_HARD_STOP_RISK_FLAGS = frozenset({_FLAG_EMERGENCY})


# ─────────────────────────────────────────────────────────────────────────────
# Templates
#
# Conservative copy. The cost of a generic-sounding "we'll follow up"
# is much smaller than the cost of a defensive or minimizing reply.
# Phase 4+ swaps these for LLM-composed empathetic copy with
# situational context.
# ─────────────────────────────────────────────────────────────────────────────

_EMERGENCY_DRAFT = (
    "I'm flagging this for the team right away. If this is a "
    "life-safety emergency, please call 911 (or your local emergency "
    "number) immediately — don't wait for our reply. Someone from "
    "our team will reach you as soon as possible."
)

_COMPLAINT_DRAFT = (
    "Thank you for letting us know — I'm sorry you're dealing with "
    "this. I've passed your message to the team so a real person can "
    "follow up with you personally."
)

_DEFENSIVE_DRAFT = (
    "Thanks for reaching out. I've flagged this for the team to "
    "review and respond personally."
)


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────


class EscalationAgent:
    """Decision-side handler for guest complaints and emergencies.

    Stateless. Construct once, reuse. No optional service dependencies
    in this version — the agent's decision is purely a function of the
    classification and the message text it sees.

    Registered for both `complaint` and `emergency` topics in
    DEFAULT_TOPIC_TO_AGENTS. One instance, two routes — that's the
    intentional shape per the seam map.
    """

    name = "EscalationAgent"
    handles_topics = ("complaint", "emergency")

    def eligible_for_identity(self, identity_state: str) -> bool:
        return True

    async def run(
        self,
        *,
        message: InboundGuestMessage,
        classification: MessageClassification,
        context: GuestContextBundle,
        db_session: Any = None,  # unused — pure decision agent
    ) -> AgentDecision:
        """Branch on intent_topic and produce the appropriate decision.

        This agent is intentionally simple — the decision is the value,
        not the answer text. Templates are minimal and conservative.
        Operators see the situation, the risk flag, and a holding
        draft; they handle the actual response.
        """
        topic = classification.intent_topic

        if topic == "emergency":
            return self._emergency_decision(classification)
        if topic == "complaint":
            return self._complaint_decision(classification)

        # Defensive: the router shouldn't send anything else here, but
        # if it does, we escalate rather than guess. Logged so the
        # routing-table drift is visible.
        logger.warning(
            "[EscalationAgent] received unexpected topic %r — "
            "defensive ESCALATE",
            topic,
        )
        return self._defensive_decision(classification)

    # ── Decision builders ───────────────────────────────────────────────────

    def _emergency_decision(
        self, classification: MessageClassification,
    ) -> AgentDecision:
        """Emergency: recommend ESCALATE, set the hard-stop flag.

        Note: even when the agent recommends ESCALATE, the final
        action is determined by ResponsePolicyAgent. See the module
        docstring's "Policy-gate interaction" section. The agent's
        recommendation is advisory today; the risk flag is what
        future autonomy work must hard-block on.
        """
        risk_flags: List[str] = [_FLAG_EMERGENCY]

        return AgentDecision(
            agent_name=self.name,
            intent_topic="emergency",
            confidence=_EMERGENCY_CONFIDENCE,
            answer_summary=(
                f"Guest message classified as emergency "
                f"(urgency={self._urgency_str(classification.urgency)}, "
                f"matched={classification.matched_keyword!r}); "
                f"recommending ESCALATE."
            ),
            evidence_used=[],
            missing_info=[],
            risk_flags=risk_flags,
            recommended_action=RecommendedAction.ESCALATE,
            module_events=[],
            draft_text=_EMERGENCY_DRAFT,
        )

    def _complaint_decision(
        self, classification: MessageClassification,
    ) -> AgentDecision:
        """Complaint: recommend DRAFT_ONLY with empathetic acknowledgment."""
        risk_flags: List[str] = [_FLAG_COMPLAINT]

        # If IntakeAgent flagged requires_human_review explicitly (e.g.
        # ESCALATE_EQ path), pass that signal through more loudly.
        # Today the agent doesn't compute the EQ flag itself — Session 7
        # populates _FLAG_EMOTIONAL_DISTRESS when the route was EQ-driven.
        # For non-EQ complaint review cases, requires_human_review just
        # reinforces the existing complaint flag.
        if classification.matched_keyword == "eq_crisis":
            risk_flags.append("escalation_emotional_distress")

        return AgentDecision(
            agent_name=self.name,
            intent_topic="complaint",
            confidence=_COMPLAINT_CONFIDENCE,
            answer_summary=(
                f"Guest message classified as complaint "
                f"(urgency={self._urgency_str(classification.urgency)}, "
                f"matched={classification.matched_keyword!r}, "
                f"review_flagged={classification.requires_human_review}); "
                f"recommending DRAFT_ONLY for personal operator response."
            ),
            evidence_used=[],
            missing_info=[],
            risk_flags=risk_flags,
            recommended_action=RecommendedAction.DRAFT_ONLY,
            module_events=[],
            draft_text=_COMPLAINT_DRAFT,
        )

    def _defensive_decision(
        self, classification: MessageClassification,
    ) -> AgentDecision:
        """Defensive ESCALATE for unexpected topics on this route."""
        return AgentDecision(
            agent_name=self.name,
            intent_topic=classification.intent_topic,
            confidence=_DEFENSIVE_CONFIDENCE,
            answer_summary=(
                f"EscalationAgent received unexpected topic "
                f"{classification.intent_topic!r}; defensive ESCALATE."
            ),
            evidence_used=[],
            missing_info=["expected_topic_complaint_or_emergency"],
            risk_flags=[_FLAG_COMPLAINT],
            recommended_action=RecommendedAction.ESCALATE,
            module_events=[],
            draft_text=_DEFENSIVE_DRAFT,
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _urgency_str(urgency: Urgency) -> str:
        """Render urgency for the audit summary, defending against
        non-Urgency values just in case."""
        return urgency.value if hasattr(urgency, "value") else str(urgency)
