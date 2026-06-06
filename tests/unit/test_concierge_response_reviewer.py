import pytest

from app.services.messaging_brain.grounding.response_reviewer import (
    PLACEHOLDER_RESPONSE_PATTERNS,
    ConciergeReviewResult,
    _apply_placeholder_guard,
    _heuristic_review,
    match_placeholder_pattern,
)


def test_heuristic_review_routes_contract_negotiation_to_human_review():
    result = _heuristic_review(
        guest_message=(
            "I would like an amendment to our rental agreement that if a golf cart "
            "is not available we would be reimbursed $2,000."
        ),
        draft_response="We can absolutely update that for you and note the reimbursement.",
        source_context="property_name: Example House\ngolf cart: included when available",
        lifecycle_stage="pre_arrival",
        sender_role="guest",
    )

    assert result.verdict == "human_review"
    assert "negotiation_or_contract_change" in result.flags


def test_heuristic_review_flags_early_arrival_promises_for_revision():
    result = _heuristic_review(
        guest_message="We land at 12. Can we come earlier to the house?",
        draft_response="Certainly, you can check in at noon when you arrive.",
        source_context="check_in_time: 4:00 PM\nnote: early arrivals require confirmation",
        lifecycle_stage="pre_arrival",
        sender_role="guest",
    )

    assert result.verdict == "revise"
    assert "early_arrival_or_checkin_without_confirmation_language" in result.flags


def test_heuristic_review_blocks_off_platform_booking_language_for_prebooking_ota():
    result = _heuristic_review(
        guest_message="Is there anyway to book directly through your company with VRBO? Just trying to avoid fees.",
        draft_response="We can book you directly through our website if you'd like and help you avoid the Vrbo fees.",
        source_context="platform=vrbo\nsource=Vrbo pre-booking inquiry",
        lifecycle_stage="pre_booking",
        sender_role="guest",
    )

    assert result.verdict == "block"
    assert "off_platform_booking_policy_risk" in result.flags
    assert "response_encourages_off_platform_booking" in result.flags


def test_heuristic_review_flags_ungrounded_policy_decision():
    result = _heuristic_review(
        guest_message="Are we allowed to bring our own chairs and umbrella to the beach?",
        draft_response="Yes, you can absolutely bring your own setup to the beach.",
        source_context="property_name: Example House",
        lifecycle_stage="pre_booking",
        sender_role="guest",
    )

    assert result.verdict == "human_review"
    assert "ungrounded_policy_decision" in result.flags


def test_heuristic_review_blocks_service_animal_overreach_when_guest_only_said_pet():
    result = _heuristic_review(
        guest_message="Can we bring our dog?",
        draft_response="Service animals are always allowed, but pets are not.",
        source_context="pet_policy: not_allowed",
        lifecycle_stage="pre_booking",
        sender_role="guest",
    )

    assert result.verdict == "human_review"
    assert "response_introduces_service_animal_framing" in result.flags


def test_heuristic_review_flags_ungrounded_amenity_fact():
    result = _heuristic_review(
        guest_message="Is the golf cart a 4 or 6 seater and does it come with the booking?",
        draft_response="It is a 6 seater and comes with the booking at no extra fee.",
        source_context="property_name: Example House",
        lifecycle_stage="pre_booking",
        sender_role="guest",
    )

    assert result.verdict == "human_review"
    assert "ungrounded_amenity_fact" in result.flags


def test_heuristic_review_flags_ungrounded_golf_cart_policy_decision():
    result = _heuristic_review(
        guest_message="Are golf carts allowed at the property?",
        draft_response="Golf carts are not allowed on the property.",
        source_context="property_name: Example House\nmessage: Are golf carts allowed at the property?",
        lifecycle_stage="pre_booking",
        sender_role="guest",
    )

    assert result.verdict == "human_review"
    assert "ungrounded_policy_decision" in result.flags


