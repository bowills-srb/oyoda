from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NormalizationCoverageSnapshot:
    total_inquiries: int
    normalized_inquiries: int
    coverage_ratio: float
    threshold_ratio: float
    window_hours: int

    @property
    def tripwire_fired(self) -> bool:
        return self.total_inquiries > 0 and self.coverage_ratio < self.threshold_ratio

    @property
    def coverage_percent(self) -> float:
        return round(self.coverage_ratio * 100.0, 2)

    @property
    def threshold_percent(self) -> float:
        return round(self.threshold_ratio * 100.0, 2)


async def get_normalization_coverage_snapshot(
    db,
    *,
    window_hours: int = 24,
    threshold_ratio: float = 0.95,
) -> NormalizationCoverageSnapshot:
    row = (
        await db.execute(
            text(
                """
                WITH base AS (
                    SELECT
                        pbi.company_id AS tenant_id,
                        COALESCE(pbi.gmail_message_id, pbi.message_id) AS inbound_message_id
                    FROM pre_booking_inquiries pbi
                    WHERE pbi.created_at >= NOW() - (:window_hours * INTERVAL '1 hour')
                )
                SELECT
                    COUNT(*) AS total_inquiries,
                    COUNT(*) FILTER (
                        WHERE EXISTS (
                            SELECT 1
                            FROM message_normalizations mn
                            WHERE mn.tenant_id = base.tenant_id
                              AND mn.source_channel = 'email'
                              AND mn.source_message_id = base.inbound_message_id
                        )
                    ) AS normalized_inquiries
                FROM base
                """
            ),
            {"window_hours": window_hours},
        )
    ).fetchone()

    total_value = 0
    normalized_value = 0
    if row is not None:
        if hasattr(row, "total_inquiries"):
            total_value = row.total_inquiries
            normalized_value = row.normalized_inquiries
        else:
            total_value = row[0]
            normalized_value = row[1]
    total = int(total_value or 0)
    normalized = int(normalized_value or 0)
    ratio = 1.0 if total == 0 else (normalized / total)
    return NormalizationCoverageSnapshot(
        total_inquiries=total,
        normalized_inquiries=normalized,
        coverage_ratio=ratio,
        threshold_ratio=threshold_ratio,
        window_hours=window_hours,
    )


async def run_normalization_coverage_tripwire(
    db,
    *,
    window_hours: int = 24,
    threshold_ratio: float = 0.95,
) -> NormalizationCoverageSnapshot:
    snapshot = await get_normalization_coverage_snapshot(
        db,
        window_hours=window_hours,
        threshold_ratio=threshold_ratio,
    )
    if snapshot.tripwire_fired:
        logger.error(
            "[CoverageTripwire] normalization_coverage_below_threshold "
            "coverage=%.2f covered=%d total=%d threshold=%.2f window_hours=%d",
            snapshot.coverage_percent,
            snapshot.normalized_inquiries,
            snapshot.total_inquiries,
            snapshot.threshold_percent,
            snapshot.window_hours,
        )
    return snapshot
