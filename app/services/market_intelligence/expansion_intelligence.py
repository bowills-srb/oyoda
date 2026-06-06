"""
Market Expansion Intelligence Module v1.

Implements the 4 systems from the v1 Architecture spec:
1. Amenity Point Score (APS) v1 - Enhanced with full schema
2. Operator Similarity Scoring (OSS) - NEW
3. Market Expansion Dashboard Data Contract - NEW
4. Signal Confidence Visualization - Enhanced

These systems enable:
- Expansion market projections without internal data
- Operator skill transferability modeling
- Decision-support for market expansion
- Explainable confidence for voice/BD
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# 1. AMENITY POINT SCORE (APS) v1 - Full Schema
# =============================================================================

class APSOutput(BaseModel):
    """
    Amenity Point Score output - full v1 schema.
    
    APS quantifies the marginal pricing power of amenities by geography.
    Replaces flat multipliers with context-aware uplift scores.
    """
    market_id: str
    geo_hash: Optional[str] = None
    amenity: str
    
    # Saturation metrics
    saturation_rate: float  # 0-1, how common in market
    scarcity_index: float  # 1 - saturation_rate
    
    # Modifiers
    market_health_modifier: float  # From MHI, typically 0.9-1.2
    operator_performance_modifier: float  # From internal data, capped
    
    # Final score
    amenity_point_score: float  # Multiplicative ADR factor
    
    # Confidence
    confidence: float
    last_updated: date = Field(default_factory=date.today)
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "market_id": "PalmSprings_CA",
                "geo_hash": "9q5ct",
                "amenity": "pool",
                "saturation_rate": 0.78,
                "scarcity_index": 0.22,
                "market_health_modifier": 1.08,
                "operator_performance_modifier": 1.04,
                "amenity_point_score": 1.17,
                "confidence": 0.81,
                "last_updated": "2026-01-14"
            },
        },
    )


class APSCalculator:
    """
    Calculate Amenity Point Scores with full v1 logic.
    
    APS = Base Amenity Weight × Scarcity Index × Market Health Modifier × Operator Modifier
    
    Safeguards:
    - Operator modifier hard-capped at 1.15
    - Confidence decays with data age
    - APS never exceeds 1.50 (global bound)
    """
    
    # Base weights for amenities (neutral market)
    BASE_WEIGHTS = {
        "pool": 1.10,
        "pool_heated": 1.03,
        "hot_tub": 1.05,
        "waterfront": 1.20,
        "gulf_view": 1.12,
        "ocean_view": 1.10,
        "bay_view": 1.06,
        "lake_view": 1.05,
        "mountain_view": 1.04,
        "beach_access_private": 1.08,
        "beach_access_public": 1.03,
        "pet_friendly": 1.03,
        "dock": 1.05,
        "elevator": 1.03,
        "game_room": 1.02,
        "home_theater": 1.02,
        "ev_charger": 1.02,
    }
    
    # Hard caps
    MAX_OPERATOR_MODIFIER = 1.15
    MAX_APS = 1.50
    MIN_APS = 0.85
    
    def calculate(
        self,
        amenity: str,
        market_id: str,
        saturation_rate: float,
        market_health_score: float = 50.0,
        operator_performance_delta: Optional[float] = None,
        geo_hash: Optional[str] = None,
    ) -> APSOutput:
        """
        Calculate APS for an amenity in a market.
        
        Args:
            amenity: Amenity name
            market_id: Market identifier
            saturation_rate: 0-1, how common the amenity is
            market_health_score: 0-100 from MHI
            operator_performance_delta: Optional observed lift from operator data
            geo_hash: Optional sub-market identifier
        """
        # Base weight
        base_weight = self.BASE_WEIGHTS.get(amenity, 1.0)
        
        # Scarcity index (inverse of saturation)
        scarcity_index = 1.0 - saturation_rate
        
        # Scarcity multiplier (scarce = more valuable)
        # Maps scarcity_index to a 0.7-1.5 range
        if scarcity_index >= 0.8:
            scarcity_mult = 1.5
        elif scarcity_index >= 0.6:
            scarcity_mult = 1.3
        elif scarcity_index >= 0.4:
            scarcity_mult = 1.1
        elif scarcity_index >= 0.2:
            scarcity_mult = 0.9
        else:
            scarcity_mult = 0.7
        
        # Market health modifier (healthy market = amenities matter more)
        # Maps 0-100 score to 0.9-1.2 range
        market_health_modifier = 0.9 + (market_health_score / 100) * 0.3
        
        # Operator performance modifier (capped)
        if operator_performance_delta is not None:
            raw_operator_mod = 1.0 + operator_performance_delta
            operator_modifier = min(raw_operator_mod, self.MAX_OPERATOR_MODIFIER)
        else:
            operator_modifier = 1.0
        
        # Calculate APS
        raw_aps = base_weight * scarcity_mult * market_health_modifier * operator_modifier
        
        # Apply global bounds
        aps = max(min(raw_aps, self.MAX_APS), self.MIN_APS)
        
        # Calculate confidence
        confidence = self._calculate_confidence(
            has_operator_data=operator_performance_delta is not None,
            saturation_known=True,
            market_health_confidence=market_health_score / 100,
        )
        
        return APSOutput(
            market_id=market_id,
            geo_hash=geo_hash,
            amenity=amenity,
            saturation_rate=round(saturation_rate, 3),
            scarcity_index=round(scarcity_index, 3),
            market_health_modifier=round(market_health_modifier, 3),
            operator_performance_modifier=round(operator_modifier, 3),
            amenity_point_score=round(aps, 3),
            confidence=round(confidence, 2),
        )
    
    def _calculate_confidence(
        self,
        has_operator_data: bool,
        saturation_known: bool,
        market_health_confidence: float,
    ) -> float:
        """Calculate confidence in APS."""
        base = 0.5
        
        if saturation_known:
            base += 0.2
        
        if has_operator_data:
            base += 0.2
        
        base += market_health_confidence * 0.1
        
        return min(base, 0.95)


# =============================================================================
# 2. OPERATOR SIMILARITY SCORING (OSS) - NEW
# =============================================================================

class OSSOutput(BaseModel):
    """
    Operator Similarity Score output.
    
    Estimates how well an operator will perform in a new market
    based on their performance characteristics in existing markets.
    """
    operator_id: str
    source_market: str  # Market with known performance
    target_market: str  # Market being evaluated for expansion
    
    # Overall similarity
    similarity_score: float  # 0-1
    confidence: float
    
    # Transferable strengths
    transferable_strengths: List[str] = Field(default_factory=list)
    
    # Risk factors
    risk_factors: List[str] = Field(default_factory=list)
    
    # Dimension breakdown
    dimension_scores: Dict[str, float] = Field(default_factory=dict)
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "operator_id": "beach_habitats",
                "source_market": "30A_FL",
                "target_market": "HiltonHead_SC",
                "similarity_score": 0.74,
                "confidence": 0.69,
                "transferable_strengths": [
                    "luxury_waterfront",
                    "family_travel", 
                    "high_season_yield"
                ],
                "risk_factors": [
                    "shorter_season_length",
                    "higher_supply_growth"
                ]
            },
        },
    )


@dataclass
class MarketProfile:
    """Profile of a market for similarity comparison."""
    market_id: str
    
    # Property mix
    avg_bedrooms: float
    pct_luxury: float  # % of listings > $500/night
    pct_waterfront: float
    pct_pool: float
    
    # Seasonality
    peak_months: List[int]
    season_length_months: int
    peak_to_trough_ratio: float  # Peak ADR / Trough ADR
    
    # Market characteristics
    supply_growth_rate: float
    avg_occupancy: float
    market_density: str  # "dense", "moderate", "sparse"
    
    # Guest segments
    pct_family: float
    pct_couples: float
    pct_groups: float


@dataclass
class OperatorProfile:
    """Profile of an operator's characteristics."""
    operator_id: str
    
    # Property strategy
    avg_bedrooms: float
    pct_luxury: float
    pct_waterfront: float
    pct_pool: float
    
    # Pricing discipline
    adr_vs_market: float  # e.g., 1.12 = 12% above market
    occupancy_vs_market: float
    yield_consistency: float  # 0-1, how consistent across seasons
    
    # Experience
    markets_operated: int
    years_in_business: int
    
    # Strengths (default empty)
    strengths: List[str] = field(default_factory=list)


