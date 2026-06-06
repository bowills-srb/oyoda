"""
Shared Schemas Package.

These schemas are the CANONICAL data spine.
BD and Concierge consume these - they do NOT own their own models.

Core Schemas (v1.0.0):
- Tenant, Operator, Property, Listing, Booking
- GuestProfile, MessageThread, Message
- GeoPolygon, MarketSnapshot, AnalyticsResult

Signal Schemas (v2.0.0) - canonical_signals.py:
- Signal - Base signal with confidence bands
- SignalBundle - Collection with coverage scoring
- Type-specific signals (Supply, Demand, Rate, etc.)

Contracts (v1.0.0):
- Canonical API contracts (the internal RFC)
- All API boundaries defined here
"""

# =============================================================================
# CANONICAL SIGNALS (v2.0 - Use These for new code)
# =============================================================================

from schemas.canonical_signals import (
    # Enums
    SignalType as CanonicalSignalType,
    SignalSource as CanonicalSignalSource,
    ConfidenceLevel,
    
    # Base signal
    Signal as CanonicalSignal,
    SignalBundle as CanonicalSignalBundle,
    
    # Supply signals
    SupplyDensitySignal,
    SupplyDensityValue,
    BedroomDistributionSignal,
    BedroomDistributionValue,
    
    # Demand signals
    CalendarCompressionSignal,
    CalendarCompressionValue,
    LeadTimeSignal,
    LeadTimeValue,
    
    # Platform signals
    PlatformDominanceSignal,
    PlatformDominanceValue,
    
    # Amenity signals
    AmenityPrevalenceSignal,
    AmenityPrevalenceValue,
    AmenityLiftSignal,
    AmenityLiftValue,
    
    # Seasonality signals
    SeasonalityCurveSignal,
    SeasonalityCurveValue,
    
    # Rate signals
    RatePositionSignal,
    RatePositionValue,
    
    # Operator signals
    OperatorDeltaSignal,
    OperatorDeltaValue,
    
    # Macro signals
    HousingStockSignal,
    HousingStockValue,
    TravelFlowSignal,
    TravelFlowValue,
    RegulatoryRiskSignal,
    RegulatoryRiskValue,
)

# =============================================================================
# CORE ENTITIES
# =============================================================================

from schemas.core import (
    # Version
    SCHEMA_VERSION,
    get_schema_version,
    get_all_schemas,
    
    # Enums
    BookingChannel,
    PropertyType,
    ListingStatus,
    BookingStatus,
    MessageDirection,
    GuestType,
    
    # Base models
    TenantScopedModel,
    TimestampedModel,
    
    # Core entities
    Tenant,
    Operator,
    Property,
    Listing,
    Booking,
    GuestProfile,
    MessageThread,
    Message,
    GeoPolygon,
    MarketSnapshot,
    AnalyticsResult,
)

from schemas.contracts import (
    # Version
    CONTRACT_VERSION,
    
    # Signal contracts
    Signal as SignalContract,
    SignalBundle as SignalBundleContract,
    
    # Gating
    GatingDecision,
    GatingResult,
    
    # Analytics
    AttributionDriver,
    MetricType,
    
    # Property
    PropertyProfile,
    AmenityScore,
    
    # Projection
    RentProjection,
    MonthlyProjection as MonthlyProjectionContract,
    ComparableProperty,
    
    # Operator & Expansion
    OperatorProfile,
    ExpansionReadiness,
    
    # Concierge
    GuestMessage,
    KnowledgeFact,
    ConciergeResponse,
    
    # Discount
    DiscountDecision,
    DiscountEvaluation,
    
    # BNPL
    BNPLEligibility,
    
    # Investment
    InvestmentMetrics,
    InvestmentScore,
    
    # Narrative
    NarrativeAudience,
    NarrativeBlock,
    
    # API Responses
    APIResponse,
    RentProjectionResponse,
    AnalyticsResponse,
    ConciergeResponseAPI,
    DiscountResponse,
    ExpansionResponse,
    InvestmentResponse,
)

__all__ = [
    # ==========================================================================
    # CANONICAL SIGNALS (v2.0 - Use these for new code)
    # ==========================================================================
    "CanonicalSignalType",
    "CanonicalSignalSource", 
    "ConfidenceLevel",
    "CanonicalSignal",
    "CanonicalSignalBundle",
    
    # Supply signals
    "SupplyDensitySignal", "SupplyDensityValue",
    "BedroomDistributionSignal", "BedroomDistributionValue",
    
    # Demand signals
    "CalendarCompressionSignal", "CalendarCompressionValue",
    "LeadTimeSignal", "LeadTimeValue",
    
    # Platform signals
    "PlatformDominanceSignal", "PlatformDominanceValue",
    
    # Amenity signals
    "AmenityPrevalenceSignal", "AmenityPrevalenceValue",
    "AmenityLiftSignal", "AmenityLiftValue",
    
    # Seasonality signals
    "SeasonalityCurveSignal", "SeasonalityCurveValue",
    
    # Rate signals
    "RatePositionSignal", "RatePositionValue",
    
    # Operator signals
    "OperatorDeltaSignal", "OperatorDeltaValue",
    
    # Macro signals
    "HousingStockSignal", "HousingStockValue",
    "TravelFlowSignal", "TravelFlowValue",
    "RegulatoryRiskSignal", "RegulatoryRiskValue",
    
    # ==========================================================================
    # CORE ENTITIES
    # ==========================================================================
    # Version
    "SCHEMA_VERSION",
    "CONTRACT_VERSION",
    "get_schema_version",
    "get_all_schemas",
    
    # Enums
    "BookingChannel",
    "PropertyType",
    "ListingStatus",
    "BookingStatus",
    "MessageDirection",
    "GuestType",
    
    # Base models
    "TenantScopedModel",
    "TimestampedModel",
    
    # Core entities
    "Tenant",
    "Operator",
    "Property",
    "Listing",
    "Booking",
    "GuestProfile",
    "MessageThread",
    "Message",
    "GeoPolygon",
    "MarketSnapshot",
    "AnalyticsResult",
    
    # ==========================================================================
    # CONTRACTS (API boundaries)
    # ==========================================================================
    "SignalContract",
    "SignalBundleContract",
    "GatingDecision",
    "GatingResult",
    "AttributionDriver",
    "MetricType",
    "PropertyProfile",
    "AmenityScore",
    "RentProjection",
    "MonthlyProjectionContract",
    "ComparableProperty",
    "OperatorProfile",
    "ExpansionReadiness",
    "GuestMessage",
    "KnowledgeFact",
    "ConciergeResponse",
    "DiscountDecision",
    "DiscountEvaluation",
    "BNPLEligibility",
    "InvestmentMetrics",
    "InvestmentScore",
    "NarrativeAudience",
    "NarrativeBlock",
    "APIResponse",
    "RentProjectionResponse",
    "AnalyticsResponse",
    "ConciergeResponseAPI",
    "DiscountResponse",
    "ExpansionResponse",
    "InvestmentResponse",
]
