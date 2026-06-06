# Infrastructure Topology Snapshot -- 2026-05-02

Investigation snapshot captured during the Beach Habitats pre-booking
brain rollout. This is a runtime topology report, not a design doc and
not a fix proposal.

The goal is to record what is actually running in production tonight,
what code paths those processes execute, and what that means for the
rollout and for follow-up infrastructure work.

## 1. Current Actual Runtime Topology

Observed Railway services on the production canvas:

- `oyvoda`
- `oyvoda-beat`
- `oyvoda-worker`
- `Redis`
- `function-bun`
- `redis-volume`

Only the first three were inspected directly in this session.

### `oyvoda` (API)

- Railway source: GitHub-connected
- Repo / branch: `huntermckenzie/oyvoda`, branch `main`
- Auto-deploy: enabled
- Build config: `docker/Dockerfile.api`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 2`
- Service ID: `b348fbfa-c069-4e18-95d4-8c6915c82fe9`
- Deployment ID: `cd2ffc4f-0583-4585-8c38-eed2f6820b13`
- Live process inspection:
  - PID 1 command: `/usr/local/bin/python3.11 /usr/local/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 2`
  - Process name: `uvicorn`
- Git metadata in live env:
  - `RAILWAY_GIT_BRANCH=main`
  - `RAILWAY_GIT_COMMIT_SHA=a55715e2a0a0b1ad987a00afd7b9f60153fb2119`
  - `RAILWAY_GIT_COMMIT_MESSAGE=Session 14 hotfix: fix feature flag resolver reads`

Conclusion:

- `oyvoda` is the only inspected service definitively running the
  resolver hotfix from `a55715e`.

### `oyvoda-beat`

- Railway source: not connected to GitHub
- Deploy mechanism: CLI-based service deploys
- Root directory: `/`
- Build config: `docker/Dockerfile.worker`
- Start command: `celery -A app.workers.celery_app:celery_app beat --loglevel=INFO`
- Service ID: `826b3385-de06-4ac6-a31a-3cd5326328cb`
- Deployment ID: `ed93f445-01cf-4bdc-b94d-3aa6179889c7`
- Live process inspection:
  - PID 1 command: `/usr/local/bin/python3.11 /usr/local/bin/celery -A app.workers.celery_app:celery_app beat --loglevel=INFO`
  - Process name: `celery`

Conclusion:

- `oyvoda-beat` is a real Celery beat scheduler.

### `oyvoda-worker`

- Railway source: not connected to GitHub
- Deploy mechanism: CLI-based service deploys
- Root directory: `/`
- Build config: `docker/Dockerfile.api`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 2`
- Service ID: `05adbbaf-81c4-498c-be09-bf4956f3da61`
- Deployment ID: `710e0954-e1ff-499c-8e5a-d0a411f16fa3`
- Live process inspection:
  - PID 1 command: `/usr/local/bin/python3.11 /usr/local/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 2`
  - Process name: `uvicorn`
- No Git SHA metadata present in the live environment

Conclusion:

- `oyvoda-worker` is not a Celery worker. It is a second API-style
  process built from the API Dockerfile and started with the API command.

### Uninspected services

- `Redis`: visible on the Railway canvas as online; not inspected beyond
  service presence.
- `function-bun`: visible on the Railway canvas as sleeping; not
  inspected.
- `redis-volume`: visible as the attached Redis volume; not inspected.

## 2. How Polling Actually Works Today

Beach Habitats inbox polling is happening in production.

The runtime path observed tonight is the API service's embedded Gmail
poller, not a Celery worker path.

### Embedded poller path

In [app/main.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/main.py:646),
the API lifespan startup checks `settings.run_gmail_polling_worker`. If
true, it starts `_gmail_polling_worker()` as an `asyncio` background
task:

- it acquires `/tmp/.oyvoda_gmail_worker_started`
- only the first uvicorn worker process in the container wins that lock
- the other uvicorn worker logs that it is the secondary process and does
  not start the Gmail poller

This matters because `uvicorn --workers 2` does not create two inbox
pollers per container. The lock gates the embedded poller down to one
process.

The poller loop sleeps for 300 seconds between runs:

- `await asyncio.sleep(300)` in
  [app/main.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/main.py:643)

### Why the API is polling in production

The relevant config defaults are:

- `run_embedded_background_workers: bool = False`
- `run_gmail_polling_worker: bool = True`

from
[app/core/config.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/core/config.py:156).

In the live `oyvoda` environment:

- `RUN_EMBEDDED_BACKGROUND_WORKERS=true`
- `RUN_GMAIL_POLLING_WORKER` is unset
- therefore the embedded Gmail poller remains enabled by default

The live API env also contains:

- `GMAIL_WATCHED_EMAIL=info@beachhabitats30a.com`

which is consistent with the Beach Habitats inbox being serviced through
this embedded API poller path.

### What writes `last_polled_at`

The heartbeat writer lives in
[app/services/integrations/gmail_inbox_poller.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/gmail_inbox_poller.py:974)
as `_record_poll_heartbeat(...)`.

That method updates:

- `last_polled_at`
- `last_poll_success`
- `last_poll_summary`
- `last_poll_error`
- `last_messages_found`
- `last_new_pending_inquiries`
- `last_query_mode`