class OSSCalculator:
    """
    Calculate Operator Similarity Scores for expansion markets.
    
    Dimensions (from spec):
    - Property Type Mix: 25%
    - Amenity Strategy: 20%
    - Price Discipline: 20%
    - Seasonality Volatility: 15%
    - Guest Segment Focus: 10%
    - Market Density Experience: 10%
    
    OSS never CREATES performance - it gates how much can be transferred.
    """
    
    DIMENSION_WEIGHTS = {
        "property_type_mix": 0.25,
        "amenity_strategy": 0.20,
        "price_discipline": 0.20,
        "seasonality_volatility": 0.15,
        "guest_segment_focus": 0.10,
        "market_density_experience": 0.10,
    }
    
    # Known transferable strengths
    STRENGTH_INDICATORS = {
        "luxury_waterfront": lambda op, tm: op.pct_waterfront > 0.3 and tm.pct_waterfront > 0.2,
        "family_travel": lambda op, tm: tm.pct_family > 0.3,  # Market has family travel
        "high_season_yield": lambda op, tm: op.adr_vs_market > 1.1,
        "large_property_specialist": lambda op, tm: op.avg_bedrooms >= 4,
        "luxury_positioning": lambda op, tm: op.pct_luxury > 0.4,
    }
    
    # Known risk factors
    RISK_INDICATORS = {
        "shorter_season_length": lambda sm, tm: tm.season_length_months < sm.season_length_months - 2,
        "higher_supply_growth": lambda sm, tm: tm.supply_growth_rate > sm.supply_growth_rate + 0.03,
        "different_guest_mix": lambda sm, tm: abs(tm.pct_family - sm.pct_family) > 0.2,
        "higher_seasonality": lambda sm, tm: tm.peak_to_trough_ratio > sm.peak_to_trough_ratio * 1.3,
        "different_market_density": lambda sm, tm: sm.market_density != tm.market_density,
    }
    
    def calculate(
        self,
        operator: OperatorProfile,
        source_market: MarketProfile,
        target_market: MarketProfile,
    ) -> OSSOutput:
        """
        Calculate operator similarity score between markets.
        
        Args:
            operator: Operator's profile and characteristics
            source_market: Market where operator has performance data
            target_market: Market being evaluated for expansion
        """
        dimension_scores = {}
        
        # 1. Property Type Mix (25%)
        bedroom_sim = 1 - abs(operator.avg_bedrooms - target_market.avg_bedrooms) / 5
        luxury_sim = 1 - abs(operator.pct_luxury - target_market.pct_luxury)
        dimension_scores["property_type_mix"] = (bedroom_sim + luxury_sim) / 2
        
        # 2. Amenity Strategy (20%)
        waterfront_sim = 1 - abs(operator.pct_waterfront - target_market.pct_waterfront)
        pool_sim = 1 - abs(operator.pct_pool - target_market.pct_pool)
        dimension_scores["amenity_strategy"] = (waterfront_sim + pool_sim) / 2
        
        # 3. Price Discipline (20%)
        # Operators with strong discipline transfer better
        dimension_scores["price_discipline"] = min(operator.adr_vs_market - 0.9, 0.3) / 0.3
        
        # 4. Seasonality Volatility (15%)
        season_overlap = len(set(source_market.peak_months) & set(target_market.peak_months))
        season_sim = season_overlap / max(len(source_market.peak_months), 1)
        volatility_sim = 1 - abs(
            source_market.peak_to_trough_ratio - target_market.peak_to_trough_ratio
        ) / 3
        dimension_scores["seasonality_volatility"] = (season_sim + volatility_sim) / 2
        
        # 5. Guest Segment Focus (10%)
        family_sim = 1 - abs(source_market.pct_family - target_market.pct_family)
        dimension_scores["guest_segment_focus"] = family_sim
        
        # 6. Market Density Experience (10%)
        density_match = 1.0 if source_market.market_density == target_market.market_density else 0.5
        dimension_scores["market_density_experience"] = density_match
        
        # Calculate weighted score
        similarity_score = sum(
            score * self.DIMENSION_WEIGHTS[dim]
            for dim, score in dimension_scores.items()
        )
        
        # Identify transferable strengths
        strengths = [
            name for name, check in self.STRENGTH_INDICATORS.items()
            if check(operator, target_market)
        ]
        
        # Identify risk factors
        risks = [
            name for name, check in self.RISK_INDICATORS.items()
            if check(source_market, target_market)
        ]
        
        # Calculate confidence (lower if many risks)
        base_confidence = 0.75
        risk_penalty = len(risks) * 0.08
        confidence = max(base_confidence - risk_penalty, 0.4)
        
        return OSSOutput(
            operator_id=operator.operator_id,
            source_market=source_market.market_id,
            target_market=target_market.market_id,
            similarity_score=round(max(similarity_score, 0), 2),
            confidence=round(confidence, 2),
            transferable_strengths=strengths,
            risk_factors=risks,
            dimension_scores={k: round(v, 2) for k, v in dimension_scores.items()},
        )


