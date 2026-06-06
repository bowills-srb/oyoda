"""
Local Intelligence Service.

Provides geofenced lifestyle intelligence for the Guest Concierge Agent.

This is NOT property data - it's area/local knowledge:
- Activities (kids, couples, groups)
- Dining recommendations
- Rentals (jet skis, bikes, kayaks)
- Retail (grocery, boutiques, butchers)
- Services (spa, fishing charters)

Key Features:
1. Geofenced to property polygon
2. Seasonally aware
3. Guest profile aware (family, couple, group)
4. Operator-approved options prioritized
5. No pricing claims
6. No speculation

This feeds the Guest Concierge Agent (NOT the BD Agent).
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# POI CATEGORIES
# =============================================================================

class POICategory(str, Enum):
    """Point of Interest categories."""
    # Activities
    ACTIVITY_KIDS = "activity_kids"
    ACTIVITY_COUPLES = "activity_couples"
    ACTIVITY_GROUPS = "activity_groups"
    ACTIVITY_OUTDOOR = "activity_outdoor"
    ACTIVITY_WATER = "activity_water"
    ACTIVITY_ADVENTURE = "activity_adventure"
    ACTIVITY_RELAXATION = "activity_relaxation"
    
    # Dining
    DINING_CASUAL = "dining_casual"
    DINING_FINE = "dining_fine"
    DINING_SEAFOOD = "dining_seafood"
    DINING_FAMILY = "dining_family"
    DINING_BREAKFAST = "dining_breakfast"
    DINING_COFFEE = "dining_coffee"
    
    # Rentals
    RENTAL_WATER = "rental_water"  # Jet ski, kayak, paddleboard
    RENTAL_BIKE = "rental_bike"
    RENTAL_BEACH = "rental_beach"  # Chairs, umbrellas
    RENTAL_GOLF_CART = "rental_golf_cart"
    RENTAL_BOAT = "rental_boat"
    
    # Retail
    RETAIL_GROCERY = "retail_grocery"
    RETAIL_BOUTIQUE = "retail_boutique"
    RETAIL_SPECIALTY = "retail_specialty"  # Butcher, cheese, wine
    RETAIL_BEACH_GEAR = "retail_beach_gear"
    
    # Services
    SERVICE_SPA = "service_spa"
    SERVICE_FISHING = "service_fishing"
    SERVICE_TOURS = "service_tours"
    SERVICE_CHILDCARE = "service_childcare"
    
    # Attractions
    ATTRACTION_NATURE = "attraction_nature"
    ATTRACTION_MUSEUM = "attraction_museum"
    ATTRACTION_ENTERTAINMENT = "attraction_entertainment"


class GuestProfile(str, Enum):
    """Guest profile types for personalized recommendations."""
    FAMILY_YOUNG_KIDS = "family_young_kids"
    FAMILY_TEENS = "family_teens"
    COUPLE = "couple"
    GROUP_FRIENDS = "group_friends"
    SOLO = "solo"
    BUSINESS = "business"
    MULTI_GENERATIONAL = "multi_generational"


class Season(str, Enum):
    """Seasonal relevance."""
    PEAK_SUMMER = "peak_summer"
    SHOULDER_SPRING = "shoulder_spring"
    SHOULDER_FALL = "shoulder_fall"
    OFF_WINTER = "off_winter"
    HOLIDAY = "holiday"
    ALL_YEAR = "all_year"


# =============================================================================
# PROPERTY AMENITY (Deterministic Answers)
# =============================================================================

class PropertyAmenity(BaseModel):
    """
    Canonical amenity facts for deterministic answers.
    
    These are PROPERTY-SPECIFIC, not market signals.
    Confidence is always 1.0 (we know for certain).
    """
    property_id: UUID
    amenity_key: str  # keurig, bikes, pool_toys, grill, etc.
    available: bool = True
    details: Optional[str] = None  # "Located in the garage"
    confidence: float = 1.0  # Always certain for property amenities
    
    # Source
    source: str = "pms"  # pms, owner_provided, guest_verified
    last_verified: Optional[datetime] = None


# =============================================================================
# LOCAL INSIGHT (Aggregated Signal)
# =============================================================================

class LocalInsight(BaseModel):
    """
    Aggregated signal used for ranking and phrasing.
    
    This is a DERIVED signal, not raw data.
    """
    insight_id: UUID = Field(default_factory=uuid4)
    polygon_id: str
    
    # Topic
    topic: str  # kids_activities, dining, rentals, etc.
    season: Optional[str] = None
    
    # Strength & confidence
    insight_strength: float = 0.5  # How strong is this signal?
    confidence: float = 0.5  # How certain are we?
    
    # Derivation
    derived_from: List[str] = Field(default_factory=list)  # poi, guest_messages, operator_data
    
    # Expiration (for time decay)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    
    # For voice
    voice_phrase: Optional[str] = None  # Pre-approved phrasing


# =============================================================================
# CONFIDENCE THRESHOLDS (From Spec)
# =============================================================================

class ConfidenceThresholds:
    """
    Confidence thresholds for voice response behavior.
    
    From spec:
    - > 0.85 → freely answerable
    - 0.65–0.85 → cautious phrasing
    - < 0.65 → suggest alternatives or escalate
    """
    FREELY_ANSWERABLE = 0.85
    CAUTIOUS_PHRASING = 0.65
    ESCALATE = 0.65
    
    @classmethod
    def get_response_mode(cls, confidence: float) -> str:
        """Determine response mode based on confidence."""
        if confidence >= cls.FREELY_ANSWERABLE:
            return "direct"
        elif confidence >= cls.CAUTIOUS_PHRASING:
            return "cautious"
        else:
            return "escalate"


# =============================================================================
# POINT OF INTEREST
# =============================================================================

class PointOfInterest(BaseModel):
    """
    A local point of interest for recommendations.
    """
    poi_id: UUID = Field(default_factory=uuid4)
    
    # Basic info
    name: str
    description: str
    category: POICategory
    
    # Location
    latitude: float
    longitude: float
    address: Optional[str] = None
    
    # Distance (computed at query time)
    distance_miles: Optional[float] = None
    
    # Confidence & approval
    confidence: float = 0.5  # 0-1, how confident we are in this recommendation
    operator_approved: bool = False  # Has operator verified/approved this?
    
    # Seasonality
    seasonal_availability: List[Season] = Field(default_factory=lambda: [Season.ALL_YEAR])
    is_currently_operating: bool = True
    
    # Guest profiles this is good for
    suitable_for: List[GuestProfile] = Field(default_factory=list)
    
    # Popularity signals
    guest_mention_count: int = 0  # Times mentioned in guest messages
    external_rating: Optional[float] = None  # From Google/Yelp
    
    # Metadata
    source: str = "scraped"  # scraped, operator_added, guest_suggested
    last_verified: Optional[datetime] = None


# =============================================================================
# LOCAL RECOMMENDATION
# =============================================================================

class LocalRecommendation(BaseModel):
    """
    A curated recommendation for a guest.
    
    This is what the concierge returns - NOT raw POI data.
    """
    poi: PointOfInterest
    
    # Why we're recommending this
    relevance_score: float = 0.0  # Combined score
    match_reasons: List[str] = Field(default_factory=list)
    
    # Voice-safe description (no pricing claims)
    voice_description: str = ""
    
    # Can we help further?
    can_provide_directions: bool = True
    can_help_booking: bool = False  # Only if operator has integration


# =============================================================================
# LOCAL INTELLIGENCE SERVICE
# =============================================================================

class LocalIntelligenceService:
    """
    Provides geofenced local recommendations for the Guest Concierge.
    
    This is NOT property knowledge - it's area intelligence.
    
    The concierge can say:
    ✅ "Families often enjoy the Gulfarium"
    ✅ "Many guests recommend this restaurant"
    ✅ "This is a great time of year for dolphin tours"
    
    The concierge CANNOT say:
    ❌ Pricing information
    ❌ Availability guarantees
    ❌ Speculative claims
    """
    
    def __init__(self, geofence_id: str):
        self.geofence_id = geofence_id
        self._pois: Dict[UUID, PointOfInterest] = {}
        self._operator_favorites: Set[UUID] = set()
    
    def add_poi(self, poi: PointOfInterest) -> None:
        """Add a POI to the knowledge base."""
        self._pois[poi.poi_id] = poi
    
    def mark_operator_approved(self, poi_id: UUID) -> None:
        """Mark a POI as operator-approved."""
        self._operator_favorites.add(poi_id)
        if poi_id in self._pois:
            self._pois[poi_id].operator_approved = True
    
    def get_recommendations(
        self,
        property_lat: float,
        property_lng: float,
        category: Optional[POICategory] = None,
        guest_profile: Optional[GuestProfile] = None,
        current_season: Optional[Season] = None,
        max_distance_miles: float = 15.0,
        limit: int = 5,
    ) -> List[LocalRecommendation]:
        """
        Get recommendations for a guest.
        
        Prioritizes:
        1. Operator-approved options
        2. High confidence options
        3. Profile-appropriate options
        4. Seasonally relevant options
        5. Proximity
        """
        candidates = []
        
        for poi in self._pois.values():
            # Filter by category if specified
            if category and poi.category != category:
                continue
            
            # Calculate distance
            distance = self._calculate_distance(
                property_lat, property_lng,
                poi.latitude, poi.longitude
            )
            
            # Filter by distance
            if distance > max_distance_miles:
                continue
            
            poi.distance_miles = round(distance, 1)
            
            # Calculate relevance score
            score, reasons = self._calculate_relevance(
                poi, guest_profile, current_season, distance
            )
            
            candidates.append((poi, score, reasons))
        
        # Sort by score
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        # Build recommendations
        recommendations = []
        for poi, score, reasons in candidates[:limit]:
            rec = LocalRecommendation(
                poi=poi,
                relevance_score=score,
                match_reasons=reasons,
                voice_description=self._generate_voice_description(poi, reasons),
            )
            recommendations.append(rec)
        
        return recommendations
    
    def _calculate_distance(
        self,
        lat1: float, lng1: float,
        lat2: float, lng2: float,
    ) -> float:
        """Calculate distance in miles (simplified)."""
        import math
        
        # Haversine formula (simplified)
        R = 3959  # Earth's radius in miles
        
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lng = math.radians(lng2 - lng1)
        
        a = (math.sin(delta_lat/2)**2 + 
             math.cos(lat1_rad) * math.cos(lat2_rad) * 
             math.sin(delta_lng/2)**2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        return R * c
    
    def _calculate_relevance(
        self,
        poi: PointOfInterest,
        guest_profile: Optional[GuestProfile],
        current_season: Optional[Season],
        distance: float,
    ) -> Tuple[float, List[str]]:
        """
        Calculate relevance score for a POI.
        
        Ranking Formula (from spec):
        Rank Score =
          (Distance Weight * Proximity)
        + (Seasonal Relevance Weight * Season Match)
        + (Confidence Weight * Confidence Score)
        + (Operator Boost * Operator Approved)
        
        Weights are market-tuned but bounded:
        - Distance: 20-30%
        - Seasonality: 20-30%
        - Confidence: 30-40%
        - Operator boost: capped
        
        Returns (score, reasons).
        """
        # Weight configuration (bounded per spec)
        DISTANCE_WEIGHT = 0.25
        SEASONALITY_WEIGHT = 0.25
        CONFIDENCE_WEIGHT = 0.35
        OPERATOR_BOOST = 0.15  # Capped
        
        score = 0.0
        reasons = []
        
        # 1. Distance component (closer = better)
        # Normalize distance to 0-1 (15 miles = 0, 0 miles = 1)
        max_distance = 15.0
        proximity = max(0, 1 - (distance / max_distance))
        score += DISTANCE_WEIGHT * proximity
        
        if distance < 2:
            reasons.append("Very close to your property")
        elif distance < 5:
            reasons.append("Nearby")
        
        # 2. Seasonal relevance component
        season_match = 0.0
        if current_season:
            if Season.ALL_YEAR in poi.seasonal_availability:
                season_match = 0.8  # Year-round is good but not perfect match
            elif current_season in poi.seasonal_availability:
                season_match = 1.0  # Perfect seasonal match
                reasons.append("Currently in season")
            else:
                season_match = 0.2  # Out of season
        else:
            season_match = 0.5  # No season specified
        
        score += SEASONALITY_WEIGHT * season_match
        
        # 3. Confidence component
        score += CONFIDENCE_WEIGHT * poi.confidence
        
        if poi.confidence >= ConfidenceThresholds.FREELY_ANSWERABLE:
            pass  # High confidence, no special reason needed
        
        # 4. Operator boost (capped per spec)
        if poi.operator_approved:
            score += OPERATOR_BOOST
            reasons.append("Recommended by your host")
        
        # 5. Profile match bonus (additional)
        if guest_profile and guest_profile in poi.suitable_for:
            score += 0.1
            if guest_profile in [GuestProfile.FAMILY_YOUNG_KIDS, GuestProfile.FAMILY_TEENS]:
                reasons.append("Great for families")
            elif guest_profile == GuestProfile.COUPLE:
                reasons.append("Popular with couples")
        
        # 6. Social proof bonus (from guest mentions)
        if poi.guest_mention_count > 10:
            score += 0.05
            reasons.append("Frequently mentioned by guests")
        
        # 7. External rating bonus
        if poi.external_rating and poi.external_rating >= 4.5:
            score += 0.05
            reasons.append("Highly rated")
        
        return min(score, 1.0), reasons
    
    def _generate_voice_description(
        self,
        poi: PointOfInterest,
        reasons: List[str],
    ) -> str:
        """
        Generate a voice-safe description.
        
        NO pricing claims.
        NO availability guarantees.
        """
        parts = [poi.name]
        
        if poi.description:
            parts.append(f"- {poi.description}")
        
        if poi.distance_miles:
            parts.append(f"About {poi.distance_miles} miles away.")
        
        if reasons:
            parts.append(reasons[0] + ".")
        
        return " ".join(parts)
    
    def get_kids_activities(
        self,
        property_lat: float,
        property_lng: float,
        current_season: Optional[Season] = None,
    ) -> List[LocalRecommendation]:
        """
        Get kid-friendly activities.
        
        Common concierge question: "What activities are available for kids?"
        """
        return self.get_recommendations(
            property_lat=property_lat,
            property_lng=property_lng,
            category=POICategory.ACTIVITY_KIDS,
            guest_profile=GuestProfile.FAMILY_YOUNG_KIDS,
            current_season=current_season,
            limit=5,
        )
    
    def get_dining(
        self,
        property_lat: float,
        property_lng: float,
        guest_profile: Optional[GuestProfile] = None,
    ) -> List[LocalRecommendation]:
        """Get dining recommendations."""
        # Get multiple dining categories
        categories = [
            POICategory.DINING_CASUAL,
            POICategory.DINING_SEAFOOD,
            POICategory.DINING_FAMILY,
        ]
        
        all_recs = []
        for cat in categories:
            recs = self.get_recommendations(
                property_lat=property_lat,
                property_lng=property_lng,
                category=cat,
                guest_profile=guest_profile,
                limit=3,
            )
            all_recs.extend(recs)
        
        # Sort by relevance and dedupe
        all_recs.sort(key=lambda x: x.relevance_score, reverse=True)
        return all_recs[:5]
    
    def get_rentals(
        self,
        property_lat: float,
        property_lng: float,
        rental_type: Optional[str] = None,
    ) -> List[LocalRecommendation]:
        """Get rental recommendations (jet ski, bikes, etc.)."""
        category_map = {
            "water": POICategory.RENTAL_WATER,
            "bike": POICategory.RENTAL_BIKE,
            "beach": POICategory.RENTAL_BEACH,
            "golf_cart": POICategory.RENTAL_GOLF_CART,
            "boat": POICategory.RENTAL_BOAT,
        }
        
        category = category_map.get(rental_type) if rental_type else None
        
        return self.get_recommendations(
            property_lat=property_lat,
            property_lng=property_lng,
            category=category,
            limit=5,
        )


# =============================================================================
# CONCIERGE VS BD AGENT SEPARATION
# =============================================================================

class AgentDomainSeparation:
    """
    Defines the clear separation between Guest Concierge and BD agents.
    
    KEY PRINCIPLE:
    - BD produces insights
    - Concierge consumes sanitized conclusions, NOT raw math
    """
    
    # What BD Agent can access
    BD_ALLOWED = {
        "amenity_prevalence_aps": True,
        "seasonal_demand_signals": True,
        "market_confidence_states": True,
        "platform_dominance": True,
        "revenue_projections": True,
        "adr_calculations": True,
        "competitor_data": True,
        "booking_curves": True,
        "pricing_recommendations": True,
        "expansion_viability": True,
        "operator_benchmarking": True,
    }
    
    # What Concierge Agent can access
    CONCIERGE_ALLOWED = {
        "amenity_prevalence_aps": True,  # Shared
        "seasonal_demand_signals": True,  # Shared (for "great time for X")
        "market_confidence_states": True,  # Gated
        "platform_dominance": False,
        "revenue_projections": False,
        "adr_calculations": False,
        "competitor_data": False,
        "booking_curves": False,
        "pricing_recommendations": False,
        "expansion_viability": False,
        "operator_benchmarking": False,
        
        # Concierge-specific
        "property_knowledge_base": True,
        "local_intelligence": True,
        "guest_messaging_faqs": True,
        "operator_approved_recommendations": True,
    }
    
    # What Concierge can SAY (voice policy)
    CONCIERGE_CAN_SAY = [
        "This is a popular time for families in the area",
        "Many guests ask about this activity",
        "This place is well-reviewed by visitors",
        "Your host recommends...",
        "Families often enjoy...",
        "This is a great time of year for...",
    ]
    
    # What Concierge CANNOT SAY
    CONCIERGE_CANNOT_SAY = [
        "This area is underpriced",
        "Occupancy is high",
        "Rates are rising",
        "Competitors charge more",
        "The market is...",
        "Revenue projections...",
        "ADR is...",
    ]
    
    @classmethod
    def can_bd_access(cls, asset: str) -> bool:
        """Check if BD agent can access an asset."""
        return cls.BD_ALLOWED.get(asset, False)
    
    @classmethod
    def can_concierge_access(cls, asset: str) -> bool:
        """Check if Concierge agent can access an asset."""
        return cls.CONCIERGE_ALLOWED.get(asset, False)
    
    @classmethod
    def sanitize_for_concierge(cls, bd_output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize BD output for concierge consumption.
        
        Removes all financial/competitive data.
        Keeps only voice-safe signals.
        """
        safe_output = {}
        
        # Only pass through allowed fields
        allowed_for_concierge = [
            "seasonal_context",  # "It's peak season"
            "demand_level",  # "high" / "moderate" / "low" (not numbers)
            "popular_activities",  # From market signals
            "amenity_highlights",  # What's special about area
        ]
        
        for key in allowed_for_concierge:
            if key in bd_output:
                safe_output[key] = bd_output[key]
        
        # Add voice-safe interpretation
        if "demand_level" in safe_output:
            level = safe_output["demand_level"]
            if level == "high":
                safe_output["voice_hint"] = "This is a popular time to visit"
            elif level == "low":
                safe_output["voice_hint"] = "It's a quieter time in the area"
        
        return safe_output


