# Safety Control Decision — 2026-05-04

**Status: Confirmed. Recommendation locked pending the confirmation
conditions in §6. Supersedes the draft at
`docs/SAFETY_CONTROL_DECISION_DRAFT_2026_05_04.md` (commit 91eff2c).**

This document confirms the decision for tracker items G1 (adversarial
review disposition) and G2 (policy enforcement disposition). The two
are decided together because the integration strategy is structurally
parallel; §6.7 names the condition under which they would split.

This document decides **the integration strategy for closing the
safety control asymmetry first**, not the final long-term architecture
of review and policy enforcement forever. Near-term closure of the
live gap and long-term target architecture are separate questions
with different answers, and conflating them would make the
recommendation either too cautious for the near-term or too radical
for the long-term.

## 0. Operational context at confirmation

This confirmation was made on 2026-05-04 against the following
operational state, which the recommendation's risk weighting
explicitly depends on:

- **Watch window:** 9 of 50 brain drafts attributed; mix is varied
  across direct, Airbnb, and Vrbo channels; latest attributed brain
  draft 2026-05-03 19:55:40 UTC. Pipeline is live and growing.
- **Operator-quality signal:** None yet. All 13 in-window inquiries
  remain `pending_review`. Approval, edit, rejection, and
  time-to-decision are unmeasured.
- **Issue 3 (canonical persistence):** Appears self-healed under the
  14-day watch-period rule, but 4 of 13 in-window inquiries (~31%)
  still have no joined normalization row. Visibility is muddied even
  though the underlying outage is no longer producing new errors.
- **B11 (legacy `pre_booking_auto_send` orchestration disposition):**
  Unresolved.
- **Metric infrastructure:** `scripts/prebooking_review_metrics.sql`
  metric 4 still failing on a known SQL bug; metrics 1–3 returning 0
  rows due to absence of operator action, not infrastructure failure.

The operational state strengthens the case for Option A near-term
rather than weakening it. New code surface during a period of muddied
observability and absent operator-quality signal is materially riskier
than static analysis would suggest.

## 1. Decision made

The downstream uniformity audit (`eb13f1f`) found that adversarial
review and policy enforcement run on the legacy concierge path but
not on the newer brain path. Brain-path exposure is limited but real
and producing live drafts without uniform safety controls.

The decision is: **how do brain-path drafts get adversarial review
and policy enforcement?**

Two structurally distinct options were evaluated:

- **Option A:** Wire brain-path drafts through the existing legacy
  reviewer and policy checker (faster, less architecturally clean).
- **Option B:** Promote review and policy checking to canonical-typed
  implementations operating uniformly across both paths (slower, more
  architecturally aligned with the canonical contract).

This document decides which to do **first** to close the production
gap. It does not foreclose the other option as eventual long-term work.

What this document does *not* decide:

- The final long-term architecture of review and policy controls
  beyond naming Option B as the target.
- Whether the legacy `pre_booking_auto_send` orchestration is retired
  (tracker item B11 — separate decision).
- Implementation specifics of either option.
- Sequencing of G1 and G2 relative to each other; see §6.7 for the
  condition under which they separate.

## 2. Option A: Wire brain output through legacy controls

### What this means

Adapt the brain's draft output to the input shape that
`response_reviewer.review_concierge_response(...)` and
`pre_booking_auto_send.check_inquiry_policy(...)` already accept.
Brain-produced drafts pass through these existing functions before
reaching operators.

### Concrete shape

The legacy reviewer accepts a text bundle: `guest_message`,
`draft_response`, `source_context`, `lifecycle_stage`, `property_name`.
Brain output today produces a draft plus structured context. The
adaptation is mostly mechanical: convert the brain's structured
output into the legacy text bundle, call the existing function, route
the result back into the brain's draft pipeline.

The legacy policy checker has a similar story. Brain output gets
converted into the inputs `check_inquiry_policy` expects, the function
runs, the resulting `policy_flags` and `policy_warnings` get attached
to the brain's draft.

### Strengths

- **Closes the live gap fastest.** The legacy controls already exist
  and work. Wiring is interface-shaping, not new logic.
- **Reuses validated logic.** The legacy reviewer has been catching
  hallucinations on real traffic for some time. Promoting brain
  output into that flow inherits the existing investment.
- **Lower implementation risk.** Smaller code change, smaller test
  surface, fewer ways to subtly break what currently works.
- **Reversible.** If the long-term direction shifts to Option B, the
  wiring is easily replaced later. Option A does not foreclose B.

### Weaknesses

- **Does not address the architectural asymmetry.** Both paths now
  use the legacy controls; the canonical-typed control surface still
  doesn't exist. The architecture commitment to canonical-aware
  enforcement is unmet.
- **Couples brain to legacy code that may be retired.** If B11
  resolves toward retiring the legacy `pre_booking_auto_send`
  orchestration, the legacy reviewer and policy checker may go with
  it. Building Option A creates a dependency on code that may not
  survive.
