from __future__ import annotations

import pytest

from scripts import synthetic_inbound_pipeline_report as harness


@pytest.mark.asyncio
async def test_brain_primary_profile_passes_full_matrix():
    results = await harness.run_profile("brain_primary")

    assert results, "expected non-empty regression results"
    failures = {
        result.name: result.failures
        for result in results
        if result.failures
    }
    assert failures == {}


@pytest.mark.asyncio
async def test_kb_gap_case_requires_non_empty_blocked_topics():
    results = await harness.run_profile("ship_i_canary")
    kb_gap = next(result for result in results if result.name == "generic_pool_heat_gap")

    assert kb_gap.success is True
    assert kb_gap.blocked_topics == ["pool_heating_cost"]


@pytest.mark.asyncio
async def test_flag_matrix_runs_without_stale_flag_lookup_failures():
    results_by_profile = await harness.run_profiles(list(harness.PROFILES.keys()))

    for results in results_by_profile.values():
        for result in results:
            joined = " ".join(result.notes + result.failures)
            assert "flag lookup failed" not in joined.lower()
            assert "IndexError" not in joined
