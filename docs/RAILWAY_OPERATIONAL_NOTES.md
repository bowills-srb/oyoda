# Railway Operational Notes

Last updated: 2026-05-13

This document is the permanent operational record for how Railway is configured for Oyvoda, what each service is supposed to run, how deployments actually behave, and what was learned during the 2026-05-12 / 2026-05-13 production incident investigation, recovery, and inbox parsing remediation.

## 1. Service Architecture

Oyvoda currently runs as a multi-service Railway deployment:

- `oyvoda`: API/web service
- `oyvoda-worker`: Celery worker
- `oyvoda-beat`: Celery beat scheduler
- `Redis`: shared broker / cache / results backend
- `function-bun`: template/example service, not part of the main application path

Each Railway service has a distinct role and must remain mapped to the correct manifest. If a service falls back to the wrong manifest, Railway can successfully deploy the wrong process type.

### Intended roles

- `oyvoda`
  - Serves the FastAPI application
  - Runs `uvicorn`
  - Handles web/API traffic

- `oyvoda-worker`
  - Runs Celery workers
  - Consumes tasks from the application queues
  - Executes background jobs and integrations

- `oyvoda-beat`
  - Runs Celery beat only
  - Schedules periodic tasks
  - Must not run the API server

- `Redis`
  - Celery broker / backend and shared cache layer

- `function-bun`
  - Railway template/example service
  - Not part of the API/worker/beat production path

## 2. Per-Service Railway Configuration

Known-good service-to-manifest mapping:

### `oyvoda`

