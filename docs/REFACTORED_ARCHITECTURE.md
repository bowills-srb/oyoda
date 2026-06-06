# RentalRevenue.ai - Refactored Architecture

## Overview

This document describes the refactored architecture that separates **computation** from **orchestration** and introduces a pure **domain layer** with thin **execution wrappers**.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                           API Layer                                  │
│                  (FastAPI endpoints, request/response)               │
│                                                                      │
│  • Validates input                                                   │
│  • Calls ONE orchestrator                                            │
│  • Returns response                                                  │
│  • Does NOT call multiple services or low-level engines              │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                       Orchestration Layer                            │
│              (IntelligenceRunner, SignalScheduler)                   │
│                                                                      │
│  COORDINATES:                                                        │
│  • When to run intelligence                                          │
│  • What signals to gather                                            │
│  • Which policies to apply                                           │
│  • Batch vs real-time execution                                      │
│                                                                      │
│  DOES NOT:                                                           │
│  • Compute signal math                                               │
│  • Access databases directly                                         │
│  • Make HTTP calls                                                   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                        Execution Layer                               │
│           (PricingExecutor, ForecastingExecutor, etc.)               │
│                                                                      │
│  THIN WRAPPERS that:                                                 │
│  • Translate DTOs/payloads → domain inputs                           │
│  • Call domain functions                                             │
│  • Return domain outputs                                             │
│                                                                      │
│  DOES NOT:                                                           │
│  • Make branching decisions                                          │
│  • Handle scheduling/retries                                         │
│  • Manage async concerns                                             │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                         Domain Layer                                 │
│     (signals, governance, pricing, forecasting, ownership,          │
│              opportunity, documents, bd)                             │
│                                                                      │
│  *** PURE - NO IO ***                                                │
│                                                                      │
│  • Signal models and computations (decay, weighting, bundling)       │
│  • Governance policies and decisions                                 │
│  • Pricing computations (amenity uplift, seasonality, discounts)     │
│  • Forecasting projections                                           │
│  • Ownership models (owner, property linkage, confidence)            │
│  • Opportunity models (usage scenarios, scoring, conversion)         │
│  • Document models (evidence extraction, property data)              │
│  • BD models (projection summaries, compliance, lead scoring)        │
│                                                                      │
│  RULES:                                                              │
│  • No FastAPI imports                                                │
│  • No DB sessions                                                    │
│  • No external API calls                                             │
│  • Pure inputs → outputs                                             │
│  • Purity enforced by assert_domain_purity()                         │
└─────────────────────────────────────────────────────────────────────┘
```

## Signal Lifecycle (Formal)

```
Raw Data
    │
    ▼
┌─────────────────┐
│   INGESTION     │  Scrapers, PMS connectors, federal data
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  NORMALIZATION  │  Canonical schema applied (VRBO/Airbnb → canonical)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    DETECTION    │  Detectors produce Signal objects
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   WEIGHTING     │  Decay + confidence → weighted value
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   APPLICATION   │  Used in projection/pricing/narrative
└─────────────────┘
```

Each stage is tracked via `SignalStage` enum:
- `RAW` - Just ingested
- `NORMALIZED` - Canonical schema applied
- `CONTRACTED` - Meets signal contract
- `WEIGHTED` - Decay/confidence applied
- `APPLIED` - Used in decision/output

## Domain Layer Structure

```
app/domain/
├── __init__.py
├── signals/
│   ├── __init__.py
│   ├── models.py         # Signal, SignalType, SignalScope, SignalSource
│   ├── computations.py   # Decay, weighting, SignalBundle
│   └── confidence.py     # Thresholds, gating, classification
├── governance/
│   ├── __init__.py
│   ├── policies.py       # PolicyRule, PolicyDecision, DecisionPolicy
│   └── presets.py        # PresetPolicies factory
├── pricing/
│   ├── __init__.py
│   └── computations.py   # Amenity uplift, seasonality, operator delta, discounts
├── forecasting/
│   ├── __init__.py
│   └── projections.py    # PropertyInputs, MarketInputs, generate_projection
└── market/               # (future)
    └── ...
```

## Orchestration Layer Structure

```
app/services/orchestration/
├── __init__.py
├── intelligence_runner.py   # IntelligenceOrchestrator
└── signal_scheduler.py      # SignalScheduler
```

## Execution Layer Structure

```
app/services/execution/
├── __init__.py
├── pricing_executor.py      # PricingExecutor - amenities, discounts
├── forecasting_executor.py  # ForecastingExecutor - projections
├── signal_executor.py       # SignalExecutor - signal operations
└── governance_executor.py   # GovernanceExecutor - policy evaluation
```

### Execution Service Pattern

```python
class PricingExecutor:
    def calculate_amenity_uplift(self, payload: AmenityUpliftPayload) -> AmenityUpliftResult:
        # Translate DTOs to domain inputs
        amenities = [AmenityType(a) for a in payload.amenities]
        
        # Call domain function
        combined, confidence, uplifts = compute_combined_amenity_uplift(amenities)
        
        # Return result
        return AmenityUpliftResult(combined_multiplier=combined, ...)