# =============================================================================
# CONFIDENCE SCORING (From Spec)
# =============================================================================

class ConfidenceScorer:
    """
    Confidence scoring per spec.
    
    Confidence is NOT popularity. It reflects answer safety.
    
    Inputs:
    - Signal agreement across sources
    - Recency (time decay)
    - Volume of guest mentions
    - Stability across seasons
    
    Formula:
    Confidence = 
      (Source Agreement * 0.4)
    + (Time Decay Score * 0.3)
    + (Mention Consistency * 0.3)
    """
    
    SOURCE_AGREEMENT_WEIGHT = 0.4
    TIME_DECAY_WEIGHT = 0.3
    MENTION_CONSISTENCY_WEIGHT = 0.3
    
    @classmethod
    def calculate_confidence(
        cls,
        source_agreement: float,  # 0-1, how much sources agree
        days_since_last_signal: int,
        mention_count: int,
        mention_consistency: float,  # 0-1, stability across time
        decay_lambda: float = 0.05,  # Decay rate
    ) -> float:
        """
        Calculate confidence score.
        
        Args:
            source_agreement: Agreement across operator, guest, external sources
            days_since_last_signal: Days since last reinforcing signal
            mention_count: Total guest mentions
            mention_consistency: How stable mentions are across seasons
            decay_lambda: Exponential decay rate
            
        Returns:
            Confidence score 0-1
        """
        import math
        
        # Source agreement component
        source_score = source_agreement * cls.SOURCE_AGREEMENT_WEIGHT
        
        # Time decay component
        # Decay(t) = e^(-λ * days_since_last_signal)
        time_decay = math.exp(-decay_lambda * days_since_last_signal)
        time_score = time_decay * cls.TIME_DECAY_WEIGHT
        
        # Mention consistency component
        # Normalize mention count (100+ = max)
        mention_volume = min(mention_count / 100, 1.0)
        mention_score = (mention_volume * 0.5 + mention_consistency * 0.5) * cls.MENTION_CONSISTENCY_WEIGHT
        
        total = source_score + time_score + mention_score
        
        return min(max(total, 0.0), 1.0)


