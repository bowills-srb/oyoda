"""
Amenity ADR Attribution Engine

Learns what drives ADR differences from ACTUAL portfolio data.
This is the key differentiator - we don't guess at amenity lifts,
we CALCULATE them from real operator performance.

METHODOLOGY:
1. Load all properties with their amenities and actual ADR
2. Group by bedroom count (baseline control)
3. Compare ADR of properties WITH vs WITHOUT each amenity
4. Calculate lift = (avg_with - avg_without) / avg_without
5. Weight by sample size for confidence

This gives us REAL, DEFENSIBLE numbers for BD conversations:
- "Properties with pools in your market earn 18% more than those without"
- "Gulf views add $215/night on average for 4BR properties"

Usage:
    from app.services.analytics.amenity_attribution import AmenityAttributionEngine
    
    engine = AmenityAttributionEngine()
    results = engine.calculate_amenity_lifts()
    
    # Use in BD projections
    base_adr = 800
    property_amenities = ["pool", "gulf_view"]
    adjusted_adr = engine.apply_lifts(base_adr, property_amenities, bedrooms=4)
"""

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Any, Tuple
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor

from app.core.db_connect import resolve_runtime_sync_database_url

DATABASE_URL = resolve_runtime_sync_database_url(os.getenv("DATABASE_URL"))


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class AmenityLiftResult:
    """Result of amenity lift calculation from real data."""
    amenity: str
    
    # Lift calculation
    avg_adr_with: float
    avg_adr_without: float
    lift_pct: float  # (with - without) / without
    lift_dollars: float  # with - without
    
    # Sample sizes
    count_with: int
    count_without: int
    
    # Confidence based on sample size
    confidence: float
    
    # Statistical significance (simplified)
    is_significant: bool
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "amenity": self.amenity,
            "avg_adr_with": round(self.avg_adr_with, 2),
            "avg_adr_without": round(self.avg_adr_without, 2),
            "lift_pct": round(self.lift_pct, 4),
            "lift_dollars": round(self.lift_dollars, 2),
            "count_with": self.count_with,
            "count_without": self.count_without,
            "confidence": round(self.confidence, 3),
            "is_significant": self.is_significant,
        }


@dataclass
class BedroomAmenityLift:
    """Amenity lift for a specific bedroom count."""
    bedrooms: int
    amenity: str
    lift_pct: float
    lift_dollars: float
    sample_with: int
    sample_without: int
    confidence: float


@dataclass
class AmenityAttributionReport:
    """Complete amenity attribution analysis."""
    generated_at: datetime
    property_count: int
    
    # Overall lifts (across all bedrooms)
    overall_lifts: Dict[str, AmenityLiftResult]
    
    # Lifts by bedroom count
    lifts_by_bedroom: Dict[int, Dict[str, BedroomAmenityLift]]
    
    # Top drivers
    top_adr_drivers: List[str]
    
    # Voice-ready insights
    insights: List[str]


# =============================================================================
# AMENITY ATTRIBUTION ENGINE
# =============================================================================

