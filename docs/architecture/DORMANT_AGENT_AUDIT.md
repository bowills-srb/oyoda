# Dormant Agent Audit — Phase 4.4.B

Date: 2026-05-18
Status: corrected against live code + production schema

## Summary

The revised Phase 4.4 brief identified several potentially dormant agents.
The codebase and production schema check changed that picture in a few
important ways:

- `KnowledgeCuratorAgent` was structurally wired but missing its review-queue
  table. That is a real dormant seam and is addressed in Phase 4.4.A.
- `OperatorLearningService` is not dormant in the way the brief assumed.
  Its caller path exists and its backing tables already ship in migration 018.
- `kb_gap_manager` is not dormant either; it is actively imported from live
  concierge paths, but it is backed by tables that do not exist in production.
  This makes it an active-but-misaligned subsystem, not safe dead code.
- `builder_agent.py` has no callers and is superseded by the live onboarding
  stack under `app/services/agents/onboarding/`.

## KnowledgeCuratorAgent

Current status:
- Input signal alive
- Review queue missing before Phase 4.4.A
- Daily Celery task already scheduled

Evidence:
- Production `concierge_knowledge_gaps` exists
- Production last-14-days row count: `190`
- Production `knowledge_gap_drafts` was missing before Phase 4.4.A
- Celery beat already includes `curate_knowledge_gaps`
- Operator API already exposes draft list / approve / reject routes

Decision:
- `WIRED`

Rationale:
- This subsystem had immediate value trapped behind one missing table and
  tenant-scoping cleanup. Phase 4.4.A is the right fix.

## OperatorLearningService

Current status:
- Active caller path
- Active schema
- Nightly rebuild task remains valid

Evidence:
- `record_approval`, `record_edit`, and `record_rejection` are called from
  `app/api/v1/endpoints/operator_prebooking.py`
- The same learning calls also appear in
  `app/api/v1/endpoints/operator_onboarding.py`
- Production tables exist:
  - `operator_draft_events`
  - `operator_learned_preferences`
  - `platform_learning_events`
  - `platform_intelligence`
- Migration source exists in `018_pre_booking_pipeline.py`
- Celery beat includes `rebuild_platform_intelligence_task`

Decision:
- `ACTIVE — NO RETIRE/DEFER ACTION`

Rationale:
- The revised brief's assumption that this subsystem had no caller and no
  schema is outdated. It is a live learning path and should stay scheduled.

## kb_gap_manager

Current status:
- Live imports
- Missing backing tables
- Needs dedicated remap or retirement follow-up

Evidence:
- Imported from:
  - `app/services/concierge/pre_booking_auto_send.py`
  - `app/services/concierge/pre_booking_handler.py`
  - `app/services/concierge/ai_concierge.py`
  - `app/services/messaging_brain/orchestrator.py`
- Production tables are missing:
  - `kb_gaps`
  - `operator_gap_settings`

Decision:
- `DEFER — REMAP OR QUARANTINE IN FOLLOW-UP`

Rationale:
- This code cannot be safely retired in Phase 4.4.B because it is still
  imported from active concierge flows.
- It also cannot be called healthy in its current state because its storage
  contract is absent in production.
- The next step should be a targeted follow-up that either:
  1. remaps it onto `concierge_knowledge_gaps` / `operator_settings.extra`, or
  2. removes its live imports and replaces them with the canonical gap path.

## builder_agent.py

Current status:
- No callers
- Superseded by live onboarding stack

Evidence:
- No codebase callers of `BuilderAgent`
- Active onboarding path lives in
  `app/services/agents/onboarding/onboarding_agent.py`
- API onboarding endpoints use the newer onboarding agent directly

Decision:
- `RETIRED`

Rationale:
- Keeping an unused legacy onboarding builder beside the active onboarding
  stack only increases discovery noise and future audit churn.
