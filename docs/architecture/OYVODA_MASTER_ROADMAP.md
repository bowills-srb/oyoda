# Oyvoda Master Roadmap

Product-level implementation plan and open decisions. This is the layer ABOVE the
frontend migration brick-order (which lives in FRONTEND_MIGRATION_DISCIPLINE.md). This
doc carries the cross-cutting sequence, the backend work, and the decisions that are
genuinely blocked on founder judgment rather than engineering.

Companion docs (read together):
- `docs/architecture/FRONTEND_MIGRATION_DISCIPLINE.md` — the Tailwind migration rules,
  conversion order, violation/decision log, retained-family notes.
- `OYVODA_OPERATOR_OS_BLUEPRINT.md` — target-state UI/IA and the Data Delivery Posture.
- `OYVODA_AUTONOMY_OS_SPEC.md`, `OYVODA_REVIEW_DRAWER_SPEC.md`,
  `OYVODA_HOME_ROUTE_SPEC.md`, `OYVODA_ESCALATIONS_ROUTE_SPEC.md` — surface specs.

<!-- ===================================================================== -->
<!-- LIVE STATUS — update every session. This is the source of truth for   -->
<!-- "where are we." If conversation and this doc disagree, fix this doc.   -->
<!-- ===================================================================== -->

## CURRENT STATUS

Last reconciled against committed SHAs.

### Committed and done
- Learning capture: tables (089_operator_learning_tables) migration; capture
  wired in operator_prebooking.py (verified live, all three routes fire-and-forget). NOTE: the
  real migration chain is 088 -> 089_operator_learning_tables -> 090_operator_autonomy_snapshots.
  (An earlier session summary referenced a phantom "090_operator_learning_tenant_id" that does
  NOT exist in the tree — disregard it; tenant_id/naming work was folded into 089, not a separate 090.)
- Frontend migration bricks LANDED:
  - ListDetailSurface primitive + PreBooking detail conversion (95c921f / 770dd65)
  - App shell + sidebar -> Tailwind (b1aa6c3; first CSS Module, governed by Rule 6)
  - Home route, born-native Tailwind, honest placeholders (e9952c0)
  - Escalations domain module + route, born-native (3776ffc)
  - Briefs A+B-technical: SurfaceControls/Tabs/Header + PreBooking chrome -> Tailwind (9aa067e)
  - Discipline doc committed to repo (1233cb3)
  - **B-product: Inquiry Operations work-queue reframe (710e8e0)**
    Surface renamed "Inquiry Operations" (Shell nav + SurfaceHeader title; route path unchanged).
    summaryLine added: live "N awaiting · M ready · K blocked" counts. Language pass: message-nouns
    -> work-nouns across getNextStepGuidance, QueueShell headers, footer copy. guidance.title now
    the dominant row element (text-primary font-medium) after identity, above preview lines. styles.css
    unchanged at 52,801 bytes.
  - **Guest-Ops-Technical: Today route → Tailwind (6ddfde5)**
    Both files converted (index.tsx chrome+rows+skeletons+banners; SessionExpansion.tsx all blocks).
    Inline surface-header markup replaced with SurfaceHeader component. Deleted sole-consumer families:
    metric-strip/metric-chip, proactive-*, action-list/action-row*, operator-tools/operator-tool*.
    Retained with other consumers: filter-*, queue-shell/empty, queue-banner*, surface-column,
    surface-header* (Properties/Knowledge/Settings/Vendors/Router/Components still inline).
    styles.css: 52,801 → 43,994 bytes (−8,807). tsc clean.
