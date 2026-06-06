"""
Execution Layer: BD Executor.

Thin wrapper around BD domain for pitch book and projection summary generation.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from app.domain.bd import (
    # Scenarios
    ProjectionScenario,
    ScenarioType,
    MetricRange,
    ConfidenceBand,
    
    # Narratives
    NarrativeBlock,
    NarrativeBlockType,
    generate_projection_narrative,
    
    # Pitch book
    PitchBook,
    PropertySnapshot,
    MarketContextSection,
    ComparableInsightsSection,
    ProjectionScenariosSection,
    UpsideAnalysisSection,
    RiskDisclosureSection,
    NextStepsSection,
    
    # Summary
    BDProjectionSummary,
    ComparableSnapshot,
    validate_bd_projection,
    
    # Leads
    BDLeadScore,
    rank_bd_leads,
)

from app.domain.market import MarketContext, MarketSummary


# =============================================================================
# PAYLOADS
# =============================================================================

@dataclass
class PitchBookPayload:
    """Input for generating a pitch book."""
    property_id: UUID
    
    # Property data
    beds: int
    baths: float
    sqft: Optional[int] = None
    property_type: str = "Single Family"
    address: Optional[str] = None
    
    # Market data
    market_id: str = ""
    market_name: str = ""
    
    # Projections
    annual_revenue_low: float = 0.0
    annual_revenue_expected: float = 0.0
    annual_revenue_high: float = 0.0
    
    adr_low: float = 0.0
    adr_expected: float = 0.0
    adr_high: float = 0.0
    
    occupancy_low: float = 0.0
    occupancy_expected: float = 0.0
    occupancy_high: float = 0.0
    
    # Comparable data
    comparable_count: int = 0
    comparable_avg_revenue: float = 0.0
    comparable_avg_adr: float = 0.0
    comparable_avg_occupancy: float = 0.0
    
    # Assumptions
    assumptions: List[str] = None
    
    # Audience
    audience: str = "homeowner"  # homeowner, realtor, investor
    
    def __post_init__(self):
        if self.assumptions is None:
            self.assumptions = ["Professional management", "Average furnishing level"]


@dataclass
class BDSummaryPayload:
    """Input for generating BD projection summary."""
    property_id: UUID
    property_description: str
    property_address: Optional[str] = None
    
    # Projections (required)
    annual_revenue_low: float = 0.0
    annual_revenue_expected: float = 0.0
    annual_revenue_high: float = 0.0
    
    # Comparable data
    comparable_count: int = 0
    comparable_avg_revenue: float = 0.0
    
    # Assumptions
    assumptions: List[str] = None
    
    # Confidence
    confidence_level: str = "medium"
    
    def __post_init__(self):
        if self.assumptions is None:
            self.assumptions = ["Professional management", "Average furnishing level"]


# =============================================================================
# EXECUTOR
# =============================================================================

class BDExecutor:
    """
    Executor for BD artifacts.
    
    Generates:
    - Pitch books
    - Projection summaries
    - Lead rankings
    """
    
    def generate_pitch_book(
        self,
        payload: PitchBookPayload,
        market_context: Optional[MarketContext] = None,
    ) -> PitchBook:
        """
        Generate a complete pitch book.
        
        This is the main BD artifact.
        """
        property_description = f"{payload.beds}BR/{payload.baths}BA {payload.property_type}"
        
        # Create projection scenarios
        conservative = ProjectionScenario.create(
            scenario_type=ScenarioType.CONSERVATIVE,
            annual_revenue_min=payload.annual_revenue_low * 0.9,
            annual_revenue_max=payload.annual_revenue_low * 1.1,
            adr_min=payload.adr_low * 0.95,
            adr_max=payload.adr_low * 1.05,
            occupancy_min=payload.occupancy_low * 0.95,
            occupancy_max=payload.occupancy_low * 1.05,
            confidence=0.8,
            assumptions=["Conservative assumptions", "Below-market occupancy"],
            drivers=["Seasonality", "Competition"],
            comparable_count=payload.comparable_count,
        )
        
        baseline = ProjectionScenario.create(
            scenario_type=ScenarioType.BASELINE,
            annual_revenue_min=payload.annual_revenue_expected * 0.9,
            annual_revenue_max=payload.annual_revenue_expected * 1.1,
            adr_min=payload.adr_expected * 0.95,
            adr_max=payload.adr_expected * 1.05,
            occupancy_min=payload.occupancy_expected * 0.95,
            occupancy_max=payload.occupancy_expected * 1.05,
            confidence=0.7,
            assumptions=payload.assumptions,
            drivers=["Furnishing quality", "Management approach"],
            comparable_count=payload.comparable_count,
        )
        
        optimized = ProjectionScenario.create(
            scenario_type=ScenarioType.OPTIMIZED,
            annual_revenue_min=payload.annual_revenue_high * 0.9,
            annual_revenue_max=payload.annual_revenue_high * 1.1,
            adr_min=payload.adr_high * 0.95,
            adr_max=payload.adr_high * 1.05,
            occupancy_min=payload.occupancy_high * 0.95,
            occupancy_max=payload.occupancy_high * 1.05,
            confidence=0.55,
            assumptions=["Premium furnishing", "Optimized pricing"],
            drivers=["Dynamic pricing", "Guest experience"],
            comparable_count=payload.comparable_count,
        )
        
        # Create narrative blocks
        property_narrative = NarrativeBlock(
            block_type=NarrativeBlockType.PROPERTY_OVERVIEW,
            headline="Property Overview",
            body=[
                f"This {property_description} offers strong rental potential.",
                f"Located in {payload.market_name}." if payload.market_name else "",
            ],
            confidence=0.9,
        )
        
        projection_narrative = generate_projection_narrative(baseline, property_description)
        
        # Build sections
        property_snapshot = PropertySnapshot(
            title="Property Overview",
            content={
                "beds": payload.beds,
                "baths": payload.baths,
                "sqft": payload.sqft,
                "type": payload.property_type,
                "address": payload.address,
            },
            narrative=property_narrative,
        )
        
        market_section = None
        if market_context:
            summary = MarketSummary.from_context(market_context, bedrooms=payload.beds)
            market_section = MarketContextSection(
                title="Market Context",
                content={
                    "market_name": summary.market_name,
                    "demand_trend": summary.demand_trend,
                    "supply_demand": summary.supply_demand_state,
                    "upcoming_events": summary.upcoming_events,
                },
                narrative=NarrativeBlock(
                    block_type=NarrativeBlockType.MARKET_CONTEXT,
                    headline="Market Overview",
                    body=[f"{payload.market_name} is showing {summary.demand_trend.lower()} demand."],
                ),
            )
        
        comparable_section = ComparableInsightsSection(
            title="Comparable Performance",
            content={
                "count": payload.comparable_count,
                "avg_revenue": payload.comparable_avg_revenue,
                "avg_adr": payload.comparable_avg_adr,
                "avg_occupancy": payload.comparable_avg_occupancy,
            },
            narrative=NarrativeBlock(
                block_type=NarrativeBlockType.COMPARABLE_ANALYSIS,
                headline="Comparable Properties",
                body=[
                    f"Analysis based on {payload.comparable_count} comparable properties.",
                    f"Average annual revenue: ${payload.comparable_avg_revenue:,.0f}.",
                ],
            ),
        )
        
        projection_section = ProjectionScenariosSection(
            title="Revenue Projections",
            scenarios=[conservative, baseline, optimized],
            narrative=projection_narrative,
        )
        
        upside_section = UpsideAnalysisSection(
            title="Upside Opportunities",
            content={
                "premium_potential": payload.annual_revenue_high - payload.annual_revenue_expected,
                "drivers": ["Premium furnishing", "Dynamic pricing", "Guest experience optimization"],
            },
            narrative=NarrativeBlock(
                block_type=NarrativeBlockType.OPPORTUNITY_SUMMARY,
                headline="Upside Potential",
                body=[
                    f"With optimization, this property could achieve up to ${payload.annual_revenue_high:,.0f} annually.",
                ],
            ),
        )
        
        risk_section = RiskDisclosureSection(
            title="Risk Considerations",
            content={
                "risks": [
                    "Market conditions may vary",
                    "Actual results depend on execution",
                    "Regulatory changes possible",
                ],
            },
            narrative=NarrativeBlock(
                block_type=NarrativeBlockType.RISK_DISCLOSURE,
                headline="Important Considerations",
                body=[
                    "Projections are estimates based on comparable properties.",
                    "Actual results may vary based on property condition, management, and market conditions.",
                ],
                disclosures=["This is not a guarantee of income."],
            ),
        )
        
        next_steps = NextStepsSection(
            title="Next Steps",
            cta="Schedule a consultation to discuss your property's potential.",
        )
        
        # Assemble pitch book
        pitch_book = PitchBook(
            property_id=payload.property_id,
            property_snapshot=property_snapshot,
            market_context=market_section,
            comparable_insights=comparable_section,
            projection_scenarios=projection_section,
            upside_analysis=upside_section,
            risk_disclosure=risk_section,
            next_steps=next_steps,
            audience=payload.audience,
        )
        
        return pitch_book
    
    def generate_projection_summary(
        self,
        payload: BDSummaryPayload,
    ) -> BDProjectionSummary:
        """
        Generate a BD projection summary for homeowner outreach.
        
        Safe, compliant, with built-in disclaimers.
        """
        summary = BDProjectionSummary(
            property_id=payload.property_id,
            property_description=payload.property_description,
            property_address=payload.property_address,
            
            # Annual
            annual_revenue_low=payload.annual_revenue_low,
            annual_revenue_expected=payload.annual_revenue_expected,
            annual_revenue_high=payload.annual_revenue_high,
            
            # Monthly
            monthly_revenue_low=payload.annual_revenue_low / 12,
            monthly_revenue_expected=payload.annual_revenue_expected / 12,
            monthly_revenue_high=payload.annual_revenue_high / 12,
            
            # Comparable
            comparable_snapshot=ComparableSnapshot(
                count=payload.comparable_count,
                avg_revenue=payload.comparable_avg_revenue,
                avg_adr=0.0,
                avg_occupancy=0.0,
                similarity_description="similar homes in your area",
            ) if payload.comparable_count > 0 else None,
            
            assumptions_used=payload.assumptions,
            confidence_level=payload.confidence_level,
            
            why_this_applies_to_you=(
                f"Based on {payload.comparable_count} comparable properties in your area, "
                f"homes like yours typically generate strong rental income."
            ),
        )
        
        # Validate compliance
        check = validate_bd_projection(summary)
        if not check.is_compliant:
            # Add missing elements
            if not summary.assumptions_used:
                summary.assumptions_used = ["Professional management assumed"]
        
        return summary
    
    def rank_leads(
        self,
        leads: List[BDLeadScore],
        min_score: float = 0.0,
    ) -> List[BDLeadScore]:
        """Rank BD leads by priority."""
        filtered = [l for l in leads if l.total_score >= min_score]
        return rank_bd_leads(filtered)
