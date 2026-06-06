"""
Concierge Database Service

Connects the guest concierge to the actual database for:
- Property amenities lookup
- Booking availability checks (for extend stay offers)
- Session persistence
- Journey tracking persistence
"""

from datetime import date, datetime, timedelta
from typing import Optional, Dict, Any, List
from uuid import UUID
import logging

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def get_property_amenities(
    db: AsyncSession,
    property_id: UUID,
) -> Dict[str, Any]:
    """
    Get property amenities for concierge context.
    Returns structured data for quick answers.
    """
    from db.models.core import PropertyModel
    
    result = await db.execute(
        select(PropertyModel).where(PropertyModel.property_id == property_id)
    )
    prop = result.scalar_one_or_none()
    
    if not prop:
        return {}
    
    return {
        "property_id": str(prop.property_id),
        "name": prop.name,
        "bedrooms": prop.bedrooms,
        "bathrooms": float(prop.bathrooms),
        "sleeps": prop.sleeps,
        
        # Pool
        "has_pool": prop.has_pool,
        "pool_heated": prop.pool_heated,
        "pool_heat_cost": "$50/day" if prop.pool_heated else None,
        
        # Beach
        "beach_access": prop.beach_access,
        "has_waterfront": prop.has_waterfront,
        "waterfront_type": prop.waterfront_type,
        
        # Other amenities
        "has_hot_tub": prop.has_hot_tub,
        "pet_friendly": prop.pet_friendly,
        "has_garage": prop.has_garage,
        "has_ev_charger": prop.has_ev_charger,
        "has_game_room": prop.has_game_room,
        "has_home_theater": prop.has_home_theater,
        
        # Additional amenities list
        "amenities": prop.amenities or [],
    }


async def check_next_booking(
    db: AsyncSession,
    property_id: UUID,
    current_checkout: date,
) -> Dict[str, Any]:
    """
    Check if there's a booking starting on the checkout date.
    Used to determine if extend stay offer is available.
    
    Returns:
        {
            "has_next_booking": bool,
            "next_booking_date": date or None,
            "gap_nights": int (0 if next guest same day)
        }
    """
    from db.models.core import BookingModel
    
    # Look for bookings starting on or after checkout date
    result = await db.execute(
        select(BookingModel)
        .where(
            and_(
                BookingModel.property_id == property_id,
                BookingModel.start_date >= current_checkout,
                BookingModel.status.in_(["confirmed", "pending"]),
            )
        )
        .order_by(BookingModel.start_date)
        .limit(1)
    )
    next_booking = result.scalar_one_or_none()
    
    if not next_booking:
        return {
            "has_next_booking": False,
            "next_booking_date": None,
            "gap_nights": 999,  # No next booking
            "extend_offer_available": True,
        }
    
    gap_nights = (next_booking.start_date - current_checkout).days
    
    return {
        "has_next_booking": True,
        "next_booking_date": next_booking.start_date.isoformat(),
        "gap_nights": gap_nights,
        "extend_offer_available": gap_nights > 0,  # Can extend if at least 1 night gap
    }


async def get_property_for_concierge(
    db: AsyncSession,
    property_code: str,
) -> Optional[Dict[str, Any]]:
    """
    Get property details by internal code for concierge session creation.
    """
    from db.models.core import PropertyModel
    
    # Try by property code first, then by name
    result = await db.execute(
        select(PropertyModel).where(
            or_(
                PropertyModel.name.ilike(f"%{property_code}%"),
                # Add other lookup methods as needed
            )
        ).limit(1)
    )
    prop = result.scalar_one_or_none()
    
    if not prop:
        return None
    
    return {
        "property_id": str(prop.property_id),
        "name": prop.name,
        "address": f"{prop.address_line1}, {prop.city}, {prop.state}",
        "bedrooms": prop.bedrooms,
        "bathrooms": float(prop.bathrooms),
        "sleeps": prop.sleeps,
        "amenities": await get_property_amenities(db, prop.property_id),
    }


async def get_market_demand(
    db: AsyncSession,
    check_in: date,
    check_out: date,
    property_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Demand-signal stub — returns honest-unknown until real inputs are wired.

    A safe stub CONFESSES it doesn't know; it never emits a confident wrong
    number.  The previous implementation returned a month-of-year heuristic
    with a concrete suggested_discount_pct (0/10/20).  That fake confidence
    was removed because a specific number grounded in nothing looks
    authoritative and is dangerous at the pricing layer.

    Real demand is a function of THREE inputs, none of which are wired yet:

    1. PORTFOLIO OCCUPANCY at the requested dates — query pms_bookings across
       the operator's properties for the date window.  High occupancy (e.g.
       all-but-one booked around July 4) → demand high → no discount (someone
       takes the last unit at rack rate).  Zero occupancy → discount may fill
       the calendar.

    2. EVENT SIGNAL — scraped events tied to the date window (festival/race
       weekend).  Low current bookings BUT a big event approaching → do NOT
       discount.  This is what the MarketSnapshotModel hook below is meant to
       fold in.

    3. LEAD-TIME HARD GATE — beyond a horizon (business decision; a few months
       is realistic), return decision="decline_to_decide" regardless of
       occupancy, because pricing drifts and a discount committed that far out
       is meaningless.  Too-far-out → hold for human, never auto-quote.

    Decision shape when real:
        portfolio_occupancy(dates) + event_signal(dates),
        bounded by lead_time_gate → demand_level + confidence.
    Feeds DiscountEngineV2 as a signal; the engine computes
    approve/counter/deny; the COMPOSER renders the reply.  Never
    auto-approve a discount on unknown/stale demand or beyond the
    lead-time bound.

    Wiring gate: do not change decision away from "defer_to_human" until
    BOTH pms_bookings data AND the event/MarketSnapshotModel ingestion are
    confirmed populated and fresh for the tenant.
    """
    from db.models.core import BookingModel, MarketSnapshotModel  # noqa: F401 — hooks for real impl

    return {
        "demand_level": "unknown",
        "confidence": 0.0,
        "suggested_discount_pct": None,
        "decision": "defer_to_human",
        "check_in": check_in.isoformat(),
        "check_out": check_out.isoformat(),
    }


# =============================================================================
# Session Persistence — REMOVED 2026-05-23
# =============================================================================
#
# The in-memory ConciergeSessionStore / get_session_store() pair was superseded
# by app/services/concierge/db_session_service.py and had no production
# callers. Removed as part of Phase 0 of the Brain-Only Unified Migration Plan.
# The remaining utility functions above (get_property_amenities, check_next_booking,
# get_property_for_concierge, get_market_demand) retire with Phase 6 / Phase 7.
