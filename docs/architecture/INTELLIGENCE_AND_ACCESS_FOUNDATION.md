# Intelligence and Access Foundation

**Status:** Architecture design document (no code)
**Author:** Claude, written under Hunter's direction with input from Codex
**Date:** May 2026
**Parent docs:**
- `docs/architecture/COMMAND_MODULE_PROPOSAL.md`
- `docs/architecture/SHIP_A_FOUNDATIONS.md` through `SHIP_D_PREBOOKING_REDESIGN.md`
- `docs/architecture/KNOWN_REFINEMENTS.md`

---

## Why this document exists

The shipped UI redesign arc (Ships A–D) made Oyvoda look like a modern operator product. It did not change what the product *is*. As of Ship D, Pre-Booking is still structurally an inbox — a queue you work through, with AI assistance. That is not the product Oyvoda is meant to be.

The product Oyvoda is meant to be is described well in Hunter's instinct and Codex's framing of it:

> "Messaging is the ingestion layer. Intelligence is the compounding layer."

Every guest inquiry is two things simultaneously: an operational event (a guest needs a reply) and a learning event (a signal about what guests want, what properties sell, what knowledge is missing, what drives conversion). The messaging workflow is how Oyvoda enters an operator's account. The intelligence layer is how it becomes indispensable — and how it becomes defensible against competitors who can also build messaging.

To deliver that product, three foundations have to be designed together rather than serially:

1. **Access control** — because the operator segment Oyvoda needs to serve (50–1000+ unit operators with staff, possibly outsourced) requires real role-based access, property-scoped permissions, and audit trails. Building intelligence surfaces without RBAC bakes in "everyone sees everything" assumptions that are painful to retrofit.
2. **Inquiry intelligence model** — what we capture per inquiry, how we structure it, and how the same data structures serve both operator-facing analytics and network-level learning. Built carelessly, this is reporting. Built deliberately, this is the compounding layer.
3. **Network intelligence and feedback loops** — how aggregated learning across operators flows back into the messaging layer to make every operator's AI sharper than it could be on their data alone. This is the moat.

This document is the design pass for all three. **It commits no code.** It does commit to a model that subsequent ships will execute against.

The document also names what Oyvoda already has, so we are not re-proposing infrastructure that exists. The "Verified repo reality" sections under each part anchor the design in what is real today versus what is being proposed.

---

## Part 0: Geographic agnosticism is a hard requirement

Before defining the intelligence model, name the constraint that shapes it: **Oyvoda is geographic agnostic.** The first operator is in 30A. The second may be in Sedona, Asheville, the Outer Banks, the Smokies, the Texas hill country, Joshua Tree, or anywhere else short-term rentals concentrate. Every system we design must work without 30A-specific assumptions hard-coded.

This means three concrete things:

**1. Location is `(latitude, longitude)`, not "the beach" or "30A."** Properties carry coordinates. Markets are defined as geofence polygons or radius circles around coordinates, not by named regions. Distance-to-amenity is computed against coordinates, not against curated 30A landmarks.

**2. Local context is fetched, not hard-coded.** What the AI knows about a property's surroundings — restaurants, attractions, beaches, hiking trails, events — comes from APIs and scrapers that take coordinates as input. Google Places pipeline (which already exists at `app/services/knowledge/places_pipeline.py`) is the canonical example: operator registers a geofence during onboarding, the pipeline seeds market knowledge from Places API for any geography.

**3. Market intelligence indexes on geography, not on names.** Comparable-property analysis, amenity attribution, nightly-rate benchmarking — all of it joins on geographic proximity, market segment, and property characteristics, not on "30A" or "Florida panhandle." A property in Sedona benefits from the same aggregations as a property in Seaside, applied to its own local comparable set.

Anywhere this document references location, amenities, events, or market data, the assumption is geographic agnosticism. 30A is a concrete example because it is the first operator, not because it is special.

### Verified repo reality

What already supports geographic agnosticism today:

- `app/services/knowledge/places_pipeline.py` — Google Places (New) pipeline takes operator-registered geofence polygons and seeds local knowledge for any market. Pricing model is documented (≈$15/month per large market on weekly re-seed). Currently behind `GOOGLE_PLACES_API_KEY` env var.
- `app/services/scrapers/market_scraper.py` — market scraper plumbing. 30a.com and VisitSouthWalton sources exist as concrete adapters; the architecture allows additional source adapters per market.
- `app/services/analytics/market_amenity_attribution.py` — hedonic pricing model design (already documented) that controls for property characteristics including `distance_to_beach_ft`, view type, floor level, etc. The methodology is geography-agnostic; the attribute list will need market-specific extension (a "distance_to_trailhead_ft" matters in Sedona; "distance_to_lift_ft" matters in Park City).

