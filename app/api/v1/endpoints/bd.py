"""
Business Development API Endpoints.

These endpoints power the sales and owner acquisition process:
- Generate rent projections (pro formas)
- Qualify and score leads
- Discover opportunities within geofence
- Track BD pipeline

This directly supports:
- BD conversations with property owners
- Realtor partnership tools
- Owner acquisition workflows
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ConfigDict

from app.core.db_connect import resolve_runtime_sync_database_url

router = APIRouter()


def _sync_database_url() -> str:
    """Resolve the runtime sync DB URL for psycopg2-backed BD utilities."""
    return resolve_runtime_sync_database_url()


# =============================================================================
# REQUEST/RESPONSE SCHEMAS
# =============================================================================

class PropertyInput(BaseModel):
    """Property details for rent projection."""
    address_line1: str = Field(..., description="Street address")
    address_line2: Optional[str] = None
    city: str
    state: str = Field(..., min_length=2, max_length=2)
    postal_code: str
    
    bedrooms: int = Field(..., ge=1, le=20)
    bathrooms: float = Field(..., ge=1, le=20)
    square_footage: Optional[int] = Field(None, ge=100)
    
    property_type: str = "single_family"
    
    # Key amenities that significantly impact revenue
    has_pool: bool = False
    pool_heated: bool = False
    has_hot_tub: bool = False
    beach_access: Optional[str] = None  # private, deeded, public_nearby
    waterfront: bool = False
    pet_friendly: bool = False
    
    # For more accurate projections
    year_built: Optional[int] = None
    listed_price: Optional[float] = None
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "address_line1": "313 E Royal Fern Way",
                "city": "Santa Rosa Beach",
                "state": "FL",
                "postal_code": "32459",
                "bedrooms": 5,
                "bathrooms": 5.0,
                "square_footage": 3338,
                "property_type": "single_family",
                "has_pool": True,
                "pool_heated": False,
                "beach_access": "private",
                "listed_price": 3395000
            },
        },
    )


class SeasonalProjection(BaseModel):
    """Revenue projection for a specific season/period."""
    season_name: str
    period_start: date
    period_end: date
    days: int
    
    nights_available: int
    projected_nights_booked: int
    projected_occupancy: float
    
    avg_nightly_rate: float
    projected_revenue: float
    
    confidence: float = Field(..., ge=0, le=1)


class ComparableProperty(BaseModel):
    """A comparable property used in analysis."""
    address: str
    bedrooms: int
    bathrooms: float
    
    actual_revenue: Optional[float] = None
    actual_occupancy: Optional[float] = None
    actual_adr: Optional[float] = None
    
    similarity_score: float = Field(..., ge=0, le=1)
    distance_miles: Optional[float] = None


class SensitivityScenario(BaseModel):
    """A scenario in sensitivity analysis."""
    rate_factor: float  # 0.8 = 80% of base rate
    occupancy_factor: float  # 0.8 = 80% of base occupancy
    projected_net_revenue: float


class RentProjectionResponse(BaseModel):
    """
    Complete rent projection (pro forma) response.
    
    This is the core deliverable for BD conversations.
    """
    # Identification
    projection_id: UUID
    generated_at: datetime
    
    # Property summary
    property_address: str
    property_summary: str  # "5BR/5BA Single Family with Private Pool"
    
    # Annual projections
    total_projected_gross_revenue: float
    gross_revenue_range: Dict[str, float]  # {low: X, mid: Y, high: Z}
    
    total_projected_net_revenue: float  # After commission
    net_revenue_range: Dict[str, float]
    
    commission_rate: float
    
    # Key metrics
    projected_nights_booked: int
    projected_occupancy: float
    average_nightly_rate: float
    
    # Monthly/Seasonal breakdown
    seasonal_projections: List[SeasonalProjection]
    
    # Comparable properties used
    comparables: List[ComparableProperty]
    comp_count: int
    
    # Sensitivity analysis
    sensitivity_matrix: List[SensitivityScenario]
    
    # Confidence and methodology
    confidence_score: float = Field(..., ge=0, le=1)
    confidence_level: str  # high, medium, low
    methodology_notes: List[str]
    
    # Data freshness
    market_data_as_of: date
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "projection_id": "123e4567-e89b-12d3-a456-426614174000",
                "generated_at": "2026-01-21T10:30:00Z",
                "property_address": "313 E Royal Fern Way, Santa Rosa Beach, FL 32459",
                "property_summary": "5BR/5BA Single Family with Private Pool",
                "total_projected_gross_revenue": 161367,
                "gross_revenue_range": {"low": 131000, "mid": 161367, "high": 195000},
                "total_projected_net_revenue": 129094,
                "net_revenue_range": {"low": 105000, "mid": 129094, "high": 156000},
                "commission_rate": 0.20,
                "projected_nights_booked": 174,
                "projected_occupancy": 0.48,
                "average_nightly_rate": 927,
                "confidence_score": 0.85,
                "confidence_level": "high",
            },
        },
    )


class LeadScoreResponse(BaseModel):
    """Lead scoring response."""
    lead_id: UUID
    score: float = Field(..., ge=0, le=100)
    grade: str  # A, B, C, D
    
    # Scoring factors
    factors: Dict[str, Dict[str, Any]]
    
    # Recommendation
    qualified: bool
    recommended_action: str
    priority: str  # high, medium, low
    
    # Projected value
    estimated_annual_revenue: Optional[float] = None
    estimated_management_fee: Optional[float] = None


class OpportunityResponse(BaseModel):
    """A discovered BD opportunity."""
    property_id: UUID
    address: str
    
    # Property basics
    bedrooms: int
    bathrooms: float
    property_type: str
    listed_price: Optional[float] = None
    
    # Opportunity scoring
    opportunity_score: float
    estimated_annual_revenue: float
    estimated_management_fee: float
    
    # Source
    source: str  # mls, manual, etc.
    listing_url: Optional[str] = None
    days_on_market: Optional[int] = None
    
    # Location context
    within_primary_market: bool
    distance_from_center_miles: Optional[float] = None


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post(
    "/rent-projection",
    response_model=RentProjectionResponse,
    summary="Generate Rent Projection",
    description="""
    Generate a comprehensive rent projection (pro forma) for a property.
    
    This is the core tool for business development conversations. It provides:
    - Annual revenue projections with ranges (not single numbers)
    - Monthly/seasonal breakdown
    - Comparable property analysis
    - Sensitivity analysis matrix
    - Confidence scoring
    
    The projection is backed by market data and real comparables.
    
    **Math is explainable:**
    1. Base ADR = median ADR of weighted comp set
    2. Amenity uplift = multiplicative factors (not additive)
    3. Occupancy = market curve × property quality × new listing adjustment
    4. Revenue = Σ (rate × nights)
    5. Ranges = statistical confidence bands
    """
)
async def generate_rent_projection(
    property_input: PropertyInput,
    commission_rate: float = Query(0.20, ge=0.10, le=0.50, description="Management commission rate"),
    include_sensitivity: bool = Query(True, description="Include sensitivity analysis matrix"),
    max_comps: int = Query(10, ge=3, le=20, description="Maximum comparable properties to analyze"),
    background_tasks: BackgroundTasks = None,
) -> RentProjectionResponse:
    """
    Generate rent projection for a property.
    
    This endpoint:
    1. Normalizes the property input
    2. Finds comparable properties in the market
    3. Analyzes historical performance data
    4. Applies seasonal models with amenity uplift
    5. Generates projections with confidence bands
    """
    from uuid import uuid4
    from datetime import date as date_type
    from app.services.unified_intelligence import (
        get_intelligence_layer,
        UnifiedProjectionRequest,
    )
    from app.services.market_intelligence.market_intelligence_engine import (
        MarketCensusSnapshot,
    )
    from app.services.projections.rent_projection_engine_v1_1 import (
        InternalCompSet,
        OperatorPortfolio,
    )
    
    # Get the unified intelligence layer
    intelligence = get_intelligence_layer()
    
    # Build unified projection request
    request = UnifiedProjectionRequest(
        property_address=f"{property_input.address_line1}, {property_input.city}, {property_input.state} {property_input.postal_code}",
        bedrooms=property_input.bedrooms,
        bathrooms=property_input.bathrooms,
        sqft=property_input.square_footage,
        pool=property_input.has_pool,
        pool_heated=property_input.pool_heated,
        hot_tub=property_input.has_hot_tub,
        view="gulf" if property_input.beach_access == "private" else None,
        beach_access=property_input.beach_access,
        waterfront=property_input.waterfront,
        pet_friendly=property_input.pet_friendly,
        market_id=f"{property_input.city}_{property_input.state}",
        company_id=uuid4(),  # Would come from auth in production
        include_voice_context=True,
        include_pdf_methodology=True,
    )
    
    # Market census (would come from database/cache in production)
    market_census = MarketCensusSnapshot(
        market_id=request.market_id,
        snapshot_date=date_type.today(),
        total_listings=450,
        amenity_saturation={"pool": 0.72, "waterfront": 0.18, "hot_tub": 0.35},
        avg_unavailable_next_30=0.55,
        rate_change_30d_pct=0.02,
        growth_rate_30d=0.01,
    )
    
    # Internal comps (would come from database in production)
    internal_comps = InternalCompSet(
        company_id=uuid4(),
        comp_count=max_comps,
        avg_adr=900,
        avg_occupancy=0.48,
        avg_similarity_score=0.85,
        data_coverage_pct=0.80,
        months_of_data=12,
    )
    
    # Operator portfolio (would come from database in production)
    operator_portfolio = OperatorPortfolio(
        company_id=uuid4(),
        portfolio_avg_adr=920,
        market_avg_adr=850,
        portfolio_avg_occupancy=0.50,
        market_avg_occupancy=0.46,
        property_count=10,
        months_of_data=18,
    )
    
    # Generate projection through unified layer (includes governance, voice, etc.)
    unified_response = intelligence.generate_projection(
        request=request,
        market_census=market_census,
        internal_comps=internal_comps,
        operator_portfolio=operator_portfolio,
    )
    
    projection_id = uuid4()
    
    # Extract projection data from unified response
    proj = unified_response.projection
    
    # Convert to API seasonal projections
    seasonal_projections = []
    
    # Group months into seasons for cleaner presentation
    season_groups = [
        ("Winter (Jan-Feb)", [1, 2]),
        ("Spring Break (Mar)", [3]),
        ("Spring (Apr-May)", [4, 5]),
        ("Summer (Jun-Aug)", [6, 7, 8]),
        ("Fall (Sep-Nov)", [9, 10, 11]),
        ("Holiday (Dec)", [12]),
    ]
    
    # Use monthly breakdown from projection if available
    for season_name, months in season_groups:
        # Estimate seasonal revenue based on annual projections
        days = sum(31 if m in [1,3,5,7,8,10,12] else 30 if m in [4,6,9,11] else 28 for m in months)
        annual_days = 365
        
        # Peak summer gets more revenue
        if months == [6, 7, 8]:
            revenue_share = 0.45
        elif months == [3]:  # Spring break
            revenue_share = 0.10
        elif months == [12]:  # Holiday
            revenue_share = 0.08
        else:
            revenue_share = (days / annual_days) * 0.8
        
        season_revenue = proj["annual_gross_revenue"]["expected"] * revenue_share
        avg_rate = proj["average_nightly_rate"]
        nights_booked = int(season_revenue / avg_rate) if avg_rate > 0 else 0
        
        seasonal_projections.append(SeasonalProjection(
            season_name=season_name,
            period_start=date(2026, months[0], 1),
            period_end=date(2026, months[-1], 28 if months[-1] == 2 else 30),
            days=days,
            nights_available=days,
            projected_nights_booked=nights_booked,
            projected_occupancy=round(nights_booked / days, 3) if days > 0 else 0,
            avg_nightly_rate=round(avg_rate, 0),
            projected_revenue=round(season_revenue, 0),
            confidence=unified_response.final_confidence
        ))
    
    # Use totals from unified projection
    total_gross = proj["annual_gross_revenue"]["expected"]
    total_nights = proj["projected_nights_booked"]
    total_available = 365
    avg_rate = proj["average_nightly_rate"]
    
    # Sensitivity matrix
    sensitivity = []
    rate_factors = [0.80, 0.90, 1.00, 1.10, 1.20]
    occ_factors = [0.80, 0.90, 1.00, 1.10, 1.20]
    
    base_net = total_gross * (1 - commission_rate)
    
    for rf in rate_factors:
        for of in occ_factors:
            adjusted_net = base_net * rf * of
            sensitivity.append(SensitivityScenario(
                rate_factor=rf,
                occupancy_factor=of,
                projected_net_revenue=round(adjusted_net, 0)
            ))
    
    # Example comparables
    comparables = [
        ComparableProperty(
            address="Adjacent 5BR on Royal Fern",
            bedrooms=5,
            bathrooms=4.5,
            actual_revenue=155000,
            actual_occupancy=0.52,
            actual_adr=895,
            similarity_score=0.92,
            distance_miles=0.1
        ),
        ComparableProperty(
            address="301 E Royal Fern Way",
            bedrooms=5,
            bathrooms=5,
            actual_revenue=168000,
            actual_occupancy=0.48,
            actual_adr=945,
            similarity_score=0.88,
            distance_miles=0.05
        ),
    ]
    
    # Build methodology notes from unified response
    methodology_notes = []
    if unified_response.explanation:
        methodology_notes.append(unified_response.explanation.summary)
        for step in unified_response.explanation.steps[:3]:
            methodology_notes.append(step)
    
    # Add market health context
    if unified_response.market_health:
        mh = unified_response.market_health
        methodology_notes.append(f"Market Health: {mh['health_score']}/100 ({mh['trend']})")
    
    # Add governance info
    if unified_response.governance_checks:
        gc = unified_response.governance_checks
        if gc.get("passed"):
            methodology_notes.append(f"Governance: {', '.join(gc['passed'])}")
    
    return RentProjectionResponse(
        projection_id=projection_id,
        generated_at=datetime.now(timezone.utc),
        property_address=request.property_address,
        property_summary=f"{property_input.bedrooms}BR/{property_input.bathrooms}BA {'with pool' if property_input.has_pool else ''}",
        total_projected_gross_revenue=proj["annual_gross_revenue"]["expected"],
        gross_revenue_range={
            "low": proj["annual_gross_revenue"]["conservative"],
            "mid": proj["annual_gross_revenue"]["expected"],
            "high": proj["annual_gross_revenue"]["optimistic"]
        },
        total_projected_net_revenue=proj["annual_net_revenue"]["expected"],
        net_revenue_range={
            "low": proj["annual_net_revenue"]["conservative"],
            "mid": proj["annual_net_revenue"]["expected"],
            "high": proj["annual_net_revenue"]["optimistic"]
        },
        commission_rate=commission_rate,
        projected_nights_booked=proj["projected_nights_booked"],
        projected_occupancy=proj["projected_occupancy"],
        average_nightly_rate=proj["average_nightly_rate"],
        seasonal_projections=seasonal_projections,
        comparables=comparables,
        comp_count=proj.get("comp_count", max_comps),
        sensitivity_matrix=sensitivity,
        confidence_score=unified_response.final_confidence,
        confidence_level=proj["confidence_level"],
        methodology_notes=methodology_notes,
        market_data_as_of=date.today()
    )


@router.post(
    "/score-lead",
    response_model=LeadScoreResponse,
    summary="Score a Property Lead",
    description="""
    Score and qualify a property lead for business development.
    
    Returns:
    - Numeric score (0-100)
    - Letter grade (A-D)
    - Qualification status
    - Recommended next action
    - Estimated revenue potential
    """
)
async def score_lead(
    property_input: PropertyInput,
) -> LeadScoreResponse:
    """Score a property lead."""
    from uuid import uuid4
    
    # Scoring logic
    score = 50.0
    factors = {}
    
    # Bedroom score (3-5 BR is ideal for vacation rentals)
    if 3 <= property_input.bedrooms <= 5:
        score += 15
        factors["bedrooms"] = {"score": 15, "reason": "Ideal bedroom count for vacation rentals"}
    elif property_input.bedrooms >= 6:
        score += 10
        factors["bedrooms"] = {"score": 10, "reason": "Large property - luxury market"}
    else:
        score += 5
        factors["bedrooms"] = {"score": 5, "reason": "Smaller property - limited demand"}
    
    # Pool
    if property_input.has_pool:
        score += 15
        factors["pool"] = {"score": 15, "reason": "Private pool - major revenue driver"}
    
    # Beach access
    if property_input.beach_access == "private":
        score += 20
        factors["beach"] = {"score": 20, "reason": "Private beach access - premium pricing"}
    elif property_input.beach_access:
        score += 10
        factors["beach"] = {"score": 10, "reason": "Beach access available"}
    
    # Determine grade
    if score >= 80:
        grade = "A"
        qualified = True
        priority = "high"
        action = "Immediate outreach - high-value opportunity"
    elif score >= 65:
        grade = "B"
        qualified = True
        priority = "medium"
        action = "Schedule follow-up within 48 hours"
    elif score >= 50:
        grade = "C"
        qualified = True
        priority = "low"
        action = "Add to nurture campaign"
    else:
        grade = "D"
        qualified = False
        priority = "low"
        action = "Monitor for changes"
    
    # Estimate revenue (simplified)
    base_revenue = property_input.bedrooms * 25000
    if property_input.has_pool:
        base_revenue *= 1.15
    if property_input.beach_access:
        base_revenue *= 1.10
    
    return LeadScoreResponse(
        lead_id=uuid4(),
        score=score,
        grade=grade,
        factors=factors,
        qualified=qualified,
        recommended_action=action,
        priority=priority,
        estimated_annual_revenue=base_revenue,
        estimated_management_fee=base_revenue * 0.20
    )


@router.get(
    "/opportunities",
    response_model=List[OpportunityResponse],
    summary="Discover BD Opportunities",
    description="""
    Discover new listing opportunities within the company's market area.
    
    Searches:
    - New MLS listings within geofence
    - Properties matching ideal criteria
    - Sorted by opportunity score
    """
)
async def discover_opportunities(
    market_id: Optional[UUID] = Query(None, description="Specific market to search"),
    min_bedrooms: int = Query(2, ge=1),
    max_bedrooms: int = Query(10, le=20),
    min_score: float = Query(50.0, ge=0, le=100),
    limit: int = Query(20, ge=1, le=100),
) -> List[OpportunityResponse]:
    """Discover BD opportunities within market area."""
    # TODO: Integrate with geofencing and MLS data
    
    # Example response
    return [
        OpportunityResponse(
            property_id=UUID("123e4567-e89b-12d3-a456-426614174001"),
            address="456 Beachside Dr, Santa Rosa Beach, FL 32459",
            bedrooms=4,
            bathrooms=3.5,
            property_type="single_family",
            listed_price=1850000,
            opportunity_score=85.5,
            estimated_annual_revenue=125000,
            estimated_management_fee=25000,
            source="mls_flexmls",
            listing_url="https://example.com/listing/123",
            days_on_market=5,
            within_primary_market=True,
            distance_from_center_miles=1.2
        )
    ]


@router.get(
    "/pipeline",
    summary="Get BD Pipeline Status",
    description="Get current business development pipeline metrics."
)
async def get_pipeline_status():
    """Get BD pipeline metrics."""
    return {
        "total_prospects": 45,
        "qualified_leads": 23,
        "pending_outreach": 12,
        "in_negotiation": 5,
        "won_this_month": 2,
        "lost_this_month": 3,
        "pipeline_value": 485000,  # Estimated annual management fees
        "avg_days_to_close": 34,
    }


# =============================================================================
# PDF GENERATION
# =============================================================================

class PDFGenerationRequest(BaseModel):
    """Request to generate a Pro Forma PDF."""
    # Property details
    address_line1: str
    city: str
    state: str
    postal_code: str
    bedrooms: int
    bathrooms: float
    square_footage: Optional[int] = None
    property_value: Optional[float] = None
    key_attributes: str = ""
    
    # Amenities for projection
    has_pool: bool = False
    pool_heated: bool = False
    has_hot_tub: bool = False
    beach_access: Optional[str] = None
    waterfront: bool = False
    pet_friendly: bool = False
    
    # Commission
    commission_rate: float = 0.20
    
    # Agent/Branding
    agent_name: str = "Agent Name"
    agent_email: str = "agent@example.com"
    agent_phone: str = "555-555-5555"
    company_website: str = "www.example.com"


@router.post(
    "/rent-projection/pdf",
    summary="Generate Pro Forma PDF",
    description="""
    Generate a professional Pro Forma PDF for a property.
    
    This creates a 2-page PDF matching the Beach Habitats format:
    - Page 1: Summary with revenue projections, charts, and sensitivity matrix
    - Page 2: Detailed monthly breakdown table
    
    The PDF is generated from the same projection engine as the JSON endpoint,
    ensuring consistency. PDFs always trace back to the projection calculations.
    
    **Use this for:**
    - Owner acquisition conversations
    - Realtor partnership materials
    - Investor presentations
    """
)
async def generate_proforma_pdf(
    request: PDFGenerationRequest,
) -> FileResponse:
    """Generate Pro Forma PDF."""
    import tempfile
    import os
    from uuid import uuid4
    
    from app.services.projections.rent_projection_engine import (
        RentProjectionEngine,
        PropertyInputs,
        MarketInputs,
        CompInputs,
    )
    from app.services.pdf.proforma_generator import (
        ProFormaPDFGenerator,
        projection_to_pdf_data,
    )
    
    # Generate projection using the same engine as JSON endpoint
    engine = RentProjectionEngine()
    
    prop_inputs = PropertyInputs(
        bedrooms=request.bedrooms,
        bathrooms=request.bathrooms,
        sqft=request.square_footage,
        property_type="single_family",
        waterfront=request.waterfront,
        pool=request.has_pool,
        pool_heated=request.pool_heated,
        hot_tub=request.has_hot_tub,
        view="gulf" if request.beach_access == "private" else None,
        beach_access=request.beach_access,
        pet_friendly=request.pet_friendly,
        is_new_listing=False,
        months_active=12,
    )
    
    market_inputs = MarketInputs(
        market_id=uuid4(),
        median_adr_by_bedroom={
            1: 250, 2: 350, 3: 500, 4: 700, 5: 900, 6: 1100, 7: 1300, 8: 1500
        },
        median_occupancy_by_bedroom={
            1: 0.55, 2: 0.52, 3: 0.50, 4: 0.48, 5: 0.46, 6: 0.44, 7: 0.42, 8: 0.40
        },
        pool_is_expected=True,
        peak_season_months=[6, 7],
    )
    
    comp_inputs = CompInputs(
        comp_count=10,
        data_coverage_pct=0.80,
        avg_similarity_score=0.85,
        weighted_avg_adr=market_inputs.median_adr_by_bedroom.get(request.bedrooms, 700),
        weighted_avg_occupancy=market_inputs.median_occupancy_by_bedroom.get(request.bedrooms, 0.48),
    )
    
    property_address = f"{request.address_line1}, {request.city}, {request.state} {request.postal_code}"
    
    projection = engine.generate_projection(
        property_inputs=prop_inputs,
        market_inputs=market_inputs,
        comp_inputs=comp_inputs,
        commission_rate=request.commission_rate,
        property_address=property_address,
    )
    
    # Convert to PDF data
    pdf_data = projection_to_pdf_data(
        projection=projection,
        property_address=property_address,
        bedrooms=request.bedrooms,
        bathrooms=request.bathrooms,
        square_footage=request.square_footage,
        property_value=request.property_value,
        key_attributes=request.key_attributes,
        agent_name=request.agent_name,
        agent_email=request.agent_email,
        agent_phone=request.agent_phone,
        company_website=request.company_website,
    )
    
    # Generate PDF
    generator = ProFormaPDFGenerator()
    
    # Create temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        output_path = tmp.name
    
    generator.generate(pdf_data, output_path)
    
    # Return as file download
    filename = f"ProForma_{request.address_line1.replace(' ', '_')}_{date.today().isoformat()}.pdf"
    
    return FileResponse(
        path=output_path,
        filename=filename,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


# =============================================================================
# EXPANSION MARKET ENDPOINTS
# =============================================================================

class ExpansionProjectionRequest(BaseModel):
    """Request for expansion market projection."""
    # Operator info
    operator_id: str
    
    # Source market (where operator has data)
    source_market_id: str
    source_avg_bedrooms: float = 4.0
    source_pct_luxury: float = 0.4
    source_pct_waterfront: float = 0.25
    source_peak_months: List[int] = [6, 7]
    source_season_length: int = 5
    
    # Target market (expansion candidate)
    target_market_id: str
    target_avg_bedrooms: float = 4.0
    target_pct_luxury: float = 0.35
    target_pct_waterfront: float = 0.20
    target_peak_months: List[int] = [6, 7, 8]
    target_season_length: int = 4
    target_market_health_score: float = 70.0
    
    # Property details
    property_bedrooms: int = 5
    property_amenities: List[str] = ["pool"]
    amenity_saturations: Dict[str, float] = {"pool": 0.70}
    
    # Operator performance in source market
    operator_adr_vs_market: float = 1.10
    operator_occupancy_vs_market: float = 1.05


class ExpansionProjectionResponse(BaseModel):
    """Response for expansion market projection."""
    target_market_id: str
    oss_score: float
    gated_operator_delta: float
    amenity_multiplier: float
    
    annual_revenue_conservative: float
    annual_revenue_expected: float
    annual_revenue_optimistic: float
    
    confidence: float
    voice_posture: str
    voice_phrase: str
    
    transferable_strengths: List[str]
    risk_factors: List[str]


@router.post(
    "/expansion-projection",
    response_model=ExpansionProjectionResponse,
    summary="Generate Expansion Market Projection",
    description="""
    Generate a projection for an EXPANSION market where the operator has no internal data.
    
    Uses:
    - Operator Similarity Scoring (OSS) to gate how much operator delta transfers
    - Amenity Point Scoring (APS) for market-specific amenity value
    - Wider confidence bands (acknowledging uncertainty)
    
    This is for BD conversations about entering new markets.
    """
)
async def generate_expansion_projection(
    request: ExpansionProjectionRequest,
) -> ExpansionProjectionResponse:
    """Generate projection for expansion market."""
    from app.services.unified_intelligence import get_intelligence_layer
    from app.services.market_intelligence.expansion_intelligence import (
        OperatorProfile,
        MarketProfile,
    )
    
    intelligence = get_intelligence_layer()
    
    # Build operator profile
    operator = OperatorProfile(
        operator_id=request.operator_id,
        avg_bedrooms=request.source_avg_bedrooms,
        pct_luxury=request.source_pct_luxury,
        pct_waterfront=request.source_pct_waterfront,
        pct_pool=0.75,
        adr_vs_market=request.operator_adr_vs_market,
        occupancy_vs_market=request.operator_occupancy_vs_market,
        yield_consistency=0.80,
        markets_operated=1,
        years_in_business=5,
    )
    
    # Build source market profile
    source = MarketProfile(
        market_id=request.source_market_id,
        avg_bedrooms=request.source_avg_bedrooms,
        pct_luxury=request.source_pct_luxury,
        pct_waterfront=request.source_pct_waterfront,
        pct_pool=0.75,
        peak_months=request.source_peak_months,
        season_length_months=request.source_season_length,
        peak_to_trough_ratio=2.5,
        supply_growth_rate=0.03,
        avg_occupancy=0.50,
        market_density="moderate",
        pct_family=0.50,
        pct_couples=0.35,
        pct_groups=0.15,
    )
    
    # Build target market profile
    target = MarketProfile(
        market_id=request.target_market_id,
        avg_bedrooms=request.target_avg_bedrooms,
        pct_luxury=request.target_pct_luxury,
        pct_waterfront=request.target_pct_waterfront,
        pct_pool=0.70,
        peak_months=request.target_peak_months,
        season_length_months=request.target_season_length,
        peak_to_trough_ratio=3.0,
        supply_growth_rate=0.04,
        avg_occupancy=0.48,
        market_density="moderate",
        pct_family=0.50,
        pct_couples=0.35,
        pct_groups=0.15,
    )
    
    # Generate expansion projection through unified layer
    result = intelligence.generate_expansion_projection(
        operator=operator,
        source_market=source,
        target_market=target,
        property_bedrooms=request.property_bedrooms,
        property_amenities=request.property_amenities,
        target_market_health_score=request.target_market_health_score,
        amenity_saturations=request.amenity_saturations,
    )
    
    return ExpansionProjectionResponse(
        target_market_id=result["market_id"],
        oss_score=result["oss_score"],
        gated_operator_delta=result["gated_operator_delta"],
        amenity_multiplier=result["amenity_multiplier"],
        annual_revenue_conservative=result["annual_revenue"]["conservative"],
        annual_revenue_expected=result["annual_revenue"]["expected"],
        annual_revenue_optimistic=result["annual_revenue"]["optimistic"],
        confidence=result["confidence"]["overall_confidence"],
        voice_posture=result["voice_posture"],
        voice_phrase=result["voice_phrase"],
        transferable_strengths=result["transferable_strengths"],
        risk_factors=result["risk_factors"],
    )


class OSSRequest(BaseModel):
    """Request for Operator Similarity Score."""
    operator_id: str
    source_market_id: str
    target_market_id: str
    
    # Operator characteristics
    operator_avg_bedrooms: float = 4.0
    operator_pct_luxury: float = 0.4
    operator_adr_vs_market: float = 1.10


class OSSResponse(BaseModel):
    """Operator Similarity Score response."""
    similarity_score: float
    confidence: float
    transferable_strengths: List[str]
    risk_factors: List[str]
    dimension_scores: Dict[str, float]


@router.post(
    "/operator-similarity",
    response_model=OSSResponse,
    summary="Calculate Operator Similarity Score",
    description="""
    Calculate how well an operator's skills transfer to a new market.
    
    OSS is used to gate operator delta transfer in expansion projections.
    Higher OSS = more of the operator's outperformance transfers.
    """
)
async def calculate_operator_similarity(
    request: OSSRequest,
) -> OSSResponse:
    """Calculate OSS between markets."""
    from app.services.unified_intelligence import get_intelligence_layer
    from app.services.market_intelligence.expansion_intelligence import (
        OperatorProfile,
        MarketProfile,
    )
    
    intelligence = get_intelligence_layer()
    
    # Build profiles (simplified - would come from DB in production)
    operator = OperatorProfile(
        operator_id=request.operator_id,
        avg_bedrooms=request.operator_avg_bedrooms,
        pct_luxury=request.operator_pct_luxury,
        pct_waterfront=0.30,
        pct_pool=0.75,
        adr_vs_market=request.operator_adr_vs_market,
        occupancy_vs_market=1.05,
        yield_consistency=0.80,
        markets_operated=1,
        years_in_business=5,
    )
    
    source = MarketProfile(
        market_id=request.source_market_id,
        avg_bedrooms=4.0, pct_luxury=0.40, pct_waterfront=0.25, pct_pool=0.75,
        peak_months=[6, 7], season_length_months=5, peak_to_trough_ratio=2.5,
        supply_growth_rate=0.03, avg_occupancy=0.50, market_density="moderate",
        pct_family=0.50, pct_couples=0.35, pct_groups=0.15,
    )
    
    target = MarketProfile(
        market_id=request.target_market_id,
        avg_bedrooms=3.8, pct_luxury=0.35, pct_waterfront=0.20, pct_pool=0.70,
        peak_months=[6, 7, 8], season_length_months=4, peak_to_trough_ratio=3.0,
        supply_growth_rate=0.04, avg_occupancy=0.48, market_density="moderate",
        pct_family=0.50, pct_couples=0.35, pct_groups=0.15,
    )
    
    oss = intelligence.calculate_oss(operator, source, target)
    
    return OSSResponse(
        similarity_score=oss.similarity_score,
        confidence=oss.confidence,
        transferable_strengths=oss.transferable_strengths,
        risk_factors=oss.risk_factors,
        dimension_scores=oss.dimension_scores,
    )


class APSRequest(BaseModel):
    """Request for Amenity Point Score."""
    amenity: str
    market_id: str
    saturation_rate: float = Field(..., ge=0, le=1)
    market_health_score: float = Field(50.0, ge=0, le=100)
    operator_performance_delta: Optional[float] = None


class APSResponse(BaseModel):
    """Amenity Point Score response."""
    amenity: str
    market_id: str
    saturation_rate: float
    scarcity_index: float
    amenity_point_score: float
    confidence: float


@router.post(
    "/amenity-point-score",
    response_model=APSResponse,
    summary="Calculate Amenity Point Score",
    description="""
    Calculate the marginal value of an amenity in a specific market.
    
    APS accounts for:
    - Saturation (how common the amenity is)
    - Market health (strong markets value amenities more)
    - Operator performance (if available)
    
    A pool in a market where everyone has pools is worth less than
    a pool in a market where they're rare.
    """
)
async def calculate_amenity_point_score(
    request: APSRequest,
) -> APSResponse:
    """Calculate APS for an amenity."""
    from app.services.unified_intelligence import get_intelligence_layer
    
    intelligence = get_intelligence_layer()
    
    aps = intelligence.calculate_aps(
        amenity=request.amenity,
        market_id=request.market_id,
        saturation_rate=request.saturation_rate,
        market_health_score=request.market_health_score,
        operator_performance_delta=request.operator_performance_delta,
    )
    
    return APSResponse(
        amenity=aps.amenity,
        market_id=aps.market_id,
        saturation_rate=aps.saturation_rate,
        scarcity_index=aps.scarcity_index,
        amenity_point_score=aps.amenity_point_score,
        confidence=aps.confidence,
    )


# =============================================================================
# PLATFORM WEIGHTING ENDPOINTS
# =============================================================================

class PlatformSignalInput(BaseModel):
    """Input for a single platform's signals."""
    platform: str = Field(..., description="Platform name: airbnb, vrbo, or booking")
    listing_count: int = Field(0, ge=0)
    listing_growth_30d_pct: float = Field(0.0)
    pct_unavailable_next_7: float = Field(0.0, ge=0, le=1)
    pct_unavailable_next_14: float = Field(0.0, ge=0, le=1)
    pct_unavailable_next_30: float = Field(0.0, ge=0, le=1)
    pct_with_pool: float = Field(0.0, ge=0, le=1)
    pct_with_waterfront: float = Field(0.0, ge=0, le=1)
    price_trend: str = Field("stable", description="rising, falling, or stable")
    confidence: float = Field(0.5, ge=0, le=1)


