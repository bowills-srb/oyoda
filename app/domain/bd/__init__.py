"""
Domain: BD - Pure Models for Business Development.

Safe, compliant projection summaries and pitch book schemas.
No FastAPI. No DB sessions. No external API calls.

Per Master Spec:
- NarrativeBlock: Machine-generated language from projections
- ProjectionScenario: Formal schema with scenario_type
- PitchBook: Composable sections schema
- BDProjectionSummary: Safe homeowner-facing projections
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4


# =============================================================================
# SCENARIO TYPES
# =============================================================================

class ScenarioType(str, Enum):
    """Type of projection scenario."""
    CONSERVATIVE = "conservative"
    BASELINE = "baseline"
    OPTIMIZED = "optimized"


class ConfidenceBand(str, Enum):
    """Confidence level band."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# =============================================================================
# PROJECTION SCENARIO (Master Spec Requirement)
# =============================================================================

@dataclass
class MetricRange:
    """A metric with min/max range."""
    min: float
    max: float
    
    @property
    def midpoint(self) -> float:
        return (self.min + self.max) / 2
    
    def format_currency(self) -> str:
        return f"${self.min:,.0f} - ${self.max:,.0f}"
    
    def format_percent(self) -> str:
        return f"{self.min:.0%} - {self.max:.0%}"


@dataclass
class ProjectionScenario:
    """
    Formal projection scenario per master spec.
    
    This is the analytics output that NarrativeBlock consumes.
    """
    scenario_id: UUID = field(default_factory=uuid4)
    scenario_type: ScenarioType = ScenarioType.BASELINE
    
    # Assumptions used
    assumptions_used: List[str] = field(default_factory=list)
    assumption_profile_id: Optional[str] = None
    
    # Metrics (always ranges, never point estimates)
    metrics: Dict[str, MetricRange] = field(default_factory=dict)
    
    # Confidence
    confidence_band: ConfidenceBand = ConfidenceBand.MEDIUM
    confidence_score: float = 0.0
    
    # What drives the numbers
    sensitivity_drivers: List[str] = field(default_factory=list)
    
    # Metadata
    generated_at: datetime = field(default_factory=datetime.utcnow)
    comparable_count: int = 0
    
    @property
    def annual_revenue(self) -> Optional[MetricRange]:
        return self.metrics.get("annual_revenue")
    
    @property
    def adr(self) -> Optional[MetricRange]:
        return self.metrics.get("adr")
    
    @property
    def occupancy(self) -> Optional[MetricRange]:
        return self.metrics.get("occupancy")
    
    @classmethod
    def create(
        cls,
        scenario_type: ScenarioType,
        annual_revenue_min: float,
        annual_revenue_max: float,
        adr_min: float,
        adr_max: float,
        occupancy_min: float,
        occupancy_max: float,
        confidence: float,
        assumptions: List[str],
        drivers: List[str],
        comparable_count: int = 0,
    ) -> "ProjectionScenario":
        """Create a scenario with standard metrics."""
        return cls(
            scenario_type=scenario_type,
            metrics={
                "annual_revenue": MetricRange(annual_revenue_min, annual_revenue_max),
                "adr": MetricRange(adr_min, adr_max),
                "occupancy": MetricRange(occupancy_min, occupancy_max),
            },
            confidence_band=ConfidenceBand.HIGH if confidence >= 0.7 else ConfidenceBand.MEDIUM if confidence >= 0.4 else ConfidenceBand.LOW,
            confidence_score=confidence,
            assumptions_used=assumptions,
            sensitivity_drivers=drivers,
            comparable_count=comparable_count,
        )


# =============================================================================
# NARRATIVE BLOCK (Master Spec Requirement)
# =============================================================================

class NarrativeBlockType(str, Enum):
    """Type of narrative block."""
    PROJECTION_EXPLANATION = "projection_explanation"
    MARKET_CONTEXT = "market_context"
    PROPERTY_OVERVIEW = "property_overview"
    COMPARABLE_ANALYSIS = "comparable_analysis"
    RISK_DISCLOSURE = "risk_disclosure"
    OPPORTUNITY_SUMMARY = "opportunity_summary"
    NEXT_STEPS = "next_steps"


