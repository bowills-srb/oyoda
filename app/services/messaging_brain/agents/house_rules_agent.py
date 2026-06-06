"""
house_rules_agent.py — Decision-side handler for guest house-rules questions.

Phase 2 Session 2 — see docs/PHASE_2_SEAM_MAP.md.

Scope:
  - Reads context.property_knowledge.faq (surfaced by ContextBuilderAgent
    in Session 1) and grounds answers there.
  - Optionally calls ConciergeKnowledgeService.best_faq_answer(...) for
    the answer text so the brain and the legacy /concierge/message path
    return identical answers for the same FAQ match.
  - Never emits ModuleEvents (house rules are pure conversation; no
    operational side effects).

Edge-case bias:
  Per the Phase 2 seam map, this agent biases toward DRAFT_ONLY on
  pet/smoking-style edge cases. A wrong "yes pets are fine" or
  "smoking is allowed" answer carries real liability for the operator,
  so the agent:
    1. Always recommends DRAFT_ONLY (never AUTO_SEND, regardless of
       how confident the FAQ match looks).
    2. Floors confidence on edge-case topics so the policy gate's
       aggregated-confidence inputs also lean cautious.
    3. Surfaces a "house_rules_edge_case" risk flag so the audit log
       and operator UI can show why review was preferred.

This stays compatible with the orchestrator's existing pipeline:
  - The agent's recommended_action is advisory; ResponsePolicyAgent
    (autonomy_gate) makes the final ruling.
  - The agent never writes to a DB. (Rule 4 from the 1.3 seam map:
    modules own the work, agents own the decision. House rules don't
    have a module because there's no operational work to do.)

Phase 4+ swaps the keyword-based confidence model for an LLM-grounded
RAG answer with sentence-level provenance against the FAQ list. The
contract this agent exposes (run() returning AgentDecision) does not
change; only the internals do.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.messaging_brain.knowledge.faq_answering import (
    best_faq_answer as _best_faq_answer,
    score_faq_match,
)
from app.services.messaging_brain.policy.platform_compliance import (
    SERVICE_ANIMAL_ACCOMMODATION_RESPONSE,
    is_esa_request,
    is_service_animal_request,
)
from app.services.orchestration.messaging_brain_contracts import (
    AgentDecision,
    GuestContextBundle,
    InboundGuestMessage,
    MessageClassification,
    RecommendedAction,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Confidence calibration
#
# These constants are calibrated against the legacy ConciergeKnowledgeService
# scoring (see _faq_match in app/services/concierge/knowledge_service.py).
# That scorer:
#   score = 0.7 * (overlap_q / |q_tokens|) + 0.3 * (overlap_any / |msg_tokens|)
#   accepts when overlap_q >= 1 AND score >= 0.45
#
# We keep our local scorer aligned with the same formula so the brain's
# confidence reading reflects what best_faq_answer actually matched on.
# ─────────────────────────────────────────────────────────────────────────────

# Score thresholds for the local match. The 0.45 lower bound mirrors the
# knowledge_service threshold so we don't claim a match the service rejected.
_MATCH_FLOOR = 0.45
_STRONG_MATCH_FLOOR = 0.65

# Confidence outputs for each band.
_STRONG_MATCH_CONFIDENCE = 0.85
_WEAK_MATCH_CONFIDENCE = 0.65
_NO_MATCH_CONFIDENCE = 0.40

# When the message hits an edge-case topic (pets/smoking), confidence is
# capped here regardless of how strong the FAQ match is. The aim is to
# nudge the aggregated confidence the policy gate sees toward review,
# not to suppress the answer.
_EDGE_CASE_CONFIDENCE_CAP = 0.70


# ─────────────────────────────────────────────────────────────────────────────
# Edge-case detection
#
# Pet and smoking questions are the highest-liability mistakes in
# automated house-rules answers — getting them wrong has real cost for
# the operator (deposit disputes, ETF charges, eviction risk) and is
# disproportionately likely vs the long tail of house-rules questions.
#
# We use word-boundary regex rather than substring matching so that:
#   * "carpet" doesn't trigger on "pet"
#   * "smokestack" doesn't trigger on "smoke"
#
# This list is intentionally narrow. Adding more triggers (occupancy
# limits, parties, quiet hours) is a Phase 4+ refinement once we have
# real traffic to calibrate against.
# ─────────────────────────────────────────────────────────────────────────────

_EDGE_CASE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bpets?\b", re.IGNORECASE),
    re.compile(r"\bdogs?\b", re.IGNORECASE),
    re.compile(r"\bcats?\b", re.IGNORECASE),
    re.compile(r"\bpuppies?\b", re.IGNORECASE),
    re.compile(r"\bkittens?\b", re.IGNORECASE),
    re.compile(r"\bservice animal\b", re.IGNORECASE),
    re.compile(r"\besa\b", re.IGNORECASE),
    re.compile(r"\bemotional support\b", re.IGNORECASE),
    re.compile(r"\bsmoke\b", re.IGNORECASE),
    re.compile(r"\bsmoking\b", re.IGNORECASE),
    re.compile(r"\bvape\b", re.IGNORECASE),
    re.compile(r"\bvaping\b", re.IGNORECASE),
    re.compile(r"\bcigar(s|ette|ettes)?\b", re.IGNORECASE),
    re.compile(r"\bweed\b", re.IGNORECASE),
    re.compile(r"\bcannabis\b", re.IGNORECASE),
    re.compile(r"\bmarijuana\b", re.IGNORECASE),
)

_PET_PATTERNS: tuple[re.Pattern[str], ...] = tuple(_EDGE_CASE_PATTERNS[:8])


def _is_edge_case(text: str) -> bool:
    """Return True if the message touches a pet- or smoking-style edge case."""
    if not text:
        return False
    return any(pat.search(text) for pat in _EDGE_CASE_PATTERNS)


def _is_pet_question(text: str) -> bool:
    if not text:
        return False
    return any(pat.search(text) for pat in _PET_PATTERNS)


# ─────────────────────────────────────────────────────────────────────────────
# Default drafts
# ─────────────────────────────────────────────────────────────────────────────

# When we have an FAQ-grounded answer, the agent uses the answer text
# directly. These defaults cover the no-match and no-context paths.

_DEFAULT_NO_MATCH_DRAFT = (
    "Thanks for asking — I want to make sure I get this right, so let me "
    "double-check with the team and follow up shortly."
)

_DEFAULT_NO_CONTEXT_DRAFT = (
    "Thanks for the message — I'll loop in the team to confirm and "
    "follow up shortly."
)

# ─────────────────────────────────────────────────────────────────────────────
# Local lexical scorer
#
# A standalone, side-effect-free scorer used purely for confidence
# calibration. The actual answer text comes from
# ConciergeKnowledgeService.best_faq_answer so the brain stays aligned
# with the legacy path.
#
# Why a parallel scorer? best_faq_answer returns Optional[str] — just
# the answer or None. We need a numeric score to drive confidence
# bands. Re-deriving the score from the public API keeps us decoupled
# from the service's private _faq_match without requiring a contract
# change in knowledge_service.
# ─────────────────────────────────────────────────────────────────────────────

def _score_faq_match(
    message_text: str,
    faq: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], float]:
    """Compatibility wrapper for tests and local confidence calibration."""
    return score_faq_match(message_text, faq)


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────


class HouseRulesAgent:
    """Decision-side handler for guest house-rules questions.

    Stateless. Construct once, reuse. The optional knowledge_service
    parameter remains as a test seam; production uses the brain-owned
    FAQ matcher directly.
    """

    name = "HouseRulesAgent"
    handles_topics = ("house_rules",)

    def __init__(
        self,
        knowledge_service: Optional[Any] = None,
    ) -> None:
        self._faq_answerer = knowledge_service
        self._knowledge = knowledge_service

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
        """Produce a grounded, draft-only house-rules answer."""
        text = message.text or ""

        if is_service_animal_request(text):
            return self._service_animal_decision(context=context)

        if is_esa_request(text):
            return self._esa_decision(context=context)

        edge_case = _is_edge_case(text)

        policy_decision = self._pet_policy_decision_v2(text=text, context=context, edge_case=edge_case)
        if policy_decision is not None:
            return policy_decision

        faq_list = self._extract_faq_from_context(context)

        # No FAQ available at all — defer to operator with a polite
        # holding draft. Don't pretend to know the answer.
        if not faq_list:
            return self._no_context_decision(edge_case=edge_case)

        # Score the local match so we can calibrate confidence.
        match_entry, match_score = _score_faq_match(text, faq_list)

        # Ask the official scorer for the answer text. The two scorers
        # use the same formula and threshold, so they will agree on
        # whether there's a match. If they disagree (e.g. private
        # scorer changes upstream) we trust the public scorer for the
        # answer and use our local score for confidence — both being
        # available is the point.
        try:
            if self._faq_answerer is not None:
                answer_text = self._faq_answerer.best_faq_answer(text, faq_list)
            else:
                answer_text = _best_faq_answer(text, faq_list)
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.exception(
                "[HouseRulesAgent] best_faq_answer raised: %s", exc,
            )
            answer_text = None

        if not answer_text:
            return self._no_match_decision(
                edge_case=edge_case,
                evidence_used=self._evidence_keys_used(context),
            )

        return self._matched_decision(
            answer_text=answer_text,
            match_score=match_score,
            edge_case=edge_case,
            matched_question=(
                str(match_entry.get("question") or "") if match_entry else ""
            ),
            evidence_used=self._evidence_keys_used(context),
        )

    # ── Decision builders ───────────────────────────────────────────────────

    def _no_context_decision(self, *, edge_case: bool) -> AgentDecision:
        """No FAQ in context — defer cleanly with a holding response."""
        risk_flags: List[str] = []
        if edge_case:
            risk_flags.append("house_rules_edge_case")

        return AgentDecision(
            agent_name=self.name,
            intent_topic="house_rules",
            confidence=_NO_MATCH_CONFIDENCE,
            answer_summary=(
                "No FAQ available in context for house-rules question; "
                "deferring to operator."
            ),
            evidence_used=[],
            missing_info=["property_knowledge.faq"],
            risk_flags=risk_flags,
            recommended_action=RecommendedAction.DRAFT_ONLY,
            module_events=[],
            draft_text=_DEFAULT_NO_CONTEXT_DRAFT,
        )

    def _no_match_decision(
        self,
        *,
        edge_case: bool,
        evidence_used: List[str],
    ) -> AgentDecision:
        """FAQ present but no match — defer with a polite holding draft.

        We still cite the FAQ key as evidence_used because the agent did
        consult it; the audit log should reflect that the question was
        grounded against operator knowledge, not invented out of thin
        air. missing_info notes the specific gap.
        """
        risk_flags: List[str] = []
        if edge_case:
            risk_flags.append("house_rules_edge_case")

        return AgentDecision(
            agent_name=self.name,
            intent_topic="house_rules",
            confidence=_NO_MATCH_CONFIDENCE,
            answer_summary=(
                "House-rules question did not match any FAQ entry; "
                "deferring to operator."
            ),
            evidence_used=evidence_used,
            missing_info=["faq_match_for_question"],
            risk_flags=risk_flags,
            recommended_action=RecommendedAction.DRAFT_ONLY,
            module_events=[],
            draft_text=_DEFAULT_NO_MATCH_DRAFT,
        )

    def _matched_decision(
        self,
        *,
        answer_text: str,
        match_score: float,
        edge_case: bool,
        matched_question: str,
        evidence_used: List[str],
    ) -> AgentDecision:
        """FAQ-grounded answer."""
        confidence = (
            _STRONG_MATCH_CONFIDENCE
            if match_score >= _STRONG_MATCH_FLOOR
            else _WEAK_MATCH_CONFIDENCE
        )

        risk_flags: List[str] = []
        if edge_case:
            risk_flags.append("house_rules_edge_case")
            # Cap confidence on edge cases regardless of FAQ score.
            # The seam map's "DRAFT_ONLY over aggressive certainty" is
            # implemented in two layers: this confidence cap (which
            # influences aggregated confidence at the policy gate) and
            # the always-DRAFT_ONLY recommended_action below.
            confidence = min(confidence, _EDGE_CASE_CONFIDENCE_CAP)

        summary_question_preview = (
            f"matched FAQ {matched_question[:60]!r}" if matched_question
            else "matched FAQ entry"
        )

        return AgentDecision(
            agent_name=self.name,
            intent_topic="house_rules",
            confidence=confidence,
            answer_summary=(
                f"{summary_question_preview} (score={match_score:.2f}); "
                f"recommending DRAFT_ONLY"
                + (" — pet/smoking edge case" if edge_case else "")
            ),
            evidence_used=evidence_used,
            missing_info=[],
            risk_flags=risk_flags,
            # Always DRAFT_ONLY — see module docstring. The policy gate
            # may upgrade to AUTO_SEND for properties in auto-send mode,
            # but the agent itself does not endorse auto-sending house
            # rules answers.
            recommended_action=RecommendedAction.DRAFT_ONLY,
            module_events=[],
            draft_text=answer_text.strip(),
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_faq_from_context(
        context: GuestContextBundle,
    ) -> List[Dict[str, Any]]:
        """Pull the FAQ list from the bundle's property_knowledge.faq.

        Returns an empty list if the key isn't surfaced. Defends against
        non-list values (shouldn't happen given ContextBuilderAgent's
        normalization, but cheap to check).
        """
        faq = (context.property_knowledge or {}).get("faq")
        if not isinstance(faq, list):
            return []
        return faq

    @staticmethod
    def _evidence_keys_used(context: GuestContextBundle) -> List[str]:
        """Return the evidence keys we'll cite, restricted to keys that
        are actually in context.evidence_keys.

        The orchestrator enforces a strict-subset rule: anything cited
        outside context.evidence_keys is logged as an evidence violation.
        We only ever cite property_knowledge.faq, and only when it's
        actually surfaced.
        """
        if "property_knowledge.faq" in (context.evidence_keys or []):
            return ["property_knowledge.faq"]
        return []

    def _pet_policy_decision_v2(
        self,
        *,
        text: str,
        context: GuestContextBundle,
        edge_case: bool,
    ) -> Optional[AgentDecision]:
        """Pet workflow: property allow/deny first, operator fees second."""
        if not _is_pet_question(text):
            return None

        property_facts = context.property_facts or {}
        policies = context.operator_policies or {}
        available = set(context.evidence_keys or [])

        evidence: List[str] = []
        if "property_facts.pet_friendly" in available:
            evidence.append("property_facts.pet_friendly")

        pet_friendly = property_facts.get("pet_friendly")
        if pet_friendly is False:
            risk_flags = ["house_rules_edge_case"] if edge_case else []
            return AgentDecision(
                agent_name=self.name,
                intent_topic="house_rules",
                confidence=_EDGE_CASE_CONFIDENCE_CAP if edge_case else _STRONG_MATCH_CONFIDENCE,
                answer_summary="property-level pet_friendly=False, declining",
                evidence_used=evidence,
                missing_info=[],
                risk_flags=risk_flags,
                recommended_action=RecommendedAction.DRAFT_ONLY,
                module_events=[],
                draft_text="This property does not allow pets. We're happy to help if you have other questions about your stay.",
            )

        if pet_friendly is True:
            for key in (
                "operator_policies.pet_fee",
                "operator_policies.pet_max_weight",
                "operator_policies.pet_notes",
                "operator_policies.pet_restricted_breeds",
                "operator_policies.pet_policy",
            ):
                if key in available:
                    evidence.append(key)

            fee = policies.get("pet_fee")
            max_weight = policies.get("pet_max_weight")
            notes = str(policies.get("pet_notes") or "").strip()
            breeds = policies.get("pet_restricted_breeds") or []

            parts = ["This property allows pets."]
            if fee not in (None, "", 0, 0.0):
                parts.append(f"There's a ${float(fee):.0f} pet fee per stay.")
            if max_weight:
                parts.append(f"Max weight is {int(max_weight)} lbs.")
            if isinstance(breeds, list) and breeds:
                parts.append(f"Restricted breeds include {', '.join(str(b) for b in breeds[:5])}.")
            if notes:
                parts.append(notes)
            parts.append("Could you share details about your pet — breed, weight, and number — so we can confirm?")

            return AgentDecision(
                agent_name=self.name,
                intent_topic="house_rules",
                confidence=_EDGE_CASE_CONFIDENCE_CAP,
                answer_summary="property pet_friendly=True, prompting for case-specifics",
                evidence_used=evidence,
                missing_info=[],
                risk_flags=["house_rules_edge_case"],
                recommended_action=RecommendedAction.DRAFT_ONLY,
                module_events=[],
                draft_text=" ".join(parts),
            )

        return AgentDecision(
            agent_name=self.name,
            intent_topic="house_rules",
            confidence=_NO_MATCH_CONFIDENCE,
            answer_summary="property pet_friendly not authored; deferring",
            evidence_used=evidence,
            missing_info=["property_facts.pet_friendly"],
            risk_flags=["house_rules_edge_case"],
            recommended_action=RecommendedAction.DRAFT_ONLY,
            module_events=[],
            draft_text=_DEFAULT_NO_CONTEXT_DRAFT,
        )

    def _service_animal_decision(self, *, context: GuestContextBundle) -> AgentDecision:
        evidence = []
        if "platform_compliance.service_animal" in (context.evidence_keys or []):
            evidence.append("platform_compliance.service_animal")
        return AgentDecision(
            agent_name=self.name,
            intent_topic="house_rules",
            confidence=_STRONG_MATCH_CONFIDENCE,
            answer_summary="service animal request — platform compliance response",
            evidence_used=evidence,
            missing_info=[],
            risk_flags=["service_animal_accommodation"],
            recommended_action=RecommendedAction.DRAFT_ONLY,
            module_events=[],
            draft_text=SERVICE_ANIMAL_ACCOMMODATION_RESPONSE,
        )

    def _esa_decision(self, *, context: GuestContextBundle) -> AgentDecision:
        evidence = []
        if "platform_compliance.esa" in (context.evidence_keys or []):
            evidence.append("platform_compliance.esa")
        return AgentDecision(
            agent_name=self.name,
            intent_topic="house_rules",
            confidence=_WEAK_MATCH_CONFIDENCE,
            answer_summary="ESA request — routing to operator for review",
            evidence_used=evidence,
            missing_info=[],
            risk_flags=["house_rules_edge_case", "esa_request"],
            recommended_action=RecommendedAction.ESCALATE,
            module_events=[],
            draft_text=(
                "Thanks for letting me know — emotional support animals are "
                "handled on a case-by-case basis. Let me check with the team "
                "and get back to you shortly."
            ),
        )
