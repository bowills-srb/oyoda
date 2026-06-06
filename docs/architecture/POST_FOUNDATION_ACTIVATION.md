## Post-Foundation Activation

Date: 2026-05-14
Status: Strategic companion to the foundation rebuild docs

These features were partially identified during Phase 2 disposition discussion.
They are not Phase 2 execution work, but understanding their current state
matters for prioritizing what to activate after foundation completes.

## Core Reframing

The gap is not "we need to build everything from scratch."

The better framing is:
- many meaningful features already have partial implementations
- those implementations are disconnected, drifted, or blocked by schema and
  identity ambiguity
- foundation rebuild makes them safe to activate

That changes the roadmap from greenfield invention to reconnection and
operationalization.

## 1. Preferred Vendors

The vendor system already supports two distinct vendor classes that flow
through the same data model.

### Class A: Guest-facing concierge vendors

Used by Coral during guest conversations.

Examples:
- beach chair rentals
- umbrella rentals
- crib rentals
- baby gear rentals
- ski rentals
- boat rentals
- paddleboard rentals
- charter fishing
- helicopter tours
- restaurants
- activities and tours

Trigger:
- guest asks for a recommendation in scope of the vendor's category and the
  operator's geographic area

### Class B: Operator-facing maintenance and ops vendors

Used when operational issues arise.

Examples:
- HVAC repair
- appliance repair
- plumbers
- electricians
- yard care
- pool service
- cleaning services
- photographers
- locksmiths

Trigger:
- guest reports a system failure
- or operator initiates a maintenance request

Routing factors:
- issue type
- property system metadata
- warranty status
- manufacturer
- service area
- operator preference order

### Verified implementation

- UI: [vendors.js](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard/js/sections/vendors.js)
- backend: [vendor_intelligence_service.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/operator/vendor_intelligence_service.py)
- email parsing: [vendor_email_parsers.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/vendor_email_parsers.py)

The tag system already supports both patterns through:
- manufacturer tags
- warranty provider tags
- supported issue tags
- supported system tags
- service area tags
- category tags for guest-facing recommendations

### Critical Constraint

Vendor system absence must not break the rest of the platform.

If an operator has not configured vendors:
- inbox parsing still works
- pre-booking still works
- guest messaging still works
- Coral gives generic responses instead of operator-specific vendor references

Vendor activation is value-add, not critical-path. Architecture should keep it
that way.

### Gap to operational

- underlying tables may or may not be present in production depending on the
  final reconciliation path
- messaging brain does not yet consult the vendor list when context matches
- referral analytics for guest-facing vendors is not built
- warranty-aware dispatch logic for maintenance vendors is not built

### Activation work

- verify vendor tables and supporting schema
- test the vendor UI end-to-end
- wire the brain to consult the correct vendor subset based on context
- build referral analytics for guest-facing vendors
- build warranty-aware dispatch logic for maintenance vendors

## 2. Proactive Guest Notifications

Delivery-side scaffolding already exists.

### Verified implementation

- notification orchestration:
  [notification_service.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/notification_service.py)
- proactive journey logic:
  [stay_proactive_runtime.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/operator/stay_proactive_runtime.py)
  and [stay_journey_service.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/operator/stay_journey_service.py)
- SMS delivery:
  [sms_service.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/notifications/sms_service.py)
- email delivery:
  SendGrid-backed messaging paths

### Gap to operational

- no weather service
- no NOAA integration
- no beach flag feeds
- no signal-to-affected-guest wiring
- no operator opt-in controls per category
- no volume controls for cascade events

### Activation work

- build weather and NOAA signal ingestion
- add beach flag or region-specific safety feeds
- wire signal -> affected guest identification -> notification trigger
- add operator controls per category
- add rate limiting and anti-spam controls

Expected effort:
- roughly 1-2 weeks of focused work after foundation, assuming the delivery
  layer behaves cleanly

## 3. Upsells

Upsells are a real product surface, not a speculative add-on.

### What it is

Proactive scanning during guest stays for revenue-generating opportunities.

### Trigger examples

- mid-stay scan for adjacent-night availability -> offer extension
- pre-checkout scan for amenity upsells -> pool heat, late checkout, beach gear
- booking lead-time discount logic -> suggest add-ons

### Inputs

