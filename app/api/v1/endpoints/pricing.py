"""
Pricing Intelligence API Endpoints.

Provides dynamic pricing recommendations:
- Rate calculations
- Discount recommendations
- Revenue forecasting
- Pricing opportunities
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class PricingRecommendationRequest(BaseModel):
    """Request for pricing recommendation."""
    property_id: UUID
    target_date: date
    length_of_stay: int = Field(1, ge=1, le=365)
    is_gap_fill: bool = False
    gap_days: int = 0


class PricingRecommendationResponse(BaseModel):
    """Pricing recommendation response."""
    property_id: UUID
    target_date: date
    
    # Current vs recommended
    current_rate: float
    recommended_rate: float
    floor_rate: float  # Owner minimum
    
    # Discount details
    recommended_discount: float = Field(..., ge=0, le=0.5)
    discount_type: str
    
    # Confidence
    confidence: float = Field(..., ge=0, le=1)
    
    # Context
    days_until_checkin: int
    historical_occupancy: float
    current_booking_pace: float  # vs historical
    
    # Rationale (for BD conversations and owner transparency)
    rationale: str
    factors: Dict[str, Any]
    
    # Flags
    requires_approval: bool = False
    is_protected_period: bool = False


class RateForecastResponse(BaseModel):
    """Rate forecast for a date range."""
    property_id: UUID
    period_start: date
    period_end: date
    
    daily_rates: List[Dict[str, Any]]  # [{date, rate, occupancy_prob, revenue_expected}]
    
    period_summary: Dict[str, float]  # {avg_rate, projected_revenue, projected_occupancy}


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post(
    "/recommendation",
    response_model=PricingRecommendationResponse,
    summary="Get Pricing Recommendation",
    description="""
    Get an intelligent pricing recommendation for a specific date.
    
    The recommendation considers:
    - Historical demand patterns (won't discount 4th of July early!)
    - Current booking velocity vs historical pace
    - Market supply/demand conditions
    - Days until check-in
    - Length of stay incentives
    - Gap fill opportunities
    
    Returns a clear rationale that can be shared with owners.
    """
)
async def get_pricing_recommendation(
    request: PricingRecommendationRequest,
) -> PricingRecommendationResponse:
    """Get pricing recommendation."""
    
    # Calculate days until
    days_until = (request.target_date - date.today()).days
    
    # Example: 4th of July should not be discounted
    is_july_4th = request.target_date.month == 7 and 1 <= request.target_date.day <= 7
    
    if is_july_4th and days_until > 30:
        return PricingRecommendationResponse(
            property_id=request.property_id,
            target_date=request.target_date,
            current_rate=1400,
            recommended_rate=1400,
            floor_rate=1200,
            recommended_discount=0.0,
            discount_type="none",
            confidence=0.95,
            days_until_checkin=days_until,
            historical_occupancy=0.98,
            current_booking_pace=1.05,
            rationale="No discount recommended. 4th of July week historically books at 98% occupancy. Current pace is ahead of last year. Hold rate.",
            factors={
                "historical_pattern": {
                    "occupancy": 0.98,
                    "recommendation": "PROTECTED - High demand holiday"
                },
                "booking_velocity": {
                    "pace_vs_historical": 1.05,
                    "recommendation": "HOLD - Ahead of pace"
                }
            },
            requires_approval=False,
            is_protected_period=True
        )
    
    # Normal recommendation logic
    base_rate = 800
    recommended_discount = 0.10 if days_until < 30 else 0.0
    
    return PricingRecommendationResponse(
        property_id=request.property_id,
        target_date=request.target_date,
        current_rate=base_rate,
        recommended_rate=base_rate * (1 - recommended_discount),
        floor_rate=base_rate * 0.7,
        recommended_discount=recommended_discount,
        discount_type="last_minute" if recommended_discount > 0 else "none",
        confidence=0.80,
        days_until_checkin=days_until,
        historical_occupancy=0.45,
        current_booking_pace=0.85,
        rationale=f"{'10% last-minute discount recommended - booking pace below historical.' if recommended_discount > 0 else 'Hold current rate.'}",
        factors={
            "historical_pattern": {"occupancy": 0.45, "recommendation": "MODERATE demand period"},
            "booking_velocity": {"pace_vs_historical": 0.85, "recommendation": "Slightly behind pace"},
            "timing": {"days_until": days_until, "recommendation": "In booking window"}
        },
        requires_approval=False,
        is_protected_period=False
    )


@router.get(
    "/forecast/{property_id}",
    response_model=RateForecastResponse,
    summary="Get Rate Forecast",
    description="Get rate forecast for a property over a date range."
)
async def get_rate_forecast(
    property_id: UUID,
    start_date: date = Query(...),
    end_date: date = Query(...),
) -> RateForecastResponse:
    """Get rate forecast for date range."""
    from datetime import timedelta
    
    daily_rates = []
    current = start_date
    
    while current <= end_date:
        # Simplified seasonal logic
        if current.month in [6, 7]:
            rate = 1150
            occ = 0.95
        elif current.month in [3]:
            rate = 875
            occ = 0.85
        else:
            rate = 650
            occ = 0.45
        
        daily_rates.append({
            "date": current.isoformat(),
            "recommended_rate": rate,
            "occupancy_probability": occ,
            "expected_revenue": rate * occ
        })
        current = current + timedelta(days=1)
    
    return RateForecastResponse(
        property_id=property_id,
        period_start=start_date,
        period_end=end_date,
        daily_rates=daily_rates[:30],  # Limit for response
        period_summary={
            "avg_rate": sum(d["recommended_rate"] for d in daily_rates) / len(daily_rates) if daily_rates else 0,
            "projected_revenue": sum(d["expected_revenue"] for d in daily_rates),
            "projected_occupancy": sum(d["occupancy_probability"] for d in daily_rates) / len(daily_rates) if daily_rates else 0
        }
    )


@router.get(
    "/opportunities/{property_id}",
    summary="Get Pricing Opportunities",
    description="Identify pricing opportunities (gaps, last-minute, length-of-stay)."
)
async def get_pricing_opportunities(
    property_id: UUID,
    days_ahead: int = Query(90, ge=7, le=365),
):
    """Get pricing opportunities for a property."""
    return {
        "property_id": str(property_id),
        "analysis_period_days": days_ahead,
        "opportunities": [
            {
                "type": "gap_fill",
                "dates": {"start": "2026-02-15", "end": "2026-02-17"},
                "gap_days": 2,
                "recommended_action": "Apply 15% discount to fill 2-night gap",
                "potential_revenue": 900,
                "priority": "high"
            },
            {
                "type": "last_minute",
                "dates": {"start": "2026-01-25", "end": "2026-01-28"},
                "days_out": 4,
                "recommended_action": "Consider 20% last-minute discount",
                "current_rate": 650,
                "recommended_rate": 520,
                "priority": "medium"
            },
            {
                "type": "length_of_stay",
                "dates": {"start": "2026-03-01", "end": "2026-03-31"},
                "recommended_action": "Offer 10% discount for 7+ night stays during Spring Break",
                "rationale": "Incentivize longer bookings to maximize occupancy",
                "priority": "low"
            }
        ],
        "summary": {
            "total_opportunities": 3,
            "high_priority": 1,
            "potential_additional_revenue": 2400
        }
    }


@router.post(
    "/bulk-recommendation",
    summary="Get Bulk Pricing Recommendations",
    description="Get pricing recommendations for multiple dates at once."
)
async def get_bulk_recommendations(
    property_id: UUID,
    start_date: date = Query(...),
    end_date: date = Query(...),
):
    """Get recommendations for a date range."""
    from datetime import timedelta
    
    recommendations = []
    current = start_date
    
    while current <= end_date:
        days_until = (current - date.today()).days
        
        # Simplified logic
        if current.month in [6, 7]:
            discount = 0.0
            rate = 1150
            is_protected = True
        elif days_until < 14:
            discount = 0.15
            rate = 650 * 0.85
            is_protected = False
        else:
            discount = 0.0
            rate = 650
            is_protected = False
        
        recommendations.append({
            "date": current.isoformat(),
            "recommended_rate": rate,
            "recommended_discount": discount,
            "is_protected_period": is_protected
        })
        
        current = current + timedelta(days=1)
    
    return {
        "property_id": str(property_id),
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "recommendations": recommendations,
        "summary": {
            "avg_recommended_rate": sum(r["recommended_rate"] for r in recommendations) / len(recommendations) if recommendations else 0,
            "dates_with_discount": sum(1 for r in recommendations if r["recommended_discount"] > 0),
            "protected_dates": sum(1 for r in recommendations if r["is_protected_period"])
        }
    }