- styles.css: 67,113 -> 43,994 bytes.

  - **Guest-Ops-product: rename Today → Guest Operations (f6f9af9)**
    SurfaceHeader title + Shell nav label updated; route path /app/v2/today unchanged.
    styles.css unchanged. tsc clean.
  - **PreBooking queue-shell* cleanup (7a0d210)**
    PreBookingQueueShell was the last consumer of queue-shell, queue-shell-head,
    queue-shell-tools, queue-meta, queue-depth-control — converted inline, families deleted.
    PreBooking chrome now 100% Tailwind. styles.css: 43,994 → 43,299 bytes (−695).
  - **Property-Readiness-Technical: Properties → Tailwind (724866d)** — LARGEST single drop.
    PropertiesRoute.tsx + PropertyExpansion.tsx + DocumentUploadForm.tsx fully converted.
    Inline surface-header replaced with SurfaceHeader; view-toggle/search/selects moved into
    SurfaceControls block (the one authorized structural move — required to use shared header).
    Both view modes (row + grid) and both detail paths (inline expansion + grid modal) preserved.
    Deleted Properties-owned families: view-toggle*, properties-metric-*, property-table*,
    property-row-completeness*, property-expansion*, property-gap-entry*, property-kb-entry*,
    property-asset-entry*, property-grid/property-card*, property-detail-modal*, document-upload-*,
    queue-banner* (Properties was the last consumer). styles.css: 43,299 → 24,976 (−18,323). tsc clean.
- styles.css: 67,113 → 24,976 bytes (−63%).

  - **Property-Readiness-product: property trust console reframe (bee2fd3)**
    Surface renamed "Property Readiness" (title + Shell nav; route path unchanged). Trust-question
    subtitle + summaryLine ("N high readiness · M need coverage · K blocked"). Introduced
    readiness.ts with single READINESS_LABELS mapping (keyed by completeness label keys); all
    consumers (CompletenessChip, MetricChip, status filter options, expansion chip) read from it.
    A-swap (autonomy verdicts) is provably one-file — label strings appear only in readiness.ts.
    COMPLETENESS_LABELS import removed from PropertiesRoute + PropertyExpansion; completeness
    calculation, label keys, filters, both views, both detail paths all unchanged.
    styles.css: 24,976 bytes (unchanged). tsc clean.

  - **Inline-header consolidation sweep (1c820b2)**
    Every surface now uses SurfaceHeader component. Zero inline surface-header* markup remains.
    Router.tsx (loading fallback) + Home (both error + main returns) + Components: converted to
    Tailwind <main> + SurfaceHeader. Knowledge + Vendors + Settings: surface-column → Tailwind
    (already used SurfaceHeader). Families deleted: surface-column, surface-header,
    surface-header-copy, surface-kicker (removed from shared selector; panel-kicker retained),
    surface-title, surface-subtitle, surface-summary-line (was already unused).
    RETAINED: filter-bar, panel-kicker (Knowledge/Settings/Vendors still consume them — own bricks).
    styles.css: 24,976 → 23,628 bytes (−1,348). tsc clean.
