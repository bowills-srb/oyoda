"""
Orchestration: BD Runner.

Thin workflow orchestrator for BD operations.
Loads context, calls executors, assembles responses.

Does NOT contain business logic or make decisions.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.domain.bd import PitchBook, BDProjectionSummary, BDLeadScore
from app.domain.market import MarketContext
from app.domain.opportunity import HomeownerOpportunityScore

from app.services.execution import (
    BDExecutor,
    PitchBookPayload,
    BDSummaryPayload,
    OpportunityExecutor,
    OpportunityPayload,
    OpportunityResult,
    MarketExecutor,
    MarketContextPayload,
)


# =============================================================================
# REQUEST/RESPONSE DTOs
# =============================================================================

@dataclass
class PitchRequest:
    """Request for pitch book generation."""
    property_id: UUID
    
    # Property data
    beds: int
    baths: float
    sqft: Optional[int] = None
    property_type: str = "Single Family"
    address: Optional[str] = None
    
    # Market
    market_id: str = ""
    market_name: str = ""
    
    # Projections (if pre-computed)
    annual_revenue_low: Optional[float] = None
    annual_revenue_expected: Optional[float] = None
    annual_revenue_high: Optional[float] = None
    
    # Comparable data
    comparable_count: int = 0
    comparable_avg_revenue: float = 0.0
    
    # Audience
    audience: str = "homeowner"


@dataclass
class PitchResponse:
    """Response containing pitch book."""
    pitch_book: PitchBook
    generated_at: datetime
    market_context: Optional[MarketContext] = None


@dataclass
class OpportunityRequest:
    """Request for opportunity scoring."""
    owner_id: UUID
    property_id: UUID
    market_id: str
    
    # Property
    beds: int
    baths: float
    sqft: Optional[int] = None
    
    # Owner signals
    owner_type: str = "unknown"
    absentee_owner: bool = False
    portfolio_size: int = 1
    
    # Contact
    has_email: bool = False
    has_phone: bool = False
    contact_confidence: float = 0.0
    
    # Market
    base_revenue_estimate: float = 0.0
    comparable_count: int = 0


@dataclass
class OpportunityResponse:
    """Response containing opportunity score."""
    score: HomeownerOpportunityScore
    conservative_projection: float
    typical_projection: float
    upside_projection: float
    rank: Optional[int] = None


@dataclass
class LeadListRequest:
    """Request for ranked lead list."""
    market_id: str
    opportunities: List[OpportunityRequest]
    min_score: float = 0.0
    limit: int = 50


@dataclass
class LeadListResponse:
    """Response containing ranked leads."""
    leads: List[OpportunityResponse]
    total_count: int
    filtered_count: int
    generated_at: datetime


# =============================================================================
# BD RUNNER
# =============================================================================

class BDRunner:
    """
    Orchestrates BD workflows.
    
    This is a THIN orchestrator that:
    - Loads context (market, property)
    - Calls executors
    - Assembles response DTOs
    
    It does NOT:
    - Contain business logic
    - Make decisions
    - Compute projections
    
    Usage:
        runner = BDRunner()
        
        # Generate pitch book
        response = runner.generate_pitch(request)
        
        # Score opportunity
        response = runner.score_opportunity(request)
        
        # Get ranked lead list
        response = runner.get_lead_list(request)
    """
    
    def __init__(self):
        self.bd_executor = BDExecutor()
        self.opportunity_executor = OpportunityExecutor()
        self.market_executor = MarketExecutor()
        
        # Context cache (in production, use Redis or similar)
        self._market_cache: Dict[str, MarketContext] = {}
    
    def generate_pitch(
        self,
        request: PitchRequest,
        market_context: Optional[MarketContext] = None,
    ) -> PitchResponse:
        """
        Generate a pitch book.
        
        Args:
            request: Pitch book request
            market_context: Optional pre-loaded market context
            
        Returns:
            PitchResponse with generated pitch book
        """
        # Load market context if not provided
        if market_context is None and request.market_id:
            market_context = self._get_market_context(request.market_id)
        
        # Build payload
        payload = PitchBookPayload(
            property_id=request.property_id,
            beds=request.beds,
            baths=request.baths,
            sqft=request.sqft,
            property_type=request.property_type,
            address=request.address,
            market_id=request.market_id,
            market_name=request.market_name or (market_context.market_name if market_context else ""),
            annual_revenue_low=request.annual_revenue_low or 0.0,
            annual_revenue_expected=request.annual_revenue_expected or 0.0,
            annual_revenue_high=request.annual_revenue_high or 0.0,
            comparable_count=request.comparable_count,
            comparable_avg_revenue=request.comparable_avg_revenue,
            audience=request.audience,
        )
        
        # Generate pitch book
        pitch_book = self.bd_executor.generate_pitch_book(payload, market_context)
        
        return PitchResponse(
            pitch_book=pitch_book,
            generated_at=datetime.utcnow(),
            market_context=market_context,
        )
    
    def score_opportunity(
        self,
        request: OpportunityRequest,
    ) -> OpportunityResponse:
        """
        Score a single opportunity.
        
        Args:
            request: Opportunity scoring request
            
        Returns:
            OpportunityResponse with score and projections
        """
        payload = OpportunityPayload(
            owner_id=request.owner_id,
            property_id=request.property_id,
            market_id=request.market_id,
            beds=request.beds,
            baths=request.baths,
            sqft=request.sqft,
            owner_type=request.owner_type,
            absentee_owner=request.absentee_owner,
            portfolio_size=request.portfolio_size,
            has_email=request.has_email,
            has_phone=request.has_phone,
            contact_confidence=request.contact_confidence,
            base_revenue_estimate=request.base_revenue_estimate,
            comparable_count=request.comparable_count,
        )
        
        result = self.opportunity_executor.score_opportunity(payload)
        
        return OpportunityResponse(
            score=result.score,
            conservative_projection=result.conservative_projection.expected_annual,
            typical_projection=result.typical_projection.expected_annual,
            upside_projection=result.upside_projection.expected_annual,
        )
    
    def get_lead_list(
        self,
        request: LeadListRequest,
    ) -> LeadListResponse:
        """
        Get a ranked list of BD leads.
        
        Args:
            request: Lead list request with opportunities
            
        Returns:
            LeadListResponse with ranked leads
        """
        # Score all opportunities
        results = []
        for opp_request in request.opportunities:
            response = self.score_opportunity(opp_request)
            results.append(response)
        
        # Filter by minimum score
        filtered = [r for r in results if r.score.overall_score >= request.min_score]
        
        # Sort by score
        filtered.sort(key=lambda r: r.score.overall_score, reverse=True)
        
        # Add ranks
        for i, lead in enumerate(filtered):
            lead.rank = i + 1
        
        # Apply limit
        limited = filtered[:request.limit]
        
        return LeadListResponse(
            leads=limited,
            total_count=len(results),
            filtered_count=len(filtered),
            generated_at=datetime.utcnow(),
        )
    
    def generate_summary(
        self,
        property_id: UUID,
        property_description: str,
        annual_revenue_low: float,
        annual_revenue_expected: float,
        annual_revenue_high: float,
        comparable_count: int = 0,
    ) -> BDProjectionSummary:
        """
        Generate a BD projection summary (for outreach).
        
        Returns a compliant, safe summary with built-in disclaimers.
        """
        payload = BDSummaryPayload(
            property_id=property_id,
            property_description=property_description,
            annual_revenue_low=annual_revenue_low,
            annual_revenue_expected=annual_revenue_expected,
            annual_revenue_high=annual_revenue_high,
            comparable_count=comparable_count,
        )
        
        return self.bd_executor.generate_projection_summary(payload)
    
    def _get_market_context(self, market_id: str) -> Optional[MarketContext]:
        """
        Load market context.
        
        In production, this would load from database/cache.
        """
        if market_id in self._market_cache:
            return self._market_cache[market_id]
        
        # Placeholder - in production, load from DB
        return None
    
    def set_market_context(self, market_id: str, context: MarketContext):
        """Cache a market context."""
        self._market_cache[market_id] = context


# =============================================================================
# FACTORY
# =============================================================================

_runner: Optional[BDRunner] = None


def get_bd_runner() -> BDRunner:
    """Get or create the BD runner singleton."""
    global _runner
    if _runner is None:
        _runner = BDRunner()
    return _runner