on `operator_gmail_creds`.

That explains the production observations from tonight:

- `last_polled_at` advancing on a 5-minute cadence was real
- `last_poll_success=True` was real
- inbox health data was coming from the API's embedded Gmail poller

### Operational consequence

The Beach Habitats data plane is not broken. Inbox polling has continued
to function tonight because the API is doing it inline.

## 3. What Celery Is Actually Doing

`oyvoda-beat` is a real Celery beat scheduler. The schedule is defined in
[app/workers/celery_app.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/workers/celery_app.py:55).

Notable periodic tasks include:

- hourly operational snapshot refresh
- 15-minute proactive trigger evaluation
- 5-minute escalation SLA checks
- 5-minute Escapia polling
- 5-minute connected inbox polling
- hourly PMS sync
- daily retention and knowledge-gap jobs

Task routing in the same file sends inbox polling to the `ingestion`
queue:

- `app.workers.tasks.poll_connected_inboxes_all_operators` -> `ingestion`
- `app.workers.tasks.poll_connected_inbox_for_operator` -> `ingestion`

The task implementation is in
[app/workers/tasks.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/workers/tasks.py:852).
That task:

- queries `operator_gmail_creds`
- enqueues `poll_connected_inbox_for_operator.delay(...)`
- the per-operator task then runs `poller.poll()` and optional
  `poll_with_mode(query_mode="recent_inbox")`

### Current contradiction resolved

The reason inbox polling still works despite `oyvoda-worker` not being a
Celery worker is that the API's embedded Gmail poller is doing the work.

### Remaining Celery question

Among inspected Railway services, no actual Celery worker process was
found.

That means one of the following is true:

- Celery beat is enqueueing jobs to Redis and no inspected service is
  consuming them
- another uninspected service consumes those jobs
- some classes of work expected to run on Celery are currently not
  executing

This is an infrastructure question for follow-up. It is not required to
explain Beach Habitats' live inbox polling tonight because that behavior
is already explained by the embedded API poller.

## 4. Probable Intended Topology

The repository clearly models a split API / worker design:

- [docker/Dockerfile.api](/Users/dhuntermckenzie/Downloads/oyvoda/docker/Dockerfile.api)
  builds an API image and starts `uvicorn`
- [docker/Dockerfile.worker](/Users/dhuntermckenzie/Downloads/oyvoda/docker/Dockerfile.worker)
  builds a worker image and starts a Celery worker
- [app/workers/celery_app.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/workers/celery_app.py)
  defines task routing and beat schedules
- [app/workers/tasks.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/workers/tasks.py)
  contains inbox polling, PMS sync, and other periodic job logic

So the codebase expects a Celery worker tier to exist.

What production actually has tonight:

- one GitHub-linked API service
- one CLI-deployed Celery beat service
- one CLI-deployed service named `oyvoda-worker` that is really another
  API instance

This report does not determine whether:

- the worker tier was once correctly configured and later regressed, or
- it was never correctly wired in Railway

That is a follow-up historical question.

## 5. Open Questions

Questions that remain unanswered tonight:

1. Is there any uninspected Railway service or external worker process
   consuming Celery jobs?
2. What is the current Redis queue depth and retention behavior for the
   Celery queues, especially `ingestion` and `concierge`?
3. Which periodic tasks matter operationally if no Celery worker is
   consuming them, and how long has that been true?
4. Is the embedded API Gmail poller the intended production design, or a
   fallback path that quietly became the primary mechanism?
5. Do other Railway environments share the same service topology issue?
6. When did `oyvoda-worker` become an API-shaped service, and was that an
   intentional workaround or an accidental config drift?
7. How should Railway config-as-code be organized so service-specific
   build/start settings are auditable and cannot silently drift between
   CLI-deployed services?

## 6. What This Means For The Brain Rollout

The most important rollout-specific conclusion from tonight is:

- the Beach Habitats brain rollout is no longer blocked on the worker
  tier for inbox polling

Reason:

- the API service is the thing polling the Beach Habitats inbox tonight
- the API service is already on `a55715e`
- therefore the resolver fix is live on the process that is actually
  polling that inbox

Implication:

- the next qualifying Beach Habitats pre-booking inquiry should now be
  able to exercise the messaging-brain runtime path

This does not resolve the broader infrastructure issues around Celery,
Railway topology, or the phantom worker service. It only means those
issues are no longer on the immediate critical path for the next
Beach Habitats brain signal.

Operationally:

- the cutover verification bundle remains the right artifact to run on
  the next qualifying inquiry
- the watch window still starts on the first Q4 success row, not on the
  earlier flag-write timestamp

## 7. What Not To Decide Tonight

This snapshot intentionally does not decide:

- whether `oyvoda-worker` should be repointed to
  `docker/Dockerfile.worker`
- whether the embedded API poller should remain part of the production
  design
- whether `oyvoda-worker` should be deleted
- whether Celery should become the sole polling mechanism
- whether Redis queues should be drained, replayed, or ignored

Those are design and remediation decisions for a follow-up session.

Tonight's useful artifact is the empirical map:

- what each service is
- what each service is actually running
- what code path is really moving Beach Habitats inbox traffic right now
- which problem is in the rollout critical path, and which problems are
  broader infrastructure debt
