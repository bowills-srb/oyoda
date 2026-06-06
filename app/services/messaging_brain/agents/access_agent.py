"""
access_agent.py — Decision-side handler for guest access questions.

Phase 2 Session 3 — see docs/PHASE_2_SEAM_MAP.md.

Scope:
  - Two evidence paths, picked deliberately:
      1. DIRECT FACT: wifi password / check-in / check-out questions
         answered straight from `property_facts.{wifi,check_in,check_out}`
         when present. High confidence. This is the structured path.
      2. FAQ FALLBACK: door codes / parking / pool / hot tub / grill /
         "how do I get in" style questions answered via
         `ConciergeKnowledgeService.best_faq_answer(...)` against the
         `property_knowledge.faq` list surfaced by Session 1. Medium
         confidence. This is the lexical path.
  - Never emits ModuleEvents (access answers are pure conversation).

Why two paths instead of one?
  Direct facts and FAQ matches have genuinely different reliability
  profiles. A wifi password populated in `property_facts.wifi` has been
  authored as a fact by an operator and is the same string the legacy
  /concierge/message path returns for QUICK_ANSWER routes. A FAQ-based
  answer for "how do I get in?" is a lexical guess against operator
  prose and might match the wrong entry. Keeping the bands separated
  here lets the policy gate (and future auto-send eligibility) reason
  about the two cases differently.

Door-code carve-out:
  Door codes are not amenity facts. In real operator workflows (e.g.
  Beach Habitats), they're per-reservation credentials generated late
  in the turnover cycle and gated by housekeeping completion +
  operator walkthrough sign-off. They're typically issued PROACTIVELY
  alongside wifi/password just before arrival, not retrieved
  reactively from a knowledge base.

  That means the FAQ-fallback path in this agent is a stopgap, not
  the steady-state model. Today, if a guest asks about a door code,
  the safest behavior is:
    - draft (never auto-send), and
    - flag `access_credential_answer` so the operator's review queue
      surfaces it.

  The proper fix (Session 3.5) is operator-opt-in via the planned
  Turnover Module — see docs/PHASE_2_SEAM_MAP.md "Optional Modules".
  When that module is enabled for an operator, the brain reads
  reservation lifecycle and turnover-gate state to answer correctly:
    - is this reservation pre-arrival, in-stay, or post-stay?
    - has housekeeping completed for this property's current turnover?
    - has the walkthrough cleared the property for issuance?
    - has a per-reservation code already been issued?
  When the Turnover Module is NOT enabled, AccessAgent stays in
  this stopgap mode permanently — that is the correct steady state
  for operators who run turnover outside the system, NOT a degraded
  mode. The brain must never assume the module is present.

  The `access_credential_answer` risk flag exists so:
    1. Operators can filter on it during review.
    2. Future sessions that relax DRAFT_ONLY → AUTO_SEND for access
       topics MUST treat this flag as a hard block. Door-code
       auto-send specifically requires the Turnover Module to be
       enabled AND its context to confirm gate clearance for the
       current reservation. FAQ-match confidence alone is never
       sufficient.
  This is the structural analog of `house_rules_edge_case` from
  Session 2: a topic-specific marker that future autonomy work cannot
  quietly walk past.

Always recommends DRAFT_ONLY:
  Same reasoning as HouseRulesAgent. Phase 2 is the learning phase. The
  policy gate has the final say. Auto-send eligibility for high-confidence
  access answers (wifi, check-in time) is a future session — see the
  "Long-term target" section of the seam map.

This stays compatible with the orchestrator's existing pipeline:
  - The agent's recommended_action is advisory; ResponsePolicyAgent
    (autonomy_gate) makes the final ruling.
  - The agent never writes to a DB. (Rule 4 from the 1.3 seam map:
    modules own the work, agents own the decision.)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.messaging_brain.knowledge.faq_answering import (
    best_faq_answer as _best_faq_answer,
    score_faq_match,
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
# Confidence bands
#
# Direct facts (wifi/check_in/check_out from property_facts) are the
# operator's authored truth — high confidence is appropriate.
#
# FAQ-derived answers are lexical matches against operator prose —
# medium confidence is appropriate. Strong/weak match distinction
# mirrors HouseRulesAgent, calibrated against the same scoring formula
# in ConciergeKnowledgeService._faq_match.
# ─────────────────────────────────────────────────────────────────────────────

_DIRECT_FACT_CONFIDENCE = 0.90
_FAQ_STRONG_CONFIDENCE = 0.75
_FAQ_WEAK_CONFIDENCE = 0.60
_NO_MATCH_CONFIDENCE = 0.40

# Score thresholds aligned with knowledge_service._faq_match.
_MATCH_FLOOR = 0.45
_STRONG_MATCH_FLOOR = 0.65


# ─────────────────────────────────────────────────────────────────────────────
# Topic detection
#
# We detect the question's specific access subtopic (wifi, check-in time,
# check-out time, door code) so we can route to the correct evidence
# path with the correct confidence band.
#
# Word-boundary regex patterns prevent false positives:
#   * "key" should not match inside "keyboard" or "Mickey"
#   * "code" should not match inside "encoded"
#   * "door" should not match inside "outdoor" — \bdoor\b handles this
#
# Patterns are tuned against the QUICK_ANSWER_KEYWORDS set in
# router_agent.py so the brain and legacy path agree on what counts as
# what kind of access question.
# ─────────────────────────────────────────────────────────────────────────────

_WIFI_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bwifi\b", re.IGNORECASE),
    re.compile(r"\bwi-?fi\b", re.IGNORECASE),
    re.compile(r"\binternet\b", re.IGNORECASE),
    re.compile(r"\bnetwork\b", re.IGNORECASE),
    re.compile(r"\bpassword\b", re.IGNORECASE),
    re.compile(r"\bssid\b", re.IGNORECASE),
)

_CHECK_IN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcheck[- ]?in\b", re.IGNORECASE),
    re.compile(r"\bchecking in\b", re.IGNORECASE),
    re.compile(r"\barrival time\b", re.IGNORECASE),
    re.compile(r"\bwhen can (we|i) (arrive|get there|come)\b", re.IGNORECASE),
)

_CHECK_OUT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcheck[- ]?out\b", re.IGNORECASE),
    re.compile(r"\bchecking out\b", re.IGNORECASE),
    re.compile(r"\bdeparture time\b", re.IGNORECASE),
    re.compile(r"\bwhen (do|should) (we|i) leave\b", re.IGNORECASE),
)

# Door-code-flavored phrasings. These all imply asking for credentials
# or instructions to physically enter the property. We flag them with
# `access_credential_answer` regardless of which evidence path produced
# the answer.
_DOOR_CODE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bdoor code\b", re.IGNORECASE),
    re.compile(r"\bdoor\b", re.IGNORECASE),
    re.compile(r"\baccess code\b", re.IGNORECASE),
    re.compile(r"\bentry code\b", re.IGNORECASE),
    re.compile(r"\bgate code\b", re.IGNORECASE),
    re.compile(r"\block(box)?\b", re.IGNORECASE),
    re.compile(r"\bkey\b", re.IGNORECASE),
    re.compile(r"\bkeypad\b", re.IGNORECASE),
    re.compile(r"\bget in\b", re.IGNORECASE),
    re.compile(r"\bhow do (we|i) enter\b", re.IGNORECASE),
)


def _matches_any(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    if not text:
        return False
    return any(pat.search(text) for pat in patterns)


# ─────────────────────────────────────────────────────────────────────────────
# Default drafts (only used on no-match / no-context paths; matched paths
# return either the property_facts value or the operator-authored FAQ
# answer text directly).
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_NO_MATCH_DRAFT = (
    "Thanks for asking — let me confirm with the team and get right "
    "back to you with the details."
)

_DEFAULT_NO_CONTEXT_DRAFT = (
    "Thanks for the message — I'll loop in the team to confirm and "
    "follow up shortly."
)

# Templated copy for the high-confidence direct-fact answers. We wrap
# the operator-authored fact in a friendly sentence rather than
# returning the bare value alone, so the draft reads like a reply
# rather than a key-value dump.
_DIRECT_FACT_TEMPLATES: dict[str, str] = {
    "wifi": "Here's the wifi info: {value}",
    "check_in": "Check-in is {value}.",
    "check_out": "Check-out is {value}.",
}


# ─────────────────────────────────────────────────────────────────────────────
# Local lexical scorer
#
# Same shape as HouseRulesAgent's local scorer. The implementation now
# lives under messaging_brain/knowledge so brain agents do not need to
# tunnel through ConciergeKnowledgeService for FAQ matching.
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


class AccessAgent:
    """Decision-side handler for guest access questions.

    Stateless. Construct once, reuse. The optional knowledge_service
    parameter remains as a test seam; production uses the brain-owned
    FAQ matcher directly.
    """

    name = "AccessAgent"
    handles_topics = ("access",)

    def __init__(
        self,
        knowledge_service: Optional[Any] = None,
    ) -> None:
        self._faq_answerer = knowledge_service
        self._knowledge = knowledge_service

    def eligible_for_identity(self, identity_state: str) -> bool:
        return str(identity_state or "").strip().lower() == "identified"

    async def run(
        self,
        *,
        message: InboundGuestMessage,
        classification: MessageClassification,
        context: GuestContextBundle,
        db_session: Any = None,  # unused — pure decision agent
    ) -> AgentDecision:
        """Produce a grounded, draft-only access answer.

        Decision order:
          1. Direct fact path — wifi/check-in/check-out questions whose
             corresponding property_facts value is populated.
          2. FAQ fallback path — anything else, scored against
             property_knowledge.faq via best_faq_answer.
          3. No-match — defer with a holding draft.
          4. No-context — defer with a holding draft.

        Door-code-flavored questions get the `access_credential_answer`
        risk flag regardless of which path produced the answer (or even
        if no answer was produced).
        """
        text = message.text or ""
        is_door_code = _matches_any(text, _DOOR_CODE_PATTERNS)

        # ── 1. Direct fact path ───────────────────────────────────────
        direct_fact_key = self._detect_direct_fact_key(text)
        if direct_fact_key is not None:
            value = (context.property_facts or {}).get(direct_fact_key)
            if value:
                return self._direct_fact_decision(
                    fact_key=direct_fact_key,
                    fact_value=str(value),
                    is_door_code=is_door_code,
                    context=context,
                )

        # ── 2. FAQ fallback path ──────────────────────────────────────
        faq_list = self._extract_faq_from_context(context)
        if faq_list:
            match_entry, match_score = _score_faq_match(text, faq_list)
            try:
                if self._faq_answerer is not None:
                    answer_text = self._faq_answerer.best_faq_answer(text, faq_list)
                else:
                    answer_text = _best_faq_answer(text, faq_list)
            except Exception as exc:  # noqa: BLE001 — fail-open
                logger.exception(
                    "[AccessAgent] best_faq_answer raised: %s", exc,
                )
                answer_text = None

            if answer_text:
                return self._faq_match_decision(
                    answer_text=answer_text,
                    match_score=match_score,
                    matched_question=(
                        str(match_entry.get("question") or "")
                        if match_entry else ""
                    ),
                    is_door_code=is_door_code,
                    context=context,
                )

            # FAQ list present but no match — fall through.
            return self._no_match_decision(
                is_door_code=is_door_code,
                evidence_used=self._faq_evidence_keys_used(context),
                direct_fact_attempted=direct_fact_key,
            )

        # ── 3/4. No FAQ and no direct fact value ──────────────────────
        return self._no_context_decision(
            is_door_code=is_door_code,
            direct_fact_attempted=direct_fact_key,
        )

    # ── Decision builders ───────────────────────────────────────────────────

    def _direct_fact_decision(
        self,
        *,
        fact_key: str,
        fact_value: str,
        is_door_code: bool,
        context: GuestContextBundle,
    ) -> AgentDecision:
        """High-confidence answer from property_facts.

        The cited evidence key matches what ContextBuilderAgent registers
        (property_facts.wifi / property_facts.check_in / property_facts.check_out).
        We additionally restrict to keys actually in context.evidence_keys
        so the orchestrator's strict-subset check passes.
        """
        evidence_key = f"property_facts.{fact_key}"
        evidence_used = (
            [evidence_key]
            if evidence_key in (context.evidence_keys or [])
            else []
        )

        risk_flags: List[str] = []
        if is_door_code:
            risk_flags.append("access_credential_answer")

        template = _DIRECT_FACT_TEMPLATES.get(
            fact_key, "{value}",
        )
        draft_text = template.format(value=fact_value.strip())

        return AgentDecision(
            agent_name=self.name,
            intent_topic="access",
            confidence=_DIRECT_FACT_CONFIDENCE,
            answer_summary=(
                f"answered from property_facts.{fact_key}; "
                f"recommending DRAFT_ONLY (Phase 2 learning phase)"
            ),
            evidence_used=evidence_used,
            missing_info=[],
            risk_flags=risk_flags,
            recommended_action=RecommendedAction.DRAFT_ONLY,
            module_events=[],
            draft_text=draft_text,
        )

    def _faq_match_decision(
        self,
        *,
        answer_text: str,
        match_score: float,
        matched_question: str,
        is_door_code: bool,
        context: GuestContextBundle,
    ) -> AgentDecision:
        """Medium-confidence FAQ-grounded answer."""
        confidence = (
            _FAQ_STRONG_CONFIDENCE
            if match_score >= _STRONG_MATCH_FLOOR
            else _FAQ_WEAK_CONFIDENCE
        )

        risk_flags: List[str] = []
        if is_door_code:
            risk_flags.append("access_credential_answer")

        summary_question_preview = (
            f"matched FAQ {matched_question[:60]!r}" if matched_question
            else "matched FAQ entry"
        )

        return AgentDecision(
            agent_name=self.name,
            intent_topic="access",
            confidence=confidence,
            answer_summary=(
                f"{summary_question_preview} (score={match_score:.2f}); "
                f"recommending DRAFT_ONLY"
                + (" — door-code question" if is_door_code else "")
            ),
            evidence_used=self._faq_evidence_keys_used(context),
            missing_info=[],
            risk_flags=risk_flags,
            recommended_action=RecommendedAction.DRAFT_ONLY,
            module_events=[],
            draft_text=answer_text.strip(),
        )

    def _no_match_decision(
        self,
        *,
        is_door_code: bool,
        evidence_used: List[str],
        direct_fact_attempted: Optional[str],
    ) -> AgentDecision:
        """FAQ list present but no match — defer with a holding draft.

        We still cite property_knowledge.faq because the agent did
        consult it. missing_info distinguishes "tried direct fact and
        nothing was populated" from "tried FAQ and nothing matched".
        """
        risk_flags: List[str] = []
        if is_door_code:
            risk_flags.append("access_credential_answer")

        missing: List[str] = ["faq_match_for_question"]
        if direct_fact_attempted is not None:
            # Operator hasn't authored this structured fact yet — flag
            # the gap so the audit log shows what we'd have liked.
            missing.append(f"property_facts.{direct_fact_attempted}")

        return AgentDecision(
            agent_name=self.name,
            intent_topic="access",
            confidence=_NO_MATCH_CONFIDENCE,
            answer_summary=(
                "Access question did not match any FAQ entry and no "
                "direct property fact applied; deferring to operator."
            ),
            evidence_used=evidence_used,
            missing_info=missing,
            risk_flags=risk_flags,
            recommended_action=RecommendedAction.DRAFT_ONLY,
            module_events=[],
            draft_text=_DEFAULT_NO_MATCH_DRAFT,
        )

    def _no_context_decision(
        self,
        *,
        is_door_code: bool,
        direct_fact_attempted: Optional[str],
    ) -> AgentDecision:
        """Neither FAQ nor direct fact available — defer cleanly."""
        risk_flags: List[str] = []
        if is_door_code:
            risk_flags.append("access_credential_answer")

        missing: List[str] = ["property_knowledge.faq"]
        if direct_fact_attempted is not None:
            missing.append(f"property_facts.{direct_fact_attempted}")

        return AgentDecision(
            agent_name=self.name,
            intent_topic="access",
            confidence=_NO_MATCH_CONFIDENCE,
            answer_summary=(
                "No FAQ or direct property facts available for this "
                "access question; deferring to operator."
            ),
            evidence_used=[],
            missing_info=missing,
            risk_flags=risk_flags,
            recommended_action=RecommendedAction.DRAFT_ONLY,
            module_events=[],
            draft_text=_DEFAULT_NO_CONTEXT_DRAFT,
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _detect_direct_fact_key(text: str) -> Optional[str]:
        """Decide which structured fact (if any) this question is asking about.

        Returns one of:
          - "wifi"      — wifi/internet/password/network
          - "check_in"  — check-in time, arrival time
          - "check_out" — check-out time, departure time
          - None        — no direct-fact match; FAQ is the only path

        Order matters: check_in is tested before check_out because
        "check-in" and "check-out" share a substring boundary; the
        regexes themselves are unambiguous, but listing check_in first
        keeps the precedence explicit.

        Door-code questions deliberately do NOT have a direct-fact
        path. Door codes are per-reservation credentials, not
        per-property amenity facts — in real operator workflows they're
        generated late, gated by turnover-cycle steps (housekeeping +
        walkthrough), and issued proactively rather than retrieved on
        demand. The FAQ-fallback path catches them as a stopgap; the
        right long-term answer involves reservation context plus
        turnover-gate state, not a property_facts.door_code slot.
        See the module docstring's "Door-code carve-out" section.
        """
        if _matches_any(text, _WIFI_PATTERNS):
            return "wifi"
        if _matches_any(text, _CHECK_IN_PATTERNS):
            return "check_in"
        if _matches_any(text, _CHECK_OUT_PATTERNS):
            return "check_out"
        return None

    @staticmethod
    def _extract_faq_from_context(
        context: GuestContextBundle,
    ) -> List[Dict[str, Any]]:
        """Pull the FAQ list from the bundle's property_knowledge.faq."""
        faq = (context.property_knowledge or {}).get("faq")
        if not isinstance(faq, list):
            return []
        return faq

    @staticmethod
    def _faq_evidence_keys_used(
        context: GuestContextBundle,
    ) -> List[str]:
        """Return ['property_knowledge.faq'] iff the bundle registered
        the key, else []. Strict-subset rule — see HouseRulesAgent for
        the same pattern.
        """
        if "property_knowledge.faq" in (context.evidence_keys or []):
            return ["property_knowledge.faq"]
        return []
