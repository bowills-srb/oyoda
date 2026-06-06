# Messaging Brain Rich Context -- Rollout

Operational doc for the `MESSAGING_BRAIN_RICH_CONTEXT` flag cutover. Covers
the shadow observation phase, the criteria that gate cutover, the cutover
procedure itself, and the rollback path.

Authored Session 13 Phase A. Update in place when criteria are revised or
when the rollout completes.

## Scope

This doc covers the rollout of the rich-context path in
`ContextBuilderAgent`, gated by feature flag
`MESSAGING_BRAIN_RICH_CONTEXT` (env `OYVODA_MESSAGING_BRAIN_RICH_CONTEXT`).

It does not cover the shadow observation infrastructure itself, which is
a Session 12 deliverable, nor any other messaging-brain flag. The rich
context implementation is at `ContextBuilderAgent._load_rich_context()`
with the shadow seam in the same method.

## What shadow mode captures, and what it doesn't

The shadow path computes the rich-context output under production traffic
and writes it to `rich_context_shadow_observations`. The table records
what the rich-context path produced -- `richness_shadow`,
`evidence_shadow`, `preferences_block_shadow` -- and any exceptions
keyed by sub-computation in `shadow_exceptions`.

It does not record what the legacy path would have produced for the same
message. There is no side-by-side comparison stored.

This means the criteria below assess **internal validity of the
rich-context path under realistic traffic**, not **agreement with the
legacy path**. Cutover is justified by evidence that the rich-context
path produces sane outputs at acceptable exception rates across a
representative traffic distribution. It is not justified by, and cannot
be justified by, this data alone, as bit-for-bit equivalence with
legacy.

If at any point during the rollout someone needs equivalence evidence
specifically, the path is to extend the eval harness (Session 10
infrastructure) to record bundle snapshots from both paths. That is
explicitly out of scope for this rollout unless shadow data turns up
something that requires it.

## Sufficient Signal -- Criteria For Cutover

All criteria below are hard gates. Cutover does not proceed unless every
gate is satisfied or, in the case of spread gates, explicitly released
under the structural-unavailability clause in this section.

These thresholds were chosen at Session 13 time as initial operational
thresholds, before any production sample was reviewed. They may require
revision once actual distributions are observed. Revision requires
observed production evidence from the shadow data, not preference or
intuition. Revisions belong in this doc with rationale, not in chat or
commit messages.

**Volume.** At least 500 observations recorded in
`rich_context_shadow_observations` for the tenant under rollout.
"Observation" means one row, which by the table grain means one message.

**Intent spread.** At least 5 distinct values of `intent` represented in
the observation set, with no single intent comprising more than 60% of
observations.

**Property spread.** At least 10 distinct `property_code` values
represented in the observation set.

**Exception rate per sub-computation.** For each sub-computation key
recorded in `shadow_exceptions` (`richness`, `evidence`, `preferences`),
the share of observations that recorded an exception for that key must
be below 1%. Any sub-computation at or above 1% blocks cutover until
the cause is understood and resolved.

**Cumulative exception rate.** The share of observations recording any
exception at all (any non-empty `shadow_exceptions`) must be below 2%.

**Structural-unavailability clause for spread gates.** If the observed
tenant's actual traffic mix makes a spread dimension genuinely
unattainable -- for example, the tenant has only 6 properties that
message in a typical observation window -- the gate for that dimension
may be released. Release requires written justification appended to
this doc identifying which gate is released, for which tenant, and what
evidence supports the claim that the dimension is structurally
unavailable rather than merely undersampled. The escape hatch is for
"the dimension does not exist in this tenant's reality." It is not for
cases where the observation window has merely been long. Other gates
are unaffected.

## Explicit Non-Criteria

The following do not gate cutover and should not be raised as blockers
during signal review:

**Numeric drift in richness scores.** The richness-score computation
contains tunable constants (the "magic numbers" thread carried from
Session 11). Numeric drift in `richness_shadow` values is expected and
does not constitute a divergence signal. See the closing note for
the resolution of this thread.

**Disagreement with legacy output, of any kind.** The shadow table does
not record legacy output. Any claim about agreement or disagreement
with legacy is, by construction, not supported by this data. See the
"What shadow mode captures" section above.

