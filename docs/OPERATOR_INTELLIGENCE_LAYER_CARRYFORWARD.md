# Operator Intelligence Layer Carryforward Brief

**Source session:** Conversation establishing the messaging tier map; subsequent discussion of supply/demand signals, PMS booking + pricing feeds, cross-operator aggregation, and operator BD intelligence.
**Workstream label:** C — Operator Intelligence Layer (future strategic architecture)
**Estimated scope:** Multi-session. This brief is the architectural seed, not the implementation plan.
**Status going in:** Aspirational. Nothing in this layer is built yet. The existing predecessor docs reference some of these concepts in a different (RentalRevenue.ai) product framing; this brief reframes them as Oyvoda architecture.

---

## Why this layer needs to exist

Beach Habitats today gets value from the messaging brain: guests are answered, the brain learns from operator approvals, the healer loop improves deterministic routing over time. That's one source of value.

The second source of value, not yet realized, is the *operator intelligence* layer. As more operators sign up, Oyvoda accumulates data that no individual operator has visibility into:

- Cross-operator booking patterns (which property types fill at what lead times)
- Aggregate event impact on demand (this music festival drove 18% surge; that one had no effect)
- Pricing power signals (which amenities justified premium pricing; which didn't)
- Portfolio composition outcomes (operators who diversified into condos vs single-family; outcomes)
- Conversation patterns (which guest questions correlate with bookings; which correlate with churn)

This isn't a "nice to have." It's the second pillar of the platform's value proposition. The brain answers messages; the intelligence layer answers questions like *"should I buy this property?"*, *"should I add a hot tub?"*, *"is my pricing strategy working?"*.

Some of this exists in predecessor (RentalRevenue.ai) docs at a high level. Those concepts get extracted and reframed under Oyvoda branding during Workstream D (docs cleanup). This brief is the architectural target they extract toward.

---

## Where this layer lives

```
app/services/intelligence/                ← NEW package
├── __init__.py                            ← package docstring, tier framing
├── signals/                               ← ingest + canonicalize supply/demand signals
│   ├── booking_signals.py                 ← from PMS booking feed
│   ├── pricing_signals.py                 ← from PMS daily pricing feed
│   ├── event_signals.py                   ← from event feed (Tier 1 integration)
│   ├── conversation_signals.py            ← derived from messaging brain audit data
│   └── canonical_signal.py                ← shared signal contract
├── aggregation/                           ← cross-property and cross-operator rollups
│   ├── per_property.py                    ← single-property views
│   ├── per_portfolio_group.py             ← group-level views
│   ├── per_tenant.py                      ← operator-level views
│   └── cross_tenant.py                    ← platform-wide views (privacy-preserving)
├── analytics/                             ← derived metrics, decisions
│   ├── pricing_recommendations.py
│   ├── amenity_value.py
│   ├── demand_forecasting.py
│   ├── portfolio_recommendations.py
│   └── coverage_quality.py                ← measures messaging brain's effectiveness per operator
├── delivery/                              ← surfaces (API, dashboard, notifications)
│   ├── operator_insights_api.py
│   ├── periodic_reports.py
│   └── proactive_alerts.py
└── tests/
```

**Tier classification:** The intelligence layer is its own concern, distinct from the four-tier messaging model. It reads from the messaging tiers but operates on a different timescale (batch / scheduled / on-demand analytics, not per-message decisions).

It most resembles `app/services/agents/` in role: cross-cutting workers that read signals from all tiers and produce derived value. The difference is purpose:
- `agents/` (healers, sync, curator) — improves the *operational system*
- `intelligence/` — produces *decision-support output* for operators and the platform

Both are legitimately cross-cutting. They share the dependency rule (may read from any tier) but live in separate packages because their consumers are different (operational system vs operator dashboards / BD).

---

## Data flow

```
PMS booking feed         ┐
PMS daily pricing feed   ├─→ integrations/pms/  (Tier 1)
Event feed (calendars,   ┘                       ↓
  scrapers, manual)                     canonical event/booking/pricing records
                                                ↓
                                  intelligence/signals/  (this layer)
                                                ↓
                              normalized SupplyDemandSignal records
                                                ↓
                            intelligence/aggregation/  ← scoped rollups
                                                ↓
                            intelligence/analytics/    ← derived metrics
                                                ↓
                            intelligence/delivery/     ← operator surfaces
                                                ↓
                                  v2 frontend dashboard
                                  periodic email/SMS reports
                                  proactive alerts ("rates trending up in your market")
```

A parallel input stream comes from the messaging brain:

```
messaging_brain/ audit data
  ├─→ message_normalizations (per-message brain decisions)
  ├─→ pre_booking_inquiries (operator review patterns)
  ├─→ kb_gaps (knowledge coverage)
  └─→ healer_proposals (deterministic layer learning)
                  ↓
       intelligence/signals/conversation_signals.py
                  ↓
       (joins with supply/demand signals)
```

The intelligence layer reads brain audit data but doesn't change it. The brain is the source of truth for messaging decisions; the intelligence layer is a downstream consumer for analytics.

---

## Key concepts the predecessor docs reference (extract candidates)

When Workstream D moves the RentalRevenue.ai docs to legacy, these concepts may have reusable framing:

- **Signal types and detectors** (`docs/ARCHITECTURE.md` references "Detector Engine" with new listing, price change, occupancy shift, booking pattern, market anomaly). The detector pattern is reusable; the specific implementations may not be.
- **Pricing intelligence patterns** (`docs/REFACTORED_ARCHITECTURE.md` references `PricingExecutor`, projection engine). The separation of pricing computation from orchestration is a sound principle; the specific class structure isn't.
- **Multi-tenant analytics with row-level isolation** (`docs/DEVELOPER_GUIDEBOOK.md` references RLS). Oyvoda already does this; the framing might be useful for cross-tenant aggregation specifically.
- **EWMA-based time decay for signal aging** (`docs/DUPLICATION_ANALYSIS.md`). The aggregation layer needs decay semantics; this is reusable.

**Extraction discipline:** Don't blindly port concepts. The predecessor product had different consumer assumptions (PMS companies buying analytics). Oyvoda's consumer is the STR operator using the platform daily. Some concepts translate; some don't. During extraction, every brought-forward concept gets reframed for Oyvoda's actual product shape.

---

## Phased execution (this is a roadmap, not a single session)

### Phase 1 — Signal contract + booking/pricing ingestion (1 session)

Establish the canonical `SupplyDemandSignal` shape. Build `intelligence/signals/booking_signals.py` and `intelligence/signals/pricing_signals.py` to ingest from the existing PMS integration (Escapia today). The signals start writing to `supply_demand_signals` table; nothing downstream consumes them yet.

This is the cheap first step. It creates data that the rest of the layer needs without committing to analytics output.

### Phase 2 — Event signal source + first aggregation (1 session)

Build `intelligence/signals/event_signals.py` consuming from the existing event scraper (30A events, Visit South Walton, etc.). Build `intelligence/aggregation/per_property.py` to roll booking + pricing + events into per-property weekly snapshots.

Output: an `intelligence_property_snapshots` table that the operator dashboard can read for property-level analytics.

### Phase 3 — First analytics surface (1 session)

Build `intelligence/analytics/pricing_recommendations.py`. This is the highest-value first analytics output because pricing is where operators have agency. Input: per-property snapshots + market signals. Output: per-property pricing recommendations with confidence and reasoning.

Land a `recommendations` API endpoint. The v2 frontend gets a "Pricing Insights" view.

This phase is when the intelligence layer becomes user-visible.

### Phase 4 — Cross-operator aggregation (1 session)

Build `intelligence/aggregation/cross_tenant.py` with privacy-preserving rollups. No operator sees another operator's specific data; aggregate statistics only ("operators in your market saw 12% occupancy growth this quarter"). This is where the platform-wide intelligence becomes a moat.

Requires careful privacy/anonymization review before this ships.

### Phase 5 — Amenity value analysis (1 session)

Build `intelligence/analytics/amenity_value.py`. Inputs: property amenity rosters + booking patterns + pricing realized. Output: per-amenity value contribution (e.g., "hot tubs in your market correlated with $42/night premium").

This is the BD-facing intelligence that helps operators decide capital investments.

### Phase 6+ — Forecasting, portfolio recommendations, conversation pattern analytics

Each its own session, each reading from the substrate built in phases 1–4.

---

## What needs to exist before this work starts

- **PMS booking feed working in production.** Today's Escapia integration may or may not fully populate canonical booking records. Verify before starting Phase 1.
- **PMS daily pricing feed working in production.** Likely needs a new ingestion path; today's PMS focus is reservations, not rate schedules.
- **Event scraper output reaching a canonical events table.** The scraper exists; canonical landing may or may not.
- **Multi-tenant data discipline.** Cross-tenant aggregation only works if tenant data is reliably isolated. Verify RLS / tenant_id discipline holds across all source tables before Phase 4.

The first three are work items themselves and should be confirmed (or scheduled) before Phase 1 begins. The fourth is a discipline check that gates Phase 4.

---

## Dependency rules for this layer

- `intelligence/` MAY import from any tier (`integrations/`, `messaging/`, `messaging_brain/`). Cross-cutting like `agents/`.
- `intelligence/` MUST NOT be imported by any of those tiers. The data flow is downstream-only.
- `intelligence/delivery/` is the only subpackage that exposes API endpoints; everything else is internal.
- Per-tenant aggregation never leaks across tenants. Cross-tenant aggregation is its own subpackage and only produces statistical outputs.

---

## What this brief deliberately does not commit to

- Specific pricing algorithms (EWMA vs ARIMA vs neural). That's Phase 3 design work.
- Specific database schemas for signal storage. That's Phase 1 design work.
- Specific frontend visualizations. That's frontend work after Phase 3.
- Whether ML models live in this package or in a separate `app/services/ml/` package. Worth deciding when the first analytics module needs a model.
- Cost / licensing for any third-party data (market reports, comp data). Procurement decision, not architecture.
- Whether the intelligence layer becomes a separate deployable service eventually. Likely yes at scale, but starts as same-process.

---

## Risks worth flagging now

**Risk: PMS data is incomplete or unreliable.** Escapia gives us what it gives us. If daily pricing isn't accessible via ENET, Phase 2 pricing analytics is blocked until a workaround exists (scraping operator-facing portals, manual operator input, etc.).

**Risk: Cross-tenant aggregation requires more privacy scaffolding than expected.** The "operators in your market" framing sounds simple but requires geofencing definitions, minimum-N anonymization thresholds, and policy decisions about what statistics are shareable.

**Risk: The intelligence layer becomes a distraction from messaging brain operations.** The brain is the daily-driver product. Don't ship intelligence Phase 1 if it would delay operationally-critical brain work. Sequence carefully.

**Risk: Confusion with the predecessor product's analytics framing.** RentalRevenue.ai positioned itself as an analytics platform. Oyvoda is an AI concierge platform with analytics as a second pillar. Don't let the architecture drift toward predecessor-shape.

---

## Closure criteria (for the architectural seed, not the full build)

The seed is "done" when:

1. `app/services/intelligence/` package exists with the subpackage structure above
2. `__init__.py` files at each level document the cross-cutting framing and dependency rules
3. `canonical_signal.py` defines the `SupplyDemandSignal` contract
4. `docs/architecture/intelligence/` exists with this brief filed under it
5. Phase 1 has a separate execution brief written when ready to start

The full build is multi-quarter. This brief gets the architectural home in place so future phases land in the right directory and inherit the right dependency rules.

---

## How this relates to the other workstreams

- **Workstream A (frontend v2 extension):** The intelligence layer will eventually need a frontend surface. Coordinate so the v2 frontend has a clear pattern for analytics views once Phase 3 lands.
- **Workstream B (operator knowledge substrate):** The intelligence layer reads operator-provided knowledge as one input (e.g., amenity rosters). The substrate brief is a prerequisite for amenity value analysis in Phase 5.
- **Workstream D (docs cleanup):** Predecessor docs get reviewed for extraction candidates during cleanup. The extraction targets are bucket 2 (`docs/architecture/future/`) and ultimately move into `docs/architecture/intelligence/` as phases ship.
