"""
general_agent.py — Decision-side handler for general concierge hospitality asks.

Ship L scope:
  - Owns the Brain's fallback handling for `general` and
    `local_recommendation` topics.
  - Reuses the canonical event-planning helper when the ask is clearly about
    stay-window events and we have dates.
  - Keeps the conservative Session 2-4 autonomy stance: recommend
    DRAFT_ONLY everywhere in this ship.

This agent is intentionally lightweight. It does not create a second FAQ,
market-intelligence, or concierge-planning system inside the Brain. It owns
the decision path and calls canonical helpers where appropriate.
"""

from __future__ import annotations

from datetime import date
import re
from typing import Any, Optional
from uuid import UUID

from app.services.concierge import (
    get_event_planning_service,
    is_event_planning_question,
)
from app.services.orchestration.messaging_brain_contracts import (
    AgentDecision,
    GuestContextBundle,
    InboundGuestMessage,
    MessageClassification,
    RecommendedAction,
)

_GREETING_CONFIDENCE = 0.72
_THANKS_CONFIDENCE = 0.72
_LOCAL_INFO_CONFIDENCE = 0.60
_EVENT_PLAN_CONFIDENCE = 0.70
_GENERAL_CONFIDENCE = 0.50

_DINING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brestaurants?\b", re.IGNORECASE),
    re.compile(r"\bdining\b", re.IGNORECASE),
    re.compile(r"\bfood\b", re.IGNORECASE),
    re.compile(r"\bbreakfast\b", re.IGNORECASE),
    re.compile(r"\blunch\b", re.IGNORECASE),
    re.compile(r"\bdinner\b", re.IGNORECASE),
)

_GREETING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bhi\b", re.IGNORECASE),
    re.compile(r"\bhello\b", re.IGNORECASE),
    re.compile(r"\bhey\b", re.IGNORECASE),
    re.compile(r"\bgood morning\b", re.IGNORECASE),
    re.compile(r"\bgood afternoon\b", re.IGNORECASE),
)

_THANKS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bthank(s| you)?\b", re.IGNORECASE),
    re.compile(r"\bappreciate\b", re.IGNORECASE),
)

_QUESTION_CUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\?", re.IGNORECASE),
    re.compile(r"\b(what|where|when|which|who|how)\b", re.IGNORECASE),
    re.compile(r"\b(can|could|would|will|do|does|did|is|are|am|may)\b", re.IGNORECASE),
    re.compile(r"\b(wondering|let me know|tell me|question)\b", re.IGNORECASE),
    re.compile(
        r"\b(bedroom|bedrooms|bunk|level|floor|stairs|entry|access|code|door|check[- ]?in|arrival|parking|pet|pool|rate|pricing|available|availability|dates)\b",
        re.IGNORECASE,
    ),
)


