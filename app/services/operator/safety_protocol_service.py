from __future__ import annotations

from typing import Any


class SafetyProtocolService:
    def evaluate(
        self,
        text_blob: str,
        *,
        policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = policy if isinstance(policy, dict) else {}
        normalized = (text_blob or "").lower()

        trigger_map = {
            "gas": ("life_safety", "evacuate_now", ["gas leak", "gas smell", "smell gas"]),
            "fire": ("life_safety", "evacuate_now", ["fire", "smoke", "sparking", "alarm going off"]),
            "flood": ("property_damage", "urgent_shutdown", ["flood", "flooding", "water everywhere", "burst pipe"]),
            "medical": ("life_safety", "call_emergency_services", ["injured", "medical", "not breathing", "ambulance"]),
            "intrusion": ("security", "call_emergency_services", ["intruder", "break in", "someone is inside", "unsafe person"]),
        }

        matched: list[str] = []
        severity = "none"
        protocol = "none"
        for label, (candidate_severity, candidate_protocol, tokens) in trigger_map.items():
            if any(token in normalized for token in tokens):
                matched.append(label)
                severity = candidate_severity
                protocol = candidate_protocol
                if candidate_severity == "life_safety":
                    break

        emergency_override = severity in {"life_safety", "security"}
        booking_hold_required = severity in {"life_safety", "property_damage", "security"}
        human_ack_required = emergency_override or bool(policy.get("require_human_ack_for_property_damage", True) and severity == "property_damage")

        guest_script = None
        if protocol == "evacuate_now":
            guest_script = (
                "Please leave the property immediately. Do not use lights, appliances, or switches. "
                "Once you are safely outside, call 911 or the local utility company and reply here to confirm you are out."
            )
        elif protocol == "call_emergency_services":
            guest_script = (
                "Please get to a safe place immediately and call 911 now. "
                "Reply here once you are safe so we can continue coordinating."
            )
        elif protocol == "urgent_shutdown":
            guest_script = (
                "Please avoid the affected area and do not use any nearby electrical devices. "
                "We are escalating this immediately and will share the next safety update as soon as possible."
            )

        return {
            "severity": severity,
            "protocol": protocol,
            "matched_triggers": matched,
            "emergency_override": emergency_override,
            "booking_hold_required": booking_hold_required,
            "human_ack_required": human_ack_required,
            "guest_script": guest_script,
        }


_SERVICE = SafetyProtocolService()


def get_safety_protocol_service() -> SafetyProtocolService:
    return _SERVICE