# =============================================================================
# TIME DECAY LOGIC (From Spec)
# =============================================================================

class TimeDecayCalculator:
    """
    Time decay logic per spec.
    
    Signals decay exponentially but reset when reinforced:
    Decay(t) = e^(-λ * days_since_last_signal)
    
    Different signal types have different decay rates:
    - Platform dominance (slow-decay): λ = 0.01
    - Event-driven signals (fast-decay): λ = 0.1
    - POI relevance (medium-decay): λ = 0.05
    """
    
    # Decay rates by signal type
    DECAY_RATES = {
        "platform_dominance": 0.01,  # Slow decay
        "seasonal_signal": 0.03,
        "poi_relevance": 0.05,  # Medium decay
        "guest_mention": 0.07,
        "event_driven": 0.10,  # Fast decay
    }
    
    @classmethod
    def calculate_decay(
        cls,
        signal_type: str,
        days_since_signal: int,
    ) -> float:
        """
        Calculate decay factor for a signal.
        
        Returns value 0-1 where 1 = fresh, 0 = fully decayed.
        """
        import math
        
        decay_rate = cls.DECAY_RATES.get(signal_type, 0.05)
        return math.exp(-decay_rate * days_since_signal)
    
    @classmethod
    def should_refresh(
        cls,
        signal_type: str,
        days_since_signal: int,
        threshold: float = 0.5,
    ) -> bool:
        """
        Check if a signal needs refreshing.
        
        Returns True if decay has dropped below threshold.
        """
        decay = cls.calculate_decay(signal_type, days_since_signal)
        return decay < threshold


