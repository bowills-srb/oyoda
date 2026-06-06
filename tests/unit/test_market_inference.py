import pytest

from app.services.knowledge.market_inference import infer_market_from_properties


@pytest.mark.asyncio
async def test_infer_market_from_small_curated_market_center():
    result = await infer_market_from_properties([(30.3198, -86.1136)])

    assert result.market_id == "MARKET_30A"
    assert result.market_name == "30A Florida"
    assert result.market_type == "beach"
    assert result.inferred_from == "registry_match"
    assert result.confidence >= 0.3
