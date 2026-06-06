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

Concierge BD Insight Service — Booking Velocity Edition.

Philosophy
----------
The only signal we surface to guests is whether market bookings are
*speeding up or slowing down*.  We do NOT expose ADR, forecast bands,
revenue projections, or rate recommendations.  Those signals live
elsewhere in the BD layer and are operator-facing only.

What this service does
----------------------
1. Reads the CalendarDeltaResult (booking compression velocity) for
   the property's market from the signal pipeline.
2. Classifies the velocity into one of three postures:
     ACCELERATING  → bookings are filling up faster than baseline
     STABLE        → pace is normal for this time of year
     DECELERATING  → pace is softer than usual
3. Returns a short, *action-oriented nudge* that the concierge can
   weave naturally into its reply when the guest is asking about
   availability, timing, or activities.

Nudge design rules
------------------
- Never mention prices, rates, ADR, or discount windows.
- Never say "book now or lose out" — that's pressure selling.
- Stick to experience-adjacent actions: secure beach chair rentals,
  make a restaurant reservation, grab equipment rental slots, etc.
- Confidence gate: if velocity confidence < 0.45 emit nothing — the
  data isn't good enough to nudge at all.
- Frequency gate: only inject on relevant query types (see TRIGGER_KEYWORDS).
- Fallback: if the DB query fails or returns no data, return None
  silently — the concierge degrades gracefully.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Query-type gate — only inject when the guest topic warrants it
# ---------------------------------------------------------------------------

TRIGGER_KEYWORDS = (
    "available",
    "availability",
    "busy",
    "crowded",
    "best time",
    "how busy",
    "beach",
    "rental",
    "activity",
    "activities",
    "restaurant",
    "reservation",
    "equipment",
    "kayak",
    "paddleboard",
    "boat",
    "chair",
    "umbrella",
    "excursion",
    "tour",
    "when should",
    "should i book",
    "getting full",
    "last minute",
    "wait",
    "popular",
    "season",
    "peak",
)

# ---------------------------------------------------------------------------
# Nudge copy banks — by velocity posture
# These are deliberately vague on timing and never mention prices.
# The concierge can quote them verbatim or rephrase naturally.
# ---------------------------------------------------------------------------

# Things are filling up faster than normal
_ACCELERATING_NUDGES = [
    "Things are moving quickly around here — if you're thinking about beach chair or umbrella rentals, it's worth locking those in soon so you're not scrambling.",
    "The area tends to fill up fast this time of year. I'd suggest making any restaurant reservations or equipment rental bookings sooner rather than later.",
    "A heads-up: activity and rental slots in the area have been booking up quickly lately. Worth securing anything on your list early in the trip.",
    "Beach excursions and watersport rentals tend to go fast when things get busy. If any of those are on your radar, earlier is better.",
    "Just a soft heads-up — guided tours and equipment rentals in the area have been booking out. If that's on your list, I'd grab a spot while you can.",
]

# Pace is normal — gentle, low-pressure observation
_STABLE_NUDGES = [
    "Things are at a pretty typical pace right now — you should have good availability for rentals and activities, though popular spots can still book up on short notice.",
    "No unusual rush at the moment, but for beach equipment rentals or popular restaurants, booking a day or two ahead is always a safe move.",
    "It's a pretty steady season right now. Most rentals and activity slots are available, though weekends tend to fill faster.",
]

# Softer than usual — no pressure, just reassurance
_DECELERATING_NUDGES = [
    "Things are a bit more relaxed than usual around here, so you should have plenty of flexibility with rentals and activity bookings.",
    "It's a quieter stretch right now — good news if you like a bit more breathing room when booking beach rentals or making dinner reservations.",
]

# Minimum confidence to emit any nudge at all
_CONFIDENCE_GATE = 0.45


# ---------------------------------------------------------------------------
# Velocity reader — pulls CalendarDeltaResult from the signals layer
# ---------------------------------------------------------------------------

