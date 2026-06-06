# Canonical Operator Knowledge Model — Phase 4.3-E

Date: 2026-05-17
Status: The architectural back-into target — what an operator must provide for the system to draft well, regardless of source
Scope: System-wide foundation for onboarding, document extraction, UI authoring, and Brain consumption

## Corrective notice

This document was originally committed in revision `e813e14`. That first revision correctly defined the canonical model tiers and the 90%+ drafting target, but it misread empty `properties` columns as if Beach Habitats had failed to provide the underlying information.

That diagnosis was wrong. The operator-authored data exists. It was ingested by Phase 4.0 into `concierge_scoped_knowledge` and the vector store. The real gap is **pipeline propagation**: structured facts such as bedrooms, bathrooms, sleeps, wifi, parking, and pet/pool attributes were not written back into structured `properties` columns.

This corrective revision preserves the model itself, but updates the diagnosis everywhere it matters:

- Empty structured columns are treated as an ingest-pipeline projection gap, not an operator-authoring gap
- Beach Habitats does not need to re-author this information
- The near-term fix is a one-time structured backfill from existing canonical knowledge (Phase 4.0-A)
- A later Brain enhancement can add vector retrieval as a tertiary/fallback read path (Phase 4.2.5)

## Purpose

This document defines **the canonical knowledge model an operator must populate for the system to draft at 90%+ accuracy** — independent of source format (Breezeway guidebook, CSV upload, PDF, PMS integration, direct UI entry, scraped listing).

It is reverse-engineered from Beach Habitats's production data after Phases 4.0/4.1/4.2 populated `concierge_scoped_knowledge` with 1,757 active entries across 45 properties. The model identifies:

- What every operator needs at minimum to draft well
- What's universal across markets vs market-bundled
- What's structured vs topic-tagged vs freeform
- The current gaps in Beach Habitats that future onboarding flows must close

The model is **geographic-agnostic by default** per `GEOGRAPHIC_AGNOSTICISM.md`. Market-specific extensions are explicitly named where they apply.

## Empirical findings (Beach Habitats, 2026-05-17)

### Topic-tagged entries (318 entries, 12 topics)

Universal core — populated for all 45 properties:

- `accessibility`
- `late_check_out`
- `local_area`
- `parking`
- `pool_access`
- `cancellation_policy`
- `check_in_process`
- `golf_cart` (market-specific to coastal/30A, present for Beach Habitats but not universal)

Sparse coverage — present for 1–4 properties only:

- `beach_access` (4) — extraction missed for the other 41 properties
- `beach_gear` (4)
- `sleeping_arrangement` (1)
- `pool_heating_capability` (1)

Sparse coverage signal: **operator-supplied content likely contains these facts for all 45 properties; the ingest pipeline failed to topic-tag them.** They landed in freeform entries instead. This is an extraction-quality issue, not an authoring gap.

### Freeform entries (1,439 entries across 9 source categories)

Section-based categorization inherited from Breezeway's guidebook information architecture:

- **FAQs** — 897 entries across 39 properties (largest single category)
- **Travel Tips** — 90 entries, 45 properties
- **About Property** — 90 entries, 45 properties
- **Trash Info** — 56 entries, 28 properties
- **Safety** — 45 entries, 45 properties
- **Recommendations** — 45 entries, 45 properties
- **Contact Info** — 45 entries, 45 properties
- **Welcome** — 45 entries, 45 properties
- **About Us** — 45 entries, 45 properties

Key signal: **the freeform sections cover universal property knowledge categories** that any operator in any market needs (emergency contacts, welcome orientation, area recommendations, safety notes). The labels are Breezeway-specific; the underlying content shape is universal.

### Structured `properties` table population

Field-level coverage across 45 active properties:

| Field | Populated | Notes |
|---|---|---|
| `bedrooms` | 33/45 | Partial structured propagation |
| `bathrooms` | 37/45 | Partial structured propagation |
| `sleeps` / `max_occupancy` | 0/45 | **Not propagated into structured fields** |
| `has_pool` flag | 0/45 | **Not propagated into structured fields** |
| `pool_heated` flag | 0/45 | **Not propagated into structured fields** |
| `has_hot_tub` flag | 0/45 | **Not propagated into structured fields** |
| `pets_allowed` flag | 0/45 | **Not propagated into structured fields** |
| `wifi_network` | 0/45 | **Not propagated into structured fields** |
| `check_in_time` | 45/45 | Universal |
| `check_out_time` | 45/45 | Universal |
| `parking_instructions` | 0/45 | **Not propagated into structured fields** |
| `address_street` | 45/45 | Universal |
| `community` | 38/45 | Partial |
| `general_notes` | 0/45 | Structured notes column unused |
| `amenities` JSONB | 0/45 | **Not used at all** |
| `property_policy_overrides` JSONB | 0/45 | Expected (new column) |