# =============================================================================
# 3. MARKET EXPANSION DASHBOARD DATA CONTRACT - NEW
# =============================================================================

class MarketAttractiveness(BaseModel):
    """Market attractiveness ranking for expansion dashboard."""
    market_id: str
    market_name: str
    
    # Health & trends
    market_health_score: float  # 0-100
    supply_trend: str  # "+4.1%", "-2.3%"
    demand_trend: str  # "strengthening", "stable", "weakening"
    
    # Opportunity indicators
    event_density: str  # "high", "moderate", "low"
    amenity_opportunity_score: float  # APS-derived
    
    # Ranking
    attractiveness_rank: int
    
    class Config:
        json_schema_extra = {
            "example": {
                "market_id": "HiltonHead_SC",
                "market_name": "Hilton Head, SC",
                "market_health_score": 76,
                "supply_trend": "+4.1%",
                "demand_trend": "strengthening",
                "event_density": "moderate",
                "amenity_opportunity_score": 1.22,
                "attractiveness_rank": 3
            }
        }


class OperatorFitPanel(BaseModel):
    """Operator fit assessment for a target market."""
    operator_id: str
    target_market_id: str
    
    # OSS summary
    oss_score: float
    transferable_strengths: List[str]
    
    # Expected performance
    expected_uplift_low: float  # e.g., 0.03 = +3%
    expected_uplift_high: float
    
    # Confidence
    fit_confidence: float


