# Incident — 2026-05-05 Dropped Drafts (Part 2)

This is a continuation of `INCIDENT_2026_05_05_DROPPED_DRAFTS.md`.
It captures the second half of the 2026-05-05 session, which diverged
from the original within-inquiry trigger hunt into two parallel
workstreams: shipping the InboundMessageGate and resolving service
topology drift.

To merge into the main incident note, append this content to the end
of `INCIDENT_2026_05_05_DROPPED_DRAFTS.md` (after the existing
"Related artifacts" section).

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
- Test results: 13 passed plus 7 live tests passing all fixtures
  (2 Airbnb guest, 3 Airbnb operational, 2 Vrbo guest)

Migration 053 ran successfully via `oyvoda` `preDeployCommand` at
11:01 UTC.

Design captured in `docs/INBOUND_MESSAGE_GATE.md` with three-phase
rollout plan:

1. Code and migration deployed, flags off (current state)
2. `GATE_ENABLED=on` plus `GATE_REVIEW_ALL=on` for 24-48 hour audit
3. `GATE_ENABLED=on`, `GATE_REVIEW_ALL=off` for selective suppression

Gate rollout is paused pending topology cleanup so phase 1 verification
is meaningful in a single-runtime state.

## Operator-facing read-state regression resurfaced

During the gate work, the operator reported that inbound messages were
being marked read on arrival again — the same regression that
`1739c73` was supposed to fix the previous day.

This was not a new bug. The fix was correct in `oyvoda`'s code but
never reached `oyvoda-worker`, which had been running stale code for
an unknown duration.

## Service topology drift discovered

Investigation revealed substantial drift between Railway service
configuration and what each service actually does in production.

Three services in the Railway project:

- `oyvoda` — API and embedded background workers, runs
  `uvicorn app.main:app`, auto-deploys from `main` on push.
  Currently on `8cf79a9`. Settings default
  `run_gmail_polling_worker=True` and Railway env override
  `RUN_EMBEDDED_BACKGROUND_WORKERS=true`. Polls Gmail. Active.
- `oyvoda-worker` — configured as duplicate API service, not as a
  Celery worker. Uses `docker/Dockerfile.api` and starts
  `uvicorn app.main:app --workers 2`. Not GitHub-source-connected,
  manually deployed via CLI. No
  `RUN_EMBEDDED_BACKGROUND_WORKERS=true` override but inherits
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
  `restore-expired-ooo`, `evaluate-proactive-triggers`. No Celery
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
  snapshot without migration 053
- Successful deploy via `railway up -s oyvoda-worker` from current
  repo as deployment
  `cc03cfcc-7077-4bc1-a805-3ef92cd53c90`

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

`oyvoda-worker` post-Stage-1 logs:
`CRITICAL ... JWT_SECRET env var not set!`

Not blocking gate work or Stage 1. Risk depends on whether
`oyvoda-worker` actually serves authenticated traffic, which has
not been confirmed. Address tomorrow.

## Pending work

In rough priority order:

1. Verify operator's read-state complaint resolves on the next real
   inbound. If clean, mark Stage 1 operationally verified.
2. Address `JWT_SECRET` missing on `oyvoda-worker` — assess whether
   the service serves authenticated traffic.
3. Stage 2: prove or refute Celery worker absence. Strong hypothesis
   but not proven. Methods: check Redis queue depth for piling
   tasks, search wider infrastructure for any Celery-worker-shaped
   runtime.
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
   and `insight_engine.py` against schemas that don't exist in
   prod. Separate workstream.

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
