import pytest

from app.services.concierge.market_brain import (
    build_market_brain_bundle,
    format_market_brain_context,
)
from app.services.concierge.market_source_adapters import (
    GooglePlacesAdapter,
    MarketSourceContext,
    MarketSourcePayload,
    WeatherGovAdapter,
)
from app.services.knowledge.market_inference import MarketInferenceResult


def test_format_market_brain_context_includes_market_topics_and_events():
    class Bundle:
        market_id = "MARKET_ASPEN"
        market_name = "Aspen, Colorado"
        neighborhood = "West End"
        market_type = "mountain"
        local_topics = ["ski access", "winter roads", "shuttles"]
        live_conditions = ["Weather: Tonight | 31F | Snow showers likely"]
        active_alerts = ["Winter Weather Advisory"]
        featured_places = []
        upcoming_events = ["Food & Wine Classic at Wagner Park on 2026-06-14"]

    text = format_market_brain_context(Bundle())

    assert "Aspen, Colorado" in text
    assert "West End" in text
    assert "ski access" in text
    assert "Snow showers likely" in text
    assert "Winter Weather Advisory" in text
    assert "Food & Wine Classic" in text


@pytest.mark.asyncio
async def test_build_market_brain_bundle_resolves_from_property_coordinates(monkeypatch):
    async def fake_property_snapshot(session, property_code, property_name):
        return {
            "property_code": "CHALET-1",
            "name": "Aspen Chalet",
            "latitude": 39.1911,
            "longitude": -106.8175,
            "city": "Aspen",
            "state": "CO",
        }

    async def fake_registry_row(session, market_id):
        return {
            "market_id": market_id,
            "market_name": "Aspen, Colorado",
            "market_type": "mountain",
        }

    async def fake_source_payload(session, context):
        assert context.market_id == "MARKET_ASPEN"
        return MarketSourcePayload(
            live_conditions=["Weather: Tonight | 31F | Snow showers likely"],
            active_alerts=["Winter Weather Advisory"],
            upcoming_events=["Lift Opening Celebration at Gondola Plaza on 2026-12-01"],
            featured_places=["Ajax Tavern (restaurant) — Aspen, CO"],
            weather_summary="Tonight | 31F | Snow showers likely",
            weather_source="weather.gov",
            source_attribution=["weather.gov", "market_events_db"],
        )

    async def fake_infer(coords, fallback_market_id=None):
        assert coords == [(39.1911, -106.8175)]
        return MarketInferenceResult(
            market_id="MARKET_ASPEN",
            market_name="Aspen, Colorado",
            market_type="mountain",
            neighborhood="West End",
            confidence=0.93,
            centroid_lat=39.1911,
            centroid_lng=-106.8175,
            property_count=1,
            inferred_from="registry_match",
            confirmation_message="Your properties appear to be in Aspen, Colorado.",
        )

    monkeypatch.setattr(
        "app.services.concierge.market_brain._load_property_snapshot",
        fake_property_snapshot,
    )
    monkeypatch.setattr(
        "app.services.concierge.market_brain._load_market_registry_row",
        fake_registry_row,
    )
    monkeypatch.setattr(
        "app.services.concierge.market_brain.assemble_market_source_payload",
        fake_source_payload,
    )
    monkeypatch.setattr(
        "app.services.concierge.market_brain.infer_market_from_properties",
        fake_infer,
    )
    monkeypatch.setattr(
        "app.services.concierge.market_brain._registry_topics",
        lambda market_id, neighborhood_name: ["ski access", "mountain dining"],
    )

    bundle = await build_market_brain_bundle(
        session=object(),
        property_code="CHALET-1",
    )

    assert bundle.market_id == "MARKET_ASPEN"
    assert bundle.market_name == "Aspen, Colorado"
    assert bundle.market_type == "mountain"
    assert bundle.neighborhood == "West End"
    assert bundle.confidence == 0.93
    assert bundle.local_topics == ["ski access", "mountain dining"]
    assert bundle.live_conditions == ["Weather: Tonight | 31F | Snow showers likely"]
    assert bundle.active_alerts == ["Winter Weather Advisory"]
    assert bundle.featured_places == ["Ajax Tavern (restaurant) — Aspen, CO"]
    assert bundle.weather_summary == "Tonight | 31F | Snow showers likely"
    assert bundle.weather_source == "weather.gov"
    assert bundle.upcoming_events == ["Lift Opening Celebration at Gondola Plaza on 2026-12-01"]
    assert bundle.metadata["source_attribution"] == ["weather.gov", "market_events_db"]


def test_google_places_adapter_uses_market_config_for_radius_and_types():
    adapter = GooglePlacesAdapter()
    context = MarketSourceContext(
        market_id="MARKET_30A",
        market_name="30A Florida",
        market_type="beach",
        latitude=30.3,
        longitude=-86.1,
        sources_config={
            "google_places": {
                "enabled": True,
                "radius_meters": 1800,
                "included_types": ["restaurant", "cafe"],
                "max_result_count": 4,
            }
        },
    )

    assert adapter._radius_for_context(context) == 1800.0
    assert adapter._included_types_for_context(context) == ["restaurant", "cafe"]
    assert adapter._max_results_for_context(context) == 4


def test_weather_adapter_can_be_disabled_via_market_config():
    adapter = WeatherGovAdapter()
    context = MarketSourceContext(
        market_id="MARKET_30A",
        market_name="30A Florida",
        market_type="beach",
        latitude=30.3,
        longitude=-86.1,
        sources_config={"weather": {"enabled": False}},
    )

    assert adapter._enabled(context) is False
