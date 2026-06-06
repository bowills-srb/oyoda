"""
Projections API - Refactored to use Orchestration Layer.

This endpoint demonstrates the new architecture:
- API validates input
- API calls ONE orchestrator
- Orchestrator coordinates the pipeline
- Domain layer computes
- API returns response

NO direct service calls. NO scattered logic.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict

# Import from orchestration layer (single entry point)
from app.services.orchestration import (
    IntelligenceOrchestrator,
    IntelligenceContext,
    IntelligenceType,
    get_orchestrator,
    # Payloads (re-exported from execution)
    PropertyPayload,
    MarketPayload,
    CompSetPayload,
    OperatorPayload,
)

# Domain types for response building
from app.domain.signals import ConfidenceTier


router = APIRouter(prefix="/projections", tags=["projections"])


# =============================================================================
# REQUEST SCHEMAS
# =============================================================================

class ProjectionRequest(BaseModel):
    """Request for revenue projection."""
    
    # Property details
    bedrooms: int = Field(..., ge=1, le=20)
    bathrooms: float = Field(..., ge=1, le=20)
    property_type: str = "single_family"
    sqft: Optional[int] = Field(None, ge=100)
    
    # Amenities (using domain amenity types)
    amenities: List[str] = Field(
        default_factory=list,
        description="Amenity codes: pool, hot_tub, gulf_view, bay_view, lake_view, waterfront, pet_friendly, ev_charger"
    )
    
    # New listing handling
    is_new_listing: bool = False
    months_active: int = Field(default=12, ge=0)
    
    # Market context
    market_id: str = Field(..., description="Market identifier")
    market_name: Optional[str] = None
    market_type: str = Field(default="coastal", description="coastal, urban, mountain, rural")
    
    # Market data (typically from database, here from request for demo)
    median_adr_by_bedroom: Dict[int, float] = Field(
        default_factory=dict,
        description="Median ADR by bedroom count in this market"
    )
    median_occupancy_by_bedroom: Dict[int, float] = Field(
        default_factory=dict,
        description="Median occupancy by bedroom count in this market"
    )
    
    # Optional: Comparable data
    internal_comp_count: Optional[int] = None
    internal_comp_avg_adr: Optional[float] = None
    internal_comp_avg_occupancy: Optional[float] = None
    internal_comp_similarity: Optional[float] = None
    
    # Optional: Operator data
    operator_portfolio_adr: Optional[float] = None
    operator_portfolio_occupancy: Optional[float] = None
    operator_market_adr: Optional[float] = None
    operator_market_occupancy: Optional[float] = None
    operator_property_count: Optional[int] = None
    
    # Commission
    commission_rate: float = Field(default=0.20, ge=0.0, le=0.50)
    
    # Policy
    policy_name: Optional[str] = Field(
        default="high_confidence_pricing",
        description="Governance policy to apply"
    )
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "bedrooms": 4,
                "bathrooms": 3.5,
                "property_type": "single_family",
                "sqft": 2800,
                "amenities": ["pool", "gulf_view"],
                "is_new_listing": False,
                "months_active": 12,
                "market_id": "30a-beaches",
                "market_name": "30A Beaches",
                "market_type": "coastal",
                "median_adr_by_bedroom": {3: 450, 4: 650, 5: 850},
                "median_occupancy_by_bedroom": {3: 0.55, 4: 0.52, 5: 0.48},
                "commission_rate": 0.20,
                "policy_name": "high_confidence_pricing"
            },
        },
    )


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================

class MonthlyBreakdown(BaseModel):
    """Monthly projection breakdown."""
    month: int
    adr: float
    occupancy: float
    nights_booked: int
    gross_revenue: float
    net_revenue: float


class ProjectionReasoning(BaseModel):
    """Explanation of how projection was computed."""
    base_adr_source: str
    base_occupancy_source: str
    amenity_uplifts: Dict[str, float]
    seasonality_applied: bool
    operator_delta_applied: bool
    new_listing_penalty_applied: bool
    confidence_factors: Dict[str, float]


class ProjectionResponse(BaseModel):
    """Complete projection response."""
    
    # Identification
    projection_id: str
    generated_at: datetime
    
    # Annual totals
    projected_annual_revenue: float
    projected_net_revenue: float
    
    # Revenue range (low/expected/high)
    revenue_range: Dict[str, float]
    
    # Key metrics
    average_adr: float
    average_occupancy: float
    projected_nights_booked: int
    
    # Monthly breakdown
    monthly_breakdown: List[MonthlyBreakdown]
    
    # Confidence
    confidence: float
    confidence_tier: str
    
    # Gating
    is_gated: bool
    gate_reason: Optional[str]
    allowed_outputs: List[str]
    
    # Policy decision
    policy_applied: str
    policy_decision: str
    
    # Reasoning (for transparency)
    reasoning: ProjectionReasoning
    
    # Execution metadata
    execution_time_ms: float
    engine_version: str


# =============================================================================
# ENDPOINT
# =============================================================================

@router.post(
    "/generate",
    response_model=ProjectionResponse,
    summary="Generate Revenue Projection",
    description="""
    Generate a revenue projection using the refactored architecture.
    
    **Architecture Flow:**
    1. API validates request
    2. API calls IntelligenceOrchestrator
    3. Orchestrator coordinates: signals → projection → policy
    4. Domain layer computes (pure functions)
    5. API formats and returns response
    
    **Confidence Tiers:**
    - HIGH (≥0.75): Full automation allowed
    - MEDIUM (0.50-0.74): Human review recommended
    - LOW (0.25-0.49): Manual validation required
    - INSUFFICIENT (<0.25): Output gated
    
    **Governance:**
    - Policy evaluation determines allowed outputs
    - Audit trail captured for every decision
    """
)
async def generate_projection(
    request: ProjectionRequest,
    tenant_id: UUID = Query(default_factory=uuid4, description="Tenant ID"),
) -> ProjectionResponse:
    """Generate revenue projection through orchestration layer."""
    
    # Get the orchestrator (single entry point)
    orchestrator = get_orchestrator()
    
    # Build context for this request
    context = IntelligenceContext(
        request_id=str(uuid4()),
        tenant_id=tenant_id,
        intelligence_type=IntelligenceType.PROJECTION,
        geo_id=request.market_id,
        policy_name=request.policy_name,
    )
    
    # Build property payload (DTO for execution layer)
    property_payload = PropertyPayload(
        bedrooms=request.bedrooms,
        bathrooms=request.bathrooms,
        property_type=request.property_type,
        sqft=request.sqft,
        amenities=request.amenities,
        is_new_listing=request.is_new_listing,
        months_active=request.months_active,
    )
    
    # Build market payload
    market_payload = MarketPayload(
        market_id=request.market_id,
        market_name=request.market_name or request.market_id,
        market_type=request.market_type,
        median_adr_by_bedroom=request.median_adr_by_bedroom,
        median_occupancy_by_bedroom=request.median_occupancy_by_bedroom,
    )
    
    # Build optional comp set payload
    internal_comps = None
    if request.internal_comp_count and request.internal_comp_avg_adr:
        internal_comps = CompSetPayload(
            source="internal",
            comp_count=request.internal_comp_count,
            avg_adr=request.internal_comp_avg_adr,
            avg_occupancy=request.internal_comp_avg_occupancy or 0.50,
            avg_similarity_score=request.internal_comp_similarity or 0.80,
            data_coverage_pct=0.80,
        )
    
    # Build optional operator payload
    operator_payload = None
    if request.operator_portfolio_adr and request.operator_market_adr:
        operator_payload = OperatorPayload(
            company_id=str(tenant_id),
            portfolio_avg_adr=request.operator_portfolio_adr,
            portfolio_avg_occupancy=request.operator_portfolio_occupancy or 0.50,
            market_avg_adr=request.operator_market_adr,
            market_avg_occupancy=request.operator_market_occupancy or 0.50,
            property_count=request.operator_property_count or 10,
            months_of_data=12,
        )
    
    # === THIS IS THE KEY CHANGE ===
    # One call to orchestrator. It handles everything.
    result = orchestrator.run_full_intelligence(
        context=context,
        property_payload=property_payload,
        market_payload=market_payload,
        internal_comps=internal_comps,
        operator_payload=operator_payload,
        commission_rate=request.commission_rate,
        policy_name=request.policy_name,
    )
    
    # Handle failure
    if not result.success:
        raise HTTPException(
            status_code=500,
            detail=f"Projection failed: {result.context.errors}"
        )
    
    # Extract projection from result
    projection = result.output
    
    # Build monthly breakdown from projection
    monthly_breakdown = []
    for mp in projection.monthly_projections:
        # Calculate nights booked from occupancy
        days_in_month = 30  # Simplification
        nights_booked = int(mp.projected_occupancy * days_in_month)
        net_revenue = mp.projected_revenue * (1 - projection.commission_rate)
        
        monthly_breakdown.append(MonthlyBreakdown(
            month=mp.month,
            adr=mp.avg_nightly_rate,
            occupancy=mp.projected_occupancy,
            nights_booked=nights_booked,
            gross_revenue=mp.projected_revenue,
            net_revenue=net_revenue,
        ))
    
    # Build reasoning from projection
    reasoning_data = projection.reasoning
    
    # Convert uplifts to dict
    amenity_uplifts_dict = {u.name: u.factor for u in reasoning_data.uplifts_applied}
    
    reasoning = ProjectionReasoning(
        base_adr_source=reasoning_data.base_adr_source,
        base_occupancy_source=reasoning_data.seasonality_source,  # Use seasonality source
        amenity_uplifts=amenity_uplifts_dict,
        seasonality_applied=reasoning_data.seasonality_profile is not None,
        operator_delta_applied=reasoning_data.operator_delta is not None,
        new_listing_penalty_applied=reasoning_data.new_listing_adjustment is not None,
        confidence_factors=reasoning_data.confidence_factors,
    )
    
    # Get policy decision info
    policy_decision = result.context.policy_decision
    policy_decision_str = "allowed" if policy_decision and policy_decision.is_allowed() else "denied"
    
    # Build response
    # Calculate total nights booked
    total_nights = sum(mb.nights_booked for mb in monthly_breakdown)
    
    # Calculate revenue range (± 15% for now)
    revenue_low = projection.projected_annual_revenue * 0.85
    revenue_high = projection.projected_annual_revenue * 1.15
    
    return ProjectionResponse(
        projection_id=context.request_id,
        generated_at=datetime.now(timezone.utc),
        
        # Annual totals
        projected_annual_revenue=projection.projected_annual_revenue,
        projected_net_revenue=projection.projected_net_to_owner,
        
        # Range
        revenue_range={
            "low": revenue_low,
            "expected": projection.projected_annual_revenue,
            "high": revenue_high,
        },
        
        # Key metrics
        average_adr=projection.avg_adr,
        average_occupancy=projection.avg_occupancy,
        projected_nights_booked=total_nights,
        
        # Monthly
        monthly_breakdown=monthly_breakdown,
        
        # Confidence
        confidence=result.confidence,
        confidence_tier=result.confidence_tier.value,
        
        # Gating
        is_gated=result.is_gated,
        gate_reason=result.gate_reason,
        allowed_outputs=[o.value for o in result.allowed_outputs],
        
        # Policy
        policy_applied=request.policy_name or "high_confidence_pricing",
        policy_decision=policy_decision_str,
        
        # Reasoning
        reasoning=reasoning,
        
        # Metadata
        execution_time_ms=result.context.duration_ms,
        engine_version=reasoning_data.engine_version,
    )


# =============================================================================
# SIMPLE PROJECTION (MINIMAL INPUT)
# =============================================================================

@router.post(
    "/quick",
    response_model=ProjectionResponse,
    summary="Quick Projection (Minimal Input)",
    description="Generate projection with minimal input. Uses market defaults."
)
async def quick_projection(
    bedrooms: int = Query(..., ge=1, le=20),
    bathrooms: float = Query(..., ge=1, le=20),
    market_id: str = Query(...),
    has_pool: bool = Query(False),
    has_view: bool = Query(False),
    tenant_id: UUID = Query(default_factory=uuid4),
) -> ProjectionResponse:
    """Quick projection with minimal inputs."""
    
    # Build amenities list
    amenities = []
    if has_pool:
        amenities.append("pool")
    if has_view:
        amenities.append("gulf_view")
    
    # Use defaults for market data
    # In production, this would query the database
    default_adr = {3: 400, 4: 550, 5: 750, 6: 950}
    default_occupancy = {3: 0.55, 4: 0.52, 5: 0.48, 6: 0.45}
    
    request = ProjectionRequest(
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        amenities=amenities,
        market_id=market_id,
        market_type="coastal",
        median_adr_by_bedroom=default_adr,
        median_occupancy_by_bedroom=default_occupancy,
    )
    
    return await generate_projection(request, tenant_id)
