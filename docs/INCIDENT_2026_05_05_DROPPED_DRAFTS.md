# Incident — 2026-05-05 Dropped Drafts

This note captures the 2026-05-05 investigation into dropped
`pre_booking_inquiries` drafts observed after the `ecbbfd2` deploy
window. It is an incident note, not a finished postmortem. The
priority is preserving the real state of the investigation so the next
session resumes from the narrowed trigger path rather than re-tracing
already-cleared branches.

## What happened

During the post-`ecbbfd2` stability check, several inquiry drafts were
found in worker logs as:

- `[PreBooking] DB save failed for draft_id=...`

The failed draft ids did not exist in `pre_booking_inquiries`, so this
was a real persistence failure rather than a noisy log-only condition.

Observed failed draft ids from the 2026-05-04/2026-05-05 window:

- `INQ-C860047B`
- `INQ-51C6408F`
- `INQ-784C8F26`
- `INQ-655583DD`
- `INQ-33C0D621`
- `INQ-3BE6D4D8`

The worker-side stack traces showed `InFailedSQLTransactionError`,
meaning the transaction was already aborted before `_save_inquiry(...)`
attempted to persist the draft.

## Structural fix already shipped

Commit `7d09813` moved the Escapia inquiry worker from one shared DB
session per batch to one DB session per inquiry in
`app/workers/tasks.py`.

What that fixes:

- One poisoned inquiry can no longer contaminate later inquiries in the
  same batch.

What that does not fix:

- A single inquiry can still poison its own session and fail its own
  save if an earlier DB operation aborts that inquiry's transaction.

This reduced the blast radius but did not identify the original
within-inquiry trigger.

## Investigation timeline and framing shift

### Initial hypothesis

The first working theory was:

- production schema drift around `knowledge_gaps` / `kb_gaps` /
  `operator_gap_settings`
- a missing-table query on the shared pre-booking session
- later `_save_inquiry(...)` failures as downstream fallout

This was motivated by two real findings:

- production does not have `knowledge_gaps`, `kb_gaps`, or
  `operator_gap_settings`
- application logs showed `UndefinedTableError` against
  `knowledge_gaps`

### What static tracing disproved

Tracing through the worker and pre-booking pipeline materially narrowed
the picture:

- `process_pre_booking_inquiry(...)` itself is not the obvious poison
  site
- key helpers in `pre_booking_auto_send.py` roll back on failure:
  `_get_approval_mode`, `_load_auto_send_policy`,
  `_load_operator_guidance`, `is_pre_booking_enabled`
- `kb_gap_manager` calls under `_ground_inquiry_draft(...)` open their
  own sessions or background tasks and are not the shared-session
  poison path
- `generate_inquiry_draft(...)` does not directly query
  `knowledge_gaps`, `kb_gaps`, or `operator_gap_settings` on the
  shared inquiry session

Conclusion: the original "missing-table query inside pre-booking draft
generation" hypothesis weakened substantially before the trigger was
found.

## Separate finding: shared-session swallow pattern

While tracing the worker path, several real exception-handling bugs
were found that are separate from the active trigger hunt.

Confirmed shared-session swallow-without-rollback sites:

1. `message_history.py::_store_alias`
   - table: `listing_id_aliases`
2. `message_history.py::OrphanMessageHandler.handle_orphan`
   - table: `message_orphan_queue`
3. `operator_learning.py::get_preferences_for_draft`
   - table: `operator_learned_preferences`
4. `operator_learning.py::get_platform_intelligence`
   - table: `platform_intelligence`

All four tables exist in production. These are therefore structural
bugs, but not the currently-confirmed missing-table trigger.

These findings belong in the same incident because they explain why
"best effort" DB lookups are dangerous in any shared-session context:
returning a default is not sufficient if the transaction is already
aborted.

## Schema-design situation

Production schema and code expectations are not aligned around one
single "gaps" model.

Present in production:

- `concierge_knowledge_gaps`
- `operator_ai_guidance`
- `operator_feature_flags`
- `operator_pre_booking_policies`
- `property_rollout_phases`

Absent in production:

- `knowledge_gaps`
- `kb_gaps`
- `operator_gap_settings`

Relevant codepaths:

- `app/services/intelligence/insight_engine.py` queries
  `knowledge_gaps`
- `app/services/concierge/kb_gap_manager.py` expects `kb_gaps` and
  `operator_gap_settings`
- dashboard/operator surfaces use `concierge_knowledge_gaps`

This now looks less like one missed migration and more like multiple
incompatible schema branches surviving in code at once.

