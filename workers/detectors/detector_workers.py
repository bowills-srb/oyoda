"""
Detector Workers - Signal Producers.

Detectors are single-purpose, parallelizable, and cheap.
They analyze raw data and emit interpreted evidence (signals).

Key Properties:
1. Each detector runs in a background worker
2. Writes to signals table
3. Is idempotent
4. Can be scheduled, re-run, backfilled, upgraded independently

Detectors NEVER:
- Talk to each other
- Make decisions
- Compute final prices
- Access the analytics engine

Detectors ONLY:
- Consume raw/normalized data
- Emit signals with confidence scores
- Explain their reasoning in metadata
"""

from abc import abstractmethod
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4
import math

from pydantic import BaseModel, Field

from schemas.signals import (
    Signal,
    SignalType,
    SignalScope,
    SignalSource,
    TimeWindow,
    DecayProfile,
    GeoSensitivity,
    create_signal_metadata,
)
from workers.base import (
    BaseWorker,
    JobPayload,
    JobResult,
    WorkerCategory,
    register_worker,
)


# =============================================================================
# BASE DETECTOR
# =============================================================================

class DetectorPayload(JobPayload):
    """Base payload for all detectors."""
    geo_id: Optional[str] = None
    property_id: Optional[UUID] = None
    time_window: TimeWindow = TimeWindow.LAST_30D
    force_refresh: bool = False


class BaseDetector(BaseWorker[DetectorPayload]):
    """
    Abstract base class for all detectors.
    
    Subclasses implement:
    - detect(): The detection logic
    - signal_type: What type of signal this produces
    - detector_version: For reproducibility
    """
    
    category = WorkerCategory.ANALYTICS  # Detectors run in analytics worker pool
    
    # Override in subclasses
    signal_type: SignalType = None
    detector_version: str = "1.0.0"
    decay_profile: DecayProfile = DecayProfile.STABLE
    geo_sensitivity: GeoSensitivity = GeoSensitivity.LOCAL
    
    @abstractmethod
    async def detect(
        self, 
        payload: DetectorPayload,
        raw_data: Dict[str, Any],
    ) -> List[Signal]:
        """
        Run detection and produce signals.
        
        Returns a list of signals (may be empty if nothing detected).
        """
        pass
    
    async def process(self, payload: DetectorPayload) -> JobResult:
        """Execute the detector."""
        try:
            # Fetch raw data for this scope
            raw_data = await self._fetch_raw_data(payload)
            
            # Run detection
            signals = await self.detect(payload, raw_data)
            
            # Store signals
            stored_count = await self._store_signals(signals)
            
            return JobResult(
                success=True,
                data={
                    "signals_produced": len(signals),
                    "signals_stored": stored_count,
                    "signal_type": self.signal_type,
                    "detector": self.name,
                },
                items_processed=len(signals),
            )
            
        except Exception as e:
            self.logger.exception(f"Detector {self.name} failed: {e}")
            return JobResult(success=False, error=str(e))
    
    async def _fetch_raw_data(self, payload: DetectorPayload) -> Dict[str, Any]:
        """
        Fetch raw data needed for detection.
        
        Override in subclasses for specific data needs.
        """
        # Default: return empty dict, subclasses fetch what they need
        return {}
    
    async def _store_signals(self, signals: List[Signal]) -> int:
        """Store produced signals."""
        # In production, this writes to the signal store
        # For now, return count
        return len(signals)
    
    def create_signal(
        self,
        tenant_id: UUID,
        value: float,
        confidence: float,
        metadata: Dict[str, Any],
        geo_id: Optional[str] = None,
        property_id: Optional[UUID] = None,
        platform: Optional[str] = None,
        time_window: TimeWindow = TimeWindow.LAST_30D,
        structured_value: Optional[Dict[str, Any]] = None,
        weight_hint: float = 1.0,
        source: SignalSource = SignalSource.INTERNAL_ANALYTICS,
    ) -> Signal:
        """Helper to create a properly formatted signal."""
        return Signal(
            signal_id=uuid4(),
            tenant_id=tenant_id,
            signal_type=self.signal_type,
            scope=self._determine_scope(geo_id, property_id),
            geo_id=geo_id,
            property_id=property_id,
            platform=platform,
            value=value,
            structured_value=structured_value,
            confidence=confidence,
            weight_hint=weight_hint,
            source=source,
            detector_name=self.name,
            detector_version=self.detector_version,
            detected_at=datetime.utcnow(),
            time_window=time_window,
            decay_profile=self.decay_profile,
            geo_sensitivity=self.geo_sensitivity,
            metadata=metadata,
        )
    
    def _determine_scope(
        self, 
        geo_id: Optional[str], 
        property_id: Optional[UUID]
    ) -> SignalScope:
        """Determine signal scope from references."""
        if property_id:
            return SignalScope.PROPERTY
        if geo_id:
            return SignalScope.GEO
        return SignalScope.MARKET


