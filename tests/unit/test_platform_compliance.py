from __future__ import annotations

from app.services.messaging_brain.policy.platform_compliance import (
    apply_pre_booking_draft_source_policy,
    evaluate_pre_booking_policy,
    PreBookingPolicyOutcome,
    SERVICE_ANIMAL_ACCOMMODATION_RESPONSE,
    is_esa_request,
    is_service_animal_request,
)


def test_service_animal_patterns_match_expected_phrasings():
    assert is_service_animal_request("I am traveling with a service dog.")
    assert is_service_animal_request("We have a guide dog with us.")
    assert is_service_animal_request("This is a service animal request.")


def test_service_animal_patterns_do_not_false_positive_on_unrelated_service_text():
    assert not is_service_animal_request("Can you service the AC before we arrive?")
    assert not is_service_animal_request("Is animal print bedding included?")


def test_esa_detection_is_distinct_from_service_animal():
    assert is_esa_request("I have an emotional support dog.")
    assert not is_service_animal_request("I have an emotional support dog.")


def test_accommodation_response_constant_is_non_empty():
    assert "Service animals are welcome" in SERVICE_ANIMAL_ACCOMMODATION_RESPONSE


def test_prebooking_policy_send_now_for_clean_high_confidence_case():
    outcome = evaluate_pre_booking_policy(
        message="Do you have a high chair?",
        intent="amenities",
        confidence=0.84,
        requested_nights=4,
        requested_guests=4,
        property_data={"max_guests": 8},
        operator_policies={"min_nights": 3},
        auto_send_threshold=0.75,
        flag_pricing_inquiries=True,
        flag_pet_inquiries=False,
        approval_mode="auto",
        missing_knowledge_topics=[],
    )

    assert outcome.decision == "send_now"
    assert outcome.flags == []
    assert outcome.warnings == []
    assert outcome.block_send is False


def test_prebooking_policy_holds_when_knowledge_gap_detected():
    outcome = evaluate_pre_booking_policy(
        message="Do you have a golf cart?",
        intent="amenities",
        confidence=0.84,
        requested_nights=4,
        requested_guests=4,
        property_data={"max_guests": 8},
        operator_policies={"min_nights": 3},
        auto_send_threshold=0.75,
        flag_pricing_inquiries=True,
        flag_pet_inquiries=False,
        approval_mode="auto",
        missing_knowledge_topics=["golf_cart"],
    )

    assert outcome.decision == "hold"
    assert "missing_property_knowledge:golf_cart" in outcome.warnings


def test_prebooking_draft_source_policy_forces_verification_hold():
    outcome = apply_pre_booking_draft_source_policy(
        outcome=PreBookingPolicyOutcome(decision="send_now"),
        draft_source="verification_required",
        intent="amenities",
        message="Can you confirm whether the property includes a golf cart?",
    )

    assert outcome.decision == "hold"
    assert "draft_source:verification_required" in outcome.warnings
    assert any("Verification follow-up required" in flag for flag in outcome.flags)