- Config-as-code file: `/railway.toml`
- Dockerfile: `docker/Dockerfile.api`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 2`
- Role: API/web service

### `oyvoda-worker`

- Config-as-code file: `/railway-worker.toml`
- Dockerfile: `docker/Dockerfile.worker`
- Start command:

```sh
sh -c 'celery -A app.workers.celery_app:celery_app worker --loglevel=INFO --queues=ingestion,concierge,operations --hostname=multiq@%h --concurrency=${CELERY_INGESTION_CONCURRENCY:-6} --prefetch-multiplier=1'
```

- Role: Celery worker

### `oyvoda-beat`

- Config-as-code file: `/railway-beat.toml`
- Dockerfile: `docker/Dockerfile.worker`
- Start command:

```sh
celery -A app.workers.celery_app:celery_app beat --loglevel=INFO
```

- Role: Celery beat scheduler

### Important rule

If `oyvoda-worker` or `oyvoda-beat` are not explicitly tied to their own Railway config files, Railway can fall back to `/railway.toml`, which is the API manifest. A deploy can then succeed while starting `uvicorn` instead of Celery.

## 3. Required Environment Variables Per Service

These are the practical requirements observed from production behavior and service startup paths.

### Common runtime requirements

- `DATABASE_URL`
  - Required by any service that touches the database
  - Required for services that run Alembic on boot

- `REDIS_URL`
  - Required by Celery worker and beat
  - Required by services using Redis-backed session/task state

### `oyvoda` API

Required or strongly expected:

- `DATABASE_URL`
- `REDIS_URL`
- `JWT_SECRET`
  - Missing this causes security warnings and session invalidation behavior on restart

Commonly present because the API can exercise these paths:

- `ANTHROPIC_API_KEY`
- `GROQ_API_KEY`
- Gmail / OAuth credentials
- storage and platform integration credentials
- observability keys as applicable

Behavior flags observed in production:

- `RUN_EMBEDDED_BACKGROUND_WORKERS=true` on the API service was observed during the 2026-05-12 audit

### `oyvoda-worker`

Required:

- `DATABASE_URL`
- `REDIS_URL`

Required for LLM-using task paths:

- `ANTHROPIC_API_KEY`
- `GROQ_API_KEY` if Groq-backed code paths are expected

Required for integration task paths actually in use:

- Gmail / OAuth credentials
- storage / PMS / integration credentials as needed by active tasks

Observed on the known-good worker:

- `RUN_GMAIL_POLLING_WORKER=false`

Important note:

- The inbox polling kill switch added in commit `4cf2f76d87b432d947f7de7b62aac2b618313466` does not require a new env var to disable polling.
- Poll scheduling remains off by default unless `ENABLE_INBOX_POLL_SCHEDULE=true` is explicitly set.

### `oyvoda-beat`

Required:

- `DATABASE_URL`
- `REDIS_URL`

Not all application secrets need to be present on beat, because beat schedules work but does not perform the worker execution itself.

Important note:

- Beat should not require API-only settings like `JWT_SECRET` just to schedule tasks.
- If beat starts as `uvicorn`, that is a misdeployment, not a valid requirement signal.

### `Redis`

- Railway-managed Redis service variables only

### `function-bun`

- Template/example service variables only

## 4. Deployment Mechanism Reality

This section records the behavior observed directly during incident recovery.

### What "Redeploy" does not mean

The Railway dashboard `Redeploy` action does not guarantee a rebuild from latest source code.

In practice:

- It can redeploy the existing build artifact / existing deployment configuration
- It does not by itself fix a wrong service-to-manifest mapping
- A service can keep redeploying the wrong process type if its config mapping is wrong

### Reliable ways to rebuild from source

- `railway up -s <service>` via CLI
- Push to `main` on a GitHub-connected service with auto-deploy enabled

### Secret rotation contract

Railway secret changes are not treated as complete until all three app services
boot on a new config revision marker.

Required env on `oyvoda`, `oyvoda-worker`, and `oyvoda-beat`:

- `OYVODA_CONFIG_REVISION` (preferred), or `CONFIG_REVISION`, or `SECRET_EPOCH`

Operational rule:

1. Bump the revision marker when rotating any env-backed credential
2. Redeploy API, worker, and beat together
3. Verify the live revision via the ops infra summary endpoint

The repository now enforces this at Railway startup with
`scripts/railway_bootstrap.py`:

- boot fails if no revision marker is set
- boot fails if critical secret fingerprints changed without a revision bump
- the current revision and hashed secret fingerprints are persisted in Redis so
  the next boot can detect an unversioned rotation

Verification detail:

- `deployment_runtime` shows the API process-local snapshot
- `deployment_runtime_signals.services.<service>.payload` shows the Redis-backed
  boot payload for `oyvoda`, `oyvoda-worker`, and `oyvoda-beat`
- prefer the Redis-backed signals when confirming all three services restarted
  onto the expected revision, since Railway deploy-log search may not show the
  bootstrap print line consistently

### Config-as-code reality

Config-as-code path requires a GitHub-connected service to function correctly in the expected source-driven deployment flow.

Known-good pattern:

- service connected to GitHub repo `huntermckenzie/oyvoda`
- production branch set to `main`
- service-specific config file explicitly set

For this repo:

- `oyvoda` -> `/railway.toml`
- `oyvoda-worker` -> `/railway-worker.toml`
- `oyvoda-beat` -> `/railway-beat.toml`

If `oyvoda-worker` or `oyvoda-beat` are disconnected from GitHub and/or missing their explicit config-as-code path, fresh deployments can fall back to the root API manifest.

## 5. Deployment Verification Standard

`SUCCESS` in Railway is necessary but not sufficient.

Every production deployment should be verified against all of the following:

1. Running commit hash matches the expected git ref
2. Boot completes successfully
3. Correct process is running
4. Expected new behavior is observable in production logs

### Process checks by service

- `oyvoda`
  - should run `uvicorn`
  - should not start as Celery worker or beat

- `oyvoda-worker`
  - should run Celery worker
  - should not start `uvicorn`

- `oyvoda-beat`
  - should run Celery beat
  - should not start `uvicorn`

### Example verification questions

- Does Railway report the expected config file?
- Does Railway report the expected Dockerfile?
- Does the start command match the service role?
- Do runtime logs show the expected process banner?
- Do logs show the new code path / new behavior actually taking effect?

## 6. 2026-05-12 Incident Summary

### Spend / behavior summary

Inbox polling had been repeatedly driving Anthropic activity after `ANTHROPIC_API_KEY` was added on 2026-05-07.

### Application root cause

The inbox poller could repeatedly revisit the same messages because:

- `LLMEmailExtractor` parse-failed messages were not being marked as terminally seen
- fallback retrieval from recent inbox state could pull the same messages again every 5 minutes

### Code fixes

Dedupe and kill-switch fixes landed across these commits:

- `594d8e8`
- `579889a`
- `4cf2f76d87b432d947f7de7b62aac2b618313466`

Intent of those fixes:

- persist Gmail message processing state in `gmail_processed_messages`
- treat multiple outcomes as terminal states rather than "retry forever"
- disable inbox poll scheduling by default unless explicitly re-enabled

### Infrastructure root cause

`oyvoda-worker` and `oyvoda-beat` were found in a drifted Railway state:

- not correctly connected to GitHub source in the intended source-driven flow
- missing or not actively applied service-specific config-as-code paths
- fresh deployments therefore fell back to `/railway.toml`
- `/railway.toml` is the API manifest, so new deployments became `uvicorn` API services instead of worker / beat

### Infrastructure fix

The working pattern restored on 2026-05-12 was:

- connect each service to GitHub repo `huntermckenzie/oyvoda`
- track branch `main`
- explicitly set:
  - `oyvoda-worker` -> `/railway-worker.toml`
  - `oyvoda-beat` -> `/railway-beat.toml`
- deploy from source so Railway rebuilds with the correct manifest

## 7. Known-Good Deployment IDs As Of 2026-05-12

### `oyvoda-worker`

- Deployment ID: `ced9a0cc-0964-44f5-9b92-59ee0acb05ec`
- Status: `SUCCESS`
- Commit: `4cf2f76d87b432d947f7de7b62aac2b618313466`
- Config file: `/railway-worker.toml`

### `oyvoda-beat`

- Deployment ID: `d42d1b5d-926f-4cb8-8a73-d5decba6962e`
- Status: `SUCCESS`
- Commit: `4cf2f76d87b432d947f7de7b62aac2b618313466`
- Config file: `/railway-beat.toml`

Verification observed after these deployments:

- beat scheduled legitimate periodic tasks
- beat did not schedule `poll-email-inboxes`
- worker processed legitimate scheduled tasks
- worker showed no new `LLMEmailExtractor` or Anthropic inbox-poll activity in the verification window

## 8. Operational Discoveries

These points were learned directly from live Railway behavior.

- Service config can drift away from what an older running deployment is currently doing.
- Build and Deploy panels reflect the active deployment, not necessarily a pending config change.
- Config-as-code changes in this UI apply through the deploy flow; there is no separate "save now, apply later" mental model to rely on.
- A service can be healthy from Railway's perspective while still running the wrong process for its intended role.
- A successful deployment is not the end of verification. Runtime logs are part of the deploy checklist.

## 9. Recommended Future Deploy Checklist

Before deploying:

1. Confirm service is connected to GitHub repo `huntermckenzie/oyvoda`
2. Confirm branch is `main`
3. Confirm config-as-code file is correct for the service
4. Confirm the service role matches the expected manifest

After deploying:

1. Confirm deployment `SUCCESS`
2. Confirm commit hash
3. Confirm config file and Dockerfile
4. Confirm runtime startup banner
5. Confirm expected post-deploy behavior in logs

For `oyvoda-beat` specifically:

1. Confirm beat startup line appears
2. Confirm legitimate periodic tasks fire
3. Confirm `poll-email-inboxes` is absent unless intentionally re-enabled

For `oyvoda-worker` specifically:

1. Confirm worker ready banner appears
2. Confirm tasks are consumed normally
3. Confirm no unexpected repeated LLM / inbox polling activity appears

## 10. 2026-05-13 Parsing Architecture Outcome

The inbox path was deliberately narrowed and hardened before polling was re-enabled.

### Final inbox architecture

Connected inbox mail now flows through this chain:

1. deterministic Layer 1 non-guest filtering
2. deterministic message-type classification
3. targeted routing by message type
4. LLM extraction only for inquiry-shaped mail that still needs it

### What this means in practice

- obvious non-guest mail is dropped before any LLM call
- booking events are handled without LLM extraction
- direct website inquiry forms use the deterministic direct form parser first
- Airbnb inquiry extraction now relies on the new deterministic-first plus Groq-primary path rather than the old brittle Airbnb parsers
- Groq is primary for inbox extraction
- Anthropic remains available as fallback when Groq fails

### Live routing decisions as of 2026-05-13

- `ota_parser_airbnb` and `ota_parser_airbnb_plain`
  - removed from the live routing chain
  - code remains in the repo for now, but is intentionally unwired

- `ota_parser_vrbo` and `ota_parser_vrbo_plain`
  - retained in source
  - not moved ahead of the current LLM path at current volume

- `direct_website_form_parser`
  - retained in the live path
  - still the preferred deterministic parser for inquiry-shaped website form mail

## 11. Phase A-F Timeline

### Phase A: deterministic non-guest filtering

- Added a dedicated non-guest pattern library
- Inserted deterministic non-guest classification ahead of the LLM path
- Validated against historical production-failure samples

Primary commits:

- `f369455` `feat(inbox): non-guest pattern library for deterministic filtering`
- `cce4a04` `feat(inbox): additional non-guest patterns from phase e replay findings`

### Phase B: Groq-primary inbox extraction

- Reversed provider order in `LLMEmailExtractor`
- Inbox extraction now prefers Groq first and falls back to Anthropic only on failure

Primary commit:

- `9203398` `fix(inbox): groq primary, anthropic fallback in llm extractor`

### Phase C: deterministic message-type classification

- Added conservative message-type classification before the LLM path
- Booking events are routed deterministically
- Ambiguous guest inquiry mail still falls through safely to LLM

Primary commit:

- `bf38471` `feat(inbox): deterministic message type classification before llm extraction`

### Phase D: retire Airbnb legacy parsers from live routing

- Removed legacy Airbnb parser invocation from the live router
- Left the old parser code in source for now, but unwired

Primary commit:

- `3a9ee1c` `refactor(inbox): retire airbnb legacy parsers, rely on phase a/b/c chain`

### Phase E: dry-run replay verification

- Added a replay task that runs the live parsing chain against recent production messages without making LLM calls
- Verified the route distribution on real Beach Habitats inbox traffic

Primary commits:

- `425fc67` `feat(inbox): add dry-run replay task for parsing chain`
- `bcff16b` `fix(inbox): normalize replay dry-run provider and joins`

Observed 100-message replay distribution after tightening:

- `75` `non_guest`
- `16` `llm_route`
- `6` `deterministic_direct_parser`
- `2` `booking_event`
- `1` `vendor_ops`

Critical result:

- no real guest inquiries were observed landing in `non_guest` or `booking_event`

### Phase F: poller re-enable and live verification

- Re-enabled `ENABLE_INBOX_POLL_SCHEDULE=true` on `oyvoda-beat`
- Initially hit a runtime import bug, then fixed it
- Re-ran with live inbox polling active
- Verified clean processing, Groq-primary ingress, and draft-hold behavior

Primary fix commit for retry:

- `6cf31e9` `fix(inbox): missing LLMEmailExtractor import in gmail_inbox_poller`

Live result:

- inbox poller active
- Groq primary confirmed at inbox ingress
- no autonomous guest sends observed
- pre-booking drafts held for operator review

## 12. Known-Good Deployments As Of 2026-05-13

### `oyvoda-worker`

- Deployment ID: `acf38e1f-b7fb-4fc4-ab19-1a020690e30f`
- Status: `SUCCESS`
- Commit: `6cf31e9d790091a8d93f8e291a59792a4efb1108`
- Config file: `/railway-worker.toml`
- Dockerfile: `docker/Dockerfile.worker`
- Runtime process: Celery worker

### `oyvoda-beat`

- Deployment ID: `78948707-4fbc-4e29-867d-e7744dd60081`
- Status: `SUCCESS`
- Config file: `/railway-beat.toml`
- Dockerfile: `docker/Dockerfile.worker`
- Runtime process: Celery beat
- Important env state: `ENABLE_INBOX_POLL_SCHEDULE=true`

### Live behavioral verification

Observed during the 2026-05-13 monitoring window:

- beat was actively scheduling `poll-email-inboxes`
- worker was consuming inbox poll tasks normally
- first successful backlog-style cycle reported:
  - `found=25`
  - `processed=6`
  - `new_pending_inquiries=2`
  - `non_guest_skips=8`
  - `errors=0`
- a later steady-state cycle reported:
  - `found=1`
  - `processed=0`
  - `non_guest_skips=1`
  - `errors=0`
- a later inquiry cycle showed:
  - Groq success at inbox ingress
  - draft created and held for review
  - no runtime parser failure

## 13. Phase F Safety Verification

### Auto-send safety

Beach Habitats remained on hold-for-review behavior during the re-enable window.

Observed live indicators:

- no `operator_pre_booking_policies` rows were present for Beach Habitats
- no `property_rollout_phases` rows were present for Beach Habitats
- application fallback behavior remained `ApprovalMode.REQUIRED`
- live logs showed:
  - `approval mode overridden to required`
  - `decision=hold`
  - `draft ... held for required approval`

No autonomous outbound guest send was observed during the monitored poll cycles.

### Groq-primary verification

At inbox ingress, live `LLMEmailExtractor` logs showed:

- `provider=groq`
- `fallback_fired=false`

Anthropic traffic was still visible downstream in broader concierge / draft-review paths, but not as the primary inbox-ingress parser in the observed cycles.

### Draft quality spot-check

Two held drafts were spot-checked during the first successful run:

- one Airbnb early-check-in draft
- one direct availability inquiry draft

Both were reasonable and conservative enough to remain safe for operator review, with no auto-send behavior.

## 14. Operational Lessons Reinforced

- Railway config-as-code only works predictably when the service is GitHub-connected and the correct file path is actively applied through the deploy flow.
- A service can show correct settings in the dashboard while a building deployment briefly reports incomplete metadata; transient build-state metadata should not be treated as final deployment truth.
- Live verification must include runtime log behavior, not just successful deployment state.
- The inbox path needs integration-level verification, not only parser unit tests. A runtime import bug survived focused unit coverage and only appeared when the real poller path was exercised.
- Replay verification against real production traffic was the key safety gate before re-enabling polling.

## 15. Carry-Forwards

Priority order reflects current operational risk, not code neatness.

### Medium

- Add an integration test that exercises the real inbox poller path end-to-end with a stubbed extractor.
  - Goal: catch runtime wiring issues like the `LLMEmailExtractor` import bug before production.

### Low-Medium

- Fix `topic_classifier` coroutine pre-creation in `app/services/concierge/topic_classifier.py`.
  - Current warning: `_call_claude` coroutine created but never awaited when Groq succeeds first.
  - Observed impact: warning noise, not functional break, but should be cleaned up.

### Low

- Fix transaction handling around `rich_context_shadow` writes.
  - Current warning: `InFailedSQLTransactionError`
  - Observed impact: observability / shadow telemetry only, not draft generation failure.

- Remove unwired Airbnb legacy parser code if it remains unused for 60+ days.

- Improve dashboard UX density / information presentation in the operator-facing surface.

## 16. Session Summary: 2026-05-12 / 2026-05-13

### Commits landed

- `19` commits landed during the session window beginning 2026-05-12

Most important commits in the remediation sequence:

- `4cf2f76` disable inbox polling by default
- `f369455` add deterministic non-guest filtering
- `9203398` make Groq primary for inbox extraction
- `bf38471` add deterministic message-type classification
- `3a9ee1c` retire Airbnb legacy parsers from live routing
- `425fc67` and `bcff16b` add and fix replay verification
- `cce4a04` tighten patterns from replay findings
- `6cf31e9` fix live poller import bug uncovered during re-enable

### Architectural change summary

Before remediation:

- inbox polling could repeatedly revisit failed messages
- worker / beat service config had drifted away from intended manifests
- inbox parsing was spending too much on Anthropic and routing too much noise into the LLM path

After remediation:

- worker and beat are restored to correct Railway manifests
- inbox polling is back on intentionally, not accidentally
- deterministic non-guest filtering removes most noise before any LLM call
- deterministic message-type classification narrows when LLM is used
- Groq is the primary inbox extraction provider
- Airbnb legacy parsers are removed from the live routing chain
- pre-booking drafts remain held for review

### Cost trajectory summary

Before remediation:

- repeated inbox polling was a real Anthropic spend driver
- production logs showed repeated parser retries and fallback behavior

After remediation:

- replay and live monitoring show most mail now exits on deterministic paths
- observed live inbox-ingress LLM calls were Groq-primary
- Hunter's live balance watch remained the correct final guardrail for exact Anthropic spend confirmation

### Closing state

Phase F is considered complete.

The system is now in a materially safer state than it was at the start of the incident window:

- correct service manifests
- poller intentionally enabled
- no autonomous send observed
- deterministic-first routing in place
- Groq-primary inbox extraction verified live
