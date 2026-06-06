"""
Market Intelligence Engine - Proprietary External Signals.

This replaces AirDNA dependency with owned, defensible market intelligence.

THREE CORE COMPONENTS:
1. Crawling Schema - What we collect and how often
2. Market Health Index (MHI) - External bounding signal (0-100)
3. Signal Confidence Decay - Prevents stale data from poisoning projections

CRITICAL PRINCIPLES:
- We crawl for STRUCTURE, not revenue
- Scraped data is AGGREGATED first, never flows directly to projections
- We model WHY revenue happens, not what happened
- External signals BOUND projections, they don't drive them
"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# CRAWL CONFIGURATION & SCHEMA
# =============================================================================

class CrawlFrequency(str, Enum):
    """How often to crawl each signal type."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class SignalType(str, Enum):
    """Types of signals we crawl."""
    LISTING_CENSUS = "listing_census"  # Weekly - total active listings
    AMENITY_SATURATION = "amenity_saturation"  # Weekly - feature prevalence
    AVAILABILITY_PRESSURE = "availability_pressure"  # Daily - booking velocity
    PRICE_POSTURE = "price_posture"  # Weekly - rate movements
    EVENT_CALENDAR = "event_calendar"  # Monthly - upcoming events
    SEARCH_TRENDS = "search_trends"  # Weekly - Google Trends data


@dataclass
class CrawlConfig:
    """
    Crawl cadence configuration.
    
    These frequencies are tuned to avoid:
    - Noise from over-sampling
    - Throttling from platforms
    - Stale data from under-sampling
    """
    SIGNAL_CADENCE: Dict[SignalType, CrawlFrequency] = field(default_factory=lambda: {
        SignalType.LISTING_CENSUS: CrawlFrequency.WEEKLY,
        SignalType.AMENITY_SATURATION: CrawlFrequency.WEEKLY,
        SignalType.AVAILABILITY_PRESSURE: CrawlFrequency.DAILY,
        SignalType.PRICE_POSTURE: CrawlFrequency.WEEKLY,
        SignalType.EVENT_CALENDAR: CrawlFrequency.MONTHLY,
        SignalType.SEARCH_TRENDS: CrawlFrequency.WEEKLY,
    })
    
    # Decay half-lives in days
    SIGNAL_HALF_LIFE: Dict[SignalType, int] = field(default_factory=lambda: {
        SignalType.LISTING_CENSUS: 30,  # Slow decay
        SignalType.AMENITY_SATURATION: 45,  # Very slow
        SignalType.AVAILABILITY_PRESSURE: 3,  # Fast decay
        SignalType.PRICE_POSTURE: 14,  # Medium
        SignalType.EVENT_CALENDAR: 7,  # Fast as events pass
        SignalType.SEARCH_TRENDS: 14,  # Medium
    })


# =============================================================================
# CANONICAL CRAWL SCHEMAS (Versioned)
# =============================================================================

class ListingAmenities(BaseModel):
    """Amenities extracted from listing."""
    pool: bool = False
    pool_heated: bool = False
    hot_tub: bool = False
    waterfront: bool = False
    pet_friendly: bool = False
    parking: bool = False
    garage: bool = False
    ev_charger: bool = False
    view_type: Optional[str] = None  # gulf, ocean, mountain, lake
    beach_access: Optional[str] = None  # private, public
    dock: bool = False
    elevator: bool = False
    game_room: bool = False
    home_theater: bool = False


class ListingPriceSnapshot(BaseModel):
    """Price information from listing."""
    nightly_displayed: Optional[float] = None
    min_stay: int = 1
    cleaning_fee: Optional[float] = None
    has_dynamic_pricing: bool = False


class ListingAvailabilitySnapshot(BaseModel):
    """Availability metrics (booking pressure indicators)."""
    unavailable_next_7: int = 0
    unavailable_next_14: int = 0
    unavailable_next_30: int = 0
    unavailable_next_60: int = 0
    unavailable_next_90: int = 0


