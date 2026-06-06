# Worker Tier Status

Date: 2026-05-07

This note records the current worker-tier truth after the attempted normalization coverage tripwire rollout on 2026-05-07.

It is a status document, not a remediation plan.

## Prior Audit Trail

The relevant prior artifacts are:

- [docs/INFRASTRUCTURE_TOPOLOGY_2026_05_02.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/INFRASTRUCTURE_TOPOLOGY_2026_05_02.md:1)
- [docs/INCIDENT_2026_05_05_DROPPED_DRAFTS.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/INCIDENT_2026_05_05_DROPPED_DRAFTS.md:340)
- `cf868ea` `Document 2026-05-02 production topology snapshot`

Those artifacts already established three important facts:

1. `oyvoda` was running the embedded Gmail poller in-process.
2. `oyvoda-worker` had drifted into an API-shaped `uvicorn` service rather than a real Celery worker.
3. `oyvoda-beat` was a real Celery beat scheduler, but no actual Celery worker had been proven to consume its queues.

## What We Verified Tonight

### Repo state still models two different background mechanisms

The current repo still contains both:

- embedded in-process background workers in [app/main.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/main.py:646)
- Celery beat/tasks in [app/workers/celery_app.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/workers/celery_app.py:1) and [app/workers/tasks.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/workers/tasks.py:1)

Relevant config defaults in [app/core/config.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/core/config.py:156):

- `run_embedded_background_workers = False`
- `run_gmail_polling_worker = True`

Relevant startup wiring in [app/main.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/main.py:646):

- the Gmail polling worker can run in the API process
- the embedded background worker bundle can also run in the API process

So the codebase has not converged on one single, unambiguous background execution surface.

### Current Railway state

As of the end of the session:

- `oyvoda`
  - service status: `SUCCESS`
  - deployment id: `c45756f9-a296-4b28-ac54-dac8a9242f16`
  - commit hash: `f9965b7a99f48b9f1d5d446d96f8d2874abf61ad`
  - commit message: `feat(monitoring): add normalization coverage tripwire`

- `oyvoda-beat`
  - service status: `FAILED`
  - deployment id: `a8892dbd-27c5-4cf7-b9f2-86d1a4d2fc30`
  - stable failure state; not left building

- `oyvoda-worker`
  - service status: `SUCCESS`
  - deployment id: `833ee156-a4ca-4f1d-b8aa-88ce008d3952`
  - deployment manifest shows:
    - `docker/Dockerfile.api`
    - `uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 2`

This matters because the worker service that is now live is still API-shaped, not Celery-worker-shaped.

## What This Means For Tonight's Tripwire

Commit `f9965b7` added a normalization coverage tripwire:

- code location: [app/services/messaging/coverage_monitor.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging/coverage_monitor.py:1)
- periodic wiring: [app/workers/celery_app.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/workers/celery_app.py:37) and [app/workers/tasks.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/workers/tasks.py:650)

The code exists in the repo and the API service has the commit.

But the tripwire was wired to the Celery beat/task surface. Because worker-tier topology is still unresolved, we cannot honestly call the tripwire operationally live.

The correct status is:

- tripwire exists in code
- tripwire is committed and pushed
- tripwire reached the API service
- tripwire is **not yet verified as an executing production monitor**

## The Key Finding

There is no clean evidence that `oyvoda-worker` was deliberately consolidated into `oyvoda`.

The stronger read is:

- `oyvoda` became an effective runtime for some background behavior through embedded workers
- `oyvoda-worker` drifted into a second API-shaped service
- `oyvoda-beat` still exists as a scheduler
- a real Celery worker remains unproven

So the active problem is not "choose between old worker tier and new API-only architecture."

The active problem is "production still contains mixed and partially drifting background execution paths."

## Overnight Production Risk

Two facts should be carried forward explicitly:

1. `oyvoda-worker` is now live again as an API-shaped service.
2. We verified the relevant runtime flags before closing:
   - `oyvoda`
     - `RUN_EMBEDDED_BACKGROUND_WORKERS=true`
     - `RUN_GMAIL_POLLING_WORKER` unset, so code default applies: `true`
   - `oyvoda-worker`
     - `RUN_GMAIL_POLLING_WORKER=false`
     - `RUN_EMBEDDED_BACKGROUND_WORKERS` unset, so code default applies: `false`

So the specific duplicate-poller overnight risk was checked and is not present in the current service-level variable configuration. `oyvoda-worker` remains topology debt, but it is not configured tonight to run the embedded Gmail poller or the embedded background-worker bundle.

`oyvoda-beat` being failed is acceptable for tonight only in the narrow sense that it is stable and not actively churning. It does not mean the worker-tier question is resolved.

## Unresolved Questions

1. Is there any real Celery worker consuming the queues that `oyvoda-beat` schedules?
2. Is `oyvoda-worker` currently configured with `RUN_GMAIL_POLLING_WORKER=false` and `RUN_EMBEDDED_BACKGROUND_WORKERS=false`, or did tonight's redeploy change that behavior?
3. Which periodic/operational jobs are actually executed today:
   - API embedded workers
   - Celery beat + worker
   - some mix of both
4. Should `oyvoda-worker` and `oyvoda-beat` be:
   - repaired into a real worker tier
   - retired in favor of an API-embedded approach
   - or split by responsibility in some third way

## Bottom Line

Worker-tier topology remains unresolved.

That unresolved topology now blocks:

- making the normalization coverage tripwire operationally live
- designing Item 2 as if the periodic/background execution surface were settled
- trusting Celery-based monitoring additions without first proving what executes them