# =============================================================================
# CORE DETECTORS
# =============================================================================

class PlatformDominancePayload(DetectorPayload):
    """Payload for platform dominance detection."""
    platforms: List[str] = Field(default=["airbnb", "vrbo", "booking"])


@register_worker
class PlatformDominanceDetector(BaseDetector):
    """
    Detect which platform dominates bookings in a geo.
    
    Input:
    - Scraped listings
    - Booking proxies
    - Availability deltas
    
    Output Signal:
    - value: Dominance score of top platform (0-1)
    - structured_value: Full distribution
    """
    
    name = "platform_dominance_detector"
    signal_type = SignalType.PLATFORM_DOMINANCE
    detector_version = "1.0.0"
    decay_profile = DecayProfile.PERSISTENT  # Platform dominance is stable
    geo_sensitivity = GeoSensitivity.LOCAL
    
    async def detect(
        self, 
        payload: PlatformDominancePayload,
        raw_data: Dict[str, Any],
    ) -> List[Signal]:
        """Detect platform dominance."""
        
        # In production, this analyzes:
        # - Listing counts by platform
        # - Booking velocity by platform
        # - Review frequency by platform
        # - Availability patterns
        
        # Simulated analysis
        platform_shares = raw_data.get("platform_shares", {
            "airbnb": 0.65,
            "vrbo": 0.28,
            "booking": 0.07,
        })
        
        # Find dominant platform
        dominant = max(platform_shares, key=platform_shares.get)
        dominance_score = platform_shares[dominant]
        
        # Calculate confidence based on sample size
        sample_size = raw_data.get("sample_size", 100)
        confidence = min(0.95, 0.5 + (sample_size / 500))
        
        # Determine weight hint based on data quality
        weight_hint = 1.0
        if sample_size < 50:
            weight_hint = 0.7
        elif sample_size > 200:
            weight_hint = 1.2
        
        signal = self.create_signal(
            tenant_id=payload.tenant_id,
            geo_id=payload.geo_id,
            value=dominance_score,
            confidence=confidence,
            weight_hint=weight_hint,
            structured_value={
                "dominant_platform": dominant,
                "distribution": platform_shares,
            },
            metadata=create_signal_metadata(
                explanation=f"{dominant.title()} dominates with {dominance_score:.0%} market share",
                sample_size=sample_size,
                methodology="Weighted analysis of listings, bookings, and availability",
                comparisons={
                    "vs_market_avg": platform_shares[dominant] - 0.5,
                },
            ),
            time_window=payload.time_window,
        )
        
        return [signal]


class AmenityLiftPayload(DetectorPayload):
    """Payload for amenity lift detection."""
    amenities: List[str] = Field(default=[
        "pool", "pool_heated", "hot_tub", "waterfront", 
        "pet_friendly", "ev_charger", "game_room"
    ])