class AmenityAttributionEngine:
    """
    Calculates amenity lifts from ACTUAL portfolio data.
    
    This is the source of truth for BD projections.
    """
    
    # Amenities to analyze
    AMENITIES = [
        "has_pool",
        "pool_heated", 
        "has_hot_tub",
        "has_grill",
        "has_bikes",
        "has_beach_gear",
        "has_washer_dryer",
        "pets_allowed",
    ]
    
    # Community-derived amenities (waterfront, beach access, etc.)
    COMMUNITY_WATERFRONT = ["watercolor", "watersound", "rosemary", "seacrest", "alys"]
    
    # Minimum sample size for confidence
    MIN_SAMPLE_SIZE = 3
    
    def __init__(self, database_url: str = None):
        self.database_url = database_url or DATABASE_URL
    
    def _get_connection(self):
        return psycopg2.connect(self.database_url, cursor_factory=RealDictCursor)
    
    def load_property_amenity_data(self) -> List[Dict[str, Any]]:
        """
        Load all properties with their amenities and ADR.
        """
        conn = self._get_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                p.property_code,
                p.bedrooms,
                p.bathrooms,
                p.sleeps,
                p.community,
                p.has_pool,
                p.pool_heated,
                p.has_hot_tub,
                p.has_grill,
                p.has_bikes,
                p.has_beach_gear,
                p.has_washer_dryer,
                p.pets_allowed,
                AVG(pr.adr) as avg_adr
            FROM properties p
            JOIN property_pricing pr ON p.property_code = pr.property_code
            WHERE pr.adr > 0 AND p.bedrooms > 0
            GROUP BY p.property_code, p.bedrooms, p.bathrooms, p.sleeps,
                     p.community, p.has_pool, p.pool_heated, p.has_hot_tub,
                     p.has_grill, p.has_bikes, p.has_beach_gear, 
                     p.has_washer_dryer, p.pets_allowed
        """)
        
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        # Add derived amenities
        properties = []
        for row in rows:
            prop = dict(row)
            # Derive waterfront from community
            community = (prop.get('community') or '').lower()
            prop['is_waterfront'] = any(c in community for c in self.COMMUNITY_WATERFRONT)
            properties.append(prop)
        
        return properties
    
    def calculate_lift_for_amenity(
        self,
        properties: List[Dict],
        amenity: str,
        bedrooms: int = None,
    ) -> Optional[AmenityLiftResult]:
        """
        Calculate lift for a single amenity.
        
        Args:
            properties: List of property dicts with amenities and ADR
            amenity: Amenity column name
            bedrooms: Optional bedroom filter
        
        Returns:
            AmenityLiftResult or None if insufficient data
        """
        # Filter by bedrooms if specified
        if bedrooms:
            props = [p for p in properties if p['bedrooms'] == bedrooms]
        else:
            props = properties
        
        # Split into with/without amenity
        with_amenity = [p for p in props if p.get(amenity)]
        without_amenity = [p for p in props if not p.get(amenity)]
        
        # Need minimum sample in both groups
        if len(with_amenity) < self.MIN_SAMPLE_SIZE or len(without_amenity) < self.MIN_SAMPLE_SIZE:
            return None
        
        # Calculate averages
        avg_with = sum(p['avg_adr'] for p in with_amenity) / len(with_amenity)
        avg_without = sum(p['avg_adr'] for p in without_amenity) / len(without_amenity)
        
        # Calculate lift
        if avg_without > 0:
            lift_pct = (avg_with - avg_without) / avg_without
        else:
            lift_pct = 0
        
        lift_dollars = avg_with - avg_without
        
        # Calculate confidence based on sample size
        # More samples = higher confidence
        total_sample = len(with_amenity) + len(without_amenity)
        min_group = min(len(with_amenity), len(without_amenity))
        
        # Confidence formula: starts at 0.5, maxes at 0.95
        # Needs ~20 samples to reach 0.9 confidence
        confidence = min(0.95, 0.5 + (min_group / 20) * 0.45)
        
        # Simple significance test: lift must be > 5% and have decent sample
        is_significant = abs(lift_pct) > 0.05 and min_group >= 5
        
        return AmenityLiftResult(
            amenity=amenity,
            avg_adr_with=float(avg_with),
            avg_adr_without=float(avg_without),
            lift_pct=lift_pct,
            lift_dollars=lift_dollars,
            count_with=len(with_amenity),
            count_without=len(without_amenity),
            confidence=confidence,
            is_significant=is_significant,
        )
    
    def calculate_bedroom_controlled_lift(self, properties: List[Dict], amenity: str) -> Optional[AmenityLiftResult]:
        """
        Calculate lift controlling for bedroom count.
        
        This is the CORRECT way to calculate amenity impact:
        1. For each bedroom count, calculate lift
        2. Weight by sample size
        3. Aggregate to overall lift
        
        This avoids confounding where e.g. non-pool properties happen
        to be larger homes with naturally higher ADR.
        """
        bedroom_counts = sorted(set(p['bedrooms'] for p in properties))
        
        weighted_lift_sum = 0.0
        weighted_dollars_sum = 0.0
        total_weight = 0
        total_with = 0
        total_without = 0
        confidences = []
        
        for beds in bedroom_counts:
            result = self.calculate_lift_for_amenity(properties, amenity, bedrooms=beds)
            if result and result.count_with >= 2 and result.count_without >= 2:
                # Weight by minimum sample size (bottleneck)
                weight = min(result.count_with, result.count_without)
                weighted_lift_sum += float(result.lift_pct) * weight
                weighted_dollars_sum += float(result.lift_dollars) * weight
                total_weight += weight
                total_with += result.count_with
                total_without += result.count_without
                confidences.append(float(result.confidence))
        
        if total_weight == 0:
            return None
        
        avg_lift = weighted_lift_sum / total_weight
        avg_dollars = weighted_dollars_sum / total_weight
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5
        
        return AmenityLiftResult(
            amenity=amenity,
            avg_adr_with=0,  # Not meaningful for controlled calculation
            avg_adr_without=0,
            lift_pct=float(avg_lift),
            lift_dollars=float(avg_dollars),
            count_with=total_with,
            count_without=total_without,
            confidence=float(avg_confidence),
            is_significant=abs(avg_lift) > 0.05 and total_weight >= 5,
        )
    
    def calculate_all_lifts(self) -> AmenityAttributionReport:
        """
        Calculate lifts for all amenities.
        
        Uses bedroom-controlled calculation for overall lifts
        to avoid confounding variables.
        
        Returns:
            AmenityAttributionReport with complete analysis
        """
        properties = self.load_property_amenity_data()
        
        if not properties:
            return AmenityAttributionReport(
                generated_at=datetime.utcnow(),
                property_count=0,
                overall_lifts={},
                lifts_by_bedroom={},
                top_adr_drivers=[],
                insights=["Insufficient data for amenity attribution"],
            )
        
        # Calculate bedroom-controlled overall lifts (THE CORRECT WAY)
        overall_lifts = {}
        amenities_to_check = self.AMENITIES + ['is_waterfront']
        
        for amenity in amenities_to_check:
            # Use bedroom-controlled calculation for overall
            result = self.calculate_bedroom_controlled_lift(properties, amenity)
            if result:
                overall_lifts[amenity] = result
        
        # Calculate lifts by bedroom count (raw, for detail view)
        bedroom_counts = sorted(set(p['bedrooms'] for p in properties))
        lifts_by_bedroom = {}
        
        for beds in bedroom_counts:
            lifts_by_bedroom[beds] = {}
            for amenity in amenities_to_check:
                result = self.calculate_lift_for_amenity(properties, amenity, bedrooms=beds)
                if result:
                    lifts_by_bedroom[beds][amenity] = BedroomAmenityLift(
                        bedrooms=beds,
                        amenity=amenity,
                        lift_pct=result.lift_pct,
                        lift_dollars=result.lift_dollars,
                        sample_with=result.count_with,
                        sample_without=result.count_without,
                        confidence=result.confidence,
                    )
        
        # Identify top ADR drivers
        significant_lifts = [
            (name, lift) for name, lift in overall_lifts.items()
            if lift.is_significant and lift.lift_pct > 0
        ]
        sorted_lifts = sorted(significant_lifts, key=lambda x: x[1].lift_pct, reverse=True)
        top_drivers = [name for name, _ in sorted_lifts[:5]]
        
        # Generate insights
        insights = self._generate_insights(overall_lifts, properties)
        
        return AmenityAttributionReport(
            generated_at=datetime.utcnow(),
            property_count=len(properties),
            overall_lifts=overall_lifts,
            lifts_by_bedroom=lifts_by_bedroom,
            top_adr_drivers=top_drivers,
            insights=insights,
        )
    
    def _generate_insights(
        self,
        lifts: Dict[str, AmenityLiftResult],
        properties: List[Dict],
    ) -> List[str]:
        """Generate voice-ready insights from the data."""
        insights = []
        
        # Pool insight
        if 'has_pool' in lifts:
            pool = lifts['has_pool']
            if pool.is_significant and pool.lift_pct > 0:
                insights.append(
                    f"Properties with pools earn {pool.lift_pct:.0%} more "
                    f"(${pool.lift_dollars:.0f}/night) than those without"
                )
        
        # Waterfront insight
        if 'is_waterfront' in lifts:
            wf = lifts['is_waterfront']
            if wf.is_significant and wf.lift_pct > 0:
                insights.append(
                    f"Waterfront communities command a {wf.lift_pct:.0%} premium "
                    f"(${wf.lift_dollars:.0f}/night average)"
                )
        
        # Hot tub insight (often a differentiator)
        if 'has_hot_tub' in lifts:
            ht = lifts['has_hot_tub']
            if ht.is_significant:
                if ht.lift_pct > 0:
                    insights.append(
                        f"Hot tubs add {ht.lift_pct:.0%} to ADR in this market"
                    )
                elif ht.lift_pct < -0.05:
                    insights.append(
                        "Hot tub presence doesn't correlate with higher ADR - "
                        "may not be a value driver in this market"
                    )
        
        # Top driver summary
        top_positive = [(n, l) for n, l in lifts.items() if l.is_significant and l.lift_pct > 0.1]
        if top_positive:
            top_positive.sort(key=lambda x: x[1].lift_pct, reverse=True)
            top_name = top_positive[0][0].replace('has_', '').replace('_', ' ')
            insights.append(
                f"Top ADR driver: {top_name} "
                f"(+{top_positive[0][1].lift_pct:.0%})"
            )
        
        return insights
    
    def apply_lifts(
        self,
        base_adr: float,
        property_amenities: List[str],
        bedrooms: int = None,
    ) -> Tuple[float, float, List[Dict]]:
        """
        Apply learned lifts to a base ADR.
        
        Args:
            base_adr: Starting ADR
            property_amenities: List of amenities the property has
            bedrooms: Bedroom count (for bedroom-specific lifts)
        
        Returns:
            (adjusted_adr, confidence, applied_lifts)
        """
        report = self.calculate_all_lifts()
        
        # Choose lifts source (bedroom-specific or overall)
        if bedrooms and bedrooms in report.lifts_by_bedroom:
            lifts_source = {
                name: BedroomAmenityLift(
                    bedrooms=bedrooms,
                    amenity=name,
                    lift_pct=lift.lift_pct,
                    lift_dollars=lift.lift_dollars,
                    sample_with=lift.count_with,
                    sample_without=lift.count_without,
                    confidence=lift.confidence,
                )
                for name, lift in report.lifts_by_bedroom[bedrooms].items()
            }
        else:
            lifts_source = {
                name: BedroomAmenityLift(
                    bedrooms=0,
                    amenity=name,
                    lift_pct=lift.lift_pct,
                    lift_dollars=lift.lift_dollars,
                    sample_with=lift.count_with,
                    sample_without=lift.count_without,
                    confidence=lift.confidence,
                )
                for name, lift in report.overall_lifts.items()
            }
        
        # Apply multiplicative lifts
        multiplier = 1.0
        confidences = []
        applied = []
        
        for amenity in property_amenities:
            # Map common names to database columns
            db_amenity = amenity
            if amenity == 'pool':
                db_amenity = 'has_pool'
            elif amenity == 'hot_tub':
                db_amenity = 'has_hot_tub'
            elif amenity == 'waterfront':
                db_amenity = 'is_waterfront'
            elif amenity == 'grill':
                db_amenity = 'has_grill'
            
            if db_amenity in lifts_source:
                lift = lifts_source[db_amenity]
                multiplier *= (1 + lift.lift_pct)
                confidences.append(lift.confidence)
                applied.append({
                    "amenity": amenity,
                    "lift_pct": lift.lift_pct,
                    "confidence": lift.confidence,
                })
        
        adjusted_adr = base_adr * multiplier
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5
        
        return adjusted_adr, avg_confidence, applied
    
    def get_attribution_summary(self) -> Dict[str, Any]:
        """
        Get a summary suitable for API response.
        """
        report = self.calculate_all_lifts()
        
        return {
            "generated_at": report.generated_at.isoformat(),
            "property_count": report.property_count,
            "overall_lifts": {
                name: lift.to_dict() 
                for name, lift in report.overall_lifts.items()
            },
            "lifts_by_bedroom": {
                str(beds): {
                    name: {
                        "lift_pct": round(lift.lift_pct, 4),
                        "lift_dollars": round(lift.lift_dollars, 2),
                        "sample_with": lift.sample_with,
                        "sample_without": lift.sample_without,
                        "confidence": round(lift.confidence, 3),
                    }
                    for name, lift in lifts.items()
                }
                for beds, lifts in report.lifts_by_bedroom.items()
            },
            "top_adr_drivers": report.top_adr_drivers,
            "insights": report.insights,
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_amenity_attribution() -> Dict[str, Any]:
    """Get amenity attribution summary."""
    engine = AmenityAttributionEngine()
    return engine.get_attribution_summary()


def calculate_adjusted_adr(
    base_adr: float,
    amenities: List[str],
    bedrooms: int = None,
) -> Tuple[float, float]:
    """
    Calculate ADR with amenity adjustments from real data.
    
    Returns (adjusted_adr, confidence)
    """
    engine = AmenityAttributionEngine()
    adjusted, confidence, _ = engine.apply_lifts(base_adr, amenities, bedrooms)
    return adjusted, confidence