class ExpansionProjectionPreview(BaseModel):
    """Projection preview for expansion market."""
    market_id: str
    property_type: str  # "5BR Luxury Waterfront"
    
    # Revenue ranges (wider than home markets)
    conservative: float
    expected: float
    optimistic: float
    
    # Confidence badge
    confidence_score: float
    confidence_badge: str  # "High", "Medium", "Exploratory"
    
    # Key assumptions
    assumptions: List[str]


class MarketExpansionDashboardData(BaseModel):
    """
    Complete data contract for Market Expansion Dashboard.
    
    This is a decision-support view, not a forecasting toy.
    """
    # Section A: Market Rankings
    market_rankings: List[MarketAttractiveness]
    
    # Section B: Operator Fit (for selected market)
    operator_fit: Optional[OperatorFitPanel] = None
    
    # Section C: Projection Preview (for selected market)
    projection_preview: Optional[ExpansionProjectionPreview] = None
    
    # Metadata
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    operator_id: str
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "market_rankings": [
                    {
                        "market_id": "HiltonHead_SC",
                        "market_health_score": 76,
                        "supply_trend": "+4.1%",
                        "demand_trend": "strengthening",
                        "amenity_opportunity_score": 1.22
                    }
                ],
                "operator_fit": {
                    "oss_score": 0.74,
                    "transferable_strengths": ["luxury_waterfront", "family_travel"]
                },
                "projection_preview": {
                    "conservative": 165000,
                    "expected": 195000,
                    "optimistic": 235000,
                    "confidence_badge": "Medium"
                }
            },
        },
    )