@dataclass
class NarrativeBlock:
    """
    Machine-generated language block per master spec.
    
    Every projection MUST emit language, not just math.
    
    Rule:
    - No projection without a narrative
    - No narrative without evidence references
    
    This powers:
    - Pitch books
    - Voice concierge
    - Realtor conversations
    - Legal defensibility
    """
    block_type: NarrativeBlockType
    headline: str
    body: List[str] = field(default_factory=list)
    disclosures: List[str] = field(default_factory=list)
    
    # Evidence references (for traceability)
    evidence_refs: List[str] = field(default_factory=list)
    
    # Confidence
    confidence: float = 0.0
    
    def to_text(self) -> str:
        """Convert to plain text."""
        lines = [self.headline, ""]
        lines.extend(self.body)
        if self.disclosures:
            lines.append("")
            lines.extend(self.disclosures)
        return "\n".join(lines)
    
    def to_voice_script(self) -> str:
        """Convert to voice-friendly script."""
        return " ".join(self.body)


def generate_projection_narrative(
    scenario: ProjectionScenario,
    property_description: str = "this property",
) -> NarrativeBlock:
    """
    Generate narrative block from projection scenario.
    
    Pure function - no IO.
    """
    body = []
    
    # Revenue statement
    if scenario.annual_revenue:
        body.append(
            f"Based on comparable homes, {property_description} could generate "
            f"between {scenario.annual_revenue.format_currency()} annually."
        )
    
    # Assumptions statement
    if scenario.assumptions_used:
        assumptions_text = ", ".join(scenario.assumptions_used[:3])
        body.append(f"This estimate assumes {assumptions_text.lower()}.")
    
    # Drivers statement
    if scenario.sensitivity_drivers:
        drivers_text = " and ".join(scenario.sensitivity_drivers[:2])
        body.append(f"Results are most sensitive to {drivers_text.lower()}.")
    
    # Comparable basis
    if scenario.comparable_count > 0:
        body.append(
            f"Analysis is based on {scenario.comparable_count} comparable properties."
        )
    
    # Standard disclosures
    disclosures = [
        "Estimates are ranges, not guarantees.",
        "Actual results depend on property condition, management, and market conditions.",
    ]
    
    return NarrativeBlock(
        block_type=NarrativeBlockType.PROJECTION_EXPLANATION,
        headline="Estimated Rental Performance",
        body=body,
        disclosures=disclosures,
        confidence=scenario.confidence_score,
    )


# =============================================================================
# PITCH BOOK SECTIONS
# =============================================================================

@dataclass
class PitchBookSection:
    """Base class for pitch book sections."""
    title: str
    content: Dict[str, Any] = field(default_factory=dict)
    narrative: Optional[NarrativeBlock] = None


@dataclass
class PropertySnapshot(PitchBookSection):
    """Property overview section."""
    title: str = "Property Overview"


@dataclass
class MarketContextSection(PitchBookSection):
    """Market context section."""
    title: str = "Market Context"


@dataclass
class ComparableInsightsSection(PitchBookSection):
    """Comparable properties section."""
    title: str = "Comparable Performance"


@dataclass
class ProjectionScenariosSection(PitchBookSection):
    """Projection scenarios section."""
    title: str = "Revenue Projections"
    scenarios: List[ProjectionScenario] = field(default_factory=list)


@dataclass
class UpsideAnalysisSection(PitchBookSection):
    """Upside opportunities section."""
    title: str = "Upside Opportunities"


@dataclass
class RiskDisclosureSection(PitchBookSection):
    """Risk disclosure section."""
    title: str = "Risk Considerations"


@dataclass
class NextStepsSection(PitchBookSection):
    """Next steps / CTA section."""
    title: str = "Next Steps"
    cta: str = "Schedule a consultation to discuss your property's potential."


# =============================================================================
# PITCH BOOK (Master Spec Requirement)
# =============================================================================