What still needs work for full geographic agnosticism:

- Properties need a documented requirement to carry `(latitude, longitude)` and a market identifier
- Market scraper adapter framework needs documentation of how to add a new market (event sources, comparable-listing sources, local news sources)
- Amenity taxonomy needs to be extensible per market without code changes (config-driven)
- Some current code paths assume 30A-specific landmarks; those need to be identified and converted to coordinate-based

These are not blockers for the intelligence model design — but they are work items the design implies.

---

## Part 1: Access control model

### What we are building toward

A role-based access control system with property-level (and portfolio-level) scoping, capability-based permission checks, and a complete audit trail. Targeted at mid-market operators (50–1000 units) where the org has actual staff, possibly outsourced, with differentiated responsibilities. The model should also work cleanly for the 5-unit owner-operator (Lanier today) by collapsing to a single role.

### Roles

Five roles. Each role is a bundle of default capabilities. A user has exactly one role per organization, plus property scope (which properties they can act on).

**Owner** — full access to everything, including billing and org deletion. One per organization typically (founders, family-owned property managers). Cannot be revoked except by themselves or by Oyvoda support.

**Admin** — manages users, role assignments, property assignments, integrations (PMS, OTA, inbox), org-wide settings. Cannot change billing or delete the org. Property scope is always "all" — admin role implies portfolio-wide responsibility.

**Manager** — operational lead. Can approve/reject/edit drafts, manage knowledge base entries, dispatch vendors, configure operator AI guidance, see analytics across assigned scope. Can invite Operator and View-only roles but not Admin or Manager. Property scope is configurable: portfolio-wide, specific portfolios, or specific properties.

**Operator** — front-line messaging staff. Can approve/reject/edit drafts on assigned properties. Can mark inquiries as resolved. Sees analytics scoped to assigned properties. Cannot manage users, change settings, edit knowledge base entries, or dispatch vendors. Property scope is configurable down to individual properties.

**View-only** — sees everything in their scope but takes no actions. For owners who want oversight without operational role, for stakeholders (investors, family members of property owners), and for compliance/audit purposes. Property scope is configurable.

### Capabilities

Roles map to capabilities. Capability checks happen server-side at every action endpoint, not just in the UI. The UI hides controls a user lacks capability for, but the backend never trusts the UI.

Initial capability set (will grow as features land):

```
# Messaging actions
can_view_inquiries
can_approve_drafts
can_edit_drafts
can_reject_drafts
can_regenerate_drafts
can_mark_resolved

# Knowledge base
can_view_kb
can_edit_kb
can_resolve_kb_gaps

# Vendor / work orders
can_view_vendors
can_dispatch_vendors
can_manage_vendor_directory
can_view_work_orders
can_close_work_orders

# Analytics
can_view_property_analytics    # scoped to assigned properties
can_view_portfolio_analytics   # all properties in org
can_export_analytics

# Configuration
can_edit_operator_guidance
can_edit_org_settings
can_edit_integrations
can_edit_retention_policy

# Org administration
can_invite_users
can_change_user_roles
can_change_property_assignments
can_remove_users
can_view_audit_log
can_change_billing
```

Default capability map per role:

| Capability | Owner | Admin | Manager | Operator | View-only |
|---|---|---|---|---|---|
| can_view_inquiries | ✓ | ✓ | ✓ | ✓ | ✓ |
| can_approve_drafts | ✓ | ✓ | ✓ | ✓ | — |
| can_edit_drafts | ✓ | ✓ | ✓ | ✓ | — |
| can_reject_drafts | ✓ | ✓ | ✓ | ✓ | — |
| can_regenerate_drafts | ✓ | ✓ | ✓ | ✓ | — |
| can_view_kb | ✓ | ✓ | ✓ | ✓ | ✓ |
| can_edit_kb | ✓ | ✓ | ✓ | — | — |
| can_resolve_kb_gaps | ✓ | ✓ | ✓ | — | — |
| can_dispatch_vendors | ✓ | ✓ | ✓ | — | — |
| can_view_property_analytics | ✓ | ✓ | ✓ | ✓ | ✓ |
| can_view_portfolio_analytics | ✓ | ✓ | ✓ | — | ✓ (if scope=all) |
| can_edit_operator_guidance | ✓ | ✓ | ✓ | — | — |
| can_edit_org_settings | ✓ | ✓ | — | — | — |
| can_edit_integrations | ✓ | ✓ | — | — | — |
| can_invite_users | ✓ | ✓ | ✓ (Operator/View-only only) | — | — |
| can_change_user_roles | ✓ | ✓ | — | — | — |
| can_view_audit_log | ✓ | ✓ | ✓ (scoped) | — | — |
| can_change_billing | ✓ | — | — | — | — |