class ExpansionScoreOutput(BaseModel):
    """
    Combined expansion score for a market.
    
    This is the final output used for ranking.
    """
    market_id: str
    
    # Combined score
    expansion_score: float  # 0-1, weighted combination
    operator_fit: float  # OSS score
    confidence: float
    
    # Key drivers
    key_drivers: List[str]
    
    # Key risks
    key_risks: List[str]
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "market_id": "HiltonHead_SC",
                "expansion_score": 0.71,
                "operator_fit": 0.74,
                "confidence": 0.68,
                "key_drivers": [
                    "underserved luxury segment",
                    "strong summer compression"
                ],
                "key_risks": [
                    "short shoulder season",
                    "higher HOA restrictions"
                ]
            },
        },
    )


# =============================================================================
# 4. SIGNAL CONFIDENCE VISUALIZATION - Enhanced
# =============================================================================

class DataFreshness(str, Enum):
    """Data freshness indicators."""
    GREEN = "green"  # Fresh, high confidence
    YELLOW = "yellow"  # Aging, moderate confidence
    RED = "red"  # Stale, low confidence


class ConfidenceComposition(BaseModel):
    """
    Breakdown of confidence by source.
    
    Shows WHY a projection is trustworthy (or uncertain).
    Essential for BD credibility, operator trust, voice compliance.
    """
    # Overall confidence
    overall_confidence: float
    
    # Source composition (sums to 1.0)
    composition: Dict[str, float] = Field(
        default_factory=lambda: {
            "internal_operator_data": 0.0,
            "external_market_signals": 0.0,
            "seasonality_events": 0.0,
            "inference_extrapolation": 0.0,
        }
    )
    
    # Data freshness by signal type
    data_freshness: Dict[str, str] = Field(
        default_factory=lambda: {
            "supply_signals": "green",
            "availability_pressure": "green",
            "price_posture": "yellow",
            "events": "green",
        }
    )
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "overall_confidence": 0.73,
                "composition": {
                    "internal_operator_data": 0.42,
                    "external_market_signals": 0.38,
                    "seasonality_events": 0.12,
                    "inference_extrapolation": 0.08
                },
                "data_freshness": {
                    "supply_signals": "green",
                    "availability_pressure": "green", 
                    "price_posture": "yellow",
                    "events": "green"
                }
            },
        },
    )


class VoicePosture(str, Enum):
    """Voice posture based on confidence."""
    FIRM = "firm"  # > 0.80
    CONFIDENT_CAUTIOUS = "confident_cautious"  # 0.65-0.80
    EXPLORATORY = "exploratory"  # < 0.65


