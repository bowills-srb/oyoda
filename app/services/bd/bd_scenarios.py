"""
BD Scenario - First-Class Operator Scoping.

Core Principle (Non-Negotiable):
Operators never modify signals or analytics.
They only define a BD lens that filters, gates, and ranks results.

📊 Analytics = objective market truth
🔍 BD Lens = "What subset do I want to look at?"

This preserves trust with owners, realtors, and enterprise buyers.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# ENUMS
# =============================================================================

class PropertyTypeFilter(str, Enum):
    """Property types for filtering."""
    SINGLE_FAMILY = "single_family"
    CONDO = "condo"
    TOWNHOUSE = "townhouse"
    VILLA = "villa"
    COTTAGE = "cottage"
    CABIN = "cabin"
    MULTI_UNIT = "multi_unit"


class BDAudience(str, Enum):
    """Target audience for BD scenario."""
    REALTOR = "realtor"
    OWNER = "owner"
    INVESTOR = "investor"
    INSTITUTIONAL = "institutional"


class BDPurpose(str, Enum):
    """Purpose of BD scenario."""
    ACQUISITION = "acquisition"
    EXPANSION = "expansion"
    PRICING_REVIEW = "pricing_review"
    PORTFOLIO_ANALYSIS = "portfolio_analysis"
    MARKET_ENTRY = "market_entry"


# =============================================================================
# GEO SCOPE
# =============================================================================

class GeoScopeType(str, Enum):
    """Type of geographic scope."""
    POLYGON = "polygon"
    ZIP_LIST = "zip_list"
    METRO = "metro"
    COUNTY = "county"
    STATE = "state"
    CUSTOM = "custom"


class GeoScope(BaseModel):
    """
    Geographic scope for BD scenario.
    
    Defines WHERE to look.
    """
    scope_type: GeoScopeType
    
    # For polygon scope
    polygon_id: Optional[str] = None
    polygon_coords: Optional[List[Tuple[float, float]]] = None
    
    # For zip list
    zip_codes: Optional[List[str]] = None
    
    # For metro/county/state
    region_id: Optional[str] = None
    region_name: Optional[str] = None
    
    # Radius-based (optional overlay)
    center_lat: Optional[float] = None
    center_lng: Optional[float] = None
    radius_miles: Optional[float] = None


# =============================================================================
# ASSET CONSTRAINTS (Pure Filtering, No Math)
# =============================================================================

class AssetConstraints(BaseModel):
    """
    Asset constraints for filtering.
    
    This is where "$2M+ properties" lives.
    Pure filtering, no recomputation.
    """
    # Value constraints
    min_estimated_value: Optional[int] = None  # e.g., 2_000_000
    max_estimated_value: Optional[int] = None
    
    # Property attributes
    min_bedrooms: Optional[int] = None
    max_bedrooms: Optional[int] = None
    min_bathrooms: Optional[float] = None
    max_bathrooms: Optional[float] = None
    min_sqft: Optional[int] = None
    max_sqft: Optional[int] = None
    
    # Property types
    property_types: Optional[List[PropertyTypeFilter]] = None
    
    # Amenity requirements
    required_amenities: Optional[List[str]] = None  # Must have ALL
    preferred_amenities: Optional[List[str]] = None  # Nice to have
    
    # Performance filters
    min_rent_potential_score: Optional[float] = Field(None, ge=0, le=100)
    min_adr: Optional[float] = None
    min_occupancy: Optional[float] = Field(None, ge=0, le=1)
    
    # Regulatory
    zoning_allowed: Optional[bool] = None
    hoa_str_allowed: Optional[bool] = None
    
    # Operator fit
    min_operator_fit_score: Optional[float] = Field(None, ge=0, le=100)


# =============================================================================
# SCORING PROFILE (Safe Customization)
# =============================================================================

class ScoringProfile(BaseModel):
    """
    Scoring profile for ranking within filtered set.
    
    Operators can emphasize what matters most.
    They CANNOT change raw signal values.
    
    This is presentation emphasis, not model tampering.
    """
    # Weights (must sum to 1.0)
    weight_cashflow: float = Field(default=0.30, ge=0, le=1)
    weight_appreciation: float = Field(default=0.20, ge=0, le=1)
    weight_seasonality_fit: float = Field(default=0.15, ge=0, le=1)
    weight_platform_dominance: float = Field(default=0.10, ge=0, le=1)
    weight_operator_fit: float = Field(default=0.15, ge=0, le=1)
    weight_risk_adjusted: float = Field(default=0.10, ge=0, le=1)
    
    @field_validator('weight_cashflow')
    @classmethod
    def validate_weights_sum(cls, v, info):
        """Weights should approximately sum to 1.0."""
        # Note: Full validation would check all weights together
        return v
    
    def get_weights_dict(self) -> Dict[str, float]:
        """Get weights as dictionary."""
        return {
            "cashflow": self.weight_cashflow,
            "appreciation": self.weight_appreciation,
            "seasonality_fit": self.weight_seasonality_fit,
            "platform_dominance": self.weight_platform_dominance,
            "operator_fit": self.weight_operator_fit,
            "risk_adjusted": self.weight_risk_adjusted,
        }


# =============================================================================
# BD SCENARIO (First-Class Object)
# =============================================================================

class BDScenario(BaseModel):
    """
    BD Scenario - Named, persisted scoping object.
    
    "Show me properties that meet these constraints,
    scored using our existing analytics,
    for this audience."
    
    NOT a UI filter. A first-class business object.
    """
    scenario_id: UUID = Field(default_factory=uuid4)
    operator_id: UUID
    tenant_id: UUID
    
    # Identity
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    
    # Geographic scope
    geo_scope: GeoScope
    
    # Asset constraints (filters)
    asset_constraints: AssetConstraints = Field(default_factory=AssetConstraints)
    
    # Scoring preferences (weights, not overrides)
    scoring_profile: ScoringProfile = Field(default_factory=ScoringProfile)
    
    # Presentation context
    audience: BDAudience = BDAudience.REALTOR
    purpose: BDPurpose = BDPurpose.ACQUISITION
    
    # Status
    is_active: bool = True
    is_template: bool = False  # Can be copied by others
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Luxury Gulf Coast Acquisitions",
                "description": "Properties $2M+ for investor presentation",
                "audience": "investor",
                "purpose": "acquisition",
            }
        }


# =============================================================================
# RANKED PROPERTY (Output)
# =============================================================================

class RankedProperty(BaseModel):
    """
    A property ranked within a BD scenario.
    
    Analytics unchanged - just ranked and explained.
    """
    property_id: UUID
    
    # Basic info
    address: str
    bedrooms: int
    bathrooms: float
    estimated_value: Optional[float] = None
    
    # Analytics (from unchanged engine)
    projected_adr: float
    projected_occupancy: float
    projected_annual_revenue: float
    confidence: float
    
    # Scenario-specific ranking
    rank: int
    composite_score: float  # Weighted score
    
    # Score breakdown
    score_breakdown: Dict[str, float] = Field(default_factory=dict)
    
    # Why it ranked here
    ranking_factors: List[str] = Field(default_factory=list)
    
    # Constraints it passed
    constraints_met: List[str] = Field(default_factory=list)


# =============================================================================
# BD SCENARIO RESULT (Shareable, Auditable Output)
# =============================================================================

class BDScenarioSummary(BaseModel):
    """Summary statistics for scenario results."""
    total_candidates: int
    total_after_filter: int
    
    median_adr: float
    median_occupancy: float
    
    expected_revenue_low: float
    expected_revenue_high: float
    
    avg_confidence: float


class BDScenarioDisclaimers(BaseModel):
    """
    Disclaimers for scenario results.
    
    TRUST RULE: Every result includes this.
    """
    confidence_level: float
    data_coverage_notes: List[str] = Field(default_factory=list)
    
    # Standard disclaimer (always included)
    standard_disclaimer: str = Field(
        default=(
            "Analytics are market-derived and unchanged by scenario filters. "
            "This view reflects a scoped subset for evaluation purposes only."
        )
    )
    
    # Additional caveats
    caveats: List[str] = Field(default_factory=list)


class BDScenarioResult(BaseModel):
    """
    BD Scenario Result - Shareable, auditable output.
    
    This is what gets:
    - Exported to PDF
    - Shared with a realtor
    - Shown to an owner
    """
    # Scenario reference
    scenario_id: UUID
    scenario_name: str
    
    # Operator context
    operator_id: UUID
    
    # Results
    properties: List[RankedProperty] = Field(default_factory=list)
    
    # Summary
    summary: BDScenarioSummary
    
    # Trust markers
    disclaimers: BDScenarioDisclaimers
    
    # Metadata
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None  # Results may become stale


# =============================================================================
# BD SCENARIO SERVICE
# =============================================================================

class BDScenarioService:
    """
    BD Scenario Service.
    
    Executes scenarios against the analytics engine.
    
    Flow:
    1. BD Scenario (filters + weights)
    2. Property Universe (geo-scoped)
    3. Asset Constraints (filter)
    4. Signal Bundle (UNCHANGED)
    5. Analytics Engine (UNCHANGED)
    6. Ranking + Explanation
    
    Nothing upstream changes. We slice reality, not edit it.
    """
    
    def __init__(self):
        self.version = "1.0.0"
    
    def execute_scenario(
        self,
        scenario: BDScenario,
        properties: List[Dict[str, Any]],  # Property universe
        signal_bundles: Dict[str, Any],     # Pre-computed bundles by geo
    ) -> BDScenarioResult:
        """
        Execute a BD scenario.
        
        Args:
            scenario: The scenario definition
            properties: Property universe to filter
            signal_bundles: Signal bundles keyed by geo_id
        
        Returns:
            BDScenarioResult with ranked properties
        """
        # Step 1: Filter by geo scope
        geo_filtered = self._filter_by_geo(properties, scenario.geo_scope)
        
        # Step 2: Filter by asset constraints
        constraint_filtered = self._filter_by_constraints(
            geo_filtered, scenario.asset_constraints
        )
        
        # Step 3: Score and rank
        ranked = self._score_and_rank(
            constraint_filtered,
            scenario.scoring_profile,
            signal_bundles,
        )
        
        # Step 4: Build summary
        summary = self._build_summary(ranked)
        
        # Step 5: Build disclaimers
        disclaimers = self._build_disclaimers(
            len(properties),
            len(constraint_filtered),
            ranked,
        )
        
        return BDScenarioResult(
            scenario_id=scenario.scenario_id,
            scenario_name=scenario.name,
            operator_id=scenario.operator_id,
            properties=ranked,
            summary=summary,
            disclaimers=disclaimers,
        )
    
    def _filter_by_geo(
        self,
        properties: List[Dict],
        geo_scope: GeoScope,
    ) -> List[Dict]:
        """Filter properties by geographic scope."""
        # Implementation would check coordinates/zips/regions
        # For now, return all (would be implemented with actual geo logic)
        return properties
    
    def _filter_by_constraints(
        self,
        properties: List[Dict],
        constraints: AssetConstraints,
    ) -> List[Dict]:
        """Filter properties by asset constraints."""
        filtered = []
        
        for prop in properties:
            # Check each constraint
            passes = True
            
            if constraints.min_estimated_value:
                if prop.get("estimated_value", 0) < constraints.min_estimated_value:
                    passes = False
            
            if constraints.max_estimated_value:
                if prop.get("estimated_value", float('inf')) > constraints.max_estimated_value:
                    passes = False
            
            if constraints.min_bedrooms:
                if prop.get("bedrooms", 0) < constraints.min_bedrooms:
                    passes = False
            
            if constraints.max_bedrooms:
                if prop.get("bedrooms", float('inf')) > constraints.max_bedrooms:
                    passes = False
            
            if constraints.property_types:
                if prop.get("property_type") not in [pt.value for pt in constraints.property_types]:
                    passes = False
            
            if constraints.required_amenities:
                prop_amenities = set(prop.get("amenities", []))
                if not all(a in prop_amenities for a in constraints.required_amenities):
                    passes = False
            
            if passes:
                filtered.append(prop)
        
        return filtered
    
    def _score_and_rank(
        self,
        properties: List[Dict],
        profile: ScoringProfile,
        signal_bundles: Dict,
    ) -> List[RankedProperty]:
        """Score and rank properties using weights."""
        weights = profile.get_weights_dict()
        scored = []
        
        for prop in properties:
            # Calculate component scores (0-100 scale)
            scores = {
                "cashflow": self._score_cashflow(prop),
                "appreciation": self._score_appreciation(prop),
                "seasonality_fit": self._score_seasonality(prop, signal_bundles),
                "platform_dominance": self._score_platform(prop, signal_bundles),
                "operator_fit": self._score_operator_fit(prop),
                "risk_adjusted": self._score_risk(prop),
            }
            
            # Weighted composite
            composite = sum(
                scores[k] * weights[k]
                for k in weights
            )
            
            scored.append({
                "property": prop,
                "composite": composite,
                "scores": scores,
            })
        
        # Sort by composite score
        scored.sort(key=lambda x: x["composite"], reverse=True)
        
        # Build ranked list
        ranked = []
        for i, item in enumerate(scored):
            prop = item["property"]
            
            ranked.append(RankedProperty(
                property_id=prop.get("property_id", uuid4()),
                address=prop.get("address", "Unknown"),
                bedrooms=prop.get("bedrooms", 0),
                bathrooms=prop.get("bathrooms", 0),
                estimated_value=prop.get("estimated_value"),
                projected_adr=prop.get("projected_adr", 0),
                projected_occupancy=prop.get("projected_occupancy", 0),
                projected_annual_revenue=prop.get("projected_annual_revenue", 0),
                confidence=prop.get("confidence", 0.5),
                rank=i + 1,
                composite_score=item["composite"],
                score_breakdown=item["scores"],
                ranking_factors=self._explain_ranking(item["scores"]),
            ))
        
        return ranked
    
    def _score_cashflow(self, prop: Dict) -> float:
        """Score property on cashflow potential."""
        revenue = prop.get("projected_annual_revenue", 0)
        # Normalize to 0-100
        return min(100, revenue / 1000)  # Simplified
    
    def _score_appreciation(self, prop: Dict) -> float:
        """Score property on appreciation potential."""
        return 60  # Placeholder
    
    def _score_seasonality(self, prop: Dict, bundles: Dict) -> float:
        """Score property on seasonality fit."""
        return 70  # Placeholder
    
    def _score_platform(self, prop: Dict, bundles: Dict) -> float:
        """Score property on platform distribution."""
        return 65  # Placeholder
    
    def _score_operator_fit(self, prop: Dict) -> float:
        """Score property on operator fit."""
        return prop.get("operator_fit_score", 60)
    
    def _score_risk(self, prop: Dict) -> float:
        """Score property on risk-adjusted basis."""
        confidence = prop.get("confidence", 0.5)
        return confidence * 100
    
    def _explain_ranking(self, scores: Dict[str, float]) -> List[str]:
        """Generate ranking explanation."""
        factors = []
        
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        
        for name, score in sorted_scores[:3]:
            readable = name.replace("_", " ").title()
            if score >= 80:
                factors.append(f"Strong {readable} ({score:.0f})")
            elif score >= 60:
                factors.append(f"Good {readable} ({score:.0f})")
        
        return factors
    
    def _build_summary(self, ranked: List[RankedProperty]) -> BDScenarioSummary:
        """Build summary statistics."""
        if not ranked:
            return BDScenarioSummary(
                total_candidates=0,
                total_after_filter=0,
                median_adr=0,
                median_occupancy=0,
                expected_revenue_low=0,
                expected_revenue_high=0,
                avg_confidence=0,
            )
        
        adrs = [p.projected_adr for p in ranked]
        occs = [p.projected_occupancy for p in ranked]
        revenues = [p.projected_annual_revenue for p in ranked]
        confs = [p.confidence for p in ranked]
        
        return BDScenarioSummary(
            total_candidates=len(ranked),
            total_after_filter=len(ranked),
            median_adr=sorted(adrs)[len(adrs) // 2] if adrs else 0,
            median_occupancy=sorted(occs)[len(occs) // 2] if occs else 0,
            expected_revenue_low=min(revenues) if revenues else 0,
            expected_revenue_high=max(revenues) if revenues else 0,
            avg_confidence=sum(confs) / len(confs) if confs else 0,
        )
    
    def _build_disclaimers(
        self,
        total_universe: int,
        total_filtered: int,
        ranked: List[RankedProperty],
    ) -> BDScenarioDisclaimers:
        """Build disclaimers for results."""
        notes = []
        caveats = []
        
        # Coverage notes
        filter_rate = total_filtered / total_universe if total_universe > 0 else 0
        if filter_rate < 0.1:
            notes.append(f"Only {filter_rate:.1%} of properties met constraints")
        
        # Confidence notes
        if ranked:
            avg_conf = sum(p.confidence for p in ranked) / len(ranked)
            if avg_conf < 0.6:
                caveats.append("Average confidence is below recommended threshold")
        
        return BDScenarioDisclaimers(
            confidence_level=avg_conf if ranked else 0,
            data_coverage_notes=notes,
            caveats=caveats,
        )


# =============================================================================
# CONVENIENCE
# =============================================================================

_service: Optional[BDScenarioService] = None


def get_bd_scenario_service() -> BDScenarioService:
    """Get BD scenario service singleton."""
    global _service
    if _service is None:
        _service = BDScenarioService()
    return _service


def create_scenario(
    operator_id: UUID,
    tenant_id: UUID,
    name: str,
    geo_scope: GeoScope,
    **kwargs,
) -> BDScenario:
    """
    Create a new BD scenario.
    
    Example:
        scenario = create_scenario(
            operator_id=op_id,
            tenant_id=tenant_id,
            name="Luxury Gulf Coast",
            geo_scope=GeoScope(scope_type=GeoScopeType.METRO, region_name="30A"),
            asset_constraints=AssetConstraints(min_estimated_value=2_000_000),
            audience=BDAudience.INVESTOR,
        )
    """
    return BDScenario(
        operator_id=operator_id,
        tenant_id=tenant_id,
        name=name,
        geo_scope=geo_scope,
        **kwargs,
    )


def execute_scenario(
    scenario: BDScenario,
    properties: List[Dict],
    signal_bundles: Dict,
) -> BDScenarioResult:
    """Execute a BD scenario."""
    return get_bd_scenario_service().execute_scenario(
        scenario, properties, signal_bundles
    )