**Significant finding: most "structured" fields are empty, but the data is not absent.** Beach Habitats's property facts live almost entirely in `concierge_scoped_knowledge` freeform/topic-tagged entries and the vector store — not in the structured `properties` columns. The schema has columns; the ingest pipeline simply never projected many extracted facts back into them.

This shapes the canonical model: **structured columns should be reserved for facts the system uses deterministically (bedrooms for occupancy reasoning, has_pool for pool-question routing, etc.), and the ingest pipeline must write those facts into both structured fields and canonical knowledge surfaces.** The remaining long-tail content stays in `concierge_scoped_knowledge` with topic tags where possible.

## The canonical knowledge model

### Tier 1: Structured property facts (required, atomic, queryable)

These belong as columns on `properties` (or as flat JSONB if column proliferation becomes a problem). The Brain uses them for deterministic routing and reasoning. Every property needs them:

**Identity:**
- `property_code` — operator's internal identifier (e.g., "17LL")
- `property_name` — human-readable name
- `display_name` — name shown to guests

**Address & location:**
- `address_street`, `address_city`, `address_state_region`, `address_postal_code`, `address_country`
- `latitude`, `longitude`
- `community` or `neighborhood_name` (optional)
- `property_group_id` (optional FK if part of a condo complex / portfolio segment)

**Occupancy & layout:**
- `bedrooms`
- `bathrooms`
- `max_occupancy` (sleeps)
- `square_footage` (optional)
- `property_type` (single_family, condo, townhouse, cabin, apartment, villa, chalet, etc.)

**Universal-friendliness flags (boolean, every market):**
- `pet_friendly` — does this property allow pets (operator-level policies provide fee/restrictions)
- `accessible` / `wheelchair_accessible`
- `wifi_available`
- `parking_available`

**Conditional flags (operator may or may not have these — empty is fine):**
- `has_pool`, `pool_heated`
- `has_hot_tub`
- `has_waterfront`
- `has_outdoor_space` (yard, patio, balcony)
- `has_fireplace` / `has_woodburning_fireplace` / `has_gas_fireplace`
- `has_kitchen` / `has_full_kitchen`
- `has_laundry` / `has_washer_dryer`
- `has_ac`
- `has_heat`

**Timing:**
- `check_in_time` (operator default if not set)
- `check_out_time` (operator default if not set)
- `time_zone`

**Per-property policy overrides:**
- `property_policy_overrides` JSONB (already in schema after Phase 4.3-A.1) — flat-mirrors `operator_policies` field names, overrides apply per-property

**Tenant-scoped routing controls:**
- `operator_settings.extra.intent_classifier_escalation_threshold` — pre-booking low-confidence escalation threshold, default `0.40`
- `operator_settings.extra.brain_router_confidence_threshold` — Brain specialist-routing floor, default `0.30`
- `operator_settings.extra.reservation_aware_routing_window_days_past` — how far past check-in a reservation may still count for intake lifecycle resolution, default `14`
- `operator_settings.extra.reservation_aware_routing_window_days_future` — how far before check-in a reservation may still count for intake lifecycle resolution, default `30`

These are not property facts, but they are part of the canonical operator
control plane for message handling. They tune when deterministic intent
classification should escalate to an LLM and when uncertain classifications
should fall back to a generalist rather than a specialist. They also govern
when inbound email routing should treat a PMS reservation as sufficient
evidence that a guest is already in the booked lifecycle, even before a
concierge session exists.

### Tier 2: Topic-tagged knowledge (universal core)

These are the topics the Brain routes deterministically. Every operator needs them populated for every property (or inherited from operator-level defaults). The universal core, regardless of market:

- `pet_policy` — sourced from `properties.pet_friendly` + `operator_policies.pet_*`
- `check_in_process` — instructions for arrival
- `check_out_process` — instructions for departure
- `parking` — where guests park, instructions, any restrictions
- `wifi_access` — network name, password, troubleshooting
- `max_occupancy` — guest count limits
- `sleeping_arrangement` — bed configuration
- `cleaning_fee` — disclosure of cleaning charges
- `cancellation_policy` — operator policy
- `payment_schedule` — when payment is due
- `deposit_policy` — security deposit handling
- `late_check_out` — availability, fee, approval
- `early_check_in` — availability, fee, approval
- `accessibility` — wheelchair access, stairs, elevator, accessibility features
- `local_area` — neighborhood character, walking distance attractions
- `emergency_contacts` — who guests call for what
- `trash_disposal` — pickup days, recycling, bin location
- `quiet_hours` — noise restrictions
- `smoking_policy` — where allowed/not

**Status note (Phase 4.6-A):** `wifi_access`, `emergency_contacts`, `trash_disposal`, `quiet_hours`, and `smoking_policy` were added to `TOPIC_REGISTRY` in Phase 4.6-A. Existing freeform entries in Beach Habitats's Trash Info, Safety, Contact Info, Welcome, and FAQ sections will be properly topic-tagged on next re-ingest or via Phase 4.3-F new-operator extraction.

### Tier 3: Topic-tagged knowledge (market-bundled extensions)

Topics inherited from operator's market. Not universal. Examples by market type:

**Coastal markets (FL Gulf, FL Atlantic, CA coast, NC Outer Banks, etc.):**
- `beach_access` — distance, access route, public vs private
- `beach_gear` — chairs/umbrellas included or rental partner
- `pool_access`, `pool_heating_capability`, `pool_heating_cost`, `pool_heating_notice`
- `hurricane_evacuation` — compliance language
- `red_tide_advisory` — seasonal water quality

**Mountain / ski markets (Park City, Aspen, Vermont, Chamonix, etc.):**
- `ski_in_ski_out_access`
- `ski_storage`
- `lift_ticket_distance`
- `firewood_supply`
- `mountain_view_type`
- `avalanche_advisory` — compliance language
- `snow_chains_required` — seasonal driving conditions

**Desert markets (Sedona, Palm Springs, Tucson, etc.):**
- `monsoon_advisory` — seasonal
- `pool_cooling_capability` — opposite shape from pool heating
- `casita_separate` — accessory dwelling unit
- `shade_structures` — pergola, ramada

**Urban markets (Buenos Aires, Paris, Mexico City, etc.):**
- `elevator_access`
- `doorman_hours`
- `building_security`
- `balcony_type`
- `public_transit_access`

**Wine / agritourism markets (Napa, Tuscany, Mendoza, etc.):**
- `vineyard_view`
- `winery_walking_distance`
- `tasting_room_partners`

**Coastal-tropical markets (30A is one of these — also Cabo, Tulum, Bali, etc.):**
- All coastal topics plus `golf_cart` (where local culture supports it)

Markets in `market_registry` declare their topic extensions. Operators inherit at onboarding and can opt out per property.

### Tier 4: Freeform knowledge (the long tail)

What doesn't fit a topic registry but operators still need to capture. Beach Habitats's freeform categories suggest the universal shape:

- **Welcome / orientation** — warm welcome message, what to expect on arrival
- **About the property** — character, history, unique features that don't fit structured fields
- **About the operator** — who guests are renting from, hospitality philosophy
- **Travel tips** — operator-curated local advice ("hidden beach is at end of access road #4")
- **Recommendations** — restaurants, activities, services (becomes proper vendor entries in Phase 4.4)
- **Safety information** — hurricane prep, fire extinguisher location, first aid kit, medical facility distance
- **House rules & quirks** — anything not policy-grade but worth knowing ("septic system — only flush TP")
- **Contact information** — operator/property manager phone, emergency contact, owner contact if applicable
- **FAQs** — operator-curated common questions not covered by topic registry

These land in `concierge_scoped_knowledge` as freeform entries with `topic_id=NULL` and metadata noting the category. The Brain consumes them via FAQ matching when guest questions don't trigger topic-tagged routing.

### Tier 5: Operator-level policies (tenant-wide)

In `operator_policies` table. Universal columns:

- Canonical identity key: `tenant_id`
- Transitional legacy key: `operator_id` remains temporarily for compatibility only and should not be used by new reads or writes
- Market scoping field: `market_id` for event and locale-aware operator context

- Pet policy defaults: `pet_fee`, `pet_cleaning_fee`, `pet_max_weight`, `pet_restricted_breeds`, `pet_notes`
- Cleaning fee defaults (if uniform across portfolio)
- Cancellation terms: `cancellation_full_refund_days`, `cancellation_partial_refund_days`, `cancellation_partial_refund_percent`
- Check-in/out defaults: `check_in_time`, `check_out_time`
- Late checkout: `late_checkout_available`, `late_checkout_fee`, `late_checkout_max_time`, `late_checkout_requires_approval`
- Early checkin: `early_checkin_available`, `early_checkin_earliest`, `early_checkin_fee`, `early_checkin_subject_to_availability`
- Discount rules: `discount_policies` JSONB (structured per `DiscountRule` schema)
- Support contacts: `support_phone`, `support_email`, `emergency_phone`

**Coastal-biased columns currently in schema (deprecate in Phase 4.6):**
- `beach_chairs_included`, `beach_chair_rental_partners`
- `pool_heat_available`, `pool_heat_daily_fee`, `pool_heat_advance_notice_hours`

These migrate to a market-bundled or operator-authored amenity model in Phase 4.4 / 4.6.

### Tier 6: Property-group knowledge (Phase 4.3-A.2, dormant)

For multi-segment portfolios. Knowledge that applies to "all units in Watercolor Resort" or "all units in Building A":

- Group-scoped entries in `concierge_scoped_knowledge` with `scope_type='property_group'`
- Inheritance order: property > property_group > operator > market > schema_default

### Tier 7: Vendor knowledge (Phase 4.4, future)

Operator's vendor relationships, by category. Examples vary by market:

- Coastal: beach chair rentals, charter captains, paddleboard rentals
- Mountain: ski rentals, lift ticket concierge, snowmobile tours
- Universal: cleaners, maintenance vendors, locksmith, plumber, HVAC

Operator-authored or market-bundled categories. Each vendor: name, contact, hours, service area, pricing notes, operator's relationship status.

### Tier 8: Market knowledge bundle (Phase 4.7, future)

Inherited automatically at onboarding based on lat/long → market match. Contains defaults for Tiers 2 (market-bundled topics), 3 (market-bundled vendors), and parts of Tiers 4–5 (regional defaults, locale settings, seasonal patterns).

## The 90% accuracy target

For the Brain to draft at 90%+ accuracy for a new operator, the operator must provide:

**Required minimum (the floor):**

1. **Property structured facts** (Tier 1) for every property — bedrooms, bathrooms, max_occupancy, address, check-in/out times, key amenity flags (pet_friendly, has_pool, etc.)
2. **Topic-tagged universal core** (Tier 2) — at least operator-level defaults for: pet policy, cancellation, check-in process, parking, wifi access. Property-level overrides where they differ.
3. **Operator-level policies** (Tier 5) — at least: pet fee, cleaning fee, cancellation terms, check-in/out defaults, support contacts.

**Strongly recommended (gets you above 90%):**

4. **Topic-tagged universal core extended** — quiet hours, smoking policy, emergency contacts, trash disposal, accessibility.
5. **Freeform property knowledge** (Tier 4) — welcome message, safety info, neighborhood character, operator's recommended local spots.
6. **Property-level overrides** for variances (one specific property has a higher pet fee, etc.)

**Adds polish (gets you above 95%):**

7. **Market-bundled extensions** (Tier 3) — beach access details, ski storage, elevator access, whatever the market includes.
8. **Vendor knowledge** (Tier 7) — operator's preferred local services.
9. **Property groups** (Tier 6) — for multi-segment portfolios.

## Mapping to onboarding pathways

This model is **source-agnostic**. The same canonical structure can be populated from:

- **CSV upload** — operator exports property data from their PMS (Guesty, Hostfully, Track, Escapia, etc.) and uploads. Each row maps to a property. Columns map to Tier 1 structured fields and to topic-tagged knowledge entries.
- **PDF upload** — operator drops in their existing property packet PDF (rental agreement, welcome book, property info sheet). LLM extraction parses structured facts and topic-tagged content.
- **Spreadsheet upload** — same as CSV but Excel/Google Sheets format.
- **PMS API integration** — direct connector to operator's PMS pulls structured property data and policy data automatically.
- **Listing URL scrape** — operator provides their Airbnb / Vrbo / direct-website listing URLs. LLM extraction parses listing copy and amenity lists.
- **Operator website scrape** — operator's own website often has property pages with detailed info. LLM extraction parses.
- **Plain text dump** — operator pastes whatever they have (Word doc, email signature template, FAQ list). LLM structures it.
- **Direct UI entry** — for operators starting from scratch or with no structured source data. Guided flow walks them through the model tier by tier.
- **Hybrid** — most operators use multiple pathways. CSV for property facts + PDF for policies + direct entry for vendor list.

**Critically, the operator never types the same information twice.** The pathways feed the same canonical model. An operator can start with CSV for property facts, add a PDF for policies, then refine via UI — and the system maintains a single canonical view.

## Pipeline-propagation gaps surfaced by the current Beach Habitats data

These are concrete ingest-pipeline and data-projection issues that the next onboarding and extraction flow must close. They should not be interpreted as “the operator failed to provide the data.” In most cases, Beach Habitats already supplied the information in guidebooks; the system simply did not propagate it to the right deterministic surface.

1. **Bedrooms missing for 12/45 properties.** These should be projected from existing canonical knowledge into structured fields.
2. **Bathrooms missing for 8/45.** Same.
3. **`sleeps`/`max_occupancy` missing for all 45.** Critical for occupancy questions. The value likely exists in guidebook/listing content but was never propagated into a deterministic field.
4. **`has_pool` flag missing for all 45.** The pool topic-tagged entries are populated (45/45 have `pool_access`), but the structured flag is empty. The ingest should infer and project this.
5. **`pets_allowed` flag missing for all 45.** Beach Habitats's operator policy is "not allowed" but no property-level flag is set. The deterministic property flag should still be projected, even if uniformly false.
6. **`wifi_network` missing for all 45.** The wifi info likely lives in freeform FAQs and/or the vector store. It should be promoted to a topic-tagged entry and, where available, projected into a structured field.
7. **`parking_instructions` missing for all 45** — same propagation problem as wifi.
8. **`general_notes` missing for all 45** — operator-authored property-specific notes column unused; long-tail content remained in canonical knowledge instead.
9. **`amenities` JSONB unused** — flexible amenity authoring path not yet exercised.
10. **`property_policy_overrides` empty for all 45** — expected (new column from Phase 4.3-A.1), but future onboarding should make this easy to populate where applicable.
11. **Topic-tagging missed `beach_access`, `beach_gear`, `sleeping_arrangement`, `pool_heating_capability` for 41+ properties.** The content exists; the ingest pipeline failed to tag it.

Two distinct fixes follow from this:

- **Phase 4.0-A:** one-time Beach Habitats structured-properties backfill from existing canonical knowledge
- **Phase 4.3-F:** new-operator document upload + extraction writes to all three surfaces from day one: structured fields, `concierge_scoped_knowledge`, and vector storage

The future extraction and backfill flows must close these gaps by ensuring:

- Every property has every Tier 1 field populated
- The universal core topics (Tier 2) are populated for every property
- Operators see and confirm structured extraction results before commit
- Extraction quality is measured (% topics correctly tagged, % structured fields populated) and surfaced to operators as an onboarding completeness score

## Implications for ongoing phases

### Phase 4.0-A (next): Beach Habitats structured-properties backfill

A one-time projection job reads the existing canonical knowledge for Beach Habitats's 45 properties and writes extracted deterministic facts back into the empty `properties` columns.

This closes the current production data-shape gap without asking Beach Habitats to re-author anything. It is a backfill on already-ingested data, not a new onboarding flow.

### Phase 4.2.5 (later): Brain vector retrieval fallback

Long-term, the Brain should read in this order:

1. Structured property facts
2. Topic-tagged canonical knowledge
3. Freeform canonical knowledge
4. Vector retrieval fallback

The vector store already contains the full guidebook content from Phase 4.0. Wiring it into the Brain as a tertiary/fallback read path is a separate read-path enhancement, not part of onboarding extraction.

### Phase 4.3-F (next): Document upload + LLM extraction

