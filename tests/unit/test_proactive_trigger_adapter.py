from __future__ import annotations

from app.services.messaging_brain.proactive_trigger_adapter import (
    proactive_touch_to_trigger,
    stage_to_lifecycle,
    stay_phase_to_lifecycle,
)
from app.services.orchestration.messaging_brain_contracts import MessagingLifecycle


def test_stage_to_lifecycle_maps_explicit_values():
    assert stage_to_lifecycle("booked") == MessagingLifecycle.PRE_ARRIVAL
    assert stage_to_lifecycle("in_stay") == MessagingLifecycle.IN_STAY
    assert stage_to_lifecycle("post_stay") == MessagingLifecycle.POST_STAY


def test_stay_phase_to_lifecycle_maps_operator_phases():
    assert stay_phase_to_lifecycle("pre_arrival") == MessagingLifecycle.PRE_ARRIVAL
    assert stay_phase_to_lifecycle("departure_day") == MessagingLifecycle.IN_STAY
    assert stay_phase_to_lifecycle("post_stay") == MessagingLifecycle.POST_STAY


def test_touch_type_maps_to_expected_trigger():
    assert proactive_touch_to_trigger(
        "pre_arrival_welcome",
        lifecycle=MessagingLifecycle.PRE_ARRIVAL,
    ) == "system_welcome"
    assert proactive_touch_to_trigger(
        "checkout_prep",
        lifecycle=MessagingLifecycle.IN_STAY,
    ) == "system_checkout_reminder"
