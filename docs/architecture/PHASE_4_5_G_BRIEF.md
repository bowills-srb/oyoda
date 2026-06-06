# Phase 4.5.G — Retire `kb_gap_manager.py` onto canonical knowledge-gap recording

Date: 2026-05-20  
Phase: 4.5.G

## Decision

`4.5.G` is a retirement ship, not a feature ship.

The legacy module [kb_gap_manager.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/kb_gap_manager.py)
still has live imports in both legacy and brain paths, but its backing tables
(`kb_gaps`, `operator_gap_settings`) do not exist in production. Meanwhile the
canonical knowledge-gap system already exists and is live:

- `ConciergeKnowledgeService.record_gap(...)` in
  [knowledge_service.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/knowledge_service.py)
- `concierge_knowledge_gaps` table
- dashboard and operator API reads from `concierge_knowledge_gaps`
- `knowledge_curator_agent.py` reads and resolves `concierge_knowledge_gaps`
- `gmail_inbox_poller.py` already records gaps through the canonical service

So `4.5.G` should not build a new brain gap system. It should delete the broken
legacy tiering subsystem by cutting the remaining callers over to the canonical
gap recorder that already exists.

This is the additive-only rule for `4.5.G`:

1. reuse existing canonical storage: `concierge_knowledge_gaps`
2. reuse existing canonical writer: `ConciergeKnowledgeService.record_gap(...)`
3. add at most one thin shared adapter for metadata shaping if needed
4. do **not** recreate `kb_gaps`, `operator_gap_settings`, `GapTier`, or a
   second knowledge-gap decision vocabulary in the brain

## What `4.5.G` retires

### Legacy subsystem to remove

- `app/services/concierge/kb_gap_manager.py`
  - `classify_gap(...)`
  - `_classify_category(...)`
  - `log_gap_async(...)`
  - `_persist_gap(...)`
  - `get_operator_gap_settings(...)`
  - `suppress_category(...)`
  - `unsuppress_category(...)`
  - `_save_gap_settings(...)`
  - `build_weekly_digest(...)`
  - `schedule_gap_log(...)`

### Remaining live callers today

Per code audit, the remaining callers are:

- [app/services/messaging_brain/orchestrator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/orchestrator.py)
- [app/services/concierge/pre_booking_auto_send.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/pre_booking_auto_send.py)
- [app/services/concierge/pre_booking_handler.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/pre_booking_handler.py)
- [app/services/concierge/ai_concierge.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/ai_concierge.py)

These callers currently depend on a gap logger that writes to absent tables.
`4.5.G` rewires them to the canonical service.

## What must NOT be duplicated

This is the main architectural guardrail for the ship.

Things that already exist and must be reused:

- canonical gap persistence:
  `ConciergeKnowledgeService.record_gap(...)`
- canonical operator-facing storage:
  `concierge_knowledge_gaps`
- canonical dashboard / curator readers:
  `operator_dashboard_api.py`, `knowledge_curator_agent.py`

Things that must **not** be recreated inside `messaging_brain/` or elsewhere:

- `GapTier`
- `GapCategory`
- `kb_gaps`
- `operator_gap_settings`
- weekly digest builder for suggest-tier gaps
- category suppression rules attached to the dead legacy schema

The tiering/suppression model is not “brain work waiting to migrate.” It is a
broken legacy subsystem over nonexistent tables. If operators want a ranked or
suppressed knowledge-gap workflow later, that is a new feature built on
`concierge_knowledge_gaps`, not a resurrection of `kb_gap_manager.py`.

## Current runtime truth

The canonical gap system is already the real one:

- Gmail poller uses `ConciergeKnowledgeService.record_gap(...)`
- Operator dashboard reads `concierge_knowledge_gaps`
- Knowledge curator reads and resolves `concierge_knowledge_gaps`

The stale subsystem is only surviving as a write-side helper in a few places.
That means `4.5.G` is mostly a call-site cleanup plus one shared adapter.

## Proposed implementation shape

### Deliverable 1 — Add one shared canonical gap-recording adapter

Add one narrow helper module, likely:

- `app/services/concierge/knowledge_gap_recorder.py`

This helper should:

- accept the current call-site inputs that `log_gap_async(...)` callers already
  have:
  - `tenant_id`
  - `question`
  - `answer_attempt`
  - `confidence_score`
  - `property_code`
  - `used_kb_chunks`
  - `was_deflected`
  - optional intent/topic/source metadata
- open or reuse a DB session appropriately
- call `ConciergeKnowledgeService.record_gap(...)`
- normalize metadata into the canonical `metadata_json` shape
- never block or crash the guest-facing pipeline

This helper is allowed because it is a thin adapter around the canonical
service, not a second gap system.

### Deliverable 2 — Cut brain orchestrator off `kb_gap_manager`

In [orchestrator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/orchestrator.py):

- remove imports of `get_operator_gap_settings` and `log_gap_async`
- replace `_emit_kb_gaps_from_decisions(...)` so it calls the new canonical
  gap-recording adapter