- styles.css: 67,113 → 23,628 bytes (−65%) as of 1c820b2.

  - **Motion layer — Phase 5.2 (6d9d265)**
    Detail pane symmetric enter/exit on both breakpoints. Option A path: presence hook
    (non-modal Dialog fought the flex layout — presence hook is cleaner, fully contained).
    Desktop: usePresence in ListDetailSurface — slide+fade 180ms, transitionend-driven
    unmount (not setTimeout), prefers-reduced-motion instant. Mobile: Radix presence
    (already existed) + CSS @keyframes for enter (sheet-in/overlay-in, defined in
    tailwind.config.cjs — not styles.css), CSS transitions for exit (data-[state=closed]).
    Selection feedback, button states, row transitions: already in place. Deferred: row
    settle on send (needs per-card exiting presence, own brick), count tick-downs (own brick).
    styles.css unchanged at 23,628 bytes. tsc clean. No new npm deps.

  - **Keyboard navigation (54768de + be4b9b9)**
    useListKeyboardNav hook (shared/hooks/) + wired to all four list surfaces.
    j/k/ArrowDown/ArrowUp moves through current visible/filtered list; Escape closes.
    Focus-in-input guard: keys no-op while operator types in search/filter/textarea.
    Scroll-into-view on move (smooth; instant under prefers-reduced-motion). No-wrap
    at list ends (consistent; wrapping disorients in 73-item queues). enabled gate
    for Properties grid modal. Two commits: hook+PreBooking prove-out, then roll-out.
    styles.css unchanged. tsc clean. No new deps.

  - **Autonomy snapshot job — brick 1 DONE (migration + service + task)**
    Migration 090_operator_autonomy_snapshots: append-only history table, UNIQUE(tenant_id,
    snapshot_date), index (tenant_id, snapshot_date DESC), reversible. autonomy_score_service.py:
    portfolio-level directional score (readiness 60% + escalation 30% + behavior 10%=neutral),
    weights as named constants, domain bands (Inquiry computed; Guest Ops Developing; Maintenance/
    Turnover Emerging — band words, never fabricated numbers). Celery task snapshot_autonomy_all_operators:
    fail-soft per tenant, idempotent per day (ON CONFLICT DO UPDATE), nightly beat at hour=6.
    History capture has STARTED. Verification (run task against Beach Habitats, confirm row with
    sane score + bands) is the last step before marking fully done.

  - **Gap recording fix — property attribution (this commit)**
    Root cause confirmed in code: record_gap() wrote property_id=NULL by construction because
    _resolve_property_id_from_external was only called from resolve_gap, never at write time.
    Both sources (gmail_poll AND messaging_brain_orchestrator) were affected — shared-path bug.
    Fix: record_gap() now resolves property_external_id → property_id before INSERT, fail-soft
    (NULL + debug log if resolution misses). record_gap_async passes None not "" so guard triggers.
    Note: the "webhook cutover" was misread — gmail_push.py triggers the same poller via Celery;
    source="gmail_poll" IS the current active path. No poller retirement needed.
    Backfill script: app/services/messaging_brain/knowledge/gap_backfill.py
      --backfill: resolves the ~100 rows with external_id (recoverable)
      --quarantine: flags the ~473 rows with neither id as attribution_status=unattributable,
        resolved=True (excluded from scoring; NOT deleted)
    Run dry-run first; then --backfill --quarantine --no-dry-run against live tenant.
    This fix affects Property Readiness, Knowledge Health, and KB-gap queues — not just autonomy.
    After backfill/quarantine, re-run daily attribution query to confirm new gaps land attributed.
  - **Knowledge-layer audit arc — COMPLETE and live-verified**
    The operator-correct-anything-at-any-scope question is now answered YES through the real
    dashboard path, including neighborhood/property_group scope. This arc landed in five commits:
    Gap 1 staging/property_group seam fixed (9916f13), Gap 2 provenance columns + honest
    verified semantics (6fd730d), Gap 4 proactive neighborhood/HOA gap surfacing (5dc5209),
    Gap 3 real neighborhood data populated for Beach Habitats (1b4b713), and Piece A
    scope-aware operator editing path (6c4edee).
    Live end-to-end verification caught three DB-truth bugs that unit tests missed and that are
    now resolved: topic_id was being hardcoded NULL on writes (surfacer could never mark a gap
    covered), verified_at was being passed as an isoformat string instead of a timestamptz-
    compatible datetime, and migration 092 had not yet been applied to live. After fixing those,
    the full loop was verified on Beach Habitats: WaterColor missing HOA rules -> operator creates
    a group-scoped entry -> member property inherits with scope_origin='property_group' ->
    surfacer moves topic from missing to present -> verified_at set, confidence NULL,
    operator-authored and honest. Migration 092 is now applied to live.

### In flight / next
- **Gap backfill/quarantine — DONE on anchor tenant.**
  Beach Habitats live cleanup run: 65 rows backfilled, 476 quarantined as
  attribution_status=unattributable, 35 identifier-bearing rows still unresolved
  (mostly free-text/title residue plus a smaller canonical-ref miss bucket). New gaps
  should now benefit from the shared resolver fixes on the forward path.
- **Autonomy formula redesign — DONE (Theory A confirmed and fixed).**
  Clean input still pinned the old formula at 0.5, so readiness math was redesigned to use
  scale-aware gap ratios and escalation now distinguishes pristine-with-traffic from no-signal.
  Unit tests now validate 4 hypothetical tenant profiles plus perturbation checks. Beach Habitats
  live recompute moved to portfolio_score=0.8137 (readiness=0.8478, escalation=0.85), proving the
  score is now responsive on clean input. Computation layer is now UNBLOCKED.