```

Execution services:
- No branching logic
- No scheduling logic
- No async concerns
- Just DTO translation + domain calls

### IntelligenceOrchestrator

Coordinates the full intelligence pipeline:
1. Assemble signals from provider
2. Run projection (delegates to domain)
3. Evaluate policy (delegates to domain)
4. Return gated result

```python
orchestrator = get_orchestrator()

result = orchestrator.run_full_intelligence(
    context=IntelligenceContext(...),
    property_inputs=PropertyInputs(...),
    market_inputs=MarketInputs(...),
    policy_name="high_confidence_pricing",
)

if result.is_gated:
    # Handle low confidence
    pass
else:
    projection = result.output
```

### SignalScheduler

Manages WHEN signals are collected:
- Tracks freshness per signal type + scope
- Schedules collection jobs
- Prioritizes by urgency

```python
scheduler = get_scheduler()

# Check if refresh needed
if scheduler.needs_refresh(SignalType.SEASONALITY_CURVE, tenant_id, geo_id):
    job = scheduler.schedule_collection(
        signal_types=[SignalType.SEASONALITY_CURVE],
        tenant_id=tenant_id,
        geo_id=geo_id,
        priority=JobPriority.HIGH,
    )
```

## Key Principles

### 1. Domain Layer is Pure

The domain layer has **zero dependencies** on:
- FastAPI
- SQLAlchemy / databases
- HTTP clients
- File system
- Environment variables

This means:
- Easy to test (just inputs → outputs)
- Easy to reason about
- Can run anywhere
- No hidden side effects

### 2. Orchestration Coordinates, Domain Computes

**Orchestration** answers: WHEN? HOW? IN WHAT ORDER?
**Domain** answers: WHAT IS THE VALUE? WHAT ARE THE RULES?

Example:
- Orchestration: "Gather signals, run projection, check policy"
- Domain: "Weighted average = Σ(value × confidence × decay) / Σ(confidence × decay)"

### 3. Single Responsibility at API Layer

Endpoints should:
```python
@router.post("/projections")
async def create_projection(request: ProjectionRequest):
    # 1. Validate input (Pydantic does this)
    
    # 2. Call ONE orchestrator
    result = orchestrator.run_projection(...)
    
    # 3. Return response
    return ProjectionResponse.from_result(result)
```

Endpoints should NOT:
- Call multiple services
- Access signal internals
- Implement business logic

### 4. Confidence Gating is First-Class

Every output is gated by confidence:

```python
OutputType.VOICE_PRICING_CLAIM      # Requires 0.75+
OutputType.BD_PROJECTION            # Requires 0.60+
OutputType.INTERNAL_ANALYSIS        # Requires 0.50+
```

The orchestrator automatically applies these gates.

### 5. Governance is Auditable

Every policy decision is recorded:

```python
{
    "policy_id": "...",
    "policy_name": "high_confidence_pricing",
    "action": "allow",
    "reason": "Confidence 0.82 meets threshold",
    "matched_rule": "high_confidence_allow",
    "decided_at": "2024-01-27T12:00:00Z"
}
```

## Migration Path

To migrate existing code:

1. **Identify pure computations** in `services/`
2. **Move them to `domain/`** without IO dependencies
3. **Create orchestrators** that coordinate the flow
4. **Update endpoints** to call orchestrators instead of services directly
5. **Update workers** to call domain functions (same as API)

This ensures:
- API and workers use the same logic
- No diverging code paths
- Easy testing at every layer

## Testing Strategy

### Domain Layer (Unit Tests)
```python
def test_weighted_average():
    signals = [Signal(...), Signal(...)]
    result = compute_weighted_average(signals)
    assert result == expected_value
```

### Orchestration Layer (Integration Tests)
```python
def test_full_projection_pipeline():
    orchestrator = IntelligenceOrchestrator(signal_provider=MockProvider())
    result = orchestrator.run_full_intelligence(...)
    assert result.success
    assert result.confidence > 0.5
```

### API Layer (E2E Tests)
```python
def test_projection_endpoint():
    response = client.post("/api/v1/projections", json={...})
    assert response.status_code == 200
    assert "projected_annual_revenue" in response.json()
```

## Summary

| Layer | Purpose | Dependencies | Tests |
|-------|---------|--------------|-------|
| API | HTTP handling | Orchestration | E2E |
| Orchestration | Coordination | Domain | Integration |
| Domain | Business logic | None (pure) | Unit |
| Execution | IO operations | External services | Integration |

This architecture:
- ✅ Reduces complexity creep
- ✅ Makes logic testable
- ✅ Enables swapping batch/real-time
- ✅ Provides audit trails
- ✅ Scales to enterprise requirements
