"""
API Endpoint: Opportunity Scoring.

Exposes opportunity scoring for BD lead prioritization.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.orchestration import (
    OpportunityRunner,
    PropertyData,
    OwnerData,
    MarketData,
    get_opportunity_runner,
)


router = APIRouter(prefix="/opportunity", tags=["Opportunity"])


# =============================================================================
# REQUEST/RESPONSE SCHEMAS
# =============================================================================

class PropertyInput(BaseModel):
    """Property data for scoring."""
    property_id: UUID
    beds: int = Field(..., ge=1, le=20)
    baths: float = Field(..., ge=1, le=15)
    sqft: Optional[int] = Field(None, ge=100, le=50000)
    address: Optional[str] = None


class OwnerInput(BaseModel):
    """Owner data for scoring."""
    owner_id: UUID
    owner_type: str = Field("unknown", description="individual, llc, trust, corporate")
    absentee_owner: bool = False
    portfolio_size: int = Field(1, ge=1)
    tenure_years: Optional[float] = None
    
    # Contact info
    has_email: bool = False
    has_phone: bool = False
    do_not_contact: bool = False
    contact_confidence: float = Field(0.0, ge=0, le=1)


class MarketInput(BaseModel):
    """Market data for scoring."""
    market_id: str
    base_revenue_estimate: float = Field(0.0, ge=0)
    comparable_count: int = Field(0, ge=0)
    compliance_status: str = Field("unknown", pattern="^(known_allowed|likely_allowed|unknown|likely_restricted|known_restricted)$")


class ScoreRequest(BaseModel):
    """Request for single opportunity score."""
    property: PropertyInput
    owner: OwnerInput
    market: MarketInput


class BatchScoreRequest(BaseModel):
    """Request for batch opportunity scoring."""
    opportunities: List[ScoreRequest]
    min_score: float = Field(0.0, ge=0, le=100)
    max_results: int = Field(100, ge=1, le=1000)


class ScoredOpportunityResponse(BaseModel):
    """A scored opportunity."""
    owner_id: UUID
    property_id: UUID
    
    # Score
    overall_score: float
    rank: Optional[int] = None
    
    # Projections
    conservative_annual: float
    typical_annual: float
    upside_annual: float
    
    # Explainability
    top_drivers: List[str]
    data_gaps: List[str]


class ScoreResponse(BaseModel):
    """Response for single opportunity score."""
    opportunity: ScoredOpportunityResponse


class BatchScoreResponse(BaseModel):
    """Response for batch scoring."""
    opportunities: List[ScoredOpportunityResponse]
    total_processed: int
    total_qualified: int


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/score", response_model=ScoreResponse)
async def score_opportunity(request: ScoreRequest):
    """
    Score a single opportunity.
    
    Returns HomeownerOpportunityScore with projections and explainability.
    """
    runner = get_opportunity_runner()
    
    # Convert to internal format
    owner = OwnerData(
        owner_id=request.owner.owner_id,
        owner_type=request.owner.owner_type,
        absentee_owner=request.owner.absentee_owner,
        portfolio_size=request.owner.portfolio_size,
        tenure_years=request.owner.tenure_years,
        has_email=request.owner.has_email,
        has_phone=request.owner.has_phone,
        do_not_contact=request.owner.do_not_contact,
        contact_confidence=request.owner.contact_confidence,
    )
    
    property = PropertyData(
        property_id=request.property.property_id,
        beds=request.property.beds,
        baths=request.property.baths,
        sqft=request.property.sqft,
        address=request.property.address,
    )
    
    market = MarketData(
        market_id=request.market.market_id,
        base_revenue_estimate=request.market.base_revenue_estimate,
        comparable_count=request.market.comparable_count,
        compliance_status=request.market.compliance_status,
    )
    
    result = runner.score_single(owner, property, market)
    
    return ScoreResponse(
        opportunity=ScoredOpportunityResponse(
            owner_id=result.owner.owner_id,
            property_id=result.property.property_id,
            overall_score=result.overall_score,
            conservative_annual=result.conservative_annual,
            typical_annual=result.typical_annual,
            upside_annual=result.upside_annual,
            top_drivers=result.top_drivers,
            data_gaps=result.data_gaps,
        )
    )


@router.post("/score/batch", response_model=BatchScoreResponse)
async def batch_score_opportunities(request: BatchScoreRequest):
    """
    Score multiple opportunities and rank by score.
    
    Returns filtered and ranked list of opportunities.
    """
    runner = get_opportunity_runner()
    
    # Convert to internal format
    from app.services.orchestration.opportunity_runner import BatchScoreRequest as InternalRequest
    
    opportunities = []
    for opp in request.opportunities:
        owner = OwnerData(
            owner_id=opp.owner.owner_id,
            owner_type=opp.owner.owner_type,
            absentee_owner=opp.owner.absentee_owner,
            portfolio_size=opp.owner.portfolio_size,
            tenure_years=opp.owner.tenure_years,
            has_email=opp.owner.has_email,
            has_phone=opp.owner.has_phone,
            do_not_contact=opp.owner.do_not_contact,
            contact_confidence=opp.owner.contact_confidence,
        )
        
        property = PropertyData(
            property_id=opp.property.property_id,
            beds=opp.property.beds,
            baths=opp.property.baths,
            sqft=opp.property.sqft,
            address=opp.property.address,
        )
        
        market = MarketData(
            market_id=opp.market.market_id,
            base_revenue_estimate=opp.market.base_revenue_estimate,
            comparable_count=opp.market.comparable_count,
            compliance_status=opp.market.compliance_status,
        )
        
        opportunities.append((owner, property, market))
    
    internal_request = InternalRequest(
        opportunities=opportunities,
        min_score=request.min_score,
        max_results=request.max_results,
    )
    
    result = runner.score_batch(internal_request)
    
    return BatchScoreResponse(
        opportunities=[
            ScoredOpportunityResponse(
                owner_id=opp.owner.owner_id,
                property_id=opp.property.property_id,
                overall_score=opp.overall_score,
                rank=opp.rank,
                conservative_annual=opp.conservative_annual,
                typical_annual=opp.typical_annual,
                upside_annual=opp.upside_annual,
                top_drivers=opp.top_drivers,
                data_gaps=opp.data_gaps,
            )
            for opp in result.scored
        ],
        total_processed=result.total_processed,
        total_qualified=result.total_qualified,
    )


@router.get("/top/{market_id}", response_model=BatchScoreResponse)
async def get_top_opportunities(
    market_id: str,
    limit: int = 20,
    min_score: float = 50.0,
):
    """
    Get top opportunities for a market.
    
    Returns cached/pre-scored opportunities.
    """
    runner = get_opportunity_runner()
    
    results = runner.get_top_opportunities(
        market_id=market_id,
        limit=limit,
        min_score=min_score,
    )
    
    return BatchScoreResponse(
        opportunities=[
            ScoredOpportunityResponse(
                owner_id=opp.owner.owner_id,
                property_id=opp.property.property_id,
                overall_score=opp.overall_score,
                rank=opp.rank,
                conservative_annual=opp.conservative_annual,
                typical_annual=opp.typical_annual,
                upside_annual=opp.upside_annual,
                top_drivers=opp.top_drivers,
                data_gaps=opp.data_gaps,
            )
            for opp in results
        ],
        total_processed=len(results),
        total_qualified=len(results),
    )