class CrawledListing(BaseModel):
    """
    Canonical schema for a crawled listing.
    
    Version: 1.0.0
    
    IMPORTANT: This data is for AGGREGATION only.
    It never flows directly into projections.
    """
    schema_version: str = "1.0.0"
    
    # Identification
    crawl_id: UUID = Field(default_factory=uuid4)
    source: str  # "airbnb", "vrbo", "booking", "mls"
    source_listing_id: str
    
    # Location
    market_id: str
    geo_hash: str  # For sub-market grouping
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    
    # Timing
    snapshot_date: date
    crawled_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Property attributes
    bedrooms: int
    bathrooms: float
    max_guests: Optional[int] = None
    property_type: str = "unknown"  # house, condo, apartment
    sqft: Optional[int] = None
    
    # Structured data
    amenities: ListingAmenities = Field(default_factory=ListingAmenities)
    price: ListingPriceSnapshot = Field(default_factory=ListingPriceSnapshot)
    availability: ListingAvailabilitySnapshot = Field(default_factory=ListingAvailabilitySnapshot)


class MarketCensusSnapshot(BaseModel):
    """
    Aggregated market census from crawled listings.
    
    This is what we USE, not raw listings.
    """
    schema_version: str = "1.0.0"
    
    market_id: str
    snapshot_date: date
    
    # Listing counts
    total_listings: int
    listings_by_bedroom: Dict[int, int] = Field(default_factory=dict)
    listings_by_source: Dict[str, int] = Field(default_factory=dict)
    
    # Growth
    listings_added_30d: int = 0
    listings_removed_30d: int = 0
    net_growth_30d: int = 0
    growth_rate_30d: float = 0.0
    
    # Amenity saturation (% of listings with each)
    amenity_saturation: Dict[str, float] = Field(default_factory=dict)
    
    # Availability pressure (avg % unavailable)
    avg_unavailable_next_30: float = 0.0
    avg_unavailable_next_14: float = 0.0
    
    # Price posture
    median_displayed_rate: float = 0.0
    median_rate_by_bedroom: Dict[int, float] = Field(default_factory=dict)
    rate_change_30d_pct: float = 0.0


# =============================================================================
# SIGNAL CONFIDENCE DECAY
# =============================================================================

class SignalDecay:
    """
    Implements confidence decay for all signals.
    
    Every signal decays over time:
    confidence = base_confidence * e^(-days_since / half_life)
    
    This prevents stale data from poisoning projections
    and allows honest "confidence is lower" statements.
    """
    
    @staticmethod
    def calculate_decay(
        base_confidence: float,
        days_since_observation: int,
        half_life_days: int,
    ) -> float:
        """
        Calculate decayed confidence.
        
        Args:
            base_confidence: Original confidence (0-1)
            days_since_observation: Days since data was collected
            half_life_days: Days for confidence to halve
            
        Returns:
            Decayed confidence (0-1)
        """
        if days_since_observation <= 0:
            return base_confidence
        
        decay_factor = math.exp(-days_since_observation / half_life_days * math.log(2))
        return base_confidence * decay_factor
    
    @staticmethod
    def calculate_signal_confidence(
        signal_type: SignalType,
        observation_date: date,
        base_confidence: float = 1.0,
        config: CrawlConfig = None,
    ) -> Tuple[float, str]:
        """
        Calculate current confidence for a signal.
        
        Returns:
            (confidence, explanation)
        """
        config = config or CrawlConfig()
        half_life = config.SIGNAL_HALF_LIFE.get(signal_type, 14)
        days_since = (date.today() - observation_date).days
        
        confidence = SignalDecay.calculate_decay(base_confidence, days_since, half_life)
        
        if confidence >= 0.9:
            explanation = "Fresh data"
        elif confidence >= 0.7:
            explanation = "Recent data"
        elif confidence >= 0.5:
            explanation = "Aging data"
        elif confidence >= 0.3:
            explanation = "Stale data - use with caution"
        else:
            explanation = "Data too old - refresh required"
        
        return round(confidence, 3), explanation
    
    @staticmethod
    def is_data_usable(
        signal_type: SignalType,
        observation_date: date,
        min_confidence: float = 0.3,
    ) -> bool:
        """Check if data is fresh enough to use."""
        confidence, _ = SignalDecay.calculate_signal_confidence(signal_type, observation_date)
        return confidence >= min_confidence


# =============================================================================
# MARKET HEALTH INDEX (MHI)
# =============================================================================

class MarketTrend(str, Enum):
    """Market trend direction."""
    STRENGTHENING = "strengthening"
    STABLE = "stable"
    WEAKENING = "weakening"
    VOLATILE = "volatile"


@dataclass
class MHIComponent:
    """A component of the Market Health Index."""
    name: str
    weight: float
    raw_score: float  # 0-100
    confidence: float  # 0-1
    explanation: str