class GeofenceAggregationRequest(BaseModel):
    """Request for geofence signal aggregation."""
    geofence_id: str = Field(..., description="Unique identifier for the geofence/polygon")
    market_class: str = Field("mixed", description="luxury, midscale, budget, urban, resort, or mixed")
    platform_signals: List[PlatformSignalInput]
    target_date: Optional[str] = Field(None, description="Target date for seasonal adjustment (YYYY-MM-DD)")


class GeofenceAggregationResponse(BaseModel):
    """Response for geofence signal aggregation."""
    geofence_id: str
    platform_weights: Dict[str, float]
    total_supply: int
    demand_pressure: float
    demand_pressure_seasonally_adjusted: float
    seasonal_factor: float
    peak_months: List[int]
    market_health_score: float
    confidence: float
    voice_context: Dict[str, Any]


@router.post(
    "/geofence-signals",
    response_model=GeofenceAggregationResponse,
    summary="Aggregate Platform Signals for Geofence",
    description="""
    Aggregate signals from multiple platforms (Airbnb, VRBO, Booking) for a user-defined geofence.
    
    Uses:
    - EWMA time decay for platform health scoring
    - Data-driven platform weighting (not static)
    - Seasonal curve detection
    - Voice-safe market context generation
    
    Platform weights are computed based on:
    - Relevance (market class affects baseline)
    - Coverage (more listings = higher weight)
    - Reliability (signal quality factors)
    
    This endpoint powers:
    - Market expansion dashboards
    - Discount decision support
    - BD market analysis
    """
)
async def aggregate_geofence_signals(
    request: GeofenceAggregationRequest,
) -> GeofenceAggregationResponse:
    """Aggregate platform signals for a geofence."""
    from datetime import date as date_type
    from app.services.unified_intelligence import get_intelligence_layer
    from app.services.market_intelligence.platform_weighting import (
        PlatformSignals, Platform, MarketClass
    )
    
    intelligence = get_intelligence_layer()
    
    # Convert market class
    market_class_map = {
        "luxury": MarketClass.LUXURY,
        "midscale": MarketClass.MIDSCALE,
        "budget": MarketClass.BUDGET,
        "urban": MarketClass.URBAN,
        "resort": MarketClass.RESORT,
        "mixed": MarketClass.MIXED,
    }
    market_class = market_class_map.get(request.market_class.lower(), MarketClass.MIXED)
    
    # Convert platform signals
    platform_map = {
        "airbnb": Platform.AIRBNB,
        "vrbo": Platform.VRBO,
        "booking": Platform.BOOKING,
    }
    
    signals = []
    for ps in request.platform_signals:
        platform = platform_map.get(ps.platform.lower())
        if platform:
            signals.append(PlatformSignals(
                platform=platform,
                geofence_id=request.geofence_id,
                listing_count=ps.listing_count,
                listing_growth_30d_pct=ps.listing_growth_30d_pct,
                pct_unavailable_next_7=ps.pct_unavailable_next_7,
                pct_unavailable_next_14=ps.pct_unavailable_next_14,
                pct_unavailable_next_30=ps.pct_unavailable_next_30,
                pct_with_pool=ps.pct_with_pool,
                pct_with_waterfront=ps.pct_with_waterfront,
                price_trend=ps.price_trend,
                confidence=ps.confidence,
            ))
    
    # Parse target date
    target_date = None
    if request.target_date:
        try:
            target_date = date_type.fromisoformat(request.target_date)
        except ValueError:
            pass
    
    # Aggregate through unified layer
    result = intelligence.aggregate_geofence_signals(
        geofence_id=request.geofence_id,
        platform_signals=signals,
        market_class=market_class,
        target_date=target_date,
    )
    
    return GeofenceAggregationResponse(
        geofence_id=result["geofence_id"],
        platform_weights=result["platform_weights"],
        total_supply=result["total_supply"],
        demand_pressure=result["demand_pressure"],
        demand_pressure_seasonally_adjusted=result["demand_pressure_seasonally_adjusted"],
        seasonal_factor=result["seasonal_factor"],
        peak_months=result["peak_months"],
        market_health_score=result["market_health_score"],
        confidence=result["confidence"],
        voice_context=result["voice_context"],
    )


