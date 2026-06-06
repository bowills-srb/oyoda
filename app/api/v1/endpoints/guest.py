"""
Guest API Endpoints

Live guest concierge endpoints that use real database data.
This connects the scraped property/booking/pricing data to the concierge.
"""

from datetime import date
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.concierge.property_context import (
    get_full_guest_context,
    get_property_profile_dict,
    format_context_for_llm,
)

router = APIRouter(prefix="/guest", tags=["Guest Concierge"])


class GuestContextResponse(BaseModel):
    """Response with full guest context."""
    property_code: str
    property_name: str
    community: str
    bedrooms: int
    bathrooms: float
    sleeps: int
    
    # Access
    wifi_network: Optional[str] = None
    wifi_password: Optional[str] = None
    check_in_time: str
    check_out_time: str
    property_guide_url: Optional[str] = None
    
    # Amenities
    has_pool: bool = False
    has_hot_tub: bool = False
    has_grill: bool = False
    has_bikes: bool = False
    bike_count: int = 0
    
    # Current booking (if any)
    has_active_booking: bool = False
    check_in: Optional[date] = None
    check_out: Optional[date] = None
    nights: Optional[int] = None
    is_arrival_day: bool = False
    is_departure_day: bool = False
    
    # Pricing
    avg_nightly_rate: Optional[float] = None
    
    # LLM-ready context
    llm_context: str


@router.get("/{property_code}", response_model=GuestContextResponse)
async def get_guest_context(property_code: str, as_of: Optional[date] = None):
    """
    Get complete guest context for a property.
    
    Returns property details, current booking info, and LLM-ready context.
    """
    ctx = get_full_guest_context(property_code, as_of)
    
    if not ctx:
        raise HTTPException(status_code=404, detail=f"Property {property_code} not found")
    
    p = ctx.property
    b = ctx.booking
    
    return GuestContextResponse(
        property_code=p.property_code,
        property_name=p.property_name,
        community=p.community,
        bedrooms=p.bedrooms,
        bathrooms=p.bathrooms,
        sleeps=p.sleeps,
        wifi_network=p.wifi_network,
        wifi_password=p.wifi_password,
        check_in_time=p.check_in_time,
        check_out_time=p.check_out_time,
        property_guide_url=p.property_guide_url,
        has_pool=p.has_pool,
        has_hot_tub=p.has_hot_tub,
        has_grill=p.has_grill,
        has_bikes=p.has_bikes,
        bike_count=p.bike_count,
        has_active_booking=b is not None,
        check_in=b.check_in if b else None,
        check_out=b.check_out if b else None,
        nights=b.nights if b else None,
        is_arrival_day=b.is_arrival_day if b else False,
        is_departure_day=b.is_departure_day if b else False,
        avg_nightly_rate=float(ctx.avg_nightly_rate) if ctx.avg_nightly_rate else None,
        llm_context=format_context_for_llm(ctx),
    )


@router.get("/{property_code}/context")
async def get_llm_context(property_code: str, as_of: Optional[date] = None):
    """
    Get LLM-ready context string for a property.
    
    Use this to inject property context into your voice agent prompt.
    """
    ctx = get_full_guest_context(property_code, as_of)
    
    if not ctx:
        raise HTTPException(status_code=404, detail=f"Property {property_code} not found")
    
    return {
        "property_code": property_code,
        "llm_context": format_context_for_llm(ctx),
    }


@router.get("/{property_code}/profile")
async def get_property_profile(property_code: str):
    """
    Get property profile dictionary for concierge runner.
    
    This replaces hardcoded property profiles.
    """
    profile = get_property_profile_dict(property_code)
    
    if not profile:
        raise HTTPException(status_code=404, detail=f"Property {property_code} not found")
    
    return profile
