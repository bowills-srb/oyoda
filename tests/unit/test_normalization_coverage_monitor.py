from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from app.services.messaging.coverage_monitor import (
    get_normalization_coverage_snapshot,
    run_normalization_coverage_tripwire,
)


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeDb:
    def __init__(self, total: int, normalized: int):
        self._row = SimpleNamespace(
            total_inquiries=total,
            normalized_inquiries=normalized,
        )

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self._row)


@pytest.mark.asyncio
async def test_coverage_snapshot_100_percent_no_tripwire(caplog):
    db = _FakeDb(total=10, normalized=10)

    with caplog.at_level(logging.ERROR):
        snapshot = await run_normalization_coverage_tripwire(db)

    assert snapshot.total_inquiries == 10
    assert snapshot.normalized_inquiries == 10
    assert snapshot.coverage_percent == 100.0
    assert snapshot.tripwire_fired is False
    assert "[CoverageTripwire]" not in caplog.text


@pytest.mark.asyncio
async def test_coverage_snapshot_96_percent_no_tripwire(caplog):
    db = _FakeDb(total=25, normalized=24)

    with caplog.at_level(logging.ERROR):
        snapshot = await run_normalization_coverage_tripwire(db)

    assert snapshot.coverage_percent == 96.0
    assert snapshot.tripwire_fired is False
    assert "[CoverageTripwire]" not in caplog.text


@pytest.mark.asyncio
async def test_coverage_snapshot_94_percent_fires_tripwire(caplog):
    db = _FakeDb(total=100, normalized=94)

    with caplog.at_level(logging.ERROR):
        snapshot = await run_normalization_coverage_tripwire(db)

    assert snapshot.coverage_percent == 94.0
    assert snapshot.tripwire_fired is True
    assert "[CoverageTripwire] normalization_coverage_below_threshold" in caplog.text
    assert "coverage=94.00" in caplog.text
    assert "covered=94" in caplog.text
    assert "total=100" in caplog.text
    assert "threshold=95.00" in caplog.text


@pytest.mark.asyncio
async def test_coverage_snapshot_empty_window_is_graceful(caplog):
    db = _FakeDb(total=0, normalized=0)

    with caplog.at_level(logging.ERROR):
        snapshot = await run_normalization_coverage_tripwire(db)

    assert snapshot.total_inquiries == 0
    assert snapshot.normalized_inquiries == 0
    assert snapshot.coverage_percent == 100.0
    assert snapshot.tripwire_fired is False
    assert "[CoverageTripwire]" not in caplog.text


@pytest.mark.asyncio
async def test_snapshot_reads_counts_from_db_row():
    db = _FakeDb(total=7, normalized=5)

    snapshot = await get_normalization_coverage_snapshot(db, window_hours=12)

    assert snapshot.total_inquiries == 7
    assert snapshot.normalized_inquiries == 5
    assert snapshot.window_hours == 12
    assert snapshot.coverage_percent == round((5 / 7) * 100.0, 2)