Important: this schema-design problem is real, but the latest worker
log analysis suggests it may not be the active trigger behind the
dropped drafts.

## What the worker logs changed

Pulling a tight `oyvoda-worker` log window around the first failed
draft materially changed the active picture.

### First concrete stack-trace finding

For `INQ-C860047B` around `2026-05-04 20:27:37 UTC`:

- `_save_inquiry(...)` did not fail first at the
  `INSERT INTO pre_booking_inquiries`
- it failed earlier inside `guest_thread_service.ensure_inquiry_thread`
- the failing statement there was:
  `SELECT guest_thread_id FROM guest_threads ...`
- the exception was still `InFailedSQLTransactionError`

This proves the save path was already running on an aborted
transaction before the pre-booking row insert was attempted.

### Fanout failures on the same poisoned inquiry

In the same narrow window, the already-aborted session also caused:

- feature-flag reads on `operator_feature_flags` to fail
- rich-context shadow writes to fail
- later guest-thread lookup to fail

These are not root causes. They are symptoms of a transaction that had
already been aborted earlier in the same inquiry flow.

## New leading trigger shape

The most diagnostic single finding from the narrowed worker log window
is the inquiry shape associated with the first failed save:

- parser output identified the message as `platform='airbnb'`
- `parser_source='ota_parser_airbnb_plain'`
- `guest_email='resolutions@airbnb.com'`
- `message_chars=0`
- the "property external id" in later logs was effectively a subject
  string:
  `Airbnb Reimbursement Request [CLSF-05819862] [HMTAZXMB3N]`

This suggests an Airbnb operations / reimbursement / automation email
was allowed through the inquiry path as if it were a guest inquiry.

That yields two separate findings:

### Finding A — Intake classification failure

An Airbnb operations email (`resolutions@airbnb.com`) was admitted to a
guest-inquiry processing path.

This intersects directly with the mixed-intake / non-guest traffic
problem documented in the 2026-05-04 addendum. A sender/domain
blocklist or allowlist at intake would likely have prevented this
message from reaching the worker flow at all.

### Finding B — Upstream worker path abort on malformed inquiry

Once that malformed inquiry entered the worker path, some earlier
Gmail / messaging-brain / rich-context operation raised and aborted the
transaction before pre-booking persistence ran.

This is the actual trigger hunt now. The pre-booking path is mostly
collateral damage.

## Current best hypothesis

The active within-inquiry trigger is now believed to be upstream of
pre-booking persistence:

- in the Gmail intake / messaging-brain / rich-context path
- on malformed Airbnb automation-shaped messages
- with recent `rich_context_shadow_store` behavior as a strong
  candidate area to inspect next

The application-side `knowledge_gaps` errors are still real, but they
may be parallel noise from a different worker path rather than the
causal root of the dropped-draft incident.

## Next trace direction

Do not resume by continuing static trace in `generate_inquiry_draft()`
or other pre-booking internals. That branch was productively cleared
but is no longer the lead.

Resume with this sequence:

1. Work backward from the first failed inquiry window:
   `2026-05-04 20:27:36Z` to `20:27:37Z`
2. Follow the malformed Airbnb reimbursement-shaped inquiry
3. Focus on Gmail / messaging-brain / rich-context code before
   pre-booking persistence
4. Find the first non-`InFailedSQLTransactionError` exception on that
   inquiry
5. Treat `rich_context_shadow_store` as a strong candidate because:
   - it appears in the fallout window
   - the code is recent
   - the migration head is `052_rich_context_shadow_observations`

## Open questions

- What exact statement first aborted the transaction for the malformed
  Airbnb reimbursement inquiry?
- Is the trigger a missing table, missing column, constraint
  violation, or another DB failure class entirely?
- Did all observed dropped drafts share the same malformed
  Airbnb-automation shape, or are there multiple trigger shapes?
- Should the fix sequence be:
  - intake hygiene first
  - upstream abort fix first
  - or both in parallel
- Which of the incompatible "gap" schemas is actually intended to
  survive long-term?

## Recovery / impact context

The operator is still manually replying to guest inquiries, so this
incident occurred during supervised shakedown rather than unsupervised
production autonomy. That reduces end-user urgency, but it does not
change the fact that:

- the system dropped drafts that should have persisted
- malformed non-guest traffic entered a guest-inquiry path
- transaction handling remained brittle in the face of bad inputs

## Related artifacts

- `docs/SESSION_RESUME_2026_05_05.md`
- `docs/PIPELINE_COORDINATION_ADDENDUM_2026_05_04.md`
- `docs/ARCHITECTURE_RECONCILIATION_TRACKER.md`

