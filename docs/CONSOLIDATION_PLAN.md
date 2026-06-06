# Signal Intelligence System - Consolidation & Wiring Plan

## Current State Analysis

### Identified Duplications

| Component | File 1 (OLD) | File 2 (NEW) | Action |
|-----------|--------------|--------------|--------|
| Signal Types Enum | `schemas/signals.py` | `schemas/canonical_signals.py` | **Consolidate → canonical** |
| Signal Model | `app/services/signals/signal_contract.py` | `schemas/canonical_signals.py` | **Consolidate → canonical** |
| SignalBundle | `signal_contract.py` | `canonical_signals.py` | **Consolidate → canonical** |
| OTA Scraper | `app/services/scrapers/public_data_scraper.py` | `tools/signal_scraper.py` | **Keep tools/ as standalone** |
| Data Ingestion | `app/services/scrapers/data_ingestion.py` | - | **Keep, wire to pipeline** |

### Files to Keep (Canonical)

```
schemas/
├── __init__.py          # Re-export canonical
├── canonical_signals.py # ✅ SINGLE SOURCE OF TRUTH
├── contracts.py         # API contracts (keep)
└── core.py              # Core types (keep)

app/services/signals/
├── __init__.py          # Re-export from canonical
├── signal_pipeline.py   # ✅ Production pipeline
├── scheduler.py         # ✅ Job orchestration
├── coverage_score.py    # ✅ BD slide calculator
├── attribution.py       # ✅ PDF footnotes
├── seasonality.py       # Keep - specialized logic
├── platform.py          # Keep - specialized logic
├── amenity.py           # Keep - specialized logic
├── operator.py          # Keep - specialized logic
└── signal_contract.py   # DEPRECATE → use canonical

tools/
├── signal_scraper.py      # ✅ Standalone scraper (run on Mac)
├── federal_data_scraper.py # ✅ Standalone federal data
├── signal_converter.py    # ✅ Raw → Canonical conversion
└── SCRAPER_QUICKSTART.md  # ✅ Deployment guide
```

### Files to Deprecate

```
schemas/signals.py              # → Use canonical_signals.py
app/services/signals/signal_contract.py  # → Merge useful parts into canonical
app/services/scrapers/public_data_scraper.py  # → Use tools/signal_scraper.py
```

---

## Consolidation Steps

### Step 1: Update schemas/__init__.py

Re-export everything from canonical_signals.py as the single source of truth.

### Step 2: Update app/services/signals/__init__.py

Import from canonical schemas, keep specialized logic (seasonality, amenity, etc.)

### Step 3: Wire signal_pipeline.py to existing services

Connect the new pipeline to existing BD services, analytics, etc.

### Step 4: Update BD services to use new synopsis

Wire signal_synopsis.py into existing BD endpoints.

### Step 5: Add migration path for old code

Provide backward compatibility aliases during transition.

---

## Wiring Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CANONICAL SCHEMAS                                  │
│                    schemas/canonical_signals.py                              │
│                         (Single Source of Truth)                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
         ┌──────────────────────────┼──────────────────────────┐
         │                          │                          │
         ▼                          ▼                          ▼
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│  DATA COLLECTION │      │  SIGNAL PIPELINE │      │   CONSUMERS     │
├─────────────────┤      ├─────────────────┤      ├─────────────────┤
│ tools/          │      │ app/services/   │      │ app/services/bd │
│  signal_scraper │─────►│  signals/       │─────►│  signal_synopsis│
│  federal_data   │      │   pipeline.py   │      │  proforma_*     │
│  signal_convert │      │   scheduler.py  │      │  pitch_deck     │
└─────────────────┘      └─────────────────┘      └─────────────────┘
                                    │
                                    ▼
                         ┌─────────────────┐
                         │    DATABASE     │
                         │  (PostgreSQL)   │
                         │  alembic/       │
                         │   migrations    │
                         └─────────────────┘
```

---

## Implementation Below
