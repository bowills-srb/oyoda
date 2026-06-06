# BD.py Migration Specification

## Status: BLOCKED (Awaiting Validation)

This document defines the migration plan for `bd.py` from `unified_intelligence` to the new orchestration layer.

**DO NOT EXECUTE** until validation criteria are met.

---

## Pre-Migration Validation Checklist

Before touching `bd.py`, ALL of these must be true:

- [ ] `projections.py` endpoint produces identical outputs to legacy
- [ ] `ProjectionWorker` produces identical outputs to API
- [ ] `PricingSensitivityWorker` runs without errors in production
- [ ] Domain purity guard passes in CI
- [ ] No performance regressions observed (< 10% latency increase)
- [ ] Error handling verified (bad inputs, missing data, timeouts)

---

## What `bd.py` IS

A **presentation assembler** that:
- Consumes intelligence
- Packages it for humans (sales, BD, pitch)
- Applies BD-specific framing
- Generates narratives, PDFs, decks

## What `bd.py` is NOT

- An intelligence producer
- A computation engine
- A domain layer component

---

## Section-by-Section Migration Guide

### A. Request Parsing & Validation

**Location:** Top of endpoint functions
**Action:** ✅ KEEP EXACTLY AS-IS

```python
# Example - DO NOT CHANGE
@router.post("/rent-projection")
async def generate_rent_projection(
    property_input: PropertyInput,
    commission_rate: float = Query(0.20, ...),
    include_sensitivity: bool = Query(True, ...),
):
```

**Rules:**
- ❌ Never move to domain
- ❌ Never move to orchestration
- This is API-layer concern

---

### B. Intelligence Fetch (THE ONLY CHANGE)

**Current:**
```python
from app.services.unified_intelligence import (
    get_intelligence_layer,
    UnifiedProjectionRequest,
)

intelligence = get_intelligence_layer()
unified_response = intelligence.generate_projection(
    request=request,
    market_census=market_census,
    internal_comps=internal_comps,
    operator_portfolio=operator_portfolio,
)
```

**After Migration:**
```python
from app.services.orchestration import (
    get_orchestrator,
    IntelligenceContext,
    IntelligenceType,
    PropertyPayload,
    MarketPayload,
)

orchestrator = get_orchestrator()
context = IntelligenceContext(
    request_id=str(uuid4()),
    tenant_id=tenant_id,
    intelligence_type=IntelligenceType.PROJECTION,
    geo_id=market_id,
)

result = orchestrator.run_full_intelligence(
    context=context,
    property_payload=property_payload,
    market_payload=market_payload,
)
```

**Rules:**
- 🟡 This is the ONLY part that changes
- ❌ `bd.py` must NEVER call domain directly
- ❌ `bd.py` must NEVER import from `app.domain`

---

### C. Post-Processing / Framing Logic

**Location:** After intelligence fetch
**Action:** ✅ KEEP EXACTLY AS-IS

```python
# Example - DO NOT CHANGE
# Highlighting upside
if proj["annual_gross_revenue"]["expected"] > 150000:
    highlight = "premium_opportunity"

# Selecting top drivers
top_drivers = sorted(drivers, key=lambda d: d["impact"])[:3]

# Framing conservative vs aggressive
if scenario == "conservative":
    use_projection = proj["annual_gross_revenue"]["low"]
```

**Rules:**
- ✅ This logic STAYS in `bd.py`
- ❌ Must NOT go to domain (this is persuasion, not computation)
- ❌ Must NOT go to orchestration

---

### D. Narrative Generation

**Location:** Narrative builder calls
**Action:** ✅ KEEP AS-IS

```python
# Example - DO NOT CHANGE
narrative = generate_bd_narrative(
    projection=result,
    market_context=market,
    framing="opportunity",
)
```

**Rules:**
- ✅ Stay in `bd.py` or BD-specific modules
- ❌ Intelligence must never know narrative exists
- Narrative CONSUMES intelligence, never the reverse

---

### E. PDF / Deck Assembly

**Location:** End of endpoint
**Action:** ✅ KEEP UNTOUCHED

```python
# Example - DO NOT CHANGE
if include_pdf:
    pdf = build_projection_pdf(result, narrative)
    return FileResponse(pdf)
```

**Rules:**
- ✅ STAYS as-is
- ❌ Do NOT refactor during orchestration migration
- ❌ Do NOT introduce domain imports here

---

## The Actual Diff (Should Be Boring)

When you migrate, the diff should be approximately:

```diff
- from app.services.unified_intelligence import (
-     get_intelligence_layer,
-     UnifiedProjectionRequest,
- )
+ from app.services.orchestration import (
+     get_orchestrator,
+     IntelligenceContext,
+     IntelligenceType,
+     PropertyPayload,
+     MarketPayload,
+ )

  # ... inside endpoint function ...

- intelligence = get_intelligence_layer()
- unified_response = intelligence.generate_projection(
-     request=request,
-     market_census=market_census,
-     ...
- )
+ orchestrator = get_orchestrator()
+ context = IntelligenceContext(...)
+ result = orchestrator.run_full_intelligence(
+     context=context,
+     property_payload=property_payload,
+     market_payload=market_payload,
+ )

  # Map result to existing variable names for minimal downstream changes
+ unified_response = result  # or adapt as needed
```

**If your diff is > 50 lines, you're doing too much.**

---

## BD Intelligence DTO (Future Enhancement)

After migration is stable, consider introducing:

```python
@dataclass
class BDIntelligenceSummary:
    """Stable interface for BD consumers."""
    
    # Projections (pre-computed scenarios)
    base_case: ProjectionSummary
    upside_case: ProjectionSummary
    downside_case: ProjectionSummary
    
    # Key insights (ranked for storytelling)
    key_drivers: List[RankedDriver]
    
    # Market context
    market_summary: MarketSummary
    
    # Confidence (for disclosure)
    confidence_tier: str
    confidence_score: float
    
    # Explainability (for trust)
    methodology_summary: str
    key_assumptions: List[str]
```

**Rules:**
- Lives in orchestration layer (not domain)
- Optimized for storytelling, not computation
- Stable across internal refactors
- `bd.py` should only touch this, never raw signals

---

## Migration Execution Steps

When validation is complete:

### Step 1: Create Branch
```bash
git checkout -b refactor/bd-orchestrator-migration
```

### Step 2: Replace Import
Change unified_intelligence → orchestrator import

### Step 3: Replace Call
Change the single intelligence fetch call

### Step 4: Adapt Output Mapping
Map orchestrator result to existing variable names

### Step 5: Run Tests
```bash
pytest tests/ -k bd
```

### Step 6: Manual Validation
- Generate a projection via API
- Compare output to pre-migration
- Check narrative quality
- Check PDF generation (if applicable)

### Step 7: Commit
```
git commit -m "refactor(bd): switch to orchestrator (no behavior change)"
```

### Step 8: Deprecate Legacy
```python
# In unified_intelligence.py
import warnings

def get_intelligence_layer():
    warnings.warn(
        "unified_intelligence is deprecated. Use orchestration layer.",
        DeprecationWarning,
        stacklevel=2
    )
    return UnifiedIntelligenceLayer()
```

---

## Red Flags (STOP if you see these)

🚫 "While I'm here, I'll clean up the narrative logic"
🚫 "This framing logic feels like it belongs in domain"
🚫 "Let's unify BD and projections response schemas"
🚫 "We should refactor the PDF builder now"
🚫 "I'll add a few improvements to the output"

**These are Phase 3+ thoughts. Not now.**

---

## Success Criteria

Migration is COMPLETE when:

- [ ] `bd.py` imports from `orchestration`, not `unified_intelligence`
- [ ] All BD endpoints produce identical outputs
- [ ] No domain imports in `bd.py`
- [ ] `unified_intelligence` marked deprecated
- [ ] CI passes
- [ ] Manual validation complete

---

## Post-Migration Cleanup (Later)

Only after ALL consumers migrated:

1. Remove `unified_intelligence` module
2. Consider BD DTO introduction
3. Consider splitting large `bd.py` into sub-modules (optional)

---

## Architecture After Migration

```
┌─────────────────────────────────────────────────────────┐
│                      bd.py                               │
│  (presentation, framing, narrative, PDF)                │
└────────────────────────┬────────────────────────────────┘
                         │ consumes
┌────────────────────────▼────────────────────────────────┐
│                  Orchestrator                            │
│         (IntelligenceRunner, SignalScheduler)           │
└────────────────────────┬────────────────────────────────┘
                         │ coordinates
┌────────────────────────▼────────────────────────────────┐
│                   Executors                              │
│    (PricingExecutor, ForecastingExecutor, etc.)         │
└────────────────────────┬────────────────────────────────┘
                         │ calls
┌────────────────────────▼────────────────────────────────┐
│                    Domain                                │
│        (Pure computation, no IO, guard enforced)        │
└─────────────────────────────────────────────────────────┘
```

**Key insight:** `bd.py` is a consumer, not a thinker.
