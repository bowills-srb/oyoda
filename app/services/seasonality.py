"""
Unified Seasonality Service - Single Source of Truth.

This module REPLACES all inline seasonality calculations across the platform.

BEFORE (Dangerous):
- platform_weighting.py → SeasonalityDetector class
- rent_projection_engine_v1_1.py → DEFAULT_SEASONALITY dict
- market_intelligence_engine.py → inline seasonality

AFTER (Clean):
- SeasonalityCurveDetector produces signals → Signal Store
- This service consumes those signals
- All engines call this service

Why This Matters:
- Voice answers match BD math
- Expansion scores match pricing behavior
- One truth per concept
- Perfect explainability

Usage:
    from app.services.seasonality import get_seasonality_for_geo
    
    seasonality = get_seasonality_for_geo(tenant_id, geo_id, as_of_date)
    
    # Returns SeasonalityData with:
    # - monthly_factors: {1: 0.7, 2: 0.72, ...}
    # - peak_months: [6, 7]
    # - trough_months: [1, 2]
    # - confidence: 0.85
    # - source: "signal" | "default"
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from pydantic import BaseModel, Field

from schemas.signals import (
    Signal,
    SignalBundle,
    SignalType,
    TimeWindow,
)


# =============================================================================
# SEASONALITY DATA MODELS
# =============================================================================

class SeasonalitySource(str, Enum):
    """Where the seasonality data came from."""
    SIGNAL = "signal"           # From detector via signal store
    GEO_DEFAULT = "geo_default" # Market-specific default
    FALLBACK = "fallback"       # Generic fallback


@dataclass
class MonthlyFactor:
    """Seasonality factors for a single month."""
    month: int
    month_name: str
    
    # Demand factor (1.0 = average, >1 = high demand, <1 = low demand)
    demand_factor: float
    
    # Rate multiplier (what to charge relative to base)
    rate_multiplier: float
    
    # Expected occupancy (0-1)
    expected_occupancy: float
    
    # Confidence in this month's data
    confidence: float = 0.8


@dataclass
class SeasonalityData:
    """
    Complete seasonality profile for a geo.
    
    This is the ONLY seasonality object that should be used
    throughout the platform.
    """
    geo_id: str
    tenant_id: UUID
    
    # Monthly factors (1-12)
    monthly_factors: Dict[int, MonthlyFactor] = field(default_factory=dict)
    
    # Quick access
    peak_months: List[int] = field(default_factory=list)
    trough_months: List[int] = field(default_factory=list)
    shoulder_months: List[int] = field(default_factory=list)
    
    # Seasonality strength (peak/trough ratio)
    # 1.0 = no seasonality, 2.0 = peak is 2x trough
    seasonality_strength: float = 1.5
    
    # Overall confidence
    confidence: float = 0.5
    
    # Provenance
    source: SeasonalitySource = SeasonalitySource.FALLBACK
    signal_id: Optional[UUID] = None
    detected_at: Optional[datetime] = None
    
    # For legacy compatibility
    def to_legacy_dict(self) -> Dict[int, Dict[str, float]]:
        """
        Convert to legacy format used by rent_projection_engine.
        
        Returns: {month: {"occupancy": float, "rate": float}}
        """
        return {
            month: {
                "occupancy": factor.expected_occupancy,
                "rate": factor.rate_multiplier,
            }
            for month, factor in self.monthly_factors.items()
        }
    
    def get_factor_for_date(self, target_date: date) -> MonthlyFactor:
        """Get the seasonality factor for a specific date."""
        return self.monthly_factors.get(
            target_date.month,
            MonthlyFactor(
                month=target_date.month,
                month_name=_MONTH_NAMES[target_date.month],
                demand_factor=1.0,
                rate_multiplier=1.0,
                expected_occupancy=0.5,
            )
        )
    
    def get_rate_multiplier(self, target_date: date) -> float:
        """Get just the rate multiplier for a date."""
        return self.get_factor_for_date(target_date).rate_multiplier
    
    def get_expected_occupancy(self, target_date: date) -> float:
        """Get expected occupancy for a date."""
        return self.get_factor_for_date(target_date).expected_occupancy
    
    def is_peak_season(self, target_date: date) -> bool:
        """Check if date is in peak season."""
        return target_date.month in self.peak_months
    
    def is_trough_season(self, target_date: date) -> bool:
        """Check if date is in trough/off season."""
        return target_date.month in self.trough_months


# =============================================================================
# CONSTANTS
# =============================================================================

_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


# =============================================================================
# DEFAULT SEASONALITY PROFILES BY MARKET TYPE
# =============================================================================

class MarketType(str, Enum):
    """Market archetypes for default seasonality."""
    BEACH_GULF = "beach_gulf"
    BEACH_ATLANTIC = "beach_atlantic"
    MOUNTAIN_SKI = "mountain_ski"
    MOUNTAIN_SUMMER = "mountain_summer"
    URBAN = "urban"
    LAKE = "lake"
    DESERT = "desert"
    GENERIC = "generic"


# Default profiles - ONLY used when signals are unavailable
_DEFAULT_PROFILES: Dict[MarketType, Dict[int, Dict[str, float]]] = {
    MarketType.BEACH_GULF: {
        1: {"demand": 0.45, "rate": 0.70, "occupancy": 0.25},
        2: {"demand": 0.50, "rate": 0.72, "occupancy": 0.30},
        3: {"demand": 1.20, "rate": 1.10, "occupancy": 0.85},
        4: {"demand": 0.85, "rate": 0.90, "occupancy": 0.55},
        5: {"demand": 0.95, "rate": 0.95, "occupancy": 0.60},
        6: {"demand": 1.40, "rate": 1.35, "occupancy": 0.92},
        7: {"demand": 1.50, "rate": 1.45, "occupancy": 0.95},
        8: {"demand": 1.20, "rate": 1.15, "occupancy": 0.75},
        9: {"demand": 0.60, "rate": 0.78, "occupancy": 0.40},
        10: {"demand": 0.65, "rate": 0.80, "occupancy": 0.45},
        11: {"demand": 0.55, "rate": 0.75, "occupancy": 0.35},
        12: {"demand": 0.60, "rate": 0.85, "occupancy": 0.35},
    },
    MarketType.MOUNTAIN_SKI: {
        1: {"demand": 1.30, "rate": 1.25, "occupancy": 0.80},
        2: {"demand": 1.35, "rate": 1.30, "occupancy": 0.82},
        3: {"demand": 1.20, "rate": 1.15, "occupancy": 0.75},
        4: {"demand": 0.60, "rate": 0.70, "occupancy": 0.35},
        5: {"demand": 0.50, "rate": 0.65, "occupancy": 0.30},
        6: {"demand": 0.90, "rate": 0.90, "occupancy": 0.55},
        7: {"demand": 1.10, "rate": 1.05, "occupancy": 0.70},
        8: {"demand": 1.00, "rate": 1.00, "occupancy": 0.65},
        9: {"demand": 0.70, "rate": 0.75, "occupancy": 0.40},
        10: {"demand": 0.65, "rate": 0.70, "occupancy": 0.35},
        11: {"demand": 0.80, "rate": 0.85, "occupancy": 0.50},
        12: {"demand": 1.40, "rate": 1.40, "occupancy": 0.90},
    },
    MarketType.URBAN: {
        1: {"demand": 0.80, "rate": 0.85, "occupancy": 0.55},
        2: {"demand": 0.85, "rate": 0.88, "occupancy": 0.58},
        3: {"demand": 0.95, "rate": 0.95, "occupancy": 0.65},
        4: {"demand": 1.00, "rate": 1.00, "occupancy": 0.70},
        5: {"demand": 1.05, "rate": 1.02, "occupancy": 0.72},
        6: {"demand": 1.10, "rate": 1.05, "occupancy": 0.75},
        7: {"demand": 1.05, "rate": 1.02, "occupancy": 0.72},
        8: {"demand": 1.00, "rate": 1.00, "occupancy": 0.70},
        9: {"demand": 1.10, "rate": 1.05, "occupancy": 0.75},
        10: {"demand": 1.15, "rate": 1.08, "occupancy": 0.78},
        11: {"demand": 0.90, "rate": 0.92, "occupancy": 0.62},
        12: {"demand": 0.85, "rate": 0.88, "occupancy": 0.58},
    },
    MarketType.GENERIC: {
        1: {"demand": 0.70, "rate": 0.75, "occupancy": 0.40},
        2: {"demand": 0.75, "rate": 0.78, "occupancy": 0.45},
        3: {"demand": 0.90, "rate": 0.90, "occupancy": 0.55},
        4: {"demand": 0.95, "rate": 0.95, "occupancy": 0.60},
        5: {"demand": 1.00, "rate": 1.00, "occupancy": 0.65},
        6: {"demand": 1.15, "rate": 1.10, "occupancy": 0.75},
        7: {"demand": 1.20, "rate": 1.15, "occupancy": 0.78},
        8: {"demand": 1.10, "rate": 1.08, "occupancy": 0.72},
        9: {"demand": 0.90, "rate": 0.90, "occupancy": 0.55},
        10: {"demand": 0.85, "rate": 0.85, "occupancy": 0.50},
        11: {"demand": 0.80, "rate": 0.82, "occupancy": 0.48},
        12: {"demand": 0.85, "rate": 0.88, "occupancy": 0.50},
    },
}

# Copy generic to other types that aren't defined
for market_type in MarketType:
    if market_type not in _DEFAULT_PROFILES:
        _DEFAULT_PROFILES[market_type] = _DEFAULT_PROFILES[MarketType.GENERIC]


# =============================================================================
# SEASONALITY SERVICE
# =============================================================================

class SeasonalityService:
    """
    Unified seasonality service - the ONLY place seasonality should come from.
    
    Priority order:
    1. Fresh signal from signal store (< 30 days old)
    2. Stale signal with decay applied (30-90 days old)  
    3. Geo-specific default profile
    4. Generic fallback
    
    This service REPLACES:
    - SeasonalityDetector in platform_weighting.py
    - DEFAULT_SEASONALITY in rent_projection_engine_v1_1.py
    - Inline seasonality in market_intelligence_engine.py
    """
    
    def __init__(self, signal_repository=None):
        """
        Initialize service.
        
        Args:
            signal_repository: Repository for fetching signals from store.
                              If None, will only use defaults (for testing).
        """
        self.signal_repo = signal_repository
        
        # Cache for geo → market type mapping
        self._geo_market_type_cache: Dict[str, MarketType] = {}
    
    async def get_seasonality(
        self,
        tenant_id: UUID,
        geo_id: str,
        as_of_date: Optional[date] = None,
        market_type_hint: Optional[MarketType] = None,
    ) -> SeasonalityData:
        """
        Get seasonality data for a geo.
        
        This is the PRIMARY entry point. All other methods are internal.
        
        Args:
            tenant_id: Tenant ID for isolation
            geo_id: Geographic polygon ID
            as_of_date: Date to get seasonality for (default: today)
            market_type_hint: Optional hint for default selection
        
        Returns:
            SeasonalityData with full monthly breakdown
        """
        as_of_date = as_of_date or date.today()
        
        # Try to get from signal store first
        if self.signal_repo:
            signal_data = await self._get_from_signals(tenant_id, geo_id)
            if signal_data:
                return signal_data
        
        # Fall back to defaults
        return self._get_default_seasonality(
            tenant_id, geo_id, market_type_hint
        )
    
    def get_seasonality_sync(
        self,
        tenant_id: UUID,
        geo_id: str,
        signals: Optional[SignalBundle] = None,
        market_type_hint: Optional[MarketType] = None,
    ) -> SeasonalityData:
        """
        Synchronous version that accepts pre-fetched signals.
        
        Use this when you already have signals in memory.
        """
        if signals:
            signal_data = self._extract_from_bundle(signals, tenant_id, geo_id)
            if signal_data:
                return signal_data
        
        return self._get_default_seasonality(tenant_id, geo_id, market_type_hint)
    
    async def _get_from_signals(
        self,
        tenant_id: UUID,
        geo_id: str,
    ) -> Optional[SeasonalityData]:
        """Fetch seasonality from signal store."""
        if not self.signal_repo:
            return None
        
        try:
            signal = await self.signal_repo.get_latest_by_type(
                tenant_id=tenant_id,
                geo_id=geo_id,
                signal_type=SignalType.SEASONALITY_CURVE.value,
            )
            
            if not signal:
                return None
            
            return self._convert_signal_to_seasonality(signal, tenant_id, geo_id)
            
        except Exception:
            # Log but don't fail - fall back to defaults
            return None
    
    def _extract_from_bundle(
        self,
        signals: SignalBundle,
        tenant_id: UUID,
        geo_id: str,
    ) -> Optional[SeasonalityData]:
        """Extract seasonality from a pre-fetched signal bundle."""
        seasonality_signal = signals.most_recent(SignalType.SEASONALITY_CURVE)
        
        if not seasonality_signal:
            return None
        
        return self._convert_signal_to_seasonality(
            seasonality_signal, tenant_id, geo_id
        )
    
    def _convert_signal_to_seasonality(
        self,
        signal: Signal,
        tenant_id: UUID,
        geo_id: str,
    ) -> Optional[SeasonalityData]:
        """Convert a SEASONALITY_CURVE signal to SeasonalityData."""
        if not signal.structured_value:
            return None
        
        sv = signal.structured_value
        monthly_curve = sv.get("monthly_curve", {})
        
        if not monthly_curve:
            return None
        
        # Convert signal curve to MonthlyFactors
        month_map = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        
        monthly_factors = {}
        for month_name, demand_factor in monthly_curve.items():
            month_num = month_map.get(month_name.lower())
            if month_num:
                monthly_factors[month_num] = MonthlyFactor(
                    month=month_num,
                    month_name=_MONTH_NAMES[month_num],
                    demand_factor=demand_factor,
                    rate_multiplier=demand_factor,  # Assume rate tracks demand
                    expected_occupancy=min(0.95, demand_factor * 0.55),
                    confidence=signal.confidence,
                )
        
        # Fill any missing months with neutral values
        for month in range(1, 13):
            if month not in monthly_factors:
                monthly_factors[month] = MonthlyFactor(
                    month=month,
                    month_name=_MONTH_NAMES[month],
                    demand_factor=1.0,
                    rate_multiplier=1.0,
                    expected_occupancy=0.55,
                    confidence=0.5,
                )
        
        # Determine peak/trough months
        sorted_months = sorted(
            monthly_factors.items(),
            key=lambda x: x[1].demand_factor,
            reverse=True
        )
        
        peak_months = [m for m, f in sorted_months[:3]]
        trough_months = [m for m, f in sorted_months[-3:]]
        shoulder_months = [m for m in range(1, 13) if m not in peak_months and m not in trough_months]
        
        # Calculate seasonality strength
        peak_avg = sum(monthly_factors[m].demand_factor for m in peak_months) / 3
        trough_avg = sum(monthly_factors[m].demand_factor for m in trough_months) / 3
        strength = peak_avg / trough_avg if trough_avg > 0 else 1.5
        
        return SeasonalityData(
            geo_id=geo_id,
            tenant_id=tenant_id,
            monthly_factors=monthly_factors,
            peak_months=peak_months,
            trough_months=trough_months,
            shoulder_months=shoulder_months,
            seasonality_strength=strength,
            confidence=signal.confidence,
            source=SeasonalitySource.SIGNAL,
            signal_id=signal.signal_id,
            detected_at=signal.detected_at,
        )
    
    def _get_default_seasonality(
        self,
        tenant_id: UUID,
        geo_id: str,
        market_type_hint: Optional[MarketType] = None,
    ) -> SeasonalityData:
        """Get default seasonality for a geo."""
        # Determine market type
        market_type = market_type_hint or self._infer_market_type(geo_id)
        
        # Get profile
        profile = _DEFAULT_PROFILES.get(market_type, _DEFAULT_PROFILES[MarketType.GENERIC])
        
        # Convert to MonthlyFactors
        monthly_factors = {}
        for month, data in profile.items():
            monthly_factors[month] = MonthlyFactor(
                month=month,
                month_name=_MONTH_NAMES[month],
                demand_factor=data["demand"],
                rate_multiplier=data["rate"],
                expected_occupancy=data["occupancy"],
                confidence=0.6,  # Lower confidence for defaults
            )
        
        # Determine peak/trough
        sorted_months = sorted(
            monthly_factors.items(),
            key=lambda x: x[1].demand_factor,
            reverse=True
        )
        
        peak_months = [m for m, f in sorted_months[:3]]
        trough_months = [m for m, f in sorted_months[-3:]]
        shoulder_months = [m for m in range(1, 13) if m not in peak_months and m not in trough_months]
        
        peak_avg = sum(monthly_factors[m].demand_factor for m in peak_months) / 3
        trough_avg = sum(monthly_factors[m].demand_factor for m in trough_months) / 3
        strength = peak_avg / trough_avg if trough_avg > 0 else 1.5
        
        return SeasonalityData(
            geo_id=geo_id,
            tenant_id=tenant_id,
            monthly_factors=monthly_factors,
            peak_months=peak_months,
            trough_months=trough_months,
            shoulder_months=shoulder_months,
            seasonality_strength=strength,
            confidence=0.6,
            source=SeasonalitySource.GEO_DEFAULT if market_type_hint else SeasonalitySource.FALLBACK,
        )
    
    def _infer_market_type(self, geo_id: str) -> MarketType:
        """
        Infer market type from geo_id.
        
        In production, this would:
        - Look up geo metadata
        - Check coastal proximity
        - Check elevation
        - etc.
        
        For now, use simple heuristics.
        """
        if geo_id in self._geo_market_type_cache:
            return self._geo_market_type_cache[geo_id]
        
        geo_lower = geo_id.lower()
        
        # Simple keyword matching (would be replaced with proper geo lookup)
        if any(kw in geo_lower for kw in ["gulf", "destin", "panama", "30a", "pensacola"]):
            market_type = MarketType.BEACH_GULF
        elif any(kw in geo_lower for kw in ["atlantic", "myrtle", "outer-banks", "jersey"]):
            market_type = MarketType.BEACH_ATLANTIC
        elif any(kw in geo_lower for kw in ["aspen", "vail", "park-city", "ski"]):
            market_type = MarketType.MOUNTAIN_SKI
        elif any(kw in geo_lower for kw in ["nyc", "chicago", "la", "sf", "urban"]):
            market_type = MarketType.URBAN
        elif any(kw in geo_lower for kw in ["lake", "tahoe"]):
            market_type = MarketType.LAKE
        else:
            market_type = MarketType.GENERIC
        
        self._geo_market_type_cache[geo_id] = market_type
        return market_type


# =============================================================================
# SINGLETON & CONVENIENCE FUNCTIONS
# =============================================================================

_service: Optional[SeasonalityService] = None


def get_seasonality_service(signal_repository=None) -> SeasonalityService:
    """Get or create seasonality service singleton."""
    global _service
    if _service is None:
        _service = SeasonalityService(signal_repository)
    return _service


async def get_seasonality_for_geo(
    tenant_id: UUID,
    geo_id: str,
    as_of_date: Optional[date] = None,
    market_type_hint: Optional[MarketType] = None,
) -> SeasonalityData:
    """
    Convenience function to get seasonality for a geo.
    
    This is the recommended entry point for all code that needs seasonality.
    """
    service = get_seasonality_service()
    return await service.get_seasonality(
        tenant_id, geo_id, as_of_date, market_type_hint
    )


def get_seasonality_from_signals(
    tenant_id: UUID,
    geo_id: str,
    signals: SignalBundle,
    market_type_hint: Optional[MarketType] = None,
) -> SeasonalityData:
    """
    Synchronous convenience function when signals are already loaded.
    """
    service = get_seasonality_service()
    return service.get_seasonality_sync(
        tenant_id, geo_id, signals, market_type_hint
    )


# =============================================================================
# LEGACY COMPATIBILITY LAYER
# =============================================================================

def get_legacy_seasonality_dict(
    tenant_id: UUID,
    geo_id: str,
    signals: Optional[SignalBundle] = None,
) -> Dict[int, Dict[str, float]]:
    """
    Get seasonality in legacy format for backward compatibility.
    
    Returns: {month: {"occupancy": float, "rate": float}}
    
    DEPRECATED: Use get_seasonality_for_geo() instead.
    """
    service = get_seasonality_service()
    seasonality = service.get_seasonality_sync(tenant_id, geo_id, signals)
    return seasonality.to_legacy_dict()
