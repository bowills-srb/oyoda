# Brief — Managed-Property Predicate Sweep (is_active consistency, system-wide)

For Claude Code. Build-ready. Read OYVODA_MASTER_ROADMAP.md (CROSS-CUTTING + DOMAIN-AUTONOMY)
first. This fixes a DEFINITIONAL bug: the `properties` table contains both managed and
unmanaged rows, and property-counting paths inconsistently filter them. This is a CONSISTENCY
sweep of a predicate the repo ALREADY uses in places — not a new concept.

## The finding (verified on live tenant)
`properties.is_active` is a first-class managed/unmanaged signal. Beach Habitats
(e07980b2-a990-4b24-91d1-c8cb71ab70e1): 45 rows is_active=true (managed), 5 is_active=false
(stale, no longer managed: 102-1785, 203WW, 236SC, 68RF, 75ECRAB). The repo ALREADY uses
`COALESCE(is_active, TRUE) = TRUE` in several property queries — but not all counting/autonomy
paths. So this is finishing a consistent application, not inventing logic.

## The predicate (use this EXACT form)
`COALESCE(properties.is_active, TRUE) = TRUE`
- COALESCE matters: NULL is_active → treated as MANAGED (presumed active unless explicitly
  deactivated). Bare `is_active = TRUE` would wrongly drop NULL rows. Match the repo's existing
  COALESCE form.

## Orthogonality — DO NOT conflate managed-status with signal/traffic (critical)
Managed-vs-unmanaged = is_active (a management fact, set deliberately).
Has-signal-vs-insufficient = traffic (an activity fact, derived).
These are INDEPENDENT and must stay so. A newly-onboarded property is is_active=true with zero
traffic → MANAGED + insufficient-signal (counted in the denominator, shown as insufficient-signal
in the per-property layer). NEVER use traffic as a managed-predicate, and never let the is_active
filter and the per-property insufficient-signal gate collide. is_active decides "is it in the set";
traffic decides "can we score it."

## The sweep — find every property-counting/listing path, decide per consumer
Do NOT blind find-replace. For EACH place that counts or lists properties, decide whether
"currently managed" applies, and apply the predicate where it does:

APPLY the predicate (operator-facing "current portfolio" semantics):
- **Autonomy portfolio denominator** — autonomy_score_service.py property count
  (`SELECT COUNT(*) FROM properties WHERE tenant_id=...`) → add the COALESCE(is_active) filter.
  This corrects the readiness denominator from 50→45 (250→225 target). Score will rise slightly
  (currently conservative).
- **Per-property computation set** (the capstone layer, when built) — iterate only managed
  properties, or the insufficient-signal count will overstate by counting stale rows.
- **dashboard-summary / Home property count** — the operator's portfolio total should be 45, not 50.
- **Property Readiness list + counts** — must not show the 5 stale properties as things needing
  coverage. Filter the list AND the metric-strip totals.
- Any other operator-facing property total (search for COUNT/list against `properties`).

DO NOT apply (these intentionally see all rows):
- Admin/audit/debug views that exist to show ALL properties including inactive.
- Migrations / backfills / data-integrity tooling that must touch every row.
- Historical autonomy snapshots ALREADY computed on 50 — do NOT retroactively rewrite stored
  history; only forward computation uses the corrected set. (The trend will have a tiny
  discontinuity when the denominator changes — that's honest; note it, don't paper over it.)
- The gap backfill/quarantine tooling (operates on data regardless of managed status).

For each consumer touched, note in the commit WHY the predicate applies (or a deliberate skip).

## Find-the-consumers method
Grep for property counting/listing: `FROM properties`, `COUNT(*) ... properties`, property
list endpoints, the dashboard-summary service, Property Readiness route's data source,
autonomy_score_service. Build the list, classify each apply/skip, then patch the applies.

## Doc sequencing (do this LAST, after code)
Only AFTER the code uses the predicate: update the roadmap CROSS-CUTTING note back to
"45 managed properties (50 raw rows; 5 is_active=false)" and the readiness denominator to
45×5=225. Code first, doc follows — so doc and code agree. Until the code is patched, the doc
should say 50 (matching current code). Do not flip the doc ahead of the code.

## Verification
- Autonomy snapshot re-run for Beach Habitats: property count now 45, readiness denominator 225,
  score rises slightly from 0.8137 (report new value — it's the corrected, less-conservative score).
- dashboard-summary / Home: property total reads 45.
- Property Readiness: the 5 stale properties (102-1785, 203WW, 236SC, 68RF, 75ECRAB) no longer
  appear in the list or counts.
- Confirm a hypothetical is_active=true zero-traffic property would still be COUNTED (managed) and
  marked insufficient-signal (not excluded) — the orthogonality holds.

## Scope guards
- Predicate only; no schema change (is_active already exists).
- Use COALESCE(is_active, TRUE)=TRUE consistently; match the repo's existing form.
- Do NOT retroactively rewrite stored historical snapshots.
- Do NOT use traffic as a managed signal anywhere.
- System-wide: this affects autonomy, dashboard-summary, Property Readiness, Knowledge Health —
  not autonomy-only. Note system-wide impact in the commit.

## Done when
- COALESCE(is_active, TRUE)=TRUE applied to all operator-facing property-counting/listing paths;
  admin/migration/history paths deliberately skipped (each decision noted).
- Beach Habitats: autonomy denominator 45, Home total 45, Property Readiness excludes the 5 stale,
  score re-run reported.
- Orthogonality verified: managed (is_active) and signal (traffic) stay independent.
- Roadmap doc updated to 45 AFTER the code (doc follows code).
- Commit SHA(s).
