"""
Market Intelligence API Endpoints

Provides access to:
- External market data (excluding operator properties)
- Event calendars and demand signals
- Booking velocity and dynamic pricing recommendations
- Market-wide amenity attribution

These endpoints serve BD, pricing engine, and voice concierge.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
from datetime import date, datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

from app.core.db_connect import resolve_runtime_sync_database_url


router = APIRouter(prefix="/market-intel", tags=["Market Intelligence"])


DATABASE_URL = resolve_runtime_sync_database_url()


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


# =============================================================================
# MARKET DATA ENDPOINTS
# =============================================================================

@router.get(
    "/markets",
    summary="List Available Markets",
    description="Get list of markets with scraped data."
)
async def list_markets():
    """List all markets with data."""
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT 
            m.*,
            (SELECT COUNT(*) FROM external_listings WHERE market_id = m.market_id AND is_active = true) as listing_count,
            (SELECT COUNT(*) FROM submarkets WHERE market_id = m.market_id) as submarket_count
        FROM markets m
        ORDER BY m.name
    """)
    
    markets = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    
    return {"markets": markets}


@router.get(
    "/markets/{market_id}/summary",
    summary="Market Summary",
    description="Get comprehensive summary of a market including ADR, amenity prevalence, and submarket breakdown."
)
async def get_market_summary(
    market_id: str,
    exclude_operator: bool = Query(True, description="Exclude operator-owned properties from analysis"),
):
    """Get market summary with external data only."""
    conn = get_connection()
    cur = conn.cursor()
    
    # Build exclusion clause
    exclude_clause = ""
    if exclude_operator:
        # Get operator property codes to exclude
        cur.execute("SELECT property_code FROM properties")
        operator_codes = [r['property_code'] for r in cur.fetchall()]
        if operator_codes:
            # External listings use listing_id, we'll match on partial patterns
            # For now, just note that external_listings shouldn't overlap
            exclude_clause = "-- Operator properties excluded by design (separate tables)"
    
    # Market overview
    cur.execute("""
        SELECT 
            COUNT(*) as total_listings,
            COUNT(*) FILTER (WHERE source = 'airbnb') as airbnb_count,
            COUNT(*) FILTER (WHERE source = 'vrbo') as vrbo_count,
            ROUND(AVG(avg_adr)::numeric, 0) as avg_adr,
            ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY avg_adr)::numeric, 0) as adr_p25,
            ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY avg_adr)::numeric, 0) as adr_p50,
            ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY avg_adr)::numeric, 0) as adr_p75,
            ROUND(AVG(review_score)::numeric, 2) as avg_review_score,
            ROUND(AVG(review_count)::numeric, 0) as avg_review_count,
            COUNT(*) FILTER (WHERE has_pool) as with_pool,
            COUNT(*) FILTER (WHERE has_hot_tub) as with_hot_tub,
            COUNT(*) FILTER (WHERE has_view) as with_view,
            COUNT(*) FILTER (WHERE pet_friendly) as pet_friendly
        FROM external_listings
        WHERE market_id = %s AND is_active = true AND avg_adr > 0
    """, (market_id,))
    
    overview = dict(cur.fetchone())
    
    # By bedroom
    cur.execute("""
        SELECT 
            bedrooms,
            COUNT(*) as count,
            ROUND(AVG(avg_adr)::numeric, 0) as avg_adr,
            ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY avg_adr)::numeric, 0) as median_adr
        FROM external_listings
        WHERE market_id = %s AND is_active = true AND avg_adr > 0 AND bedrooms > 0
        GROUP BY bedrooms
        ORDER BY bedrooms
    """, (market_id,))
    
    by_bedroom = [dict(r) for r in cur.fetchall()]
    
    # By submarket
    cur.execute("""
        SELECT 
            e.submarket_id,
            s.name as submarket_name,
            s.tier,
            COUNT(*) as count,
            ROUND(AVG(e.avg_adr)::numeric, 0) as avg_adr
        FROM external_listings e
        JOIN submarkets s ON e.submarket_id = s.submarket_id
        WHERE e.market_id = %s AND e.is_active = true AND e.avg_adr > 0
        GROUP BY e.submarket_id, s.name, s.tier
        ORDER BY s.tier, AVG(e.avg_adr) DESC
    """, (market_id,))
    
    by_submarket = [dict(r) for r in cur.fetchall()]
    
    # Amenity prevalence
    total = overview['total_listings'] or 1
    amenity_prevalence = {
        "pool": round((overview['with_pool'] or 0) / total, 3),
        "hot_tub": round((overview['with_hot_tub'] or 0) / total, 3),
        "view": round((overview['with_view'] or 0) / total, 3),
        "pet_friendly": round((overview['pet_friendly'] or 0) / total, 3),
    }
    
    cur.close()
    conn.close()
    
    return {
        "market_id": market_id,
        "data_source": "external_listings_only" if exclude_operator else "all_listings",
        "overview": {
            "total_listings": overview['total_listings'],
            "by_platform": {
                "airbnb": overview['airbnb_count'],
                "vrbo": overview['vrbo_count'],
            },
            "adr": {
                "mean": overview['avg_adr'],
                "p25": overview['adr_p25'],
                "median": overview['adr_p50'],
                "p75": overview['adr_p75'],
            },
            "quality": {
                "avg_review_score": overview['avg_review_score'],
                "avg_review_count": overview['avg_review_count'],
            },
        },
        "by_bedroom": by_bedroom,
        "by_submarket": by_submarket,
        "amenity_prevalence": amenity_prevalence,
    }