@dataclass
class PitchBook:
    """
    Composable, regeneratable pitch book per master spec.
    
    This is not a PDF template - it's a structured story.
    
    Key properties:
    - One analytics run → many outputs
    - Realtor version ≠ homeowner version
    - Updated data → regenerated deck in seconds
    """
    pitch_id: UUID = field(default_factory=uuid4)
    property_id: UUID = None
    
    # Core sections (per spec)
    property_snapshot: Optional[PropertySnapshot] = None
    market_context: Optional[MarketContextSection] = None
    comparable_insights: Optional[ComparableInsightsSection] = None
    projection_scenarios: Optional[ProjectionScenariosSection] = None
    upside_analysis: Optional[UpsideAnalysisSection] = None
    risk_disclosure: Optional[RiskDisclosureSection] = None
    next_steps: Optional[NextStepsSection] = None
    
    # Metadata
    generated_at: datetime = field(default_factory=datetime.utcnow)
    version: int = 1
    
    # Audience customization
    audience: str = "homeowner"  # homeowner, realtor, investor
    
    def get_sections(self) -> List[PitchBookSection]:
        """Get all non-null sections in order."""
        sections = [
            self.property_snapshot,
            self.market_context,
            self.comparable_insights,
            self.projection_scenarios,
            self.upside_analysis,
            self.risk_disclosure,
            self.next_steps,
        ]
        return [s for s in sections if s is not None]
    
    def to_outline(self) -> List[str]:
        """Get section titles as outline."""
        return [s.title for s in self.get_sections()]


# =============================================================================
# BD PROJECTION SUMMARY (Safe for Homeowner Outreach)
# =============================================================================

@dataclass
class ComparableSnapshot:
    """Summary of comparable properties used."""
    count: int
    avg_revenue: float
    avg_adr: float
    avg_occupancy: float
    similarity_description: str


@dataclass
class BDProjectionSummary:
    """
    Safe, compliant projection summary for homeowner outreach.
    
    Designed for credibility and compliance.
    """
    summary_id: UUID = field(default_factory=uuid4)
    property_id: UUID = None
    
    # Property snapshot
    property_address: Optional[str] = None
    property_description: str = ""
    
    # Projection ranges (NEVER single numbers)
    annual_revenue_low: float = 0.0
    annual_revenue_expected: float = 0.0
    annual_revenue_high: float = 0.0
    
    monthly_revenue_low: float = 0.0
    monthly_revenue_expected: float = 0.0
    monthly_revenue_high: float = 0.0
    
    # Key metrics
    estimated_adr_range: str = ""
    estimated_occupancy_range: str = ""
    
    # Comparable basis
    comparable_snapshot: Optional[ComparableSnapshot] = None
    
    # Assumptions (REQUIRED)
    assumptions_used: List[str] = field(default_factory=list)
    
    # Human-readable explanation
    methodology_summary: str = ""
    why_this_applies_to_you: str = ""
    
    # Confidence
    confidence_level: str = "medium"
    confidence_explanation: str = ""
    
    # Built-in disclaimers (REQUIRED)
    disclaimers: List[str] = field(default_factory=lambda: [
        "Projections are estimates based on comparable properties.",
        "Actual results may vary based on property condition, management, and market conditions.",
        "This is not a guarantee of income.",
    ])
    
    # CTA
    next_steps_cta: str = "Schedule a free consultation to discuss your property's potential."
    
    # Metadata
    generated_at: datetime = field(default_factory=datetime.utcnow)
    valid_until: Optional[datetime] = None
    
    @property
    def annual_range_formatted(self) -> str:
        return f"${self.annual_revenue_low:,.0f} - ${self.annual_revenue_high:,.0f}"
    
    @property
    def monthly_range_formatted(self) -> str:
        return f"${self.monthly_revenue_low:,.0f} - ${self.monthly_revenue_high:,.0f}"
    
    def to_email_snippet(self) -> str:
        return (
            f"Based on homes like yours in your area, properties similar to your "
            f"{self.property_description} typically earn between {self.annual_range_formatted} "
            f"per year as a vacation rental.\n\n"
            f"{self.why_this_applies_to_you}\n\n"
            f"{self.next_steps_cta}"
        )
    
    def to_voice_script(self) -> str:
        return (
            f"Based on similar homes in your area, your {self.property_description} "
            f"could potentially earn between {self.monthly_range_formatted} per month "
            f"as a short-term rental. "
            f"This estimate is based on {self.comparable_snapshot.count if self.comparable_snapshot else 'comparable'} "
            f"similar properties. {self.confidence_explanation}"
        )


# =============================================================================
# BD COMPLIANCE
# =============================================================================