@register_worker
class AmenityLiftDetector(BaseDetector):
    """
    Detect ADR lift per amenity in a geo.
    
    Compares properties with/without each amenity to determine
    the revenue premium.
    """
    
    name = "amenity_lift_detector"
    signal_type = SignalType.AMENITY_LIFT
    detector_version = "1.0.0"
    decay_profile = DecayProfile.STABLE  # Amenity values are fairly stable
    geo_sensitivity = GeoSensitivity.LOCAL
    
    async def detect(
        self, 
        payload: AmenityLiftPayload,
        raw_data: Dict[str, Any],
    ) -> List[Signal]:
        """Detect amenity lift for each amenity."""
        
        signals = []
        
        # In production, this compares ADR of properties with/without amenity
        # controlling for other factors (bedrooms, location, etc.)
        
        amenity_lifts = raw_data.get("amenity_lifts", {
            "pool": 0.15,           # +15% ADR
            "pool_heated": 0.08,    # Additional +8%
            "hot_tub": 0.10,        # +10%
            "waterfront": 0.25,     # +25%
            "pet_friendly": 0.05,   # +5%
            "ev_charger": 0.08,     # +8%
            "game_room": 0.06,      # +6%
        })
        
        amenity_samples = raw_data.get("amenity_samples", {})
        
        for amenity in payload.amenities:
            if amenity not in amenity_lifts:
                continue
            
            lift = amenity_lifts[amenity]
            sample_size = amenity_samples.get(amenity, 50)
            
            # Confidence based on sample size and lift magnitude
            confidence = min(0.90, 0.4 + (sample_size / 200) + abs(lift) * 0.5)
            
            signal = self.create_signal(
                tenant_id=payload.tenant_id,
                geo_id=payload.geo_id,
                value=lift,  # Normalized lift value
                confidence=confidence,
                structured_value={
                    "amenity": amenity,
                    "lift_percent": lift * 100,
                    "sample_with": sample_size,
                    "sample_without": raw_data.get("total_properties", 200) - sample_size,
                },
                metadata=create_signal_metadata(
                    explanation=f"{amenity.replace('_', ' ').title()} provides {lift:.0%} ADR premium",
                    sample_size=sample_size,
                    methodology="Controlled comparison of properties with/without amenity",
                ),
                time_window=payload.time_window,
            )
            signals.append(signal)
        
        return signals


class SeasonalityCurvePayload(DetectorPayload):
    """Payload for seasonality curve detection."""
    pass


@register_worker
class SeasonalityCurveDetector(BaseDetector):
    """
    Detect monthly demand shape for a geo.
    
    Produces a 12-month curve of relative demand.
    """
    
    name = "seasonality_curve_detector"
    signal_type = SignalType.SEASONALITY_CURVE
    detector_version = "1.0.0"
    decay_profile = DecayProfile.SEASONAL
    geo_sensitivity = GeoSensitivity.LOCAL  # Seasonality is very geo-specific
    
    async def detect(
        self, 
        payload: SeasonalityCurvePayload,
        raw_data: Dict[str, Any],
    ) -> List[Signal]:
        """Detect seasonality curve."""
        
        # In production, analyzes:
        # - Historical booking patterns
        # - ADR by month
        # - Occupancy by month
        # - Forward booking pace
        
        # Simulated curve (normalized to average = 1.0)
        monthly_curve = raw_data.get("monthly_curve", {
            "jan": 0.70, "feb": 0.75, "mar": 1.10, "apr": 0.95,
            "may": 1.05, "jun": 1.35, "jul": 1.40, "aug": 1.30,
            "sep": 0.85, "oct": 0.80, "nov": 0.85, "dec": 0.90,
        })
        
        # Identify peak and trough
        peak_month = max(monthly_curve, key=monthly_curve.get)
        trough_month = min(monthly_curve, key=monthly_curve.get)
        
        # Seasonality strength (peak/trough ratio)
        seasonality_strength = monthly_curve[peak_month] / monthly_curve[trough_month]
        
        # Normalize to -1 to +1 scale (1.0 average = 0, higher = positive)
        normalized_value = (seasonality_strength - 1.5) / 1.5  # Assuming 1.5 is "normal" seasonality
        
        sample_size = raw_data.get("sample_months", 24)
        confidence = min(0.92, 0.5 + (sample_size / 48))
        
        signal = self.create_signal(
            tenant_id=payload.tenant_id,
            geo_id=payload.geo_id,
            value=normalized_value,
            confidence=confidence,
            structured_value={
                "monthly_curve": monthly_curve,
                "peak_month": peak_month,
                "trough_month": trough_month,
                "seasonality_strength": seasonality_strength,
            },
            metadata=create_signal_metadata(
                explanation=f"Peak in {peak_month.title()}, trough in {trough_month.title()}. "
                           f"Seasonality strength: {seasonality_strength:.1f}x",
                sample_size=sample_size,
                methodology="Analysis of 24-month booking and ADR patterns",
            ),
            time_window=TimeWindow.TRAILING_12M,
        )
        
        return [signal]