@router.get(
    "/markets/{market_id}/amenity-attribution",
    summary="Market-Wide Amenity Attribution",
    description="""
    Calculate amenity lifts from EXTERNAL market data.
    
    This is the accurate way to measure amenity value:
    - Uses 100s of external listings, not just operator portfolio
    - Controls for submarket and bedroom count
    - Excludes operator properties to avoid bias
    """
)
async def get_market_amenity_attribution(
    market_id: str,
    amenity: str = Query("pool", description="Amenity to analyze: pool, hot_tub, view, pet_friendly"),
    control_for_submarket: bool = Query(True, description="Control for submarket tier"),
    control_for_bedrooms: bool = Query(True, description="Control for bedroom count"),
):
    """Calculate amenity lift from external market data."""
    conn = get_connection()
    cur = conn.cursor()
    
    amenity_col = f"has_{amenity}" if amenity in ["pool", "hot_tub", "view"] else amenity
    if amenity == "pet_friendly":
        amenity_col = "pet_friendly"
    
    # Get all external listings
    cur.execute(f"""
        SELECT 
            listing_id,
            submarket_id,
            bedrooms,
            {amenity_col} as has_amenity,
            avg_adr
        FROM external_listings
        WHERE market_id = %s 
          AND is_active = true 
          AND avg_adr > 0 
          AND avg_adr < 5000
          AND bedrooms > 0
    """, (market_id,))
    
    listings = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    
    if len(listings) < 20:
        return {
            "error": "Insufficient data",
            "listing_count": len(listings),
            "message": "Need at least 20 external listings for attribution",
        }
    
    # Simple comparison
    with_amenity = [l for l in listings if l['has_amenity']]
    without_amenity = [l for l in listings if not l['has_amenity']]
    
    if not with_amenity or not without_amenity:
        return {
            "error": "Cannot compare",
            "with_amenity": len(with_amenity),
            "without_amenity": len(without_amenity),
            "message": f"Need listings both with and without {amenity}",
        }
    
    simple_avg_with = sum(float(l['avg_adr']) for l in with_amenity) / len(with_amenity)
    simple_avg_without = sum(float(l['avg_adr']) for l in without_amenity) / len(without_amenity)
    
    # Controlled comparison
    controlled_results = []
    
    if control_for_submarket and control_for_bedrooms:
        # Group by (submarket, bedrooms)
        from collections import defaultdict
        groups = defaultdict(lambda: {"with": [], "without": []})
        
        for l in listings:
            key = (l['submarket_id'], l['bedrooms'])
            if l['has_amenity']:
                groups[key]["with"].append(l)
            else:
                groups[key]["without"].append(l)
        
        weighted_lift_sum = 0.0
        total_weight = 0
        
        for key, group in groups.items():
            if len(group["with"]) >= 2 and len(group["without"]) >= 2:
                avg_with = sum(float(l['avg_adr']) for l in group["with"]) / len(group["with"])
                avg_without = sum(float(l['avg_adr']) for l in group["without"]) / len(group["without"])
                lift = (avg_with - avg_without) / avg_without if avg_without > 0 else 0
                
                weight = min(len(group["with"]), len(group["without"]))
                weighted_lift_sum += lift * weight
                total_weight += weight
                
                controlled_results.append({
                    "submarket": key[0],
                    "bedrooms": key[1],
                    "with_count": len(group["with"]),
                    "without_count": len(group["without"]),
                    "lift_pct": round(lift, 4),
                })
        
        controlled_lift = weighted_lift_sum / total_weight if total_weight > 0 else None
    else:
        controlled_lift = None
    
    return {
        "market_id": market_id,
        "amenity": amenity,
        "sample_size": {
            "total": len(listings),
            "with_amenity": len(with_amenity),
            "without_amenity": len(without_amenity),
        },
        "simple_comparison": {
            "avg_adr_with": round(simple_avg_with, 0),
            "avg_adr_without": round(simple_avg_without, 0),
            "lift_dollars": round(simple_avg_with - simple_avg_without, 0),
            "lift_pct": round((simple_avg_with - simple_avg_without) / simple_avg_without, 4),
            "note": "Not controlled - may be confounded by location/size",
        },
        "controlled_comparison": {
            "controlled_for": ["submarket", "bedrooms"] if control_for_submarket and control_for_bedrooms else [],
            "weighted_avg_lift_pct": round(controlled_lift, 4) if controlled_lift else None,
            "comparison_groups": len(controlled_results),
            "confidence": "high" if len(controlled_results) >= 10 else "medium" if len(controlled_results) >= 5 else "low",
            "group_details": sorted(controlled_results, key=lambda x: x['lift_pct'], reverse=True)[:10],
        },
        "recommendation": f"Use controlled lift ({round(controlled_lift * 100, 1)}%) for BD projections" if controlled_lift else "Need more data for controlled comparison",
    }


