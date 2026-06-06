"""
PRESERVATION STATUS (post-Phase-1, 2026-05-23):
This module is preserved for future product surface (pre-arrival,
in-stay, multi-guest, returning-guest personalization, BD-aware
messaging, etc.). It is not currently part of the active brain
runtime path. Do not delete in subsequent phases unless explicitly
retired by product decision.

When the relevant product surface is wired into the brain, this
module relocates to the appropriate messaging_brain/ subdirectory
and stops being marked as preserved.

Unified market-brain service for concierge runtime context.

This service is the canonical bridge between:
  property identity -> coordinates -> market resolution -> guest-safe market context

The concierge engine should not hardcode market knowledge. It should ask this
service for a reusable market bundle and reason over that bundle.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.concierge.market_source_adapters import (
    MarketSourceContext,
    assemble_market_source_payload,
)
from app.services.knowledge.market_inference import infer_market_from_properties
from app.services.knowledge.places_pipeline import MARKET_REGISTRY

logger = logging.getLogger(__name__)


@dataclass
class MarketBrainBundle:
    property_code: Optional[str] = None
    property_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    market_id: Optional[str] = None
    market_name: Optional[str] = None
    market_type: Optional[str] = None
    neighborhood: Optional[str] = None
    confidence: float = 0.0
    resolution_source: str = "unresolved"
    local_topics: List[str] = field(default_factory=list)
    active_alerts: List[str] = field(default_factory=list)
    upcoming_events: List[str] = field(default_factory=list)
    live_conditions: List[str] = field(default_factory=list)
    featured_places: List[str] = field(default_factory=list)
    weather_summary: Optional[str] = None
    weather_source: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


async def _table_columns(session: AsyncSession, table_name: str) -> set[str]:
    rows = (
        await session.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = :table_name
                """
            ),
            {"table_name": table_name},
        )
    ).fetchall()
    return {str(row[0]) for row in rows}


def _pick_first(row: Dict[str, Any], keys: Sequence[str]) -> Optional[Any]:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


async def _load_property_snapshot(
    session: AsyncSession,
    property_code: Optional[str],
    property_name: Optional[str],
) -> Dict[str, Any]:
    if not property_code and not property_name:
        return {}

    columns = await _table_columns(session, "properties")
    if not columns:
        return {}

    selectable = [col for col in [
        "property_code",
        "external_id",
        "internal_code",
        "name",
        "address_line1",
        "address_street",
        "city",
        "state",
        "community",
        "latitude",
        "longitude",
        "deleted_at",
        "is_deleted",
        "is_active",
    ] if col in columns]
    if not selectable:
        return {}

    where_clauses: List[str] = []
    params: Dict[str, Any] = {}
    if property_code:
        for col in ("property_code", "external_id", "internal_code"):
            if col in columns:
                where_clauses.append(f"{col} = :property_code")
        params["property_code"] = property_code
    if property_name and "name" in columns:
        where_clauses.append("name = :property_name")
        params["property_name"] = property_name
    if not where_clauses:
        return {}

    active_filters: List[str] = []
    if "deleted_at" in columns:
        active_filters.append("deleted_at IS NULL")
    if "is_deleted" in columns:
        active_filters.append("COALESCE(is_deleted, false) = false")
    if "is_active" in columns:
        active_filters.append("COALESCE(is_active, true) = true")

    query = f"""
        SELECT {", ".join(selectable)}
        FROM properties
        WHERE ({' OR '.join(where_clauses)})
        {'AND ' + ' AND '.join(active_filters) if active_filters else ''}
        LIMIT 1
    """
    row = (await session.execute(text(query), params)).mappings().first()
    return dict(row) if row else {}


async def _load_market_registry_row(
    session: AsyncSession,
    market_id: str,
) -> Dict[str, Any]:
    columns = await _table_columns(session, "market_registry")
    if not columns or "market_id" not in columns:
        return {}

    selectable = [col for col in [
        "market_id",
        "market_name",
        "market_type",
        "state_code",
        "center_lat",
        "center_lng",
        "timezone",
        "radius_miles",
        "sources_config",
        "scrape_enabled",
    ] if col in columns]
    row = (
        await session.execute(
            text(
                f"""
                SELECT {", ".join(selectable)}
                FROM market_registry
                WHERE market_id = :market_id
                LIMIT 1
                """
            ),
            {"market_id": market_id},
        )
    ).mappings().first()
    return dict(row) if row else {}


def _registry_topics(market_id: Optional[str], neighborhood_name: Optional[str]) -> List[str]:
    market = MARKET_REGISTRY.get(market_id or "")
    if not market:
        return []

    tags: List[str] = []
    if neighborhood_name:
        for hood in market.neighborhoods:
            if hood.name == neighborhood_name or hood.slug == neighborhood_name:
                tags.extend(hood.tags)
                break

    if not tags:
        for hood in market.neighborhoods[:3]:
            tags.extend(hood.tags[:2])

    deduped: List[str] = []
    for tag in tags:
        if tag and tag not in deduped:
            deduped.append(tag)
    return deduped[:6]


def _extract_sources_config(registry_row: Dict[str, Any]) -> Dict[str, Any]:
    raw = registry_row.get("sources_config")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


