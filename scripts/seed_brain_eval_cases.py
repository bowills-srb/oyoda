#!/usr/bin/env python3
"""
seed_brain_eval_cases.py — Seed the initial eval set with the 7 Session 9
golden-set cases.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict, List

from app.services.messaging_brain.eval.eval_case_store import upsert_case


SEED_CASES: List[Dict[str, Any]] = [
    {
        "case_key": "matthew_payment",
        "message_text": (
            "My business partner wants to pick up the second half payment. "
            "Can you please help us accommodate that?"
        ),
        "market_tag": "coastal_30a",
        "source": "curated_seed",
        "expected_intent_topic": "general",
        "expected_secondary_topics": [],
        "expected_sub_intents": ["payment_coordination"],
        "expected_constraint_keys": [],
        "expected_review": True,
        "expected_urgency": "medium",
        "notes": (
            "Payment-coordination logistics for an existing reservation. "
            "Doesn't fit access/maintenance/late_checkout/etc. Surfaces "
            "the open seam-map question about a future "
            "reservation_logistics topic."
        ),
    },
    {
        "case_key": "tracey_lounge_bed",
        "message_text": (
            "What is the size of bed in the lounge area? I'm looking for "
            "a four bedroom but wondering if it could work as a bedroom "
            "for one young man."
        ),
        "market_tag": "coastal_30a",
        "source": "curated_seed",
        "expected_intent_topic": "booking_inquiry",
        "expected_secondary_topics": [],
        "expected_sub_intents": ["sleeping_arrangement"],
        "expected_constraint_keys": ["sleeping_concern"],
        "expected_review": False,
        "expected_urgency": "medium",
        "notes": (
            "Pre-booking sleeping-arrangement question. Tests that 'lounge "
            "bed as bedroom' coerces to booking_inquiry with the nuance in "
            "sub_intents."
        ),
    },
    {
        "case_key": "trisha_portfolio",
        "message_text": (
            "Hello! Looking for any last minute deals for 5 days over the "
            "date of May 29th. Budget is around $6-7,000."
        ),
        "market_tag": "coastal_30a",
        "source": "curated_seed",
        "expected_intent_topic": "booking_inquiry",
        "expected_secondary_topics": [],
        "expected_sub_intents": ["portfolio_search", "pricing"],
        "expected_constraint_keys": ["dates.check_in", "budget.amount"],
        "expected_review": False,
        "expected_urgency": "medium",
        "notes": (
            "Open portfolio search with firm date window and budget. "
            "Tests structural extraction of dates and budget."
        ),
    },
    {
        "case_key": "dana_beach_gear",
        "message_text": (
            "My party is eyeing this space for the July 4th timeframe. "
            "We may all be flying in from a few different places, so we "
            "won't have the normal beach supplies we are used to bringing "
            "with us; does the home come with any beach chairs, carts, or "
            "coolers? If not, do you know if there is a chair service "
            "available on the beach?"
        ),
        "market_tag": "coastal_30a",
        "source": "curated_seed",
        "expected_intent_topic": "booking_inquiry",
        "expected_secondary_topics": [],
        "expected_sub_intents": ["amenities", "local_services"],
        "expected_constraint_keys": ["amenity_asks"],
        "expected_review": False,
        "expected_urgency": "medium",
        "notes": (
            "Pre-booking amenity question (beach gear) plus local services "
            "(chair rental). Tests dual sub_intents and amenity_asks "
            "extraction."
        ),
    },
    {
        "case_key": "mary_early_checkin",
        "message_text": (
            "How late early can you check in? Looking at flights 5/7 "
            "would need after 8pm check in or 5/8 10am"
        ),
        "market_tag": "coastal_30a",
        "source": "curated_seed",
        "expected_intent_topic": "late_checkout",
        "expected_secondary_topics": [],
        "expected_sub_intents": ["early_check_in"],
        "expected_constraint_keys": [],
        "expected_review": False,
        "expected_urgency": "medium",
        "notes": (
            "Arrival-time flexibility for an existing booking. Maps to "
            "late_checkout per existing brain semantics. Captures the "
            "open seam-map question about splitting late_checkout into "
            "arrival_timing and departure_timing."
        ),
    },
    {
        "case_key": "synthetic_ski",
        "message_text": (
            "Looking at your Breckenridge place for Presidents Day "
            "weekend. Are snow chains required to get to the property? "
            "And how far is the nearest lift?"
        ),
        "market_tag": "breckenridge_ski",
        "source": "curated_seed",
        "expected_intent_topic": "booking_inquiry",
        "expected_secondary_topics": [],
        "expected_sub_intents": ["road_access"],
        "expected_constraint_keys": ["amenity_asks"],
        "expected_review": False,
        "expected_urgency": "medium",
        "notes": (
            "Geography-test case. Tests that ski-specific concerns "
            "(snow chains, lift proximity) classify correctly under the "
            "LLM classifier without any code changes for the ski market."
        ),
    },
    {
        "case_key": "synthetic_gas_leak",
        "message_text": "I smell gas in the kitchen — is this normal??",
        "market_tag": "coastal_30a",
        "source": "curated_seed",
        "expected_intent_topic": "emergency",
        "expected_secondary_topics": [],
        "expected_sub_intents": [],
        "expected_constraint_keys": [],
        "expected_review": True,
        "expected_urgency": "emergency",
        "notes": "Life-safety emergency. Tests urgency-emergency routing.",
    },
]


async def _run() -> int:
    """Connect to the database and seed the cases."""
    from app.db.session import SessionLocal

    inserted = 0
    async with SessionLocal() as db:
        for case_kwargs in SEED_CASES:
            case_id = await upsert_case(db, **case_kwargs)
            print(f"  ✓ {case_kwargs['case_key']:30s} → {case_id}")
            inserted += 1

    print(f"\nSeeded {inserted} cases.")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