The extraction pipeline targets this canonical model. For each property the operator uploads documents about, extraction populates:

- Tier 1 structured fields (via field-level extraction from CSV/PDF/text)
- Tier 2 topic-tagged knowledge (via LLM categorization against the topic registry)
- Tier 3 market-bundled topic-tagged knowledge (via market detection + topic application)
- Tier 4 freeform knowledge (whatever doesn't categorize)
- Vector storage for semantic retrieval fallback

The operator review/confirm UI shows what was extracted by tier, what's missing, and what the operator should add directly.

### Phase 4.3-B: Operator UI for policy editing

Targets Tier 5 (operator-level policies) and Tier 1 property-level edits. UI sections map to model tiers, not to coastal-biased columns.

### Phase 4.3-C: Per-property knowledge UI

Targets Tier 4 (freeform property knowledge) and Tier 6 (property-group knowledge if portfolio is grouped). Operator can add ad-hoc property updates ("outdoor kitchen added") that land as new freeform entries.

### Phase 4.4: Vendor activation

Targets Tier 7 (vendor knowledge). UI lets operators author vendors by category (with market-bundled category suggestions from Tier 8 once Phase 4.7 ships).

### Phase 4.5/4.6: Legacy retirement

Drops `concierge_knowledge` legacy table. Migrates coastal-biased schema columns (`beach_chairs_included`, `pool_heat_*`) out of `operator_policies` into market-bundled or operator-authored amenity model.

### Phase 4.6: Topic registry split

Current `TOPIC_REGISTRY` becomes the universal core (Tier 2). Market-bundled topics (Tier 3) move into market registry as inheritable extensions. New universal topics added: `wifi_access`, `emergency_contacts`, `trash_disposal`, `quiet_hours`, `smoking_policy`.

### Phase 4.7: Signup geographic intelligence + market knowledge bundles

Targets Tier 8 (market knowledge bundle). Onboarding workflow: lat/long → market match or bootstrap → operator inherits Tier 3 topic extensions, Tier 7 vendor categories, Tier 4 regional defaults, locale settings. Adds `pricing_tier` to operator/tenant model.

### Phase 4.8: Upsell activation

Targets parts of Tier 7 (upsell categories) and Tier 8 (market-bundled upsell rates with regional currency). Retires hardcoded `PLATFORM_DEFAULTS`.

### Phase 4.9: Expanded property data gathering

Adds more onboarding pathways (PMS integrations, listing scrapes) feeding the same canonical model.

### Phase 4.10: Proactive signal ingestion

Targets parts of Tier 3 (market-specific topic content) and Tier 8 (signal sources per market). NOAA for coastal, ski resort calendars for mountain, etc.

## Architectural authority

This document, together with `TENANT_ISOLATION_AUDIT.md`, `GEOGRAPHIC_AGNOSTICISM.md`, `POST_FOUNDATION_ACTIVATION.md`, and `FOUNDATION_REBUILD_ARCHITECTURE.md`, defines the architectural constraints under which Phase 4.3-F onward proceeds. The canonical model is the back-into target. The pathways are how operators populate it. The Brain reads the populated model.

Future briefs must respect:

- The model is source-agnostic — pathways serve the model, not the other way around
- The model is geographic-agnostic by default with market-bundled extensions
- The model is operator-friendly (operators provide what they have, system structures it)
- The 90%+ accuracy target requires the floor (Tiers 1, 2, 5) at minimum
- LLM-augmented extraction costs are tracked and attributed per `GEOGRAPHIC_AGNOSTICISM.md`
- Tenant isolation per `TENANT_ISOLATION_AUDIT.md` applies to every onboarding surface

## Acknowledgment for memory

This document is the empirical back-into target for Oyvoda's operator onboarding architecture. Reverse-engineered from Beach Habitats's production data on 2026-05-17, then corrected in a follow-up revision once it became clear that empty structured columns reflected an ingest-pipeline propagation gap rather than missing operator-provided data.

Beach Habitats is operator #1, not the template — but their populated content (and the way it landed across canonical knowledge, vector storage, and structured fields) is the only real-world signal we have about what operators need to provide and what the ingest pipeline must do with it. The canonical model is geography-agnostic, source-agnostic, and operator-friendly. Future onboarding pathways (document upload, PMS integration, listing scrape, direct entry) target this model. The Brain reads it.
