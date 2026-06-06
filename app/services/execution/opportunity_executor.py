"""
Execution Layer: Opportunity Executor.

Thin wrapper around opportunity domain for HomeownerOpportunityScore generation.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from uuid import UUID

from app.domain.opportunity import (
    HomeownerOpportunityScore,
    AssumptionProfile,
    OpportunityProjection,
    UnrealizedValue,
    OwnerSignals,
    PropertySignals,
    Contactability,
    Explainability,
    OpportunityType,
    ComplianceAssumption,
    compute_overall_score,
    get_compliance_modifier,
    infer_assumptions_from_signals,
    generate_three_scenario_projections,
)


# =============================================================================
# PAYLOADS
# =============================================================================

@dataclass
class OpportunityPayload:
    """Input payload for opportunity scoring."""
    owner_id: UUID
    property_id: UUID
    market_id: str
    
    # Property data
    beds: int
    baths: float
    sqft: Optional[int] = None
    
    # Owner data
    owner_type: str = "unknown"
    absentee_owner: bool = False
    portfolio_size: int = 1
    tenure_years: Optional[float] = None
    
    # Contact data
    has_email: bool = False
    has_phone: bool = False
    do_not_contact: bool = False
    contact_confidence: float = 0.0
    
    # Market data
    base_revenue_estimate: float = 0.0
    comparable_count: int = 0
    compliance_status: str = "unknown"
    
    # Evidence
    has_hoa_docs: bool = False
    nearby_listings_quality: Optional[str] = None


@dataclass
class OpportunityResult:
    """Result from opportunity scoring."""
    score: HomeownerOpportunityScore
    conservative_projection: OpportunityProjection
    typical_projection: OpportunityProjection
    upside_projection: OpportunityProjection


# =============================================================================
# EXECUTOR
# =============================================================================

class OpportunityExecutor:
    """
    Executor for opportunity scoring.
    
    Wraps domain functions with payload translation.
    """
    
    def score_opportunity(self, payload: OpportunityPayload) -> OpportunityResult:
        """
        Generate HomeownerOpportunityScore from payload.
        
        This is the main entry point for BD opportunity scoring.
        """
        # Build owner signals
        owner_signals = OwnerSignals(
            owner_type=payload.owner_type,
            absentee_owner=payload.absentee_owner,
            portfolio_size=payload.portfolio_size,
            tenure_years=payload.tenure_years,
        )
        
        # Build property signals
        property_signals = PropertySignals(
            beds=payload.beds,
            baths=payload.baths,
            sqft=payload.sqft,
        )
        
        # Build contactability
        contactability = Contactability(
            has_email=payload.has_email,
            has_phone=payload.has_phone,
            do_not_contact=payload.do_not_contact,
            confidence=payload.contact_confidence,
        )
        
        # Infer assumptions
        profile, data_gaps = infer_assumptions_from_signals(
            owner_signals=owner_signals,
            property_signals=property_signals,
            has_hoa_docs=payload.has_hoa_docs,
            nearby_listings_quality=payload.nearby_listings_quality,
        )
        
        # Map compliance
        compliance_map = {
            "known_allowed": ComplianceAssumption.KNOWN_ALLOWED,
            "likely_allowed": ComplianceAssumption.LIKELY_ALLOWED,
            "unknown": ComplianceAssumption.UNKNOWN,
            "likely_restricted": ComplianceAssumption.LIKELY_RESTRICTED,
            "known_restricted": ComplianceAssumption.KNOWN_RESTRICTED,
        }
        compliance = compliance_map.get(payload.compliance_status, ComplianceAssumption.UNKNOWN)
        
        # Generate three scenarios
        conservative, typical, upside = generate_three_scenario_projections(
            base_revenue=payload.base_revenue_estimate,
            base_confidence=0.7 - profile.confidence_penalty,
            comparable_count=payload.comparable_count,
        )
        
        # Calculate unrealized value (assuming current income is $0)
        unrealized = UnrealizedValue(
            absolute=typical.expected_annual,
            percentile_vs_market=50.0,  # Would need market data to calculate properly
        )
        
        # Compute overall score
        overall = compute_overall_score(
            unrealized_value=unrealized.absolute,
            projection_confidence=typical.confidence,
            contactability_confidence=contactability.confidence,
            compliance_modifier=get_compliance_modifier(compliance),
        )
        
        # Build explainability
        top_drivers = []
        if unrealized.absolute > 40000:
            top_drivers.append("High unrealized value")
        if contactability.is_contactable:
            top_drivers.append("Strong contactability")
        if payload.comparable_count >= 5:
            top_drivers.append("Good comparable data")
        
        explainability = Explainability(
            top_drivers=top_drivers,
            key_assumptions=profile.to_assumptions_list(),
            data_gaps=data_gaps,
        )
        
        # Build final score
        hos = HomeownerOpportunityScore(
            owner_id=payload.owner_id,
            property_id=payload.property_id,
            market_id=payload.market_id,
            opportunity_type=OpportunityType.STR_CONVERSION,
            projection=typical,
            unrealized_value=unrealized,
            owner_signals=owner_signals,
            property_signals=property_signals,
            contactability=contactability,
            overall_score=overall,
            explainability=explainability,
        )
        
        return OpportunityResult(
            score=hos,
            conservative_projection=conservative,
            typical_projection=typical,
            upside_projection=upside,
        )
    
    def batch_score(self, payloads: List[OpportunityPayload]) -> List[OpportunityResult]:
        """Score multiple opportunities."""
        return [self.score_opportunity(p) for p in payloads]
    
    def rank_opportunities(
        self, 
        results: List[OpportunityResult],
        min_score: float = 0.0,
    ) -> List[OpportunityResult]:
        """Rank opportunities by overall score."""
        filtered = [r for r in results if r.score.overall_score >= min_score]
        return sorted(filtered, key=lambda r: r.score.overall_score, reverse=True)
