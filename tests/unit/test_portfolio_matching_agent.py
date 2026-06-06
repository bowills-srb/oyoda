"""
test_portfolio_matching_agent.py

Locks the contracts of the canonical PortfolioMatchingAgent retrieval executor.

Behavioral invariants covered:

  1. Passthrough  — portfolio_search not in sub_intents → zero-cost no-op,
                    no DB call, confidence=0.0
  2. No dates     — portfolio_search detected but no date_window extracted
                    → DRAFT_ONLY hold with status="no_dates"
  3. No portfolio — pms_listings empty for company (never synced)
                    → DRAFT_ONLY hold, missing_info contains "no_portfolio_data"
                    (NOT "nothing available" — that is a DIFFERENT empty case)
  4. Stale sync   — last_synced_at older than FRESHNESS_THRESHOLD_HOURS
                    → DRAFT_ONLY hold, missing_info contains "stale_hold"
  5. No candidates — listings exist, none match / available
                    → DRAFT_ONLY, answer_summary says "no listings available",
                    evidence_used cites pms_listings + pms_bookings
  6. Happy path   — candidates found → DRAFT_ONLY, draft_text="" (empty),
                    answer_summary contains structured facts for composer,
                    evidence_used cites canonical tables
  7. Hard limit   — result_limit_hint > RESULT_LIMIT is capped
  8. Unverified   — party_size / golf_cart / community / budget → missing_info

The DB is faked via a mock async DB that records how many SQL execute() calls
happen.  Test 3 verifies ONE execute (no per-property loop) for the happy path.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.services.messaging_brain.agents.portfolio_matching_agent import (
    FRESHNESS_THRESHOLD_HOURS,
    RESULT_LIMIT,
    PortfolioMatchingAgent,
    _parse_dates,
    _rank_by_proximity,
)
from app.services.orchestration.messaging_brain_contracts import (
    GuestContextBundle,
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    MessagingLifecycle,
    RecommendedAction,
    Urgency,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_TENANT_ID = "e07980b2-a990-4b24-91d1-c8cb71ab70e1"
_COMPANY_ID = UUID(_TENANT_ID)


def _make_classification(
    *,
    sub_intents: List[str] | None = None,
    extracted_constraints: Dict[str, Any] | None = None,
) -> MessageClassification:
    return MessageClassification(
        intent_type=IntentType.QUESTION,
        intent_topic="booking_inquiry",
        confidence=0.85,
        urgency=Urgency.MEDIUM,
        sub_intents=sub_intents or [],
        extracted_constraints=extracted_constraints or {},
    )


def _make_context(tenant_id: str = _TENANT_ID) -> GuestContextBundle:
    return GuestContextBundle(
        tenant_id=tenant_id,
        property_code="PROP-TEST-001",
        lifecycle=MessagingLifecycle.PRE_BOOKING,
    )


def _make_inbound() -> InboundGuestMessage:
    return InboundGuestMessage(
        message_id="test_001",
        tenant_id=_TENANT_ID,
        channel="sms",
        source_provider="twilio",
        text="send me a few similar properties for July 4 week",
        guest_phone="+18505551234",
    )


def _fresh_ts() -> datetime:
    """A last_synced_at that is within the freshness window."""
    return datetime.now(timezone.utc) - timedelta(hours=FRESHNESS_THRESHOLD_HOURS - 1)


def _stale_ts() -> datetime:
    """A last_synced_at that is beyond the freshness window."""
    return datetime.now(timezone.utc) - timedelta(hours=FRESHNESS_THRESHOLD_HOURS + 2)


def _make_fake_db(
    *,
    listing_count: int,
    last_synced_at: datetime | None = None,
    available_rows: List[Dict[str, Any]] | None = None,
) -> MagicMock:
    """Return a fake async SQLAlchemy session that replays canned responses.

    execute() call 1 → sync-check row (COUNT, MAX last_synced_at)
    execute() call 2 → anti-join rows (the candidate set)
    execute() call 3 → anchor-proximity lookup (optional — only when anchor set)
    """
    if last_synced_at is None:
        last_synced_at = _fresh_ts()

    available_rows = available_rows or []

    db = MagicMock()
    call_count = [0]

    async def _fake_execute(query, params=None):
        call_count[0] += 1
        n = call_count[0]
        mock_result = MagicMock()

        if n == 1:
            # sync-check: COUNT + MAX
            mock_result.mappings.return_value.first.return_value = {
                "cnt": listing_count,
                "latest_sync": last_synced_at if listing_count > 0 else None,
            }
        elif n == 2:
            # anti-join: candidate rows
            mock_result.mappings.return_value.all.return_value = [
                dict(r) for r in available_rows
            ]
        else:
            # anchor lookup: empty (no anchor in most tests)
            mock_result.mappings.return_value.first.return_value = None

        return mock_result

    db.execute = _fake_execute
    db._call_count = call_count
    return db


def _make_candidate(
    name: str = "Beach House",
    bedrooms: int = 3,
    bathrooms: float = 2.0,
    has_pool: bool = True,
    pet_friendly: bool = False,
    beach_access: bool = True,
    city: str = "Rosemary Beach",
    state: str = "FL",
) -> Dict[str, Any]:
    return {
        "id": str(uuid4()),
        "external_id": f"ext_{name.lower().replace(' ', '_')}",
        "property_name": name,
        "city": city,
        "state": state,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "has_pool": has_pool,
        "pet_friendly": pet_friendly,
        "beach_access": beach_access,
        "has_waterfront": False,
        "latitude": 30.27,
        "longitude": -86.03,
        "last_synced_at": _fresh_ts(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_passthrough_when_portfolio_search_not_in_sub_intents():
    """portfolio_search absent → zero-cost passthrough, no DB call."""
    agent = PortfolioMatchingAgent()
    db = MagicMock()
    db.execute = AsyncMock()

    decision = await agent.run(
        message=_make_inbound(),
        classification=_make_classification(sub_intents=["availability"]),
        context=_make_context(),
        db_session=db,
    )

    assert decision.confidence == 0.0
    assert "passthrough" in decision.answer_summary
    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_hold_when_portfolio_search_but_no_dates():
    """Dates missing from extracted_constraints → hold with no_dates status."""
    agent = PortfolioMatchingAgent()
    db = _make_fake_db(listing_count=5)

    decision = await agent.run(
        message=_make_inbound(),
        classification=_make_classification(
            sub_intents=["portfolio_search"],
            extracted_constraints={
                "portfolio_search": {},   # no date_window
                "bedroom_count": 3,
            },
        ),
        context=_make_context(),
        db_session=db,
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert "no_dates" in decision.missing_info
    # No DB call needed when we can gate early
    assert db._call_count[0] == 0


@pytest.mark.asyncio
async def test_hold_when_pms_listings_empty():
    """pms_listings empty for company → no_portfolio_data hold.

    Critical: must NOT say 'nothing available' (that is a different case).
    The agent returns a hold so the composer says 'let me follow up'.
    """
    agent = PortfolioMatchingAgent()
    db = _make_fake_db(listing_count=0)

    decision = await agent.run(
        message=_make_inbound(),
        classification=_make_classification(
            sub_intents=["portfolio_search"],
            extracted_constraints={
                "portfolio_search": {
                    "date_window": {"check_in": "2026-07-04", "check_out": "2026-07-11"},
                },
            },
        ),
        context=_make_context(),
        db_session=db,
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert "no_portfolio_data" in decision.missing_info
    assert "no_portfolio_data" in decision.answer_summary
    # Must not contain language that says "nothing available" (that is a lie
    # for an unconnected operator — they may have properties, just unsync'd)
    assert "nothing available" not in decision.answer_summary.lower()


@pytest.mark.asyncio
async def test_hold_when_sync_is_stale():
    """Stale last_synced_at → stale_hold, availability not asserted."""
    agent = PortfolioMatchingAgent()
    db = _make_fake_db(listing_count=10, last_synced_at=_stale_ts())

    decision = await agent.run(
        message=_make_inbound(),
        classification=_make_classification(
            sub_intents=["portfolio_search"],
            extracted_constraints={
                "portfolio_search": {
                    "date_window": {"check_in": "2026-07-04", "check_out": "2026-07-11"},
                },
            },
        ),
        context=_make_context(),
        db_session=db,
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert "stale_hold" in decision.missing_info
    assert "stale" in decision.answer_summary.lower()


@pytest.mark.asyncio
async def test_no_candidates_returns_draft_only_with_evidence():
    """Listings exist but none available → DRAFT_ONLY (not hold), evidence cited."""
    agent = PortfolioMatchingAgent()
    db = _make_fake_db(listing_count=8, available_rows=[])  # none available

    decision = await agent.run(
        message=_make_inbound(),
        classification=_make_classification(
            sub_intents=["portfolio_search"],
            extracted_constraints={
                "portfolio_search": {
                    "date_window": {"check_in": "2026-07-04", "check_out": "2026-07-11"},
                },
            },
        ),
        context=_make_context(),
        db_session=db,
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert "pms_listings" in decision.evidence_used
    assert "pms_bookings" in decision.evidence_used
    # answer_summary should explain "nothing available matching"
    assert "available" in decision.answer_summary.lower()
    # draft_text empty — composer writes prose
    assert decision.draft_text == ""


@pytest.mark.asyncio
async def test_happy_path_candidates_found():
    """Candidates returned → DRAFT_ONLY, draft_text empty, facts in answer_summary."""
    candidates = [
        _make_candidate("Sunset Retreat", bedrooms=4),
        _make_candidate("Beach Haven", bedrooms=3, has_pool=False),
    ]
    agent = PortfolioMatchingAgent()
    db = _make_fake_db(listing_count=20, available_rows=candidates)

    decision = await agent.run(
        message=_make_inbound(),
        classification=_make_classification(
            sub_intents=["portfolio_search"],
            extracted_constraints={
                "portfolio_search": {
                    "date_window": {"check_in": "2026-07-04", "check_out": "2026-07-11"},
                },
            },
        ),
        context=_make_context(),
        db_session=db,
    )

    assert decision.recommended_action == RecommendedAction.DRAFT_ONLY
    assert decision.draft_text == "", (
        "Portfolio agent must NOT compose prose — LLM composer does that"
    )
    assert "Sunset Retreat" in decision.answer_summary
    assert "Beach Haven" in decision.answer_summary
    assert "pms_listings" in decision.evidence_used
    assert "pms_bookings" in decision.evidence_used
    assert decision.confidence == 0.85


@pytest.mark.asyncio
async def test_set_based_query_uses_two_db_calls_not_per_property_loop():
    """Anti-join issues TWO DB calls regardless of candidate count.

    Legacy code did one COUNT(*) per property — N queries for N properties.
    The new implementation does:
      call 1: COUNT + MAX(last_synced_at) — presence + freshness
      call 2: the anti-join — all candidates in one shot

    With 50 listings in the portfolio, we still only see 2 execute() calls.
    """
    candidates = [_make_candidate(f"Property {i}") for i in range(10)]
    agent = PortfolioMatchingAgent()
    db = _make_fake_db(listing_count=50, available_rows=candidates)

    await agent.run(
        message=_make_inbound(),
        classification=_make_classification(
            sub_intents=["portfolio_search"],
            extracted_constraints={
                "portfolio_search": {
                    "date_window": {"check_in": "2026-07-04", "check_out": "2026-07-11"},
                },
            },
        ),
        context=_make_context(),
        db_session=db,
    )

    assert db._call_count[0] == 2, (
        f"Expected 2 DB calls (presence-check + anti-join), "
        f"got {db._call_count[0]} — per-property loop regression"
    )


@pytest.mark.asyncio
async def test_hard_limit_caps_result_set():
    """RESULT_LIMIT is the absolute cap regardless of result_limit_hint."""
    # Build RESULT_LIMIT + 5 candidates from the DB
    candidates = [
        _make_candidate(f"Property {i}") for i in range(RESULT_LIMIT + 5)
    ]
    agent = PortfolioMatchingAgent()
    # DB returns all candidates; the SQL LIMIT is enforced in the query
    # but here we trust the fake and cap in the query binding
    db = _make_fake_db(
        listing_count=100,
        available_rows=candidates[:RESULT_LIMIT],  # SQL LIMIT respected by fake
    )

    decision = await agent.run(
        message=_make_inbound(),
        classification=_make_classification(
            sub_intents=["portfolio_search"],
            extracted_constraints={
                "portfolio_search": {
                    "date_window": {"check_in": "2026-07-04", "check_out": "2026-07-11"},
                    "result_limit_hint": RESULT_LIMIT + 100,  # oversized hint
                },
            },
        ),
        context=_make_context(),
        db_session=db,
    )

    # answer_summary should mention the hard cap
    assert f"cap {RESULT_LIMIT}" in decision.answer_summary


@pytest.mark.asyncio
async def test_unverified_constraints_surfaced_in_missing_info():
    """party_size / golf_cart / community / budget → missing_info, not silently dropped."""
    candidates = [_make_candidate()]
    agent = PortfolioMatchingAgent()
    db = _make_fake_db(listing_count=5, available_rows=candidates)

    decision = await agent.run(
        message=_make_inbound(),
        classification=_make_classification(
            sub_intents=["portfolio_search"],
            extracted_constraints={
                "portfolio_search": {
                    "date_window": {"check_in": "2026-07-04", "check_out": "2026-07-11"},
                },
                "party_size": {"adults": 8, "children": 2},
                "amenity_asks": ["golf cart", "pool"],
                "budget": {"amount": 500, "currency": "USD", "scope": "per_night"},
            },
        ),
        context=_make_context(),
        db_session=db,
    )

    assert "party_size" in decision.missing_info
    assert "golf_cart"  in decision.missing_info
    assert "price_point" in decision.missing_info
    # Unverified also appears in the composer summary so it can hedge
    assert "party_size" in decision.answer_summary or "hedge" in decision.answer_summary


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests for pure helpers
# ─────────────────────────────────────────────────────────────────────────────


def test_parse_dates_iso_strings():
    ci, co = _parse_dates({"check_in": "2026-07-04", "check_out": "2026-07-11"})
    assert ci == date(2026, 7, 4)
    assert co == date(2026, 7, 11)


def test_parse_dates_date_objects():
    ci, co = _parse_dates({
        "check_in": date(2026, 7, 4),
        "check_out": date(2026, 7, 11),
    })
    assert ci == date(2026, 7, 4)
    assert co == date(2026, 7, 11)


def test_parse_dates_partial_returns_none_for_missing():
    ci, co = _parse_dates({"check_in": "2026-07-04"})
    assert ci == date(2026, 7, 4)
    assert co is None


def test_parse_dates_malformed_returns_none():
    ci, co = _parse_dates({"check_in": "not-a-date", "check_out": "also-bad"})
    assert ci is None
    assert co is None


def test_rank_by_proximity_sorts_by_bedroom_distance():
    anchor = {"latitude": 30.27, "longitude": -86.03, "bedrooms": 4}
    candidates = [
        {"property_name": "Far", "bedrooms": 6, "latitude": 30.27, "longitude": -86.03},
        {"property_name": "Near", "bedrooms": 4, "latitude": 30.27, "longitude": -86.03},
        {"property_name": "Mid", "bedrooms": 5, "latitude": 30.27, "longitude": -86.03},
    ]
    ranked = _rank_by_proximity(candidates, anchor)
    assert ranked[0]["property_name"] == "Near"   # 0 bedroom diff
    assert ranked[1]["property_name"] == "Mid"    # 1 bedroom diff
    assert ranked[2]["property_name"] == "Far"    # 2 bedroom diff
