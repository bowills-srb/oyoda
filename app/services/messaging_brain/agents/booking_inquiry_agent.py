"""
booking_inquiry_agent.py — Decision-side handler for booking inquiries.

Phase 2 Session 6 — see docs/PHASE_2_SEAM_MAP.md.

Scope:
  - Handles the `booking_inquiry` topic routed from IntakeAgent's
    PMS_QUERY path.
  - Answers two high-value sub-cases first:
      1. availability-style questions ("is this available?", "are those
         dates open?") using requested-date context plus canonical PMS
         booking lookup when a DB session is available
      2. group-size / occupancy questions ("can it fit 8?", "how many
         guests can stay?") using `house_rules.max_guests` when present
  - Never emits ModuleEvents (booking inquiries are pure conversation).

Why this shape?
  Session 5 established the provider-agnostic pre-booking seam. This
  agent is the first specialist that depends on it directly: it reads
  provider-normalized requested dates / guests from `reservation_facts`
  and, when possible, supplements that with a canonical booking lookup
  against PMS cache data.

Safety posture:
  - Always recommends DRAFT_ONLY in Phase 2.
  - Availability answers are still review-first even when the lookup
    looks clean. A wrong "yes, it's open" answer is materially costly.
  - `booking_availability_unverified` and `booking_group_size_review`
    risk flags mark the paths future autonomy work must treat
    conservatively.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Optional
from uuid import UUID

from app.services.messaging.booking_context_adapters import (
    BookingContextAdapterConfig,
    BookingContextLookup,
    build_booking_context_adapter,
)
from app.services.orchestration.messaging_brain_contracts import (
    AgentDecision,
    GuestContextBundle,
    InboundGuestMessage,
    MessageClassification,
    RecommendedAction,
)

logger = logging.getLogger(__name__)

_CONFIDENT_CONTEXT_CONFIDENCE = 0.85
_PARTIAL_CONTEXT_CONFIDENCE = 0.68
_NO_CONTEXT_CONFIDENCE = 0.45

_AVAILABILITY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bavailable\b", re.IGNORECASE),
    re.compile(r"\bavailability\b", re.IGNORECASE),
    re.compile(r"\bopen\b", re.IGNORECASE),
    re.compile(r"\bdates?\b", re.IGNORECASE),
    re.compile(r"\bbook(?:ed|ing)?\b", re.IGNORECASE),
    re.compile(r"\breserve\b", re.IGNORECASE),
)

_PRICING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bprice(?:s|d)?\b", re.IGNORECASE),
    re.compile(r"\brate(?:s)?\b", re.IGNORECASE),
    re.compile(r"\bcost\b", re.IGNORECASE),
    re.compile(r"\bdiscount\b", re.IGNORECASE),
    re.compile(r"\bdeal\b", re.IGNORECASE),
)

_ACCESS_MISROUTE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bgate code\b", re.IGNORECASE),
    re.compile(r"\bdoor code\b", re.IGNORECASE),
    re.compile(r"\baccess code\b", re.IGNORECASE),
    re.compile(r"\blockbox\b", re.IGNORECASE),
    re.compile(r"\bcheck[\s-]?in instructions?\b", re.IGNORECASE),
)

_GROUP_SIZE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bhow many (?:guests|people)\b", re.IGNORECASE),
    re.compile(r"\bmax(?:imum)? (?:guests|occupancy|people)\b", re.IGNORECASE),
    re.compile(r"\bcan (?:it|this|the home|the property) fit\b", re.IGNORECASE),
    re.compile(r"\bsleeps?\b", re.IGNORECASE),
    re.compile(r"\boccupancy\b", re.IGNORECASE),
    re.compile(r"\bgroup size\b", re.IGNORECASE),
)

_EARLY_CHECKIN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bearly check[\s-]?in\b", re.IGNORECASE),
    re.compile(r"\bearly arrival\b", re.IGNORECASE),
)

_LATE_CHECKOUT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\blate check[\s-]?out\b", re.IGNORECASE),
    re.compile(r"\bstay later\b", re.IGNORECASE),
)

_CANCELLATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcancel(?:lation|led)?\b", re.IGNORECASE),
    re.compile(r"\brefund\b", re.IGNORECASE),
)

_GATHERING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bgathering\b", re.IGNORECASE),
    re.compile(r"\bcelebrat(?:e|ing|ion)\b", re.IGNORECASE),
    re.compile(r"\belop(?:e|ed|ement)\b", re.IGNORECASE),
    re.compile(r"\breception\b", re.IGNORECASE),
    re.compile(r"\bevent\b", re.IGNORECASE),
    re.compile(r"\bparty\b", re.IGNORECASE),
)

_DATE_TOKEN_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_DEFAULT_AVAILABILITY_HOLD = (
    "Thanks for your interest — I’m checking the calendar details now and "
    "will confirm the best answer for those dates shortly."
)
_DEFAULT_GROUP_SIZE_HOLD = (
    "Thanks for checking — I want to confirm the exact occupancy details "
    "before I answer so I give you the most accurate information."
)


def _matches_any(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in patterns)


def _parse_iso_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and _DATE_TOKEN_RE.match(value.strip()):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


class BookingInquiryAgent:
    """Specialist agent for booking availability / occupancy questions."""

    name = "BookingInquiryAgent"
    handles_topics = ("booking_inquiry",)

    def eligible_for_identity(self, identity_state: str) -> bool:
        return True

    async def run(
        self,
        *,
        message: InboundGuestMessage,
        classification: MessageClassification,
        context: GuestContextBundle,
        db_session: Any = None,
    ) -> AgentDecision:
        text = message.text or ""
        policy_decision = self._handle_policy_question(text=text, context=context)
        if policy_decision is not None:
            return policy_decision
        clarify_decision = self._handle_gathering_clarify(
            text=text,
            context=context,
        )
        if clarify_decision is not None:
            return clarify_decision
        is_group_size = _matches_any(text, _GROUP_SIZE_PATTERNS)
        if is_group_size:
            return await self._handle_group_size(
                message=message,
                context=context,
                db_session=db_session,
            )
        return await self._handle_availability(
            message=message,
            classification=classification,
            context=context,
            db_session=db_session,
        )

    async def _handle_availability(
        self,
        *,
        message: InboundGuestMessage,
        classification: MessageClassification,
        context: GuestContextBundle,
        db_session: Any,
    ) -> AgentDecision:
        evidence = self._cite_evidence(
            context,
            "reservation_facts.requested_check_in",
            "reservation_facts.requested_check_out",
        )
        check_in = _parse_iso_date(context.reservation_facts.get("requested_check_in"))
        check_out = _parse_iso_date(context.reservation_facts.get("requested_check_out"))
        availability_shaped = self._is_availability_shaped(
            message=message,
            classification=classification,
        )

        if not check_in or not check_out:
            if not availability_shaped:
                return AgentDecision(
                    agent_name=self.name,
                    intent_topic="booking_inquiry",
                    confidence=_NO_CONTEXT_CONFIDENCE,
                    answer_summary="non-availability booking inquiry routed here without actionable date context",
                    evidence_used=evidence,
                    missing_info=[],
                    risk_flags=["booking_inquiry_review"],
                    recommended_action=RecommendedAction.DRAFT_ONLY,
                    draft_text=(
                        "Thanks for reaching out — I’m reviewing the property details now so "
                        "I can make sure we give you the right information."
                    ),
                    module_events=[],
                )
            return AgentDecision(
                agent_name=self.name,
                intent_topic="booking_inquiry",
                confidence=_NO_CONTEXT_CONFIDENCE,
                answer_summary="availability question missing requested dates",
                evidence_used=evidence,
                missing_info=["requested_dates"],
                risk_flags=["booking_availability_unverified"],
                clarification_questions=[
                    "Which dates are you considering?",
                ],
                recommended_action=RecommendedAction.CLARIFY,
                draft_text=(
                    "Thanks for your interest! Could you share the dates you’re "
                    "considering so I can confirm availability accurately?"
                ),
                module_events=[],
            )

        lookup = await self._lookup_booking_context(
            tenant_id=context.tenant_id,
            property_code=context.property_code or message.property_code,
            check_in=check_in,
            check_out=check_out,
            db_session=db_session,
        )

        if lookup and lookup.get("available") is True and lookup.get("booking"):
            booking = lookup["booking"]
            status = str(booking.get("status") or "booked")
            draft_text = (
                f"Thanks for checking those dates. It looks like there may already "
                f"be a {status.replace('_', ' ')} stay overlapping that window, so "
                f"I’m confirming the best next option for you now."
            )
            return AgentDecision(
                agent_name=self.name,
                intent_topic="booking_inquiry",
                confidence=_CONFIDENT_CONTEXT_CONFIDENCE,
                answer_summary=f"calendar overlap found via {lookup.get('match_strategy', 'lookup')}",
                evidence_used=evidence,
                missing_info=[],
                risk_flags=["booking_availability_unverified"],
                recommended_action=RecommendedAction.DRAFT_ONLY,
                draft_text=draft_text,
                module_events=[],
            )

        if lookup and lookup.get("available") is False:
            return AgentDecision(
                agent_name=self.name,
                intent_topic="booking_inquiry",
                confidence=_PARTIAL_CONTEXT_CONFIDENCE,
                answer_summary=f"no overlapping booking found via {lookup.get('match_strategy', 'lookup')}",
                evidence_used=evidence,
                missing_info=["final_availability_confirmation"],
                risk_flags=["booking_availability_unverified"],
                recommended_action=RecommendedAction.DRAFT_ONLY,
                draft_text=(
                    "Those dates look promising from the current calendar snapshot, "
                    "and I’m confirming the final availability details now."
                ),
                module_events=[],
            )

        return AgentDecision(
            agent_name=self.name,
            intent_topic="booking_inquiry",
            confidence=_NO_CONTEXT_CONFIDENCE,
            answer_summary="availability question without verified calendar context",
            evidence_used=evidence,
            missing_info=["calendar_lookup_unavailable"],
            risk_flags=["booking_availability_unverified"],
            recommended_action=RecommendedAction.DRAFT_ONLY,
            draft_text=_DEFAULT_AVAILABILITY_HOLD,
            module_events=[],
        )

    def _is_availability_shaped(
        self,
        *,
        message: InboundGuestMessage,
        classification: MessageClassification,
    ) -> bool:
        sub_intents = {str(item).strip().lower() for item in (classification.sub_intents or []) if str(item).strip()}
        if sub_intents & {"availability", "pricing", "discount", "portfolio_search"}:
            return True

        extracted = classification.extracted_constraints or {}
        if extracted.get("dates") or extracted.get("budget") or extracted.get("pricing_concern"):
            return True

        text = message.text or ""
        if _matches_any(text, _ACCESS_MISROUTE_PATTERNS):
            return False
        if _matches_any(text, _AVAILABILITY_PATTERNS) or _matches_any(text, _PRICING_PATTERNS):
            return True
        return False

    async def _handle_group_size(
        self,
        *,
        message: InboundGuestMessage,
        context: GuestContextBundle,
        db_session: Any,
    ) -> AgentDecision:
        evidence = self._cite_evidence(
            context,
            "house_rules.max_guests",
            "reservation_facts.requested_guests",
        )

        requested_guests = context.reservation_facts.get("requested_guests")
        max_guests = context.house_rules.get("max_guests")

        if max_guests is None and db_session is not None:
            lookup = await self._lookup_booking_context(
                tenant_id=context.tenant_id,
                property_code=context.property_code or message.property_code,
                check_in=None,
                check_out=None,
                db_session=db_session,
            )
            property_snapshot = (lookup or {}).get("property") or {}
            bedrooms = property_snapshot.get("bedrooms")
            if bedrooms:
                # Fallback heuristic only when the PMS snapshot is all we have.
                max_guests = bedrooms * 2

        if max_guests is None:
            return AgentDecision(
                agent_name=self.name,
                intent_topic="booking_inquiry",
                confidence=_NO_CONTEXT_CONFIDENCE,
                answer_summary="group-size question missing occupancy context",
                evidence_used=evidence,
                missing_info=["max_guests"],
                risk_flags=["booking_group_size_review"],
                recommended_action=RecommendedAction.DRAFT_ONLY,
                draft_text=_DEFAULT_GROUP_SIZE_HOLD,
                module_events=[],
            )

        if requested_guests is None:
            return AgentDecision(
                agent_name=self.name,
                intent_topic="booking_inquiry",
                confidence=_PARTIAL_CONTEXT_CONFIDENCE,
                answer_summary=f"max occupancy available ({max_guests}) but guest count not supplied",
                evidence_used=evidence,
                missing_info=["requested_guests"],
                risk_flags=["booking_group_size_review"],
                clarification_questions=[
                    "How many guests would be in your group?",
                ],
                recommended_action=RecommendedAction.CLARIFY,
                draft_text=(
                    f"The home is set up for up to {max_guests} guests. If you’d "
                    "like, send over your group size and I can help confirm the fit."
                ),
                module_events=[],
            )

        if int(requested_guests) > int(max_guests):
            return AgentDecision(
                agent_name=self.name,
                intent_topic="booking_inquiry",
                confidence=_CONFIDENT_CONTEXT_CONFIDENCE,
                answer_summary=f"requested guests ({requested_guests}) exceed max occupancy ({max_guests})",
                evidence_used=evidence,
                missing_info=[],
                risk_flags=["booking_group_size_review"],
                recommended_action=RecommendedAction.DRAFT_ONLY,
                draft_text=(
                    f"Thanks for checking — the home is set up for up to {max_guests} "
                    f"guests, so a group of {requested_guests} would be above the usual limit. "
                    "I’m happy to confirm whether there’s a good alternative option."
                ),
                module_events=[],
            )

        return AgentDecision(
            agent_name=self.name,
            intent_topic="booking_inquiry",
            confidence=_CONFIDENT_CONTEXT_CONFIDENCE,
            answer_summary=f"requested guests ({requested_guests}) fit within max occupancy ({max_guests})",
            evidence_used=evidence,
            missing_info=[],
            risk_flags=["booking_group_size_review"],
            recommended_action=RecommendedAction.DRAFT_ONLY,
            draft_text=(
                f"Yes — the home is set up for up to {max_guests} guests, so a group "
                f"of {requested_guests} should fit well. I’m confirming the final stay "
                "details now so I can give you the clearest answer."
            ),
            module_events=[],
        )

    async def _lookup_booking_context(
        self,
        *,
        tenant_id: str,
        property_code: str,
        check_in: Optional[date],
        check_out: Optional[date],
        db_session: Any,
    ) -> Optional[dict]:
        if db_session is None:
            return None
        try:
            adapter = build_booking_context_adapter(
                BookingContextAdapterConfig(company_id=UUID(tenant_id)),
            )
            return await adapter.lookup(
                db_session,
                BookingContextLookup(
                    property_code=property_code or None,
                    check_in=check_in,
                    check_out=check_out,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[BookingInquiryAgent] booking lookup failed: %s", exc)
            return None

    @staticmethod
    def _cite_evidence(
        context: GuestContextBundle,
        *keys: str,
    ) -> list[str]:
        available = set(context.evidence_keys or [])
        return [key for key in keys if key in available]

    def _handle_policy_question(
        self,
        *,
        text: str,
        context: GuestContextBundle,
    ) -> Optional[AgentDecision]:
        policies = context.operator_policies or {}
        if not policies or not policies.get("_authored"):
            return None

        if _matches_any(text, _EARLY_CHECKIN_PATTERNS):
            evidence = self._cite_evidence(
                context,
                "operator_policies.early_checkin_available",
                "operator_policies.early_checkin_earliest",
                "operator_policies.early_checkin_fee",
                "operator_policies.early_checkin_subject_to_availability",
            )
            if not policies.get("early_checkin_available", False):
                draft = "Early check-in is not currently offered."
            else:
                draft = f"Early check-in is available from {policies.get('early_checkin_earliest') or 'the earlier approved time'}"
                fee = policies.get("early_checkin_fee")
                if fee not in (None, "", 0, 0.0):
                    draft += f" for a ${float(fee):.0f} fee"
                if policies.get("early_checkin_subject_to_availability", True):
                    draft += ", subject to availability"
                draft += "."
            return AgentDecision(
                agent_name=self.name,
                intent_topic="booking_inquiry",
                confidence=_PARTIAL_CONTEXT_CONFIDENCE,
                answer_summary="answered early check-in question from operator policies",
                evidence_used=evidence,
                missing_info=[],
                risk_flags=["booking_group_size_review"],
                recommended_action=RecommendedAction.DRAFT_ONLY,
                draft_text=draft,
                module_events=[],
            )

        if _matches_any(text, _LATE_CHECKOUT_PATTERNS):
            evidence = self._cite_evidence(
                context,
                "operator_policies.late_checkout_available",
                "operator_policies.late_checkout_max_time",
                "operator_policies.late_checkout_fee",
                "operator_policies.late_checkout_requires_approval",
            )
            if not policies.get("late_checkout_available", False):
                draft = "Late checkout is not currently offered."
            else:
                draft = f"Late checkout is available until {policies.get('late_checkout_max_time') or 'the approved time'}"
                fee = policies.get("late_checkout_fee")
                if fee not in (None, "", 0, 0.0):
                    draft += f" for a ${float(fee):.0f} fee"
                if policies.get("late_checkout_requires_approval", False):
                    draft += ", and it requires approval"
                draft += "."
            return AgentDecision(
                agent_name=self.name,
                intent_topic="booking_inquiry",
                confidence=_PARTIAL_CONTEXT_CONFIDENCE,
                answer_summary="answered late checkout question from operator policies",
                evidence_used=evidence,
                missing_info=[],
                risk_flags=["booking_group_size_review"],
                recommended_action=RecommendedAction.DRAFT_ONLY,
                draft_text=draft,
                module_events=[],
            )

        if _matches_any(text, _CANCELLATION_PATTERNS):
            evidence = self._cite_evidence(
                context,
                "operator_policies.cancellation_full_refund_days",
                "operator_policies.cancellation_partial_refund_days",
                "operator_policies.cancellation_partial_refund_percent",
            )
            full_days = policies.get("cancellation_full_refund_days")
            partial_days = policies.get("cancellation_partial_refund_days")
            partial_pct = policies.get("cancellation_partial_refund_percent")
            if full_days is None and partial_days is None:
                return None
            draft = f"Cancellations made {full_days} days or more before arrival receive a full refund."
            if partial_days is not None and partial_pct is not None:
                draft += f" Cancellations made {partial_days} days or more before arrival receive a {int(partial_pct)}% refund."
            return AgentDecision(
                agent_name=self.name,
                intent_topic="booking_inquiry",
                confidence=_PARTIAL_CONTEXT_CONFIDENCE,
                answer_summary="answered cancellation question from operator policies",
                evidence_used=evidence,
                missing_info=[],
                risk_flags=["booking_group_size_review"],
                recommended_action=RecommendedAction.DRAFT_ONLY,
                draft_text=draft,
                module_events=[],
            )

        return None

    def _handle_gathering_clarify(
        self,
        *,
        text: str,
        context: GuestContextBundle,
    ) -> Optional[AgentDecision]:
        if not _matches_any(text, _GATHERING_PATTERNS):
            return None

        evidence = self._cite_evidence(
            context,
            "house_rules.max_guests",
            "property_facts.max_guests",
            "reservation_facts.requested_guests",
        )
        max_guests = (
            context.house_rules.get("max_guests")
            or context.property_facts.get("max_guests")
        )

        opener = "Congratulations on the celebration."
        if re.search(r"\belop(?:e|ed|ement)\b", text, re.IGNORECASE):
            opener = "Congratulations on your elopement."

        if max_guests:
            draft_text = (
                f"{opener} The home is set up for up to {max_guests} guests. "
                "Could you share about how many people would be joining you, and whether you’re picturing a small family gathering or something more event-style?"
            )
        else:
            draft_text = (
                f"{opener} Could you share about how many people would be joining you, "
                "and whether you’re picturing a small family gathering or something more event-style?"
            )

        return AgentDecision(
            agent_name=self.name,
            intent_topic="booking_inquiry",
            confidence=_PARTIAL_CONTEXT_CONFIDENCE,
            answer_summary="gathering request needs guest-supplied event details before policy answer",
            evidence_used=evidence,
            missing_info=["requested_guests", "event_type"],
            clarification_questions=[
                "How many people would be joining you?",
                "Is this a small family gathering or a larger event-style celebration?",
            ],
            risk_flags=["booking_event_details_needed"],
            recommended_action=RecommendedAction.CLARIFY,
            draft_text=draft_text,
            module_events=[],
        )
