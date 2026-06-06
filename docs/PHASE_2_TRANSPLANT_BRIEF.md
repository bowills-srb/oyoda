# Phase 2 Transplant — Execution Brief

**Date:** 2026-05-23
**Status:** Ready for Codex execution
**Estimated commits:** 3 (with 1 optional follow-up)

## Framing

Phase 0 cleaned up dead code. Phase 1 retired the legacy `concierge_knowledge` table and `knowledge_service.py`. Phase 2 is the **brain transplant**: nine files in `app/services/concierge/` are brain-owned code at the wrong path. Move them into `app/services/messaging_brain/` where they architecturally belong. No wrappers, no shims, no back-compat bridges — just `git mv` + import rewires.

In parallel: mark twelve files as "preserved for future product surface" so they don't get swept by future cleanup passes. These are real capabilities (dining, events, BD insight, group sessions, etc.) that aren't wired into the brain runtime today but represent product surface for pre-arrival / in-stay / personalization features.

## Helper scripts (already in repo)

Three scripts in `scripts/` to make this mechanical:

- **`scripts/verify_phase2_transplant.sh`** — grep-based verification. Run before Commit 1 and after each commit.
- **`scripts/rewrite_phase2_imports.sh`** — `sed` sweep that rewrites all 9 import paths across `app/`, `tests/`, `scripts/`. Handles macOS vs Linux `sed -i` quirk.
- **`scripts/add_preservation_banners.py`** — adds the preservation banner to all 12 future-feature files. Idempotent.

---

## Commit 1: Retire legacy `/concierge/message` pipeline

### Prerequisite

Pull Railway access logs for `/api/v1/concierge/message` over the last 14 days. **Block on either:**

- Zero hits, OR
- All hits have `auto_track_maintenance=True` in the request body

If any hits send `auto_track_maintenance=False`, do not proceed — that traffic still goes through legacy and needs a brain-side equivalent first.

Then:

```bash
bash scripts/verify_phase2_transplant.sh pre-commit-1
```

This confirms the three legacy files exist (sanity check we're about to delete the right things) and the brain runtime is alive (sanity check we're not deleting the only working path).

### Files to delete entirely

- `app/services/concierge/ai_concierge.py`
- `app/services/concierge/concierge_intelligence.py`
- `app/services/concierge/concierge_runner.py`

### Edits

**`app/api/v1/endpoints/concierge.py`:**
- Delete the `_handle_via_existing` function entirely
- Delete the `if request.auto_track_maintenance: ... else:` gate around the brain check — the brain path runs unconditionally when the runtime flag is on
- Delete imports of `ConciergeRunner`, `get_concierge_runner`, `classify_intent` from `app.services.concierge`
- The `/concierge/message` endpoint either calls the brain pipeline unconditionally or returns 410 Gone. Recommended: keep it alive and unconditionally route to brain.

**`app/services/concierge/__init__.py`:**

Remove these from `_EXPORTS`:
- `ConciergeRunner`
- `ConciergeRequest`
- `ConciergeReply`
- `classify_intent`
- `get_concierge_runner`

**Keep** these (still in use):
- `ConciergeMaintenanceService` / `get_concierge_maintenance_service` (brain `maintenance_module` uses it)
- `ConciergeBDInsightService` / `get_concierge_bd_insight_service` (future feature)
- `GuestSession` / `GuestSessionManager` / `SessionPhase` / `build_concierge_context` / `build_system_prompt` / `get_session_manager` (Phase 4 surface)
- `EscalationService` and friends (broadly used)
- `GuestNotificationService` / `NotificationType` / `get_notification_service`
- `DiningReservationService` and friends (future feature)
- `EventPlanningService` and friends (future feature)

### Verify

```bash
bash scripts/verify_phase2_transplant.sh post-commit-1
PYTHONPATH=$(pwd) ./.venv/bin/pytest tests/unit/ -q
```

Expected failures: tests that import from the three deleted files. Fix or delete those tests.

### Commit message

```
Phase 2 prep: retire legacy /concierge/message pipeline

Beach Habitats has been on the messaging_brain runtime path since
2026-05-02. Railway logs for the last 14 days show <N> hits to
/concierge/message; all routed through the brain path (no
auto_track_maintenance=False traffic).

Deleted:
- app/services/concierge/ai_concierge.py
- app/services/concierge/concierge_intelligence.py
- app/services/concierge/concierge_runner.py
- _handle_via_existing in app/api/v1/endpoints/concierge.py
- auto_track_maintenance=False escape branch
- ConciergeRunner exports from concierge/__init__.py

Unblocks Phase 2 transplant: brain-owned helpers can now move into
messaging_brain/ without coordinating with legacy callers.
```

---

## Commit 2: Transplant brain-owned helpers

Nine files. Pure relocation.

### Create directory structure

```bash
mkdir -p app/services/messaging_brain/context
mkdir -p app/services/messaging_brain/intake
mkdir -p app/services/messaging_brain/grounding
touch app/services/messaging_brain/context/__init__.py
touch app/services/messaging_brain/intake/__init__.py
touch app/services/messaging_brain/grounding/__init__.py
```

### Move files (use `git mv` to preserve history)

