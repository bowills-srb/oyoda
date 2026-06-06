"""
Orchestration: Opportunity Runner.

Thin workflow orchestrator for opportunity operations.
Handles batch scoring, ranking, and list management.

Does NOT contain business logic or make decisions.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from app.domain.opportunity import (
    HomeownerOpportunityScore,
    OpportunityProjection,
    OpportunityType,
)

from app.services.execution import (
    OpportunityExecutor,
    OpportunityPayload,
    OpportunityResult,
)


# =============================================================================
# REQUEST/RESPONSE DTOs
# =============================================================================

@dataclass
class PropertyData:
    """Property data for opportunity scoring."""
    property_id: UUID
    beds: int
    baths: float
    sqft: Optional[int] = None
    address: Optional[str] = None


@dataclass
class OwnerData:
    """Owner data for opportunity scoring."""
    owner_id: UUID
    owner_type: str = "unknown"
    absentee_owner: bool = False
    portfolio_size: int = 1
    tenure_years: Optional[float] = None
    
    # Contact
    has_email: bool = False
    has_phone: bool = False
    email: Optional[str] = None
    phone: Optional[str] = None
    do_not_contact: bool = False
    contact_confidence: float = 0.0


@dataclass
class MarketData:
    """Market data for opportunity scoring."""
    market_id: str
    base_revenue_estimate: float = 0.0
    comparable_count: int = 0
    compliance_status: str = "unknown"


@dataclass
class ScoredOpportunity:
    """A scored opportunity with all projections."""
    owner: OwnerData
    property: PropertyData
    market: MarketData
    
    # Score
    overall_score: float = 0.0
    
    # Projections
    conservative_annual: float = 0.0
    typical_annual: float = 0.0
    upside_annual: float = 0.0
    
    # Explainability
    top_drivers: List[str] = field(default_factory=list)
    data_gaps: List[str] = field(default_factory=list)
    
    # Ranking
    rank: Optional[int] = None
    
    # Raw score object (for detailed access)
    _raw_score: Optional[HomeownerOpportunityScore] = None


@dataclass
class BatchScoreRequest:
    """Request for batch scoring."""
    opportunities: List[Tuple[OwnerData, PropertyData, MarketData]]
    min_score: float = 0.0
    max_results: int = 100


@dataclass
class BatchScoreResponse:
    """Response from batch scoring."""
    scored: List[ScoredOpportunity]
    total_processed: int
    total_qualified: int
    generated_at: datetime


# =============================================================================
# OPPORTUNITY RUNNER
# =============================================================================

class OpportunityRunner:
    """
    Orchestrates opportunity scoring workflows.
    
    This is a THIN orchestrator that:
    - Accepts property/owner/market data
    - Calls the opportunity executor
    - Ranks and filters results
    
    It does NOT:
    - Contain scoring logic
    - Make decisions
    - Compute assumptions
    
    Usage:
        runner = OpportunityRunner()
        
        # Score single
        result = runner.score_single(owner, property, market)
        
        # Score batch
        response = runner.score_batch(request)
        
        # Get top opportunities
        top = runner.get_top_opportunities(market_id, limit=20)
    """
    
    def __init__(self):
        self.executor = OpportunityExecutor()
        
        # Results cache (in production, use Redis or DB)
        self._results_cache: Dict[str, List[ScoredOpportunity]] = {}
    
    def score_single(
        self,
        owner: OwnerData,
        property: PropertyData,
        market: MarketData,
    ) -> ScoredOpportunity:
        """
        Score a single opportunity.
        
        Args:
            owner: Owner data
            property: Property data
            market: Market data
            
        Returns:
            ScoredOpportunity with projections
        """
        payload = OpportunityPayload(
            owner_id=owner.owner_id,
            property_id=property.property_id,
            market_id=market.market_id,
            beds=property.beds,
            baths=property.baths,
            sqft=property.sqft,
            owner_type=owner.owner_type,
            absentee_owner=owner.absentee_owner,
            portfolio_size=owner.portfolio_size,
            tenure_years=owner.tenure_years,
            has_email=owner.has_email,
            has_phone=owner.has_phone,
            do_not_contact=owner.do_not_contact,
            contact_confidence=owner.contact_confidence,
            base_revenue_estimate=market.base_revenue_estimate,
            comparable_count=market.comparable_count,
            compliance_status=market.compliance_status,
        )
        
        result = self.executor.score_opportunity(payload)
        
        return ScoredOpportunity(
            owner=owner,
            property=property,
            market=market,
            overall_score=result.score.overall_score,
            conservative_annual=result.conservative_projection.expected_annual,
            typical_annual=result.typical_projection.expected_annual,
            upside_annual=result.upside_projection.expected_annual,
            top_drivers=result.score.explainability.top_drivers,
            data_gaps=result.score.explainability.data_gaps,
            _raw_score=result.score,
        )
    
    def score_batch(
        self,
        request: BatchScoreRequest,
    ) -> BatchScoreResponse:
        """
        Score a batch of opportunities.
        
        Args:
            request: Batch scoring request
            
        Returns:
            BatchScoreResponse with ranked results
        """
        scored = []
        
        for owner, property, market in request.opportunities:
            try:
                result = self.score_single(owner, property, market)
                scored.append(result)
            except Exception as e:
                # Log error but continue processing
                continue
        
        # Filter by minimum score
        qualified = [s for s in scored if s.overall_score >= request.min_score]
        
        # Sort by score (descending)
        qualified.sort(key=lambda s: s.overall_score, reverse=True)
        
        # Assign ranks
        for i, opp in enumerate(qualified):
            opp.rank = i + 1
        
        # Apply limit
        limited = qualified[:request.max_results]
        
        return BatchScoreResponse(
            scored=limited,
            total_processed=len(scored),
            total_qualified=len(qualified),
            generated_at=datetime.utcnow(),
        )
    
    def get_top_opportunities(
        self,
        market_id: str,
        limit: int = 20,
        min_score: float = 50.0,
    ) -> List[ScoredOpportunity]:
        """
        Get top opportunities for a market.
        
        In production, this would query persisted scores.
        """
        if market_id in self._results_cache:
            results = self._results_cache[market_id]
            filtered = [r for r in results if r.overall_score >= min_score]
            filtered.sort(key=lambda r: r.overall_score, reverse=True)
            return filtered[:limit]
        
        return []
    
    def cache_results(self, market_id: str, results: List[ScoredOpportunity]):
        """Cache scored results for a market."""
        self._results_cache[market_id] = results
    
    def get_contactable_leads(
        self,
        opportunities: List[ScoredOpportunity],
        require_email: bool = True,
        require_phone: bool = False,
    ) -> List[ScoredOpportunity]:
        """
        Filter to contactable leads only.
        
        Args:
            opportunities: List of scored opportunities
            require_email: Must have email
            require_phone: Must have phone
            
        Returns:
            Filtered list of contactable opportunities
        """
        filtered = []
        
        for opp in opportunities:
            if opp.owner.do_not_contact:
                continue
            if require_email and not opp.owner.has_email:
                continue
            if require_phone and not opp.owner.has_phone:
                continue
            filtered.append(opp)
        
        return filtered
    
    def segment_by_score(
        self,
        opportunities: List[ScoredOpportunity],
    ) -> Dict[str, List[ScoredOpportunity]]:
        """
        Segment opportunities by score tier.
        
        Returns:
            Dict with 'hot', 'warm', 'cold' lists
        """
        hot = []    # 70+
        warm = []   # 50-70
        cold = []   # <50
        
        for opp in opportunities:
            if opp.overall_score >= 70:
                hot.append(opp)
            elif opp.overall_score >= 50:
                warm.append(opp)
            else:
                cold.append(opp)
        
        return {
            "hot": hot,
            "warm": warm,
            "cold": cold,
        }


# =============================================================================
# FACTORY
# =============================================================================

_runner: Optional[OpportunityRunner] = None


def get_opportunity_runner() -> OpportunityRunner:
    """Get or create the opportunity runner singleton."""
    global _runner
    if _runner is None:
        _runner = OpportunityRunner()
    return _runner
