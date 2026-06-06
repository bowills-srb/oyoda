# Verified Foundation Audit

**Status:** Verified repo-reality note  
**Date:** May 19, 2026  
**Purpose:** Confirm what already exists for access control, booking attribution, and inquiry intelligence before Phase 1 build work begins.

---

## Summary

The foundation is more mature than it looked at first glance, but the two most important conclusions are:

1. **Booking persistence is real; inquiry-to-booking attribution is not yet a first-class linkage.**  
   Oyvoda already ingests PMS listings and bookings into canonical tables and creates guest sessions from confirmed bookings. What does **not** yet appear to exist is a durable attribution layer that links a pre-booking inquiry sequence to a later booking outcome for conversion analysis.

2. **Scope metadata is real; server-side capability enforcement is partial.**  
   Property/portfolio/tenant scoping exists and is used on some read paths. Capability enforcement also exists in parts of the operator dashboard API. But at least one operationally important action path — pre-booking draft approval — still checks only tenant/company access, not scoped capability.

That means the architecture direction in `INTELLIGENCE_AND_ACCESS_FOUNDATION.md` is still right, but Phase 1 needs to be framed as **normalize + connect + enforce**, not “build everything from scratch.”

---

## 1. Booking attribution audit

### What already exists

#### 1.1 PMS bookings are already ingested into durable tables

The PMS ingest worker is real and production-shaped:

- `app/services/connectors/pms_ingest_worker.py`

It explicitly:

1. loads Escapia credentials
2. fetches listings
3. upserts listings into `pms_listings`
4. fetches bookings
5. upserts bookings into `pms_bookings`
6. creates guest sessions for confirmed bookings

The worker comments and SQL migration block confirm the canonical tables:

- `pms_listings`
- `pms_bookings`
- `operator_sync_log`

This is not hypothetical infrastructure. The booking layer exists.

#### 1.2 Escapia booking access exists in two forms

Two separate Escapia paths are present:

- `app/services/connectors/escapia_connector.py`
  - REST-style connector
  - supports `fetch_listings()`, `fetch_bookings()`, and webhook registration
- `app/services/connectors/escapia_enet.py`
  - ENET SOAP connector
  - can read reservation/inquiry records directly via `UnitRead`

This matters because it means the codebase is not boxed into one fragile access path. There is already both:

- a booking-sync path
- a deeper SOAP reservation/inquiry lookup path

#### 1.3 Guest sessions are already created from booking data

The PMS ingest worker calls `_create_rich_concierge_sessions(...)`, which creates `concierge_guest_sessions` rows from confirmed bookings:

- `app/services/connectors/pms_ingest_worker.py`

So the system already knows how to go:

`PMS booking -> guest session`

That is valuable because post-booking lifecycle intelligence already has a durable anchor.

### What does **not** yet appear to exist

#### 1.4 No verified durable join from pre-booking inquiries to bookings

Search across the repo did **not** reveal an existing first-class attribution layer that links:

- `pre_booking_inquiries`
- to `pms_bookings`
- or to `concierge_guest_sessions`

for conversion attribution.

There are many booking-context and reservation-routing paths, but those are not the same thing as “this inquiry chain later became this booking.”

Current state appears to be:

- pre-booking inquiries are stored
- PMS bookings are stored
- guest sessions are created from bookings
- but the conversion linkage between inquiry and booking is not yet modeled as its own durable entity

### Conclusion

**Booking ingestion is already real. Booking attribution is still the biggest Phase 1 gap.**

This is the most important audit finding because it confirms the architecture doc’s emphasis:

- we are not starting from nothing
- but the specific conversion join that unlocks intelligence still needs to be designed and built

### Phase 1 implication

Phase 1 should include a dedicated attribution design/build step:

- define what counts as a conversion linkage
- decide matching strategies in order of trust:
  - PMS reservation id
  - guest email / phone
  - property + dates + name
  - OTA reservation identifiers when PMS id absent
- store the match as a first-class attribution record, not an inferred transient

---

## 2. Access control audit

### What already exists

#### 2.1 Scope model is real

The scope model in `team.js` is backed by real service code, not just aspirational UI:

- `app/services/operator/scope_service.py`

It supports:

- `scope_type`:
  - `tenant`
  - `portfolio`
  - `property`
- visibility derivation via `visible_property_codes`
- capability flags on scopes:
  - `can_assign`
  - `can_manage_vendors`
  - `can_manage_settings`

It also supports portfolio expansion through `operator_portfolio_properties`.

This is genuine RBAC/scoping plumbing, not mock data.

#### 2.2 Scope is enforced on at least some read paths

The pre-booking read model already filters results by visible property scope:

- `app/api/v1/endpoints/operator_prebooking.py`

Specifically:

- it loads `visible_property_codes` from `scope_service`
- it applies `_row_visible_for_scope(...)`