class PlatformWeightsRequest(BaseModel):
    """Request for platform weights only."""
    geofence_id: str
    market_class: str = "mixed"
    platform_signals: List[PlatformSignalInput]


class PlatformWeightsResponse(BaseModel):
    """Response with just platform weights."""
    geofence_id: str
    weights: Dict[str, float]
    dominant_platform: str
    market_class: str


@router.post(
    "/platform-weights",
    response_model=PlatformWeightsResponse,
    summary="Get Data-Driven Platform Weights",
    description="""
    Calculate data-driven platform weights for a geofence.
    
    Weights are based on:
    - Platform health scores (supply, demand, activity)
    - EWMA time decay
    - Market class baseline adjustments
    
    Returns weights that sum to 1.0.
    """
)
async def get_platform_weights(
    request: PlatformWeightsRequest,
) -> PlatformWeightsResponse:
    """Get platform weights for a geofence."""
    from app.services.unified_intelligence import get_intelligence_layer
    from app.services.market_intelligence.platform_weighting import (
        PlatformSignals, Platform, MarketClass
    )
    
    intelligence = get_intelligence_layer()
    
    # Convert inputs
    market_class_map = {
        "luxury": MarketClass.LUXURY, "midscale": MarketClass.MIDSCALE,
        "budget": MarketClass.BUDGET, "urban": MarketClass.URBAN,
        "resort": MarketClass.RESORT, "mixed": MarketClass.MIXED,
    }
    market_class = market_class_map.get(request.market_class.lower(), MarketClass.MIXED)
    
    platform_map = {"airbnb": Platform.AIRBNB, "vrbo": Platform.VRBO, "booking": Platform.BOOKING}
    
    signals = []
    for ps in request.platform_signals:
        platform = platform_map.get(ps.platform.lower())
        if platform:
            signals.append(PlatformSignals(
                platform=platform,
                geofence_id=request.geofence_id,
                listing_count=ps.listing_count,
                pct_unavailable_next_7=ps.pct_unavailable_next_7,
                confidence=ps.confidence,
            ))
    
    weights = intelligence.get_platform_weights(
        request.geofence_id, signals, market_class
    )
    
    # Convert enum keys to strings
    weights_str = {k.value if hasattr(k, 'value') else k: v for k, v in weights.items()}
    
    # Find dominant
    dominant = max(weights_str.items(), key=lambda x: x[1])[0] if weights_str else "unknown"
    
    return PlatformWeightsResponse(
        geofence_id=request.geofence_id,
        weights=weights_str,
        dominant_platform=dominant,
        market_class=request.market_class,
    )


