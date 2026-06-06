"""
test_llm_intake_agent_smoke.py — Golden-set smoke tests for LLMIntakeAgent.

Two modes:

  1. Default (mocked LLM): asserts that GIVEN the expected JSON output for
     each of the 7 representative messages, post-coercion produces the
     expected MessageClassification. This validates the post-parse logic
     against intended outputs without needing API access.

  2. Live mode (RUN_LIVE_LLM_TESTS=1 + ANTHROPIC_API_KEY set): runs the
     actual model against the same 7 messages and prints the results for
     manual inspection. Used to verify prompt calibration during
     development. Asserts only on shape (valid classification + topic
     in expected set), not exact values.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest

from app.services.messaging_brain.agents.llm_intake_agent import LLMIntakeAgent
from app.services.orchestration.messaging_brain_contracts import (
    InboundGuestMessage,
    KNOWN_INTENT_TOPICS,
)


def _make_inbound(text: str, *, message_id: str = "MSG_SMOKE") -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id=message_id,
        tenant_id="11111111-1111-1111-1111-111111111111",
        channel="email",
        source_provider="ota_parser_vrbo",
        text=text,
    )


GOLDEN_SET = [
    {
        "name": "matthew_payment",
        "message": (
            "My business partner wants to pick up the second half payment. "
            "Can you please help us accommodate that?"
        ),
        "mocked_llm_response": {
            "intent_type": "request",
            "intent_topic": "general",
            "secondary_topics": [],
            "sub_intents": ["payment_coordination"],
            "confidence": 0.70,
            "urgency": "medium",
            "requires_human_review": True,
            "reason": (
                "Existing-reservation payment logistics — guest is asking "
                "whether the second-half payment can be charged to a "
                "different payer. Doesn't fit other brain topics; flagged "
                "for human review."
            ),
            "extracted_constraints": {
                "other": "split second-half payment between two payers"
            },
        },
        "expected_intent_topic": "general",
        "expected_sub_intents_contains": ["payment_coordination"],
        "expected_review": True,
    },
    {
        "name": "tracey_lounge_bed",
        "message": (
            "What is the size of bed in the lounge area? I'm looking for a "
            "four bedroom but wondering if it could work as a bedroom for "
            "one young man."
        ),
        "mocked_llm_response": {
            "intent_type": "question",
            "intent_topic": "booking_inquiry",
            "secondary_topics": [],
            "sub_intents": ["sleeping_arrangement"],
            "confidence": 0.90,
            "urgency": "medium",
            "requires_human_review": False,
            "reason": (
                "Pre-booking question about whether lounge sleeping area "
                "can serve as a fourth bedroom."
            ),
            "extracted_constraints": {
                "sleeping_concern": "lounge bed as bedroom for one young man",
            },
        },
        "expected_intent_topic": "booking_inquiry",
        "expected_sub_intents_contains": ["sleeping_arrangement"],
        "expected_review": False,
    },
    {
        "name": "trisha_portfolio",
        "message": (
            "Hello! Looking for any last minute deals for 5 days over the "
            "date of May 29th. Budget is around $6-7,000."
        ),
        "mocked_llm_response": {
            "intent_type": "question",
            "intent_topic": "booking_inquiry",
            "secondary_topics": [],
            "sub_intents": ["portfolio_search", "pricing", "availability"],
            "confidence": 0.92,
            "urgency": "medium",
            "requires_human_review": False,
            "reason": "Open portfolio search with firm date window and budget.",
            "extracted_constraints": {
                "dates": {"check_in": "2026-05-29", "nights": 5},
                "budget": {"amount": 6500, "currency": "USD", "scope": "total"},
                "pricing_concern": "last_minute_discount",
            },
        },
        "expected_intent_topic": "booking_inquiry",
        "expected_sub_intents_contains": ["portfolio_search", "pricing"],
        "expected_review": False,
    },
    {
        "name": "dana_beach_gear",
        "message": (
            "My party is eyeing this space for the July 4th timeframe. We "
            "may all be flying in from a few different places, so we won't "
            "have the normal beach supplies we are used to bringing with "
            "us; does the home come with any beach chairs, carts, or "
            "coolers? If not, do you know if there is a chair service "
            "available on the beach?"
        ),
        "mocked_llm_response": {
            "intent_type": "question",
            "intent_topic": "booking_inquiry",
            "secondary_topics": [],
            "sub_intents": ["amenities", "local_services"],
            "confidence": 0.88,
            "urgency": "medium",
            "requires_human_review": False,
            "reason": (
                "Pre-booking amenity question (does property include beach "
                "gear) plus question about local beach chair service."
            ),
            "extracted_constraints": {
                "dates": {"check_in": "2026-07-04 (approximate)"},
                "amenity_asks": [
                    "beach chairs", "beach carts", "coolers", "beach chair service",
                ],
            },
        },
        "expected_intent_topic": "booking_inquiry",
        "expected_sub_intents_contains": ["amenities", "local_services"],
        "expected_review": False,
    },
    {
        "name": "mary_early_checkin",
        "message": (
            "How late early can you check in? Looking at flights 5/7 would "
            "need after 8pm check in or 5/8 10am"
        ),
        "mocked_llm_response": {
            "intent_type": "request",
            "intent_topic": "late_checkout",
            "secondary_topics": [],
            "sub_intents": ["early_check_in"],
            "confidence": 0.85,
            "urgency": "medium",
            "requires_human_review": False,
            "reason": (
                "Arrival time flexibility for an existing booking. Maps to "
                "late_checkout per existing brain semantics."
            ),
            "extracted_constraints": {
                "dates": {
                    "check_in": "2026-05-07 (after 8pm) or 2026-05-08 (10am)",
                },
                "other": "either late check-in May 7 or early check-in May 8",
            },
        },
        "expected_intent_topic": "late_checkout",
        "expected_sub_intents_contains": ["early_check_in"],
        "expected_review": False,
    },
    {
        "name": "synthetic_ski",
        "message": (
            "Looking at your Breckenridge place for Presidents Day weekend. "
            "Are snow chains required to get to the property? And how far "
            "is the nearest lift?"
        ),
        "mocked_llm_response": {
            "intent_type": "question",
            "intent_topic": "booking_inquiry",
            "secondary_topics": [],
            "sub_intents": ["road_access", "amenity_distance"],
            "confidence": 0.88,
            "urgency": "medium",
            "requires_human_review": False,
            "reason": (
                "Pre-booking question about road access requirements (chains) "
                "and lift proximity. Ski-specific guest concerns."
            ),
            "extracted_constraints": {
                "dates": {"check_in": "Presidents Day weekend"},
                "amenity_asks": [
                    "road access requirements", "distance to nearest lift",
                ],
            },
        },
        "expected_intent_topic": "booking_inquiry",
        "expected_sub_intents_contains": ["road_access"],
        "expected_review": False,
    },
    {
        "name": "synthetic_gas_leak",
        "message": "I smell gas in the kitchen — is this normal??",
        "mocked_llm_response": {
            "intent_type": "problem",
            "intent_topic": "emergency",
            "secondary_topics": [],
            "sub_intents": [],
            "confidence": 0.95,
            "urgency": "emergency",
            "requires_human_review": True,
            "reason": "Possible gas leak — life safety concern.",
            "extracted_constraints": {},
        },
        "expected_intent_topic": "emergency",
        "expected_sub_intents_contains": [],
        "expected_review": True,
    },
]


def _llm_envelope(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "text": json.dumps(payload),
        "input_tokens": 250,
        "output_tokens": 120,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("case", GOLDEN_SET, ids=[c["name"] for c in GOLDEN_SET])
async def test_golden_set_with_mocked_llm(case):
    agent = LLMIntakeAgent(anthropic_key="test-anth")

    with patch.object(
        agent,
        "_call_anthropic",
        new=AsyncMock(return_value=_llm_envelope(case["mocked_llm_response"])),
    ):
        classification, metadata = await agent.classify_with_metadata(
            _make_inbound(case["message"], message_id=f"MSG_{case['name'].upper()}"),
        )

    assert classification.intent_topic == case["expected_intent_topic"], (
        f"{case['name']}: expected intent_topic={case['expected_intent_topic']!r}, "
        f"got {classification.intent_topic!r}"
    )

    for expected_sub in case["expected_sub_intents_contains"]:
        assert expected_sub in classification.sub_intents, (
            f"{case['name']}: expected sub_intent {expected_sub!r} in "
            f"{classification.sub_intents!r}"
        )

    assert classification.requires_human_review == case["expected_review"], (
        f"{case['name']}: expected requires_human_review="
        f"{case['expected_review']}, got {classification.requires_human_review}"
    )

    assert metadata.classifier_source == "llm"
    assert metadata.provider_used == "anthropic"


_RUN_LIVE = os.getenv("RUN_LIVE_LLM_TESTS") == "1"


@pytest.mark.asyncio
@pytest.mark.skipif(not _RUN_LIVE, reason="RUN_LIVE_LLM_TESTS=1 required")
@pytest.mark.parametrize("case", GOLDEN_SET, ids=[c["name"] for c in GOLDEN_SET])
async def test_golden_set_live_anthropic(case):
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")

    agent = LLMIntakeAgent()
    classification, metadata = await agent.classify_with_metadata(
        _make_inbound(case["message"], message_id=f"MSG_LIVE_{case['name'].upper()}"),
    )

    assert classification.intent_topic in KNOWN_INTENT_TOPICS
    assert 0.0 <= classification.confidence <= 1.0
    assert metadata.classifier_source in {"llm", "keyword_fallback"}

    print(f"\n=== {case['name']} ===")
    print(f"Message: {case['message']!r}")
    print(f"Expected topic: {case['expected_intent_topic']}")
    print(f"Got topic:      {classification.intent_topic}")
    print(f"Got sub_intents: {classification.sub_intents}")
    print(f"Got reason: {classification.reason}")
    print(f"Got constraints: {classification.extracted_constraints}")
    print(f"Provider: {metadata.provider_used}, latency: {metadata.latency_ms}ms")
    print(f"Coercion notes: {metadata.coercion_notes}")