So scoped data visibility is not purely cosmetic.

#### 2.3 Capability enforcement exists in the modern operator dashboard API

`operator_dashboard_api.py` contains a real helper:

- `_enforce_scope_permission(...)`

It rejects unauthorized requests for:

- `assign`
- `manage_vendors`
- `manage_settings`

And this helper is used by multiple vendor/settings/assignment endpoints in that file.

This means server-side capability enforcement is already partly real.

### What is still missing / inconsistent

#### 2.4 Pre-booking draft approval path is not capability-enforced

The approval endpoint used for pre-booking drafts is:

- `app/api/v1/endpoints/operator_onboarding.py`
- `POST /inquiries/{draft_id}/approve`

That path checks:

- authentication
- company/operator access via `_require_company_access(...)`

It does **not** check:

- role capability
- property scope
- `can_assign`
- any “can approve drafts” equivalent permission

So the current state is:

- scoped visibility exists
- some mutation endpoints enforce capabilities
- but at least one operationally important pre-booking action does not

This is exactly the kind of gap the design doc anticipated.

### Conclusion

**RBAC is not greenfield. It is partially implemented and partially enforced.**

That changes the Phase 3 framing:

- not “invent RBAC”
- but “audit every mutation path, centralize capability enforcement, and close the gaps”

### Phase 1 / Phase 3 implication

The first concrete enforcement audit target should be pre-booking actions:

- approve
- edit
- reject
- regenerate

Those should move behind the same scoped capability checks as the newer operator dashboard actions.

---

## 3. Inquiry intelligence audit

### What already exists

#### 3.1 Inquiry-level signal fields already exist in durable pre-booking data

Current pre-booking rows and feed payloads already carry many useful provisional signals:

- confidence
- confidence label / note
- parser source
- route outcome
- fallback reason
- property binding candidates
- policy flags / warnings
- asks
- intent
- draft source

These are already consumed by the Ship D UI.

#### 3.2 Booking-context lookup exists, but is transitional

The booking data provider is explicitly described as transitional:

- `app/services/connectors/adapter_backed_booking_data_provider.py`

It can reliably provide:

- property summary
- partial rate summary

It does **not** yet provide:

- authoritative availability
- a clean attribution model

That is a useful honesty boundary: some intelligence inputs exist, but not yet as the final contract.

### What still needs to be normalized

The design doc’s proposed `InquirySignals` shape is still necessary because the current fields are:

- scattered
- UI-oriented
- not clearly versioned
- not obviously designed as a durable analytics substrate

### Conclusion

The spike can safely use current pre-booking fields.  
Phase 1 still needs to normalize them into a first-class inquiry-intelligence model.

---

## 4. What Phase 1 actually needs to build

Given the verified repo state, Phase 1 is best understood as these concrete jobs:

### 4.1 Build conversion attribution as a first-class linkage

This is the highest-priority missing layer.

Needed:

- durable inquiry-to-booking linkage model
- trust-ranked matching strategies
- attribution timestamps and confidence
- operator-safe aggregation from those linkages

### 4.2 Normalize inquiry signals into a durable shape

Needed:

- versioned `InquirySignals`
- topic taxonomy storage
- property/org aggregate derivations
- clean separation of operator-facing intelligence vs internal diagnostics

### 4.3 Audit and unify server-side capability enforcement

Needed:

- trace all mutation endpoints
- identify which already use scoped capability checks
- move legacy pre-booking actions under the same enforcement model

### 4.4 Do **not** rebuild what already exists

Already real enough to preserve and extend:

- property/portfolio scope model
- vendor/settings/assignment capability checks in dashboard API
- PMS listing sync
- PMS booking sync
- guest-session creation from bookings

---

## 5. Recommended immediate next steps

1. **Keep the operations-view spike moving in parallel.**
   - It can use current pre-booking fields.
   - It does not need the normalized intelligence layer finished first.

2. **Treat attribution as the longest pole in Phase 1.**
   - Design this before implementing broad “conversion-correlated topic” analytics.

3. **Pull pre-booking action enforcement into the RBAC audit early.**
   - This is the clearest current server-side gap.

4. **Write Phase 1 as a normalization/connect/enforce ship, not a blank-slate platform build.**

---

## Bottom line

The repository already contains meaningful foundations for both intelligence and access:

- real PMS booking ingestion
- real guest-session creation
- real scope metadata
- real scoped read filtering
- real capability enforcement on some operator actions

But the two decisive gaps remain exactly where the design doc predicted:

- **inquiry-to-booking attribution is not yet a first-class model**
- **pre-booking action enforcement is not yet consistently capability-scoped**

That means the architecture direction is correct, and the next work should proceed as:

**commit -> audit -> spike**

with the audit now sharpened to:

**connect bookings to inquiries, and make access enforcement consistent.**