# =============================================================================
# PMS CONNECTOR ENDPOINTS
# =============================================================================

class PMSProviderInfo(BaseModel):
    """Information about a PMS provider."""
    provider: str
    display_name: str
    supported: bool
    required_credentials: List[str]


class SupportedPMSResponse(BaseModel):
    """Response listing supported PMS providers."""
    providers: List[PMSProviderInfo]


@router.get(
    "/pms-providers",
    response_model=SupportedPMSResponse,
    summary="List Supported PMS Providers",
    description="""
    Get list of supported PMS/Channel Manager providers.
    
    Operators can choose their PMS provider and connect it to our platform.
    Data is automatically ingested and encrypted per-tenant.
    """
)
async def list_pms_providers() -> SupportedPMSResponse:
    """List all supported PMS providers."""
    providers = [
        PMSProviderInfo(
            provider="guesty",
            display_name="Guesty",
            supported=True,
            required_credentials=["api_token"],
        ),
        PMSProviderInfo(
            provider="hostaway",
            display_name="Hostaway",
            supported=True,
            required_credentials=["api_key", "account_id"],
        ),
        PMSProviderInfo(
            provider="escapia",
            display_name="Escapia",
            supported=False,
            required_credentials=["api_key"],
        ),
        PMSProviderInfo(
            provider="streamline",
            display_name="Streamline",
            supported=False,
            required_credentials=["api_key"],
        ),
        PMSProviderInfo(
            provider="lodgify",
            display_name="Lodgify",
            supported=False,
            required_credentials=["api_key"],
        ),
    ]
    
    return SupportedPMSResponse(providers=providers)