@dataclass
class BDComplianceCheck:
    """Compliance validation for BD projections."""
    is_compliant: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def validate_bd_projection(summary: BDProjectionSummary) -> BDComplianceCheck:
    """
    Validate BD projection for compliance.
    
    Pure function - no IO.
    """
    violations = []
    warnings = []
    
    # Must have ranges
    if summary.annual_revenue_low == summary.annual_revenue_high:
        violations.append("Projection must show a range, not a single number")
    
    # Must have disclaimers
    if not summary.disclaimers:
        violations.append("Missing required disclaimers")
    
    # Must have assumptions
    if not summary.assumptions_used:
        violations.append("Missing assumptions disclosure")
    
    # Should have comparable basis
    if not summary.comparable_snapshot:
        warnings.append("No comparable data disclosed")
    
    # Check confidence
    if summary.confidence_level == "low":
        warnings.append("Low confidence projection - consider adding caveats")
    
    return BDComplianceCheck(
        is_compliant=len(violations) == 0,
        violations=violations,
        warnings=warnings,
    )


# =============================================================================
# BD LEAD SCORING
# =============================================================================

@dataclass
class BDLeadScore:
    """Scored lead for BD prioritization."""
    owner_id: UUID
    property_id: UUID
    
    opportunity_score: float
    contactability_score: float
    timing_score: float
    fit_score: float
    
    total_score: float = 0.0
    priority_rank: int = 0
    
    recommended_action: str = "email"
    recommended_message_type: str = "opportunity"
    
    def __post_init__(self):
        if self.total_score == 0:
            self.total_score = (
                self.opportunity_score * 0.40 +
                self.contactability_score * 0.25 +
                self.timing_score * 0.20 +
                self.fit_score * 0.15
            )


def rank_bd_leads(leads: List[BDLeadScore]) -> List[BDLeadScore]:
    """Rank BD leads by priority."""
    sorted_leads = sorted(leads, key=lambda l: l.total_score, reverse=True)
    for i, lead in enumerate(sorted_leads):
        lead.priority_rank = i + 1
    return sorted_leads


# =============================================================================
# ASSUMPTION OVERRIDES (Operator-Controlled Tightening)
# =============================================================================

class OccupancyMode(str, Enum):
    """Occupancy assumption mode."""
    CONSERVATIVE = "conservative"
    BASELINE = "baseline"
    OPTIMIZED = "optimized"


class ADRCeiling(str, Enum):
    """ADR ceiling mode."""
    CONSERVATIVE = "conservative"
    BASELINE = "baseline"
    OPTIMIZED = "optimized"