- booking data
- adjacent-date availability from PMS or scraped calendars
- property amenities
- configured upsell rates from `operator_policies.upsell_rates`
- guest behavior signals

### Outputs

- personalized upsell message
- delivery through the existing notification path
- operator approval workflow, or auto-send per operator policy

### Architecture pattern

This uses the same pattern as proactive notifications:
- signal
- identify guest
- compose
- send

Different signal type, same delivery infrastructure.

### Activation work

- wire a scheduled upsell scanner
- build amenity upsell rules from `operator_policies.upsell_rates`
- build adjacent-night availability checks
- wire to the existing notification service
- add operator controls for upsell categories and approvals

Expected effort:
- roughly 1 week of focused work post-foundation

## 4. Operator Signup Geographic Intelligence

The market architecture is real enough to activate after foundation work.

### Verified implementation

- `market_registry`
- `operator_market_links`
- market scraping services
- event scraping services

### Gap to operational

- signup does not capture geography cleanly enough
- no automatic signup -> market match -> link -> acquisition path
- Google Places integration is not built

### Activation work

- wire geography capture into onboarding consolidation
- add Google Places service module
- build matching logic and background job flow
- trigger per-operator data acquisition and refresh scheduling

## 5. Guidebook and Property Data Gathering

The work is not "build a guidebook system."

The work is gathering from sources operators already use.

### Existing source types

- operator public website
- Airbnb and Vrbo listings
- PMS data
- existing guidebook services such as Breezeway or Hostfully
- PDFs, welcome letters, FAQs
- property photos and floor plans

### Gathering approaches

#### A. Operator provides URLs, system scrapes with permission

Pros:
- highest wow factor
- lowest operator effort

Cons:
- scraping is fragile
- sites change
- some sites block scrapers

#### B. Operator uploads documents

Pros:
- reliable
- operator controls what is shared

Cons:
- requires operator effort
- less magical

#### C. MCP-style downloadable tool

Pros:
- could gather from local files without manual export

Cons:
- high trust barrier
- cross-OS maintenance burden
- premature before validating the need

### Recommendation

Start with A plus B after foundation.

Validate with the first few operators:
- if scraping covers enough, double down there
- if scraping misses too much, strengthen uploads and extraction

Do not commit to the downloadable-tool path before validating demand.

### Beach Habitats as template

Beach Habitats is the shape of a completed onboarding:
- 45+ property records
- canonical refs
- guidebook linkage
- policies
- vendor lists
- market linkage

New operators should be gathered toward that same shape from their existing
sources.

### Expected effort

- scraping framework and source extractors: 1-2 weeks
- document upload plus vision extraction: 1-2 weeks
- operator review and confirmation UI: 1 week

Total:
- roughly 3-5 weeks of focused work post-foundation, likely across parallel
  tracks

## 6. The Onboarding Template Thesis

Beach Habitats is best understood as the template for what a completed
operator onboarding produces.

That output shape includes:
- property records
- canonical property refs
- operator policies
- vendor lists across both vendor classes
- market linkage
- guidebook and property knowledge

### Minimum operator inputs

- company info
- Gmail or Microsoft connection
- list of property addresses and codes
- PMS choice, if any
- region or zip codes
- URLs to public source pages

### System behavior

The system gathers from the operator's existing data sources, then fills in:
- `properties`
- `canonical_property_refs`
- `operator_policies`
- property-specific knowledge
- market linkage and acquired market data

The operator reviews and confirms before going live.

This is the operational basis for the "24-48 hour onboarding" promise.

## Recommended Activation Order

After foundation rebuild completes:

1. activate `operator_policies`
2. activate vendors across both classes
3. wire signup geographic intelligence
4. activate upsells
5. activate property data gathering
6. activate proactive signal ingestion

Each step is meaningfully smaller than the foundation work because scaffolding
already exists.

## Why This Matters

The path from current state to "first new operator live" is shorter than the
"rebuild from scratch" framing implied.

Foundation work provides:
- schema integrity
- migration authority
- tenant normalization groundwork
- property identity integrity

Activation work then reconnects partial implementations onto that base.

Reasonable planning frame:
- 3-6 weeks of foundation work
- 4-8 weeks of activation work

That puts "first new operator live and working end-to-end" in the
7-14 week range, assuming discipline holds and the scale acceptance criteria
continue to gate the work.
