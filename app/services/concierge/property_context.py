"""
Property Context Service

Provides real property data from the database for the guest concierge.
This replaces hardcoded property profiles with live data from our scrapers.
"""

import os
from datetime import date, datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor

from app.core.db_connect import resolve_runtime_sync_database_url

DATABASE_URL = resolve_runtime_sync_database_url(os.getenv("DATABASE_URL"))


@dataclass
class PropertyContext:
    """Complete property context for guest interactions."""
    property_code: str
    property_name: str
    
    # Location
    address: str
    community: str
    
    # Property details
    bedrooms: int
    bathrooms: float
    sleeps: int
    
    # Access info
    wifi_network: Optional[str] = None
    wifi_password: Optional[str] = None
    lock_type: Optional[str] = None
    property_guide_url: Optional[str] = None
    
    # Check-in/out
    check_in_time: str = "4:00 PM"
    check_out_time: str = "11:00 AM"
    check_in_instructions: Optional[str] = None
    check_out_instructions: Optional[str] = None
    
    # Amenities
    has_pool: bool = False
    pool_heated: bool = False
    has_hot_tub: bool = False
    has_grill: bool = False
    has_bikes: bool = False
    bike_count: int = 0
    has_beach_gear: bool = False
    has_washer_dryer: bool = False
    
    # Rules
    pets_allowed: bool = False
    max_occupancy: Optional[int] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None


@dataclass
class BookingContext:
    """Current booking context for a guest."""
    property_code: str
    check_in: date
    check_out: date
    nights: int
    
    # Calculated fields
    nights_elapsed: int = 0
    nights_remaining: int = 0
    is_arrival_day: bool = False
    is_departure_day: bool = False
    stay_progress_pct: float = 0.0


@dataclass
class GuestContext:
    """Complete context for guest concierge interactions."""
    property: PropertyContext
    booking: Optional[BookingContext] = None
    
    # Pricing context (for upsells, etc.)
    avg_nightly_rate: Optional[Decimal] = None


def get_property_context(property_code: str) -> Optional[PropertyContext]:
    """
    Load property context from database.
    
    Returns None if property not found.
    """
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                property_code,
                address_street,
                address_city,
                community,
                bedrooms,
                bathrooms,
                sleeps,
                wifi_network,
                wifi_password,
                lock_type,
                property_guide_url,
                check_in_time,
                check_out_time,
                check_in_instructions,
                check_out_instructions,
                has_pool,
                pool_heated,
                has_hot_tub,
                has_grill,
                has_bikes,
                bike_count,
                has_beach_gear,
                has_washer_dryer,
                pets_allowed,
                max_occupancy,
                quiet_hours_start,
                quiet_hours_end
            FROM properties
            WHERE property_code = %s
        """, (property_code,))
        
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if not row:
            return None
        
        # Parse property name from address_street
        address = row['address_street'] or ''
        name = address.split(' - ')[0] if ' - ' in address else address
        
        return PropertyContext(
            property_code=row['property_code'],
            property_name=name,
            address=address,
            community=row['community'] or '',
            bedrooms=row['bedrooms'] or 0,
            bathrooms=float(row['bathrooms'] or 0),
            sleeps=row['sleeps'] or 0,
            wifi_network=row['wifi_network'],
            wifi_password=row['wifi_password'],
            lock_type=row['lock_type'],
            property_guide_url=row['property_guide_url'],
            check_in_time=row['check_in_time'] or '4:00 PM',
            check_out_time=row['check_out_time'] or '11:00 AM',
            check_in_instructions=row['check_in_instructions'],
            check_out_instructions=row['check_out_instructions'],
            has_pool=row['has_pool'] or False,
            pool_heated=row['pool_heated'] or False,
            has_hot_tub=row['has_hot_tub'] or False,
            has_grill=row['has_grill'] or False,
            has_bikes=row['has_bikes'] or False,
            bike_count=row['bike_count'] or 0,
            has_beach_gear=row['has_beach_gear'] or False,
            has_washer_dryer=row['has_washer_dryer'] or False,
            pets_allowed=row['pets_allowed'] or False,
            max_occupancy=row['max_occupancy'],
            quiet_hours_start=row['quiet_hours_start'],
            quiet_hours_end=row['quiet_hours_end'],
        )
        
    except Exception as e:
        print(f"Error loading property context: {e}")
        return None


def get_active_booking(property_code: str, as_of: date = None) -> Optional[BookingContext]:
    """
    Get the active booking for a property on a given date.
    
    Returns None if no active booking.
    """
    if as_of is None:
        as_of = date.today()
    
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                property_code,
                check_in,
                check_out,
                nights
            FROM property_bookings
            WHERE property_code = %s
              AND check_in <= %s
              AND check_out >= %s
              AND nights > 0
              AND nights <= 60  -- Exclude owner blocks
            ORDER BY check_in DESC
            LIMIT 1
        """, (property_code, as_of, as_of))
        
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if not row:
            return None
        
        check_in = row['check_in']
        check_out = row['check_out']
        nights = row['nights']
        
        nights_elapsed = (as_of - check_in).days
        nights_remaining = (check_out - as_of).days
        
        return BookingContext(
            property_code=row['property_code'],
            check_in=check_in,
            check_out=check_out,
            nights=nights,
            nights_elapsed=nights_elapsed,
            nights_remaining=nights_remaining,
            is_arrival_day=(as_of == check_in),
            is_departure_day=(as_of == check_out),
            stay_progress_pct=round((nights_elapsed / nights) * 100, 1) if nights > 0 else 0,
        )
        
    except Exception as e:
        print(f"Error loading booking context: {e}")
        return None