class ConfidenceVisualizer:
    """
    Generate confidence visualizations and voice alignment.
    
    Confidence States → Voice Posture:
    - > 0.80: Firm
    - 0.65-0.80: Confident but cautious
    - < 0.65: Exploratory / Escalate
    """
    
    # Voice phrases by confidence level
    VOICE_PHRASES = {
        VoicePosture.FIRM: [
            "Based on strong performance in this market...",
            "Our data shows consistent results for similar properties...",
            "We're confident in this projection based on extensive data...",
        ],
        VoicePosture.CONFIDENT_CAUTIOUS: [
            "Based on our analysis of comparable properties...",
            "Historical patterns suggest...",
            "We expect performance in line with similar homes...",
        ],
        VoicePosture.EXPLORATORY: [
            "Using early indicators from similar markets...",
            "Given limited historical data, ranges are wider...",
            "Based on preliminary analysis...",
        ],
    }
    
    def calculate_composition(
        self,
        has_internal_data: bool,
        internal_comp_count: int,
        internal_data_months: int,
        has_external_signals: bool,
        external_signal_confidence: float,
        has_event_data: bool,
    ) -> ConfidenceComposition:
        """
        Calculate confidence composition from available data sources.
        """
        composition = {
            "internal_operator_data": 0.0,
            "external_market_signals": 0.0,
            "seasonality_events": 0.0,
            "inference_extrapolation": 0.0,
        }
        
        total_weight = 0.0
        
        # Internal data contribution
        if has_internal_data and internal_comp_count >= 3:
            internal_weight = min(internal_comp_count / 10, 1.0) * 0.5
            internal_weight *= min(internal_data_months / 24, 1.0)
            composition["internal_operator_data"] = internal_weight
            total_weight += internal_weight
        
        # External signals contribution
        if has_external_signals:
            external_weight = external_signal_confidence * 0.4
            composition["external_market_signals"] = external_weight
            total_weight += external_weight
        
        # Event data contribution
        if has_event_data:
            event_weight = 0.15
            composition["seasonality_events"] = event_weight
            total_weight += event_weight
        
        # Inference fills the rest
        if total_weight < 1.0:
            composition["inference_extrapolation"] = 1.0 - total_weight
        
        # Normalize to sum to 1.0
        if total_weight > 0:
            for key in composition:
                composition[key] = round(composition[key] / max(total_weight, 1.0), 2)
        
        # Calculate overall confidence
        overall = (
            composition["internal_operator_data"] * 0.9 +
            composition["external_market_signals"] * 0.7 +
            composition["seasonality_events"] * 0.6 +
            composition["inference_extrapolation"] * 0.3
        )
        
        return ConfidenceComposition(
            overall_confidence=round(overall, 2),
            composition=composition,
        )
    
    def get_voice_posture(self, confidence: float) -> VoicePosture:
        """Get voice posture based on confidence level."""
        if confidence > 0.80:
            return VoicePosture.FIRM
        elif confidence >= 0.65:
            return VoicePosture.CONFIDENT_CAUTIOUS
        else:
            return VoicePosture.EXPLORATORY
    
    def get_voice_phrase(self, confidence: float) -> str:
        """Get appropriate voice phrase for confidence level."""
        posture = self.get_voice_posture(confidence)
        phrases = self.VOICE_PHRASES[posture]
        # Return first phrase (in production, could rotate)
        return phrases[0]
    
    def assess_data_freshness(
        self,
        supply_days_old: int,
        availability_days_old: int,
        price_days_old: int,
        events_days_old: int,
    ) -> Dict[str, str]:
        """Assess freshness of each signal type."""
        def freshness(days: int, fast_threshold: int = 3, slow_threshold: int = 14) -> str:
            if days <= fast_threshold:
                return DataFreshness.GREEN.value
            elif days <= slow_threshold:
                return DataFreshness.YELLOW.value
            else:
                return DataFreshness.RED.value
        
        return {
            "supply_signals": freshness(supply_days_old, 7, 21),
            "availability_pressure": freshness(availability_days_old, 3, 7),
            "price_posture": freshness(price_days_old, 7, 14),
            "events": freshness(events_days_old, 14, 30),
        }


# =============================================================================
# INTEGRATION: Expansion Market Projections
# =============================================================================

