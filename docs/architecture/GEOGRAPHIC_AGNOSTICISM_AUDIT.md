# Geographic Agnosticism Audit — Phase 4 Companion

Date: 2026-05-16
Status: Architectural principle + audit findings + implications for Phase 4.3-B onward
Scope: System-wide architectural posture toward geographic location

## Principle

**The platform is geographically agnostic by default.** Beach Habitats is the first operator and happens to be a Gulf Coast Florida vacation rental operator. The architecture must serve operators in any location on day one, with no code paths that assume a specific geography, climate, amenity ontology, or activity vertical.

Concretely, the system must work equally well for:

- 30A Florida (Beach Habitats — current first operator)
- Park City Utah ski-town rentals
- Sedona Arizona high-desert vacation homes
- Buenos Aires Argentina city apartments
- Chamonix France alpine chalets
- Tulum Mexico boutique stays
- Hudson Valley New York country homes
- Vermont ski-and-stay properties
- Cabo San Lucas Mexico beach villas
- Paris France pied-à-terre rentals

None of these is the template the system optimizes for. The system optimizes for **the architectural shape that makes all of them work simultaneously** without per-market code branches.

## What this means architecturally

1. **No hardcoded geography in business logic.** No `if community == "Watercolor"` checks. No assumption that operators are in Florida, the US, or even on a coast.
2. **No hardcoded amenity ontology that is biased to any market.** Beach access, beach chairs, pool heat are not universal property attributes. They are specific to coastal/sub-tropical markets. Ski-in/ski-out access, firewood, snow removal, mudroom storage are specific to mountain markets. Air conditioning is critical in some markets, irrelevant in others.
3. **No hardcoded vendor categories that assume any single market's verticals.** Beach chair rentals are 30A. Ski rentals are Park City. Wine tours are Napa. Jeep tours are Sedona. Boat charters are Lake Tahoe. Dive shops are Cozumel. The platform should not bake any of these into a fixed schema.
4. **No hardcoded upsell categories that assume a single market's activities.** "Pontoon rental," "fishing charter," "golf cart" are 30A activities and platform defaults should not include them as universal categories.
5. **Localization-ready.** Date formats, currency, language, address formats, phone formats, distance units (miles vs km), temperature units (F vs C), time zones — all must respect operator/market locale.
6. **Topic registry is bias-free at its core.** `TOPIC_REGISTRY` should contain universal property concerns: pets, parking, check-in, check-out, max occupancy, cleaning, cancellation, accessibility. Market-specific topics (beach_access, ski_rentals, pool_heating) are operator-authored or market-bundled, not platform-universal.
7. **Onboarding is market-aware, not market-prescriptive.** When an operator onboards at a given lat/long, the system **inherits** sensible defaults from that market's knowledge bundle. The operator can override or extend. They are never forced into a fixed schema designed for someone else's market.

## What is currently biased toward coastal/30A markets

### Schema: `operator_policies` table

The columns we hardened in Phase 4.3-A include market-specific columns that should not be first-class schema:

- `beach_chairs_included` (bool)
- `beach_chair_rental_partners` (JSONB)
- `pool_heat_available`, `pool_heat_daily_fee`, `pool_heat_advance_notice_hours`

A ski operator has no beach. A Buenos Aires apartment operator has no pool. These columns are coastal/sub-tropical assumptions baked into schema and need to migrate into a more flexible operator-authored amenity/policy structure.

**Action: deferred deprecation.** These columns stay for Beach Habitats compatibility through Phase 4.3-B/4.3-C, then migrate into a market-extensible amenity model in a future phase (4.4 or later).

### Topic registry

`app/services/concierge/knowledge_topic_registry.py` contains universal topics that work for any market:

- `pet_policy`, `pet_fee`
- `check_in_process`, `early_check_in`, `late_check_out`
- `parking`
- `sleeping_arrangement`, `max_occupancy`
- `cleaning_fee`, `cancellation_policy`, `payment_schedule`, `deposit_policy`
- `local_area`, `accessibility`

And market-specific topics that should NOT be in the universal registry as required topics:

- `beach_access`, `beach_gear` (coastal-specific)
- `pool_access`, `pool_heating_capability`, `pool_heating_cost`, `pool_heating_notice` (sub-tropical-specific)
- `hot_tub_access` (mountain/luxury-specific, but moderately universal)
- `golf_cart` (very 30A-specific — golf cart access is rare outside specific Florida/Arizona communities)