## Session continuation — gate rollout and topology drift

The second half of the 2026-05-05 session diverged from the original
within-inquiry trigger hunt into two parallel workstreams:

- shipping the `InboundMessageGate`
- resolving service topology drift that was reintroducing old inbox
  behavior in production

## InboundMessageGate built and deployed

In response to Finding A in the main incident note (intake
classification failure), an AI-first inbound message classifier was
designed, built, tested, and deployed.

Commit `8cf79a9` on `main` includes:

- `app/services/messaging_brain/inbound_message_gate.py` — gate service
  using the repo's existing httpx Anthropic pattern, model
  `claude-haiku-4-5-20251001`, classifying inbound email into
  `guest_message`, `operational_notification`, `marketing`,
  `bounce_or_system`, `unclear`
- `app/services/messaging_brain/inbound_classification_store.py` —
  isolated DB session for persisting classifications, never poisons
  shared transaction
- `db/migrations/versions/053_inbound_classifications.py` — migration
  with classification CHECK constraint, confidence range constraint,
  three indexes, no FKs by design
- Integration in `app/services/integrations/email_dispatch.py`
  `dispatch_pre_booking()` ahead of `load_property_context`
- Two feature flags in `app/services/feature_flags.py`:
  `INBOUND_MESSAGE_GATE_ENABLED` (default off),
  `INBOUND_MESSAGE_GATE_REVIEW_ALL` (default off, audit mode)
- Poller accounting in `gmail_inbox_poller.py` for new route outcomes:
  `pre_booking_gate_review`, `pre_booking_gate_skipped`,
  `pre_booking_gate_error`, with new counters `gate_review_routed`,
  `gate_skipped`, `gate_errors`
- Test coverage in
  `tests/unit/test_inbound_message_gate.py` and integration updates in
  `tests/unit/test_email_dispatch_prebooking_brain.py`
- Design doc in `docs/INBOUND_MESSAGE_GATE.md`

Validation completed:

- structural tests passed locally
- live Anthropic tests passed on 7 fixtures (Airbnb guest and
  operational cases plus Vrbo guest cases)
- code deployed to `oyvoda`
- migration `053_inbound_classifications` ran successfully on `oyvoda`
  via Railway predeploy

Gate rollout remains paused with both flags off. The gate is deployed
but inactive until service-topology cleanup is verified.

## Operator symptom clarified

During this session the operator reported that new inbounds were again
being marked read immediately on arrival.

This was traced to service drift rather than a new regression in the
current code:

- yesterday's read-state fix `1739c73` is present in current repo code
- `oyvoda` had the fix
- `oyvoda-worker` did not actually receive yesterday's or today's
  pushes, and was still running older poller code
- both services were polling Gmail, so whichever service won the race
  for a given Gmail message applied its own read-state behavior

That means:

- no new code regression was required to explain the operator complaint
- stale `oyvoda-worker` code was reintroducing the old
  "mark read on arrival" behavior
- the symptom was race-dependent and therefore inconsistent from one
  inbound to the next

## Service topology drift discovered

Railway service inspection established the following actual runtime
topology:

- `oyvoda` — API service, GitHub-source-connected, auto-deploys from
  `main`, runs `uvicorn app.main:app`, and in production runs the
  embedded Gmail poller (`run_gmail_polling_worker=True`) plus
  `RUN_EMBEDDED_BACKGROUND_WORKERS=true`
- `oyvoda-worker` — not GitHub-source-connected, manually/CLI deployed,
  also runs `docker/Dockerfile.api` and `uvicorn app.main:app`, with
  default `run_gmail_polling_worker=True`, so was also running the
  embedded Gmail poller. Stripped-down env compared to `oyvoda`
  (no `BASE_URL`, no public domain vars, no Escapia credential
  block). Private networking only.
- `oyvoda-beat` — real Celery beat scheduler, uses
  `docker/Dockerfile.worker`, starts
  `celery -A app.workers.celery_app:celery_app beat`. Schedules 10+
  tasks every 5 min including `poll-email-inboxes`,
  `poll-escapia-messages`, `check-unacked-alerts`,
  `check-escalation-slas`, `sync-pms-sessions`,
  `sync-pms-all-operators`, `void-stale-drafts`,
  `restore-expired_ooo`, `evaluate-proactive-triggers`. No Celery
  worker has been identified to consume these tasks.

Implications:

- `oyvoda-worker` was running pre-`1739c73` code and reintroducing
  the read-state regression on every Gmail poll