def get_avg_nightly_rate(property_code: str) -> Optional[Decimal]:
    """Get average nightly rate for a property."""
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT AVG(adr) as avg_adr
            FROM property_pricing
            WHERE property_code = %s AND adr > 0
        """, (property_code,))
        
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if row and row['avg_adr']:
            return Decimal(str(row['avg_adr']))
        return None
        
    except Exception as e:
        print(f"Error loading pricing: {e}")
        return None


def get_full_guest_context(property_code: str, as_of: date = None) -> Optional[GuestContext]:
    """
    Get complete guest context including property, booking, and pricing.
    
    This is the main entry point for the concierge service.
    """
    prop = get_property_context(property_code)
    if not prop:
        return None
    
    booking = get_active_booking(property_code, as_of)
    avg_rate = get_avg_nightly_rate(property_code)
    
    return GuestContext(
        property=prop,
        booking=booking,
        avg_nightly_rate=avg_rate,
    )


def format_context_for_llm(ctx: GuestContext) -> str:
    """
    Format guest context as a string for LLM system prompt injection.
    """
    lines = []
    
    # Property info
    p = ctx.property
    lines.append(f"PROPERTY: {p.property_name}")
    lines.append(f"  Location: {p.community}")
    lines.append(f"  Size: {p.bedrooms}BR/{p.bathrooms}BA, sleeps {p.sleeps}")
    
    # Booking info
    if ctx.booking:
        b = ctx.booking
        lines.append("")
        lines.append(f"CURRENT BOOKING:")
        lines.append(f"  Dates: {b.check_in} to {b.check_out} ({b.nights} nights)")
        lines.append(f"  Day {b.nights_elapsed + 1} of {b.nights}")
        
        if b.is_arrival_day:
            lines.append("  *** THIS IS ARRIVAL DAY ***")
        elif b.is_departure_day:
            lines.append("  *** THIS IS DEPARTURE DAY ***")
    
    # Access info
    lines.append("")
    lines.append("ACCESS:")
    lines.append(f"  Check-in: {p.check_in_time}")
    lines.append(f"  Check-out: {p.check_out_time}")
    if p.wifi_network:
        lines.append(f"  WiFi: {p.wifi_network} / {p.wifi_password}")
    if p.property_guide_url:
        lines.append(f"  Guide: {p.property_guide_url}")
    
    # Amenities
    amenities = []
    if p.has_pool:
        amenities.append("pool" + (" (heated)" if p.pool_heated else ""))
    if p.has_hot_tub:
        amenities.append("hot tub")
    if p.has_grill:
        amenities.append("grill")
    if p.has_bikes and p.bike_count > 0:
        amenities.append(f"{p.bike_count} bikes")
    if p.has_beach_gear:
        amenities.append("beach gear")
    if p.has_washer_dryer:
        amenities.append("washer/dryer")
    
    if amenities:
        lines.append("")
        lines.append(f"AMENITIES: {', '.join(amenities)}")
    
    # Rules
    if p.quiet_hours_start or p.max_occupancy:
        lines.append("")
        lines.append("HOUSE RULES:")
        if p.quiet_hours_start and p.quiet_hours_end:
            lines.append(f"  Quiet hours: {p.quiet_hours_start} - {p.quiet_hours_end}")
        if p.max_occupancy:
            lines.append(f"  Max occupancy: {p.max_occupancy}")
        if p.pets_allowed:
            lines.append("  Pets: Allowed")
    
    return "\n".join(lines)


# =============================================================================
# CONVENIENCE FUNCTIONS FOR API
# =============================================================================

def get_property_profile_dict(property_code: str) -> Dict[str, Any]:
    """
    Get property profile as a dictionary for the concierge runner.
    
    This replaces the hardcoded property_profile in the API endpoint.
    """
    prop = get_property_context(property_code)
    if not prop:
        return {}
    
    return {
        "property_code": prop.property_code,
        "property_name": prop.property_name,
        "operational_constraints": {
            "check_in_time": prop.check_in_time,
            "check_out_time": prop.check_out_time,
            "late_checkout_available": True,
            "late_checkout_latest": "2:00 PM",
            "minimum_turnover_hours": 4.0,
        },
        "access": {
            "wifi_network": prop.wifi_network,
            "wifi_password": prop.wifi_password,
            "lock_type": prop.lock_type,
            "property_guide_url": prop.property_guide_url,
        },
        "amenities": {
            "has_pool": prop.has_pool,
            "pool_heated": prop.pool_heated,
            "has_hot_tub": prop.has_hot_tub,
            "has_grill": prop.has_grill,
            "has_bikes": prop.has_bikes,
            "bike_count": prop.bike_count,
            "has_beach_gear": prop.has_beach_gear,
            "has_washer_dryer": prop.has_washer_dryer,
        },
        "rules": {
            "pets_allowed": prop.pets_allowed,
            "max_occupancy": prop.max_occupancy,
            "quiet_hours_start": prop.quiet_hours_start,
            "quiet_hours_end": prop.quiet_hours_end,
        }
    }