class ExpansionProjectionEngine:
    """
    Generate projections for expansion markets (no internal data).
    
    Uses:
    - OSS to gate operator delta transfer
    - APS for market-specific amenity scoring
    - Wider confidence bands
    """
    
    def __init__(self):
        self.aps_calculator = APSCalculator()
        self.oss_calculator = OSSCalculator()
        self.confidence_visualizer = ConfidenceVisualizer()
    
    def generate_expansion_projection(
        self,
        operator: OperatorProfile,
        source_market: MarketProfile,
        target_market: MarketProfile,
        property_bedrooms: int,
        property_amenities: List[str],
        target_market_health_score: float,
        amenity_saturations: Dict[str, float],
    ) -> Dict[str, Any]:
        """
        Generate projection for an expansion market.
        
        Key differences from existing market projections:
        1. Operator delta is gated by OSS
        2. Wider confidence bands
        3. More inference in confidence composition
        """
        # Calculate OSS
        oss = self.oss_calculator.calculate(operator, source_market, target_market)
        
        # Gate operator delta by OSS
        max_transferable_delta = oss.similarity_score * 0.5  # Max 50% transfer at perfect similarity
        gated_operator_delta = (operator.adr_vs_market - 1.0) * max_transferable_delta
        
        # Calculate APS for amenities
        amenity_multiplier = 1.0
        for amenity in property_amenities:
            if amenity in amenity_saturations:
                aps = self.aps_calculator.calculate(
                    amenity=amenity,
                    market_id=target_market.market_id,
                    saturation_rate=amenity_saturations[amenity],
                    market_health_score=target_market_health_score,
                    operator_performance_delta=gated_operator_delta if oss.confidence > 0.5 else None,
                )
                amenity_multiplier *= aps.amenity_point_score
        
        # Base ADR from market (no internal comps)
        base_adr_by_bedroom = {
            1: 200, 2: 300, 3: 450, 4: 600, 5: 800, 6: 1000, 7: 1200, 8: 1400
        }
        base_adr = base_adr_by_bedroom.get(property_bedrooms, 500)
        
        # Apply amenity multiplier
        adjusted_adr = base_adr * amenity_multiplier
        
        # Apply gated operator delta
        final_adr = adjusted_adr * (1 + gated_operator_delta)
        
        # Base occupancy (conservative for new market)
        base_occupancy = 0.42  # Lower than existing markets
        
        # Annual projection
        annual_revenue = final_adr * 365 * base_occupancy
        
        # Confidence composition (heavy on inference for expansion)
        confidence = self.confidence_visualizer.calculate_composition(
            has_internal_data=False,
            internal_comp_count=0,
            internal_data_months=0,
            has_external_signals=True,
            external_signal_confidence=target_market_health_score / 100,
            has_event_data=True,
        )
        
        # Wider bands for expansion markets
        if confidence.overall_confidence >= 0.6:
            low_factor, high_factor = 0.75, 1.30
        else:
            low_factor, high_factor = 0.65, 1.45
        
        return {
            "market_id": target_market.market_id,
            "oss_score": oss.similarity_score,
            "gated_operator_delta": round(gated_operator_delta, 3),
            "amenity_multiplier": round(amenity_multiplier, 3),
            "base_adr": round(base_adr, 0),
            "final_adr": round(final_adr, 0),
            "projected_occupancy": round(base_occupancy, 3),
            "annual_revenue": {
                "conservative": round(annual_revenue * low_factor, 0),
                "expected": round(annual_revenue, 0),
                "optimistic": round(annual_revenue * high_factor, 0),
            },
            "confidence": confidence.model_dump(),
            "voice_posture": self.confidence_visualizer.get_voice_posture(
                confidence.overall_confidence
            ).value,
            "voice_phrase": self.confidence_visualizer.get_voice_phrase(
                confidence.overall_confidence
            ),
            "transferable_strengths": oss.transferable_strengths,
            "risk_factors": oss.risk_factors,
        }