## Rollout Procedure

### Phase A -- Shadow Rollout And Signal Collection

1. Confirm `MESSAGING_BRAIN_RICH_CONTEXT_SHADOW` is OFF for the target
   tenant. Default is OFF; this is a sanity check, not a state change.
2. Confirm `MESSAGING_BRAIN_RICH_CONTEXT` is OFF for the target tenant.
   Same -- default OFF, sanity check only. Phase A must run with the
   production flag OFF and the shadow flag ON.
3. Run the enable script at `scripts/run_feature_flag.py` from the
   production application environment, with flag
   `MESSAGING_BRAIN_RICH_CONTEXT_SHADOW`, the target tenant's
   `company_id`, and direction `enable`. The script writes to
   `operator_feature_flags` via `FeatureFlagService.set_flag`.
   `property_code` is `None` -- shadow runs at company scope. The script
   must run in an environment where the application's DB configuration
   is loaded; running from a developer laptop pointed at production is
   not the supported path.
4. Wait for the in-process flag cache to expire across workers. TTL is
   300 seconds. New observations may not begin landing on all workers
   until that window has elapsed.
5. Allow the observation window to run until volume and spread criteria
   are at least plausibly satisfiable. The window is whatever it takes;
   do not advance to the next step on a calendar.
6. Run the analysis SQL at `scripts/rich_context_shadow_analysis.sql`
   and review against the criteria above. Results review may surface
   any of:
   - Criteria satisfied -- proceed to Phase B.
   - Volume satisfied, spread not, structural unavailability claimed --
     append justification to this doc, then proceed.
   - Volume satisfied, spread not, structural unavailability not
     claimed -- extend the observation window.
   - Exception rate above gate -- investigate cause before proceeding.
     Cutover does not proceed on elevated exception rates.
   - Any pattern not classified by the outcomes above blocks cutover
     and requires a written assessment, appended to this doc, before
     proceeding.

### Phase B -- Cutover

Phase B is **out of scope for Session 13**. The criteria are not yet
satisfiable because the observation window has not yet run. Phase B
runs in a future session, against data accumulated during Phase A.

When Phase B does run:

1. Confirm criteria reviewed and met (or spread released with written
   justification).
2. Run the enable script at `scripts/run_feature_flag.py` (same
   environmental requirements as Phase A step 3) with direction
   `enable` and flag `MESSAGING_BRAIN_RICH_CONTEXT`. Same scope
   (company-level).
3. Allow the cache TTL to elapse (300s).
4. Monitor for regressions: new exceptions in production logs, error
   rates on `ContextBuilderAgent`, downstream agent behavior changes.
   The first 24 hours after cutover are the highest-risk window.
5. If clean, leave for an observation period (multiple days) before
   ramping to the next tenant.

### Rollback

Rollback for either phase is the same primitive: write `enabled=False`
to the same row.

1. Run the enable script at `scripts/run_feature_flag.py` (same
   environmental requirements as Phase A step 3) with direction
   `disable` and the same flag and tenant scope as the original enable.
2. Wait for the 300s cache TTL to elapse across workers. Behavior
   reverts on a per-worker basis as caches expire.
3. If the rollback was triggered by a regression, capture observation
   evidence (log entries, error rates, message-level repro if
   available) before resuming any rollout work for the same flag.

The resulting row state in `operator_feature_flags` records who last
changed the flag and why via the `enabled_by` and `notes` columns. This
table is not an append-only history log. No replay queue or operator
notification is required beyond the flag change itself.

## Closing Note -- Magic Numbers In Richness Scoring

The richness-score computation in the rich-context path contains
tunable numeric constants whose ownership and tuning has been an open
thread since Session 11. The thread was carried into Session 12 and
Session 13 without resolution.

As of Session 13: this thread is closed as **accepted state**. The
shadow data captured during this rollout cannot determine whether the
constants are "correctly" tuned -- it can only show what range of
values they produce in practice. Treating numeric drift as a divergence
signal would re-open the thread on noise rather than evidence.

Future sessions should reopen this thread only on evidence, not because
the constants are visible in the code.