```bash
git mv app/services/concierge/scoped_knowledge_service.py \
       app/services/messaging_brain/knowledge/scoped_knowledge_service.py

git mv app/services/concierge/context_builder.py \
       app/services/messaging_brain/context/property_facts.py

git mv app/services/concierge/operator_guidance.py \
       app/services/messaging_brain/context/operator_guidance.py

git mv app/services/concierge/knowledge_topic_registry.py \
       app/services/messaging_brain/knowledge/topic_registry.py

git mv app/services/concierge/topic_classifier.py \
       app/services/messaging_brain/intake/topic_classifier.py

git mv app/services/concierge/intent_classification_escalator.py \
       app/services/messaging_brain/intake/intent_escalator.py

git mv app/services/concierge/conversation_history_service.py \
       app/services/messaging_brain/context/conversation_history.py

git mv app/services/concierge/response_reviewer.py \
       app/services/messaging_brain/grounding/response_reviewer.py

git mv app/services/concierge/hallucination_guard.py \
       app/services/messaging_brain/grounding/hallucination_guard.py
```

### Rewrite imports

```bash
bash scripts/rewrite_phase2_imports.sh
```

### Update `__init__.py` exports

**`app/services/messaging_brain/knowledge/__init__.py`:** add `scoped_knowledge_service` and `topic_registry` exports alongside existing.

**`app/services/concierge/__init__.py`:** remove any `_EXPORTS` entries pointing at the nine moved files (the verify script greps for these — see `post-commit-2`).

### Verify

```bash
bash scripts/verify_phase2_transplant.sh post-commit-2
PYTHONPATH=$(pwd) ./.venv/bin/pytest tests/unit/ -q
```

Expected failures:
- Tests with stale imports → the rewrite script should have caught those, but verify
- Tests that test specific internal sibling imports inside the moved files → fix the sibling import path

### Commit message

```
Phase 2 transplant: relocate brain-owned helpers into messaging_brain/

Nine files moved from app/services/concierge/ into the appropriate
messaging_brain/ subdirectory. No logic changes; pure relocation.

knowledge/:
- scoped_knowledge_service.py (canonical KB service, now at correct path)
- topic_registry.py (was knowledge_topic_registry.py)

context/:
- property_facts.py (was context_builder.py)
- operator_guidance.py
- conversation_history.py (was conversation_history_service.py)

intake/:
- topic_classifier.py
- intent_escalator.py (was intent_classification_escalator.py)

grounding/:
- response_reviewer.py
- hallucination_guard.py

All imports updated across app/, tests/, scripts/. Git history preserved
via git mv. No back-compat shims — the brain code now lives where it
architecturally belongs.
```

---

## Commit 3: Mark future-feature modules as preserved

Twelve files get a preservation banner prepended to their module docstring. No code change, no behavior change.

### Run the banner script

```bash
python scripts/add_preservation_banners.py
```

The script is idempotent — if a banner is already present, the file is left untouched. Output lists what was written, skipped, or failed.

### Verify

```bash
bash scripts/verify_phase2_transplant.sh post-commit-3
PYTHONPATH=$(pwd) ./.venv/bin/pytest tests/unit/ -q
```

Tests should pass with zero changes — this is a docstring-only commit.

### Commit message

```
Phase 2 closeout: mark future-feature concierge modules as preserved

12 files in app/services/concierge/ are real product capabilities not
currently wired into the brain runtime path:

- dining_service, event_planning_service, bd_insight_service
- portfolio_availability_service, market_brain, market_source_adapters
- proactive/guest_journey, group_session, guest_profile_service
- operator_learning, escapia_unified, maintenance_service

Added preservation banner to each so future cleanup passes don't sweep
them as orphans. These relocate into messaging_brain/ when the
corresponding product surface (pre-arrival, in-stay, multi-guest, etc.)
is wired in.

No behavior change. Docstring-only commit.
```

---

## Commit 4 (optional, separate session): Audit `property_context.py`

`property_context.py` is the old sync psycopg2-based property loader. The modern path is `app/services/property_canonical_service.py`. Likely dead-by-replacement after Commit 1 removes the three legacy runtime files.

### Work

1. Grep every importer:
   ```bash
   grep -rn "app.services.concierge.property_context" app/ tests/ scripts/
   ```
2. Classify each importer:
   - **Legacy runtime callers (gone after Commit 1):** importer is already dead.
   - **`property_canonical_service.py` candidates:** rewire to the modern async merger.
   - **Tests:** delete if testing legacy behavior, rewire if testing live behavior.
3. If after rewiring nothing imports `property_context.py`, delete the file.

Skip this commit until Commit 1 is in and tests are green.

---

## After all three commits ship

**Concierge directory shrinks by 12 files:**
- 3 deleted legacy runtime files (Commit 1)
- 9 transplanted brain-helper files (Commit 2)

**Brain directory grows by 9 files** in proper subdirectories.

**12 future-feature files** in `app/services/concierge/` get explicit preservation markers.

**Remaining in `app/services/concierge/`:**
- 12 preserved future-feature files (banner-tagged)
- Phase 3 pre-booking shell (`pre_booking_auto_send.py`, `pre_booking_handler.py`, `inquiry_persistence.py`, `post_booking_routing.py`)
- Phase 4 session/thread infrastructure (`db_session_service.py`, `guest_session.py`, `guest_thread_service.py`, `thread_property_inheritance.py`, `property_router.py`, `db_service.py`, `notification_service.py`, `escalation_service.py`, `message_history.py`, `guidebook_ingest_service.py`)
- Compatibility shims (`knowledge_gap_recorder.py`, `sms_service.py`, `operator_bridge.py`) — deletable when callers update
- `property_context.py` pending Commit 4 audit

Phase 3 (pre-booking shell) and Phase 4 (sessions) become their own focused sessions. The directory is no longer a grab bag of mixed concerns.