@dataclass
class AssumptionOverrides:
    """
    Operator-controlled assumption tightening.
    
    This does NOT re-run projections.
    It FILTERS and CONSTRAINS already-computed ranges.
    
    Usage:
        overrides = AssumptionOverrides(
            occupancy_mode=OccupancyMode.CONSERVATIVE,
            adr_ceiling=ADRCeiling.BASELINE,
            include_event_uplift=False,
        )
        synopsis = build_investment_synopsis(scenarios, overrides)
    """
    # Which scenario bounds to use
    occupancy_mode: OccupancyMode = OccupancyMode.BASELINE
    adr_ceiling: ADRCeiling = ADRCeiling.BASELINE
    
    # Feature toggles
    include_event_uplift: bool = True
    include_premium_furnishing_uplift: bool = True
    include_dynamic_pricing_uplift: bool = True
    
    # Penalties
    management_penalty_pct: float = 0.0  # 0-20%
    
    # Confidence floor (exclude scenarios below this)
    confidence_floor: float = 0.4
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for audit trail."""
        return {
            "occupancy_mode": self.occupancy_mode.value,
            "adr_ceiling": self.adr_ceiling.value,
            "include_event_uplift": self.include_event_uplift,
            "include_premium_furnishing_uplift": self.include_premium_furnishing_uplift,
            "include_dynamic_pricing_uplift": self.include_dynamic_pricing_uplift,
            "management_penalty_pct": self.management_penalty_pct,
            "confidence_floor": self.confidence_floor,
        }
    
    @classmethod
    def conservative(cls) -> "AssumptionOverrides":
        """Pre-built conservative preset."""
        return cls(
            occupancy_mode=OccupancyMode.CONSERVATIVE,
            adr_ceiling=ADRCeiling.BASELINE,
            include_event_uplift=False,
            include_premium_furnishing_uplift=False,
            include_dynamic_pricing_uplift=False,
            management_penalty_pct=5.0,
            confidence_floor=0.6,
        )
    
    @classmethod
    def realtor_safe(cls) -> "AssumptionOverrides":
        """Pre-built realtor-safe preset."""
        return cls(
            occupancy_mode=OccupancyMode.BASELINE,
            adr_ceiling=ADRCeiling.BASELINE,
            include_event_uplift=True,
            include_premium_furnishing_uplift=False,
            management_penalty_pct=0.0,
            confidence_floor=0.5,
        )
    
    @classmethod
    def homeowner_friendly(cls) -> "AssumptionOverrides":
        """Pre-built homeowner-friendly preset."""
        return cls(
            occupancy_mode=OccupancyMode.BASELINE,
            adr_ceiling=ADRCeiling.OPTIMIZED,
            include_event_uplift=True,
            include_premium_furnishing_uplift=True,
            management_penalty_pct=0.0,
            confidence_floor=0.4,
        )


@dataclass
class DisplayToggles:
    """
    UI display toggles for sections.
    
    Controls what appears in synopsis/pitchbook.
    Does NOT affect underlying intelligence.
    """
    show_conservative_scenario: bool = True
    show_baseline_scenario: bool = True
    show_optimized_scenario: bool = True
    
    show_upside_analysis: bool = True
    show_risk_factors: bool = True
    show_market_context: bool = True
    show_comparable_analysis: bool = True
    
    show_monthly_breakdown: bool = False
    show_sensitivity_drivers: bool = True
    show_assumptions_used: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for audit trail."""
        return {
            "show_conservative_scenario": self.show_conservative_scenario,
            "show_baseline_scenario": self.show_baseline_scenario,
            "show_optimized_scenario": self.show_optimized_scenario,
            "show_upside_analysis": self.show_upside_analysis,
            "show_risk_factors": self.show_risk_factors,
            "show_market_context": self.show_market_context,
            "show_comparable_analysis": self.show_comparable_analysis,
            "show_monthly_breakdown": self.show_monthly_breakdown,
            "show_sensitivity_drivers": self.show_sensitivity_drivers,
            "show_assumptions_used": self.show_assumptions_used,
        }


# =============================================================================
# TIGHTENED DISPLAY SCENARIO
# =============================================================================

@dataclass
class TightenedScenario:
    """
    A presentation-only scenario derived from base scenarios + overrides.
    
    This is what appears in UI and PDF.
    The underlying ProjectionScenarios are unchanged.
    """
    # Adjusted values (after applying overrides)
    revenue_low: float
    revenue_high: float
    adr_low: float
    adr_high: float
    occupancy_low: float
    occupancy_high: float
    
    # What constraints were applied
    constraints_applied: List[str] = field(default_factory=list)
    
    # Resulting confidence
    confidence_band: ConfidenceBand = ConfidenceBand.MEDIUM
    
    # For display
    @property
    def revenue_range_formatted(self) -> str:
        return f"${self.revenue_low:,.0f} - ${self.revenue_high:,.0f}"
    
    @property
    def monthly_range_formatted(self) -> str:
        monthly_low = self.revenue_low / 12
        monthly_high = self.revenue_high / 12
        return f"${monthly_low:,.0f} - ${monthly_high:,.0f}"


# =============================================================================
# INVESTMENT SYNOPSIS (Single Source for UI + PDF)
# =============================================================================

