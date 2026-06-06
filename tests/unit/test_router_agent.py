from __future__ import annotations

import logging

import pytest

from app.services.agents.router_agent import ConciergeRouter, Route


class _Ctx:
    property_code = "TEST_PROPERTY"
    operator_id = "TEST_OPERATOR"


@pytest.mark.asyncio
async def test_polite_hurt_idiom_routes_to_pms_query():
    decision = await ConciergeRouter(
        _Ctx(),
        eq_analyzer=None,
        watch=None,
        session_id="router-test",
    ).route("I was hoping for a late checkout, but it doesn't hurt to ask.")

    assert decision.route == Route.PMS_QUERY
    assert decision.trigger == "late checkout"


@pytest.mark.asyncio
async def test_real_injury_phrase_still_routes_to_urgent_escalation():
    decision = await ConciergeRouter(
        _Ctx(),
        eq_analyzer=None,
        watch=None,
        session_id="router-test",
    ).route("I got hurt at the property and need help.")

    assert decision.route == Route.ESCALATE_URGENT
    assert decision.trigger == "got hurt"


@pytest.mark.asyncio
async def test_escalation_logging_includes_route_trigger_and_preview(caplog):
    with caplog.at_level(logging.INFO, logger="app.services.agents.router_agent"):
        await ConciergeRouter(
            _Ctx(),
            eq_analyzer=None,
            watch=None,
            session_id="router-test",
        ).route("There is a gas leak in the kitchen.")

    assert any(
        "escalation route=escalate_urgent" in record.message
        and "gas leak" in record.message
        for record in caplog.records
    )