- **Learning foundation under the knowledge layer — DONE.**
  The scope-aware write path, four-tier scope vocabulary, provenance semantics, proactive
  neighborhood surfacing, and real property_group memberships are all present and verified live.
  What remains is Piece B: draft-edit decomposition + operator scope choice + routing into the
  already-working Piece A path and existing review/staging machinery.
- **Row settle on send/reject/resolve**: per-card exiting presence pattern (track "exiting"
  row ID, keep rendered, animate out before data refetch removes it). Own brick.
- **Knowledge / Vendors / Settings tail** (BACKGROUNDED): own bricks; each deletes filter-*,
  panel-title, queue-empty/empty-*, knowledge-*, settings-* when last consumer converts.

### Outstanding technical debt (tracked so it isn't forgotten)
- Shared families RETAINED pending last consumer: `filter-*` (Knowledge/Settings/Vendors),
  `panel-title`/`queue-empty`/`empty-*` (Settings/Vendors/Knowledge/Components),
  `knowledge-*` (Knowledge route), `settings-*` (Settings), `autonomy-*` (PreBookingAutonomyPopover),
  `badge-*`/`btn-*` (legacy — PreBooking popover, detail-* family).
- `preflight: false` stays until the last legacy CSS is gone — it is the migration tombstone.
- styles.css: 23,628 bytes as of 1c820b2. Remaining: filter-*, panel-title, queue-empty/empty-*,
  knowledge-*, settings-*, autonomy-popover*, detail-*, badge*/btn*.

## PRODUCT SEQUENCING (Feel vs. Moat)

Two investment types, not competing: **Feel** (motion, density, visual polish — execution) and
**Moat** (learning, autonomy, trust — founder judgment). Sequence:

1. ~~Migration cleanup~~ (done through inline-header sweep) — deferred long-tail to background.
2. **Motion layer** — highest-leverage Feel work, mostly execution. What an operator notices
   immediately. Next frontend brick.
3. **Operator feedback** — real Beach Habitats usage patterns from accumulated capture data.
4. **Learning loop Piece B** (from evidence, not assumptions) on top of the now-complete
   autonomy + knowledge foundations.

The sequencing argument: surfaces being built teach what the learning system needs. Capture
(089) is live and accumulating — data grows whether or not design decisions are made. Starting
the learning redesign before surfaces are mature means designing from assumptions; starting after
means designing from real approve/edit/reject/bind patterns. Waiting is strictly better.

## THE ONE OPEN DECISION (blocked on founder judgment, not engineering)

**REPRIORITIZED (this session): learning is a PRECONDITION FOR ADOPTION, not deferred-pending-
evidence.** The earlier "defer until capture accumulates" logic assumed operators are using the
system and generating edits to learn from. They are NOT — and Hunter's read is that an operator
won't meaningfully adopt until this decision layer exists (they won't trust the system with their
edits until edits are handled intelligently, not blindly auto-learned). So the dependency is
INVERTED: learning gates adoption, adoption produces the capture data — "wait for capture" was
waiting for something that can't arrive until this is built. Therefore:
- It is BUILDABLE NOW WITHOUT capture data. The decision layer is a MECHANISM (decompose edit ->
  present scope choice -> route), not a model that needs training data. Capture becomes useful for
  TUNING after the layer exists, not for building it.
- The capture-analysis-first build step (old step 1) is DROPPED as a precondition — there's no
  corpus to analyze yet. It can inform tuning later.
- This is plausibly the NEXT major workstream after the autonomy capstone, because it's what makes
  the product adoptable.

