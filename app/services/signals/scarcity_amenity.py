"""
Scarcity-Weighted Amenity Uplift

Enhancement to the base amenity lift service that:
1. Ties uplift dynamically to prevalence (scarcity effect)
2. Implements amenity saturation effect
3. Adjusts for seasonal relevance

Key insight: Amenity value increases when:
- Prevalence is low (scarcity)
- Demand is high (competition)

Amenity value decreases when:
- Prevalence is high (saturation)
- It becomes expected, not differentiated

Usage:
    from app.services.signals.scarcity_amenity import ScarcityWeightedAmenityEngine
    
    engine = ScarcityWeightedAmenityEngine()
    adjusted_lift = engine.calculate_scarcity_adjusted_lift(
        base_lift=0.15,
        prevalence=0.25,
        demand_level=0.7,
    )
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import math


# =============================================================================
# CONFIGURATION
# =============================================================================

class AmenityCategory(str, Enum):
    """Amenity categories for scarcity calculation."""
    PREMIUM = "premium"         # Pool, waterfront, view
    CONVENIENCE = "convenience" # Pet-friendly, parking, EV
    ENTERTAINMENT = "entertainment"  # Game room, theater
    ACCESSIBILITY = "accessibility"  # Elevator, single-level


# Amenity to category mapping
AMENITY_CATEGORIES = {
    "pool": AmenityCategory.PREMIUM,
    "pool_heated": AmenityCategory.PREMIUM,
    "hot_tub": AmenityCategory.PREMIUM,
    "waterfront": AmenityCategory.PREMIUM,
    "water_view": AmenityCategory.PREMIUM,
    "gulf_view": AmenityCategory.PREMIUM,
    "ocean_view": AmenityCategory.PREMIUM,
    "beach_access": AmenityCategory.PREMIUM,
    "private_beach": AmenityCategory.PREMIUM,
    "dock": AmenityCategory.PREMIUM,
    "boat_slip": AmenityCategory.PREMIUM,
    
    "pet_friendly": AmenityCategory.CONVENIENCE,
    "ev_charger": AmenityCategory.CONVENIENCE,
    "garage": AmenityCategory.CONVENIENCE,
    "parking": AmenityCategory.CONVENIENCE,
    
    "game_room": AmenityCategory.ENTERTAINMENT,
    "home_theater": AmenityCategory.ENTERTAINMENT,
    "arcade": AmenityCategory.ENTERTAINMENT,
    "pool_table": AmenityCategory.ENTERTAINMENT,
    
    "elevator": AmenityCategory.ACCESSIBILITY,
    "single_level": AmenityCategory.ACCESSIBILITY,
    "wheelchair_accessible": AmenityCategory.ACCESSIBILITY,
}

# Scarcity curve parameters by category
# (max_boost, saturation_point, curve_steepness)
SCARCITY_PARAMS = {
    AmenityCategory.PREMIUM: (0.3, 0.6, 2.0),      # Up to 30% boost, saturates at 60% prevalence
    AmenityCategory.CONVENIENCE: (0.15, 0.5, 1.5),  # Up to 15% boost
    AmenityCategory.ENTERTAINMENT: (0.1, 0.4, 1.5), # Up to 10% boost
    AmenityCategory.ACCESSIBILITY: (0.1, 0.3, 1.0), # Up to 10% boost
}

# Seasonal relevance (month -> category boost)
SEASONAL_RELEVANCE = {
    # Summer (June-Aug): Pool is king
    6: {AmenityCategory.PREMIUM: 1.2},
    7: {AmenityCategory.PREMIUM: 1.3},
    8: {AmenityCategory.PREMIUM: 1.2},
    
    # Winter (Dec-Feb): Heated amenities matter more
    12: {"pool_heated": 1.2, "hot_tub": 1.3},
    1: {"pool_heated": 1.2, "hot_tub": 1.3},
    2: {"pool_heated": 1.2, "hot_tub": 1.3},
}


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class ScarcityAdjustedLift:
    """Result of scarcity-adjusted amenity lift calculation."""
    amenity: str
    category: AmenityCategory
    
    # Original lift
    base_lift: float
    
    # Scarcity adjustment
    prevalence: float
    scarcity_multiplier: float
    
    # Demand adjustment
    demand_level: float
    demand_multiplier: float
    
    # Seasonal adjustment
    seasonal_multiplier: float
    
    # Final adjusted lift
    adjusted_lift: float
    
    # Confidence
    confidence: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "amenity": self.amenity,
            "category": self.category.value,
            "base_lift": round(self.base_lift, 4),
            "prevalence": round(self.prevalence, 4),
            "scarcity_multiplier": round(self.scarcity_multiplier, 3),
            "demand_multiplier": round(self.demand_multiplier, 3),
            "seasonal_multiplier": round(self.seasonal_multiplier, 3),
            "adjusted_lift": round(self.adjusted_lift, 4),
            "confidence": round(self.confidence, 3),
        }


@dataclass
class AmenityScarcityAnalysis:
    """Complete scarcity analysis for a market."""
    geo_id: str
    analyzed_at: datetime
    
    # Per-amenity results
    amenity_lifts: Dict[str, ScarcityAdjustedLift] = field(default_factory=dict)
    
    # Market-level metrics
    avg_scarcity_boost: float = 0.0
    most_scarce_amenity: Optional[str] = None
    most_saturated_amenity: Optional[str] = None
    
    # Differentiation opportunities
    differentiation_opportunities: List[str] = field(default_factory=list)


# =============================================================================
# SCARCITY CALCULATION ENGINE
# =============================================================================

class ScarcityWeightedAmenityEngine:
    """
    Calculates scarcity-adjusted amenity uplifts.
    
    Core formula:
        adjusted_lift = base_lift × scarcity_multiplier × demand_multiplier × seasonal_multiplier
    
    Where:
        scarcity_multiplier = 1 + max_boost × (1 - prevalence/saturation_point)^steepness
        demand_multiplier = 1 + (demand_level - 0.5) × 0.4  # -20% to +20%
        seasonal_multiplier = from lookup tables
    """
    
    def __init__(self):
        self.amenity_categories = AMENITY_CATEGORIES
        self.scarcity_params = SCARCITY_PARAMS
        self.seasonal_relevance = SEASONAL_RELEVANCE
    
    def calculate_scarcity_adjusted_lift(
        self,
        amenity: str,
        base_lift: float,
        prevalence: float,
        demand_level: float = 0.5,
        month: Optional[int] = None,
        confidence: float = 0.7,
    ) -> ScarcityAdjustedLift:
        """
        Calculate scarcity-adjusted lift for an amenity.
        
        Args:
            amenity: Amenity name
            base_lift: Base ADR lift (e.g., 0.15 = +15%)
            prevalence: Prevalence in market (0-1)
            demand_level: Current demand level (0-1, 0.5 = normal)
            month: Month for seasonal adjustment (1-12)
            confidence: Confidence in base lift
            
        Returns:
            ScarcityAdjustedLift with all adjustments
        """
        month = month or datetime.utcnow().month
        
        # Get category
        category = self.amenity_categories.get(amenity, AmenityCategory.CONVENIENCE)
        
        # Calculate scarcity multiplier
        scarcity_mult = self._calculate_scarcity_multiplier(category, prevalence)
        
        # Calculate demand multiplier
        demand_mult = self._calculate_demand_multiplier(demand_level)
        
        # Calculate seasonal multiplier
        seasonal_mult = self._calculate_seasonal_multiplier(amenity, category, month)
        
        # Apply all multipliers
        adjusted_lift = base_lift * scarcity_mult * demand_mult * seasonal_mult
        
        # Cap adjusted lift at reasonable bounds
        max_lift = base_lift * 2.0  # Never more than 2x base
        min_lift = base_lift * 0.3  # Never less than 0.3x base
        adjusted_lift = max(min_lift, min(max_lift, adjusted_lift))
        
        return ScarcityAdjustedLift(
            amenity=amenity,
            category=category,
            base_lift=base_lift,
            prevalence=prevalence,
            scarcity_multiplier=scarcity_mult,
            demand_level=demand_level,
            demand_multiplier=demand_mult,
            seasonal_multiplier=seasonal_mult,
            adjusted_lift=adjusted_lift,
            confidence=confidence * min(scarcity_mult, 1.2),  # Boost confidence when scarce
        )
    
    def _calculate_scarcity_multiplier(
        self,
        category: AmenityCategory,
        prevalence: float,
    ) -> float:
        """
        Calculate scarcity multiplier.
        
        Lower prevalence = higher multiplier (more valuable when rare).
        """
        max_boost, saturation_point, steepness = self.scarcity_params.get(
            category, (0.1, 0.5, 1.0)
        )
        
        if prevalence >= saturation_point:
            # Saturated - no scarcity boost, actually a penalty
            over_saturation = (prevalence - saturation_point) / (1 - saturation_point)
            return 1.0 - (over_saturation * 0.2)  # Up to 20% penalty
        
        # Below saturation - scarcity boost
        scarcity_ratio = 1 - (prevalence / saturation_point)
        boost = max_boost * (scarcity_ratio ** steepness)
        
        return 1.0 + boost
    
    def _calculate_demand_multiplier(self, demand_level: float) -> float:
        """
        Calculate demand multiplier.
        
        High demand = amenities more valuable (competition).
        """
        # Normalize demand to -0.5 to +0.5 range
        normalized = demand_level - 0.5
        
        # -20% to +20% adjustment
        adjustment = normalized * 0.4
        
        return 1.0 + adjustment
    
    def _calculate_seasonal_multiplier(
        self,
        amenity: str,
        category: AmenityCategory,
        month: int,
    ) -> float:
        """
        Calculate seasonal relevance multiplier.
        """
        seasonal = self.seasonal_relevance.get(month, {})
        
        # Check for amenity-specific boost
        if amenity in seasonal:
            return seasonal[amenity]
        
        # Check for category boost
        if category in seasonal:
            return seasonal[category]
        
        return 1.0
    
    def analyze_market_scarcity(
        self,
        amenity_data: List[Dict],
        demand_level: float = 0.5,
        geo_id: str = "",
    ) -> AmenityScarcityAnalysis:
        """
        Analyze scarcity across all amenities in a market.
        
        Args:
            amenity_data: List of dicts with amenity, base_lift, prevalence
            demand_level: Current market demand level
            geo_id: Market identifier
            
        Returns:
            AmenityScarcityAnalysis with full market analysis
        """
        now = datetime.utcnow()
        month = now.month
        
        analysis = AmenityScarcityAnalysis(
            geo_id=geo_id,
            analyzed_at=now,
        )
        
        if not amenity_data:
            return analysis
        
        # Calculate adjusted lift for each amenity
        scarcity_boosts = []
        min_prevalence = (None, 1.0)
        max_prevalence = (None, 0.0)
        
        for item in amenity_data:
            amenity = item.get("amenity")
            base_lift = item.get("base_lift", item.get("lift_pct", 0.1))
            prevalence = item.get("prevalence", item.get("prevalence_pct", 0.5))
            confidence = item.get("confidence", 0.7)
            
            result = self.calculate_scarcity_adjusted_lift(
                amenity=amenity,
                base_lift=base_lift,
                prevalence=prevalence,
                demand_level=demand_level,
                month=month,
                confidence=confidence,
            )
            
            analysis.amenity_lifts[amenity] = result
            scarcity_boosts.append(result.scarcity_multiplier - 1.0)
            
            # Track min/max prevalence
            if prevalence < min_prevalence[1]:
                min_prevalence = (amenity, prevalence)
            if prevalence > max_prevalence[1]:
                max_prevalence = (amenity, prevalence)
        
        # Calculate market-level metrics
        if scarcity_boosts:
            analysis.avg_scarcity_boost = sum(scarcity_boosts) / len(scarcity_boosts)
        
        analysis.most_scarce_amenity = min_prevalence[0]
        analysis.most_saturated_amenity = max_prevalence[0]
        
        # Identify differentiation opportunities
        # Amenities with high scarcity boost and reasonable base lift
        opportunities = []
        for amenity, result in analysis.amenity_lifts.items():
            if result.scarcity_multiplier > 1.15 and result.base_lift > 0.05:
                opportunities.append(amenity)
        
        analysis.differentiation_opportunities = sorted(
            opportunities,
            key=lambda a: analysis.amenity_lifts[a].adjusted_lift,
            reverse=True,
        )[:5]
        
        return analysis
    
    def get_property_adjusted_lift(
        self,
        property_amenities: List[str],
        market_amenity_data: List[Dict],
        demand_level: float = 0.5,
    ) -> Tuple[float, float, List[ScarcityAdjustedLift]]:
        """
        Calculate total scarcity-adjusted lift for a property.
        
        Args:
            property_amenities: Amenities the property has
            market_amenity_data: Market amenity data with prevalence
            demand_level: Current demand level
            
        Returns:
            Tuple of (total_lift, avg_confidence, details)
        """
        # Build lookup
        market_data = {item.get("amenity"): item for item in market_amenity_data}
        
        details = []
        total_multiplier = 1.0
        confidences = []
        
        for amenity in property_amenities:
            if amenity not in market_data:
                continue
            
            item = market_data[amenity]
            
            result = self.calculate_scarcity_adjusted_lift(
                amenity=amenity,
                base_lift=item.get("base_lift", item.get("lift_pct", 0.05)),
                prevalence=item.get("prevalence", item.get("prevalence_pct", 0.5)),
                demand_level=demand_level,
                confidence=item.get("confidence", 0.7),
            )
            
            details.append(result)
            total_multiplier *= (1 + result.adjusted_lift)
            confidences.append(result.confidence)
        
        total_lift = total_multiplier - 1.0
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5
        
        return total_lift, avg_confidence, details


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def calculate_scarcity_adjusted_lift(
    amenity: str,
    base_lift: float,
    prevalence: float,
    demand_level: float = 0.5,
) -> ScarcityAdjustedLift:
    """Calculate scarcity-adjusted lift (convenience function)."""
    engine = ScarcityWeightedAmenityEngine()
    return engine.calculate_scarcity_adjusted_lift(
        amenity, base_lift, prevalence, demand_level
    )


def analyze_market_amenity_scarcity(
    amenity_data: List[Dict],
    demand_level: float = 0.5,
    geo_id: str = "",
) -> AmenityScarcityAnalysis:
    """Analyze market amenity scarcity (convenience function)."""
    engine = ScarcityWeightedAmenityEngine()
    return engine.analyze_market_scarcity(amenity_data, demand_level, geo_id)
