from __future__ import annotations

from uuid import UUID

from app.services.extraction.canonical_block_service import CanonicalBlock
from app.services.extraction.deterministic_extractors import (
    ContactInfoExtractor,
    DirectionNoteExtractor,
    ReservationInfoExtractor,
    WifiExtractor,
    extract_deterministic_candidates,
)
from app.services.extraction.validation_rules import DETERMINISTIC_VALIDATOR


TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")
PROPERTY_ID = UUID("22222222-2222-2222-2222-222222222222")


def _canonical_block(
    render_type: str,
    data,
    *,
    scope_type: str = "property",
    duplicate_group_metadata=None,
) -> CanonicalBlock:
    return CanonicalBlock(
        block_hash="abc123",
        render_type=render_type,
        tenant_id=TENANT_ID,
        canonical_source_property_id=PROPERTY_ID,
        canonical_page_id=3367,
        applicable_property_ids=[PROPERTY_ID],
        scope_type=scope_type,
        duplicate_group_metadata=duplicate_group_metadata,
        duplicate_count=1,
        block_content={
            "id": 99,
            "render_type": render_type,
            "title": "Sample",
            "data": data,
        },
    )


def test_reservation_info_extractor_maps_typed_fields():
    block = _canonical_block(
        "widget.reservation_info",
        {
            "checkin_time": "16:00:00",
            "checkout_time": "09:00:00",
            "bedroom_count": 4,
            "bathroom_count": 5,
            "guest_count": 12,
        },
        duplicate_group_metadata={
            "group_id": "widget_reservation_info_group",
            "member_property_ids": [PROPERTY_ID],
            "member_count": 1,
            "block_hash": "abc123",
        },
    )

    payloads = ReservationInfoExtractor().extract(block)

    by_question = {payload.proposed_question_text: payload for payload in payloads}
    assert set(by_question) == {
        "What time is check-in?",
        "What time is check-out?",
        "How many bedrooms does the property have?",
        "How many bathrooms does the property have?",
        "What's the maximum occupancy?",
    }
    assert by_question["What time is check-in?"].proposed_answer_text == "4:00 PM"
    assert by_question["What time is check-in?"].proposed_topic_id == "check_in_process"
    assert by_question["How many bedrooms does the property have?"].proposed_topic_id == "sleeping_arrangement"
    assert by_question["What's the maximum occupancy?"].proposed_topic_id == "max_occupancy"
    assert (
        by_question["What time is check-in?"].proposed_metadata["duplicate_group_metadata"]["group_id"]
        == "widget_reservation_info_group"
    )
    assert by_question["What time is check-in?"].proposed_metadata["duplicate_group_metadata"]["member_property_ids"] == [
        str(PROPERTY_ID)
    ]


def test_reservation_info_extractor_skips_blank_and_null_fields():
    block = _canonical_block(
        "widget.reservation_info",
        {
            "checkin_time": "16:00:00",
            "checkout_time": "",
            "bedroom_count": None,
            "bathroom_count": 2,
            "guest_count": None,
        },
    )

    payloads = ReservationInfoExtractor().extract(block)

    questions = [payload.proposed_question_text for payload in payloads]
    assert questions == [
        "What time is check-in?",
        "How many bathrooms does the property have?",
    ]


def test_wifi_extractor_maps_name_and_password():
    block = _canonical_block(
        "widget.wifi",
        {
            "wifi_name": "House Wifi",
            "wifi_password": "secret123",
        },
    )

    payloads = WifiExtractor().extract(block)

    assert [payload.proposed_question_text for payload in payloads] == [
        "What's the WiFi network name?",
        "What's the WiFi password?",
    ]
    assert payloads[0].proposed_answer_text == "House Wifi"
    assert payloads[1].proposed_answer_text == "secret123"
    assert all(payload.proposed_topic_id is None for payload in payloads)


def test_contact_info_extractor_forces_tenant_scope():
    block = _canonical_block(
        "widget.email_address",
        "info@example.com",
        scope_type="tenant",
    )

    payloads = ContactInfoExtractor("widget.email_address").extract(block)

    assert len(payloads) == 1
    assert payloads[0].scope_type == "tenant"
    assert payloads[0].scope_target_id == str(TENANT_ID)
    assert payloads[0].proposed_question_text == "What's the operator's email address?"