This is a starting model, not a contract. As features land, the capability list grows. The role-to-capability map is configurable per org (custom role mixes possible for enterprise tier later, not now).

### Property and portfolio scoping

A user's role determines *what they can do*. Their scope determines *which properties they can do it to*.

Scope shapes:

- **Tenant-wide** — applies to all properties in the org. Default for Owner and Admin.
- **Portfolio** — applies to a named portfolio (which is itself a collection of properties). Useful for regional managers ("Manager, scope = West Coast Portfolio") or for owners managing multiple sub-businesses under one Oyvoda account.
- **Property-specific** — applies to a named list of property codes. Useful for operators assigned to specific buildings or units, and for outsourced overnight staff who should only see and act on their assigned slice.

A user can have multiple scope entries (Manager of Portfolio A *and* Property X in Portfolio B, for example). Capabilities are evaluated against the *union* of scopes.

Critical rule: **portfolio-wide analytics requires tenant-wide or matching-portfolio scope.** An operator with property scope sees their assigned properties' analytics, period. They do not see portfolio aggregates that include unassigned properties. This prevents data leakage in outsourced staffing arrangements.

### Audit log

Every action that mutates state gets logged with:

- Acting user ID
- Acting user role at time of action
- Org ID
- Action type (e.g., `inquiry.approved`, `kb_entry.edited`, `user.invited`, `settings.changed`)
- Target ID (inquiry ID, KB entry ID, user ID, etc.)
- Before/after snapshot for state changes (where applicable and reasonable)
- IP address
- Timestamp

Retention: minimum 1 year, configurable per org with a hard floor of 90 days. (Compliance environments may want 7 years; that is a per-org config.)

The audit log is its own surface (Audit view in the dashboard, which already exists at the nav level). Managers can view audit entries within their scope. Admins can view all entries. Owners can export.

The audit log is also a critical *input* to intelligence: every approved draft, every rejected draft, every regenerated draft, every edited draft is operator feedback on AI quality. This data joins back into the intelligence model (Part 3).

### Verified repo reality

What already exists:

- `app/static/dashboard/js/sections/team.js` — Team management surface with members, portfolios, properties, and per-member scope tracking. The scope model has `scope_type` (`tenant` | `portfolio` | `property`) and per-scope capability flags (`can_assign`, `can_manage_vendors`, `can_manage_settings`).
- `api.team.list()` returns members with `role` and `activated` and `invitePending` fields.
- A `role` field is referenced (e.g., `member.role === 'manager'`).
- Portfolio concept exists as a coverage abstraction.
- Invite flow exists (`invitePending` state implies an invite system is wired).

What is unclear and needs investigation before build:

- Are these capabilities *enforced server-side* at every action endpoint, or are they descriptive metadata that the UI reads? (Critical: if the backend doesn't enforce, the UI hiding controls is security theater.)
- Are all five roles described above currently supported, or only some? The code references `manager` explicitly; other roles may not yet be modeled.
- Is there a complete audit log today, or only partial action logging?
- How are property assignments physically stored? (The `member_scopes` structure suggests a `member_scopes` table with rows per scope; this needs confirmation.)

What this design proposes adding (beyond what exists):

- Complete role enumeration (Owner / Admin / Manager / Operator / View-only) if not all are present
- Capability-based enforcement at every action endpoint (verify or build)
- Audit log with the structure described above (verify completeness or extend)
- Documented capability-to-role default map (formalize and persist)
- UI for managing roles, scopes, and capabilities (the Team surface already exists; it may need redesign to match the model)

Build sequencing for RBAC is in Part 4.

---

## Part 2: Inquiry intelligence data model

### What every inquiry should produce

Every guest inquiry — whether handled by AI alone, reviewed by an operator, or escalated — should produce three distinct kinds of data:

1. **Operational state** — what's the inquiry, what's the draft, what's the status, who acted on it. This is what powers the Pre-Booking surface and the action endpoints. Mostly exists today.
2. **Intelligence signals** — what was the guest asking about (topic), what was the intent, what was the AI's confidence, what knowledge gaps did it surface, what was the operator's verdict on the draft. This is what powers analytics, both operator-facing and network-level. Partially exists today, scattered across multiple fields.
3. **Outcome attribution** — did this inquiry become a booking? At what rate? Under what nightly rate? With what amenity profile? What topics were discussed during the inquiry sequence? This is what powers conversion intelligence and is the most strategic kind of data. **This is largely not captured today.**

The intelligence model centers on a structured `InquirySignals` shape that gets computed per inquiry and stored as a first-class entity, not as a JSON blob hidden inside an inquiry row.

### The `InquirySignals` shape (per-inquiry)

```
inquiry_id                  # FK to pre_booking_inquiries
org_id                      # tenant context
property_id                 # FK, nullable if unbound
property_lat                # denormalized for fast geographic queries
property_lng                # denormalized for fast geographic queries
market_id                   # FK to markets (which is itself geofence-defined)

# Topic and intent
topics                      # array of topic tags, see taxonomy below
primary_topic               # the dominant topic (most weighted)
intent                      # 'pricing' | 'availability' | 'amenity_question' | 'logistics' | 'policy' | 'group_special' | 'pet' | 'accessibility' | 'other'
asks                        # array of explicit asks (already exists today, formalize)

# AI quality signals
confidence                  # 0.0–1.0
confidence_tier             # 'high' | 'medium' | 'low' — derived for indexing
confidence_source           # 'model_certainty' | 'kb_completeness' | 'fallback_placeholder' | 'knowledge_gap_required'
draft_generated             # boolean — did the AI produce a draft at all
draft_held_reason           # null, or one of: 'kb_gap' | 'policy_flag' | 'low_confidence' | 'unbound_property' | 'guard_failed'
knowledge_gaps_triggered    # array of KB gap IDs

# Operator interaction
operator_action             # 'approved' | 'edited' | 'rejected' | 'regenerated' | 'no_action' | 'auto_sent'
operator_id                 # FK to users, null if auto_sent
operator_action_at          # timestamp
edit_distance               # if edited, character-level distance from AI draft to sent reply (proxy for AI quality)
regeneration_count          # how many regenerates before action

# Conversation context
turn_number                 # 1st message, 2nd message, etc. in the inquiry thread
thread_id                   # groups multi-turn inquiries
channel                     # 'airbnb' | 'vrbo' | 'booking' | 'direct_email' | 'sms' | 'web_form'
parser_used                 # kept for engineering, NOT surfaced to operator
source_provider             # the OTA or direct source

# Guest signals
guest_email_hash            # hashed for repeat detection without storing PII unnecessarily
guest_phone_hash            # same
is_repeat_guest             # boolean, derived from prior matches on either hash
prior_inquiries_count       # how many inquiries from this guest in last 365 days
guest_geography             # if derivable from email / phone / explicit data, country/region only

# Booking attribution (Part 3)
became_booking              # boolean, populated by booking-attribution job
booking_id                  # FK, populated when matched
inquiry_to_booking_days     # null until matched; calendar days from inquiry to booking
booking_total_value         # null until matched; total revenue
booking_nightly_rate        # null until matched
booking_nights              # null until matched
booking_lead_time_days      # null until matched; days from booking to check-in

# Time
inquiry_received_at         # when the inbound message arrived
inquiry_replied_at          # when our reply was sent (auto or human)
response_time_seconds       # derived

# Quality flags
flagged_for_review          # boolean — manually flagged
review_notes                # operator notes
```

This shape is the canonical record. It is computed per inquiry, stored in its own table (`inquiry_signals` or similar), and indexed for the queries that drive operator analytics and network intelligence.

### Topic taxonomy

The topic field is the most strategically valuable signal because it powers nearly every interesting analytic question. It must be:

- **Multi-label** — a single inquiry can be about multiple topics ("when do you check in, and is the pool heated?")
- **Hierarchical** — coarse topics (`amenity`) and fine topics (`amenity.pool.heating`)
- **Geographically extensible** — `amenity.beach_access` matters in 30A; `amenity.ski_in_out` matters in Park City. The taxonomy needs to grow per market without breaking the global model.
- **Versioned** — the taxonomy will evolve. Inquiries should record which version classified them so we can re-classify retroactively.

Initial top-level topic categories:

```
amenity            # pool, hot tub, beach, view, wifi, parking, kitchen, laundry, etc.
location           # distance to X, neighborhood, nearby restaurants/activities
logistics          # check-in/out, key handling, arrival logistics, late arrival
policy             # cancellation, pets, smoking, parties, additional guests
pricing            # rates, discounts, fees, deposits, taxes
availability       # specific dates, length of stay flexibility
group              # group size, occasion, event suitability, multi-room
accessibility      # mobility, sensory, dietary, family
duration           # extended stay, monthly rate, work-from-home
local              # restaurants, things to do, beach conditions, events
trust              # cleanliness, safety, owner contact, photos
other              # catch-all for unclassified
```

Each top-level has subcategories. The taxonomy lives in a config file (`config/inquiry_topic_taxonomy.yaml` or similar) so it can be extended per market without code changes. A classification model (rule-based initially, learned later) assigns topics with confidence scores.

### Per-property aggregates (operator-facing intelligence)

From the per-inquiry signal data, we compute property-level aggregates. These power the operator-facing intelligence surfaces.

**Friction fingerprint** — for each property, the topics that recur in inquiries, ranked by frequency, with annotations for which correlate with non-conversion:

```
property_id                 # FK
period_start                # rolling 30/60/90 day windows
period_end
inquiry_count
booking_count
conversion_rate
topic_frequency             # { topic: count } — what guests ask about
topic_conversion_lift       # { topic: conversion_rate_when_asked - baseline } — what topics correlate with booking
recurring_questions         # surfaced clusters: "5 inquiries asked about parking this month"
knowledge_gaps              # array of KB gap IDs recurring for this property
ai_confidence_distribution  # histogram
held_draft_rate             # % of inquiries held for review
operator_edit_rate          # % of approved drafts that were edited first
```

This is the surface behind "Beach Habitat 12 has had 5 inquiries about parking this month, none of which converted; consider adding parking detail to the listing." Specific. Operational. Actionable.

**Confidence health** — per property and per portfolio:

```
property_id (or null for portfolio-wide)
period_start
period_end
sent_drafts_count
sent_drafts_avg_confidence
sent_drafts_high_conf_pct   # % above 0.9
held_drafts_count
held_drafts_avg_confidence
held_drafts_correct_hold_pct  # % of held drafts that the operator subsequently approved (i.e., AI was right to hold)
                              # vs. held drafts the operator edited or sent as-is (i.e., AI over-cautious)
trend_vs_prior_period       # delta on each
```

This is what powers the Pre-Booking confidence health band. It's also a meaningful product-health metric for Oyvoda internally: a falling confidence trend across an operator's account is a churn risk indicator.

### Per-org aggregates (operator-facing)

```
org_id
period_start
period_end
inquiry_volume
inquiry_volume_by_channel
inquiry_volume_by_property
conversion_rate
revenue_attributed_to_inquiries
ai_autonomy_rate            # % of inquiries handled without operator intervention
operator_workload           # inquiries reviewed per operator
top_friction_properties     # top 5 properties by recurring-question count
top_recurring_topics        # network-rank topics across this operator's portfolio
knowledge_gap_recurrence    # recurring KB gaps with affected property count
```

This is what powers Today, Analytics, and the cross-portfolio operator view. For a 1000-unit operator, this is the morning briefing surface.

### Verified repo reality

What already exists:

- The `pre_booking_inquiries` table carries many of these fields in various forms: `confidence`, `confidence_label`, `confidence_source`, `confidence_note`, `policy_flags`, `policy_warnings`, `parser_source`, `route_outcome`, `fallback_reason`, `draft_source`, `asks`, `property_match_type`, `property_binding_candidates`, `prior_operator_commitments`.
- `OperationalInsightEngine` (`app/services/intelligence/insight_engine.py`) produces operator-facing insights of four types: `kb_suggestion`, `volume_alert`, `context_hint`, `service_risk`. This is the prototype for "distilled intelligence."
- `app/services/analytics/market_amenity_attribution.py` documents a hedonic pricing model for amenity-to-rate attribution.
- `app/services/analytics/market_intelligence.py` and `app/services/market_intelligence/market_intelligence_engine.py` exist and likely carry significant market-level aggregation logic.
- `app/services/knowledge/places_pipeline.py` provides geographic local-knowledge seeding for any operator market.

What this design proposes adding:

- A first-class `inquiry_signals` table (or equivalent) that pulls these scattered fields into a canonical, queryable shape. Not a rewrite — a normalization pass that makes downstream analytics tractable.
- A topic classification step in the inquiry processing pipeline (runs on inbound, populates `topics` array).
- Property-level rolling aggregates computed on a schedule (nightly job, probably) and stored in materialized form so the operator-facing intelligence surfaces are fast.
- Booking attribution: a job that matches inquiries to bookings (when a booking lands in the PMS, find the inquiry sequence that preceded it). This is the most strategically valuable missing piece.

---

## Part 3: Network intelligence and the compounding loop

### What "network intelligence" means

Operator-facing intelligence answers: "what's happening in *your* account?" Network intelligence answers: "what's happening across *all* accounts that I can learn from?"

Network intelligence is computed from de-identified per-org data, aggregated by market segment, property class, and other dimensions where similarity is meaningful. It powers:

1. **Better operator-facing recommendations.** "Properties like yours in markets like yours convert 12% better when pet policy is clear in the listing." This is value Oyvoda gives back to operators that they can't get from their data alone.
2. **Better AI handling.** The messaging layer's behavior changes based on network learning. If network data shows "pool heat questions correlate strongly with bookings in cold-season properties," the AI prioritizes answering those completely. If "ambiguous parking info reduces conversion by 8% in urban markets," the knowledge gap pipeline raises parking-info gaps as higher urgency.
3. **Oyvoda's commercial intelligence.** Sales: "operators with 50–200 units convert at X% on average; this prospect's existing solution does Y%." Product: "the top 3 recurring knowledge gaps across the network are A, B, C." Market expansion: "properties of class X in geography Y have these conversion drivers."
4. **Derivative products.** This is where the booking + nightly rate + market event data unlocks new revenue. See "Derivative products" below.

### Aggregation dimensions

Network intelligence aggregates per-inquiry data across:

- **Geography** — by market (defined as geofence/coordinate cluster). Comparable-market analysis ("beach markets in the Florida panhandle behave similarly to beach markets in the Outer Banks for these topics").
- **Property class** — by amenity profile, bedroom count, price tier, structure type. A 4-bedroom beachfront pool home in 30A is comparable to a 4-bedroom beachfront pool home in the Outer Banks for many purposes.
- **Market segment** — by season, event-driven vs. steady-demand, family vs. couple/group, etc.
- **Topic patterns** — clustering similar topic mixes to find inquiry archetypes that recur.

### The compounding loop

This is the architectural point that makes Oyvoda strategically different from a normal SaaS messaging product.

**Standard loop:** operators use product → product generates revenue → revenue funds product improvement → operators use better product.

**Oyvoda's compounding loop:** operators use product → product captures inquiry-to-outcome data → network intelligence improves → the AI gets sharper at handling future inquiries → operators' AI handles a higher autonomy rate → operators stay because the AI is now better than they could get elsewhere → more inquiries flow → network intelligence improves further.

The technical requirements for this loop to function:

1. **Every inquiry produces structured signals** (Part 2).
2. **Booking attribution is automatic** — when a booking lands, the system finds the inquiry sequence and records the outcome.
3. **De-identified aggregation respects privacy** — operator A's data never leaks to operator B's surfaces. Aggregates are computed across enough operators in similar segments that no individual operator is identifiable.
4. **Network learning flows back into messaging.** This is the part that requires deliberate architecture: the messaging layer needs hooks where network signals influence behavior. Examples:
   - The AI's drafting prompt includes "in similar markets, guests who ask about X are Y% more likely to book if the response includes Z."
   - The knowledge gap pipeline ranks gaps by network-observed conversion impact, not just frequency.
   - The confidence threshold for auto-send is informed by network-observed accuracy for that topic class in that property class.
5. **Operator-facing recommendations close the loop.** Operators see "fix this and conversion goes up by Y%" recommendations that are network-informed. The recommendation gets stronger as more data flows.

### Derivative products

Once the intelligence layer is real, several adjacent products become natural:

**Amenity scoring service.** "What is the marginal revenue value of adding a hot tub to a property of this class in this market?" This already has a prototype in `market_amenity_attribution.py`. Productizing it requires the inquiry-and-booking corpus from Part 2.

**New property analysis.** Operator considering acquiring a property: enter its details, see network-comparable conversion rates, expected ADR, friction risks. This is a top-of-funnel product for operators thinking about expansion, and a sales product for Oyvoda to pull operators into deeper subscription tiers.

**Knowledge gap value scoring.** "Your top 5 unaddressed knowledge gaps would lift conversion by X% if fixed, based on network observation." This makes the knowledge layer feel like a revenue product, not a chore.

**Pricing assist.** Not full revenue management (that's a separate complex product), but "your nightly rate is in the bottom quartile for properties with these amenities during this event week, given the inquiry topic mix." This is event-aware, amenity-aware, and inquiry-aware in a way standalone pricing tools aren't.

**Market expansion advisory.** "Operators of your size who expanded into geography X did Y. Here are the conversion drivers there." This is upsell for operators with growth ambition.

**Network benchmarks.** "Your AI autonomy rate is 73%. Top quartile in your segment is 84%. Here's what they do differently." Benchmarking is enterprise-style intelligence that operators pay for in other categories (Aaron's Analytics, AirDNA) and that Oyvoda can deliver natively.

None of these are commitments. They are the design space the foundation enables.

### Verified repo reality

What already exists at the network/market level:

- `MarketIntelligenceEngine` and related services exist. They aggregate something, though I have not fully audited what.
- `market_amenity_attribution.py` documents hedonic pricing methodology.
- `places_pipeline.py` lets the system seed local knowledge for any market geography.
- 30a.com event scraping and VisitSouthWalton scraping exist as concrete adapters in `market_scraper.py`.
- Market readiness assessment (`app/services/expansion/market_readiness.py`) suggests market-expansion thinking is already in the codebase.

What this design proposes adding:

- A `network_aggregates` data layer that computes geography × property-class × topic aggregates from de-identified inquiry signal data. New work.
- A clear privacy/anonymization layer that enforces "no operator sees another operator's data" and that aggregates are only surfaced above a minimum-N threshold to prevent re-identification.
- Hooks in the messaging layer where network signals influence: prompt construction, knowledge gap prioritization, confidence threshold tuning. This is integration work that touches existing services.
- A schedule/pipeline for refreshing network aggregates (daily, probably).
- An internal Oyvoda intelligence surface — not in the operator dashboard. A separate analytics view for Hunter (and eventually the Oyvoda team) to see network-level patterns. This is product strategy intelligence, not an operator product.

---

## Part 4: How the three layers interact

The three layers are not independent.

### RBAC × analytics

- A user with `can_view_property_analytics` and property scope `[Beach Habitat 12]` sees the friction fingerprint for that property, and nothing else.
- A user with `can_view_portfolio_analytics` and tenant-wide scope sees the org-wide aggregates.
- A user with `can_view_portfolio_analytics` and portfolio scope `[East Coast Portfolio]` sees aggregates for properties in that portfolio only.
- Network-aggregated intelligence (network averages, benchmarks) is visible to all users with at least `can_view_property_analytics`, because it's de-identified. But "your account vs. network" comparisons require `can_view_portfolio_analytics`.

### RBAC × messaging actions

- All four action endpoints (`approve`, `edit`, `reject`, `regenerate`) check the corresponding capability *and* verify the user's scope includes the inquiry's property.
- Auto-send (AI sends a draft without operator action) is a system action, attributed to the org with `operator_id = null` and `operator_action = 'auto_sent'`.

### RBAC × audit log

- All capability-gated actions are audit-logged.
- Audit visibility is itself capability-gated (`can_view_audit_log`) and scope-filtered.

### Analytics × network intelligence

- Per-org operator-facing analytics are computed from the org's own data only.
- Network intelligence is computed from de-identified aggregates across all orgs.
- Some surfaces blend both: "your conversion rate vs. network average for properties of your class." This is the most operationally valuable surface and the one that makes Oyvoda's data network effect visible to operators.

### All three × messaging layer

The messaging layer (where drafts are generated and replies are sent) is influenced by all three:

- **RBAC:** who can act on a draft, and whose actions get audit-logged
- **Per-org analytics:** the AI knows this operator's properties' friction patterns and adjusts response prioritization
- **Network intelligence:** the AI knows the network's learning about what response patterns work in this property class and market

---

## Part 5: Build sequencing

The design pass is one document; the build is many ships. Here is a proposed sequencing.

**Phase 1 — Foundation (next 4–6 weeks of work)**

1. **Investigate existing RBAC plumbing.** 1–2 days. Audit `team.js`, the backend team API, member-scope storage. Document what's enforced vs. descriptive. Identify the gap between current state and the model in Part 1.
2. **Inquiry signal normalization.** 1 week. Create the canonical `inquiry_signals` shape. Migrate scattered fields from `pre_booking_inquiries` into the new structure (or normalize in a view). No new capture; just make existing data queryable.
3. **Topic classification.** 1 week. Add a topic classifier to the inquiry processing pipeline. Start rule-based (regex + keyword lists from the taxonomy), upgrade to learned classification later. Versioned taxonomy file.
4. **Booking attribution job.** 1 week. When a booking lands in the PMS, find and link the inquiry sequence. This unlocks every conversion-correlated analytic in Part 2.
5. **Property-level aggregates.** 1 week. Nightly job that computes friction fingerprints and confidence health per property and per org. Stored materialized.

**Phase 2 — Operator-facing intelligence surfaces (concurrent with Phase 1)**

6. **Operations-view spike on Pre-Booking.** Confidence health band + one exception group. Replaces top of current Pre-Booking, demotes queue underneath. Uses real Lanier data. 1–2 days. (This is what we discussed before the architecture pass.)
7. **Pre-Booking intelligence band.** Once Phase 1 aggregates exist, the Pre-Booking analytics band becomes real: top topics, top inquiry-generating properties, conversion correlates. 1 week.
8. **Stage-specific intelligence on other lifecycle phases.** Pre-Arrival, In-Stay, Post-Stay each get their analytics band as they are redesigned. Per phase, 2–3 days.

**Phase 3 — RBAC enforcement build (when first multi-user operator signs up)**

9. **Capability check middleware.** Server-side enforcement at every action endpoint. Confirm or build. 1 week.
10. **Audit log.** Confirm completeness or extend. 3–5 days.
11. **Team management UI.** Likely already exists; verify it matches the model in Part 1 and redesign if needed. 1 week.
12. **Role-and-scope onboarding flow.** When an operator invites a user, the invite flow asks for role and property/portfolio scope. 2–3 days.

**Phase 4 — Network intelligence (after Phase 1 has 60+ days of data)**

13. **De-identified aggregation layer.** Geography × property-class × topic aggregates. New data layer. 1 week.
14. **Privacy and minimum-N enforcement.** Aggregates only surface where N is large enough to prevent re-identification. 2–3 days.
15. **Internal Oyvoda intelligence surface.** Hunter-facing analytics for network patterns. 1 week.
16. **Operator-facing network benchmarks.** "Your account vs. network in your segment" surfaces. 1 week.

**Phase 5 — Network feedback into messaging**

17. **Prompt augmentation with network signals.** AI drafting prompt includes network-informed guidance. 1 week.
18. **Knowledge gap prioritization by network impact.** Recurring gaps ranked by network-observed conversion lift. 3–5 days.
19. **Confidence threshold tuning informed by network.** Per-topic, per-class accuracy from network data informs auto-send thresholds. 1 week.

**Phase 6 — Derivative products (commercial opportunity, sequenced by demand)**

20. Amenity scoring service. Productize `market_amenity_attribution.py`.
21. New property analysis.
22. Knowledge gap value scoring.
23. Pricing assist.
24. Market expansion advisory.
25. Network benchmarks as a subscription tier.

Phases 1 and 2 can run concurrently and are the immediate work. Phase 3 is needed before the second multi-user operator signs up. Phase 4 is needed before network claims can be made externally. Phases 5 and 6 are the strategic moat and commercial expansion.

---

## Part 6: What this document doesn't commit us to

This is a design document. It commits to a model, not to specific code, schemas, or timelines.

Explicit non-commitments:

- **Schema details.** Tables, columns, and indexes will be designed during build. The shapes in Part 2 are conceptual, not literal DDL.
- **Specific aggregation algorithms.** Topic classification may start as rules and become learned. Friction fingerprints may use simple frequency counts before any clustering. Hedonic models will evolve.
- **Exact UI surfaces.** Part 5's "operations-view spike" describes what to build; how it looks is a separate concern handled by the next ship brief.
- **Specific RBAC enforcement order.** Phase 3 sequencing assumes "needed when first multi-user operator signs up." It may need to move earlier if the operator pipeline requires it.
- **Productization of derivative products.** Phase 6 is the design space, not a roadmap.

What we do commit to:

- **Three foundations get designed together, not serially.** RBAC, inquiry intelligence, and network intelligence are designed in this document because they interact and because building any one of them without the others bakes in painful assumptions.
- **Every inquiry produces structured signals.** This is the single most strategically important commitment in the document. Every subsequent intelligence claim depends on it.
- **Geographic agnosticism is non-negotiable.** No future ship hard-codes 30A-specific landmarks, regions, or assumptions. Coordinates and configurable taxonomies are the only acceptable approach.
- **Operator-facing intelligence is distilled, not raw.** Operators see actionable patterns, not technical exhaust. The parser source, route outcome, and other internal signals do not appear in operator UI.
- **The compounding loop is the moat.** Messaging is the entry, intelligence is the compounding layer, and the architectural decisions that enable network learning to flow back into the messaging layer are first-class concerns, not afterthoughts.

---

## Open questions

These need to be resolved before or during the Phase 1 investigation. They are not blockers for the design but they are decisions that affect execution.

1. **Is the existing `member_scopes` capability flag system actually enforced server-side?** Determines how much Phase 3 work is "new" vs. "fill the gaps."
2. **Does the existing PMS integration (Escapia ENET / Guesty / Track) expose booking events in a way that supports booking attribution?** If not, attribution requires either a polling layer or webhook plumbing. Sizing depends on this.
3. **What's the right granularity for topic taxonomy v1?** Top-level only, or top-level + first-level subcategories? Tradeoff: granularity gives more signal but more classification error early on. Lean toward starting coarse and refining.
4. **Where does network intelligence physically run?** Same Postgres as operator data, with strict de-identification at query time? Or a separate analytics warehouse? Likely starts as same-Postgres and migrates when scale demands.
5. **What's the minimum-N for surfacing network aggregates?** 30? 100? Too low and re-identification risk grows; too high and aggregates aren't useful early. Lean toward 30 with manual review of edge cases.
6. **How do we handle topic taxonomy evolution?** Versioned, with old inquiries classified by their version-at-time? Or retroactively re-classified on taxonomy updates? Probably both — version stamps + a backfill job for major taxonomy changes.

---

*End of document.*
