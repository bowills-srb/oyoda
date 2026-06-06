"""
Signal-Based Projection Adapter v2.0.

This module bridges the legacy RentProjectionEngine with the new signal architecture.

MIGRATION PATH:
1. Phase 1 (Current): Adapter fetches signals and converts to legacy inputs
2. Phase 2: Projection engine directly consumes SignalBundle
3. Phase 3: Legacy input types deprecated

This allows gradual migration without breaking existing functionality.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from pydantic import BaseModel, Field

from schemas.signals import (
    Signal,
    SignalBundle,
    SignalType,
    SignalScope,
    TimeWindow,
)
from app.services.weighting.signal_weighting import (
    SignalWeightingEngine,
    get_weighting_engine,
)


# =============================================================================
# SIGNAL-BASED INPUT BUILDERS
# =============================================================================

class SignalBasedInputBuilder:
    """
    Builds legacy projection inputs from signals.
    
    This is the bridge between:
    - New: SignalBundle from signal store
    - Legacy: PropertyInputs, MarketInputs, etc.
    """
    
    def __init__(self, weighting_engine: Optional[SignalWeightingEngine] = None):
        self.weighting = weighting_engine or get_weighting_engine()
    
    def build_amenity_config_from_signals(
        self,
        signals: SignalBundle,
        geo_id: str,
    ) -> Dict[str, float]:
        """
        Build amenity uplift configuration from AMENITY_LIFT signals.
        
        Falls back to defaults if signals not available.
        """
        # Default values (legacy behavior)
        defaults = {
            "pool": 1.10,
            "pool_heated": 1.05,
            "hot_tub": 1.08,
            "waterfront": 1.15,
            "waterfront_premium": 1.22,
            "pet_friendly": 1.03,
            "game_room": 1.04,
            "home_theater": 1.03,
            "elevator": 1.02,
            "dock": 1.08,
        }
        
        # Get amenity lift signals
        amenity_signals = signals.by_type(SignalType.AMENITY_LIFT)
        
        if not amenity_signals:
            return defaults
        
        # Build config from signals
        config = defaults.copy()
        
        for signal in amenity_signals:
            if not signal.structured_value:
                continue
            
            amenity = signal.structured_value.get("amenity")
            lift_pct = signal.structured_value.get("lift_percent", 0)
            
            if amenity and amenity in config:
                # Convert percentage to multiplier, weighted by confidence
                weighted_lift = (lift_pct / 100) * signal.confidence
                config[amenity] = 1.0 + weighted_lift
        
        return config
    
    def build_seasonality_from_signals(
        self,
        signals: SignalBundle,
        geo_id: str,
    ) -> Dict[int, Dict[str, float]]:
        """
        Build seasonality dictionary from SEASONALITY_CURVE signals.
        
        Returns: {month: {"occupancy": float, "rate": float}}
        """
        # Default seasonality (legacy behavior)
        defaults = {
            1: {"occupancy": 0.15, "rate": 0.70},
            2: {"occupancy": 0.20, "rate": 0.72},
            3: {"occupancy": 0.85, "rate": 1.10},
            4: {"occupancy": 0.45, "rate": 0.85},
            5: {"occupancy": 0.55, "rate": 0.95},
            6: {"occupancy": 0.92, "rate": 1.35},
            7: {"occupancy": 0.95, "rate": 1.45},
            8: {"occupancy": 0.75, "rate": 1.15},
            9: {"occupancy": 0.40, "rate": 0.78},
            10: {"occupancy": 0.45, "rate": 0.80},
            11: {"occupancy": 0.30, "rate": 0.72},
            12: {"occupancy": 0.25, "rate": 0.85},
        }
        
        # Get seasonality signal
        seasonality_signal = signals.most_recent(SignalType.SEASONALITY_CURVE)
        
        if not seasonality_signal or not seasonality_signal.structured_value:
            return defaults
        
        monthly_curve = seasonality_signal.structured_value.get("monthly_curve", {})
        
        if not monthly_curve:
            return defaults
        
        # Convert from {"jan": 0.7, ...} to {1: {"occupancy": x, "rate": y}, ...}
        month_map = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        
        result = {}
        for month_name, factor in monthly_curve.items():
            month_num = month_map.get(month_name.lower())
            if month_num:
                # Signal factor is relative demand, convert to rate multiplier
                # Assume occupancy scales with demand
                result[month_num] = {
                    "occupancy": min(0.95, factor * 0.65),  # Scale to occupancy
                    "rate": factor,  # Direct rate multiplier
                }
        
        # Fill in any missing months with defaults
        for month in range(1, 13):
            if month not in result:
                result[month] = defaults[month]
        
        return result
    
    def build_operator_delta_from_signals(
        self,
        signals: SignalBundle,
        geo_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Build operator delta from OPERATOR_DELTA signals.
        
        Returns dict compatible with OperatorPortfolio or None.
        """
        delta_signal = signals.most_recent(SignalType.OPERATOR_DELTA)
        
        if not delta_signal or not delta_signal.structured_value:
            return None
        
        sv = delta_signal.structured_value
        
        return {
            "adr_delta_pct": sv.get("adr_delta_pct", 0),
            "occupancy_delta_pct": sv.get("occupancy_delta_pct", 0),
            "confidence": delta_signal.confidence,
            "months_of_data": delta_signal.metadata.get("sample_size", 12),
        }
    
    def build_platform_context_from_signals(
        self,
        signals: SignalBundle,
        geo_id: str,
    ) -> Dict[str, Any]:
        """
        Build platform context from PLATFORM_DOMINANCE signals.
        """
        platform_signal = signals.most_recent(SignalType.PLATFORM_DOMINANCE)
        
        if not platform_signal or not platform_signal.structured_value:
            return {
                "dominant_platform": "airbnb",
                "platform_weights": {"airbnb": 0.6, "vrbo": 0.3, "other": 0.1},
                "confidence": 0.5,
            }
        
        sv = platform_signal.structured_value
        
        return {
            "dominant_platform": sv.get("dominant_platform", "airbnb"),
            "platform_weights": sv.get("distribution", {}),
            "confidence": platform_signal.confidence,
        }
    
    def get_price_elasticity_from_signals(
        self,
        signals: SignalBundle,
        geo_id: str,
    ) -> Tuple[float, float]:
        """
        Get price elasticity from signals.
        
        Returns: (elasticity, confidence)
        """
        elasticity_signal = signals.most_recent(SignalType.PRICE_ELASTICITY)
        
        if not elasticity_signal or not elasticity_signal.structured_value:
            return (-1.2, 0.5)  # Default moderate elasticity
        
        elasticity = elasticity_signal.structured_value.get("elasticity", -1.2)
        return (elasticity, elasticity_signal.confidence)
    
    def get_occupancy_momentum_from_signals(
        self,
        signals: SignalBundle,
        geo_id: str,
    ) -> Tuple[float, float]:
        """
        Get occupancy momentum from signals.
        
        Returns: (momentum_value, confidence)
        - Positive = ahead of pace
        - Negative = behind pace
        """
        momentum_signal = signals.most_recent(SignalType.OCCUPANCY_MOMENTUM)
        
        if not momentum_signal:
            return (0.0, 0.5)  # Neutral
        
        return (momentum_signal.value, momentum_signal.confidence)