@dataclass
class MarketHealthIndex:
    """
    Market Health Index (MHI) - Your AirDNA replacement.
    
    Score range: 0-100
    
    This is a DIRECTIONAL signal, not a performance claim.
    It bounds projections and informs strategy.
    
    Components:
    - Demand Proxies (30%): Search trends, events, travel volume
    - Supply Growth (20%): Listing count changes
    - Availability Pressure (20%): % of inventory unavailable
    - Price Posture (15%): Rate movement direction
    - Amenity Scarcity (15%): Feature rarity premiums
    """
    market_id: str
    calculated_at: datetime = field(default_factory=datetime.utcnow)
    
    # Overall score
    health_score: float = 50.0  # 0-100
    trend: MarketTrend = MarketTrend.STABLE
    confidence: float = 0.5
    
    # Components (for transparency)
    components: List[MHIComponent] = field(default_factory=list)
    
    # Interpretation
    interpretation: str = ""
    
    # Data freshness
    oldest_data_date: Optional[date] = None
    data_staleness_warning: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "health_score": round(self.health_score, 1),
            "trend": self.trend.value,
            "confidence": round(self.confidence, 2),
            "interpretation": self.interpretation,
            "components": [
                {
                    "name": c.name,
                    "weight": f"{c.weight*100:.0f}%",
                    "score": round(c.raw_score, 1),
                    "confidence": round(c.confidence, 2),
                    "explanation": c.explanation,
                }
                for c in self.components
            ],
            "data_staleness_warning": self.data_staleness_warning,
        }


