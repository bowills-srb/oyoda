"""
Event Scrape Worker

Background worker that runs the local event scraper on a schedule
and on-demand when a new operator onboards.

Two job types:
  1. EventScrapeMarketJob   — scrape a single market (scheduled daily, or
                              triggered immediately on operator onboard)
  2. EventScrapeAllJob      — sweep all due markets (runs every 6h via cron)
  3. OperatorMarketDetectJob — fired after properties are imported for a new
                              operator; geocodes addresses, resolves/creates
                              the market, then immediately queues a scrape

Flow on new operator signup:
  Onboarding API
    → OperatorMarketDetectJob (after property import)
      → resolve_operator_market() — geocode → match/create MarketRegistryModel
        → EventScrapeMarketJob    — scrape all enabled sources
          → market_events table   (canonical records)
          → signals table         (DEMAND_PRESSURE per event)
          → concierge_knowledge   (RAG entries, scoped to market_id)

Flow on daily cron:
  EventScrapeAllJob
    → for each market in market_registry where last_scraped_at is due:
        EventScrapeMarketJob
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from pydantic import Field

from workers.base import (
    BaseWorker,
    JobPayload,
    JobResult,
    WorkerCategory,
    register_worker,
)

logger = logging.getLogger(__name__)


# =============================================================================
# PAYLOADS
# =============================================================================

class EventScrapeMarketPayload(JobPayload):
    """Scrape a single market."""
    market_id: str                      # e.g. "30a_fl"
    days_ahead: int = 90                # how far forward to scrape
    force: bool = False                 # ignore last_scraped_at throttle


class EventScrapeAllPayload(JobPayload):
    """Sweep all markets that are due for a refresh."""
    days_ahead: int = 90
    force: bool = False                 # re-scrape even if recently done


class OperatorMarketDetectPayload(JobPayload):
    """
    Triggered after a new operator's properties are imported.
    Resolves the market from property addresses and queues a scrape.
    """
    operator_id: str
    operator_name: str
    # Raw addresses pulled from the operator's properties table
    property_addresses: list[str] = Field(default_factory=list)
    days_ahead: int = 90


# =============================================================================
# WORKERS
# =============================================================================

@register_worker
class EventScrapeMarketWorker(BaseWorker[EventScrapeMarketPayload]):
    """
    Scrape local events for one market and persist results.

    On completion:
      - market_events rows upserted
      - DEMAND_PRESSURE signals emitted per event
      - concierge_knowledge entries upserted (RAG)
      - market_registry.last_scraped_at updated
    """

    name            = "event_scrape_market_worker"
    category        = WorkerCategory.INGESTION
    max_retries     = 2
    timeout_seconds = 300   # 5 min — most markets finish in <60s

    async def process(self, payload: EventScrapeMarketPayload) -> JobResult:
        from tools.event_scraper import EventScrapeOrchestrator, KNOWN_MARKETS

        market_name = (KNOWN_MARKETS.get(payload.market_id) or {}).get("name", payload.market_id)
        self.logger.info(f"[EventScrape] Starting scrape: {market_name}")

        # Throttle check (unless forced)
        if not payload.force:
            last = await self._last_scraped(payload.market_id)
            if last:
                age_hours = (datetime.now(tz=timezone.utc) - last).total_seconds() / 3600
                min_interval = await self._scrape_interval(payload.market_id)
                if age_hours < min_interval:
                    self.logger.info(
                        f"[EventScrape] {market_name} scraped {age_hours:.1f}h ago "
                        f"(interval={min_interval}h), skipping"
                    )
                    return JobResult(
                        success=True,
                        data={"skipped": True, "reason": "throttled", "age_hours": age_hours},
                        items_processed=0,
                    )

        try:
            async with EventScrapeOrchestrator(days_ahead=payload.days_ahead) as orc:
                events = await orc.scrape_market(payload.market_id)

            # Summary by category
            by_cat: dict[str, int] = {}
            for ev in events:
                by_cat[ev.category] = by_cat.get(ev.category, 0) + 1

            self.logger.info(
                f"[EventScrape] {market_name}: {len(events)} events — {by_cat}"
            )

            return JobResult(
                success=True,
                data={
                    "market_id":    payload.market_id,
                    "market_name":  market_name,
                    "event_count":  len(events),
                    "by_category":  by_cat,
                    "scraped_at":   datetime.now(tz=timezone.utc).isoformat(),
                },
                items_processed=len(events),
            )

        except Exception as e:
            self.logger.error(f"[EventScrape] {market_name} failed: {e}", exc_info=True)
            await self._mark_failed(payload.market_id, str(e))
            return JobResult(success=False, error=str(e))

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _last_scraped(self, market_id: str) -> datetime | None:
        try:
            from app.db.session import get_async_session
            from db.models.market_events import MarketRegistryModel
            from sqlalchemy import select
            async with get_async_session() as db:
                row = (await db.execute(
                    select(MarketRegistryModel.last_scraped_at)
                    .where(MarketRegistryModel.market_id == market_id)
                )).scalar_one_or_none()
            return row
        except Exception:
            return None

    async def _scrape_interval(self, market_id: str) -> int:
        try:
            from app.db.session import get_async_session
            from db.models.market_events import MarketRegistryModel
            from sqlalchemy import select
            async with get_async_session() as db:
                row = (await db.execute(
                    select(MarketRegistryModel.scrape_interval_hours)
                    .where(MarketRegistryModel.market_id == market_id)
                )).scalar_one_or_none()
            return row or 24
        except Exception:
            return 24

    async def _mark_failed(self, market_id: str, error: str):
        try:
            from app.db.session import get_async_session
            from db.models.market_events import MarketRegistryModel
            from sqlalchemy import update
            async with get_async_session() as db:
                await db.execute(
                    update(MarketRegistryModel)
                    .where(MarketRegistryModel.market_id == market_id)
                    .values(
                        last_scraped_at    = datetime.now(tz=timezone.utc),
                        last_scrape_status = "failed",
                    )
                )
                await db.commit()
        except Exception:
            pass


@register_worker
class EventScrapeAllWorker(BaseWorker[EventScrapeAllPayload]):
    """
    Daily sweep — scrapes all markets that are due for a refresh.

    Designed to run on a cron: every 6 hours.
    Each market has its own scrape_interval_hours (default 24h).
    """

    name            = "event_scrape_all_worker"
    category        = WorkerCategory.INGESTION
    max_retries     = 1
    timeout_seconds = 1800   # 30 min ceiling for a full multi-market sweep

    async def process(self, payload: EventScrapeAllPayload) -> JobResult:
        from tools.event_scraper import EventScrapeOrchestrator, KNOWN_MARKETS

        due_markets = await self._get_due_markets(payload.force)
        self.logger.info(f"[EventScrapeAll] {len(due_markets)} markets due for scrape")

        results: dict[str, Any] = {}
        total_events = 0

        async with EventScrapeOrchestrator(days_ahead=payload.days_ahead) as orc:
            for market_id in due_markets:
                try:
                    events = await orc.scrape_market(market_id)
                    results[market_id] = {"count": len(events), "status": "ok"}
                    total_events += len(events)
                    self.logger.info(f"[EventScrapeAll] {market_id}: {len(events)} events")
                except Exception as e:
                    results[market_id] = {"count": 0, "status": "error", "error": str(e)}
                    self.logger.warning(f"[EventScrapeAll] {market_id} failed: {e}")

        return JobResult(
            success=True,
            data={
                "markets_scraped": len(due_markets),
                "total_events":    total_events,
                "by_market":       results,
            },
            items_processed=total_events,
        )

    async def _get_due_markets(self, force: bool) -> list[str]:
        """
        Returns market_ids from the registry that are due.
        Falls back to KNOWN_MARKETS if the registry table doesn't exist yet.
        """
        from tools.event_scraper import KNOWN_MARKETS
        try:
            from app.db.session import get_async_session
            from db.models.market_events import MarketRegistryModel
            from sqlalchemy import select
            async with get_async_session() as db:
                rows = (await db.execute(
                    select(MarketRegistryModel).where(
                        MarketRegistryModel.scrape_enabled == True
                    )
                )).scalars().all()

            if not rows:
                return list(KNOWN_MARKETS.keys())

            due = []
            now = datetime.now(tz=timezone.utc)
            for row in rows:
                if force or row.last_scraped_at is None:
                    due.append(row.market_id)
                    continue
                age_h = (now - row.last_scraped_at).total_seconds() / 3600
                if age_h >= row.scrape_interval_hours:
                    due.append(row.market_id)
            return due
        except Exception as e:
            self.logger.warning(f"[EventScrapeAll] Registry query failed, using KNOWN_MARKETS: {e}")
            return list(KNOWN_MARKETS.keys())


@register_worker
class OperatorMarketDetectWorker(BaseWorker[OperatorMarketDetectPayload]):
    """
    Triggered after a new operator's properties are imported into the DB.

    Steps:
      1. Pull property addresses from DB if not supplied in payload
      2. Geocode centroid via Nominatim (free, no key)
      3. Match to nearest known market or create a new one
      4. Register operator with market
      5. Immediately queue EventScrapeMarketJob so the operator's concierge
         has local event data from day one
    """

    name            = "operator_market_detect_worker"
    category        = WorkerCategory.INGESTION
    max_retries     = 3
    timeout_seconds = 120

    async def process(self, payload: OperatorMarketDetectPayload) -> JobResult:
        from tools.event_scraper import resolve_operator_market

        # ── 1. Pull addresses from DB if not provided ─────────────────────────
        addresses = list(payload.property_addresses)
        if not addresses:
            addresses = await self._pull_property_addresses(payload.tenant_id)

        if not addresses:
            self.logger.warning(
                f"[MarketDetect] No addresses found for operator "
                f"{payload.operator_name} ({payload.tenant_id})"
            )
            return JobResult(
                success=False,
                error="No property addresses available for market detection",
            )

        self.logger.info(
            f"[MarketDetect] Resolving market for {payload.operator_name} "
            f"({len(addresses)} addresses)"
        )

        # ── 2. Resolve (or create) the market ─────────────────────────────────
        market = await resolve_operator_market(
            property_addresses=addresses,
            operator_id=str(payload.tenant_id),
            operator_name=payload.operator_name,
        )

        if not market:
            return JobResult(
                success=False,
                error="Could not resolve market from property addresses",
            )

        self.logger.info(
            f"[MarketDetect] {payload.operator_name} → market: "
            f"{market['name']} ({market['id']})"
        )

        # ── 3. Store market_id on the operator record ─────────────────────────
        await self._set_operator_market(payload.tenant_id, market["id"])

        # ── 4. Queue immediate scrape for this market ─────────────────────────
        await self._queue_scrape(market["id"], payload.days_ahead)

        return JobResult(
            success=True,
            data={
                "market_id":   market["id"],
                "market_name": market["name"],
                "lat":         market.get("lat"),
                "lng":         market.get("lng"),
                "scrape_queued": True,
            },
            items_processed=len(addresses),
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _pull_property_addresses(self, tenant_id: UUID) -> list[str]:
        """Query the properties table for full addresses belonging to this operator."""
        try:
            from app.db.session import get_async_session
            from sqlalchemy import select, text
            async with get_async_session() as db:
                # Try the canonical properties table first
                result = await db.execute(
                    text("""
                        SELECT
                            COALESCE(address_line1, '') || ', ' ||
                            COALESCE(city, '')          || ', ' ||
                            COALESCE(state, '')         || ' ' ||
                            COALESCE(postal_code, '')   AS full_address
                        FROM properties
                        WHERE tenant_id = :tenant_id
                          AND address_line1 IS NOT NULL
                        LIMIT 20
                    """),
                    {"tenant_id": str(tenant_id)},
                )
                rows = result.fetchall()
                return [r[0].strip(", ") for r in rows if r[0].strip(", ")]
        except Exception as e:
            self.logger.warning(f"_pull_property_addresses failed: {e}")
            return []

    async def _set_operator_market(self, tenant_id: UUID, market_id: str):
        """Persist the resolved market_id on the operator_policies row."""
        try:
            from app.db.session import get_async_session
            from db.models.operator_policy import OperatorPolicyModel
            from sqlalchemy import update
            async with get_async_session() as db:
                await db.execute(
                    update(OperatorPolicyModel)
                    .where(OperatorPolicyModel.tenant_id == tenant_id)
                    .values(market_id=market_id)
                )
                await db.commit()
        except Exception as e:
            # Non-fatal — market_id column may not exist yet on older schemas
            self.logger.debug(f"_set_operator_market failed (non-fatal): {e}")

    async def _queue_scrape(self, market_id: str, days_ahead: int):
        """Queue an immediate EventScrapeMarketWorker job."""
        try:
            from workers.base import WorkerRegistry
            registry = WorkerRegistry.get()
            worker_cls = registry.get("event_scrape_market_worker")
            if worker_cls:
                # Inline execution — small enough to run in the same process
                worker = worker_cls()
                await worker.process(
                    EventScrapeMarketPayload(
                        tenant_id  = UUID("00000000-0000-0000-0000-000000000000"),
                        market_id  = market_id,
                        days_ahead = days_ahead,
                        force      = True,   # first-time scrape always runs
                    )
                )
            else:
                self.logger.warning(
                    "[MarketDetect] event_scrape_market_worker not in registry — "
                    "scrape will run on next cron cycle"
                )
        except Exception as e:
            self.logger.warning(f"_queue_scrape failed (non-fatal): {e}")