def _read_velocity(geo_id: str) -> Optional[Any]:
    """
    Pull the most recent CalendarDeltaResult for this geo_id.

    Returns CalendarDeltaResult or None if unavailable.
    Uses a fast in-process cache via signal_pipeline if available;
    falls back to a direct CalendarDeltaEngine call over stored observations.
    """
    try:
        from app.services.signals.signal_pipeline import get_signal_pipeline
        pipeline = get_signal_pipeline()
        # Signal pipeline exposes latest calendar delta per geo as a cached result
        if hasattr(pipeline, "get_calendar_delta"):
            return pipeline.get_calendar_delta(geo_id)
    except Exception as e:
        logger.debug("signal_pipeline calendar delta unavailable: %s", e)

    # Direct fallback — load stored CalendarObservations from DB and compute
    try:
        from app.services.signals.market_dynamics import CalendarDeltaEngine, CalendarObservation
        from app.db.models.signals import CalendarObservationModel
        from app.core.database import get_sync_db

        db = get_sync_db()
        rows = (
            db.query(CalendarObservationModel)
            .filter(CalendarObservationModel.geo_id == geo_id)
            .order_by(CalendarObservationModel.observed_at.desc())
            .limit(30)
            .all()
        )
        if len(rows) < 2:
            return None

        observations = [
            CalendarObservation(
                observed_at=r.observed_at,
                blocked_pct_7d=r.blocked_pct_7d or 0.0,
                blocked_pct_30d=r.blocked_pct_30d or 0.0,
                blocked_pct_60d=r.blocked_pct_60d,
                total_listings=r.total_listings or 0,
            )
            for r in reversed(rows)  # oldest first for the engine
        ]
        engine = CalendarDeltaEngine()
        return engine.calculate_compression_delta(observations, geo_id)
    except Exception as e:
        logger.debug("CalendarDeltaEngine direct fallback failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Geo resolver — same logic used by booking scraper & event workers
# ---------------------------------------------------------------------------

def _resolve_geo_id(property_context: Optional[Dict[str, Any]]) -> str:
    ctx = property_context or {}
    community = str(ctx.get("community") or ctx.get("city") or "").strip().lower()
    state = str(ctx.get("state") or "").strip().lower()
    if community:
        slug = community.replace(" ", "-")
        if "fl" in state or "florida" in state:
            return f"fl-30a-{slug}"
        return f"market-{slug}"
    return "fl-30a"


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

class ConciergeBDInsightService:
    """
    Emit a soft velocity-based nudge when market bookings are accelerating
    or decelerating.  Returns None when confidence is insufficient or the
    query type doesn't warrant an injection.
    """

    def should_generate(self, message_text: str) -> bool:
        text = (message_text or "").lower()
        return any(k in text for k in TRIGGER_KEYWORDS)

    def generate_summary(
        self,
        tenant_id: UUID,
        message_text: str,
        property_external_id: Optional[str],
        property_context: Optional[Dict[str, Any]] = None,
        sections: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        if not self.should_generate(message_text):
            return None

        geo_id = _resolve_geo_id(property_context)
        delta = _read_velocity(geo_id)

        if delta is None:
            logger.debug("[bd_insight] no velocity data for geo=%s", geo_id)
            return None

        confidence = getattr(delta, "confidence", 0.0)
        if confidence < _CONFIDENCE_GATE:
            logger.debug(
                "[bd_insight] confidence %.2f below gate %.2f for geo=%s",
                confidence, _CONFIDENCE_GATE, geo_id,
            )
            return None

        direction = getattr(delta, "direction", None)
        direction_val = direction.value if hasattr(direction, "value") else str(direction or "stable")

        if direction_val == "accelerating":
            nudge = random.choice(_ACCELERATING_NUDGES)
        elif direction_val == "decelerating":
            nudge = random.choice(_DECELERATING_NUDGES)
        else:
            # Stable — inject only occasionally (30% of eligible messages)
            # so it doesn't feel repetitive on a quiet week
            if random.random() > 0.30:
                return None
            nudge = random.choice(_STABLE_NUDGES)

        logger.debug(
            "[bd_insight] emitting nudge direction=%s confidence=%.2f geo=%s",
            direction_val, confidence, geo_id,
        )
        return nudge


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_service: ConciergeBDInsightService | None = None


def get_concierge_bd_insight_service() -> ConciergeBDInsightService:
    global _service
    if _service is None:
        _service = ConciergeBDInsightService()
    return _service