class MarketHealthCalculator:
    """
    Calculates Market Health Index from aggregated signals.
    
    Component weights:
    - Demand Proxies: 30%
    - Supply Growth: 20%
    - Availability Pressure: 20%
    - Price Posture: 15%
    - Amenity Scarcity: 15%
    """
    
    COMPONENT_WEIGHTS = {
        "demand_proxies": 0.30,
        "supply_growth": 0.20,
        "availability_pressure": 0.20,
        "price_posture": 0.15,
        "amenity_scarcity": 0.15,
    }
    
    def calculate(
        self,
        market_id: str,
        census: MarketCensusSnapshot,
        demand_signals: Optional[Dict[str, Any]] = None,
        event_calendar: Optional[List[Dict]] = None,
    ) -> MarketHealthIndex:
        """
        Calculate Market Health Index from inputs.
        
        Args:
            market_id: Market identifier
            census: Aggregated market census
            demand_signals: Search trends, flight data, etc.
            event_calendar: Upcoming events
            
        Returns:
            MarketHealthIndex with all components
        """
        components = []
        
        # 1. Demand Proxies (30%)
        demand_score, demand_conf, demand_exp = self._score_demand(demand_signals, event_calendar)
        components.append(MHIComponent(
            name="Demand Proxies",
            weight=0.30,
            raw_score=demand_score,
            confidence=demand_conf,
            explanation=demand_exp,
        ))
        
        # 2. Supply Growth (20%)
        supply_score, supply_conf, supply_exp = self._score_supply_growth(census)
        components.append(MHIComponent(
            name="Supply Growth",
            weight=0.20,
            raw_score=supply_score,
            confidence=supply_conf,
            explanation=supply_exp,
        ))
        
        # 3. Availability Pressure (20%)
        avail_score, avail_conf, avail_exp = self._score_availability_pressure(census)
        components.append(MHIComponent(
            name="Availability Pressure",
            weight=0.20,
            raw_score=avail_score,
            confidence=avail_conf,
            explanation=avail_exp,
        ))
        
        # 4. Price Posture (15%)
        price_score, price_conf, price_exp = self._score_price_posture(census)
        components.append(MHIComponent(
            name="Price Posture",
            weight=0.15,
            raw_score=price_score,
            confidence=price_conf,
            explanation=price_exp,
        ))
        
        # 5. Amenity Scarcity (15%)
        amenity_score, amenity_conf, amenity_exp = self._score_amenity_scarcity(census)
        components.append(MHIComponent(
            name="Amenity Scarcity",
            weight=0.15,
            raw_score=amenity_score,
            confidence=amenity_conf,
            explanation=amenity_exp,
        ))
        
        # Calculate weighted score
        total_score = sum(c.raw_score * c.weight for c in components)
        
        # Calculate weighted confidence
        total_confidence = sum(c.confidence * c.weight for c in components)
        
        # Check data freshness
        days_since = (date.today() - census.snapshot_date).days
        staleness_warning = days_since > 14
        
        # Determine trend
        trend = self._determine_trend(census, demand_signals)
        
        # Generate interpretation
        interpretation = self._generate_interpretation(total_score, trend, components)
        
        return MarketHealthIndex(
            market_id=market_id,
            health_score=total_score,
            trend=trend,
            confidence=total_confidence,
            components=components,
            interpretation=interpretation,
            oldest_data_date=census.snapshot_date,
            data_staleness_warning=staleness_warning,
        )
    
    def _score_demand(
        self,
        demand_signals: Optional[Dict],
        events: Optional[List[Dict]],
    ) -> Tuple[float, float, str]:
        """Score demand proxies (0-100)."""
        if not demand_signals:
            return 50.0, 0.5, "Limited demand data available"
        
        # Search trend index (0-100 from Google Trends)
        search_index = demand_signals.get("search_index", 50)
        
        # Event boost
        event_boost = 0
        if events:
            upcoming_major = sum(1 for e in events if e.get("magnitude", "") == "major" 
                                and e.get("days_until", 999) <= 60)
            event_boost = min(upcoming_major * 5, 15)
        
        # Flight/travel data if available
        travel_index = demand_signals.get("travel_index", 50)
        
        score = (search_index * 0.5 + travel_index * 0.3 + event_boost + 10)
        score = min(max(score, 0), 100)
        
        confidence = 0.8 if demand_signals else 0.5
        
        if score >= 70:
            explanation = "Strong demand signals detected"
        elif score >= 50:
            explanation = "Moderate demand indicators"
        else:
            explanation = "Softer demand signals"
        
        return score, confidence, explanation
    
    def _score_supply_growth(self, census: MarketCensusSnapshot) -> Tuple[float, float, str]:
        """
        Score supply growth (0-100).
        
        Lower growth = higher score (less competition).
        """
        growth_rate = census.growth_rate_30d
        
        # Invert: high growth = more competition = lower score
        if growth_rate <= -0.05:
            score = 85  # Supply shrinking
            explanation = "Supply contracting - favorable conditions"
        elif growth_rate <= 0:
            score = 70
            explanation = "Supply stable to declining"
        elif growth_rate <= 0.02:
            score = 60
            explanation = "Modest supply growth"
        elif growth_rate <= 0.05:
            score = 45
            explanation = "Moderate supply growth"
        else:
            score = 30
            explanation = "Rapid supply growth - increased competition"
        
        confidence = 0.85 if census.total_listings > 100 else 0.6
        
        return score, confidence, explanation
    
    def _score_availability_pressure(self, census: MarketCensusSnapshot) -> Tuple[float, float, str]:
        """
        Score availability pressure (0-100).
        
        Higher unavailability = higher demand = higher score.
        """
        unavail_pct = census.avg_unavailable_next_30
        
        if unavail_pct >= 0.80:
            score = 95
            explanation = "Very high booking pressure"
        elif unavail_pct >= 0.65:
            score = 80
            explanation = "Strong booking velocity"
        elif unavail_pct >= 0.50:
            score = 65
            explanation = "Healthy booking activity"
        elif unavail_pct >= 0.35:
            score = 50
            explanation = "Moderate availability"
        else:
            score = 35
            explanation = "High availability - softer demand"
        
        confidence = 0.9  # Direct measurement
        
        return score, confidence, explanation
    
    def _score_price_posture(self, census: MarketCensusSnapshot) -> Tuple[float, float, str]:
        """
        Score price posture (0-100).
        
        Rising rates = higher score.
        """
        rate_change = census.rate_change_30d_pct
        
        if rate_change >= 0.10:
            score = 90
            explanation = "Rates rising significantly"
        elif rate_change >= 0.05:
            score = 75
            explanation = "Rates trending up"
        elif rate_change >= -0.02:
            score = 55
            explanation = "Rates stable"
        elif rate_change >= -0.10:
            score = 40
            explanation = "Rates softening"
        else:
            score = 25
            explanation = "Rates declining significantly"
        
        confidence = 0.75
        
        return score, confidence, explanation
    
    def _score_amenity_scarcity(self, census: MarketCensusSnapshot) -> Tuple[float, float, str]:
        """
        Score amenity scarcity opportunity (0-100).
        
        More scarcity = more premium opportunity.
        """
        saturation = census.amenity_saturation
        
        # Look for scarce high-value amenities
        scarce_count = 0
        for amenity in ["pool", "waterfront", "hot_tub", "pet_friendly"]:
            if saturation.get(amenity, 1.0) < 0.40:
                scarce_count += 1
        
        if scarce_count >= 3:
            score = 85
            explanation = "Multiple premium amenities are scarce"
        elif scarce_count >= 2:
            score = 70
            explanation = "Some amenity premium opportunities"
        elif scarce_count >= 1:
            score = 55
            explanation = "Limited amenity differentiation"
        else:
            score = 40
            explanation = "Amenities are commoditized"
        
        confidence = 0.8
        
        return score, confidence, explanation
    
    def _determine_trend(
        self,
        census: MarketCensusSnapshot,
        demand_signals: Optional[Dict],
    ) -> MarketTrend:
        """Determine market trend direction."""
        signals = []
        
        # Supply signal
        if census.growth_rate_30d < -0.02:
            signals.append(1)  # Strengthening
        elif census.growth_rate_30d > 0.05:
            signals.append(-1)  # Weakening
        else:
            signals.append(0)
        
        # Price signal
        if census.rate_change_30d_pct > 0.03:
            signals.append(1)
        elif census.rate_change_30d_pct < -0.03:
            signals.append(-1)
        else:
            signals.append(0)
        
        # Availability signal
        if census.avg_unavailable_next_30 > 0.60:
            signals.append(1)
        elif census.avg_unavailable_next_30 < 0.40:
            signals.append(-1)
        else:
            signals.append(0)
        
        avg_signal = sum(signals) / len(signals)
        
        if avg_signal >= 0.5:
            return MarketTrend.STRENGTHENING
        elif avg_signal <= -0.5:
            return MarketTrend.WEAKENING
        elif max(signals) - min(signals) >= 2:
            return MarketTrend.VOLATILE
        else:
            return MarketTrend.STABLE
    
    def _generate_interpretation(
        self,
        score: float,
        trend: MarketTrend,
        components: List[MHIComponent],
    ) -> str:
        """Generate human-readable interpretation."""
        if score >= 75:
            health = "strong"
        elif score >= 55:
            health = "healthy"
        elif score >= 40:
            health = "moderate"
        else:
            health = "challenging"
        
        trend_desc = {
            MarketTrend.STRENGTHENING: "improving",
            MarketTrend.STABLE: "stable",
            MarketTrend.WEAKENING: "softening",
            MarketTrend.VOLATILE: "showing mixed signals",
        }
        
        # Find strongest and weakest components
        sorted_comps = sorted(components, key=lambda c: c.raw_score, reverse=True)
        strongest = sorted_comps[0]
        weakest = sorted_comps[-1]
        
        return (
            f"Market conditions are {health} and {trend_desc[trend]}. "
            f"Strongest signal: {strongest.name.lower()} ({strongest.explanation.lower()}). "
            f"Watch: {weakest.name.lower()} ({weakest.explanation.lower()})."
        )


