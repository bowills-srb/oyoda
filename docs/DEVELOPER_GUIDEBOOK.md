# RentalRevenue.ai - Developer Guidebook

> A comprehensive guide for developers working on the RentalRevenue.ai platform.
> This document extends ARCHITECTURE.md with implementation details, patterns, and best practices.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Core Concepts](#core-concepts)
3. [The Unified Intelligence Layer](#the-unified-intelligence-layer)
4. [Projection Engine Deep Dive](#projection-engine-deep-dive)
5. [PMS Integration Patterns](#pms-integration-patterns)
6. [Agent Framework](#agent-framework)
7. [Voice Translation Layer](#voice-translation-layer)
8. [Governance & Guardrails](#governance--guardrails)
9. [Market Intelligence](#market-intelligence)
10. [API Development Patterns](#api-development-patterns)
11. [Testing Strategies](#testing-strategies)
12. [Operational Considerations](#operational-considerations)

---

## Getting Started

### Prerequisites

Before diving into development, ensure you understand these foundational concepts:

1. **Multi-tenancy**: Every piece of data is scoped to a `company_id`. This is enforced at the database level via row-level security.

2. **Pure Functions**: The intelligence engines are designed as pure functions—input goes in, output comes out. No database or HTTP calls inside the engines themselves.

3. **Audit Everything**: Every decision that involves operator data or AI recommendations is logged with full reasoning for legal defensibility.

### Architecture Philosophy

The platform follows a clear separation of concerns:

```
Data Sources → Normalization → Intelligence Engines → Governance → Output (API/Voice/PDF)
```

Key principles:
- **Never compute in the voice layer** - The voice layer only consumes and translates
- **Conservative uplift application** - We apply 40-60% of observed performance deltas, never 100%
- **Transparency by default** - Every projection includes a reasoning object that explains the math

---

## Core Concepts

### The Two-Layer Comp System

The platform uses two layers of comparable properties for projections:

**Internal Comps (Operator's Portfolio)**
```python
InternalCompSet:
    comps: List[InternalComp]  # Operator's own properties
    avg_adr: float             # Average daily rate from operator's data
    avg_occupancy: float       # Occupancy from operator's actual bookings
    months_of_data: int        # How much history we have
    data_coverage_pct: float   # What % of days have data
```

**External Comps (Market Data)**
```python
ExternalCompSet:
    comps: List[ExternalComp]  # Properties from market sources (scraped, MLS)
    avg_adr: float             # Market average
    avg_occupancy: float       # Market occupancy
    data_source: str           # Where this came from
```

The weighting between internal and external comps is dynamic based on data quality:
- More internal data → higher internal weight (up to 70%)
- Less internal data → fallback to external (market-only projections)

### Operator Performance Delta

This is what makes RentalRevenue.ai different from "AirDNA-lite" tools:

```python
OperatorPerformanceDelta:
    adr_delta_pct: float           # +12% = operator gets 12% higher ADR than market
    occupancy_delta_pct: float     # +7% = operator has 7% better occupancy
    
    # CRITICAL: We never apply 100% of observed delta
    adr_delta_applied: float       # After tapering (40-60% of observed)
    occupancy_delta_applied: float
    
    confidence: float              # Based on data depth
    reason: str                    # Why we chose this application rate
```

**Why conservative application?**
- New properties may not perform exactly like existing portfolio
- Market conditions change
- Prevents overconfidence that could hurt owner relationships

### Canonical Data Model

All data from any source normalizes to our canonical schema:

```python
CanonicalListing:
    # Identity
    listing_id: UUID
    external_id: str       # Original PMS ID
    pms_provider: PMSProvider
    company_id: UUID
    
    # Location (critical for footprint)
    latitude: float
    longitude: float
    city: str
    state: str
    
    # Property attributes
    bedrooms: int
    bathrooms: float
    property_type: str
    
    # Amenities (normalized to boolean flags)
    has_pool: bool
    pool_heated: bool
    has_waterfront: bool
    pet_friendly: bool
    # ... etc
```

This allows the intelligence engines to work with consistent data regardless of whether it came from Guesty, Hostaway, Escapia, or a CSV upload.

---

## The Unified Intelligence Layer

The `UnifiedIntelligenceLayer` is the central integration point that wires everything together.

### Location
```
app/services/unified_intelligence.py
```

### Purpose

This layer ensures:
1. All projections go through governance checks
2. All voice output uses translated reasoning
3. All PDFs include methodology sections
4. All decisions are auditable

### Key Entry Points

**Generate a Projection**
```python
layer = get_intelligence_layer()

response = layer.generate_projection(
    request=UnifiedProjectionRequest(
        bedrooms=4,
        bathrooms=3.5,
        market_id="30a-beaches",
        waterfront=True,
        pool=True,
        company_id=operator_uuid,  # Enables operator-aware projections
    ),
    internal_comps=internal_comp_set,  # Optional: operator's own data
    external_comps=external_comp_set,  # Market comps
    platform_signals=platform_signals,  # Airbnb/VRBO/Booking signals
)

# Response includes:
# - projection: The actual numbers
# - voice_context: Pre-translated for voice agents
# - pdf_methodology: Ready for PDF generation
# - explanation: Transparent reasoning
# - audit_log_id: For compliance tracking
```

**Handle Voice Discount Request**
```python
response = layer.handle_voice_discount_request(
    request=VoiceDiscountRequest(
        property_id=property_uuid,
        check_in=date(2025, 7, 4),
        check_out=date(2025, 7, 11),
        current_total=2800.0,
        requested_discount_pct=0.15,  # 15% discount requested
    ),
    engine_reasoning=reasoning_from_discount_engine,
    internal_occupancy=0.72,
    booking_pace=BookingPace.AHEAD,
)

# Returns voice-safe response with denial/approval and scripted language
```

**PMS Onboarding**
```python
result = await layer.onboard_operator_pms(
    company_id=company_uuid,
    provider="guesty",
    credentials={"api_key": "...", "account_id": "..."}
)

# Automatically:
# 1. Creates connector
# 2. Tests connection
# 3. Fetches all listings and bookings
# 4. Builds geographical footprint
# 5. Returns summary
```

---

## Projection Engine Deep Dive

### Location
```
app/services/projections/rent_projection_engine_v1_1.py
```

### The Reasoning Object

Every projection includes a `ProjectionReasoning` object that explains exactly how the numbers were calculated:

```python
@dataclass
class ProjectionReasoning:
    # Engine metadata
    engine_version: str = "1.1.0"
    projection_id: str
    generated_at: datetime
    input_hash: str  # For reproducibility
    
    # Base ADR derivation
    base_adr: float
    base_adr_source: str  # "internal_comps", "external_comps", "blended"
    
    # Comp analysis
    internal_comp_analysis: Optional[CompAnalysis]
    external_comp_analysis: Optional[CompAnalysis]
    final_comp_weight_internal: float  # e.g., 0.6 = 60% internal
    
    # Operator delta
    operator_delta: Optional[OperatorPerformanceDelta]
    
    # All uplifts applied (ordered)
    uplifts_applied: List[AppliedUplift]
    
    # Confidence breakdown
    confidence_factors: Dict[str, float]
    overall_confidence: float
```

### Uplift Application

Uplifts are multiplicative, not additive:

```python
# Correct: multiplicative
final_adr = base_adr * pool_uplift * waterfront_uplift * operator_uplift

# Wrong: additive
final_adr = base_adr + pool_premium + waterfront_premium  # DON'T DO THIS
```

Each uplift is recorded with its reason:

```python
AppliedUplift(
    name="heated_pool",
    factor=1.08,  # +8%
    reason="Heated pool in shoulder season market - 8% premium based on 12 internal comps",
    confidence=0.75
)
```

### Seasonality Curves

Seasonality is market-specific and influences both ADR and occupancy:

```python
# Example: 30A Beach market seasonality
seasonal_multipliers = {
    "peak_summer": {"adr": 1.45, "occupancy": 0.92},     # June-August
    "spring_break": {"adr": 1.35, "occupancy": 0.88},    # March
    "shoulder": {"adr": 1.0, "occupancy": 0.65},         # April-May, Sept-Oct
    "off_peak": {"adr": 0.70, "occupancy": 0.45},        # Nov-Feb (except holidays)
    "holidays": {"adr": 1.55, "occupancy": 0.95},        # Thanksgiving, Christmas
}
```

---

## PMS Integration Patterns

### Location
```
app/services/connectors/pms_connectors.py
```

### Supported Providers

```python
class PMSProvider(str, Enum):
    GUESTY = "guesty"
    HOSTAWAY = "hostaway"
    ESCAPIA = "escapia"
    STREAMLINE = "streamline"
    LODGIFY = "lodgify"
    TRACK = "track"
    HOSTFULLY = "hostfully"
    OWNERREZ = "ownerrez"
    BEDS24 = "beds24"
    SMOOBU = "smoobu"
    MANUAL = "manual"  # CSV upload
```

### Connector Pattern

Each connector implements a common interface:

```python
class BasePMSConnector(ABC):
    @abstractmethod
    async def test_connection(self) -> bool:
        """Verify credentials work."""
        pass
    
    @abstractmethod
    async def fetch_listings(self) -> List[CanonicalListing]:
        """Get all listings, normalized to canonical schema."""
        pass
    
    @abstractmethod
    async def fetch_bookings(
        self, 
        start_date: date, 
        end_date: date
    ) -> List[CanonicalBooking]:
        """Get bookings in date range, normalized."""
        pass
    
    @abstractmethod
    async def fetch_calendar(
        self, 
        listing_id: str,
        start_date: date,
        end_date: date
    ) -> List[CanonicalCalendarDay]:
        """Get availability/pricing calendar."""
        pass
```

### Footprint Generation

When a PMS is connected, we automatically build the operator's geographical footprint:

```python
OperatorFootprint:
    company_id: UUID
    listings: List[CanonicalListing]
    
    # Computed boundaries
    bounding_box: BoundingBox
    convex_hull: GeoJSON
    
    # Geofences (with buffer)
    operational_geofences: List[Geofence]  # 5-mile buffer around listings
    expansion_geofences: List[Geofence]    # Areas they're watching
```

This footprint is used to:
1. Scope external market scraping
2. Define internal comp boundaries  
3. Enable geofence-specific analytics

---

## Agent Framework

### Location
```
app/services/agents/agent_framework.py
```

### Agent Types

```python
class AgentType(str, Enum):
    PRICING = "pricing"           # Rate calculations, discounts
    MARKET_INTEL = "market_intel" # Market analysis, comp finding
    LEAD_QUALIFIER = "lead_qualifier"  # Score prospects
    VOICE_ASSISTANT = "voice_assistant"  # Guest/owner inquiries
    REPORT_WRITER = "report_writer"      # Pro formas, analyses
    OPERATIONS = "operations"     # Scheduling, resources
    ORCHESTRATOR = "orchestrator" # Task routing
```

### Agent Context

Every agent receives a rich context object:

```python
@dataclass
class AgentContext:
    company_id: UUID
    user_id: Optional[UUID]
    
    # Property context
    property_id: Optional[UUID]
    property_data: Optional[Dict]
    property_knowledge_base: Optional[Dict]  # FAQs, amenities, policies
    
    # Market context
    market_id: Optional[UUID]
    market_data: Optional[Dict]
    
    # Conversation (for voice/chat)
    conversation_id: Optional[UUID]
    conversation_history: List[Dict]
    
    # Additional data
    additional_context: Dict
```

### Task Flow

```python
# Create a task
task = AgentTask(
    task_type="discount_evaluation",
    description="Guest requesting 15% discount for July 4th week",
    input_data={
        "property_id": "...",
        "check_in": "2025-07-04",
        "check_out": "2025-07-11",
        "requested_discount": 0.15
    },
    context=agent_context,
    priority=TaskPriority.HIGH
)

# Orchestrator routes to appropriate agent(s)
orchestrator = AgentOrchestrator()
response = await orchestrator.execute(task)

# Response includes decision + rationale
response.data["decision"]  # "deny"
response.rationale  # "July 4th week historically 95% booked..."
response.confidence  # 0.85
```

### Building Custom Agents

```python
class CustomAgent(BaseAgent):
    agent_type = AgentType.CUSTOM
    
    def get_capabilities(self) -> List[AgentCapability]:
        return [
            AgentCapability(
                name="analyze_something",
                description="Does something specific",
                input_schema={"type": "object", ...},
                output_schema={"type": "object", ...}
            )
        ]
    
    async def execute(self, task: AgentTask) -> AgentResponse:
        # Your logic here
        return AgentResponse(
            task_id=task.id,
            success=True,
            data={"result": "..."},
            confidence=0.8,
            rationale="Because..."
        )
```

---

## Voice Translation Layer

### Location
```
app/services/voice/voice_translation.py
```

### Core Principle

**The voice layer NEVER computes. It only translates engine output to natural language.**

```python
# WRONG: Computing in voice layer
def get_voice_response(property, dates):
    # DON'T DO THIS
    rate = calculate_rate(property, dates)  # ❌ Computing here
    return f"The rate is ${rate}"

# RIGHT: Translating engine output
def get_voice_response(engine_output: PricingContext):
    # Engine already did the math
    # We just translate to voice-safe language
    return voice_engine.translate(engine_output)
```

### Voice Policy Configuration

Voice guardrails are configuration, not code:

```python
@dataclass
class VoicePolicyConfig:
    # Confidence thresholds
    min_confidence_for_internal_reference: float = 0.6
    min_confidence_for_discount_denial: float = 0.7
    min_confidence_for_strong_claims: float = 0.8
    
    # What we can say
    allow_internal_comp_references: bool = True
    allow_performance_claims: bool = True
    allow_scarcity_statements: bool = True
    
    # What we NEVER say
    never_mention_exact_revenue: bool = True
    never_mention_exact_adr: bool = True
    never_guarantee_bookings: bool = True
    never_name_competitors: bool = True
    
    # Fallback behavior
    fallback_to_market_on_low_confidence: bool = True
    
    # Branding
    operator_name: str = "we"  # "Beach Habitats", "our team"
```

### Voice Context Object

The voice agent receives a simplified, pre-translated context:

```python
@dataclass
class VoicePricingContext:
    property_summary: str          # "4BR beachfront with pool"
    
    # Dates
    check_in: date
    check_out: date
    nights: int
    days_until_checkin: int
    
    # Current ask
    current_rate: float
    total_price: float
    
    # Posture (what the agent should project)
    pricing_posture: PricingPosture  # FIRM, FLEXIBLE, EAGER
    confidence_level: ConfidenceLevel
    
    # Pre-written statements (voice agent reads these)
    can_say_statements: List[str]
    cannot_say_statements: List[str]
    
    # Scripted responses for discount requests
    discount_denial_script: Optional[str]
    alternative_offer_script: Optional[str]
```

### Pricing Postures

The pricing posture tells the voice agent how to negotiate:

```python
class PricingPosture(str, Enum):
    FIRM = "firm"        # High demand period, don't discount
    FLEXIBLE = "flexible" # Can negotiate within limits
    EAGER = "eager"      # Want to fill, will offer discounts proactively
```

---

## Governance & Guardrails

### Location
```
app/services/governance/risk_mitigation.py
app/services/guardrails/phase_guardrails.py
```

### The Three Operational Risks

1. **Overconfidence Drift**: System becomes too confident over time
2. **Black Box Accusations**: Operators don't understand how decisions are made  
3. **Voice Tone Misalignment**: Voice agent doesn't match operator's brand

### Hard Caps (Non-Negotiable)

These cannot be changed without code review:

```python
class ConfidenceGovernance:
    # Maximum operator uplift application
    MAX_OPERATOR_UPLIFT_APPLICATION_RATE: float = 0.60  # 60% max
    
    # Minimum data for internal comps
    MIN_MONTHS_FOR_INTERNAL_COMPS: int = 6
    MIN_PROPERTIES_FOR_INTERNAL_COMPS: int = 3
    MIN_DATA_COVERAGE_PCT: float = 0.50
    
    # Maximum confidence (never claim 100%)
    MAX_CONFIDENCE_SCORE: float = 0.95
    
    # Voice claim thresholds
    MIN_CONFIDENCE_FOR_INTERNAL_VOICE_CLAIMS: float = 0.60
    MIN_CONFIDENCE_FOR_DISCOUNT_DENIAL: float = 0.65
    MIN_CONFIDENCE_FOR_STRONG_ASSERTIONS: float = 0.75
```

### Audit Logging

Every confidence-related decision is logged:

```python
@dataclass
class ConfidenceAuditLog:
    log_id: str
    timestamp: datetime
    
    company_id: Optional[UUID]
    property_id: Optional[UUID]
    
    action_type: str  # "projection", "discount_evaluation", etc.
    
    # What was computed
    raw_confidence: float
    capped_confidence: float  # After governance caps
    
    # What checks passed/failed
    governance_checks_passed: List[str]
    governance_checks_failed: List[str]
    
    # Full reasoning (for audit)
    reasoning_snapshot: Dict
```

### Transparency Engine

Generates human-readable explanations:

```python
explanation = transparency_engine.generate_explanation(
    projection=projection,
    reasoning=reasoning_object,
    audience="owner"  # or "bd_rep", "internal"
)

# Returns structured explanation:
# {
#     "summary": "We project $125,000-145,000 annual gross revenue...",
#     "methodology": "Based on 8 comparable properties in your market...",
#     "key_factors": ["Private beach access (+22%)", "Heated pool (+8%)"],
#     "confidence_explanation": "High confidence (82%) based on...",
#     "data_sources": ["Internal portfolio (24 months)", "Market data (AirDNA)"]
# }
```

---

## Market Intelligence

### Components

```
app/services/market_intelligence/
├── market_intelligence_engine.py  # Market health, amenity scoring
├── expansion_intelligence.py      # OSS, APS, expansion projections
└── platform_weighting.py          # Data-driven Airbnb/VRBO weights
```

### Market Health Index

```python
MarketHealthIndex:
    score: float  # 0-100
    
    components:
        supply_demand_balance: float
        adr_trend: float  # YoY change
        occupancy_trend: float
        seasonality_strength: float
        competition_intensity: float
    
    signals:
        new_listings_30d: int
        price_changes_30d: int
        booking_velocity: float
```

### Platform Weighting

Different markets have different platform preferences:

```python
# Beach market: VRBO dominates
beach_weights = {"airbnb": 0.35, "vrbo": 0.55, "booking": 0.10}

# Urban market: Airbnb dominates
urban_weights = {"airbnb": 0.60, "vrbo": 0.25, "booking": 0.15}

# The platform weighting engine computes this automatically
# based on actual booking data in the geofence
weights = engine.compute_platform_weights(geofence_id, platform_signals)
```

### Expansion Intelligence (OSS & APS)

**OSS (Operator Similarity Score)**: How similar is a target market to where the operator currently operates?

```python
oss = oss_calculator.calculate(
    operator=operator_profile,
    source_market=current_market,
    target_market=expansion_market
)

# Returns:
# {
#     "score": 0.72,
#     "factors": {
#         "property_type_match": 0.85,
#         "seasonality_correlation": 0.68,
#         "guest_demographic_overlap": 0.70,
#         "operational_similarity": 0.65
#     },
#     "recommendation": "Partial transfer of operator delta appropriate"
# }
```

**APS (Amenity Point Score)**: How valuable is a specific amenity in a market?

```python
aps = aps_calculator.calculate(
    amenity="heated_pool",
    market_id="30a-beaches",
    saturation_rate=0.25,  # 25% of listings have it
    market_health_score=72.0,
    operator_performance_delta=0.12  # Operator is +12% vs market
)

# Returns value of amenity in ADR uplift potential
```

---

## API Development Patterns

### Location
```
app/api/v1/endpoints/
├── bd.py          # Business development (projections, leads)
├── properties.py  # Property CRUD
├── market.py      # Market data
├── pricing.py     # Pricing and discounts
└── normalize.py   # Data normalization
```

### Standard Response Pattern

```python
class RentProjectionResponse(BaseModel):
    # Identification
    projection_id: UUID
    generated_at: datetime
    
    # Core data
    total_projected_gross_revenue: float
    gross_revenue_range: Dict[str, float]  # {low, mid, high}
    
    # Breakdown
    seasonal_projections: List[SeasonalProjection]
    comparables: List[ComparableProperty]
    
    # Confidence & methodology
    confidence_score: float
    methodology_summary: str
    
    # Audit trail
    reasoning_id: str  # Links to full reasoning object
```

### Dependency Injection

```python
from fastapi import Depends
from app.services.unified_intelligence import get_intelligence_layer

@router.post("/projections")
async def create_projection(
    request: ProjectionRequest,
    intelligence: UnifiedIntelligenceLayer = Depends(get_intelligence_layer),
    company: Company = Depends(get_current_company),
):
    return await intelligence.generate_projection(
        request=request,
        company_id=company.id
    )
```

### Background Tasks for Heavy Operations

```python
@router.post("/projections/batch")
async def create_batch_projections(
    properties: List[PropertyInput],
    background_tasks: BackgroundTasks,
):
    job_id = uuid4()
    
    background_tasks.add_task(
        process_batch_projections,
        job_id=job_id,
        properties=properties
    )
    
    return {"job_id": job_id, "status": "queued"}
```

---

## Testing Strategies

### Unit Testing Engines

Since engines are pure functions, they're easy to test:

```python
def test_projection_with_internal_comps():
    engine = RentProjectionEngineV1_1()
    
    result = engine.generate_projection(
        property_inputs=PropertyInputs(bedrooms=4, ...),
        market_inputs=MarketInputs(market_id="30a", ...),
        internal_comps=InternalCompSet(comps=[...], ...),
        external_comps=ExternalCompSet(comps=[...], ...)
    )
    
    # Verify reasoning is populated
    assert result.reasoning.internal_comp_analysis is not None
    assert result.reasoning.operator_delta is not None
    
    # Verify uplift application
    assert len(result.reasoning.uplifts_applied) > 0
    
    # Verify confidence calculation
    assert 0 < result.reasoning.overall_confidence <= 0.95
```

### Integration Testing

```python
@pytest.mark.asyncio
async def test_pms_onboarding_flow():
    layer = get_intelligence_layer()
    
    result = await layer.onboard_operator_pms(
        company_id=test_company_id,
        provider="guesty",
        credentials=MOCK_CREDENTIALS
    )
    
    assert result["success"]
    assert "listings_synced" in result
    assert "footprint" in result
```

### Governance Testing

```python
def test_confidence_hard_caps():
    """Ensure governance caps are enforced."""
    # Try to exceed max confidence
    raw_confidence = 0.99
    capped = ConfidenceGovernance.validate_confidence(raw_confidence)
    assert capped == 0.95  # Hard cap
    
def test_insufficient_data_blocks_internal_comps():
    """Can't use internal comps without enough data."""
    can_use, reason = ConfidenceGovernance.can_use_internal_comps(
        months_of_data=3,  # Below minimum of 6
        property_count=5,
        data_coverage_pct=0.8
    )
    assert not can_use
    assert "Insufficient data history" in reason
```

---

## Operational Considerations

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql://...
REDIS_URL=redis://...

# External Services
OPENAI_API_KEY=...
TWILIO_ACCOUNT_SID=...
ELEVENLABS_API_KEY=...

# Feature Flags
ENABLE_INTERNAL_COMPS=true
ENABLE_VOICE_DISCOUNT_DENIAL=true
MAX_OPERATOR_UPLIFT=0.55  # Override default if needed

# Governance
AUDIT_LOG_RETENTION_DAYS=2555  # 7 years for compliance
```

### Monitoring Priorities

1. **Confidence Distribution**: Alert if average confidence drifts too high
2. **Projection Accuracy**: Compare projections to actuals (where available)
3. **Voice Denial Rate**: Track discount denial rate per operator
4. **PMS Sync Health**: Monitor connector failures
5. **Audit Log Volume**: Ensure all decisions are logged

### Data Retention

| Data Type | Retention | Reason |
|-----------|-----------|--------|
| Projections | 7 years | Legal defensibility |
| Audit logs | 7 years | Compliance |
| Voice transcripts | 2 years | Service improvement |
| Raw PMS data | 3 years | Historical analysis |
| Market snapshots | 5 years | Trend analysis |

---

## Appendix: Quick Reference

### Import Cheat Sheet

```python
# Unified layer
from app.services.unified_intelligence import (
    get_intelligence_layer,
    UnifiedProjectionRequest,
    UnifiedProjectionResponse,
)

# Projection engine
from app.services.projections.rent_projection_engine_v1_1 import (
    RentProjectionEngineV1_1,
    PropertyInputs,
    MarketInputs,
    InternalCompSet,
    ExternalCompSet,
    ProjectionReasoning,
)

# Voice
from app.services.voice.voice_translation import (
    VoiceTranslationEngine,
    VoicePolicyConfig,
    VoicePricingContext,
)

# Governance
from app.services.governance.risk_mitigation import (
    ConfidenceGovernance,
    ConfidenceAuditLog,
    TransparencyEngine,
)

# PMS
from app.services.connectors.pms_connectors import (
    PMSConnectorFactory,
    PMSProvider,
    CanonicalListing,
    CanonicalBooking,
)

# Agents
from app.services.agents.agent_framework import (
    AgentType,
    AgentTask,
    AgentContext,
    AgentOrchestrator,
)
```

### Common Patterns

```python
# 1. Generate projection with full context
layer = get_intelligence_layer()
response = layer.generate_projection(request, internal_comps, external_comps)

# 2. Check governance before voice claim
can_claim, reason = ConfidenceGovernance.can_make_voice_claim(
    "discount_denial", response.final_confidence
)

# 3. Get voice-safe output
voice_context = response.voice_context

# 4. Log everything
audit_log_id = response.audit_log_id
```

---

*This guidebook is a living document. Update it as the platform evolves.*