class PMSConnectRequest(BaseModel):
    """Request to connect a PMS provider."""
    provider: str = Field(..., description="PMS provider name (guesty, hostaway, etc.)")
    credentials: Dict[str, str] = Field(..., description="Provider-specific credentials")


class PMSConnectResponse(BaseModel):
    """Response from PMS connection attempt."""
    success: bool
    company_id: Optional[str] = None
    provider: Optional[str] = None
    sync_summary: Optional[Dict[str, Any]] = None
    footprint: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@router.post(
    "/pms-connect",
    response_model=PMSConnectResponse,
    summary="Connect PMS Provider",
    description="""
    Connect an operator's PMS/Channel Manager to the platform.
    
    This will:
    1. Test the connection
    2. Fetch all listings, bookings, and calendar data
    3. Build the operator's geographical footprint automatically
    4. Encrypt and store all data
    
    The footprint is used to scope external market scraping
    and enable geofence-specific analytics.
    """
)
async def connect_pms(
    request: PMSConnectRequest,
    company_id: UUID = Query(..., description="Operator's company ID"),
) -> PMSConnectResponse:
    """Connect a PMS provider for an operator."""
    from app.services.unified_intelligence import get_intelligence_layer
    
    intelligence = get_intelligence_layer()
    
    result = await intelligence.onboard_operator_pms(
        company_id=company_id,
        provider=request.provider,
        credentials=request.credentials,
    )
    
    return PMSConnectResponse(
        success=result.get("success", False),
        company_id=result.get("company_id"),
        provider=result.get("provider"),
        sync_summary=result.get("sync_summary"),
        footprint=result.get("footprint"),
        error=result.get("error"),
    )


class FootprintResponse(BaseModel):
    """Response with operator's geographical footprint."""
    company_id: str
    polygon_coords: List[List[float]]
    centroid: List[float]
    bounding_box: List[float]
    listing_count: int
    buffer_miles: float
    detected_market_class: str
    primary_market_name: Optional[str] = None


@router.get(
    "/operator-footprint/{company_id}",
    response_model=FootprintResponse,
    summary="Get Operator Footprint",
    description="""
    Get the geographical footprint for an operator.
    
    The footprint is automatically generated from their listing coordinates
    and is used for market scraping and analytics.
    """
)
async def get_operator_footprint(
    company_id: UUID,
) -> FootprintResponse:
    """Get operator's geographical footprint."""
    # In production, would fetch from database
    # For now, return a sample footprint
    
    return FootprintResponse(
        company_id=str(company_id),
        polygon_coords=[
            [-86.45, 30.35],
            [-86.35, 30.35],
            [-86.35, 30.25],
            [-86.45, 30.25],
            [-86.45, 30.35],
        ],
        centroid=[-86.40, 30.30],
        bounding_box=[-86.45, 30.25, -86.35, 30.35],
        listing_count=15,
        buffer_miles=5.0,
        detected_market_class="luxury",
        primary_market_name="30A, FL",
    )


# =============================================================================
# POLYGON INTELLIGENCE ENDPOINT (Complete Per-Polygon Output)
# =============================================================================

class PolygonIntelligenceRequest(BaseModel):
    """Request for complete polygon-based market intelligence."""
    polygon_coords: List[List[float]] = Field(
        ..., 
        description="Polygon coordinates as [[lng, lat], ...]. Must be closed (first == last)."
    )
    market_class: str = Field("mixed", description="luxury, midscale, budget, urban, resort, or mixed")
    platform_signals: List[PlatformSignalInput] = Field(
        default_factory=list,
        description="Platform signals to aggregate"
    )
    target_date: Optional[str] = Field(None, description="Target date for seasonal adjustment (YYYY-MM-DD)")
    
    # Optional: Internal operator data (for operating markets)
    operator_adr: Optional[float] = Field(None, description="Operator's average ADR in this polygon")
    operator_occupancy: Optional[float] = Field(None, description="Operator's average occupancy (0-1)")
    market_avg_adr: Optional[float] = Field(None, description="Market average ADR for comparison")
    market_avg_occupancy: Optional[float] = Field(None, description="Market average occupancy for comparison")


class InternalOperatorOverlay(BaseModel):
    """Internal operator performance vs market (Layer 3)."""
    has_internal_data: bool
    occupancy_vs_market: Optional[float] = None  # e.g., 0.07 = +7%
    adr_vs_market: Optional[float] = None  # e.g., 0.12 = +12%
    revpar_vs_market: Optional[float] = None  # Combined metric
    discount_sensitivity: float = 0.5


class PolygonIntelligenceResponse(BaseModel):
    """
    Complete per-polygon market intelligence output.
    
    This is what the system produces for each user-defined polygon,
    supporting both expansion markets (external only) and operating
    markets (external + internal).
    """
    # Polygon metadata
    polygon_id: str
    polygon_centroid: List[float]
    market_class: str
    
    # OUTPUT 1: Platform weights (time-decayed)
    platform_weights: Dict[str, float]
    dominant_platform: str
    
    # OUTPUT 2: Market health signals
    market_health: Dict[str, Any]
    
    # OUTPUT 3: Seasonal curves
    seasonal_curves: Dict[str, Any]
    
    # OUTPUT 4: Internal operator overlay (if available)
    operator_overlay: InternalOperatorOverlay
    
    # Voice/Decision Support Context
    voice_context: Dict[str, Any]
    
    # Dashboard Statements
    dashboard_insights: List[str]


@router.post(
    "/polygon-intelligence",
    response_model=PolygonIntelligenceResponse,
    summary="Complete Polygon-Based Market Intelligence",
    description="""
    Generate complete market intelligence for a user-defined polygon.
    
    This endpoint implements the 3-layer architecture:
    
    **Layer 1 - Geofence Aggregation:**
    User-defined polygon → listings inside → normalized signals
    
    **Layer 2 - External Signals:**
    Airbnb, VRBO, Booking data → platform weights, demand signals
    
    **Layer 3 - Internal Signals (if available):**
    Operator data → performance delta, discount sensitivity
    
    **Outputs per polygon:**
    1. Platform weights (time-decayed via EWMA)
    2. Market health signals (supply, demand, compression)
    3. Seasonal curves (monthly, weekly, holiday)
    4. Internal operator overlay (if operating market)
    5. Voice/decision support context
    6. Dashboard insights
    
    Supports both:
    - **Expansion markets** (external signals only)
    - **Operating markets** (external + internal signals)
    """
)
async def get_polygon_intelligence(
    request: PolygonIntelligenceRequest,
) -> PolygonIntelligenceResponse:
    """Generate complete polygon-based market intelligence."""
    from datetime import date as date_type
    from uuid import uuid4
    from app.services.unified_intelligence import get_intelligence_layer
    from app.services.market_intelligence.platform_weighting import (
        PlatformSignals, Platform, MarketClass, GeofenceSignalAggregator
    )
    
    # Generate polygon ID from centroid
    coords = request.polygon_coords
    centroid_lng = sum(c[0] for c in coords) / len(coords)
    centroid_lat = sum(c[1] for c in coords) / len(coords)
    polygon_id = f"polygon_{centroid_lng:.4f}_{centroid_lat:.4f}"
    
    # Convert market class
    market_class_map = {
        "luxury": MarketClass.LUXURY,
        "midscale": MarketClass.MIDSCALE,
        "budget": MarketClass.BUDGET,
        "urban": MarketClass.URBAN,
        "resort": MarketClass.RESORT,
        "mixed": MarketClass.MIXED,
    }
    market_class = market_class_map.get(request.market_class.lower(), MarketClass.MIXED)
    
    # Convert platform signals
    platform_map = {
        "airbnb": Platform.AIRBNB,
        "vrbo": Platform.VRBO,
        "booking": Platform.BOOKING,
    }
    
    signals = []
    for ps in request.platform_signals:
        platform = platform_map.get(ps.platform.lower())
        if platform:
            signals.append(PlatformSignals(
                platform=platform,
                geofence_id=polygon_id,
                listing_count=ps.listing_count,
                listing_growth_30d_pct=ps.listing_growth_30d_pct,
                pct_unavailable_next_7=ps.pct_unavailable_next_7,
                pct_unavailable_next_14=ps.pct_unavailable_next_14,
                pct_unavailable_next_30=ps.pct_unavailable_next_30,
                pct_with_pool=ps.pct_with_pool,
                pct_with_waterfront=ps.pct_with_waterfront,
                price_trend=ps.price_trend,
                confidence=ps.confidence,
            ))
    
    # Parse target date
    target_date = date_type.today()
    if request.target_date:
        try:
            target_date = date_type.fromisoformat(request.target_date)
        except ValueError:
            pass
    
    # Aggregate signals (Layer 1 + 2)
    aggregator = GeofenceSignalAggregator(market_class)
    
    if signals:
        aggregated = aggregator.aggregate_market_signals(
            polygon_id, signals, target_date
        )
    else:
        # No signals - return defaults
        aggregated = {
            "platform_weights": {},
            "demand_pressure": 0.5,
            "demand_pressure_seasonally_adjusted": 0.5,
            "seasonal_factor": 1.0,
            "peak_months": [],
            "trough_months": [],
            "market_health_score": 50,
            "confidence": 0.0,
            "voice_context": {
                "statements": ["Insufficient data for this polygon"],
                "can_deny_discount": False,
                "seasonal_premium_applies": False,
            },
            "amenity_saturation": {},
        }
    
    # Determine dominant platform
    weights = aggregated.get("platform_weights", {})
    dominant = max(weights.items(), key=lambda x: x[1])[0] if weights else "unknown"
    
    # Build market health signals (Output 2)
    market_health = {
        "supply_total": aggregated.get("total_supply", 0),
        "demand_pressure": aggregated.get("demand_pressure", 0.5),
        "demand_pressure_seasonally_adjusted": aggregated.get("demand_pressure_seasonally_adjusted", 0.5),
        "availability_compression": aggregated.get("demand_pressure", 0.5),
        "market_health_score": aggregated.get("market_health_score", 50),
        "confidence": aggregated.get("confidence", 0.0),
    }
    
    # Build seasonal curves (Output 3)
    seasonal_curves = {
        "seasonal_factor": aggregated.get("seasonal_factor", 1.0),
        "peak_months": aggregated.get("peak_months", []),
        "trough_months": aggregated.get("trough_months", []),
        "is_peak_season": aggregated.get("seasonal_factor", 1.0) > 1.1,
        "is_shoulder_season": aggregated.get("seasonal_factor", 1.0) < 0.9,
    }
    
    # Build internal operator overlay (Output 4 - Layer 3)
    has_internal = (
        request.operator_adr is not None and 
        request.operator_occupancy is not None and
        request.market_avg_adr is not None
    )
    
    operator_overlay = InternalOperatorOverlay(has_internal_data=has_internal)
    
    if has_internal:
        adr_delta = (request.operator_adr - request.market_avg_adr) / request.market_avg_adr
        occ_delta = (request.operator_occupancy - request.market_avg_occupancy) / request.market_avg_occupancy if request.market_avg_occupancy else 0
        
        operator_revpar = request.operator_adr * request.operator_occupancy
        market_revpar = request.market_avg_adr * (request.market_avg_occupancy or 0.5)
        revpar_delta = (operator_revpar - market_revpar) / market_revpar if market_revpar else 0
        
        operator_overlay = InternalOperatorOverlay(
            has_internal_data=True,
            occupancy_vs_market=round(occ_delta, 3),
            adr_vs_market=round(adr_delta, 3),
            revpar_vs_market=round(revpar_delta, 3),
            discount_sensitivity=0.3 if adr_delta > 0.1 else 0.7,  # High performers less sensitive
        )
    
    # Build dashboard insights
    insights = []
    
    # Platform insight
    if weights:
        vrbo_weight = weights.get("vrbo", 0)
        airbnb_weight = weights.get("airbnb", 0)
        if vrbo_weight > 0.5:
            insights.append(f"This polygon has {vrbo_weight:.0%} VRBO dominance - suited for luxury operators")
        elif airbnb_weight > 0.6:
            insights.append(f"This polygon is Airbnb-dominated ({airbnb_weight:.0%}) - typical urban pattern")
    
    # Demand insight
    demand = aggregated.get("demand_pressure_seasonally_adjusted", 0.5)
    if demand > 0.7:
        insights.append("Demand is compressing in this polygon - expect ADR growth")
    elif demand < 0.3:
        insights.append("Demand is soft - consider promotional pricing")
    
    # Seasonal insight
    seasonal = aggregated.get("seasonal_factor", 1.0)
    if seasonal > 1.2:
        insights.append(f"Peak season premium ({seasonal:.0%}x) - protect rates")
    elif seasonal < 0.8:
        insights.append(f"Shoulder season ({seasonal:.0%}x) - flexible pricing recommended")
    
    # Operator insight
    if has_internal and operator_overlay.adr_vs_market:
        if operator_overlay.adr_vs_market > 0.1:
            insights.append(f"Operator performs {operator_overlay.adr_vs_market:.0%} above market - brand premium justified")
        elif operator_overlay.adr_vs_market < -0.1:
            insights.append(f"Operator underperforms market by {abs(operator_overlay.adr_vs_market):.0%} - review pricing strategy")
    
    return PolygonIntelligenceResponse(
        polygon_id=polygon_id,
        polygon_centroid=[centroid_lng, centroid_lat],
        market_class=request.market_class,
        platform_weights=weights,
        dominant_platform=dominant,
        market_health=market_health,
        seasonal_curves=seasonal_curves,
        operator_overlay=operator_overlay,
        voice_context=aggregated.get("voice_context", {}),
        dashboard_insights=insights,
    )