- **Type-system debt.** The legacy reviewer accepts a text bundle
  rather than `CanonicalInboundMessage`. Brain output gets shredded
  into legacy types at the integration seam — the same anti-pattern
  the intake audit flagged for `_save_inquiry`.
- **Does not improve observability for review decisions.** Whatever
  observability state the legacy reviewer has today (not exhaustively
  audited) is what brain-path drafts get.

## 3. Option B: Promote controls to canonical-typed implementations

### What this means

Replace the legacy reviewer and policy checker with implementations
that accept canonical inputs (`CanonicalInboundMessage` plus draft
and context) and produce canonical-shaped outputs. Both paths consume
the new canonical implementations.

### Concrete shape

Two new module surfaces — `app/services/messaging/adversarial_review.py`
and `app/services/messaging/policy_enforcement.py` — accept canonical
input types and produce canonical output. Existing legacy callers
adapt to these (or get migrated to canonical orchestration that uses
them natively). Brain-side callers use the new modules directly.

The implementations might internally call the same underlying logic
the legacy code uses (LLM prompts for adversarial review, intent-based
policy rules), but their interface is canonical-typed.

### Strengths

- **Architecturally aligned.** Closes the asymmetry by making both
  paths use a single canonical-typed control surface. Matches the
  canonical contract commitment.
- **Independent of legacy orchestration disposition.** B11's
  resolution doesn't change what happens to the canonical controls.
  They survive whether or not the legacy orchestration is retired.
- **Carries observability through canonical fields.** The canonical
  modules can log with canonical correlation context, structured
  errors, and consistent metrics — fitting the architecture's
  observability commitment.
- **Sets up for future expansion.** New extraction strategies, new
  PMS integrations, and other future canonical-aware code paths get
  uniform safety controls without per-integration wiring.

### Weaknesses

- **Slower to close the live gap.** Building canonical-typed
  implementations is real work — interface design, internal logic
  migration, test coverage, deployment. The asymmetry stays open
  during build.
- **Higher implementation risk.** New code surface means new bug
  surface. Even if the underlying logic is preserved, the integration
  points are new.
- **Migration of legacy callers required.** If legacy code paths
  remain, they need to be migrated to use the canonical controls (or
  the legacy controls maintained alongside). Either is more work than
  Option A.
- **Risk of half-built canonical surface.** If the implementation
  stalls partway, both paths could end up in a worse state than today
  (no controls instead of asymmetric controls).

## 4. Evaluation criteria

The choice was evaluated against the following dimensions, in rough
priority order.

**1. Time to close the live gap.** The asymmetry is producing live
drafts today. Faster closure reduces operator exposure to drafts
without uniform safety controls.

**2. Reversibility.** A near-term decision that forecloses long-term
options is worse than one that leaves long-term flexibility intact.

**3. Implementation risk.** During an active rollout watch with
muddied observability (Issue 3's normalization gap) and absent
operator-quality signal, introducing new code surface to the
message-processing pipeline carries elevated risk.

**4. Coupling to disposition decisions.** B11 (legacy orchestration
disposition) is unresolved. Choices that minimize new dependencies on
legacy code reduce future migration cost.

**5. Architectural alignment.** The canonical contract is the target
state. Choices that move toward it are preferred over choices that
delay it, all else equal.

**6. Operator-felt impact.** Both options produce drafts with safety
controls applied; from an operator's perspective, the choice is
mostly invisible. This dimension does not strongly distinguish the
options.

## 5. Confirmed recommendation

**Near-term: Option A.**
**Long-term target: Option B.**

Wire brain-path drafts through the legacy reviewer and policy checker
*now* to close the live asymmetry. Plan canonical-typed
implementations as the long-term target, scheduled after Issue 3 is
fully resolved (not just self-healed) and B11 is decided.

### Reasoning

The criteria produce a sequenced answer rather than a binary one:

- **Time to close the live gap** strongly favors A. Exposure is small
  but real; faster closure is genuinely valuable.
- **Reversibility** does not strongly distinguish the options. A
  doesn't foreclose B; B doesn't foreclose anything.
- **Implementation risk** during the current operational state
  (active watch window, Issue 3 normalization gap, absent operator
  signal) favors A. Less new code surface during a fragile period.
- **Coupling to disposition decisions** favors B in isolation, but
  this is mitigated by Option A being explicitly framed as the
  near-term step. If B11 is resolved before Option A's wiring is
  finished, sequencing can adjust.
- **Architectural alignment** favors B. This is the strongest
  argument against A as a permanent answer, but does not undermine A
  as a near-term step.

The combined reading: A is the right near-term move because the live
gap matters and the operational state cautions against larger new
surfaces. B is the right long-term target because the architectural
commitment requires it. Treating these as sequential rather than
competing produces a cleaner recommendation than picking one and
defending it as both near-term and long-term answer.

### What this means for the rest of the tracker

This confirmation requires the following tracker actions:

- **G1 and G2 implementation work** (currently blocked) becomes
  Option A wiring. Implementation effort is smaller than originally
  implied; this is interface-shaping, not new control logic.
- **Workstream B's longer-term canonical migration items** (B10, B11)
  remain as is. They are the eventual upstream of Option B's later
  delivery.
- **A new tracker item must be added** as part of this confirmation:
  "implement canonical-typed review and policy modules" (suggested
  ID per tracker convention), status "Deferred — long-term target
  after Option A near-term wiring." This item is not optional; it is
  load-bearing for the sequenced recommendation. See §6.6.

## 6. Confirmation conditions before implementation

The recommendation is confirmed but conditional. Before becoming the
basis for implementation work, the following must be true.

**6.1 Issue 3 status check.** Re-evaluate the recommendation if Issue
3's normalization gap (currently 4/13 in-window inquiries with no
joined normalization row) does not close out. Option A is the right
near-term move *because* the operational state argues against new
surface area. If Issue 3 is fully resolved (not just self-healed) and
the canonical seam becomes reliable, Option B's risk profile improves
and the near-term A vs long-term B sequencing tightens — less time
on A, sooner on B.