async def build_market_brain_bundle(
    session: AsyncSession,
    *,
    property_code: Optional[str] = None,
    property_name: Optional[str] = None,
    property_facts: Optional[Dict[str, Any]] = None,
    session_data: Optional[Dict[str, Any]] = None,
) -> MarketBrainBundle:
    """
    Resolve a reusable market bundle for concierge runtime.

    This is best-effort. If we cannot resolve the market, return a sparse bundle
    rather than raising and interrupting concierge handling.
    """
    property_facts = property_facts or {}
    session_data = session_data or {}

    bundle = MarketBrainBundle(
        property_code=property_code,
        property_name=property_name,
    )

    snapshot = await _load_property_snapshot(session, property_code, property_name)
    if snapshot:
        bundle.property_name = str(
            _pick_first(snapshot, ("name",)) or bundle.property_name or ""
        ) or None
        bundle.latitude = _safe_float(_pick_first(snapshot, ("latitude",)))
        bundle.longitude = _safe_float(_pick_first(snapshot, ("longitude",)))
        bundle.metadata["property_snapshot"] = {
            "city": _pick_first(snapshot, ("city", "community")),
            "state": _pick_first(snapshot, ("state",)),
            "address": _pick_first(snapshot, ("address_line1", "address_street")),
        }

    if bundle.latitude is None:
        bundle.latitude = _safe_float(property_facts.get("latitude"))
    if bundle.longitude is None:
        bundle.longitude = _safe_float(property_facts.get("longitude"))
    if bundle.latitude is None:
        bundle.latitude = _safe_float(session_data.get("latitude"))
    if bundle.longitude is None:
        bundle.longitude = _safe_float(session_data.get("longitude"))

    coords: List[Tuple[float, float]] = []
    if bundle.latitude is not None and bundle.longitude is not None:
        coords.append((bundle.latitude, bundle.longitude))

    if not coords:
        bundle.metadata["resolution_error"] = "property_coordinates_missing"
        return bundle

    inferred = await infer_market_from_properties(coords)
    bundle.market_id = inferred.market_id if inferred.market_id != "MARKET_UNKNOWN" else None
    bundle.market_name = inferred.market_name if inferred.market_id != "MARKET_UNKNOWN" else None
    bundle.market_type = inferred.market_type if inferred.market_id != "MARKET_UNKNOWN" else None
    bundle.neighborhood = inferred.neighborhood
    bundle.confidence = inferred.confidence
    bundle.resolution_source = inferred.inferred_from
    bundle.metadata["inference"] = {
        "confidence": inferred.confidence,
        "centroid_lat": inferred.centroid_lat,
        "centroid_lng": inferred.centroid_lng,
        "property_count": inferred.property_count,
    }

    if not bundle.market_id:
        return bundle

    registry_row = await _load_market_registry_row(session, bundle.market_id)
    sources_config: Dict[str, Any] = {}
    if registry_row:
        bundle.market_name = str(registry_row.get("market_name") or bundle.market_name or "")
        bundle.market_type = str(registry_row.get("market_type") or bundle.market_type or "")
        bundle.metadata["registry"] = registry_row
        sources_config = _extract_sources_config(registry_row)
        if sources_config:
            bundle.metadata["sources_config"] = sources_config

    bundle.local_topics = _registry_topics(bundle.market_id, bundle.neighborhood)
    source_payload = await assemble_market_source_payload(
        session,
        MarketSourceContext(
            market_id=bundle.market_id,
            market_name=bundle.market_name,
            market_type=bundle.market_type,
            latitude=bundle.latitude,
            longitude=bundle.longitude,
            sources_config=sources_config,
        ),
    )
    bundle.upcoming_events = source_payload.upcoming_events
    bundle.live_conditions = source_payload.live_conditions
    bundle.active_alerts = source_payload.active_alerts
    bundle.featured_places = source_payload.featured_places
    bundle.weather_summary = source_payload.weather_summary
    bundle.weather_source = source_payload.weather_source
    if source_payload.source_attribution:
        bundle.metadata["source_attribution"] = source_payload.source_attribution

    return bundle


def format_market_brain_context(bundle: Optional[MarketBrainBundle]) -> str:
    """Convert a market bundle into a compact prompt-safe context block."""
    if not bundle or not bundle.market_id:
        return ""

    lines = ["MARKET CONTEXT:"]
    market_label = bundle.market_name or bundle.market_id
    summary = f"- Market: {market_label}"
    if bundle.neighborhood:
        summary += f" | Neighborhood: {bundle.neighborhood}"
    if bundle.market_type:
        summary += f" | Type: {bundle.market_type}"
    lines.append(summary)

    if bundle.local_topics:
        lines.append(f"- Relevant local topics: {', '.join(bundle.local_topics[:6])}")
    if bundle.live_conditions:
        lines.append(f"- Live local conditions: {' | '.join(bundle.live_conditions[:3])}")
    if bundle.active_alerts:
        lines.append(f"- Active alerts: {' | '.join(bundle.active_alerts[:3])}")
    if bundle.featured_places:
        lines.append(f"- Featured nearby places: {' | '.join(bundle.featured_places[:3])}")
    if bundle.upcoming_events:
        lines.append("- Upcoming local context:")
        for event in bundle.upcoming_events[:3]:
            lines.append(f"  • {event}")

    lines.append(
        "- Use this only for local/market guidance. Never invent property-specific rules, fees, or access details."
    )
    return "\n".join(lines)