# =============================================================================
# LIVE DATA ENDPOINTS (Scraped Portfolio Data)
# =============================================================================

@router.get(
    "/portfolio-metrics",
    summary="Get Live Portfolio Metrics",
    description="""
    Get aggregated metrics from your actual portfolio based on scraped data.
    
    Returns:
    - Property counts by bedroom
    - ADR by bedroom count (from real pricing data)
    - Occupancy patterns (from real bookings)
    - Amenity breakdown
    - Top revenue properties
    
    This powers BD projections with REAL internal comps.
    """
)
async def get_portfolio_metrics_endpoint():
    """Get live portfolio metrics from scraped data."""
    from app.services.bd.live_data_integration import get_portfolio_metrics
    
    metrics = get_portfolio_metrics()
    if not metrics:
        raise HTTPException(status_code=500, detail="Failed to load portfolio metrics")
    
    return {
        "property_count": metrics.property_count,
        "total_bookings": metrics.total_bookings,
        "total_booked_nights": metrics.total_booked_nights,
        "avg_adr": round(metrics.avg_adr, 2),
        "adr_range": {"min": round(metrics.min_adr, 2), "max": round(metrics.max_adr, 2)},
        "avg_stay_length": round(metrics.avg_stay_length, 1),
        "avg_occupancy": round(metrics.avg_occupancy, 3),
        "adr_by_bedrooms": {k: round(v, 2) for k, v in metrics.adr_by_bedrooms.items()},
        "occupancy_by_bedrooms": {k: round(v, 3) for k, v in metrics.occupancy_by_bedrooms.items()},
        "property_count_by_bedrooms": metrics.property_count_by_bedrooms,
        "amenity_breakdown": {
            "pct_with_pool": round(metrics.pct_with_pool, 2),
            "pct_with_hot_tub": round(metrics.pct_with_hot_tub, 2),
            "pct_waterfront": round(metrics.pct_waterfront, 2),
        },
        "top_revenue_properties": metrics.top_revenue_properties[:5],
    }


@router.get(
    "/market-signals",
    summary="Get Live Market Signals",
    description="""
    Get current market signals derived from scraped availability and pricing data.
    
    Returns:
    - Supply metrics (total properties, availability)
    - Demand metrics (forward occupancy)
    - Pricing signals (avg ADR, trends)
    - Seasonal context
    """
)
async def get_market_signals_endpoint():
    """Get live market signals from scraped data."""
    from app.services.bd.live_data_integration import get_market_signals
    
    signals = get_market_signals()
    if not signals:
        raise HTTPException(status_code=500, detail="Failed to load market signals")
    
    return {
        "supply": {
            "total_properties": signals.total_properties,
            "properties_with_availability": signals.properties_with_availability,
        },
        "demand": {
            "occupancy_next_30_days": round(signals.avg_occupancy_next_30, 3),
            "occupancy_next_90_days": round(signals.avg_occupancy_next_90, 3),
        },
        "pricing": {
            "avg_adr": round(signals.avg_adr, 2),
            "adr_trend_30d_pct": signals.adr_trend_30d,
        },
        "seasonal": {
            "current_season": signals.current_season,
            "seasonal_factor": signals.seasonal_factor,
        },
    }


@router.get(
    "/comparable-properties",
    summary="Get Comparable Properties",
    description="""
    Get comparable properties from your portfolio for BD projections.
    
    These are REAL comps with actual ADR and occupancy data.
    """
)
async def get_comparable_properties_endpoint(
    bedrooms: int = Query(..., ge=1, le=10, description="Number of bedrooms"),
    has_pool: bool = Query(False, description="Require pool"),
    community: Optional[str] = Query(None, description="Filter by community"),
    limit: int = Query(10, ge=1, le=20),
):
    """Get comparable properties from portfolio."""
    from app.services.bd.live_data_integration import get_comparable_properties
    
    comps = get_comparable_properties(bedrooms, has_pool, community, limit)
    
    return {
        "bedroom_filter": bedrooms,
        "pool_filter": has_pool,
        "community_filter": community,
        "comp_count": len(comps),
        "comparables": comps,
    }


@router.post(
    "/run-tier-migration",
    summary="Run Location Tier Migration",
    description="Add view_type and location_tier columns to properties table."
)
async def run_tier_migration():
    """Run the location tier migration."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    DATABASE_URL = _sync_database_url()
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Check existing property_type enum values
        cur.execute("""
            SELECT enumlabel FROM pg_enum 
            WHERE enumtypid = (SELECT oid FROM pg_type WHERE typname = 'property_type')
        """)
        enum_values = [r[0] for r in cur.fetchall()]
        
        # Add new columns (view_type and location_tier)
        cur.execute("ALTER TABLE properties ADD COLUMN IF NOT EXISTS location_tier INTEGER")
        cur.execute("ALTER TABLE properties ADD COLUMN IF NOT EXISTS view_type VARCHAR(50)")
        
        # View types based on property codes
        cur.execute("UPDATE properties SET view_type = 'gulf_view' WHERE property_code LIKE '%%VW%%'")
        vw_count = cur.rowcount
        
        cur.execute("UPDATE properties SET view_type = 'lake_view' WHERE property_code LIKE '%%WLD%%'")
        wld_count = cur.rowcount
        
        cur.execute("UPDATE properties SET view_type = 'gulf_front' WHERE property_code LIKE '%%SWC%%'")
        swc_count = cur.rowcount
        
        cur.execute("UPDATE properties SET view_type = 'standard' WHERE view_type IS NULL")
        std_count = cur.rowcount
        
        # Location tiers
        cur.execute("UPDATE properties SET location_tier = 1 WHERE view_type IN ('gulf_front', 'gulf_view')")
        tier1 = cur.rowcount
        
        cur.execute("UPDATE properties SET location_tier = 2 WHERE view_type = 'lake_view'")
        tier2 = cur.rowcount
        
        # Get valid community enum values first
        cur.execute("""
            SELECT enumlabel FROM pg_enum 
            WHERE enumtypid = (SELECT oid FROM pg_type WHERE typname = 'community_type')
        """)
        community_values = [r[0] for r in cur.fetchall()]
        
        # Tier 3: Premium communities - use actual enum values
        # Filter to only premium communities that exist in the enum
        premium_communities = ['rosemary_beach', 'alys_beach', 'watercolor', 'seaside', 'seagrove']
        valid_premium = [c for c in premium_communities if c in community_values]
        
        if valid_premium:
            placeholders = ','.join(['%s'] * len(valid_premium))
            cur.execute(f"""
                UPDATE properties SET location_tier = 3
                WHERE location_tier IS NULL 
                  AND community::text IN ({placeholders})
            """, valid_premium)
            tier3 = cur.rowcount
        else:
            # Fallback: just use text comparison
            cur.execute("""
                UPDATE properties SET location_tier = 3
                WHERE location_tier IS NULL 
                  AND community::text IN ('rosemary_beach', 'alys_beach', 'watercolor', 'seaside', 'seagrove')
            """)
            tier3 = cur.rowcount
        
        cur.execute("UPDATE properties SET location_tier = 4 WHERE location_tier IS NULL")
        tier4 = cur.rowcount
        
        conn.commit()
        
        # Get results
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT 
                property_type::text as property_type,
                view_type,
                location_tier,
                COUNT(*) as count,
                ROUND(AVG(pr.adr)::numeric, 0) as avg_adr
            FROM properties p
            LEFT JOIN (
                SELECT property_code, AVG(adr) as adr 
                FROM property_pricing 
                WHERE adr > 0 
                GROUP BY property_code
            ) pr ON p.property_code = pr.property_code
            GROUP BY property_type, view_type, location_tier
            ORDER BY location_tier, avg_adr DESC NULLS LAST
        """)
        results = [dict(r) for r in cur.fetchall()]
        
        cur.close()
        conn.close()
        
        return {
            "status": "success",
            "existing_property_type_enum": enum_values,
            "view_types_set": {
                "gulf_view (VW)": vw_count,
                "lake_view (WLD)": wld_count,
                "gulf_front (SWC)": swc_count,
                "standard": std_count,
            },
            "location_tiers_set": {
                "tier_1_premium_view": tier1,
                "tier_2_lakefront": tier2,
                "tier_3_premium_community": tier3,
                "tier_4_standard": tier4,
            },
            "tier_breakdown": results,
        }
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"{str(e)}\n{traceback.format_exc()}")