# =============================================================================
# AMENITY POINT SCORING (Geography-Specific)
# =============================================================================

@dataclass
class AmenityPointScore:
    """
    Amenity marginal value by geography.
    
    This is FAR more accurate than flat multipliers.
    
    Example:
    - Pool in Palm Springs (82% saturation) → 0.4 marginal value
    - Pool in Asheville (21% saturation) → 1.4 marginal value
    """
    amenity: str
    market_id: str
    
    # Saturation in market (0-1)
    saturation: float
    
    # Marginal value score (0-2, where 1.0 = neutral)
    marginal_value_score: float
    
    # ADR multiplier derived from marginal value
    adr_multiplier: float
    
    # Confidence
    confidence: float
    data_points: int
    
    # Explanation
    explanation: str


class AmenityScorer:
    """
    Calculates geography-specific amenity point scores.
    
    Uses:
    - Scraped amenity presence (saturation)
    - Internal booking performance (where available)
    - Price posture sensitivity
    """
    
    # Base multipliers (used when no market-specific data)
    BASE_MULTIPLIERS = {
        "pool": 1.10,
        "pool_heated": 1.03,
        "hot_tub": 1.05,
        "waterfront": 1.20,
        "gulf_view": 1.12,
        "ocean_view": 1.10,
        "pet_friendly": 1.03,
        "beach_access_private": 1.08,
        "beach_access_public": 1.03,
        "dock": 1.05,
        "elevator": 1.03,
        "game_room": 1.02,
        "home_theater": 1.02,
    }
    
    def score_amenity(
        self,
        amenity: str,
        market_id: str,
        saturation: float,
        internal_performance_delta: Optional[float] = None,
    ) -> AmenityPointScore:
        """
        Calculate amenity point score for a market.
        
        Args:
            amenity: Amenity name
            market_id: Market identifier
            saturation: % of listings with this amenity (0-1)
            internal_performance_delta: If available, observed ADR lift from internal data
            
        Returns:
            AmenityPointScore with market-specific value
        """
        base_mult = self.BASE_MULTIPLIERS.get(amenity, 1.0)
        
        # Calculate marginal value based on scarcity
        # Low saturation = high marginal value
        if saturation <= 0.15:
            scarcity_factor = 1.6
            explanation = f"{amenity} is rare in this market - strong premium potential"
        elif saturation <= 0.30:
            scarcity_factor = 1.3
            explanation = f"{amenity} is uncommon - good differentiation"
        elif saturation <= 0.50:
            scarcity_factor = 1.0
            explanation = f"{amenity} has moderate presence"
        elif saturation <= 0.70:
            scarcity_factor = 0.7
            explanation = f"{amenity} is common - limited premium"
        else:
            scarcity_factor = 0.4
            explanation = f"{amenity} is saturated - minimal differentiation"
        
        # Calculate marginal value
        marginal_value = (base_mult - 1.0) * scarcity_factor
        marginal_value_score = 1.0 + marginal_value
        
        # If we have internal data, blend it in
        if internal_performance_delta is not None:
            # Weight internal observation at 60%
            observed_mult = 1.0 + internal_performance_delta
            marginal_value_score = (marginal_value_score * 0.4) + (observed_mult * 0.6)
            confidence = 0.85
            data_points = 1  # Placeholder
        else:
            confidence = 0.65
            data_points = 0
        
        # Convert to ADR multiplier
        adr_multiplier = marginal_value_score
        
        return AmenityPointScore(
            amenity=amenity,
            market_id=market_id,
            saturation=saturation,
            marginal_value_score=round(marginal_value_score, 3),
            adr_multiplier=round(adr_multiplier, 3),
            confidence=confidence,
            data_points=data_points,
            explanation=explanation,
        )
    
    def score_all_amenities(
        self,
        market_id: str,
        saturation_data: Dict[str, float],
        internal_deltas: Optional[Dict[str, float]] = None,
    ) -> Dict[str, AmenityPointScore]:
        """Score all amenities for a market."""
        internal_deltas = internal_deltas or {}
        
        scores = {}
        for amenity in self.BASE_MULTIPLIERS.keys():
            saturation = saturation_data.get(amenity, 0.5)
            internal_delta = internal_deltas.get(amenity)
            
            scores[amenity] = self.score_amenity(
                amenity=amenity,
                market_id=market_id,
                saturation=saturation,
                internal_performance_delta=internal_delta,
            )
        
        return scores