# =============================================================================
# CONCIERGE QUERY PATH (From Spec)
# =============================================================================

class ConciergeQueryPath:
    """
    Implements the concierge query path from spec:
    
    1. Identify property_id
    2. Resolve polygon_id
    3. Determine intent (property vs local)
    4. Query appropriate index
    5. Apply confidence gating
    6. Enforce voice policy
    7. Respond
    """
    
    def __init__(
        self,
        local_service: 'LocalIntelligenceService',
        property_amenities: Dict[str, PropertyAmenity],
    ):
        self.local_service = local_service
        self.property_amenities = property_amenities
    
    def process_query(
        self,
        property_id: UUID,
        polygon_id: str,
        query: str,
        property_lat: float,
        property_lng: float,
        guest_profile: Optional[GuestProfile] = None,
        current_season: Optional[Season] = None,
    ) -> Dict[str, Any]:
        """
        Process a concierge query through the full path.
        """
        # Step 1: Identify property (done - passed in)
        # Step 2: Resolve polygon (done - passed in)
        
        # Step 3: Determine intent
        intent = self._determine_intent(query)
        
        # Step 4: Query appropriate index
        if intent == "property":
            result = self._query_property_amenities(property_id, query)
        else:
            result = self._query_local_intelligence(
                property_lat, property_lng, query,
                guest_profile, current_season
            )
        
        # Step 5: Apply confidence gating
        response_mode = ConfidenceThresholds.get_response_mode(result["confidence"])
        
        # Step 6: Enforce voice policy (check what can be said)
        result["response_mode"] = response_mode
        result["voice_safe"] = response_mode != "escalate"
        
        # Step 7: Return response data
        return result
    
    def _determine_intent(self, query: str) -> str:
        """Determine if query is about property or local area."""
        property_keywords = [
            "keurig", "coffee", "washer", "dryer", "grill", "pool",
            "hot tub", "bikes", "beach chairs", "wifi", "password",
            "check-in", "check-out", "key", "code", "trash"
        ]
        
        query_lower = query.lower()
        
        for kw in property_keywords:
            if kw in query_lower:
                return "property"
        
        return "local"
    
    def _query_property_amenities(
        self,
        property_id: UUID,
        query: str,
    ) -> Dict[str, Any]:
        """Query property-specific amenities."""
        # Find relevant amenity
        query_lower = query.lower()
        
        for key, amenity in self.property_amenities.items():
            if key in query_lower and str(amenity.property_id) == str(property_id):
                return {
                    "type": "property",
                    "found": True,
                    "amenity": amenity.amenity_key,
                    "available": amenity.available,
                    "details": amenity.details,
                    "confidence": amenity.confidence,  # Always 1.0 for property
                    "response": f"Yes, {'this property has' if amenity.available else 'this property does not have'} a {amenity.amenity_key}." + (f" {amenity.details}" if amenity.details else ""),
                }
        
        return {
            "type": "property",
            "found": False,
            "confidence": 0.0,
            "response": "I don't have specific information about that. Let me check with your host.",
        }
    
    def _query_local_intelligence(
        self,
        property_lat: float,
        property_lng: float,
        query: str,
        guest_profile: Optional[GuestProfile],
        current_season: Optional[Season],
    ) -> Dict[str, Any]:
        """Query local area intelligence."""
        # Determine category from query
        category = self._infer_category(query)
        
        recommendations = self.local_service.get_recommendations(
            property_lat=property_lat,
            property_lng=property_lng,
            category=category,
            guest_profile=guest_profile,
            current_season=current_season,
            limit=3,
        )
        
        if not recommendations:
            return {
                "type": "local",
                "found": False,
                "confidence": 0.3,
                "response": "I don't have specific recommendations for that right now.",
            }
        
        # Calculate aggregate confidence
        avg_confidence = sum(r.poi.confidence for r in recommendations) / len(recommendations)
        
        return {
            "type": "local",
            "found": True,
            "recommendations": [
                {
                    "name": r.poi.name,
                    "description": r.voice_description,
                    "distance_miles": r.poi.distance_miles,
                    "operator_approved": r.poi.operator_approved,
                }
                for r in recommendations
            ],
            "confidence": avg_confidence,
        }
    
    def _infer_category(self, query: str) -> Optional[POICategory]:
        """Infer POI category from query."""
        query_lower = query.lower()
        
        category_keywords = {
            POICategory.ACTIVITY_KIDS: ["kids", "children", "family", "child"],
            POICategory.DINING_SEAFOOD: ["seafood", "fish", "oyster"],
            POICategory.DINING_CASUAL: ["restaurant", "eat", "food", "dining"],
            POICategory.RENTAL_WATER: ["jet ski", "kayak", "paddleboard", "water rental"],
            POICategory.RETAIL_GROCERY: ["grocery", "supermarket", "food store"],
        }
        
        for category, keywords in category_keywords.items():
            if any(kw in query_lower for kw in keywords):
                return category
        
        return None
