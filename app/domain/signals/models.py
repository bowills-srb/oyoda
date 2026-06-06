"""
Domain: Signals - Pure Models.

No FastAPI. No DB sessions. No external API calls.
Pure inputs → outputs.

This is the canonical truth for what a Signal IS in this system.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4


# =============================================================================
# SIGNAL TYPES (Exhaustive Enum)
# =============================================================================

class SignalType(str, Enum):
    """
    All signal types in the system.
    
    Detectors produce these. Engines consume these.
    Nothing else creates market intelligence.
    """
    # Market Structure
    PLATFORM_DOMINANCE = "platform_dominance"
    SUPPLY_VELOCITY = "supply_velocity"
    DEMAND_PRESSURE = "demand_pressure"
    
    # Pricing
    SEASONALITY_CURVE = "seasonality_curve"
    AMENITY_LIFT = "amenity_lift"
    PRICE_ELASTICITY = "price_elasticity"
    RATE_POSITION = "rate_position"
    
    # Performance
    OCCUPANCY_MOMENTUM = "occupancy_momentum"
    REVENUE_TRAJECTORY = "revenue_trajectory"
    BOOKING_LEAD_TIME = "booking_lead_time"
    
    # Operator
    OPERATOR_DELTA = "operator_delta"
    PORTFOLIO_CONSISTENCY = "portfolio_consistency"
    
    # Guest Intelligence
    GUEST_INTENT_FREQUENCY = "guest_intent_frequency"
    SENTIMENT_TREND = "sentiment_trend"
    UNMET_DEMAND = "unmet_demand"
    
    # Competitive
    COMPETITOR_RATE_MOVEMENT = "competitor_rate_movement"
    INVENTORY_PRESSURE = "inventory_pressure"
    
    # Expansion
    MARKET_SIMILARITY = "market_similarity"
    EXPANSION_FIT = "expansion_fit"


class SignalScope(str, Enum):
    """Scope at which signal applies."""
    PROPERTY = "property"
    GEO = "geo"
    MARKET = "market"
    PLATFORM = "platform"
    TENANT = "tenant"


class SignalSource(str, Enum):
    """Source of signal data."""
    AIRBNB_SCRAPE = "airbnb_scrape"
    VRBO_SCRAPE = "vrbo_scrape"
    PMS_DATA = "pms_data"
    INTERNAL_ANALYTICS = "internal_analytics"
    INTERNAL_COMP = "internal_analytics"
    INTERNAL_COMPS = "internal_analytics"
    GUEST_MESSAGES = "guest_messages"
    FEDERAL_DATA = "federal_data"
    DERIVED = "derived"


# =============================================================================
# SIGNAL MODEL (Pure Domain Object)
# =============================================================================

@dataclass
class Signal:
    """
    Canonical Signal domain object.
    
    Detectors produce these. Nothing else.
    This is a pure data object - no behavior except validation.
    """
    id: UUID
    tenant_id: UUID
    signal_type: SignalType
    scope: SignalScope
    
    value: float
    confidence: float  # 0.0 to 1.0
    
    source: SignalSource
    detected_at: datetime
    time_window: str  # e.g., "30d", "7d", "1d"
    
    geo_id: Optional[str] = None
    property_id: Optional[UUID] = None
    weight_hint: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None
    version: str = "1.0.0"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def __post_init__(self):
        """Validate signal invariants."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be 0.0-1.0, got {self.confidence}")
        if self.weight_hint is not None and not 0.0 <= self.weight_hint <= 1.0:
            raise ValueError(f"Weight hint must be 0.0-1.0, got {self.weight_hint}")
    
    @classmethod
    def create(
        cls,
        tenant_id: UUID,
        signal_type: SignalType,
        scope: SignalScope,
        value: float,
        confidence: float,
        source: SignalSource,
        time_window: str,
        geo_id: Optional[str] = None,
        property_id: Optional[UUID] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "Signal":
        """Factory method for creating signals."""
        return cls(
            id=uuid4(),
            tenant_id=tenant_id,
            signal_type=signal_type,
            scope=scope,
            value=value,
            confidence=confidence,
            source=source,
            detected_at=datetime.now(timezone.utc),
            time_window=time_window,
            geo_id=geo_id,
            property_id=property_id,
            metadata=metadata,
        )


# =============================================================================
# SIGNAL LIFECYCLE STAGES
# =============================================================================

class SignalStage(str, Enum):
    """
    Explicit signal lifecycle stages.
    
    Raw Data → Normalized Entity → Signal (contract) → 
    Weighted Signal → Regime / Narrative / Pricing Impact
    """
    RAW = "raw"              # Just ingested
    NORMALIZED = "normalized"  # Canonical schema applied
    CONTRACTED = "contracted"  # Meets signal contract
    WEIGHTED = "weighted"      # Decay/confidence applied
    APPLIED = "applied"        # Used in decision/output


@dataclass
class SignalLifecycleEvent:
    """Record of a signal moving through lifecycle."""
    signal_id: UUID
    from_stage: SignalStage
    to_stage: SignalStage
    timestamp: datetime
    processor: str  # Which component processed it
    metadata: Optional[Dict[str, Any]] = None


# =============================================================================
# ATTRIBUTION
# =============================================================================

@dataclass
class SignalAttribution:
    """
    Full attribution trail for a signal.
    
    This is critical for:
    - Defensible market analysis
    - Regulatory compliance
    - Debugging/auditing
    """
    signal_id: UUID
    
    # Source attribution
    source_type: SignalSource
    source_id: str  # Platform listing ID, PMS record ID, etc.
    source_url: Optional[str] = None
    
    # Collection metadata
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    collection_method: str = ""  # "api", "scrape", "import"
    
    # Processing chain
    processors: List[str] = field(default_factory=list)  # ["normalizer", "detector", "weighter"]
    
    # Confidence factors
    source_reliability: float = 0.8  # How reliable is this source historically
    freshness_score: float = 1.0     # Decays over time
    
    def to_audit_dict(self) -> Dict[str, Any]:
        """Export for audit logging."""
        return {
            "signal_id": str(self.signal_id),
            "source_type": self.source_type.value,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "collected_at": self.collected_at.isoformat(),
            "collection_method": self.collection_method,
            "processors": self.processors,
            "source_reliability": self.source_reliability,
            "freshness_score": self.freshness_score,
        }


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Types
    "SignalType",
    "SignalScope",
    "SignalSource",
    "SignalStage",
    
    # Models
    "Signal",
    "SignalLifecycleEvent",
    "SignalAttribution",
]