**6.2 B11 resolution context.** If the legacy `pre_booking_auto_send`
orchestration is decided to be actively retired (not migrated),
Option A's coupling concerns become more material. The recommendation
might shift toward investing in B sooner rather than wiring to
soon-to-be-deleted code.

**6.3 Brain-path traffic trajectory.** If brain-path traffic increases
materially in the next session or two (e.g., from 9/50 watch-window
attribution toward saturation, or in absolute terms beyond current
levels), the urgency of closing the gap increases. Option A's "fast
closure" advantage gains weight. The recommendation does not change,
but its priority among other tracker items rises.

**6.4 Operator input.** F1 (Beach Habitats operator check-in) might
surface concerns that change evaluation. For example, if the operator
explicitly cares about consistency of review behavior across drafts,
this affects how acceptable "wired-to-legacy" looks in practice.

**6.5 Implementation scope confirmation.** Option A's "interface-
shaping, not new logic" framing is based on static analysis of legacy
reviewer and policy checker signatures. A targeted code-region review
of those functions plus the brain's draft output should confirm the
wiring shape is genuinely small. If it turns out to be larger (e.g.,
the legacy reviewer expects context fields the brain doesn't readily
produce), the option's strengths diminish.

**6.6 Long-term Option B tracker item creation.** This confirmation is
not complete until a tracker item exists for canonical-typed control
implementations, with status "Deferred — long-term target after
Option A near-term wiring." This makes the sequenced recommendation
visible in the tracker rather than buried in this document. The item
must be added as part of the same tracker update that records this
decision; bundling here is intentional, because the sequenced
recommendation degrades into "do A, intend B someday" without it.

**6.7 Adapter shape verification.** Before implementation begins,
confirm that adversarial review and policy enforcement genuinely
accept structurally similar adaptation from brain output. If
adversarial review needs context fields (retrieved grounding facts,
source attributions, intent-classification context) that the brain
doesn't produce in the shape the legacy reviewer expects, G1 and G2
separate into independent implementation tracks. The bundled
treatment in this document is a recommendation, not a commitment;
the adapter shapes are assumed parallel based on legacy signature
inspection, not verified end-to-end. Verification is a small targeted
audit (estimated 30–60 minutes) and should run before scoping
implementation effort.

## 7. Open risks

The risks worth naming explicitly, separate from the confirmation
conditions above:

- **Option A's "reversible" claim depends on disciplined sequencing.**
  Once Option A is wired and working, the pressure to invest in
  Option B diminishes. The architectural target slides if the tracker
  doesn't actively hold the line. The §6.6 tracker item requirement
  is partly a hedge against this drift, but it is not sufficient on
  its own — periodic review of the deferred Option B item is also
  needed.

- **Brain-path traffic could regress without notice.** The brain path
  may be running today on a subset of traffic that's not stable —
  e.g., it may be flag-gated to specific operators or message types.
  If those gates change and brain-path traffic grows, the "limited
  exposure" calibration becomes stale. Brain-path attribution should
  be tracked as a recurring metric, not just a one-time measurement
  during the watch window.

- **Issue 3 self-heal vs full resolution.** The 14-day watch-period
  rule moves A1 to Deferred if no further canonical-persistence
  errors and no normalization gaps appear. The current 4/13
  normalization gap may be pre-fix residue or may indicate the
  underlying issue has not fully cleared. Confirmation §6.1 depends
  on knowing which; the rule's clock should not advance unexamined.

- **The decision artifact itself ages.** This artifact reflects state
  as of 2026-05-04. If implementation work doesn't happen for weeks,
  re-confirm the recommendation against state-at-that-time before
  proceeding.

## 8. What confirmation unblocks

With this decision confirmed and the §6.6 tracker item added:

- **G1 and G2 implementation** can be scoped (subject to §6.5 and
  §6.7). Recommended next sub-step is the §6.7 adapter shape
  verification audit, before any code changes.
- **G3 and G4** become reachable once G1/G2 are implemented.
- **Option B planning** remains deferred and is not scoped here. It
  becomes active work after Issue 3 is fully resolved, B11 is
  decided, and Option A is in production.
