# Duplication Analysis: Legacy Services vs Signal Architecture

## Executive Summary

The new signal-based architecture duplicates significant logic that exists in the legacy services.
This document identifies the overlaps and provides a migration strategy.

---

## 🔴 HIGH PRIORITY - Direct Duplication

### 1. Platform Dominance / Platform Weighting

**Legacy Location:** `app/services/market_intelligence/platform_weighting.py`
- `PlatformWeightingEngine` class (lines 246-400)
- `PlatformHealthScore` calculation
- `compute_platform_weights()` method
- EWMA-based time decay
- Market class baseline weights

**New Location:** `workers/detectors/detector_workers.py`
- `PlatformDominanceDetector` class
- Produces `SignalType.PLATFORM_DOMINANCE` signal

**Duplication Issues:**
- Both compute Airbnb vs VRBO share
- Both have platform weight dictionaries
- Both have confidence calculations
- Different decay implementations (EWMA vs exponential)

**Resolution:**
```
KEEP: PlatformDominanceDetector (produces signals)
REFACTOR: PlatformWeightingEngine → consume signals from store
DEPRECATE: Direct platform weight calculations in engine
```

---

### 2. Seasonality Curve Detection

**Legacy Locations:**
- `app/services/market_intelligence/platform_weighting.py` → `SeasonalityDetector` class (lines 480-612)
- `app/services/projections/rent_projection_engine_v1_1.py` → `DEFAULT_SEASONALITY` dict (lines 464-477)
- `app/services/market_intelligence/market_intelligence_engine.py` → seasonality in crawl schema

**New Location:** `workers/detectors/detector_workers.py`
- `SeasonalityCurveDetector` class
- Produces `SignalType.SEASONALITY_CURVE` signal

**Duplication Issues:**
- Three different seasonality implementations
- Different monthly factor structures
- Different confidence calculations
- Projection engine has hardcoded seasonality fallback

**Resolution:**
```
KEEP: SeasonalityCurveDetector (produces signals)
REFACTOR: Projection engine → consume SEASONALITY_CURVE signals
REFACTOR: Platform weighting → consume signals, not compute
DEPRECATE: DEFAULT_SEASONALITY hardcoded values (use signal defaults)
```

---

### 3. Amenity Lift / Uplift Calculations

**Legacy Locations:**
- `app/services/projections/rent_projection_engine_v1_1.py` → `AmenityUpliftConfig` class + `_apply_amenity_uplifts()` (lines 399-442, 799-900)
- `app/services/market_intelligence/market_intelligence_engine.py` → amenity saturation signals

**New Location:** `workers/detectors/detector_workers.py`
- `AmenityLiftDetector` class
- Produces `SignalType.AMENITY_LIFT` signals per amenity

**Duplication Issues:**
- Projection engine has hardcoded uplift values (pool: 1.10, etc.)
- Detector should provide data-driven lifts per geo
- Currently both exist independently

**Resolution:**
```
KEEP: AmenityLiftDetector (produces geo-specific signals)
REFACTOR: Projection engine → consume AMENITY_LIFT signals
MIGRATE: Hardcoded values → default signal values or fallback only
```

---

### 4. Operator Performance Delta

**Legacy Location:** `app/services/projections/rent_projection_engine_v1_1.py`
- `OperatorPerformanceDelta` class (lines 72-92)
- `_apply_operator_delta()` method (lines 728-797)
- Conservative application rate logic

**New Location:** `workers/detectors/detector_workers.py`
- `OperatorDeltaDetector` class
- Produces `SignalType.OPERATOR_DELTA` signal

**Duplication Issues:**
- Both calculate portfolio vs market delta
- Both have conservative application logic
- Detector stores as signal, engine calculates inline

**Resolution:**
```
KEEP: OperatorDeltaDetector (runs periodically, stores signals)
REFACTOR: Projection engine → consume OPERATOR_DELTA signals
BENEFIT: Operator deltas become reusable across all analytics
```

---

### 5. Time Decay / Signal Freshness

**Legacy Locations:**
- `app/services/market_intelligence/platform_weighting.py` → `EWMACalculator` class (lines 136-190)
- `app/services/market_intelligence/market_intelligence_engine.py` → `SIGNAL_HALF_LIFE` config (lines 69-76)

**New Location:** `app/services/weighting/signal_weighting.py`
- `TimeDecayCalculator` class
- `DecayConfig` with profile-based relevance

**Duplication Issues:**
- EWMA approach vs exponential decay
- Different half-life configurations
- Not unified

**Resolution:**
```
KEEP: TimeDecayCalculator in weighting module (signal-based)
DEPRECATE: EWMACalculator (or merge as an alternative decay mode)
UNIFY: Signal half-life config should drive both
```

---

## 🟡 MEDIUM PRIORITY - Conceptual Overlap

### 6. Market Health Index

**Legacy:** `app/services/market_intelligence/market_intelligence_engine.py`
- Complex MHI calculation from crawled data