def test_heuristic_review_allows_grounded_golf_cart_policy_decision():
    result = _heuristic_review(
        guest_message="Are golf carts allowed at the property?",
        draft_response="Golf carts are not allowed on the property.",
        source_context="property_name: Example House\ngrounded_golf_cart_policy: not_allowed",
        lifecycle_stage="pre_booking",
        sender_role="guest",
    )

    assert result.verdict == "approve"
    assert "ungrounded_policy_decision" not in result.flags


def test_apply_placeholder_guard_forces_human_review_on_insert_bracket():
    result = ConciergeReviewResult(
        verdict="approve",
        confidence=0.7,
        review_source="anthropic_adversarial",
        flags=["existing_flag"],
        rationale="initial rationale",
        reviewed_response="Your check-in code is [insert door code here].",
        scores={"intent_coverage": 0.5},
    )

    guarded = _apply_placeholder_guard(result)

    assert guarded.verdict == "human_review"
    assert guarded.reviewed_response == ""
    assert "placeholder_text_detected" in guarded.flags
    assert "existing_flag" in guarded.flags
    assert "placeholder_text_detected via pattern" in guarded.rationale
    assert "initial rationale" in guarded.rationale
    assert guarded.confidence == 0.7
    assert guarded.scores == {"intent_coverage": 0.5}
    assert guarded.review_source == "anthropic_adversarial"


def test_apply_placeholder_guard_passthrough_on_clean_reviewed_response():
    result = ConciergeReviewResult(
        verdict="approve",
        confidence=0.7,
        review_source="anthropic_adversarial",
        flags=["existing_flag"],
        rationale="initial rationale",
        reviewed_response="Your check-in code is 4231.",
        scores={"intent_coverage": 0.5},
    )

    guarded = _apply_placeholder_guard(result)

    assert guarded.verdict == "approve"
    assert guarded.reviewed_response == "Your check-in code is 4231."
    assert guarded.flags == ["existing_flag"]
    assert guarded.rationale == "initial rationale"


def test_apply_placeholder_guard_passthrough_on_empty_reviewed_response():
    result = ConciergeReviewResult(
        verdict="approve",
        confidence=0.7,
        review_source="heuristic",
        flags=[],
        rationale="heuristic review completed",
        reviewed_response="",
        scores={},
    )

    guarded = _apply_placeholder_guard(result)

    assert guarded.verdict == "approve"
    assert guarded.reviewed_response == ""
    assert "placeholder_text_detected" not in guarded.flags


def test_apply_placeholder_guard_preserves_rationale_when_initially_empty():
    result = ConciergeReviewResult(
        verdict="approve",
        confidence=0.7,
        review_source="anthropic_adversarial",
        flags=[],
        rationale="",
        reviewed_response="[insert WiFi password]",
        scores={},
    )

    guarded = _apply_placeholder_guard(result)

    assert guarded.verdict == "human_review"
    assert guarded.rationale.startswith("placeholder_text_detected via pattern")
    assert not guarded.rationale.startswith(";")


@pytest.mark.parametrize(
    "placeholder_text, expected_pattern_fragment",
    [
        ("Your code is [insert door code here]", r"\[insert"),
        ("The wifi password is [fill in wifi password]", r"\[fill"),
        ("The wifi password is [fill-in wifi password]", r"\[fill"),
        ("Check in at [placeholder time]", r"\[placeholder"),
        ("Email us at [your email address]", r"\[your"),
        ("Call [specific phone number]", r"\[specific"),
        ("[bracket text needs filling]", r"\[bracket"),
        ("Door code: [...]", r"\[\.\.\.\]"),
    ],
)
def test_match_placeholder_pattern_catches_all_patterns(
    placeholder_text,
    expected_pattern_fragment,
):
    matched = match_placeholder_pattern(placeholder_text)
    assert matched is not None
    assert expected_pattern_fragment in matched


def test_match_placeholder_pattern_returns_none_on_clean_text():
    assert match_placeholder_pattern("Your door code is 4231.") is None
    assert match_placeholder_pattern("") is None
    assert match_placeholder_pattern(None) is None  # type: ignore[arg-type]


def test_placeholder_response_patterns_count():
    """Guards against accidental pattern set drift."""
    assert len(PLACEHOLDER_RESPONSE_PATTERNS) == 7