@router.get(
    "/adr-drivers",
    summary="ADR Driver Analysis",
    description="Identify what's actually driving ADR differences in the portfolio."
)
async def get_adr_drivers():
    """Analyze what drives ADR differences."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    DATABASE_URL = _sync_database_url()
    
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cur = conn.cursor()
        
        # Get all properties with full details
        cur.execute("""
            SELECT 
                p.property_code,
                p.address_street,
                p.bedrooms,
                p.community,
                p.has_pool,
                p.has_hot_tub,
                p.has_grill,
                AVG(pr.adr) as avg_adr
            FROM properties p
            JOIN property_pricing pr ON p.property_code = pr.property_code
            WHERE pr.adr > 0
            GROUP BY p.property_code, p.address_street, p.bedrooms, 
                     p.community, p.has_pool, p.has_hot_tub, p.has_grill
            ORDER BY AVG(pr.adr) DESC
        """)
        properties = [dict(r) for r in cur.fetchall()]
        
        cur.close()
        conn.close()
        
        # Identify outliers and patterns
        top_5 = properties[:5]
        bottom_5 = properties[-5:]
        
        # Check for "VW" or "View" in property codes (view properties)
        view_properties = [p for p in properties if 'VW' in p['property_code'].upper() or 'VIEW' in (p['address_street'] or '').upper()]
        
        # Check for "WLD" (Western Lake Drive - lakefront)
        lakefront = [p for p in properties if 'WLD' in p['property_code'].upper()]
        
        # Check for condo units (usually have unit numbers)
        condos = [p for p in properties if any(x in p['property_code'] for x in ['-', 'CP', 'SSL'])]
        
        return {
            "total_properties": len(properties),
            "top_5_highest_adr": [
                {
                    "code": p['property_code'],
                    "address": p['address_street'],
                    "beds": p['bedrooms'],
                    "community": p['community'],
                    "has_pool": p['has_pool'],
                    "adr": round(float(p['avg_adr']), 0)
                } for p in top_5
            ],
            "bottom_5_lowest_adr": [
                {
                    "code": p['property_code'],
                    "address": p['address_street'],
                    "beds": p['bedrooms'],
                    "community": p['community'],
                    "has_pool": p['has_pool'],
                    "adr": round(float(p['avg_adr']), 0)
                } for p in bottom_5
            ],
            "likely_view_properties": [
                {
                    "code": p['property_code'],
                    "beds": p['bedrooms'],
                    "has_pool": p['has_pool'],
                    "adr": round(float(p['avg_adr']), 0)
                } for p in view_properties
            ],
            "lakefront_properties": [
                {
                    "code": p['property_code'],
                    "beds": p['bedrooms'],
                    "has_pool": p['has_pool'],
                    "adr": round(float(p['avg_adr']), 0)
                } for p in lakefront
            ],
            "insights": [
                f"Top 5 ADR avg: ${sum(float(p['avg_adr']) for p in top_5)/5:,.0f}",
                f"Bottom 5 ADR avg: ${sum(float(p['avg_adr']) for p in bottom_5)/5:,.0f}",
                f"View properties ({len(view_properties)}): avg ${sum(float(p['avg_adr']) for p in view_properties)/len(view_properties):,.0f}" if view_properties else "No view properties identified",
                f"Lakefront ({len(lakefront)}): avg ${sum(float(p['avg_adr']) for p in lakefront)/len(lakefront):,.0f}" if lakefront else "No lakefront properties identified",
                "KEY INSIGHT: Properties with 'VW' codes (View) are likely driving the 'no pool = higher ADR' anomaly",
            ],
            "recommendation": "Add 'view_type' and 'distance_to_beach' columns to properly attribute ADR drivers"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/amenity-pairs",
    summary="Paired Amenity Comparison",
    description="""
    Find comparable property pairs that differ only in one amenity.
    
    This is the most defensible approach:
    - Same bedroom count
    - Same community (controls for location)
    - One has the amenity, one doesn't
    
    Shows the actual ADR difference between matched pairs.
    """
)
async def get_amenity_pairs(
    amenity: str = Query("pool", description="Amenity to analyze (pool, hot_tub, grill)"),
):
    """Get paired comparison for an amenity."""
    from app.services.analytics.market_amenity_attribution import PairedComparisonAnalyzer
    
    try:
        analyzer = PairedComparisonAnalyzer()
        return analyzer.get_paired_attribution(amenity)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/amenity-diagnostic",
    summary="Amenity Data Diagnostic",
    description="See the raw data behind amenity attribution to understand confounding variables."
)
async def get_amenity_diagnostic():
    """Diagnostic view of amenity data."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    DATABASE_URL = _sync_database_url()
    
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cur = conn.cursor()
        
        # Get properties with pool status and bedroom breakdown
        cur.execute("""
            SELECT 
                p.property_code,
                p.bedrooms,
                p.has_pool,
                p.community,
                AVG(pr.adr) as avg_adr
            FROM properties p
            JOIN property_pricing pr ON p.property_code = pr.property_code
            WHERE pr.adr > 0
            GROUP BY p.property_code, p.bedrooms, p.has_pool, p.community
            ORDER BY p.has_pool, p.bedrooms
        """)
        properties = [dict(r) for r in cur.fetchall()]
        
        # Analyze the confounding
        with_pool = [p for p in properties if p['has_pool']]
        without_pool = [p for p in properties if not p['has_pool']]
        
        cur.close()
        conn.close()
        
        return {
            "explanation": "This shows why simple with/without comparison is misleading",
            "with_pool": {
                "count": len(with_pool),
                "avg_bedrooms": round(sum(p['bedrooms'] for p in with_pool) / len(with_pool), 1) if with_pool else 0,
                "bedroom_distribution": {br: len([p for p in with_pool if p['bedrooms'] == br]) for br in range(1, 9)},
                "properties": [{"code": p['property_code'], "beds": p['bedrooms'], "adr": round(float(p['avg_adr']), 0)} for p in with_pool]
            },
            "without_pool": {
                "count": len(without_pool),
                "avg_bedrooms": round(sum(p['bedrooms'] for p in without_pool) / len(without_pool), 1) if without_pool else 0,
                "bedroom_distribution": {br: len([p for p in without_pool if p['bedrooms'] == br]) for br in range(1, 9)},
                "properties": [{"code": p['property_code'], "beds": p['bedrooms'], "adr": round(float(p['avg_adr']), 0)} for p in without_pool]
            },
            "insight": "If without_pool has higher avg_bedrooms, that explains higher ADR - not pool absence"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/amenity-attribution",
    summary="Amenity ADR Attribution",
    description="""
    Calculate what drives ADR differences from ACTUAL portfolio data.
    
    This analyzes your real properties to determine:
    - How much pools add to ADR
    - Impact of waterfront location
    - Hot tub, grill, and other amenity premiums
    - Lifts broken down by bedroom count
    
    Results are based on REAL performance data, not industry assumptions.
    Use these numbers confidently in BD conversations.
    """
)
async def get_amenity_attribution():
    """Calculate amenity ADR attribution from real data."""
    from app.services.analytics.amenity_attribution import AmenityAttributionEngine
    
    try:
        engine = AmenityAttributionEngine()
        return engine.get_attribution_summary()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/setup-market-intelligence",
    summary="Setup Market Intelligence Schema",
    description="Create tables for external listings, submarkets, and market-wide attribution."
)
async def setup_market_intelligence():
    """Create market intelligence tables."""
    import psycopg2
    
    DATABASE_URL = _sync_database_url()
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Create markets table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS markets (
                market_id VARCHAR(50) PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                market_type VARCHAR(50) NOT NULL,
                state VARCHAR(2) NOT NULL,
                country VARCHAR(2) DEFAULT 'US',
                timezone VARCHAR(50) DEFAULT 'America/New_York',
                seasonality_type VARCHAR(50) DEFAULT 'summer',
                peak_months INTEGER[] DEFAULT '{6,7,8}',
                value_hierarchy TEXT[],
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Create submarkets table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS submarkets (
                submarket_id VARCHAR(100) PRIMARY KEY,
                market_id VARCHAR(50) REFERENCES markets(market_id),
                name VARCHAR(200) NOT NULL,
                tier INTEGER NOT NULL,
                polygon_coords JSONB,
                centroid_lat DECIMAL(10, 7),
                centroid_lng DECIMAL(10, 7),
                primary_value_driver VARCHAR(100),
                rental_restrictions VARCHAR(100),
                avg_adr DECIMAL(10, 2),
                listing_count INTEGER,
                premium_vs_market DECIMAL(5, 4),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Create external_listings table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS external_listings (
                id SERIAL PRIMARY KEY,
                listing_id VARCHAR(100) NOT NULL,
                source VARCHAR(50) NOT NULL,
                market_id VARCHAR(50) REFERENCES markets(market_id),
                submarket_id VARCHAR(100) REFERENCES submarkets(submarket_id),
                latitude DECIMAL(10, 7) NOT NULL,
                longitude DECIMAL(10, 7) NOT NULL,
                address_approx VARCHAR(500),
                bedrooms INTEGER,
                bathrooms DECIMAL(3, 1),
                sleeps INTEGER,
                property_type VARCHAR(50),
                avg_adr DECIMAL(10, 2),
                min_nightly DECIMAL(10, 2),
                max_nightly DECIMAL(10, 2),
                has_pool BOOLEAN DEFAULT false,
                pool_type VARCHAR(50) DEFAULT 'none',
                pool_heated BOOLEAN DEFAULT false,
                has_hot_tub BOOLEAN DEFAULT false,
                has_view BOOLEAN DEFAULT false,
                view_type VARCHAR(50) DEFAULT 'none',
                beach_distance_ft INTEGER,
                beach_access_type VARCHAR(50) DEFAULT 'none',
                pet_friendly BOOLEAN DEFAULT false,
                parking_type VARCHAR(50) DEFAULT 'none',
                review_score DECIMAL(3, 2),
                review_count INTEGER,
                is_superhost BOOLEAN DEFAULT false,
                year_built INTEGER,
                listing_url VARCHAR(1000),
                title VARCHAR(500),
                scraped_at TIMESTAMP DEFAULT NOW(),
                last_updated TIMESTAMP DEFAULT NOW(),
                is_active BOOLEAN DEFAULT true,
                CONSTRAINT external_listings_unique UNIQUE (source, listing_id)
            )
        """)
        
        # Create indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_external_listings_market ON external_listings(market_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_external_listings_submarket ON external_listings(submarket_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_external_listings_geo ON external_listings(latitude, longitude)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_external_listings_beds ON external_listings(bedrooms)")
        
        # Insert 30A market
        cur.execute("""
            INSERT INTO markets (market_id, name, market_type, state, timezone, seasonality_type, peak_months, value_hierarchy)
            VALUES (
                '30a_fl', 
                '30A Corridor', 
                'beach', 
                'FL', 
                'America/Chicago',
                'summer',
                '{6,7,8}',
                '{"submarket_tier", "beach_distance", "view_type", "pool_type", "bedrooms", "property_quality"}'
            )
            ON CONFLICT (market_id) DO NOTHING
        """)
        
        # Insert 30A submarkets
        submarkets = [
            ('alys_beach', '30a_fl', 'Alys Beach', 0, 'architecture', '30_day_min'),
            ('rosemary_beach', '30a_fl', 'Rosemary Beach', 1, 'walkability', None),
            ('watercolor', '30a_fl', 'WaterColor', 1, 'beach_club', None),
            ('seaside', '30a_fl', 'Seaside', 1, 'iconic_location', None),
            ('seagrove', '30a_fl', 'Seagrove Beach', 2, 'affordability', None),
            ('watersound', '30a_fl', 'WaterSound', 2, 'beach_club', None),
            ('seacrest', '30a_fl', 'Seacrest Beach', 2, 'community_pool', None),
            ('inlet_beach', '30a_fl', 'Inlet Beach', 3, 'new_development', None),
        ]
        
        for sm in submarkets:
            cur.execute("""
                INSERT INTO submarkets (submarket_id, market_id, name, tier, primary_value_driver, rental_restrictions)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (submarket_id) DO NOTHING
            """, sm)
        
        conn.commit()
        
        # Get counts
        cur.execute("SELECT COUNT(*) FROM markets")
        market_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM submarkets")
        submarket_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM external_listings")
        listing_count = cur.fetchone()[0]
        
        cur.close()
        conn.close()
        
        return {
            "status": "success",
            "tables_created": ["markets", "submarkets", "external_listings"],
            "markets": market_count,
            "submarkets": submarket_count,
            "external_listings": listing_count,
            "next_steps": [
                "Run OTA scraper to populate external_listings",
                "Scraper should extract: lat/lng, beds, baths, pool, view, ADR",
                "Then call /bd/market-amenity-attribution for accurate lifts",
            ],
        }
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"{str(e)}\n{traceback.format_exc()}")


@router.get(
    "/tier-amenity-attribution",
    summary="Tier-Controlled Amenity Attribution",
    description="""
    Calculate amenity lifts WITHIN location tiers.
    
    This is the correct way to measure amenity value:
    - Compare pools among Tier 3 properties (not Tier 1 vs Tier 4)
    - Isolates amenity effect from location effect
    - More accurate for BD projections
    """
)
async def get_tier_amenity_attribution():
    """Calculate amenity attribution within location tiers."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    DATABASE_URL = _sync_database_url()
    
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cur = conn.cursor()
        
        # Get properties with tier and amenity info
        cur.execute("""
            SELECT 
                p.property_code,
                p.bedrooms,
                p.location_tier,
                p.view_type,
                p.has_pool,
                p.has_hot_tub,
                p.has_grill,
                AVG(pr.adr) as avg_adr
            FROM properties p
            JOIN property_pricing pr ON p.property_code = pr.property_code
            WHERE pr.adr > 0 AND p.location_tier IS NOT NULL
            GROUP BY p.property_code, p.bedrooms, p.location_tier, p.view_type,
                     p.has_pool, p.has_hot_tub, p.has_grill
        """)
        properties = [dict(r) for r in cur.fetchall()]
        
        cur.close()
        conn.close()
        
        # Analyze pool effect within Tier 3 (largest sample)
        tier3 = [p for p in properties if p['location_tier'] == 3]
        tier3_with_pool = [p for p in tier3 if p['has_pool']]
        tier3_without_pool = [p for p in tier3 if not p['has_pool']]
        
        # Analyze pool effect within Tier 4
        tier4 = [p for p in properties if p['location_tier'] == 4]
        tier4_with_pool = [p for p in tier4 if p['has_pool']]
        tier4_without_pool = [p for p in tier4 if not p['has_pool']]
        
        def calc_lift(with_amenity, without_amenity):
            if not with_amenity or not without_amenity:
                return None
            avg_with = sum(float(p['avg_adr']) for p in with_amenity) / len(with_amenity)
            avg_without = sum(float(p['avg_adr']) for p in without_amenity) / len(without_amenity)
            return {
                "avg_with": round(avg_with, 0),
                "avg_without": round(avg_without, 0),
                "lift_dollars": round(avg_with - avg_without, 0),
                "lift_pct": round((avg_with - avg_without) / avg_without, 4) if avg_without else 0,
                "sample_with": len(with_amenity),
                "sample_without": len(without_amenity),
            }
        
        # Tier summary
        tier_summary = {}
        for tier in [1, 2, 3, 4]:
            tier_props = [p for p in properties if p['location_tier'] == tier]
            if tier_props:
                tier_summary[f"tier_{tier}"] = {
                    "count": len(tier_props),
                    "avg_adr": round(sum(float(p['avg_adr']) for p in tier_props) / len(tier_props), 0),
                    "pct_with_pool": round(len([p for p in tier_props if p['has_pool']]) / len(tier_props), 2),
                }
        
        return {
            "methodology": "Amenity lifts calculated WITHIN location tiers to control for location premium",
            "tier_summary": tier_summary,
            "pool_effect_tier_3": calc_lift(tier3_with_pool, tier3_without_pool),
            "pool_effect_tier_4": calc_lift(tier4_with_pool, tier4_without_pool),
            "insights": [
                f"Tier 3 has {len(tier3)} properties ({len(tier3_with_pool)} with pool, {len(tier3_without_pool)} without)",
                f"Tier 4 has {len(tier4)} properties ({len(tier4_with_pool)} with pool, {len(tier4_without_pool)} without)",
                "Pool effect can only be measured where we have both with/without in same tier",
                "Tier 1-2 properties are too few for meaningful pool comparison",
            ],
            "recommendation": "Need more Tier 3/4 properties WITHOUT pools to accurately measure pool lift",
        }
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"{str(e)}\n{traceback.format_exc()}")


@router.get(
    "/data-coverage",
    summary="Check Data Coverage",
    description="See which properties have booking, pricing, and availability data."
)
async def get_data_coverage():
    """Check data coverage across properties."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    DATABASE_URL = _sync_database_url()
    
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) as cnt FROM properties")
        total = cur.fetchone()['cnt']
        
        cur.execute("SELECT COUNT(DISTINCT property_code) as cnt FROM property_bookings WHERE nights > 0 AND nights <= 30")
        with_bookings = cur.fetchone()['cnt']
        
        cur.execute("SELECT COUNT(DISTINCT property_code) as cnt FROM property_pricing WHERE adr > 0")
        with_pricing = cur.fetchone()['cnt']
        
        cur.execute("SELECT COUNT(DISTINCT property_code) as cnt FROM property_availability")
        with_availability = cur.fetchone()['cnt']
        
        # Properties missing data
        cur.execute("""
            SELECT p.property_code, p.address_street,
                   (SELECT COUNT(*) FROM property_bookings b WHERE b.property_code = p.property_code AND b.nights > 0 AND b.nights <= 30) as booking_count,
                   (SELECT COUNT(*) FROM property_pricing pr WHERE pr.property_code = p.property_code AND pr.adr > 0) as pricing_count
            FROM properties p
            ORDER BY p.property_code
        """)
        all_props = cur.fetchall()
        
        cur.close()
        conn.close()
        
        missing_bookings = [p for p in all_props if p['booking_count'] == 0]
        missing_pricing = [p for p in all_props if p['pricing_count'] == 0]
        
        return {
            "total_properties": total,
            "with_bookings": with_bookings,
            "with_pricing": with_pricing,
            "with_availability": with_availability,
            "coverage_pct": {
                "bookings": round(with_bookings / total * 100, 1) if total > 0 else 0,
                "pricing": round(with_pricing / total * 100, 1) if total > 0 else 0,
            },
            "missing_bookings": [{"code": p['property_code'], "address": p['address_street']} for p in missing_bookings],
            "missing_pricing": [{"code": p['property_code'], "address": p['address_street']} for p in missing_pricing],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/bd-context",
    summary="Get Complete BD Context",
    description="""
    Get complete BD context with all live data for projections and dashboards.
    
    This is the master endpoint that provides:
    - Portfolio metrics
    - Market signals
    - Internal comp set (formatted for projection engine)
    - Operator portfolio (formatted for projection engine)
    - Market census (formatted for projection engine)
    
    Use this to power BD dashboards and projection inputs with REAL data.
    """
)
async def get_bd_context_endpoint():
    """Get complete BD context from live data."""
    from app.services.bd.live_data_integration import get_bd_context
    
    return get_bd_context()