### Scope taxonomy — FOUR tiers (Hunter, this session)
When an operator edits a draft and sends it, the system proposes remembering it, with a scope:
- **one-off** -> learn nothing (the protection the current blind auto-learn engine lacks).
- **property** -> scope_type='property' (concierge_scoped_knowledge ALREADY supports this).
- **neighborhood** -> NEW: scope_type='property_group' pointing at property_groups.id. The data
  model ALREADY EXISTS (db/models/property_group.py: PropertyGroup with group_type defaulting to
  'condo_complex', docstring "condo complex or HOA zone"; PropertyGroupMembership M2M). 30A example:
  WaterSound / WaterColor / Seaside, each with HOA rules / gate codes that apply to all properties
  in that group but not others. Absence-of-neighborhood is a VALID NON-GAP state: a property with
  no group membership simply has no neighborhood scope option — never flagged as missing data
  (M2M absence handles this inherently; same honesty rule as insufficient-signal).
- **portfolio** -> scope_type='tenant' (ALREADY supported).

### Style is OUT OF SCOPE for learning (Hunter, this session)
Style (tone, length, sign-off, formality) is a SETTING the operator sets explicitly in operator
settings — NOT a learned fact and NOT part of the proposal flow. The learning loop deals ONLY with
durable fact/policy knowledge (prices, HOA rules, check-in details), scoped by the four tiers.
Style edits don't enter the proposal flow at all.

### Known build pieces (bounded — foundations largely exist)
1. Extend concierge_scoped_knowledge.scope_type to recognize 'property_group' (clean extension of
   the existing tenant/property pattern; scope_target_id -> property_groups.id).
2. Add the group layer to KB-coverage / knowledge-inheritance resolution: a property's effective
   knowledge = tenant-scoped + ITS GROUPS' scoped + property-scoped (additive to the
   tenant-baseline-inheritance model already needed for per-property autonomy).
3. Decision/proposal surface: edit -> decompose what changed -> present four-tier scope choice ->
   route to the right scope_type. Decoupled from sending (send is instant; proposal is async).
   Depends on ListDetailSurface/ReviewDrawer (already built).
4. Onboarding: capture neighborhood/group membership at SIGNUP (present to every operator), so it's
   ground truth from the source — sidesteps the property-lifecycle drift problem. Neighborhood
   optional (absent is valid).
5. Replace the current blind auto-learn (learns every non-trivial edit, can't tell durable from
   one-off) with the proposal+scope flow.

### OPEN DATA CHECK — RESOLVED (Gap 3 done)
property_group_memberships were empty; derived and populated from properties.community enum
(Gap 3, scripts/backfill_property_groups_from_community.py). Beach Habitats: 7 groups, 42 memberships.
Distribution: WaterColor (30), Seagrove Beach (6), Blue Mountain Beach (2), Seacrest Beach (1),
Rosemary Beach (1), Grayton Beach (1), WaterSound (1). 3 properties community='other' → no group
(honest absence). Gap 4 surfacer verified live: 7 groups × 8 missing topics each (0% coverage —
correct; no group-scoped knowledge written yet).

RECONCILIATION DECISION (documented): Two neighborhood representations exist:
  - Legacy: properties.community ENUM (migration 003) — operator-provided at import
  - Canonical going forward: property_groups M2M (migration 076) — richer (supports scoped
    knowledge, HOA rules, learning loop tier; the enum can hold none of that)
  v1: derived groups from enum once. New properties/onboarding should populate group membership.
  Drift risk noted (independent edits diverge); flagged for v2 "single canonical neighborhood home."
  Do NOT deprecate the enum — other code reads it. Additive only.

---

**Original design notes (still valid, refined by the above):**
The current engine auto-learns from every edit (only filter:
not-minor-polish + similarity<0.95). That is the flaw — it cannot tell a durable rule from a
one-off, so it would learn and inject both ("warm-draft" failure mode).

DECIDED design (awaiting build, decoupled so nothing else waits on it):
- Capture stays as-is (live, accumulating Beach Habitats edits now).
- Auto-learn -> **proposal + human scope** (tenant-wide / property / one-time). One-time = learn
  nothing — the protection the current engine lacks.
- **Decouple learning from sending** — send stays instant; proposals reviewed asynchronously in
  a separate "what Oyvoda noticed" surface.
