from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value)
        except Exception:
            return None
    return None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except Exception:
            return None
    return None


class StayProactiveService:
    def evaluate(self, row: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        policy = (workflow.get("policy") or {}).get("proactive") if isinstance(workflow.get("policy"), dict) else {}
        policy = policy if isinstance(policy, dict) else {}
        receptiveness = workflow.get("receptiveness") if isinstance(workflow.get("receptiveness"), dict) else {}
        receptiveness = receptiveness if isinstance(receptiveness, dict) else {}
        phase = str(row.get("phase") or workflow.get("phase") or "").lower()
        latest_direction = str(row.get("latest_message_direction") or "").lower()
        latest_message_at = _parse_dt(row.get("latest_message_created_at") or row.get("last_message_at"))
        proactive_triggered_at = _parse_dt(row.get("proactive_triggered_at"))
        open_escalations = int(row.get("open_escalations") or 0)
        conversation_count = int(row.get("conversation_count") or 0)
        notification_count = int(row.get("notification_count") or 0)
        check_in = _parse_date(row.get("check_in"))
        check_out = _parse_date(row.get("check_out"))
        journey = workflow.get("journey") or {}
        property_context = row.get("property_context") if isinstance(row.get("property_context"), dict) else {}
        intelligence_context = workflow.get("intelligence_context") if isinstance(workflow.get("intelligence_context"), dict) else {}
        market_brain = intelligence_context.get("market_brain") if isinstance(intelligence_context.get("market_brain"), dict) else {}

        days_until_checkin = (check_in - now.date()).days if check_in else None
        days_until_checkout = (check_out - now.date()).days if check_out else None

        suppression_mode = "none"
        backoff_reason = None
        allowed_touch_family = "standard"
        guest_update_state = str(workflow.get("guest_update_state") or "").lower()
        min_hours_between_proactive_touches = max(1, int(policy.get("min_hours_between_proactive_touches") or 18))
        min_hours_between_service_updates = max(1, int(policy.get("min_hours_between_service_updates") or 4))
        max_notifications_per_stay_window = max(1, int(policy.get("max_notifications_per_stay_window") or 6))
        enabled_touch_types = {
            str(item).strip()
            for item in (policy.get("enabled_touch_types") or [])
            if str(item).strip()
        } or {
            "pre_arrival_welcome",
            "arrival_info",
            "dinner_planning",
            "arrival_day_checkin",
            "in_stay_checkin",
            "checkout_prep",
            "extend_offer",
            "service_update_reassurance",
        }
        allow_service_updates_during_escalation = bool(policy.get("allow_service_updates_during_escalation", True))

        recent_outbound = latest_direction == "outbound" and latest_message_at and (now - latest_message_at.astimezone(timezone.utc)) < timedelta(hours=min_hours_between_proactive_touches)
        recent_service_touch = proactive_triggered_at and (now - proactive_triggered_at.astimezone(timezone.utc)) < timedelta(hours=min_hours_between_service_updates)

        if open_escalations > 0:
            if allow_service_updates_during_escalation:
                allowed_touch_family = "service_updates_only"
                suppression_mode = "soft"
                backoff_reason = "open_escalation_controlled_updates"
            else:
                allowed_touch_family = "none"
                suppression_mode = "hard"
                backoff_reason = "open_escalation_messages_disabled"
        if guest_update_state == "awaiting_operator":
            suppression_mode = "hard"
            backoff_reason = "waiting_on_operator"
            allowed_touch_family = "none"
        elif recent_outbound:
            suppression_mode = "hard"
            backoff_reason = "recent_outbound_contact"
            allowed_touch_family = "none"
        elif notification_count >= max_notifications_per_stay_window and phase in {"pre_arrival", "arrival_day", "in_stay"}:
            suppression_mode = "hard"
            backoff_reason = "high_notification_volume"
            allowed_touch_family = "none"
        elif receptiveness.get("should_backoff_proactive"):
            suppression_mode = "hard"
            backoff_reason = "guest_contact_fatigue"
            allowed_touch_family = "none"

        touch_type = None
        message = None
        if allowed_touch_family == "standard":
            if phase == "pre_arrival" and days_until_checkin is not None:
                if days_until_checkin <= 3 and not journey.get("welcome_sent"):
                    touch_type = "pre_arrival_welcome"
                    message = self._welcome_message(row, property_context, market_brain, days_until_checkin)
                elif days_until_checkin <= 2 and not journey.get("checkin_reminder_sent"):
                    touch_type = "arrival_info"
                    message = self._arrival_info_message(row, property_context, market_brain)
                elif days_until_checkin <= 5 and conversation_count == 0:
                    touch_type = "dinner_planning"
                    message = self._dinner_message(row, market_brain)
            elif phase == "arrival_day" and latest_direction != "inbound":
                touch_type = "arrival_day_checkin"
                message = self._arrival_day_message(row, property_context, market_brain)
            elif phase == "in_stay" and latest_direction != "inbound" and conversation_count <= 6:
                touch_type = "in_stay_checkin"
                message = self._in_stay_message(row, market_brain)
            elif phase == "departure_day" and not journey.get("checkout_reminder_sent"):
                touch_type = "checkout_prep"
                message = self._checkout_message(row, property_context, market_brain)
            elif phase == "departure_day" and journey.get("checkout_reminder_sent") and days_until_checkout == 0 and not journey.get("extend_offer_sent"):
                touch_type = "extend_offer"
                message = self._extend_offer_message(row)
        elif allowed_touch_family == "service_updates_only":
            if (
                open_escalations > 0
                and not recent_service_touch
                and notification_count < 8
                and latest_direction != "outbound"
            ):
                touch_type = "service_update_reassurance"
                message = self._service_update_message(row, market_brain)

        if touch_type and touch_type not in enabled_touch_types:
            touch_type = None
            message = None

        base_score = 0.45
        if latest_direction == "inbound":
            base_score += 0.2
        if conversation_count > 0:
            base_score += 0.1
        if open_escalations == 0:
            base_score += 0.1
        if suppression_mode == "soft":
            base_score -= 0.1
        if suppression_mode == "hard":
            base_score -= 0.35
        if receptiveness:
            base_score = (base_score * 0.45) + (float(receptiveness.get("score") or 0.5) * 0.55)

        return {
            "eligible": bool(touch_type and message),
            "backoff_active": suppression_mode in {"soft", "hard"},
            "backoff_reason": backoff_reason,
            "suppression_mode": suppression_mode,
            "suppression_scope": "proactive_only",
            "allowed_touch_family": allowed_touch_family,
            "touch_type": touch_type,
            "message": message,
            "days_until_checkin": days_until_checkin,
            "days_until_checkout": days_until_checkout,
            "cadence_bucket": phase or "unknown",
            "receptiveness_score": round(max(0.0, min(1.0, base_score)), 2),
            "receptiveness_memory": receptiveness,
            "policy_snapshot": {
                "min_hours_between_proactive_touches": min_hours_between_proactive_touches,
                "min_hours_between_service_updates": min_hours_between_service_updates,
                "max_notifications_per_stay_window": max_notifications_per_stay_window,
                "allow_service_updates_during_escalation": allow_service_updates_during_escalation,
                "enabled_touch_types": sorted(enabled_touch_types),
            },
        }

    def _context_snippet(self, market_brain: dict[str, Any], *, include_events: bool = True) -> str:
        if not isinstance(market_brain, dict):
            return ""
        conditions = market_brain.get("live_conditions") if isinstance(market_brain.get("live_conditions"), list) else []
        alerts = market_brain.get("active_alerts") if isinstance(market_brain.get("active_alerts"), list) else []
        events = market_brain.get("upcoming_events") if isinstance(market_brain.get("upcoming_events"), list) else []
        if alerts:
            return f" Current local note: {alerts[0]}."
        if conditions:
            return f" Current local conditions: {conditions[0]}."
        if include_events and events:
            return f" Local heads-up: {events[0]}."
        return ""

    def _welcome_message(self, row: dict[str, Any], property_context: dict[str, Any], market_brain: dict[str, Any], days_until_checkin: int | None) -> str:
        guest = str(row.get("guest_name") or "there").split()[0]
        property_name = row.get("property_name") or "your stay"
        checkin_line = f"You're {days_until_checkin} day{'s' if days_until_checkin != 1 else ''} away from arrival at {property_name}."
        wifi = property_context.get("wifi_name") or property_context.get("wifi_network")
        wifi_line = f" I can also pass along WiFi details before arrival." if wifi else ""
        context_line = self._context_snippet(market_brain)
        return (
            f"Hi {guest} - {checkin_line} If you'd like, I can help with arrival questions, local dinner reservations, "
            f"or anything you want lined up before check-in.{wifi_line}{context_line}"
        )

    def _arrival_info_message(self, row: dict[str, Any], property_context: dict[str, Any], market_brain: dict[str, Any]) -> str:
        guest = str(row.get("guest_name") or "there").split()[0]
        property_name = row.get("property_name") or "your stay"
        wifi = property_context.get("wifi_name") or property_context.get("wifi_network")
        checkin_time = property_context.get("check_in_time") or property_context.get("checkin_time") or "later today"
        details = []
        if wifi:
            details.append(f"WiFi: {wifi}")
        if property_context.get("wifi_password"):
            details.append(f"Password: {property_context.get('wifi_password')}")
        detail_line = f" Quick info: {' · '.join(details)}." if details else ""
        context_line = self._context_snippet(market_brain)
        return (
            f"Hi {guest} - just a gentle pre-arrival note for {property_name}. Check-in is {checkin_time}.{detail_line} "
            f"If you'd like help with dinner plans, groceries, or arrival logistics, I’m happy to help.{context_line}"
        )

    def _dinner_message(self, row: dict[str, Any], market_brain: dict[str, Any]) -> str:
        guest = str(row.get("guest_name") or "there").split()[0]
        featured_places = market_brain.get("featured_places") if isinstance(market_brain.get("featured_places"), list) else []
        place_line = f" I can also suggest a nearby option like {featured_places[0]}." if featured_places else ""
        return (
            f"Hi {guest} - a quick note before your stay. If you want dinner reservations, groceries, or a few tailored local recommendations set up ahead of time, I can help with that.{place_line}"
        )

    def _arrival_day_message(self, row: dict[str, Any], property_context: dict[str, Any], market_brain: dict[str, Any]) -> str:
        guest = str(row.get("guest_name") or "there").split()[0]
        property_name = row.get("property_name") or "the property"
        context_line = self._context_snippet(market_brain)
        return (
            f"Hi {guest} - welcome to {property_name}. If anything would make arrival smoother today, including check-in details, parking, WiFi, or dinner plans, I’m here to help.{context_line}"
        )

    def _in_stay_message(self, row: dict[str, Any], market_brain: dict[str, Any]) -> str:
        guest = str(row.get("guest_name") or "there").split()[0]
        context_line = self._context_snippet(market_brain)
        return (
            f"Hi {guest} - just checking in gently to make sure everything is going smoothly. If you'd like help with reservations, local recommendations, or anything at the property, I’m here.{context_line}"
        )

    def _checkout_message(self, row: dict[str, Any], property_context: dict[str, Any], market_brain: dict[str, Any]) -> str:
        guest = str(row.get("guest_name") or "there").split()[0]
        checkout_time = property_context.get("check_out_time") or property_context.get("checkout_time") or "checkout time today"
        context_line = self._context_snippet(market_brain, include_events=False)
        return (
            f"Hi {guest} - just a gentle checkout reminder for today. Checkout is {checkout_time}. If you need a hand with departure details or want to ask about a late checkout, let me know.{context_line}"
        )

    def _extend_offer_message(self, row: dict[str, Any]) -> str:
        guest = str(row.get("guest_name") or "there").split()[0]
        return (
            f"Hi {guest} - if you’re enjoying the stay and want to ask about extending a bit longer, I can check availability for you."
        )

    def _service_update_message(self, row: dict[str, Any], market_brain: dict[str, Any]) -> str:
        guest = str(row.get("guest_name") or "there").split()[0]
        property_name = row.get("property_name") or "the property"
        context_line = self._context_snippet(market_brain, include_events=False)
        return (
            f"Hi {guest} - just a quick update that we're actively working on the issue at {property_name}. "
            f"I'll keep you posted as we have something concrete to share.{context_line}"
        )


_SERVICE = StayProactiveService()


def get_stay_proactive_service() -> StayProactiveService:
    return _SERVICE