**New:** `app/services/analytics_engine.py`
- `ArtifactType.MARKET_HEALTH` (placeholder)

**Action:** Market health should be computed from signals in analytics engine.

---

### 7. Occupancy Momentum

**Legacy:** Embedded in various places (projections, market intelligence)

**New:** `OccupancyMomentumDetector` produces `SignalType.OCCUPANCY_MOMENTUM`

**Action:** All momentum calculations should consume this signal.

---

### 8. Price Elasticity

**Legacy:** `app/services/pricing/discount_engine.py` has elasticity concepts

**New:** `PriceElasticityDetector` produces `SignalType.PRICE_ELASTICITY`

**Action:** Discount engine should consume elasticity signals.

---

## 🟢 LOW PRIORITY - No Immediate Action Needed

### 9. Guest Intent Analysis

**Legacy:** `app/services/messaging/guest_messaging.py` - intent extraction inline

**New:** `GuestIntentFrequencyDetector` produces signals

**Action:** Can coexist - detector aggregates for analytics, messaging handles real-time.

---

## Migration Strategy

### Phase 1: Signal Production (Current State ✅)
- Detectors exist and can produce signals
- Signal store schema defined
- Analytics engine consumes signals

### Phase 2: Signal Consumption (NEXT)
1. **Projection Engine Refactor**
   - Accept `SignalBundle` as input
   - Remove `AmenityUpliftConfig` hardcoded values
   - Consume `AMENITY_LIFT`, `SEASONALITY_CURVE`, `OPERATOR_DELTA` signals
   - Keep fallback logic for missing signals

2. **Platform Weighting Refactor**
   - Consume `PLATFORM_DOMINANCE` signals
   - Remove inline platform weight calculations
   - Keep aggregation logic

3. **Discount Engine Refactor**
   - Consume `PRICE_ELASTICITY`, `OCCUPANCY_MOMENTUM` signals
   - Remove inline elasticity calculations

### Phase 3: Deprecation
1. Mark legacy calculation methods as `@deprecated`
2. Add logging when fallbacks are used
3. Monitor signal coverage
4. Remove deprecated code after 90 days

---

## Recommended File Changes

### Files to Refactor:
```
app/services/projections/rent_projection_engine_v1_1.py
  → Add SignalBundle parameter to generate_projection()
  → Refactor _apply_amenity_uplifts() to use signals
  → Refactor seasonality to use signals

app/services/market_intelligence/platform_weighting.py
  → Refactor to be a signal CONSUMER, not producer
  → Keep aggregation logic, remove detection logic

app/services/pricing/discount_engine.py
  → Consume PRICE_ELASTICITY signals
```

### Files to Keep As-Is:
```
app/services/governance/risk_mitigation.py
  → Already designed to work with confidence scores

app/services/voice/voice_translation.py
  → Consumes outputs, doesn't duplicate detection

app/services/agents/agent_framework.py
  → Framework level, no detection duplication
```

### Files to Eventually Deprecate:
```
app/services/market_intelligence/market_intelligence_engine.py
  → SignalType enum duplicates schemas/signals.py
  → Crawl logic stays, detection moves to detectors

Parts of:
  app/services/market_intelligence/platform_weighting.py
  → SeasonalityDetector (replaced by detector)
  → PlatformHealthScore inline calculation
```

---

## Transition Architecture

```
BEFORE (Current State):
┌─────────────────────────────────────────────┐
│ Raw Data                                    │
└─────────────────────────────────────────────┘
           │                    │
           ▼                    ▼
┌──────────────────┐   ┌──────────────────────┐
│ Market Intel     │   │ Projection Engine    │
│ (computes inline)│   │ (computes inline)    │
└──────────────────┘   └──────────────────────┘
           │                    │
           ▼                    ▼
┌─────────────────────────────────────────────┐
│ BD / Voice / Dashboard                      │
└─────────────────────────────────────────────┘


AFTER (Target State):
┌─────────────────────────────────────────────┐
│ Raw Data                                    │
└─────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│ DETECTORS (parallel, idempotent)            │
│ - PlatformDominance                         │
│ - AmenityLift                               │
│ - SeasonalityCurve                          │
│ - OccupancyMomentum                         │
│ - OperatorDelta                             │
└─────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│ SIGNAL STORE (TimescaleDB)                  │
│ - Confidence-weighted                       │
│ - Time-decayed                              │
│ - Geo-scoped                                │
└─────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│ ANALYTICS ENGINE (pure synthesis)           │
│ - Consumes signals only                     │
│ - Confidence-gated outputs                  │
└─────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│ BD / Voice / Dashboard                      │
└─────────────────────────────────────────────┘
```

---

## Action Items

1. **Immediate:** Review this analysis with team
2. **This Sprint:** Refactor projection engine to accept signals
3. **Next Sprint:** Refactor platform weighting to consume signals
4. **Following Sprint:** Deprecate inline calculations
5. **Ongoing:** Monitor signal coverage and fallback usage