# =============================================================================
# BOOKING VELOCITY & DYNAMIC PRICING
# =============================================================================

@router.get(
    "/markets/{market_id}/booking-velocity",
    summary="Booking Velocity",
    description="""
    Track how fast bookings are happening in the market.
    
    Compares calendar compression over time to detect:
    - Demand surges (events, holidays)
    - Booking slowdowns
    - Optimal pricing windows
    """
)
async def get_booking_velocity(market_id: str):
    """Get booking velocity for dynamic pricing."""
    conn = get_connection()
    cur = conn.cursor()
    
    # Check if we have the calendar snapshots table
    cur.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'market_calendar_snapshots'
        )
    """)
    
    if not cur.fetchone()[0]:
        cur.close()
        conn.close()
        return {
            "error": "No calendar data",
            "message": "Run market scraper with --save-to-db to collect calendar snapshots",
        }
    
    # Get recent snapshots
    cur.execute("""
        SELECT *
        FROM market_calendar_snapshots
        WHERE market_id = %s
        ORDER BY snapshot_date DESC
        LIMIT 7
    """, (market_id,))
    
    snapshots = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    
    if len(snapshots) < 2:
        return {
            "market_id": market_id,
            "message": "Need at least 2 snapshots to calculate velocity. Run scraper daily.",
            "snapshots_available": len(snapshots),
        }
    
    latest = snapshots[0]
    previous = snapshots[1]
    
    # Calculate velocity
    velocity_7d = (float(latest['compression_7d'] or 0) - float(previous['compression_7d'] or 0))
    velocity_30d = (float(latest['compression_30d'] or 0) - float(previous['compression_30d'] or 0))
    
    days_between = (latest['snapshot_date'] - previous['snapshot_date']).days
    
    # Interpret for pricing
    if velocity_30d > 0.15:
        pricing_recommendation = {
            "action": "INCREASE_ADR",
            "magnitude": "15-25%",
            "reason": "Bookings accelerating rapidly - high demand detected",
            "confidence": "high",
        }
    elif velocity_30d > 0.08:
        pricing_recommendation = {
            "action": "INCREASE_ADR",
            "magnitude": "10-15%",
            "reason": "Strong booking pace - demand exceeds normal",
            "confidence": "high",
        }
    elif velocity_30d > 0.03:
        pricing_recommendation = {
            "action": "HOLD",
            "magnitude": "0%",
            "reason": "Normal booking pace",
            "confidence": "medium",
        }
    elif velocity_30d > -0.03:
        pricing_recommendation = {
            "action": "HOLD",
            "magnitude": "0%",
            "reason": "Stable market conditions",
            "confidence": "medium",
        }
    elif velocity_30d > -0.08:
        pricing_recommendation = {
            "action": "DECREASE_ADR",
            "magnitude": "5-10%",
            "reason": "Bookings slowing - consider promotional pricing",
            "confidence": "medium",
        }
    else:
        pricing_recommendation = {
            "action": "DECREASE_ADR",
            "magnitude": "10-20%",
            "reason": "Weak demand - aggressive pricing recommended",
            "confidence": "high",
        }
    
    return {
        "market_id": market_id,
        "latest_snapshot": latest['snapshot_date'].isoformat(),
        "previous_snapshot": previous['snapshot_date'].isoformat(),
        "days_between": days_between,
        "current_compression": {
            "7d": round(float(latest['compression_7d'] or 0), 4),
            "14d": round(float(latest['compression_14d'] or 0), 4),
            "30d": round(float(latest['compression_30d'] or 0), 4),
            "90d": round(float(latest['compression_90d'] or 0), 4),
        },
        "velocity": {
            "7d_change": round(velocity_7d, 4),
            "30d_change": round(velocity_30d, 4),
        },
        "pricing_recommendation": pricing_recommendation,
        "compression_by_bedrooms": latest.get('compression_by_bedrooms'),
    }


# =============================================================================
# EVENTS & DEMAND SIGNALS
# =============================================================================

@router.get(
    "/markets/{market_id}/events",
    summary="Upcoming Events",
    description="""
    Get upcoming events that impact demand.
    
    Includes:
    - Local festivals and concerts
    - Sporting events
    - Holidays
    - Conferences
    
    Each event has an estimated demand multiplier for pricing.
    """
)
async def get_market_events(
    market_id: str,
    days_ahead: int = Query(90, description="How many days ahead to look"),
):
    """Get upcoming events for a market."""
    # Import the event scraper
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    
    try:
        from app.workers.ingestion.event_scraper import EventScraper
        
        scraper = EventScraper(market_id=market_id, lookahead_days=days_ahead)
        
        # Run sync (the scraper is simple enough)
        import asyncio
        evidence = asyncio.get_event_loop().run_until_complete(scraper.scrape())
        
        # Format for API response
        events = []
        summary = None
        
        for e in evidence:
            if e.evidence_type == "event":
                events.append({
                    "name": e.data.get("name"),
                    "dates": {
                        "start": e.data.get("start_date"),
                        "end": e.data.get("end_date"),
                    },
                    "location": e.data.get("location"),
                    "category": e.data.get("category"),
                    "expected_attendance": e.data.get("expected_attendance"),
                    "impact": e.data.get("impact"),
                    "demand_multiplier": e.data.get("demand_multiplier"),
                })
            elif e.evidence_type == "event_summary":
                summary = e.data
        
        # Sort by date
        events.sort(key=lambda x: x['dates']['start'])
        
        return {
            "market_id": market_id,
            "days_ahead": days_ahead,
            "summary": summary,
            "events": events,
            "pricing_guidance": [
                {"impact": "extreme", "multiplier": 1.5, "description": "Major event (10k+ attendance) - increase ADR 40-50%"},
                {"impact": "high", "multiplier": 1.3, "description": "Significant event (5k+ attendance) - increase ADR 25-35%"},
                {"impact": "medium", "multiplier": 1.15, "description": "Moderate event (2k+ attendance) - increase ADR 10-20%"},
                {"impact": "low", "multiplier": 1.05, "description": "Small event - slight ADR increase 5%"},
            ],
        }
        
    except Exception as e:
        # Fallback to known events
        from app.workers.ingestion.event_scraper import KNOWN_EVENTS, US_HOLIDAYS_2026
        
        today = date.today()
        cutoff = today + timedelta(days=days_ahead)
        
        events = []
        
        # Get market events
        market_key = market_id.replace("_fl", "").replace("_al", "")
        market_events = KNOWN_EVENTS.get(market_key, [])
        
        for e in market_events:
            if e.start_date >= today and e.start_date <= cutoff:
                # Estimate impact
                if e.expected_attendance and e.expected_attendance >= 10000:
                    impact, mult = "extreme", 1.5
                elif e.expected_attendance and e.expected_attendance >= 5000:
                    impact, mult = "high", 1.3
                elif e.expected_attendance and e.expected_attendance >= 2000:
                    impact, mult = "medium", 1.15
                else:
                    impact, mult = "low", 1.05
                
                events.append({
                    "name": e.name,
                    "dates": {"start": e.start_date.isoformat(), "end": e.end_date.isoformat()},
                    "location": e.location,
                    "category": e.category,
                    "expected_attendance": e.expected_attendance,
                    "impact": impact,
                    "demand_multiplier": mult,
                })
        
        # Add holidays
        for e in US_HOLIDAYS_2026:
            if e.start_date >= today and e.start_date <= cutoff:
                events.append({
                    "name": e.name,
                    "dates": {"start": e.start_date.isoformat(), "end": e.end_date.isoformat()},
                    "location": "national",
                    "category": "holiday",
                    "expected_attendance": None,
                    "impact": "high",
                    "demand_multiplier": 1.3,
                })
        
        events.sort(key=lambda x: x['dates']['start'])
        
        return {
            "market_id": market_id,
            "days_ahead": days_ahead,
            "events": events,
            "note": "Using pre-configured event data",
        }


@router.get(
    "/markets/{market_id}/pricing-signals",
    summary="Combined Pricing Signals",
    description="""
    Get all pricing signals for a market combined:
    - Booking velocity
    - Upcoming events
    - Seasonal factors
    - Competitor pricing
    
    Use for dynamic pricing engine input.
    """
)
async def get_pricing_signals(
    market_id: str,
    target_date: str = Query(None, description="Target date (YYYY-MM-DD), defaults to today"),
):
    """Get combined pricing signals for a specific date."""
    conn = get_connection()
    cur = conn.cursor()
    
    if target_date:
        check_date = date.fromisoformat(target_date)
    else:
        check_date = date.today()
    
    signals = {
        "market_id": market_id,
        "target_date": check_date.isoformat(),
        "signals": [],
        "combined_multiplier": 1.0,
    }
    
    # 1. Seasonal factor (simplified)
    month = check_date.month
    seasonal_factors = {
        1: 0.7,   # January - low
        2: 0.75,  # February - low
        3: 1.1,   # March - spring break
        4: 1.0,   # April - shoulder
        5: 1.1,   # May - warming up
        6: 1.3,   # June - summer
        7: 1.4,   # July - peak
        8: 1.3,   # August - summer
        9: 0.9,   # September - shoulder
        10: 0.95, # October - fall
        11: 0.85, # November
        12: 1.0,  # December - holidays
    }
    
    seasonal = seasonal_factors.get(month, 1.0)
    signals["signals"].append({
        "type": "seasonal",
        "factor": seasonal,
        "description": f"Seasonal factor for {check_date.strftime('%B')}",
    })
    signals["combined_multiplier"] *= seasonal
    
    # 2. Day of week
    dow = check_date.weekday()
    if dow in [4, 5]:  # Friday, Saturday
        dow_factor = 1.15
        dow_desc = "Weekend premium"
    elif dow == 6:  # Sunday
        dow_factor = 1.05
        dow_desc = "Sunday slight premium"
    else:
        dow_factor = 0.95
        dow_desc = "Weekday discount"
    
    signals["signals"].append({
        "type": "day_of_week",
        "factor": dow_factor,
        "description": dow_desc,
    })
    signals["combined_multiplier"] *= dow_factor
    
    # 3. Event check
    from app.workers.ingestion.event_scraper import KNOWN_EVENTS, US_HOLIDAYS_2026
    
    market_key = market_id.replace("_fl", "").replace("_al", "")
    all_events = KNOWN_EVENTS.get(market_key, []) + US_HOLIDAYS_2026
    
    for event in all_events:
        if event.start_date <= check_date <= event.end_date:
            if event.expected_attendance and event.expected_attendance >= 10000:
                event_factor = 1.5
            elif event.expected_attendance and event.expected_attendance >= 5000:
                event_factor = 1.3
            elif event.category == "holiday":
                event_factor = 1.25
            else:
                event_factor = 1.15
            
            signals["signals"].append({
                "type": "event",
                "factor": event_factor,
                "description": f"Event: {event.name}",
                "event_name": event.name,
            })
            signals["combined_multiplier"] *= event_factor
            break  # Only count one event
    
    # 4. Booking velocity (if available)
    try:
        cur.execute("""
            SELECT compression_30d
            FROM market_calendar_snapshots
            WHERE market_id = %s
            ORDER BY snapshot_date DESC
            LIMIT 1
        """, (market_id,))
        
        row = cur.fetchone()
        if row and row['compression_30d']:
            compression = float(row['compression_30d'])
            if compression > 0.8:
                velocity_factor = 1.2
                velocity_desc = "Very high demand (80%+ booked)"
            elif compression > 0.6:
                velocity_factor = 1.1
                velocity_desc = "High demand (60-80% booked)"
            elif compression < 0.3:
                velocity_factor = 0.9
                velocity_desc = "Low demand (<30% booked)"
            else:
                velocity_factor = 1.0
                velocity_desc = "Normal demand"
            
            signals["signals"].append({
                "type": "booking_velocity",
                "factor": velocity_factor,
                "description": velocity_desc,
                "compression": compression,
            })
            signals["combined_multiplier"] *= velocity_factor
    except:
        pass
    
    cur.close()
    conn.close()
    
    # Round combined multiplier
    signals["combined_multiplier"] = round(signals["combined_multiplier"], 3)
    
    # Add pricing guidance
    signals["pricing_guidance"] = {
        "multiplier": signals["combined_multiplier"],
        "direction": "increase" if signals["combined_multiplier"] > 1.05 else "decrease" if signals["combined_multiplier"] < 0.95 else "hold",
        "magnitude_pct": round((signals["combined_multiplier"] - 1) * 100, 1),
    }
    
    return signals


# =============================================================================
# VOICE CONCIERGE INTEGRATION
# =============================================================================

@router.get(
    "/markets/{market_id}/voice-context",
    summary="Voice Concierge Context",
    description="""
    Get market context for voice concierge.
    
    Returns natural language snippets the voice agent can use:
    - Upcoming events to mention
    - Local recommendations
    - Pricing context
    """
)
async def get_voice_context(
    market_id: str,
    check_in: str = Query(None, description="Guest check-in date"),
    check_out: str = Query(None, description="Guest check-out date"),
):
    """Get context for voice concierge."""
    snippets = []
    
    # Parse dates
    if check_in:
        checkin_date = date.fromisoformat(check_in)
    else:
        checkin_date = date.today()
    
    if check_out:
        checkout_date = date.fromisoformat(check_out)
    else:
        checkout_date = checkin_date + timedelta(days=7)
    
    # Get events during stay
    from app.workers.ingestion.event_scraper import KNOWN_EVENTS, US_HOLIDAYS_2026
    
    market_key = market_id.replace("_fl", "").replace("_al", "")
    all_events = KNOWN_EVENTS.get(market_key, []) + US_HOLIDAYS_2026
    
    events_during_stay = []
    for event in all_events:
        # Check if event overlaps with stay
        if event.start_date <= checkout_date and event.end_date >= checkin_date:
            events_during_stay.append(event)
    
    # Generate snippets
    if events_during_stay:
        for event in events_during_stay[:3]:  # Max 3 events
            if event.category == "holiday":
                snippets.append({
                    "type": "event",
                    "text": f"Just so you know, {event.name} falls during your stay. Some local businesses may have adjusted hours.",
                })
            elif event.category in ["music", "festival"]:
                snippets.append({
                    "type": "event",
                    "text": f"Great timing! The {event.name} is happening {event.start_date.strftime('%B %d')} through {event.end_date.strftime('%B %d')}. It's one of the area's most popular events.",
                })
            elif event.category == "sports":
                snippets.append({
                    "type": "event",
                    "text": f"The {event.name} is taking place during your visit. If you're interested, I can share more details.",
                })
    
    # Seasonal context
    month = checkin_date.month
    if month in [6, 7, 8]:
        snippets.append({
            "type": "seasonal",
            "text": "You're visiting during our peak summer season. I'd recommend hitting the beach early morning or late afternoon to avoid the midday crowds.",
        })
    elif month in [3, 4]:
        snippets.append({
            "type": "seasonal",
            "text": "Spring is a wonderful time on 30A. The weather is beautiful and it's less crowded than summer. Perfect for biking and exploring the coastal dune lakes.",
        })
    elif month in [9, 10]:
        snippets.append({
            "type": "seasonal",
            "text": "Fall is our hidden gem season. The water is still warm, the crowds have thinned, and the sunsets are spectacular.",
        })
    
    return {
        "market_id": market_id,
        "stay_dates": {
            "check_in": checkin_date.isoformat(),
            "check_out": checkout_date.isoformat(),
        },
        "events_during_stay": [
            {
                "name": e.name,
                "dates": f"{e.start_date.isoformat()} to {e.end_date.isoformat()}",
                "category": e.category,
            }
            for e in events_during_stay
        ],
        "voice_snippets": snippets,
    }