- **Style vs fact/policy split** — style edits (TONE_*, LENGTH_*, CTA_*) route to settings or
  drop; fact/policy edits (FACT_ADDED, POLICY_*, PRICE_*) are the real learnable surface.
- **KB-gap routing** — fact-components route to the existing KB-gap flow; preference-components to
  the preference flow. Operator's scope decision disambiguates; no duplication.

BUILD SEQUENCE when taken up (Claude recommendation, Hunter approved):
1. Capture-analysis brief first — look at REAL accumulated Beach Habitats edits (edit-type
   distribution, multi-component frequency, human-eye scope mix) BEFORE committing to the
   proposal-review architecture. Don't build the surface on assumptions about edit behavior.
2. Then proposal-and-scope backend (data-independent: component decomposition, pending-proposal
   state, style-routing, KB-gap handoff).
3. Then the review surface (its weight — batch inbox vs light nudge — shaped by step 1's data;
   also depends on ListDetailSurface/ReviewDrawer, which are built).
4. Shadow/injection LAST — validate scoped, human-approved preferences before they touch drafts.

FOLLOW-UP TRIGGER: once Beach Habitats has accumulated real edits in operator_draft_events, run
the capture-analysis. Until then, capture runs silently — intended.

## PRODUCT SEQUENCE (the agreed order; experience leads, scoring evolves underneath)

1. Home / Portfolio Autonomy — DONE (hero wired to real score 0.8063, 32 computed / 13 insufficient signal, domain bands; PropertyReadinessCard shows computed/insufficient split; see consumer wiring commit)
2. Review Drawer — DONE (slot contract, proven across PreBooking + Escalations)
3. Escalations — DONE
4. Inquiry Operations refinement — DONE (710e8e0)
5. Guest Operations refinement (Today conversion)
6. Property Readiness (Properties conversion)
7. Domain-Autonomy v1 backend (see below)
8. Real-time push layer (deferred — see Blueprint Data Delivery Posture)

## PROPERTY LIFECYCLE (tracked dependency — read vs write are separate problems)

**Read-side (fixable now, being done):** `properties.is_active` is the managed-property
predicate. `COALESCE(is_active, TRUE) = TRUE` filters the managed set. The predicate sweep
applies it to all operator-facing counts (autonomy denominator, dashboard-summary, Property
Readiness lists/totals, per-property set). Beach Habitats: 45 managed (is_active=true), 5 stale
(is_active=false: 102-1785, 203WW, 236SC, 68RF, 75ECRAB). This makes the score READ the set
correctly. See OYVODA_BRIEF_MANAGED_PROPERTY_PREDICATE.md.

**Write-side (the real gap — how does is_active STAY accurate as the operator gains/loses
rentals?):**
- **Real fix = PMS/OTA-driven reconciliation. BLOCKED on Escapia** — they have not given us the
  property feed. When available: sync reconciles the local `properties` set against the live PMS
  listings, flips is_active on departures, creates active rows on additions, triggers onboarding.
  is_active becomes a PROJECTION of PMS state. This is the destination, not buildable yet.
- **Interim = manual operator/admin add+offboard controls.** Buildable now (is_active exists,
  data model supports it), most likely an action in Property Readiness (the trust console). A
  gained property flows in as is_active=true / zero KB / zero traffic → Property Readiness shows
  "Readiness Blocked / needs coverage", autonomy shows insufficient-signal — the surfaces to
  HANDLE a new property already exist. Forward-compatible: when the PMS sync arrives, it becomes
  another writer of is_active and manual controls become the override/exception path.
- **NOT blocking autonomy.** The 5 stale rows are already is_active=false, so the predicate sweep
  handles today's set correctly (45). Drift only manifests on the NEXT gain/loss. Build the interim
  manual lifecycle when that's imminent (Beach Habitats churns a rental, or operator #2 onboards
  and manual maintenance stops scaling) — not before. Documented gap, not a current blocker.
