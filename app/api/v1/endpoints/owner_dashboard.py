"""
Owner Dashboard API

Endpoints for property owners to:
1. Sign up / onboard their properties
2. Configure concierge settings per property
3. View guest interactions and journey status
4. See analytics and extend stay conversions
"""

from datetime import date, datetime
from typing import Optional, List
from uuid import UUID
import logging

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/owner", tags=["Owner Dashboard"])


# =============================================================================
# Request/Response Models
# =============================================================================

class OwnerSignupRequest(BaseModel):
    """Owner signup/onboarding request"""
    name: str
    email: EmailStr
    phone: Optional[str] = None
    company_name: Optional[str] = None
    
    # Property info (simplified for initial signup)
    property_name: str
    property_address: str
    property_city: str
    property_state: str
    property_zip: str
    
    bedrooms: int
    bathrooms: float
    sleeps: int
    
    # Amenities (key ones for concierge)
    has_pool: bool = False
    pool_heated: bool = False
    beach_access_type: Optional[str] = None  # "private", "community", "public", "none"
    pet_friendly: bool = False


class PropertyConfigRequest(BaseModel):
    """Configure concierge settings for a property"""
    # Check-in/out
    check_in_time: str = "4:00 PM"
    check_out_time: str = "10:00 AM"
    
    # Access
    wifi_network: Optional[str] = None
    wifi_password: Optional[str] = None
    door_code_instructions: Optional[str] = None  # "Code will be sent morning of arrival"
    
    # Property specifics
    parking_info: Optional[str] = None
    trash_instructions: Optional[str] = None
    pool_rules: Optional[str] = None
    beach_access_instructions: Optional[str] = None
    
    # Concierge personality
    concierge_name: str = "Coral"
    concierge_greeting: Optional[str] = None
    
    # Extend stay settings
    extend_stay_enabled: bool = True
    extend_stay_discount_pct: int = 10
    
    # Pool heat
    pool_heat_enabled: bool = False
    pool_heat_cost_per_day: int = 50


class PropertyResponse(BaseModel):
    property_id: str
    name: str
    address: str
    status: str
    bedrooms: int
    bathrooms: float
    
    # Concierge stats
    active_sessions: int
    total_conversations: int
    extend_stay_offers_sent: int
    extend_stay_conversions: int


