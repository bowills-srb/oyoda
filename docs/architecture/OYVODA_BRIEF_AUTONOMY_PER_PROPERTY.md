# Brief — Per-Property / Per-Domain Autonomy Computation Layer (autonomy capstone)

For Claude Code. Build-ready. Read OYVODA_BRIEF_AUTONOMY_FORMULA_REDESIGN.md (the validated
formula, 0d7d14f) and the DOMAIN-AUTONOMY section of OYVODA_MASTER_ROADMAP.md first. This is
the LAST autonomy backend brick — it propagates the validated portfolio formula down to
per-property/per-domain, and it is the thing the Home hero and Property Readiness A-swap
consume. Build it on the validated formula and the fixed resolver — NOT on assumptions.

## Why this is safe to build now (it wasn't an hour ago)
The portfolio formula is validated: scale-invariant, responsive (0.8063 @ 34 gaps / 45 managed, 0.725 @
100), 6/6 hypothetical-profile tests pass. The gap attribution bug is fixed (canonical_property_refs
resolver). So per-property propagation now builds on math that MEASURES something and inputs
that ATTRIBUTE correctly. Do not re-derive the formula here — reuse compute logic from
autonomy_score_service.

## All three inputs exist (verified) — but each arrives in a different identifier shape
Everything keys to `properties.id`. The shared canonical_property_refs resolver (the one fixed
in 0d7d14f) is the bridge. Per property:
- **KB coverage**: concierge_scoped_knowledge. CRITICAL MODEL: a property's coverage =
  ALL `scope_type='tenant'` entries (shared baseline, every property inherits them) PLUS that
  property's own `scope_type='property'` entries (scope_target_id = properties.id). Do NOT count
  only property-scoped entries — a property with zero property-specific entries is still covered
  by the tenant baseline. Counting isolated would make every property look sparse and tank scores.
- **Attributed gaps**: concierge_knowledge_gaps WHERE property_id = properties.id, resolved=false,
  distinct/genuine (reuse _count_distinct_genuine_attributed_gaps logic, but per property_id).
- **Traffic**: pre_booking_inquiries COUNT per property. NOTE: keys on company_id (= tenant_id
  value) and stores property_external_id (NOT property_id) — resolve via the same
  canonical_property_refs path to properties.id before joining.

## SIGNAL-SUFFICIENCY GATE — the first thing per property (the honesty core)
Before computing ANY score for a property, decide if there's enough signal:
- **No traffic** (zero inquiries/sessions for this property) → emit "Insufficient Signal" (band
  word, NO number). Do NOT fabricate a score for a property that hasn't been used. This is the
  per-property version of the no-data honesty rule (same as escalation pristine-vs-no-data, same
  as the Home hero placeholder, same as Property Readiness coverage labels). Most of the 50
  properties may land here given sparse historical attribution — that is EXPECTED and HONEST.
- **Has traffic** → compute the per-property Inquiry score with the validated formula.
Use inquiry count as the traffic discriminator (and/or session count if cleaner). A property with
traffic + few gaps scores HIGH; traffic + many gaps scores LOW; no traffic = insufficient signal.

## Per-property computation (only for properties that pass the gate)
- **Inquiry domain — COMPUTED per property** using the validated readiness/escalation blend
  applied to that property's inputs (inherited+own KB, its attributed gaps, its escalation
  pressure if derivable per property; if escalation isn't cleanly per-property yet, use the
  portfolio escalation signal as a shared input and note it). Behavior stays NEUTRAL (decoupled
  from learning, unchanged).
- **Guest Ops / Maintenance / Turnover — band-word stubs per property** (Developing / Emerging /
  Emerging), same as portfolio. NOT computed numbers. These light up in later domain bricks.
- Map the per-property Inquiry score to a band via the existing _inquiry_band cutoffs.

## Roll-up + reconciliation
- Roll per-property Inquiry scores up to a portfolio Inquiry score. It should RECONCILE with the
  current portfolio number (~0.8063 as of the predicate sweep 8c0796f; readiness ~0.84) — if it
  diverges wildly, the per-property decomposition has a bug (likely the tenant-KB-inheritance
  modeling). Report both and confirm they're consistent. (Note: 0.8063 is the post-managed-set
  number on 45 properties; an earlier draft said 0.8137 which was the pre-sweep 50-property value.)
- Properties at "insufficient signal" are EXCLUDED from the roll-up average (don't let no-data
  properties drag the portfolio down OR inflate it) — report how many were excluded.

## Storage
- The operator_autonomy_snapshots schema is already domain-keyed (domain_bands jsonb). Extend the
  stored structure to include per-property breakdown — either a new per-property column/table
  (operator_property_autonomy or a per_property jsonb on the snapshot) keyed by property_id +
  snapshot_date, OR nested in domain_bands. Prefer a dedicated per-property table if the volume
  (50 properties × daily) warrants queryability for the Property Readiness surface. Append-only by
  date, same as the portfolio snapshot. If a new table: reversible Alembic migration, next revision
  after 090, tenant_id comment re the canonical-UUID invariant.

## Frontend consumers (wire AFTER the backend computes + verifies)
These are the payoff — but only wire them once the per-property data is computed and reconciled:
- **Home Portfolio Autonomy hero**: swap the placeholder for the real portfolio_score (~0.8063,
  post-predicate-sweep) + domain bands. The hero slot was built for exactly this.
- **Property Readiness A-swap**: re-key readiness.ts from coverage-readiness labels (High Readiness
  / Needs Coverage / Readiness Blocked) toward autonomy verdicts driven by the per-property Inquiry
  score — the one-file swap built in bee2fd3. CAUTION: keep verdicts honest — a property at
  "Insufficient Signal" must show that, not a confident verdict. And remember the band can move
  when behavior goes live (learning), so don't over-commit the labels.
These can be a SEPARATE frontend commit after the backend brick lands and verifies.

## ANTI-OVERFITTING + honesty (unchanged discipline)
- n=1 still holds: validate per-property logic against hypothetical property profiles (well-covered
  w/ traffic → high; sparse w/ traffic + many gaps → low; no traffic → insufficient signal), not
  just Beach Habitats' specific properties.
- Insufficient-signal is the DEFAULT for no-traffic properties, not an edge case. Expect many.
- Band words for immature domains, never fabricated numbers. Same rule, now per property.

## Scope guards
- Reuse the validated formula; do NOT re-tune it here.
- Behavior stays neutral (learning decoupling intact).
- Backend computation + storage FIRST, verified + reconciled, THEN the frontend consumers (separate
  commit). Don't wire the hero against unverified per-property data.
- Resolve all three inputs to properties.id via canonical_property_refs before joining.

## Done when
- Per-property computation: each property either gets a computed Inquiry score+band (if traffic) or
  "Insufficient Signal" (if not). Tenant-KB inheritance modeled correctly.
- Other domains band-stubbed per property.
- Roll-up reconciles with the portfolio score (~0.8063, post-predicate-sweep on 45 managed properties); excluded-insufficient count reported.
- Per-property data stored (table or jsonb), append-only by date; migration reversible if new table.
- Hypothetical per-property profile tests pass (high / low / insufficient-signal).
- THEN (separate commit): Home hero shows real score; Property Readiness A-swap keyed to per-property
  verdicts with insufficient-signal honestly shown.
- Commit SHA(s). Roadmap updated: autonomy backend COMPLETE, frontend consumers lit, learning redesign
  remains the open founder-judgment fork (would make behavior real and could move bands).