class OccupancyMomentumPayload(DetectorPayload):
    """Payload for occupancy momentum detection."""
    forward_days: int = 90
    trailing_days: int = 90


@register_worker
class OccupancyMomentumDetector(BaseDetector):
    """
    Detect occupancy momentum (forward vs trailing pace).
    
    Compares current booking pace to historical pace
    for the same forward period.
    """
    
    name = "occupancy_momentum_detector"
    signal_type = SignalType.OCCUPANCY_MOMENTUM
    detector_version = "1.0.0"
    decay_profile = DecayProfile.VOLATILE  # Momentum changes quickly
    geo_sensitivity = GeoSensitivity.LOCAL
    
    async def detect(
        self, 
        payload: OccupancyMomentumPayload,
        raw_data: Dict[str, Any],
    ) -> List[Signal]:
        """Detect occupancy momentum."""
        
        # In production, compares:
        # - Current forward bookings for next N days
        # - Same period last year's forward bookings at this point
        # - Trailing actuals
        
        forward_pace = raw_data.get("forward_occupancy", 0.55)  # 55% booked for next 90 days
        same_time_last_year = raw_data.get("forward_occupancy_ly", 0.50)
        trailing_actual = raw_data.get("trailing_occupancy", 0.68)
        
        # Calculate momentum (positive = ahead of pace)
        yoy_delta = forward_pace - same_time_last_year
        
        # Normalize to -1 to +1 (±20% would be extreme)
        normalized_momentum = max(-1.0, min(1.0, yoy_delta / 0.20))
        
        # Confidence based on data completeness
        confidence = raw_data.get("data_completeness", 0.85)
        
        signal = self.create_signal(
            tenant_id=payload.tenant_id,
            geo_id=payload.geo_id,
            value=normalized_momentum,
            confidence=confidence,
            structured_value={
                "forward_pace": forward_pace,
                "same_time_last_year": same_time_last_year,
                "trailing_actual": trailing_actual,
                "yoy_delta": yoy_delta,
                "forward_days": payload.forward_days,
            },
            metadata=create_signal_metadata(
                explanation=f"Forward bookings are {'+' if yoy_delta > 0 else ''}{yoy_delta:.1%} vs last year",
                sample_size=raw_data.get("property_count", 100),
                methodology="Comparison of forward booking pace vs same period last year",
                warnings=["Early season data may be less reliable"] if forward_pace < 0.30 else [],
            ),
            time_window=TimeWindow.FORWARD_90D,
        )
        
        return [signal]


class PriceElasticityPayload(DetectorPayload):
    """Payload for price elasticity detection."""
    pass


