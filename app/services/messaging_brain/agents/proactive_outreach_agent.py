"""
proactive_outreach_agent.py — Brain-owned proactive guest journey specialist.

Ship N scope:
  - Owns proactive draft composition for booking/stay/post-stay system triggers.
  - Reuses shared property/session/event context already loaded by the Brain.
  - Keeps the conservative policy stance: recommend DRAFT_ONLY and let the
    ResponsePolicyAgent make the final decision.

This agent intentionally does not introduce a second proactive cadence system.
Eligibility stays outside in canonical helpers; this agent owns composition.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from app.services.orchestration.messaging_brain_contracts import (
    AgentDecision,
    GuestContextBundle,
    InboundGuestMessage,
    MessageClassification,
    MessagingLifecycle,
    RecommendedAction,
)

_DEFAULT_CONFIDENCE = 0.64
_EVIDENCE_KEYS = (
    "property_facts.check_in_time",
    "property_facts.check_out_time",
    "property_facts.wifi",
    "guidebook_evidence",
    "guidebook_richness",
    "operator_guidance",
)


def _first_name(name: str) -> str:
    parts = [part for part in str(name or "").strip().split() if part]
    return parts[0] if parts else "there"


def _parse_iso_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


class ProactiveOutreachAgent:
    """Brain specialist for proactive system-event outreach."""

    name = "ProactiveOutreachAgent"
    handles_topics = (
        "system_welcome",
        "system_pre_arrival",
        "system_morning_brief",
        "system_extend_stay",
        "system_checkout_reminder",
        "system_post_stay",
    )

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
        payload = (message.metadata or {}).get("proactive_payload")
        payload = payload if isinstance(payload, dict) else {}
        trigger_type = classification.intent_topic

        draft_text = self._compose(trigger_type, payload, context, message)
        return AgentDecision(
            agent_name=self.name,
            intent_topic=trigger_type,
            confidence=_DEFAULT_CONFIDENCE,
            answer_summary=f"composed proactive outreach for {trigger_type}",
            evidence_used=self._cite_evidence(context),
            recommended_action=RecommendedAction.DRAFT_ONLY,
            draft_text=draft_text,
            module_events=[],
        )

    def _compose(
        self,
        trigger_type: str,
        payload: dict[str, Any],
        context: GuestContextBundle,
        message: InboundGuestMessage,
    ) -> str:
        guest = _first_name(message.guest_name)
        property_name = (
            payload.get("property_name")
            or context.property_facts.get("property_name")
            or message.property_code
            or "your stay"
        )
        lifecycle = getattr(message, "lifecycle", None) or context.lifecycle
        wifi = context.property_facts.get("wifi")
        check_in_time = (
            context.property_facts.get("check_in_time")
            or context.property_facts.get("check_in")
            or "4:00 PM"
        )
        check_out_time = (
            context.property_facts.get("check_out_time")
            or context.property_facts.get("check_out")
            or "10:00 AM"
        )
        days_until_checkin = payload.get("days_until_checkin")
        market_note = self._market_note(payload)
        custom_service_note = str(payload.get("service_update_note") or "").strip()

        if trigger_type == "system_welcome":
            lead = (
                f"You're {days_until_checkin} day{'s' if days_until_checkin != 1 else ''} away from arrival at {property_name}."
                if isinstance(days_until_checkin, int)
                else f"Your stay at {property_name} is coming up soon."
            )
            wifi_line = " I can also share WiFi details before arrival." if wifi else ""
            return (
                f"Hi {guest} - {lead} If you'd like help with arrival questions, "
                f"dinner plans, or anything you want lined up before check-in, "
                f"I'm happy to help.{wifi_line}{market_note}"
            )

        if trigger_type == "system_pre_arrival":
            arrival_date = _parse_iso_date(payload.get("check_in_date"))
            arrival_hint = (
                f" ahead of your {arrival_date.strftime('%A')} arrival"
                if arrival_date
                else ""
            )
            wifi_line = f" WiFi: {wifi}." if wifi else ""
            return (
                f"Hi {guest} - just a quick pre-arrival note{arrival_hint} for {property_name}. "
                f"Check-in is {check_in_time}.{wifi_line} If you'd like help with "
                f"groceries, dinner reservations, or arrival logistics, I’m here.{market_note}"
            )

        if trigger_type == "system_morning_brief":
            if lifecycle == MessagingLifecycle.PRE_ARRIVAL:
                return (
                    f"Hi {guest} - your stay at {property_name} is getting close. "
                    f"If you'd like me to help with arrival details, local plans, or "
                    f"anything you want arranged before check-in, I’m here.{market_note}"
                )
            if payload.get("touch_type") == "service_update_reassurance" and custom_service_note:
                return f"Hi {guest} - {custom_service_note}{market_note}"
            return (
                f"Hi {guest} - just checking in gently to make sure everything at "
                f"{property_name} is going smoothly. If you need help with the stay, "
                f"recommendations, or logistics, I’m here.{market_note}"
            )

        if trigger_type == "system_extend_stay":
            return (
                f"Hi {guest} - if you're enjoying your time at {property_name} and "
                f"want to ask about staying a little longer, I can check availability for you."
            )

        if trigger_type == "system_checkout_reminder":
            return (
                f"Hi {guest} - just a gentle reminder that checkout for {property_name} "
                f"is {check_out_time} today. If you need help with departure details or "
                f"want to ask about a late checkout, let me know.{market_note}"
            )

        if trigger_type == "system_post_stay":
            return (
                f"Hi {guest} - thank you again for staying at {property_name}. "
                f"If there's anything you need after the stay, or if you'd like to "
                f"come back in the future, I'm always happy to help."
            )

        return (
            f"Hi {guest} - just a quick note regarding your stay at {property_name}. "
            f"If there's anything you need, I'm here to help.{market_note}"
        )

    @staticmethod
    def _market_note(payload: dict[str, Any]) -> str:
        market_brain = payload.get("market_brain")
        if not isinstance(market_brain, dict):
            return ""
        alerts = market_brain.get("active_alerts")
        if isinstance(alerts, list) and alerts:
            return f" Local heads-up: {alerts[0]}."
        conditions = market_brain.get("live_conditions")
        if isinstance(conditions, list) and conditions:
            return f" Local note: {conditions[0]}."
        events = market_brain.get("upcoming_events")
        if isinstance(events, list) and events:
            return f" Upcoming local note: {events[0]}."
        return ""

    @staticmethod
    def _cite_evidence(context: GuestContextBundle) -> list[str]:
        available = set(context.evidence_keys or [])
        return [key for key in _EVIDENCE_KEYS if key in available]
