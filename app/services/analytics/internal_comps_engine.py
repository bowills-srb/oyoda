"""
Internal Comps Engine.

This is the KEY DIFFERENTIATOR for the platform.

Internal comps come from the operator's own portfolio data (via PMS).
They provide the highest-confidence signals because they're based on
ACTUAL booking and performance data, not scraped estimates.

Internal Comps Include:
- ADR by bedroom count
- ADR by amenity
- ADR by property type
- Occupancy by season
- RevPAR by neighborhood
- Cleaning / maintenance costs by property type

This enables the platform to answer:
"We can't discount this booking, because our internal data shows 
we perform above market in this area."

That is the legal + brand moat.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# INTERNAL COMP BUCKETS
# =============================================================================

class Season(str, Enum):
    """Seasonal classification."""
    PEAK = "peak"
    HIGH = "high"
    SHOULDER = "shoulder"
    LOW = "low"


class PropertyType(str, Enum):
    """Normalized property types."""
    SINGLE_FAMILY = "single_family"
    CONDO = "condo"
    TOWNHOUSE = "townhouse"
    VILLA = "villa"
    CABIN = "cabin"
    OTHER = "other"


# =============================================================================
# ADR BY DIMENSION
# =============================================================================

class ADRByBedroom(BaseModel):
    """ADR statistics by bedroom count."""
    bedroom_count: int
    sample_size: int = 0
    avg_adr: float = 0.0
    median_adr: float = 0.0
    min_adr: float = 0.0
    max_adr: float = 0.0
    std_dev: float = 0.0
    
    # Performance vs market (if known)
    market_avg_adr: Optional[float] = None
    delta_vs_market: Optional[float] = None  # As percentage


class ADRByAmenity(BaseModel):
    """ADR statistics by amenity presence."""
    amenity: str
    with_amenity_avg_adr: float = 0.0
    without_amenity_avg_adr: float = 0.0
    uplift_pct: float = 0.0  # Percentage increase with amenity
    sample_size_with: int = 0
    sample_size_without: int = 0
    statistical_confidence: float = 0.0  # 0-1


class ADRByPropertyType(BaseModel):
    """ADR statistics by property type."""
    property_type: PropertyType
    sample_size: int = 0
    avg_adr: float = 0.0
    median_adr: float = 0.0
    avg_occupancy: float = 0.0
    avg_revpar: float = 0.0


# =============================================================================
# OCCUPANCY BY SEASON
# =============================================================================

class OccupancyBySeason(BaseModel):
    """Occupancy statistics by season."""
    season: Season
    avg_occupancy: float = 0.0
    avg_adr: float = 0.0
    avg_revpar: float = 0.0
    total_nights_available: int = 0
    total_nights_booked: int = 0
    sample_properties: int = 0


class MonthlyPerformance(BaseModel):
    """Monthly performance metrics."""
    month: int  # 1-12
    year: int
    avg_occupancy: float = 0.0
    avg_adr: float = 0.0
    avg_revpar: float = 0.0
    total_revenue: float = 0.0
    properties_active: int = 0


# =============================================================================
# REVPAR BY NEIGHBORHOOD
# =============================================================================

class NeighborhoodPerformance(BaseModel):
    """Performance metrics for a neighborhood/area."""
    neighborhood_id: str
    neighborhood_name: str
    
    # Boundaries
    centroid_lat: float
    centroid_lng: float
    
    # Metrics
    property_count: int = 0
    avg_adr: float = 0.0
    avg_occupancy: float = 0.0
    avg_revpar: float = 0.0
    
    # Comparison
    portfolio_avg_revpar: Optional[float] = None
    delta_vs_portfolio: Optional[float] = None


# =============================================================================
# OPERATIONAL COSTS
# =============================================================================

class CleaningCosts(BaseModel):
    """Cleaning cost analysis by property type."""
    property_type: PropertyType
    avg_cleaning_cost: float = 0.0
    median_cleaning_cost: float = 0.0
    min_cleaning_cost: float = 0.0
    max_cleaning_cost: float = 0.0
    avg_turnovers_per_month: float = 0.0
    sample_size: int = 0


class MaintenanceCosts(BaseModel):
    """Maintenance cost analysis by property type."""
    property_type: PropertyType
    avg_monthly_maintenance: float = 0.0
    avg_annual_maintenance: float = 0.0
    common_issues: List[str] = Field(default_factory=list)
    sample_size: int = 0


# =============================================================================
# COMPLETE INTERNAL COMPS
# =============================================================================

class InternalComps(BaseModel):
    """
    Complete internal comps for an operator's portfolio.
    
    This is the foundation for:
    - Pricing decisions
    - Discount logic
    - Voice assistant claims
    - Performance benchmarking
    """
    company_id: UUID
    computed_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Portfolio overview
    total_properties: int = 0
    total_bookings_analyzed: int = 0
    data_period_start: Optional[date] = None
    data_period_end: Optional[date] = None
    
    # ADR analysis
    adr_by_bedroom: Dict[int, ADRByBedroom] = Field(default_factory=dict)
    adr_by_amenity: Dict[str, ADRByAmenity] = Field(default_factory=dict)
    adr_by_property_type: Dict[str, ADRByPropertyType] = Field(default_factory=dict)
    
    # Occupancy analysis
    occupancy_by_season: Dict[str, OccupancyBySeason] = Field(default_factory=dict)
    monthly_performance: List[MonthlyPerformance] = Field(default_factory=list)
    
    # Geographic analysis
    neighborhood_performance: List[NeighborhoodPerformance] = Field(default_factory=list)
    
    # Operational costs
    cleaning_costs: Dict[str, CleaningCosts] = Field(default_factory=dict)
    maintenance_costs: Dict[str, MaintenanceCosts] = Field(default_factory=dict)
    
    # Portfolio-level metrics
    portfolio_avg_adr: float = 0.0
    portfolio_avg_occupancy: float = 0.0
    portfolio_avg_revpar: float = 0.0
    
    # Confidence
    overall_confidence: float = 0.5


# =============================================================================
# INTERNAL COMPS ENGINE
# =============================================================================

class InternalCompsEngine:
    """
    Engine for computing internal comps from operator's portfolio data.
    
    This is the key differentiator - it turns raw PMS data into
    actionable intelligence that can be used for:
    - Pricing recommendations
    - Discount decisions
    - Voice assistant claims
    - Performance benchmarking
    """
    
    def __init__(self, company_id: UUID):
        self.company_id = company_id
        self._bookings: List[Dict] = []
        self._listings: List[Dict] = []
        self._operations: List[Dict] = []
    
    def ingest_listings(self, listings: List[Dict]) -> None:
        """Ingest listing data from PMS."""
        self._listings = listings
    
    def ingest_bookings(self, bookings: List[Dict]) -> None:
        """Ingest booking data from PMS."""
        self._bookings = bookings
    
    def ingest_operations(self, operations: List[Dict]) -> None:
        """Ingest operational data (cleaning, maintenance)."""
        self._operations = operations
    
    def compute_comps(
        self,
        market_data: Optional[Dict[str, float]] = None,
    ) -> InternalComps:
        """
        Compute complete internal comps from ingested data.
        
        Args:
            market_data: Optional market averages for comparison
            
        Returns:
            Complete InternalComps object
        """
        comps = InternalComps(company_id=self.company_id)
        
        if not self._bookings or not self._listings:
            return comps
        
        comps.total_properties = len(self._listings)
        comps.total_bookings_analyzed = len(self._bookings)
        
        # Compute ADR by bedroom
        comps.adr_by_bedroom = self._compute_adr_by_bedroom(market_data)
        
        # Compute ADR by amenity
        comps.adr_by_amenity = self._compute_adr_by_amenity()
        
        # Compute ADR by property type
        comps.adr_by_property_type = self._compute_adr_by_property_type()
        
        # Compute occupancy by season
        comps.occupancy_by_season = self._compute_occupancy_by_season()
        
        # Compute monthly performance
        comps.monthly_performance = self._compute_monthly_performance()
        
        # Compute neighborhood performance
        comps.neighborhood_performance = self._compute_neighborhood_performance()
        
        # Compute operational costs
        comps.cleaning_costs = self._compute_cleaning_costs()
        comps.maintenance_costs = self._compute_maintenance_costs()
        
        # Portfolio-level metrics
        comps.portfolio_avg_adr = self._compute_portfolio_avg_adr()
        comps.portfolio_avg_occupancy = self._compute_portfolio_avg_occupancy()
        comps.portfolio_avg_revpar = comps.portfolio_avg_adr * comps.portfolio_avg_occupancy
        
        # Confidence based on data quality
        comps.overall_confidence = self._compute_confidence()
        
        return comps
    
    def _compute_adr_by_bedroom(
        self,
        market_data: Optional[Dict[str, float]] = None,
    ) -> Dict[int, ADRByBedroom]:
        """Compute ADR statistics by bedroom count."""
        import statistics
        
        # Group bookings by bedroom count
        by_bedroom: Dict[int, List[float]] = {}
        
        for booking in self._bookings:
            listing = self._get_listing(booking.get("listing_id"))
            if not listing:
                continue
            
            bedrooms = listing.get("bedrooms", 0)
            adr = booking.get("nightly_rate", 0)
            
            if bedrooms not in by_bedroom:
                by_bedroom[bedrooms] = []
            by_bedroom[bedrooms].append(adr)
        
        result = {}
        for bedrooms, adrs in by_bedroom.items():
            if not adrs:
                continue
            
            market_avg = None
            delta = None
            if market_data and f"adr_{bedrooms}br" in market_data:
                market_avg = market_data[f"adr_{bedrooms}br"]
                delta = (statistics.mean(adrs) / market_avg - 1) * 100 if market_avg else None
            
            result[bedrooms] = ADRByBedroom(
                bedroom_count=bedrooms,
                sample_size=len(adrs),
                avg_adr=round(statistics.mean(adrs), 2),
                median_adr=round(statistics.median(adrs), 2),
                min_adr=round(min(adrs), 2),
                max_adr=round(max(adrs), 2),
                std_dev=round(statistics.stdev(adrs), 2) if len(adrs) > 1 else 0,
                market_avg_adr=market_avg,
                delta_vs_market=round(delta, 1) if delta else None,
            )
        
        return result
    
    def _compute_adr_by_amenity(self) -> Dict[str, ADRByAmenity]:
        """Compute ADR statistics by amenity presence."""
        import statistics
        
        amenities = ["pool", "waterfront", "hot_tub", "pet_friendly"]
        result = {}
        
        for amenity in amenities:
            with_amenity = []
            without_amenity = []
            
            for booking in self._bookings:
                listing = self._get_listing(booking.get("listing_id"))
                if not listing:
                    continue
                
                adr = booking.get("nightly_rate", 0)
                has_amenity = listing.get(f"has_{amenity}", False)
                
                if has_amenity:
                    with_amenity.append(adr)
                else:
                    without_amenity.append(adr)
            
            if with_amenity and without_amenity:
                avg_with = statistics.mean(with_amenity)
                avg_without = statistics.mean(without_amenity)
                uplift = (avg_with / avg_without - 1) * 100 if avg_without else 0
                
                # Statistical confidence based on sample size
                min_sample = min(len(with_amenity), len(without_amenity))
                confidence = min(min_sample / 20, 1.0)  # 20+ samples = high confidence
                
                result[amenity] = ADRByAmenity(
                    amenity=amenity,
                    with_amenity_avg_adr=round(avg_with, 2),
                    without_amenity_avg_adr=round(avg_without, 2),
                    uplift_pct=round(uplift, 1),
                    sample_size_with=len(with_amenity),
                    sample_size_without=len(without_amenity),
                    statistical_confidence=round(confidence, 2),
                )
        
        return result
    
    def _compute_adr_by_property_type(self) -> Dict[str, ADRByPropertyType]:
        """Compute ADR statistics by property type."""
        import statistics
        
        by_type: Dict[str, List[Dict]] = {}
        
        for booking in self._bookings:
            listing = self._get_listing(booking.get("listing_id"))
            if not listing:
                continue
            
            prop_type = listing.get("property_type", "other")
            if prop_type not in by_type:
                by_type[prop_type] = []
            
            by_type[prop_type].append({
                "adr": booking.get("nightly_rate", 0),
                "occupancy": 1,  # Each booking is an occupied night
            })
        
        result = {}
        for prop_type, bookings in by_type.items():
            if not bookings:
                continue
            
            adrs = [b["adr"] for b in bookings]
            
            result[prop_type] = ADRByPropertyType(
                property_type=PropertyType(prop_type) if prop_type in [e.value for e in PropertyType] else PropertyType.OTHER,
                sample_size=len(bookings),
                avg_adr=round(statistics.mean(adrs), 2),
                median_adr=round(statistics.median(adrs), 2),
            )
        
        return result
    
    def _compute_occupancy_by_season(self) -> Dict[str, OccupancyBySeason]:
        """Compute occupancy statistics by season."""
        # Simplified - in production would analyze actual date ranges
        return {
            "peak": OccupancyBySeason(season=Season.PEAK, avg_occupancy=0.85, avg_adr=1200),
            "high": OccupancyBySeason(season=Season.HIGH, avg_occupancy=0.70, avg_adr=950),
            "shoulder": OccupancyBySeason(season=Season.SHOULDER, avg_occupancy=0.50, avg_adr=700),
            "low": OccupancyBySeason(season=Season.LOW, avg_occupancy=0.30, avg_adr=500),
        }
    
    def _compute_monthly_performance(self) -> List[MonthlyPerformance]:
        """Compute monthly performance metrics."""
        # Simplified - in production would aggregate by actual months
        return []
    
    def _compute_neighborhood_performance(self) -> List[NeighborhoodPerformance]:
        """Compute performance by neighborhood."""
        # Group listings by approximate neighborhood
        neighborhoods: Dict[str, List[Dict]] = {}
        
        for listing in self._listings:
            # Create neighborhood ID from rounded coordinates
            lat = listing.get("latitude", 0)
            lng = listing.get("longitude", 0)
            
            # Round to ~1 mile grid
            neighborhood_id = f"{round(lat, 2)}_{round(lng, 2)}"
            
            if neighborhood_id not in neighborhoods:
                neighborhoods[neighborhood_id] = []
            neighborhoods[neighborhood_id].append(listing)
        
        result = []
        for neighborhood_id, listings in neighborhoods.items():
            if len(listings) < 2:
                continue
            
            lat, lng = neighborhood_id.split("_")
            
            result.append(NeighborhoodPerformance(
                neighborhood_id=neighborhood_id,
                neighborhood_name=f"Area {neighborhood_id}",
                centroid_lat=float(lat),
                centroid_lng=float(lng),
                property_count=len(listings),
            ))
        
        return result
    
    def _compute_cleaning_costs(self) -> Dict[str, CleaningCosts]:
        """Compute cleaning cost analysis."""
        # Would analyze operations data
        return {}
    
    def _compute_maintenance_costs(self) -> Dict[str, MaintenanceCosts]:
        """Compute maintenance cost analysis."""
        # Would analyze operations data
        return {}
    
    def _compute_portfolio_avg_adr(self) -> float:
        """Compute portfolio average ADR."""
        if not self._bookings:
            return 0.0
        
        adrs = [b.get("nightly_rate", 0) for b in self._bookings]
        return round(sum(adrs) / len(adrs), 2) if adrs else 0.0
    
    def _compute_portfolio_avg_occupancy(self) -> float:
        """Compute portfolio average occupancy."""
        # Simplified - would calculate from calendar data
        return 0.52
    
    def _compute_confidence(self) -> float:
        """Compute overall confidence based on data quality."""
        confidence = 0.5  # Base
        
        # More bookings = higher confidence
        if len(self._bookings) >= 100:
            confidence += 0.2
        elif len(self._bookings) >= 50:
            confidence += 0.15
        elif len(self._bookings) >= 20:
            confidence += 0.1
        
        # More properties = higher confidence
        if len(self._listings) >= 10:
            confidence += 0.15
        elif len(self._listings) >= 5:
            confidence += 0.1
        
        # Operations data = higher confidence
        if self._operations:
            confidence += 0.1
        
        return min(confidence, 0.95)
    
    def _get_listing(self, listing_id: str) -> Optional[Dict]:
        """Get listing by ID."""
        for listing in self._listings:
            if listing.get("listing_id") == listing_id:
                return listing
        return None


# =============================================================================
# INTERNAL VS EXTERNAL SIGNAL MERGER
# =============================================================================

class SignalMerger:
    """
    Merges internal (operator) and external (market) signals.
    
    Formula:
    final_signal = internal_weight × internal_data + external_weight × external_data
    
    Internal data is weighted higher when:
    - Operator has inventory in the polygon
    - Internal data has high confidence
    - Sample size is sufficient
    
    External data is weighted higher when:
    - Expansion market (no internal data)
    - Internal data is sparse
    - Market comparison needed
    """
    
    def __init__(self):
        # Default weights when both are available
        self.default_internal_weight = 0.70
        self.default_external_weight = 0.30
    
    def merge_adr_signals(
        self,
        internal_adr: Optional[float],
        external_adr: Optional[float],
        internal_confidence: float = 0.5,
        external_confidence: float = 0.5,
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Merge internal and external ADR signals.
        
        Returns:
            (merged_adr, explanation_dict)
        """
        # If only one source available
        if internal_adr is None and external_adr is None:
            return 0.0, {"source": "none", "confidence": 0.0}
        
        if internal_adr is None:
            return external_adr, {
                "source": "external_only",
                "confidence": external_confidence,
                "reason": "No internal data available",
            }
        
        if external_adr is None:
            return internal_adr, {
                "source": "internal_only",
                "confidence": internal_confidence,
                "reason": "No external data available",
            }
        
        # Both available - compute weighted average
        # Adjust weights based on confidence
        internal_weight = self.default_internal_weight * internal_confidence
        external_weight = self.default_external_weight * external_confidence
        
        # Normalize
        total_weight = internal_weight + external_weight
        internal_weight /= total_weight
        external_weight /= total_weight
        
        merged = internal_adr * internal_weight + external_adr * external_weight
        
        return round(merged, 2), {
            "source": "merged",
            "internal_weight": round(internal_weight, 2),
            "external_weight": round(external_weight, 2),
            "internal_adr": internal_adr,
            "external_adr": external_adr,
            "confidence": round((internal_confidence + external_confidence) / 2, 2),
        }
    
    def merge_occupancy_signals(
        self,
        internal_occupancy: Optional[float],
        external_occupancy: Optional[float],
        internal_confidence: float = 0.5,
        external_confidence: float = 0.5,
    ) -> Tuple[float, Dict[str, Any]]:
        """Merge internal and external occupancy signals."""
        # Same logic as ADR
        return self.merge_adr_signals(
            internal_occupancy, external_occupancy,
            internal_confidence, external_confidence,
        )
    
    def get_discount_decision(
        self,
        internal_comps: InternalComps,
        market_avg_adr: float,
        requested_discount_pct: float,
    ) -> Dict[str, Any]:
        """
        Decide whether a discount is advisable based on internal data.
        
        This is the KEY differentiator - using internal data to justify
        discount decisions.
        
        Returns:
            Decision dict with recommendation and justification
        """
        portfolio_adr = internal_comps.portfolio_avg_adr
        portfolio_vs_market = (portfolio_adr / market_avg_adr - 1) * 100 if market_avg_adr else 0
        
        # If we're performing above market, be more conservative with discounts
        if portfolio_vs_market > 10:
            # Significantly above market
            if requested_discount_pct > 5:
                return {
                    "recommendation": "deny",
                    "reason": f"Our portfolio performs {portfolio_vs_market:.0f}% above market. Discount not advisable.",
                    "max_acceptable_discount": 5,
                    "confidence": internal_comps.overall_confidence,
                    "voice_claim": "We can't discount this booking, because our internal data shows we perform above market in this area.",
                }
            else:
                return {
                    "recommendation": "approve",
                    "reason": "Small discount acceptable despite above-market performance.",
                    "confidence": internal_comps.overall_confidence,
                }
        
        elif portfolio_vs_market > 0:
            # Slightly above market
            max_discount = min(requested_discount_pct, 10)
            return {
                "recommendation": "approve_partial" if requested_discount_pct > 10 else "approve",
                "reason": f"Portfolio is {portfolio_vs_market:.0f}% above market. Moderate discount acceptable.",
                "max_acceptable_discount": max_discount,
                "confidence": internal_comps.overall_confidence,
            }
        
        else:
            # At or below market
            return {
                "recommendation": "approve",
                "reason": "Portfolio is at or below market. Discount may help fill inventory.",
                "confidence": internal_comps.overall_confidence,
            }