# =============================================================================
# INTEGRATION: How External Signals Feed ADR Math
# =============================================================================

@dataclass
class ExternalSignalBundle:
    """
    Bundle of external signals for projection engine.
    
    This is what gets passed to RentProjectionEngine.
    External signals BOUND projections, they don't drive them.
    """
    market_id: str
    
    # Market health
    market_health: MarketHealthIndex
    
    # Amenity scores (market-specific)
    amenity_scores: Dict[str, AmenityPointScore]
    
    # Confidence in external data
    overall_confidence: float
    
    # How to use these signals
    # For EXISTING markets (has internal data)
    internal_weight: float = 0.65  # 65-75% internal
    external_weight: float = 0.35  # 25-35% external
    
    # For EXPANSION markets (no internal data)
    expansion_mode: bool = False
    expansion_internal_weight: float = 0.35  # 30-40% operator delta
    expansion_external_weight: float = 0.65  # 60-70% external
    
    def get_amenity_multiplier(self, amenity: str) -> float:
        """Get market-specific amenity multiplier."""
        if amenity in self.amenity_scores:
            return self.amenity_scores[amenity].adr_multiplier
        return 1.0
    
    def get_projection_weights(self) -> Tuple[float, float]:
        """Get appropriate weights for this market."""
        if self.expansion_mode:
            return self.expansion_internal_weight, self.expansion_external_weight
        return self.internal_weight, self.external_weight
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "market_health": self.market_health.to_dict(),
            "amenity_scores": {
                k: {
                    "saturation": v.saturation,
                    "multiplier": v.adr_multiplier,
                    "explanation": v.explanation,
                }
                for k, v in self.amenity_scores.items()
            },
            "weights": {
                "internal": self.internal_weight,
                "external": self.external_weight,
            },
            "expansion_mode": self.expansion_mode,
            "confidence": self.overall_confidence,
        }