def _matches_any(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    if not text:
        return False
    return any(pattern.search(text) for pattern in patterns)


def _is_pure_thanks_message(text: str) -> bool:
    """Return True only for standalone gratitude, not gratitude plus an ask."""
    if not _matches_any(text, _THANKS_PATTERNS):
        return False
    return not _matches_any(text, _QUESTION_CUE_PATTERNS)


def _parse_iso_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


class GeneralAgent:
    """Brain specialist for greetings, thanks, and light concierge asks."""

    name = "GeneralAgent"
    handles_topics = ("general", "local_recommendation")

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
        lowered = text.lower()

        if _is_pure_thanks_message(lowered):
            return AgentDecision(
                agent_name=self.name,
                intent_topic=classification.intent_topic,
                confidence=_THANKS_CONFIDENCE,
                answer_summary="answered a thanks/handoff message",
                evidence_used=[],
                recommended_action=RecommendedAction.DRAFT_ONLY,
                draft_text=(
                    "You're very welcome! If anything else comes up, "
                    "I'm happy to help."
                ),
                module_events=[],
            )

        if _matches_any(lowered, _GREETING_PATTERNS):
            return AgentDecision(
                agent_name=self.name,
                intent_topic=classification.intent_topic,
                confidence=_GREETING_CONFIDENCE,
                answer_summary="answered a greeting-style message",
                evidence_used=[],
                recommended_action=RecommendedAction.DRAFT_ONLY,
                draft_text=(
                    "Hi! I'm here to help with anything you need. "
                    "What can I assist you with?"
                ),
                module_events=[],
            )

        if classification.intent_topic == "local_recommendation" and _matches_any(lowered, _DINING_PATTERNS):
            return AgentDecision(
                agent_name=self.name,
                intent_topic=classification.intent_topic,
                confidence=_LOCAL_INFO_CONFIDENCE,
                answer_summary="queued dining recommendation follow-up",
                evidence_used=[],
                recommended_action=RecommendedAction.DRAFT_ONLY,
                draft_text=(
                    "I'd be happy to help with dining ideas near the property. "
                    "Let me pull together the best options and send them over shortly."
                ),
                module_events=[],
            )

        if is_event_planning_question(text):
            trip_plan = await self._build_trip_plan(
                message=message,
                db_session=db_session,
            )
            if trip_plan and trip_plan.get("summary"):
                return AgentDecision(
                    agent_name=self.name,
                    intent_topic=classification.intent_topic,
                    confidence=_EVENT_PLAN_CONFIDENCE,
                    answer_summary="answered event-planning question via canonical event planning service",
                    evidence_used=[],
                    recommended_action=RecommendedAction.DRAFT_ONLY,
                    draft_text=str(trip_plan["summary"]),
                    module_events=[],
                )

            return AgentDecision(
                agent_name=self.name,
                intent_topic=classification.intent_topic,
                confidence=_LOCAL_INFO_CONFIDENCE,
                answer_summary="queued event-planning follow-up for operator review",
                evidence_used=[],
                missing_info=["stay_dates_for_event_planning"],
                recommended_action=RecommendedAction.DRAFT_ONLY,
                draft_text=(
                    "I'd be happy to help check what’s happening during your stay. "
                    "Let me pull together the best event options and follow up shortly."
                ),
                module_events=[],
            )

        if classification.intent_topic == "local_recommendation":
            return AgentDecision(
                agent_name=self.name,
                intent_topic=classification.intent_topic,
                confidence=_LOCAL_INFO_CONFIDENCE,
                answer_summary="queued local recommendation follow-up",
                evidence_used=[],
                recommended_action=RecommendedAction.DRAFT_ONLY,
                draft_text=(
                    "I'd be happy to help with local recommendations during your stay. "
                    "Let me pull together the best options nearby and follow up shortly."
                ),
                module_events=[],
            )

        return AgentDecision(
            agent_name=self.name,
            intent_topic=classification.intent_topic,
            confidence=_GENERAL_CONFIDENCE,
            answer_summary="handled a general concierge fallback message",
            evidence_used=[],
            missing_info=["general_concierge_follow_up"],
            recommended_action=RecommendedAction.DRAFT_ONLY,
            draft_text=(
                "Thanks for reaching out. I'm here to help, and I'll make sure "
                "the right follow-up goes out shortly."
            ),
            module_events=[],
        )

    async def _build_trip_plan(
        self,
        *,
        message: InboundGuestMessage,
        db_session: Any,
    ) -> Optional[dict[str, Any]]:
        if db_session is None:
            return None

        metadata = message.metadata or {}
        check_in = _parse_iso_date(metadata.get("check_in_date"))
        check_out = _parse_iso_date(metadata.get("check_out_date"))
        if not check_in or not check_out:
            return None

        property_id: Optional[UUID] = None
        if message.property_id:
            try:
                property_id = UUID(str(message.property_id))
            except (TypeError, ValueError):
                property_id = None

        try:
            return await get_event_planning_service().build_trip_plan(
                session=db_session,
                property_id=property_id,
                check_in_date=check_in,
                check_out_date=check_out,
                question_text=message.text,
            )
        except Exception:
            return None
