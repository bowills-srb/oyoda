from __future__ import annotations

from app.services.operator.safety_protocol_service import SafetyProtocolService


def test_safety_protocol_detects_life_safety_gas_event():
    service = SafetyProtocolService()

    result = service.evaluate("The guest says they smell gas in the kitchen")

    assert result["severity"] == "life_safety"
    assert result["protocol"] == "evacuate_now"
    assert result["emergency_override"] is True
    assert result["booking_hold_required"] is True
    assert "leave the property immediately" in (result["guest_script"] or "").lower()


def test_safety_protocol_marks_property_damage_for_flooding():
    service = SafetyProtocolService()

    result = service.evaluate("There is water everywhere and the unit is flooding")

    assert result["severity"] == "property_damage"
    assert result["protocol"] == "urgent_shutdown"
    assert result["human_ack_required"] is True