def test_direction_note_extractor_strips_html():
    block = _canonical_block(
        "home.direction_note",
        '<p>Turn <strong>left</strong> at the gate.</p>',
    )

    payloads = DirectionNoteExtractor().extract(block)

    assert len(payloads) == 1
    assert payloads[0].proposed_answer_text == "Turn left at the gate."
    assert payloads[0].proposed_question_text == "Are there special arrival directions?"


def test_router_returns_empty_for_unknown_render_type():
    block = _canonical_block("unknown.widget", {"value": "ignored"})
    assert extract_deterministic_candidates(block) == []


def test_router_uses_registered_extractor():
    block = _canonical_block(
        "widget.phone_number",
        "+1 850-555-0000",
        scope_type="tenant",
    )
    payloads = extract_deterministic_candidates(block)
    assert len(payloads) == 1
    assert payloads[0].proposed_question_text == "What's the operator's phone number?"


def test_reservation_info_validation_flags_implausible_bathroom_count():
    block = _canonical_block(
        "widget.reservation_info",
        {
            "checkin_time": "16:00:00",
            "checkout_time": "09:00:00",
            "bedroom_count": 1,
            "bathroom_count": 5,
            "guest_count": None,
            "bed_count": 0,
        },
    )

    payloads = extract_deterministic_candidates(block)

    assert payloads
    assert all(payload.confidence == 0.70 for payload in payloads)
    concern = payloads[0].proposed_metadata["validation_concern"]
    assert concern["concern_type"] == "implausible"
    assert concern["suggested_action"] == "stage_for_review"
    assert "bathroom_count" in concern["concern_description"]
    assert "validation_review" in payloads[0].proposed_tags


def test_wifi_validation_flags_missing_password_when_network_present():
    block = _canonical_block(
        "widget.wifi",
        {
            "wifi_name": "Beach House Wifi",
            "wifi_password": "",
        },
    )

    payloads = extract_deterministic_candidates(block)

    assert len(payloads) == 1
    assert payloads[0].confidence == 0.70
    assert payloads[0].proposed_metadata["validation_concern"]["concern_type"] == "sparse"


def test_contact_validation_flags_bad_email_format():
    block = _canonical_block(
        "widget.email_address",
        "not-an-email",
        scope_type="tenant",
    )

    payloads = extract_deterministic_candidates(block)

    assert len(payloads) == 1
    assert payloads[0].confidence == 0.70
    assert payloads[0].proposed_metadata["validation_concern"]["concern_type"] == "malformed"


def test_direction_note_validation_flags_very_short_text():
    block = _canonical_block(
        "home.direction_note",
        "<p>Turn left</p>",
    )

    payloads = extract_deterministic_candidates(block)

    assert len(payloads) == 1
    assert payloads[0].confidence == 0.70
    assert payloads[0].proposed_metadata["validation_concern"]["concern_type"] == "sparse"


def test_validator_ignores_sparse_guest_and_bed_counts_by_design():
    block = _canonical_block(
        "widget.reservation_info",
        {
            "checkin_time": "16:00:00",
            "checkout_time": "09:00:00",
            "bedroom_count": 4,
            "bathroom_count": 4,
            "guest_count": None,
            "bed_count": 0,
        },
    )
    payload = ReservationInfoExtractor().extract(block)[0]

    result = DETERMINISTIC_VALIDATOR.check(payload, block.block_content)

    assert result.passed is True
    assert result.suggested_action == "auto_promote"


def test_reservation_info_validation_flags_matching_checkin_checkout_time():
    block = _canonical_block(
        "widget.reservation_info",
        {
            "checkin_time": "16:00:00",
            "checkout_time": "16:00:00",
            "bedroom_count": 4,
            "bathroom_count": 4,
            "guest_count": None,
            "bed_count": 0,
        },
    )

    payloads = extract_deterministic_candidates(block)

    assert payloads
    assert payloads[0].proposed_metadata["validation_concern"]["concern_description"] == "check-in time matches check-out time"


def test_contact_validation_flags_website_without_scheme():
    block = _canonical_block(
        "widget.website",
        "beachhabitats30a.com",
        scope_type="tenant",
    )

    payloads = extract_deterministic_candidates(block)

    assert len(payloads) == 1
    assert payloads[0].confidence == 0.70
    assert payloads[0].proposed_metadata["validation_concern"]["concern_type"] == "malformed"