@dataclass
class InvestmentSynopsis:
    """
    Canonical synopsis object for UI and PDF.
    
    Generated once per toggle change.
    JSON-serializable.
    Renderable to UI or PDF.
    
    This is the SINGLE SOURCE OF TRUTH for presentation.
    """
    synopsis_id: UUID = field(default_factory=uuid4)
    property_id: UUID = field(default_factory=uuid4)
    
    # Property snapshot
    property_snapshot: Dict[str, Any] = field(default_factory=dict)
    
    # Market context
    market_context: Dict[str, Any] = field(default_factory=dict)
    
    # Base scenarios (immutable intelligence)
    conservative_scenario: Optional[ProjectionScenario] = None
    baseline_scenario: Optional[ProjectionScenario] = None
    optimized_scenario: Optional[ProjectionScenario] = None
    
    # Tightened scenario (after operator adjustments)
    tightened_scenario: Optional[TightenedScenario] = None
    
    # Analysis sections
    upside_drivers: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    
    # Assumptions
    original_assumptions: List[str] = field(default_factory=list)
    tightened_assumptions: List[str] = field(default_factory=list)
    
    # Comparable data
    comparable_count: int = 0
    comparable_summary: Optional[str] = None
    
    # Narratives
    narratives: Dict[str, NarrativeBlock] = field(default_factory=dict)
    
    # Audit metadata
    generated_at: datetime = field(default_factory=datetime.utcnow)
    overrides_applied: Optional[AssumptionOverrides] = None
    display_toggles: Optional[DisplayToggles] = None
    operator_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON response or storage."""
        return {
            "synopsis_id": str(self.synopsis_id),
            "property_id": str(self.property_id),
            "property_snapshot": self.property_snapshot,
            "market_context": self.market_context,
            "tightened_scenario": {
                "revenue_range": self.tightened_scenario.revenue_range_formatted if self.tightened_scenario else None,
                "monthly_range": self.tightened_scenario.monthly_range_formatted if self.tightened_scenario else None,
                "constraints_applied": self.tightened_scenario.constraints_applied if self.tightened_scenario else [],
                "confidence": self.tightened_scenario.confidence_band.value if self.tightened_scenario else None,
            } if self.tightened_scenario else None,
            "upside_drivers": self.upside_drivers,
            "risk_factors": self.risk_factors,
            "original_assumptions": self.original_assumptions,
            "tightened_assumptions": self.tightened_assumptions,
            "comparable_count": self.comparable_count,
            "generated_at": self.generated_at.isoformat(),
            "overrides_applied": self.overrides_applied.to_dict() if self.overrides_applied else None,
        }


def build_investment_synopsis(
    property_snapshot: Dict[str, Any],
    market_context: Dict[str, Any],
    conservative: ProjectionScenario,
    baseline: ProjectionScenario,
    optimized: ProjectionScenario,
    overrides: Optional[AssumptionOverrides] = None,
    toggles: Optional[DisplayToggles] = None,
    operator_id: Optional[str] = None,
) -> InvestmentSynopsis:
    """
    Build investment synopsis from scenarios + overrides.
    
    Pure function - no IO.
    
    This is the main entry point for synopsis generation.
    """
    if overrides is None:
        overrides = AssumptionOverrides()
    if toggles is None:
        toggles = DisplayToggles()
    
    # Apply overrides to compute tightened scenario
    tightened = _apply_overrides(conservative, baseline, optimized, overrides)
    
    # Collect assumptions
    original_assumptions = list(set(
        baseline.assumptions_used + 
        conservative.assumptions_used + 
        optimized.assumptions_used
    ))
    
    tightened_assumptions = list(tightened.constraints_applied)
    
    # Upside drivers (from optimized scenario)
    upside_drivers = optimized.sensitivity_drivers.copy() if optimized else []
    
    # Risk factors (from conservative scenario)
    risk_factors = []
    if conservative.confidence_score < 0.6:
        risk_factors.append("Limited comparable data")
    if "Seasonal compression" in str(conservative.sensitivity_drivers):
        risk_factors.append("Seasonal demand variations")
    
    # Generate narratives
    narratives = {}
    if baseline:
        narratives["projection"] = generate_projection_narrative(
            baseline, 
            property_snapshot.get("description", "this property")
        )
    
    return InvestmentSynopsis(
        property_id=property_snapshot.get("property_id", uuid4()),
        property_snapshot=property_snapshot,
        market_context=market_context,
        conservative_scenario=conservative if toggles.show_conservative_scenario else None,
        baseline_scenario=baseline if toggles.show_baseline_scenario else None,
        optimized_scenario=optimized if toggles.show_optimized_scenario else None,
        tightened_scenario=tightened,
        upside_drivers=upside_drivers if toggles.show_upside_analysis else [],
        risk_factors=risk_factors if toggles.show_risk_factors else [],
        original_assumptions=original_assumptions if toggles.show_assumptions_used else [],
        tightened_assumptions=tightened_assumptions,
        comparable_count=baseline.comparable_count if baseline else 0,
        narratives=narratives,
        overrides_applied=overrides,
        display_toggles=toggles,
        operator_id=operator_id,
    )


def _apply_overrides(
    conservative: ProjectionScenario,
    baseline: ProjectionScenario,
    optimized: ProjectionScenario,
    overrides: AssumptionOverrides,
) -> TightenedScenario:
    """
    Apply operator overrides to derive tightened display scenario.
    
    This does NOT change the underlying scenarios.
    It computes a presentation-only view.
    """
    constraints = []
    
    # Select occupancy bounds
    if overrides.occupancy_mode == OccupancyMode.CONSERVATIVE:
        occ_scenario = conservative
        constraints.append("Conservative occupancy")
    elif overrides.occupancy_mode == OccupancyMode.OPTIMIZED:
        occ_scenario = optimized
        constraints.append("Optimized occupancy")
    else:
        occ_scenario = baseline
    
    # Select ADR ceiling
    if overrides.adr_ceiling == ADRCeiling.CONSERVATIVE:
        adr_scenario = conservative
        constraints.append("Conservative ADR")
    elif overrides.adr_ceiling == ADRCeiling.OPTIMIZED:
        adr_scenario = optimized
    else:
        adr_scenario = baseline
        constraints.append("Baseline ADR cap")
    
    # Get base values
    revenue_low = conservative.annual_revenue.min if conservative.annual_revenue else 0
    revenue_high = baseline.annual_revenue.max if baseline.annual_revenue else 0
    
    adr_low = adr_scenario.adr.min if adr_scenario.adr else 0
    adr_high = adr_scenario.adr.max if adr_scenario.adr else 0
    
    occ_low = occ_scenario.occupancy.min if occ_scenario.occupancy else 0
    occ_high = occ_scenario.occupancy.max if occ_scenario.occupancy else 0
    
    # Apply feature toggles
    if not overrides.include_event_uplift:
        revenue_high *= 0.95  # Remove ~5% event uplift
        constraints.append("Event uplift excluded")
    
    if not overrides.include_premium_furnishing_uplift:
        revenue_high *= 0.92  # Remove ~8% premium uplift
        constraints.append("Premium furnishing uplift excluded")
    
    if not overrides.include_dynamic_pricing_uplift:
        revenue_high *= 0.97  # Remove ~3% dynamic pricing uplift
        constraints.append("Dynamic pricing uplift excluded")
    
    # Apply management penalty
    if overrides.management_penalty_pct > 0:
        penalty = 1 - (overrides.management_penalty_pct / 100)
        revenue_low *= penalty
        revenue_high *= penalty
        constraints.append(f"{overrides.management_penalty_pct:.0f}% management penalty")
    
    # Determine confidence
    if len(constraints) >= 3:
        confidence = ConfidenceBand.HIGH  # More constraints = more conservative = higher confidence
    elif len(constraints) >= 1:
        confidence = ConfidenceBand.MEDIUM
    else:
        confidence = baseline.confidence_band
    
    return TightenedScenario(
        revenue_low=revenue_low,
        revenue_high=revenue_high,
        adr_low=adr_low,
        adr_high=adr_high,
        occupancy_low=occ_low,
        occupancy_high=occ_high,
        constraints_applied=constraints,
        confidence_band=confidence,
    )


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    "ScenarioType",
    "ConfidenceBand",
    "NarrativeBlockType",
    "OccupancyMode",
    "ADRCeiling",
    
    # Projection Scenario
    "MetricRange",
    "ProjectionScenario",
    
    # Narrative Block
    "NarrativeBlock",
    "generate_projection_narrative",
    
    # Pitch Book
    "PitchBookSection",
    "PropertySnapshot",
    "MarketContextSection",
    "ComparableInsightsSection",
    "ProjectionScenariosSection",
    "UpsideAnalysisSection",
    "RiskDisclosureSection",
    "NextStepsSection",
    "PitchBook",
    
    # BD Summary
    "ComparableSnapshot",
    "BDProjectionSummary",
    
    # Compliance
    "BDComplianceCheck",
    "validate_bd_projection",
    
    # Lead Scoring
    "BDLeadScore",
    "rank_bd_leads",
    
    # Assumption Overrides (NEW)
    "AssumptionOverrides",
    "DisplayToggles",
    "TightenedScenario",
    
    # Investment Synopsis (NEW)
    "InvestmentSynopsis",
    "build_investment_synopsis",
]
