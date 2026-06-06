from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.feature_flags import FeatureFlagService, _cache


class _FakeResult:
    def __init__(self, enabled):
        self._enabled = enabled

    def fetchone(self):
        if self._enabled is None:
            return None
        return SimpleNamespace(enabled=self._enabled)


@pytest.fixture(autouse=True)
def clear_flag_cache():
    _cache._cache.clear()
    _cache._timestamps.clear()
    yield
    _cache._cache.clear()
    _cache._timestamps.clear()


@pytest.mark.anyio
async def test_is_enabled_reads_company_flag_without_property_code():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_FakeResult(True))

    value = await FeatureFlagService(db=db).is_enabled(
        "messaging_brain_runtime",
        company_id="tenant-1",
        property_code=None,
    )

    assert value is True
    params = db.execute.await_args.args[1]
    sql = str(db.execute.await_args.args[0])
    assert "property_code IS NULL" in sql
    assert params == {"flag": "messaging_brain_runtime", "cid": "tenant-1"}


@pytest.mark.anyio
async def test_is_enabled_treats_empty_string_like_company_level_lookup():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_FakeResult(True))

    value = await FeatureFlagService(db=db).is_enabled(
        "messaging_brain_runtime",
        company_id="tenant-1",
        property_code="",
    )

    assert value is True
    params = db.execute.await_args.args[1]
    sql = str(db.execute.await_args.args[0])
    assert "property_code IS NULL" in sql
    assert params == {"flag": "messaging_brain_runtime", "cid": "tenant-1"}


@pytest.mark.anyio
async def test_is_enabled_falls_back_to_company_when_property_row_missing():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_FakeResult(None), _FakeResult(True)])

    value = await FeatureFlagService(db=db).is_enabled(
        "messaging_brain_runtime",
        company_id="tenant-1",
        property_code="310FST",
    )

    assert value is True
    assert db.execute.await_count == 2
    prop_sql = str(db.execute.await_args_list[0].args[0])
    prop_params = db.execute.await_args_list[0].args[1]
    company_sql = str(db.execute.await_args_list[1].args[0])
    company_params = db.execute.await_args_list[1].args[1]
    assert "property_code = :prop" in prop_sql
    assert prop_params == {
        "flag": "messaging_brain_runtime",
        "cid": "tenant-1",
        "prop": "310FST",
    }
    assert "property_code IS NULL" in company_sql
    assert company_params == {"flag": "messaging_brain_runtime", "cid": "tenant-1"}


@pytest.mark.anyio
async def test_is_enabled_property_override_wins_over_company_level():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_FakeResult(False))

    value = await FeatureFlagService(db=db).is_enabled(
        "messaging_brain_runtime",
        company_id="tenant-1",
        property_code="310FST",
    )

    assert value is False
    assert db.execute.await_count == 1


@pytest.mark.anyio
async def test_is_enabled_defaults_false_when_no_rows_exist():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_FakeResult(None), _FakeResult(None)])

    value = await FeatureFlagService(db=db).is_enabled(
        "messaging_brain_runtime",
        company_id="tenant-1",
        property_code="310FST",
    )

    assert value is False


@pytest.mark.anyio
async def test_is_enabled_returns_false_without_raising_on_db_error():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=RuntimeError("db exploded"))

    value = await FeatureFlagService(db=db).is_enabled(
        "messaging_brain_runtime",
        company_id="tenant-1",
        property_code=None,
    )

    assert value is False