**Action: split the registry.**
- **Core topics** (universal, every operator gets): pets, check-in/out, parking, occupancy, sleeping, cleaning, cancellation, payment, deposit, local area, accessibility
- **Market-bundled topics** (inherited from operator's market): beach access, pool heat, ski rentals, hot tub, golf cart, etc.
- **Operator-authored topics** (operator extends with anything market-bundled doesn't cover)

This is Phase 4.3-B or later work. Out of scope for current ship.

### Hardcoded upsell defaults

`app/api/v1/endpoints/operator.py::get_revenue_impact` has hardcoded `PLATFORM_DEFAULTS`:

```python
PLATFORM_DEFAULTS = {
    "late_checkout": 35.0,
    "early_checkin": 35.0,
    "beach_chairs": 35.0,     # 30A
    "pontoon": 250.0,         # 30A / lake markets
    "fishing": 180.0,         # coastal / lake
    "dolphin": 120.0,         # 30A coastal
    "golf": 150.0,            # universal but USD-specific
    "bikes": 40.0,            # universal
    "spa": 120.0,             # universal
    "groceries": 15.0,        # universal
    "mid_stay_clean": 75.0,   # universal
    "pool_heat": 50.0,        # sub-tropical
}
```

Most of these are 30A-specific. A ski operator's defaults would be: `lift_tickets`, `ski_rentals`, `lesson_packages`, `firewood`, `snowshoe_tours`. A Napa operator: `wine_tasting_passes`, `vineyard_tours`, `chef_at_home`. A Buenos Aires operator: `tango_lessons`, `wine_tasting`, `private_tours`.

**Action: market-bundled upsell defaults.** Each market in `market_registry` carries its own default upsell categories and rates. Operators inherit from their market, then override. Phase 4.4 (vendor/upsell activation) work.

### Geographic intelligence scaffolding

The `market_registry`, `market_events`, `operator_market_links` tables exist (per migration `017_market_events_registry.py`) — good. But the events scraper and market intelligence today is biased toward 30A:

- Existing scrapers run against `30a.com` and `visitsouthwalton.com`
- `market_events` data is seeded with 30A events
- The `dispatch_pre_booking` and Brain pipeline assume access to market events for the operator's market — but only 30A market has populated data

**Action: market-extensibility, not market-uniformity.** Park City has its own event sources (ski resort calendars, festival pages). Buenos Aires has its own (tango events, neighborhood festivals). The architecture must support arbitrary scraper/source registration per market without code changes per market. Phase 4.7+ work.

### Proactive signal sources

Earlier framing referred to "weather/NOAA/beach-flag" signal ingestion for proactive guest notifications. NOAA is US-coastal-specific. Beach flags are US-coastal-specific. Ski operators need different signals (avalanche advisories, resort opening status, snow conditions). European operators won't use NOAA at all.

**Action: market-bundled signal sources.** Each market declares what signal sources matter for its operators. Phase 4.7+ work, specifically the proactive signal ingestion activation step.

## Market knowledge bundle concept

A `market` (existing concept in `market_registry`) carries a **knowledge bundle** that operators inherit at onboarding. Sketch of what a market bundle contains:

- **Default topic priorities** — which `TOPIC_REGISTRY` entries are pre-enabled, what additional market-specific topics are surfaced (beach_access for coastal markets, ski_rentals for ski markets)
- **Default amenity ontology** — what amenities are presented as common for this market (pool, beach access, hot tub, gas grill, ski-in/ski-out, fireplace, AC, fan, doorman)
- **Default vendor categories** — what vendor types operators in this market typically need (beach chair rental, ski equipment rental, wine tour, etc.)
- **Default upsell categories with regional pricing** — what upsells operators offer, at what typical price points (regional currency)
- **Signal sources** — which external feeds matter for proactive notifications (NOAA for coastal, ski resort calendars for mountain)
- **Compliance overrides** — market-specific compliance language (hurricane evacuation for FL/Gulf, avalanche advisory for ski markets)
- **Locale** — currency, language, date/time formats, distance/temperature units
- **Seasonal patterns** — when operators in this market expect peak/off-peak, what shoulder seasons look like

When operator onboards at lat/long → system matches to existing market OR identifies as new market needing bootstrap → operator inherits the market's bundle → operator customizes from there.

The merge precedence for operator-facing knowledge becomes:

1. Platform compliance (federal law, ADA — universal)
2. Property-level (per-unit specifics)
3. Property-group-level (condo complex / portfolio segment)
4. Operator-level (tenant defaults the operator authored)
5. **Market-level (inherited bundle — new tier)**
6. Schema defaults (last resort, minimal)

Market is the second-most-default tier. A ski operator who hasn't authored their own ski-rental policy still gets reasonable defaults from the Park City market bundle. They don't see "beach chairs included" prompts because they're in a ski market, not a coastal market.

## LLM-cost-aware onboarding architecture

### Where LLM costs occur in onboarding

When a new operator onboards, the system runs an **onboarding migration flow** that uses LLMs at several points. Each costs real money per LLM call and the costs must be tracked and attributed:

1. **Market identification** — from lat/long + operator-provided description, identify which existing market they belong to, or whether they need a new market bootstrapped
2. **Market bootstrapping (new markets only)** — if the operator is in a market the platform hasn't seen before, an LLM-driven research pass identifies the market's character (coastal/mountain/desert/urban), surfaces relevant amenity categories, identifies common vendor types in that market, etc.
3. **Property data extraction** — each property's listing data (Airbnb, Vrbo, PMS, operator website, guidebook) gets processed by an LLM to extract structured facts: bedrooms, bathrooms, amenities, special features, neighborhood description, walking-distance attractions
4. **Topic-tagged knowledge projection** — each guidebook's content gets projected into `concierge_scoped_knowledge` with topic tagging where applicable (Phase 4.0 already does this — guidebook_ingest_v2)
5. **Initial operator policy suggestions** — LLM-driven suggestions for what operator-level policies are typical for this market, that the operator can accept, modify, or decline
6. **Vendor category suggestions** — surface market-typical vendor categories the operator likely needs

### Ongoing LLM costs per property

After onboarding, ongoing LLM costs continue at lower volume:

- Periodic guidebook re-ingestion when operators update guidebooks
- New properties added to the portfolio (extraction + projection)
- Vendor list intelligence refresh
- Market event scraping per market (one-time per event, but accumulates over time)
- Real-time guest messaging (per-message LLM calls — already part of Brain operating cost)

### Cost tracking infrastructure

`llm_usage_events` table already exists (migration `063_llm_usage_events.py`). The infrastructure is there. What needs to be confirmed and possibly hardened:

- Every LLM call is attributed to `tenant_id` (the operator) and where applicable `property_id` (the property the call was made on behalf of)
- Each call records the `operation_type` (e.g. `onboarding_property_extraction`, `guidebook_ingest`, `guest_message_response`, `vendor_intelligence`)
- Each call records the model used, input tokens, output tokens, and computed cost
- The data is aggregatable per operator per month for billing purposes

**Action: audit `llm_usage_events` for tenant_id/property_id/operation_type attribution.** If gaps exist, harden in Phase 4.7 or as a focused brief. Out of scope for immediate Phase 4.3-B/C UI work, but must land before operator #2.

### Pricing baseline

The architectural decision is that operator pricing must cover LLM cost recovery plus margin. Specific pricing baseline (subject to business refinement, but architecturally required as a constraint):

**One-time onboarding fee per operator:** baseline of **$1,000–$2,500** to cover:
- Market identification + bootstrapping (new markets at the higher end)
- Property data extraction for first batch (up to N properties — definition TBD)
- Initial guidebook ingestion for the property set
- Initial topic-tagged knowledge projection
- Initial operator policy + vendor category suggestions
- Buffer for operator-side iteration (re-runs, corrections)

The fee should scale: an operator onboarding 5 properties has a lower bound; an operator onboarding 500 properties has higher LLM costs and a higher fee.

**Ongoing per-property fee:** a monthly or annual fee per property that covers:
- Periodic guidebook refresh
- Vendor intelligence refresh
- Market event ingestion attribution
- Buffer for ad-hoc operator updates (new amenities, policy changes)

Specific dollar values are business decisions that depend on:
- Operator contract structure (subscription vs revenue-share vs per-stay)
- Billing system integration
- Competitive positioning vs incumbents
- Tier offerings (basic = deterministic only, premium = LLM-augmented)

Those are not engineering decisions. The architectural requirement is:

1. **LLM costs are attributable** per tenant, per property, per operation
2. **Cost data is queryable** for billing reconciliation
3. **Different operator tiers can gate different LLM-augmented features** so a "basic" tier operator gets deterministic-only flows and a "premium" tier operator gets full LLM-augmented onboarding

### Pricing-tier architecture hooks

The system should support pricing-tier gating from day one. Architecturally:

- Operator has a `pricing_tier` (string: e.g. `basic`, `premium`, `enterprise`) — currently not present in `operator_policies` or anywhere structured
- LLM-augmented features check the operator's pricing_tier before invoking expensive LLM calls
- "Basic" tier operators get deterministic flows (templates, simple matching) — no LLM costs beyond messaging
- "Premium" tier operators get the full LLM-augmented onboarding, intelligence refresh, etc.

This isn't required for Beach Habitats today but is required architecture before operator #2 onboards if the pricing model is to be defensible.

**Action: add `pricing_tier` to operator/tenant model.** Phase 4.7+ work. Out of scope for immediate Phase 4.3-B/C.

## What this means for active phase planning

### Phase 4.3-B (operator dashboard UI for tenant-level policy authoring)

- UI must NOT bake coastal/30A assumptions
- Universal core sections always shown: Pet Policy, Pets+Fees, Cleaning Fees, Check-in/Check-out, Cancellation, Discount Rules, Support Contacts
- Market-specific sections shown only if the operator's market includes them: Beach Access policies (only for coastal markets), Pool Heating (only for sub-tropical markets), Ski Storage (only for ski markets)
- "Pets Allowed" section is universal; "Beach Chairs Included" section is market-bundled
- For operators in new/unknown markets, the UI presents universal sections and offers "Add custom amenity / policy section" so the operator can author their own
- UI copy: examples and instructional text MUST be market-appropriate. A ski operator should not see "fee for early beach access" as an example. Either generic examples ("late checkout fee") or market-bundled examples (ski operator sees "ski rental fee")

### Phase 4.3-C (operator dashboard UI for per-property knowledge authoring)

- Same principle. Per-property knowledge author flow must let operators describe their property in their own terms.
- The system structures it via topic registry (universal core + market-bundled additions + operator-authored extensions)
- No coastal-specific defaults forced onto the operator

### Phase 4.4 (vendor activation)

- Vendor categories are operator-authored OR market-bundled, never platform-prescribed
- Market bundle suggests vendor categories appropriate to that market
- Operator overrides or adds to that list
- Platform doesn't ship with a fixed vendor schema

### Phase 4.7 (signup geographic intelligence)

- This is the **primary implementation** of the principle. Onboarding flow:
  1. Operator provides lat/long + description + portfolio size
  2. Platform matches lat/long to existing market OR identifies as new market
  3. New markets trigger LLM-driven bootstrap (with cost tracking)
  4. Operator inherits market bundle
  5. Operator customizes per their portfolio
- Pricing tier gates how much LLM augmentation happens
- Cost tracking attributes every LLM call to tenant + property + operation_type

### Phase 4.8 (upsells)

- Upsell categories and rates are market-bundled, not platform-defaulted
- The hardcoded `PLATFORM_DEFAULTS` in `get_revenue_impact` retires

### Phase 4.10 (proactive signal ingestion)

- Signal sources are market-declared, not platform-fixed
- NOAA for coastal US markets, ski resort calendars for mountain markets, monsoon advisories for Sedona, etc.
- Architecture supports adding new signal sources per market without platform code changes

## Acknowledgment for memory

This audit was written 2026-05-16 to answer the architectural concern: "we're building for any operator anywhere in the world, not just Beach Habitats / Gulf Coast Florida." Beach Habitats is the first operator. The architecture must serve all future operators in all markets equally. Code currently has coastal/30A bias in several places (enumerated above) that must be addressed through Phase 4.3-B onward, treated as architectural constraints on every future brief.

The companion concern: LLM-augmented onboarding has real cost that must flow to operator pricing. Architecturally, that means: cost tracking, cost attribution, pricing-tier gating, and a baseline pricing model ($1K–$2.5K onboarding fee + ongoing per-property fee) that business decisions can refine but engineering must support.

This document and `TENANT_ISOLATION_AUDIT.md` together define the constraints under which Phase 4.3-B and onward proceed. Future briefs must respect both.
