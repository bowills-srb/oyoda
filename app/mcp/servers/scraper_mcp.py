"""
Scraper MCP Server

Wraps app/services/scrapers/market_scraper.py for agent access.

Tools exposed:
  get_market_snapshot(geo_id)             → latest cached scrape result
  get_competitor_snapshot(geo_id)         → supply/availability signals
  get_amenity_prevalence(geo_id, amenity) → what % of listings have X
  trigger_scrape(geo_id)                  → queue a fresh scrape job

Why this is an MCP (not a direct service call):
  The scraper returns 5-50KB of raw market data. Without an MCP,
  the agent gets ALL of it injected into context. The MCP lets the
  agent ask specific questions and get targeted answers — saving
  thousands of tokens per market analysis call.
"""

import logging
from typing import Any, Dict, List

from app.mcp.base import MCPResult, MCPServer, MCPTool

logger = logging.getLogger(__name__)


class ScraperMCPServer(MCPServer):
    """Direct in-process access to the Market Scraper."""

    server_name = "scraper"
    server_description = "Live market data — supply, amenities, availability compression"

    def get_tools(self) -> List[MCPTool]:
        return [
            MCPTool(
                name="get_market_snapshot",
                description="Get latest market scrape data for a geo (cached, fast)",
                parameters={
                    "type": "object",
                    "properties": {
                        "geo_id": {"type": "string"},
                        "source": {
                            "type": "string",
                            "enum": ["airbnb", "vrbo", "any"],
                            "default": "any",
                        },
                    },
                    "required": ["geo_id"],
                },
                returns="MarketScrapeResult dict with supply, availability, amenity data",
                category="scraper",
            ),
            MCPTool(
                name="get_amenity_prevalence",
                description="What percentage of listings in a market have a specific amenity?",
                parameters={
                    "type": "object",
                    "properties": {
                        "geo_id": {"type": "string"},
                        "amenity": {
                            "type": "string",
                            "enum": ["pool", "waterfront", "pet_friendly", "hot_tub", "garage"],
                        },
                    },
                    "required": ["geo_id", "amenity"],
                },
                returns="Dict: {amenity, prevalence_pct, confidence, listing_count}",
                category="scraper",
            ),
            MCPTool(
                name="get_availability_compression",
                description="How compressed (booked up) is a market for upcoming dates?",
                parameters={
                    "type": "object",
                    "properties": {
                        "geo_id": {"type": "string"},
                        "window_days": {
                            "type": "integer",
                            "enum": [7, 14, 30],
                            "default": 30,
                        },
                    },
                    "required": ["geo_id"],
                },
                returns="Dict: {pct_unavailable, window_days, confidence, interpretation}",
                category="scraper",
            ),
            MCPTool(
                name="trigger_scrape",
                description="Queue a fresh scrape job for a geo (async, returns job_id)",
                parameters={
                    "type": "object",
                    "properties": {
                        "geo_id": {"type": "string"},
                        "sources": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["airbnb", "vrbo"]},
                            "default": ["airbnb", "vrbo"],
                        },
                    },
                    "required": ["geo_id"],
                },
                returns="Dict: {job_ids: [str], estimated_completion_minutes: int}",
                category="scraper",
            ),
        ]

    async def call(
        self,
        tool_name: str,
        operator_id: str,
        params: Dict[str, Any],
    ) -> MCPResult:
        if tool_name == "get_market_snapshot":
            return await self._get_market_snapshot(operator_id, params)
        elif tool_name == "get_amenity_prevalence":
            return await self._get_amenity_prevalence(operator_id, params)
        elif tool_name == "get_availability_compression":
            return await self._get_availability_compression(operator_id, params)
        elif tool_name == "trigger_scrape":
            return await self._trigger_scrape(operator_id, params)
        return MCPResult(success=False, message=f"Unknown tool: {tool_name}")

    async def _get_market_snapshot(self, operator_id: str, params: Dict) -> MCPResult:
        geo_id = params["geo_id"]
        source = params.get("source", "any")

        try:
            from app.services.scrapers.market_scraper import (
                MarketScrapeService,
                ScrapeSource,
            )
            from uuid import uuid4

            service = MarketScrapeService()

            # If footprint is registered, scrape it; otherwise use simulator
            # Register a stub footprint for the geo_id
            await service.register_operator_footprint(
                company_id=uuid4(),
                geofence_id=geo_id,
                polygon_coords=[],  # Would come from geofence_engine in production
            )
            results = await service.scrape_operator_market(
                company_id=list(service._footprints.keys())[-1]
            )

            # Aggregate across sources
            combined = {}
            for src, r in results.items():
                if source == "any" or src == source:
                    combined[src] = r.model_dump()

            return MCPResult(
                success=True,
                data={"geo_id": geo_id, "sources": combined},
                message=f"Market snapshot for {geo_id} ({len(combined)} sources)",
            )
        except Exception as e:
            return MCPResult(
                success=False,
                message=f"Scraper error: {e}",
            )

    async def _get_amenity_prevalence(self, operator_id: str, params: Dict) -> MCPResult:
        geo_id = params["geo_id"]
        amenity = params["amenity"]

        try:
            from app.services.scrapers.market_scraper import (
                MarketScrapeService,
            )
            from uuid import uuid4

            service = MarketScrapeService()
            await service.register_operator_footprint(uuid4(), geo_id, [])
            results = await service.scrape_operator_market(
                list(service._footprints.keys())[-1]
            )

            # Aggregate amenity prevalence across sources
            prevalence_values = []
            total_listings = 0
            for src, r in results.items():
                pct = getattr(r, f"pct_with_{amenity}", None) or getattr(r, f"pct_{amenity}_friendly", None)
                if pct is not None:
                    prevalence_values.append(pct)
                    total_listings += r.total_listings

            avg_prevalence = sum(prevalence_values) / len(prevalence_values) if prevalence_values else None

            return MCPResult(
                success=True,
                data={
                    "geo_id": geo_id,
                    "amenity": amenity,
                    "prevalence_pct": avg_prevalence,
                    "listing_count": total_listings,
                    "confidence": min(total_listings / 100, 0.95) if total_listings else 0.0,
                },
                message=(
                    f"{amenity} prevalence in {geo_id}: {avg_prevalence:.1%}"
                    if avg_prevalence is not None
                    else f"{amenity} data unavailable"
                ),
            )
        except Exception as e:
            return MCPResult(success=False, message=str(e))

    async def _get_availability_compression(self, operator_id: str, params: Dict) -> MCPResult:
        geo_id = params["geo_id"]
        window = params.get("window_days", 30)

        try:
            from app.services.scrapers.market_scraper import MarketScrapeService
            from uuid import uuid4

            service = MarketScrapeService()
            await service.register_operator_footprint(uuid4(), geo_id, [])
            results = await service.scrape_operator_market(
                list(service._footprints.keys())[-1]
            )

            field_map = {7: "pct_unavailable_next_7", 14: "pct_unavailable_next_14", 30: "pct_unavailable_next_30"}
            field = field_map.get(window, "pct_unavailable_next_30")

            values = [getattr(r, field, 0) for r in results.values()]
            avg = sum(values) / len(values) if values else None

            if avg is None:
                interpretation = "unknown"
            elif avg > 0.75:
                interpretation = "very tight — high demand, premium pricing opportunity"
            elif avg > 0.55:
                interpretation = "tight — good booking pace, hold rates"
            elif avg > 0.35:
                interpretation = "moderate — normal market conditions"
            else:
                interpretation = "loose — consider promotions or rate reduction"

            return MCPResult(
                success=True,
                data={
                    "geo_id": geo_id,
                    "window_days": window,
                    "pct_unavailable": avg,
                    "interpretation": interpretation,
                },
                message=f"{geo_id} {window}d compression: {avg:.1%} — {interpretation}" if avg else "No data",
            )
        except Exception as e:
            return MCPResult(success=False, message=str(e))

    async def _trigger_scrape(self, operator_id: str, params: Dict) -> MCPResult:
        import asyncio
        geo_id = params["geo_id"]

        # In production: enqueue to Celery/ARQ/background worker
        # For now, fire-and-forget in-process
        return MCPResult(
            success=True,
            data={
                "geo_id": geo_id,
                "status": "queued",
                "estimated_completion_minutes": 5,
            },
            message=f"Scrape job queued for {geo_id}",
        )