class OwnerDashboardResponse(BaseModel):
    owner_id: str
    name: str
    email: str
    properties: List[PropertyResponse]
    
    # Aggregate stats
    total_active_guests: int
    total_conversations_today: int
    pending_escalations: int


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/signup")
async def owner_signup(
    request: OwnerSignupRequest,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Owner signup - creates owner account and their first property.
    
    This is the entry point for new property owners.
    """
    # TODO: Create actual database records
    # For now, return mock success
    
    return {
        "status": "success",
        "message": f"Welcome {request.name}! Your property '{request.property_name}' has been set up.",
        "owner_id": "owner_placeholder",
        "property_id": "prop_placeholder",
        "next_steps": [
            "Configure your property settings",
            "Add WiFi and door code information",
            "Test the guest concierge interface",
        ],
        "concierge_preview_url": "/c/preview",
    }


@router.get("/dashboard")
async def get_owner_dashboard(
    owner_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Get owner dashboard overview.
    
    Shows all properties, active guests, and key metrics.
    """
    # TODO: Pull from database
    # For now, return structure
    
    return {
        "owner_id": owner_id,
        "name": "Demo Owner",
        "email": "owner@example.com",
        "properties": [],
        "total_active_guests": 0,
        "total_conversations_today": 0,
        "pending_escalations": 0,
    }


@router.get("/properties")
async def list_owner_properties(
    owner_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """List all properties for an owner"""
    # TODO: Pull from database
    return {"properties": []}


@router.get("/properties/{property_id}")
async def get_property_detail(
    property_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """Get detailed property info including concierge config"""
    # TODO: Pull from database
    return {"property_id": property_id, "status": "not_found"}


@router.put("/properties/{property_id}/config")
async def update_property_config(
    property_id: str,
    config: PropertyConfigRequest,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Update concierge configuration for a property.
    
    This sets up all the quick-answer data (WiFi, codes, etc.)
    and concierge behavior settings.
    """
    # TODO: Save to database
    
    return {
        "status": "success",
        "property_id": property_id,
        "message": "Property configuration updated",
        "config": config.dict(),
    }


@router.get("/properties/{property_id}/guests")
async def list_property_guests(
    property_id: str,
    status: Optional[str] = None,  # "active", "upcoming", "past"
    db: AsyncSession = Depends(get_async_session),
):
    """
    List guests for a property.
    
    Shows current, upcoming, and past guests with their journey status.
    """
    from app.services.concierge.guest_session import get_session_manager
    
    manager = get_session_manager()
    sessions = [s for s in manager._sessions.values() if s.property_code == property_id]
    
    return {
        "property_id": property_id,
        "guests": [
            {
                "token": s.token,
                "guest_name": s.guest_name,
                "check_in": s.check_in.isoformat() if s.check_in else None,
                "check_out": s.check_out.isoformat() if s.check_out else None,
                "phase": s.phase.value,
                "conversation_count": s.conversation_count,
            }
            for s in sessions
        ],
    }


@router.get("/properties/{property_id}/guests/{token}/journey")
async def get_guest_journey_detail(
    property_id: str,
    token: str,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Get detailed journey for a specific guest.
    
    Shows what they've asked about, what's been booked, what they declined.
    """
    from app.services.operator.stay_journey_service import get_journey_summary_by_token

    summary = await get_journey_summary_by_token(db, token)
    if not summary:
        raise HTTPException(status_code=404, detail="Journey not found")
    
    return summary


@router.get("/properties/{property_id}/extend-stay-opportunities")
async def get_extend_stay_opportunities(
    property_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Get guests who could be offered an extended stay.
    
    Checks which guests are checking out soon without a next booking.
    """
    from app.services.concierge.guest_session import get_session_manager
    from app.services.concierge.db_service import check_next_booking
    from uuid import UUID
    
    manager = get_session_manager()
    today = date.today()
    
    opportunities = []
    
    for session in manager._sessions.values():
        if session.property_code != property_id:
            continue
        
        if not session.check_out:
            continue
        
        # Check if checking out in next 2 days
        days_until_checkout = (session.check_out - today).days
        if days_until_checkout < 0 or days_until_checkout > 2:
            continue
        
        # Check for next booking
        # TODO: Use actual property_id UUID
        # For now, assume no next booking
        next_booking = {
            "has_next_booking": False,
            "extend_offer_available": True,
        }
        
        if next_booking["extend_offer_available"]:
            opportunities.append({
                "token": session.token,
                "guest_name": session.guest_name,
                "check_out": session.check_out.isoformat(),
                "days_until_checkout": days_until_checkout,
                "offer_sent": False,  # TODO: Track this
            })
    
    return {
        "property_id": property_id,
        "opportunities": opportunities,
        "discount_pct": 10,
    }


@router.post("/properties/{property_id}/guests/{token}/send-extend-offer")
async def send_extend_stay_offer(
    property_id: str,
    token: str,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Send extend stay offer to a guest.
    
    Only works if there's no next booking.
    """
    from app.services.operator.stay_journey_service import get_canonical_proactive_preview_by_token

    preview = await get_canonical_proactive_preview_by_token(
        db,
        token,
        allowed_touch_types={"extend_offer"},
    )

    if not preview:
        raise HTTPException(
            status_code=400,
            detail="Cannot send offer - no canonical extend-offer touch is currently due"
        )
    
    # TODO: Actually send the message via SMS/notification
    
    return {
        "status": "success",
        "message": "Extend stay offer sent",
        "offer_text": preview["message"],
    }


# =============================================================================
# Analytics
# =============================================================================

@router.get("/properties/{property_id}/analytics")
async def get_property_analytics(
    property_id: str,
    period: str = "30d",  # 7d, 30d, 90d, ytd
    db: AsyncSession = Depends(get_async_session),
):
    """
    Get concierge analytics for a property.
    
    - Total conversations
    - Most asked questions
    - Extend stay conversion rate
    - Guest satisfaction (from feedback)
    """
    # TODO: Pull from database
    
    return {
        "property_id": property_id,
        "period": period,
        "metrics": {
            "total_guests": 0,
            "total_conversations": 0,
            "avg_conversations_per_guest": 0,
            "most_common_questions": [
                {"question": "WiFi password", "count": 0},
                {"question": "Restaurant recommendations", "count": 0},
                {"question": "Beach conditions", "count": 0},
            ],
            "extend_stay": {
                "offers_sent": 0,
                "accepted": 0,
                "conversion_rate": 0,
                "revenue_generated": 0,
            },
            "satisfaction": {
                "avg_rating": 0,
                "would_recommend_pct": 0,
                "responses": 0,
            },
        },
    }