- keep the same emission semantics:
  - only emit when `missing_info` is non-empty after stub filtering
  - skip `RecommendedAction.AUTO_SEND`
  - fire-and-forget behavior
  - note on the audit record that gaps were emitted

Important: this ship does **not** change the brain’s decision semantics about
when a gap is emitted. It only changes where the write lands.

### Deliverable 3 — Cut remaining concierge-era callers to canonical recording

Replace `kb_gap_manager` imports/calls in:

- `pre_booking_auto_send.py`
- `pre_booking_handler.py`
- `ai_concierge.py`

with the same shared canonical adapter.

The goal is one write path for all surviving knowledge-gap emissions.

### Deliverable 4 — Delete `kb_gap_manager.py`

Once all imports are gone:

- delete `app/services/concierge/kb_gap_manager.py`
- verify no remaining code references it
- update the retirement plan from `LEGACY-ACTIVE` to `RETIRED`

## What `4.5.G` explicitly does NOT do

`4.5.G` does **not**:

- redesign the operator knowledge-gap UI
- add queue reintegration of knowledge-gap inquiries
- add Bayesian confidence decomposition
- add new suppression settings
- add a weekly digest system
- migrate `concierge_knowledge_gaps` to a new brain-specific table
- change the canonical `record_gap(...)` schema

If any of those become desirable, they are future feature ships on top of the
canonical gap system.

## Acceptance criteria

### Additive / non-duplicative architecture

- No new gap table is introduced.
- No new gap tier enum or second gap vocabulary is introduced.
- No new operator-gap-settings schema is introduced.
- All new writes target the existing `concierge_knowledge_gaps` system.
- Any new helper added in this ship is a thin adapter around
  `ConciergeKnowledgeService.record_gap(...)`, not a parallel subsystem.

### Runtime cutover

- `messaging_brain/orchestrator.py` no longer imports from
  `app.services.concierge.kb_gap_manager`.
- `pre_booking_auto_send.py` no longer imports from
  `app.services.concierge.kb_gap_manager`.
- `pre_booking_handler.py` no longer imports from
  `app.services.concierge.kb_gap_manager`.
- `ai_concierge.py` no longer imports from
  `app.services.concierge.kb_gap_manager`.

### Behavioral parity

- Brain-side gap emission still happens for specialist decisions with
  `missing_info` and non-`AUTO_SEND` action.
- Pre-booking grounding / reviewer fallbacks still record a gap when they
  previously did.
- Failures in gap recording remain non-fatal to the guest-facing pipeline.

### Retirement

- `app/services/concierge/kb_gap_manager.py` is deleted.
- `rg -n "kb_gap_manager"` over `app/ tests/ docs/` shows only historical docs
  and intentional references in retirement/incident notes, not live imports.
- `LEGACY_RETIREMENT_PLAN.md` marks `4.5.G` as retired.

## Testing requirements

### Focused regression tests

Add or update focused tests to prove:

1. brain orchestrator emits canonical gap records without importing
   `kb_gap_manager`
2. pre-booking fallback paths still record gaps non-fatally
3. no caller crashes if canonical gap recording raises an exception

Likely files:

- `tests/unit/test_orchestrator_emits_kb_gap_from_specialist_decisions.py`
- targeted pre-booking gap logging tests
- optional new unit test for the shared canonical adapter

### Verification commands

- `python3 -m py_compile` on touched Python files
- focused `pytest` for orchestrator and pre-booking gap tests

## Files anticipated to change

- new:
  - `app/services/concierge/knowledge_gap_recorder.py`
- updated:
  - `app/services/messaging_brain/orchestrator.py`
  - `app/services/concierge/pre_booking_auto_send.py`
  - `app/services/concierge/pre_booking_handler.py`
  - `app/services/concierge/ai_concierge.py`
  - relevant unit tests
  - `docs/architecture/LEGACY_RETIREMENT_PLAN.md`
- deleted:
  - `app/services/concierge/kb_gap_manager.py`

## Notes for execution

- Start with the shared adapter, then cut one caller at a time.
- Do not port `get_operator_gap_settings(...)` semantics into the canonical
  path. That data model is tied to `operator_gap_settings`, which is absent in
  production. Retiring it is part of the point of this ship.
- Keep metadata rich when moving call sites:
  - whether the gap was deflected
  - confidence score
  - whether KB chunks were used
  - source path (`brain_orchestrator`, `pre_booking_grounding`, etc.)
  These belong in canonical `metadata_json`, not in a second table.
- If a caller truly depends on digest/suppression behavior today, stop and
  prove it from code before implementing. The current audit suggests nobody
  does.

## Outcome

If `4.5.G` lands cleanly:

- all surviving knowledge-gap writes go to one canonical system
- the brain path stops depending on a dead legacy gap subsystem
- `kb_gap_manager.py` is gone
- future knowledge-gap work has exactly one place to build on