- **Orthogonality (keep):** is_active = managed-vs-unmanaged (deliberate fact). traffic =
  has-signal-vs-insufficient (derived). Independent. A managed-but-quiet new property is counted
  AND insufficient-signal — never excluded. Never use traffic as a managed predicate.

## DOMAIN-AUTONOMY v1 (decided; tuning-only open)

Directional posture score, NOT a scientific measurement. Same honesty discipline as the
no-fake-revenue rule — band words for immature domains, computed numbers only where real inputs
exist.

- **Domain-keyed**, not single-property-score: store Inquiry / Guest Ops / Maintenance / Turnover
  per property (schema decision made NOW even though only Inquiry computes in v1, to avoid a rewrite).
- **Inquiry** = first mature domain (knowledge-driven, most automatable). Computed from real inputs.
- **Guest Ops** = Developing. **Maintenance / Turnover** = Emerging (band WORD, never a fabricated
  number — "Emerging" is honest; "22%" implies a measurement that doesn't exist).
- v1 weighting (directional): readiness (knowledge/asset/gaps) + escalation pressure + operator
  behavior. **Behavior = NEUTRAL** until the learning redesign lands — this is the decoupling that
  keeps autonomy from waiting on the learning decision.
- **Snapshot job built IMMEDIATELY** — the one piece with a calendar cost to starting late. History
  cannot be backfilled. Trend ("52% -> 84%") is empty at first and that's fine.
- Open: exact weights + band cutoffs — TUNED against real Beach Habitats numbers after the
  computation exists, not decided up front.
- When ready, the Home PortfolioAutonomyHero placeholder swaps to the real score (fills one slot;
  rest of Home unchanged).
- **A-swap consequence (Property Readiness labels):** Property Readiness currently uses
  COVERAGE-readiness labels (High Readiness / Needs Coverage / Readiness Blocked), sourced from a
  SINGLE mapping in routes/Properties (decision B). When this autonomy backend lands, that mapping
  hardens to AUTONOMY VERDICTS (Autonomous / Assisted / Review Only, or Automation Ready / Assisted /
  Blocked) and is re-keyed off the autonomy score instead of completeness. It was deliberately
  built as a one-file swap — grep the label strings; they live only in the mapping. This is the
  Properties half of "B now, A later."

## FEEL vs MOAT — the two remaining investment tracks (different investments, both needed)

After the surfaces are product-complete, the remaining work splits into two DIFFERENT kinds
of investment that should not be confused or treated as competing:

**Product FEEL** (execution; makes the product feel like premium software):
motion / transitions, density tiering, visual polish. An operator notices these immediately.
Largely execution, not founder judgment. Unblocked now that surfaces are converted.

**Product MOAT** (founder judgment; makes the product defensibly better over time):
the learning loop, autonomy scoring, trust expansion. This is the actual moat
(Trust -> Delegation -> Autonomy). Requires founder-level product-philosophy decisions.

If forced to choose between "Fin-grade UI" and "autonomy that improves every month," the
second wins. But they're not a choice — they're sequenced.

### Why learning is DELIBERATELY deferred (not procrastination)

The surfaces being built NOW are teaching us what the learning system needs. Start the
learning redesign today = designing from assumptions about operator behavior. Start it after
the Review Drawer has captured real approve/edit/reject/bind/escalate patterns across mature
surfaces = designing from EVIDENCE. Strictly better.

And it costs nothing to wait: **capture is already live** (operator_draft_events, since 089).
Data accumulates regardless of when the design decisions get made. Collect now, interpret
later, redesign third. Every surface teaches the learning system: Review Drawer ->
approve/edit/reject patterns; Inquiry Ops -> gaps/binding/confidence; Guest Ops -> escalation
types/interventions; Property Readiness -> coverage/policy deficiencies.

### Near-term sequence (consensus, Hunter + Claude + GPT)

1. Inline-header sweep — DONE.
2. Motion layer — CORE DONE.
3. Autonomy backend — COMPLETE. Portfolio score + per-property computation (28556da). Predicate
   sweep (8c0796f). Consumer wiring — Home hero 0.8063, PropertyReadinessCard computed/insufficient
   split, readiness.ts A-swap to autonomy verdicts (Autonomous/Developing/Emerging/Insufficient Signal).
4. PAUSE migration cleanup (Knowledge/Settings/Vendors/primitives) — lowest operator value;
   background work, not the focus.
5. THEN Piece B of the learning loop (MOAT; scoped proposal flow on top of the verified knowledge
   layer) — now the highest-leverage remaining substance work. Behavior component is a neutral
   stub; real signal requires redesign of operator_learning tables into behavior measurement.
   Capture running since 089 — data accumulating. Hunter deciding when to design from the evidence.

## FIN / PARLOA PARITY — four axes (so "are we moving toward them" is answerable from the doc)

1. **Workspace feel — DONE.** ListDetailSurface + ReviewDrawer; list+detail proven across
   PreBooking + Escalations. This was the biggest structural gap; it's closed. Oyvoda went
   from "pages" to "workspaces."
2. **Motion / transition layer — CORE DONE (6d9d265).** Symmetric in/out detail-pane motion
   on both breakpoints: desktop via a contained transitionend-driven presence hook in
   ListDetailSurface (non-modal Radix was preferred but Dialog.Portal renders to body, so the
   documented fallback was used); mobile via Radix data-state + a sheet-in keyframe in
   tailwind.config.cjs (no styles.css growth). Overlay on separate timing from content.
   prefers-reduced-motion fully gated. Selection/button/row-color transitions already existed
   from the migration bricks. DEFERRED to their own small bricks: row settle-on-send (needs a
   per-card exiting-presence pattern) and count tick-downs.
3. **Density tiering — MATERIALLY ADVANCED (54768de + be4b9b9).** Keyboard navigation landed:
   shared `useListKeyboardNav` hook (stable-ref window listener, focus-in-input guard, no-wrap
   at ends, scroll-into-view via data-keyboard-nav-id + block:nearest, Escape coordination,
   enabled-gating for modals), wired into PreBooking / Escalations / Guest Ops / Property
   Readiness (row view). j/k move, Enter opens, Escape closes, all respecting the visible/
   filtered list. The unified-surface foundation was already solid. STILL DEFERRED (optional,
   low value): compact row mode; bulk-select (deliberately NOT built — implies bulk actions,
   a trust/autonomy product decision, deferred until the autonomy model is settled).
4. **Crafted hero visualization — DONE.** Portfolio Autonomy hero renders real score (0.8063),
   Inquiry band (Autonomous), domain grid (guest_ops/maintenance/turnover band-stubbed), and
   computed/insufficient-signal property split (32/13). Insufficient Signal is a first-class
   display state, not an edge case. Consumer wiring commit landed alongside the capstone.

## CROSS-CUTTING (don't drop)
- Beach Habitats (anchor tenant) has **50 raw property rows; 45 managed (is_active=true), 5 stale
  (is_active=false: 102-1785, 203WW, 236SC, 68RF, 75ECRAB)**. Autonomy denominator and all
  operator-facing counts use the managed set (45). Readiness denominator:
  TARGET_KB_ENTRIES_PER_PROPERTY (5) × 45 = 225 target KB entries — use this when sanity-checking
  autonomy scores. The predicate sweep (COALESCE(is_active, TRUE) = TRUE) is SHIPPED; autonomy
  denominator, bulk-autonomy ALL path, and all paths using where_sql now operate on 45.
- Copy guardrails as CI lint (banned: Autopilot / Revenue generated / Conversion won).
- i18n: confirm guest-facing strings externalized before claiming global-ready.
- Channel abstraction (getChannelLabel) is the non-US-OTA moat — keep first-class.
- tenant_id everywhere on new tables (mid Phase-3 tenant migration); company_id holds the
  tenant_id value on legacy tables — join on tenant_id, never operator_accounts.id.
- SHIPPED requires a git commit SHA. Decision drafts committed as DRAFT, confirmed separately.
- Repo is the source of truth: roadmap + discipline doc live in docs/architecture/, not in chat.