- The dedup gate at `gmail_processed_messages` prevented duplicate
  `pre_booking_inquiries` rows but did not prevent the wrong-version
  read-state side effects from the first processor in the race
- Yesterday's structural fix `7d09813` in `app/workers/tasks.py`
  targeted Celery code that no production runtime executes, since no
  Celery worker exists. The fix is correct code but does not protect
  any current production path
- "No duplicate rows" was not equivalent to "no duplicate polling"

## Stage 1 of topology cleanup completed

Decision: keep existing code architecture, clean up topology drift
(Path A, not architectural rebuild).

Stage 1 goal: stop duplicate Gmail polling without retiring services.

Actions taken:

- Set `RUN_GMAIL_POLLING_WORKER=false` on `oyvoda-worker` in Railway
- First redeploy attempt `2e85b0b5-8e00-4059-b807-dd4924dd5e86`
  failed in predeploy because Railway redeploy used a stale source
  snapshot without migration `053`
- Successful deploy via `railway up -s oyvoda-worker` from current
  repo as deployment `cc03cfcc-7077-4bc1-a805-3ef92cd53c90`

Verified after Stage 1:

- `oyvoda-worker` startup logs show
  `Gmail polling worker disabled for this web process` and
  `Embedded background workers disabled for this web process`
- `oyvoda` continues normal Gmail polling
- No `[GmailPoller]` activity from `oyvoda-worker` post-startup
- 24-hour historical query for duplicate `gmail_message_id` rows in
  `pre_booking_inquiries` returned no rows (consistent with
  `_is_already_processed` dedup gate having absorbed the second
  processor before row creation)

Stage 1 status: structurally complete. Operational verification
pending one fresh real inbound to confirm read-state preservation
end-to-end from the operator's perspective.

## New issue surfaced during Stage 1

`oyvoda-worker` post-Stage-1 logs contain:
`CRITICAL ... JWT_SECRET env var not set!`

This is not blocking gate work or Stage 1. Risk depends on whether
`oyvoda-worker` actually serves authenticated traffic, which has not
been confirmed.

## Pending work

In rough priority order:

1. Verify the operator's read-state complaint resolves on the next
   real inbound. If clean, mark Stage 1 operationally verified.
2. Address `JWT_SECRET` missing on `oyvoda-worker` — assess whether
   the service serves authenticated traffic.
3. Stage 2: prove or refute Celery worker absence. Strong hypothesis
   but not proven. Methods: check Redis queue depth for piling tasks,
   search wider infrastructure for any Celery-worker-shaped runtime.
4. Stage 3: audit each task in `celery_app.py` `beat_schedule`
   against embedded equivalents in `app/main.py`. Specifically not
   yet covered by embedded workers:
   `poll_escapia_messages_all_operators`, `check_unacked_alerts`,
   `check_escalation_slas`, `sync_pms_all_operators`,
   `void_stale_drafts_all_operators`, `restore_expired_ooo`. For
   each: keep, move to embedded, or retire.
5. Stage 4: retire `oyvoda-worker` and `oyvoda-beat` only after
   stages 2 and 3 prove safe. Connect remaining service to GitHub
   source for auto-deploy.
6. Fix gate read-state deviation: with `GATE_REVIEW_ALL=on`,
   `_process_one_message` currently calls `_mark_read` for
   `pre_booking_gate_skipped` regardless of audit mode. Should
   respect audit mode. Fix before any flag flip in audit mode.
7. Resume gate rollout after topology clean: phase 2 audit mode,
   then phase 3 selective suppression.
8. Original within-inquiry trigger hunt (the main subject of this
   incident note) remains open. Today's work addressed the intake
   side of the problem (gate) and the deployment side (topology),
   but the upstream Gmail / messaging-brain / rich-context abort on
   malformed inputs has not been fixed.
9. Schema drift cluster cleanup: decide which "gaps" schema is
   authoritative, retire dead-code branches in `kb_gap_manager.py`
   and `insight_engine.py` against schemas that don't exist in prod.
   Separate workstream.

## Conclusions

- The gate work is sound and deployed safely with flags off.
- The operator's read-state regression was not a new bug, but a
  race between `oyvoda` on fixed code and `oyvoda-worker` on stale
  code. Stage 1 removed that race.
- "No duplicate rows" did not mean "no duplicate polling." The
  dedup gate in `gmail_processed_messages` absorbed the second
  processor before inquiry creation, but the race still mattered
  because the first processor's side effects, especially read-state,
  still won.
- Original within-inquiry trigger hunt remains open and should be
  resumed after Stage 1 is operationally verified.