# =============================================================================
# SIGNAL-BASED PROJECTION ENGINE (V2)
# =============================================================================

class SignalBasedProjectionEngine:
    """
    Projection engine that consumes signals directly.
    
    This is the TARGET architecture. It:
    1. Receives a SignalBundle
    2. Extracts what it needs
    3. Computes projections
    4. Returns confidence-gated outputs
    
    No raw data, no inline detection, pure synthesis.
    """
    
    def __init__(self):
        self.input_builder = SignalBasedInputBuilder()
        self.version = "2.0.0-signal-based"
    
    def generate_projection(
        self,
        property_attrs: Dict[str, Any],
        signals: SignalBundle,
        geo_id: str,
        projection_year: int = None,
        commission_rate: float = 0.20,
    ) -> Dict[str, Any]:
        """
        Generate projection from signals.
        
        Args:
            property_attrs: Property characteristics (bedrooms, amenities, etc.)
            signals: SignalBundle with all relevant signals
            geo_id: Geographic identifier
            projection_year: Year to project
            commission_rate: Commission rate to apply
        
        Returns:
            Projection result with confidence gating
        """
        projection_year = projection_year or datetime.now().year
        
        # =================================================================
        # STEP 1: Extract signal-based inputs
        # =================================================================
        
        # Amenity lifts from signals
        amenity_config = self.input_builder.build_amenity_config_from_signals(
            signals, geo_id
        )
        
        # Seasonality from signals
        seasonality = self.input_builder.build_seasonality_from_signals(
            signals, geo_id
        )
        
        # Operator delta from signals
        operator_delta = self.input_builder.build_operator_delta_from_signals(
            signals, geo_id
        )
        
        # Platform context from signals
        platform_context = self.input_builder.build_platform_context_from_signals(
            signals, geo_id
        )
        
        # =================================================================
        # STEP 2: Compute base ADR
        # =================================================================
        
        # Start with market baseline by bedroom count
        bedrooms = property_attrs.get("bedrooms", 3)
        
        # Market baseline ADR by bedroom (would come from signals in full implementation)
        baseline_adr = {
            1: 150, 2: 200, 3: 275, 4: 350, 5: 450, 6: 550, 7: 650, 8: 750
        }.get(bedrooms, 300)
        
        # =================================================================
        # STEP 3: Apply amenity uplifts
        # =================================================================
        
        adjusted_adr = float(baseline_adr)
        uplifts_applied = []
        
        amenity_mapping = {
            "has_pool": "pool",
            "pool": "pool",
            "pool_heated": "pool_heated",
            "has_hot_tub": "hot_tub",
            "hot_tub": "hot_tub",
            "has_waterfront": "waterfront",
            "waterfront": "waterfront",
            "pet_friendly": "pet_friendly",
            "has_game_room": "game_room",
            "game_room": "game_room",
        }
        
        for prop_key, amenity_key in amenity_mapping.items():
            if property_attrs.get(prop_key, False):
                factor = amenity_config.get(amenity_key, 1.0)
                if factor != 1.0:
                    adjusted_adr *= factor
                    uplifts_applied.append({
                        "amenity": amenity_key,
                        "factor": factor,
                    })
        
        # =================================================================
        # STEP 4: Apply operator delta (if available)
        # =================================================================
        
        if operator_delta and operator_delta.get("confidence", 0) > 0.5:
            adr_delta = operator_delta["adr_delta_pct"]
            # Conservative application: 50% of observed
            applied_delta = adr_delta * 0.5
            adjusted_adr *= (1 + applied_delta)
        
        # =================================================================
        # STEP 5: Generate monthly projections
        # =================================================================
        
        monthly_projections = []
        total_revenue = 0
        total_nights = 0
        
        days_in_month = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        month_names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        
        for month in range(1, 13):
            season = seasonality.get(month, {"occupancy": 0.5, "rate": 1.0})
            
            days = days_in_month[month]
            occupancy = season["occupancy"]
            rate_multiplier = season["rate"]
            
            nights_booked = int(days * occupancy)
            monthly_adr = adjusted_adr * rate_multiplier
            monthly_revenue = nights_booked * monthly_adr
            
            monthly_projections.append({
                "month": month,
                "month_name": month_names[month],
                "year": projection_year,
                "days_in_month": days,
                "projected_nights_booked": nights_booked,
                "projected_occupancy": occupancy,
                "avg_nightly_rate": round(monthly_adr, 2),
                "projected_revenue": round(monthly_revenue, 2),
            })
            
            total_revenue += monthly_revenue
            total_nights += nights_booked
        
        # =================================================================
        # STEP 6: Calculate confidence and ranges
        # =================================================================
        
        # Overall confidence from signal bundle
        signal_confidence = signals.overall_confidence
        
        # Adjust confidence based on signal coverage
        signal_types_needed = [
            SignalType.AMENITY_LIFT,
            SignalType.SEASONALITY_CURVE,
            SignalType.PLATFORM_DOMINANCE,
        ]
        signal_types_present = set(s.signal_type for s in signals.signals)
        coverage = sum(1 for t in signal_types_needed if t in signal_types_present) / len(signal_types_needed)
        
        final_confidence = signal_confidence * (0.5 + 0.5 * coverage)
        
        # Ranges based on confidence
        if final_confidence >= 0.7:
            low_factor, high_factor = 0.88, 1.15
        elif final_confidence >= 0.5:
            low_factor, high_factor = 0.82, 1.22
        else:
            low_factor, high_factor = 0.75, 1.30
        
        # =================================================================
        # STEP 7: Build result
        # =================================================================
        
        total_available = sum(days_in_month[1:13])
        overall_occupancy = total_nights / total_available
        overall_adr = total_revenue / total_nights if total_nights > 0 else adjusted_adr
        
        return {
            "engine_version": self.version,
            "computed_at": datetime.utcnow().isoformat(),
            "projection_year": projection_year,
            
            # Core metrics
            "avg_daily_rate": round(overall_adr, 2),
            "annual_occupancy": round(overall_occupancy, 3),
            
            # Revenue projections
            "gross_revenue": {
                "conservative": round(total_revenue * low_factor, 0),
                "expected": round(total_revenue, 0),
                "optimistic": round(total_revenue * high_factor, 0),
            },
            "net_revenue": {
                "conservative": round(total_revenue * low_factor * (1 - commission_rate), 0),
                "expected": round(total_revenue * (1 - commission_rate), 0),
                "optimistic": round(total_revenue * high_factor * (1 - commission_rate), 0),
            },
            
            # Monthly breakdown
            "monthly_projections": monthly_projections,
            
            # Confidence & gating
            "confidence": round(final_confidence, 3),
            "is_gated": final_confidence < 0.4,
            "gate_reason": "Insufficient signal confidence" if final_confidence < 0.4 else None,
            
            # Reasoning
            "reasoning": {
                "base_adr": baseline_adr,
                "uplifts_applied": uplifts_applied,
                "operator_delta_applied": operator_delta is not None,
                "platform_context": platform_context,
                "signal_count": len(signals.signals),
                "signal_coverage": coverage,
            },
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def generate_signal_based_projection(
    property_attrs: Dict[str, Any],
    signals: SignalBundle,
    geo_id: str,
    **kwargs
) -> Dict[str, Any]:
    """Convenience function for signal-based projections."""
    engine = SignalBasedProjectionEngine()
    return engine.generate_projection(property_attrs, signals, geo_id, **kwargs)