@register_worker
class PriceElasticityDetector(BaseDetector):
    """
    Detect price elasticity in a geo.
    
    Measures how sensitive demand is to price changes.
    """
    
    name = "price_elasticity_detector"
    signal_type = SignalType.PRICE_ELASTICITY
    detector_version = "1.0.0"
    decay_profile = DecayProfile.STABLE
    geo_sensitivity = GeoSensitivity.LOCAL
    
    async def detect(
        self, 
        payload: PriceElasticityPayload,
        raw_data: Dict[str, Any],
    ) -> List[Signal]:
        """Detect price elasticity."""
        
        # In production, analyzes:
        # - Discount experiments
        # - Price change vs booking response
        # - Competitor price movements
        
        # Elasticity: % change in demand / % change in price
        # -1.5 means 10% price drop = 15% demand increase
        elasticity = raw_data.get("elasticity", -1.2)
        
        # Normalize: -2 to 0 maps to -1 to +1 (more negative = more elastic)
        normalized = (elasticity + 1.0) / 1.0  # -2 -> -1, -1 -> 0, 0 -> 1
        normalized = max(-1.0, min(1.0, normalized))
        
        confidence = raw_data.get("confidence", 0.75)
        
        signal = self.create_signal(
            tenant_id=payload.tenant_id,
            geo_id=payload.geo_id,
            value=normalized,
            confidence=confidence,
            structured_value={
                "elasticity": elasticity,
                "interpretation": "elastic" if elasticity < -1 else "inelastic",
            },
            metadata=create_signal_metadata(
                explanation=f"Market is {'elastic' if elasticity < -1 else 'inelastic'} "
                           f"(elasticity: {elasticity:.2f})",
                sample_size=raw_data.get("sample_size", 50),
                methodology="Regression analysis of price changes vs booking response",
            ),
            time_window=payload.time_window,
        )
        
        return [signal]


class OperatorDeltaPayload(DetectorPayload):
    """Payload for operator performance delta detection."""
    operator_id: UUID


@register_worker
class OperatorDeltaDetector(BaseDetector):
    """
    Detect operator performance vs market baseline.
    
    This is the key signal for operator-specific projections.
    """
    
    name = "operator_delta_detector"
    signal_type = SignalType.OPERATOR_DELTA
    detector_version = "1.0.0"
    decay_profile = DecayProfile.STABLE
    geo_sensitivity = GeoSensitivity.LOCAL
    
    async def detect(
        self, 
        payload: OperatorDeltaPayload,
        raw_data: Dict[str, Any],
    ) -> List[Signal]:
        """Detect operator performance delta."""
        
        # In production, compares:
        # - Operator's properties' performance
        # - Market average for similar properties
        # - Controlled for bedrooms, amenities, location
        
        operator_adr = raw_data.get("operator_adr", 285)
        market_adr = raw_data.get("market_adr", 250)
        
        operator_occupancy = raw_data.get("operator_occupancy", 0.72)
        market_occupancy = raw_data.get("market_occupancy", 0.65)
        
        adr_delta = (operator_adr - market_adr) / market_adr
        occupancy_delta = (operator_occupancy - market_occupancy) / market_occupancy
        
        # Combined delta (weighted)
        combined_delta = (adr_delta * 0.6) + (occupancy_delta * 0.4)
        
        # Normalize to -1 to +1 (±30% would be extreme)
        normalized = max(-1.0, min(1.0, combined_delta / 0.30))
        
        # Confidence based on data depth
        months_of_data = raw_data.get("months_of_data", 12)
        property_count = raw_data.get("property_count", 20)
        confidence = min(0.90, 0.4 + (months_of_data / 24) + (property_count / 100))
        
        signal = self.create_signal(
            tenant_id=payload.tenant_id,
            geo_id=payload.geo_id,
            value=normalized,
            confidence=confidence,
            structured_value={
                "adr_delta_pct": adr_delta,
                "occupancy_delta_pct": occupancy_delta,
                "combined_delta": combined_delta,
                "operator_adr": operator_adr,
                "market_adr": market_adr,
                "operator_occupancy": operator_occupancy,
                "market_occupancy": market_occupancy,
            },
            metadata=create_signal_metadata(
                explanation=f"Operator outperforms market by {combined_delta:.1%} overall "
                           f"(ADR: {'+' if adr_delta > 0 else ''}{adr_delta:.1%}, "
                           f"Occupancy: {'+' if occupancy_delta > 0 else ''}{occupancy_delta:.1%})",
                sample_size=property_count,
                methodology="Controlled comparison vs market basket of similar properties",
                comparisons={
                    "adr_delta": adr_delta,
                    "occupancy_delta": occupancy_delta,
                },
            ),
            time_window=payload.time_window,
        )
        
        return [signal]


