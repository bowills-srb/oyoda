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

Stay-aware event planning for concierge and operator workflows.

This service turns raw market events into:
- guest trip-planning guidance for booked or in-stay guests
- operator-facing demand summaries for 0-7 / 7-30 / 30-90 day windows
- action suggestions such as dining reservations or ticket purchases
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


EVENT_QUERY_KEYWORDS = {
    "event", "events", "festival", "fest", "concert", "music", "show", "shows",
    "happening", "weekend", "during", "while", "town", "going", "tickets",
    "parking", "traffic", "restaurant", "restaurants", "book", "booking",
}


def is_event_planning_question(message_text: str) -> bool:
    words = {part.lower() for part in (message_text or "").replace("?", " ").split()}
    return any(word in words for word in EVENT_QUERY_KEYWORDS)


def _daterange_length(start_date: date, end_date: date) -> int:
    return max(1, (end_date - start_date).days + 1)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _days_until(event_start: date, anchor: date) -> int:
    return (event_start - anchor).days


def _impact_label(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _format_date_window(start_date: date, end_date: date) -> str:
    if start_date == end_date:
        return start_date.strftime("%b %d")
    return f"{start_date.strftime('%b %d')} to {end_date.strftime('%b %d')}"


def _event_priority(event: Dict[str, Any], arrival_date: date) -> float:
    demand = _safe_float(event.get("demand_impact_score"))
    guest = _safe_float(event.get("guest_relevance_score"))
    urgency = _safe_float(event.get("booking_urgency_score"))
    confidence = _safe_float(event.get("event_confidence_score"), 0.5)
    days_out = abs(_days_until(event["start_date"], arrival_date))
    recency_bonus = max(0.0, 0.25 - min(days_out, 21) / 100.0)
    return round(
        0.35 * demand + 0.30 * guest + 0.20 * urgency + 0.15 * confidence + recency_bonus,
        4,
    )


def _bucket_window(days_out: int) -> str:
    if days_out <= 7:
        return "0_7"
    if days_out <= 30:
        return "7_30"
    return "30_90"


def _generate_trip_notes(
    events: List[Dict[str, Any]],
    has_children: bool,
) -> List[str]:
    notes: List[str] = []
    high_demand = [event for event in events if _safe_float(event.get("demand_impact_score")) >= 0.65]
    ticketed = [event for event in events if event.get("ticket_url") and _safe_float(event.get("booking_urgency_score")) >= 0.45]
    family = [
        event for event in events
        if event.get("category") == "family" or "family" in (event.get("tags") or [])
    ]

    if high_demand:
        notes.append("Expect heavier parking, traffic, and restaurant pressure during your stay window.")
    if ticketed:
        notes.append("A few events look worth booking ahead of time so you do not lose ticket availability.")
    if has_children and family:
        notes.append("There are family-friendly options during your stay, so we can steer you toward easier kid-friendly plans.")
    if not notes and events:
        notes.append("There are a few local happenings during your stay, but nothing that looks likely to create major crowd pressure.")
    return notes


def _build_guest_summary(
    events: List[Dict[str, Any]],
    check_in_date: date,
    check_out_date: date,
) -> str:
    if not events:
        return (
            f"I do not see any major demand-driving events during your "
            f"{_format_date_window(check_in_date, check_out_date)} stay, so planning should stay pretty flexible."
        )

    top = events[:3]
    titles = ", ".join(event["title"] for event in top[:2])
    if len(top) > 2:
        titles += f", and {top[2]['title']}"

    demand_driver_count = sum(1 for event in events if event.get("event_class") in {"demand_driver", "seasonal_anchor"})
    if demand_driver_count:
        return (
            f"During your {_format_date_window(check_in_date, check_out_date)} stay, "
            f"I’m seeing {titles}. At least one of these looks likely to push traffic, parking, and dining demand, "
            "so planning a little ahead would help."
        )

    return (
        f"During your {_format_date_window(check_in_date, check_out_date)} stay, "
        f"I’m seeing {titles}. These look more useful for trip planning than for crowd pressure, "
        "so we can keep things flexible unless you want reservations."
    )


class EventPlanningService:
    """Converts market events into trip-planning and operator-intel responses."""

    async def resolve_market_id(
        self,
        session: AsyncSession,
        market_id: Optional[str] = None,
        property_id: Optional[UUID] = None,
    ) -> Optional[str]:
        if market_id:
            return market_id
        if not property_id:
            return None

        property_row = (
            await session.execute(
                text(
                    """
                    SELECT latitude, longitude
                    FROM properties
                    WHERE property_id = :property_id
                    LIMIT 1
                    """
                ),
                {"property_id": property_id},
            )
        ).mappings().first()
        if not property_row:
            return None

        markets = (
            await session.execute(
                text(
                    """
                    SELECT market_id, center_lat, center_lng
                    FROM market_registry
                    WHERE scrape_enabled = true
                    """
                )
            )
        ).mappings().all()
        if not markets:
            return None

        prop_lat = _safe_float(property_row["latitude"])
        prop_lng = _safe_float(property_row["longitude"])
        best_market_id = None
        best_distance = float("inf")
        for market in markets:
            distance = math.sqrt(
                (prop_lat - _safe_float(market["center_lat"])) ** 2 +
                (prop_lng - _safe_float(market["center_lng"])) ** 2
            )
            if distance < best_distance:
                best_distance = distance
                best_market_id = market["market_id"]
        return best_market_id

    async def fetch_market_events(
        self,
        session: AsyncSession,
        market_id: str,
        start_date: date,
        end_date: date,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT
                        event_id,
                        title,
                        description,
                        category,
                        tags,
                        start_date,
                        end_date,
                        venue_name,
                        venue_address,
                        estimated_attendance,
                        demand_impact_score,
                        guest_relevance_score,
                        booking_urgency_score,
                        event_confidence_score,
                        event_class,
                        actionability,
                        ticket_url,
                        ticket_price_range,
                        is_free,
                        source,
                        source_type,
                        source_count
                    FROM market_events
                    WHERE market_id = :market_id
                      AND is_active = true
                      AND start_date <= :end_date
                      AND end_date >= :start_date
                      AND (
                        stale_after IS NULL
                        OR stale_after >= NOW()
                      )
                    ORDER BY
                        COALESCE(booking_urgency_score, 0) DESC,
                        COALESCE(guest_relevance_score, 0) DESC,
                        COALESCE(demand_impact_score, 0) DESC,
                        start_date ASC
                    LIMIT :limit
                    """
                ),
                {
                    "market_id": market_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    "limit": limit,
                },
            )
        ).mappings().all()
        return [dict(row) for row in rows]

    async def build_trip_plan(
        self,
        session: AsyncSession,
        *,
        check_in_date: date,
        check_out_date: date,
        market_id: Optional[str] = None,
        property_id: Optional[UUID] = None,
        party_size: int = 2,
        has_children: bool = False,
        question_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_market_id = await self.resolve_market_id(
            session=session,
            market_id=market_id,
            property_id=property_id,
        )
        if not resolved_market_id:
            return {
                "market_id": None,
                "summary": "I could not resolve the market for this stay yet, so I cannot safely plan around local events.",
                "events": [],
                "notes": [],
                "action_items": [],
            }

        events = await self.fetch_market_events(
            session=session,
            market_id=resolved_market_id,
            start_date=check_in_date,
            end_date=check_out_date,
            limit=25,
        )

        prioritized = sorted(
            events,
            key=lambda event: _event_priority(event, check_in_date),
            reverse=True,
        )

        notes = _generate_trip_notes(prioritized, has_children=has_children)
        summary = _build_guest_summary(prioritized, check_in_date, check_out_date)
        action_items: List[Dict[str, Any]] = []

        for event in prioritized[:5]:
            urgency = _safe_float(event.get("booking_urgency_score"))
            if event.get("ticket_url") and urgency >= 0.45:
                action_items.append(
                    {
                        "type": "ticket",
                        "title": f"Buy tickets for {event['title']}",
                        "reason": "This event looks like something to lock in ahead of arrival.",
                        "url": event["ticket_url"],
                        "urgency": _impact_label(urgency),
                    }
                )

        if prioritized:
            from app.services.concierge.dining_service import get_dining_service

            dining_options = await get_dining_service().search_restaurants(
                operator_id=resolved_market_id,
                query="dinner",
                date=check_in_date.isoformat(),
                party_size=party_size,
                area=None,
            )
            for option in dining_options[:3]:
                action_items.append(
                    {
                        "type": "restaurant",
                        "title": f"Reserve {option['name']}",
                        "reason": "Dining demand may tighten around local events during this stay window.",
                        "url": option.get("booking_url"),
                        "phone": option.get("phone"),
                        "urgency": "medium",
                    }
                )

        event_cards = []
        for event in prioritized[:8]:
            event_cards.append(
                {
                    "event_id": str(event["event_id"]),
                    "title": event["title"],
                    "date_window": _format_date_window(event["start_date"], event["end_date"]),
                    "category": event.get("category") or "other",
                    "venue_name": event.get("venue_name"),
                    "description": (event.get("description") or "")[:220],
                    "demand_impact_score": round(_safe_float(event.get("demand_impact_score")), 2),
                    "guest_relevance_score": round(_safe_float(event.get("guest_relevance_score")), 2),
                    "booking_urgency_score": round(_safe_float(event.get("booking_urgency_score")), 2),
                    "event_confidence_score": round(_safe_float(event.get("event_confidence_score"), 0.5), 2),
                    "event_class": event.get("event_class"),
                    "actionability": event.get("actionability"),
                    "ticket_url": event.get("ticket_url"),
                    "ticket_price_range": event.get("ticket_price_range"),
                    "source_count": int(event.get("source_count") or 1),
                }
            )

        if question_text and "restaurant" in (question_text or "").lower() and not action_items:
            from app.services.concierge.dining_service import get_dining_service

            dining_options = await get_dining_service().search_restaurants(
                operator_id=resolved_market_id,
                query="restaurant",
                date=check_in_date.isoformat(),
                party_size=party_size,
                area=None,
            )
            for option in dining_options[:3]:
                action_items.append(
                    {
                        "type": "restaurant",
                        "title": f"Reserve {option['name']}",
                        "reason": "This is a solid nearby dining option for that stay window.",
                        "url": option.get("booking_url"),
                        "phone": option.get("phone"),
                        "urgency": "medium",
                    }
                )

        return {
            "market_id": resolved_market_id,
            "summary": summary,
            "events": event_cards,
            "notes": notes,
            "action_items": action_items[:6],
        }

    async def build_operator_event_intel(
        self,
        session: AsyncSession,
        *,
        market_id: str,
        as_of: Optional[date] = None,
        days_ahead: int = 90,
    ) -> Dict[str, Any]:
        anchor = as_of or date.today()
        window_end = anchor + timedelta(days=days_ahead)
        events = await self.fetch_market_events(
            session=session,
            market_id=market_id,
            start_date=anchor,
            end_date=window_end,
            limit=100,
        )

        buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for event in events:
            bucket = _bucket_window(max(0, _days_until(event["start_date"], anchor)))
            buckets[bucket].append(event)

        windows = []
        for bucket_key, label in (
            ("0_7", "0-7 days"),
            ("7_30", "7-30 days"),
            ("30_90", "30-90 days"),
        ):
            bucket_events = sorted(
                buckets.get(bucket_key, []),
                key=lambda event: (
                    _safe_float(event.get("demand_impact_score")),
                    _safe_float(event.get("event_confidence_score"), 0.5),
                ),
                reverse=True,
            )
            avg_impact = (
                sum(_safe_float(event.get("demand_impact_score")) for event in bucket_events) / len(bucket_events)
                if bucket_events else 0.0
            )
            titles = [event["title"] for event in bucket_events[:3]]
            recommendations: List[str] = []
            if bucket_key == "0_7" and bucket_events:
                recommendations.append("Review parking, traffic, and beach-access answers before the weekend.")
            if bucket_key == "7_30" and avg_impact >= 0.45:
                recommendations.append("Expect elevated inquiry volume and tighter check-in logistics.")
            if bucket_key == "30_90" and avg_impact >= 0.45:
                recommendations.append("Use this window to pressure-test rates, pacing, and staffing assumptions.")
            windows.append(
                {
                    "window": label,
                    "event_count": len(bucket_events),
                    "avg_demand_impact": round(avg_impact, 2),
                    "demand_level": _impact_label(avg_impact),
                    "top_events": titles,
                    "recommendations": recommendations,
                }
            )

        return {
            "market_id": market_id,
            "as_of": anchor.isoformat(),
            "days_ahead": days_ahead,
            "windows": windows,
        }


_event_planning_service: Optional[EventPlanningService] = None


def get_event_planning_service() -> EventPlanningService:
    global _event_planning_service
    if _event_planning_service is None:
        _event_planning_service = EventPlanningService()
    return _event_planning_service