class GuestIntentPayload(DetectorPayload):
    """Payload for guest intent frequency detection."""
    pass


@register_worker
class GuestIntentFrequencyDetector(BaseDetector):
    """
    Detect what guests ask most from message analysis.
    
    This bridges concierge intelligence to BD insights.
    """
    
    name = "guest_intent_frequency_detector"
    signal_type = SignalType.GUEST_INTENT_FREQUENCY
    detector_version = "1.0.0"
    decay_profile = DecayProfile.VOLATILE
    geo_sensitivity = GeoSensitivity.PROPERTY_ONLY
    
    async def detect(
        self, 
        payload: GuestIntentPayload,
        raw_data: Dict[str, Any],
    ) -> List[Signal]:
        """Detect guest intent frequency."""
        
        # In production, analyzes message threads to extract:
        # - Most common questions
        # - Emerging needs
        # - Unmet demands
        
        intent_counts = raw_data.get("intent_counts", {
            "check_in_question": 45,
            "wifi_question": 38,
            "parking_question": 32,
            "pool_question": 28,
            "local_recommendation": 25,
        })
        
        total_intents = sum(intent_counts.values())
        
        # Find dominant intent
        dominant_intent = max(intent_counts, key=intent_counts.get)
        dominant_pct = intent_counts[dominant_intent] / total_intents
        
        # Normalize (0.5 = even distribution, higher = more concentrated)
        normalized = (dominant_pct - 0.2) / 0.3  # 20% baseline, 50% = 1.0
        normalized = max(-1.0, min(1.0, normalized))
        
        confidence = min(0.85, 0.4 + (total_intents / 200))
        
        signal = self.create_signal(
            tenant_id=payload.tenant_id,
            property_id=payload.property_id,
            value=normalized,
            confidence=confidence,
            structured_value={
                "intent_distribution": {
                    k: v / total_intents for k, v in intent_counts.items()
                },
                "dominant_intent": dominant_intent,
                "total_intents": total_intents,
            },
            metadata=create_signal_metadata(
                explanation=f"Top guest question: {dominant_intent.replace('_', ' ')} "
                           f"({intent_counts[dominant_intent]} occurrences, {dominant_pct:.0%} of total)",
                sample_size=total_intents,
                methodology="NLP extraction from guest message threads",
            ),
            time_window=payload.time_window,
            source=SignalSource.GUEST_MESSAGES,
        )
        
        return [signal]


# =============================================================================
# DETECTOR REGISTRY
# =============================================================================

DETECTOR_REGISTRY = {
    "platform_dominance": PlatformDominanceDetector,
    "amenity_lift": AmenityLiftDetector,
    "seasonality_curve": SeasonalityCurveDetector,
    "occupancy_momentum": OccupancyMomentumDetector,
    "price_elasticity": PriceElasticityDetector,
    "operator_delta": OperatorDeltaDetector,
    "guest_intent_frequency": GuestIntentFrequencyDetector,
}


def get_detector(name: str) -> Optional[type]:
    """Get detector class by name."""
    return DETECTOR_REGISTRY.get(name)


def list_detectors() -> List[str]:
    """List all available detectors."""
    return list(DETECTOR_REGISTRY.keys())
