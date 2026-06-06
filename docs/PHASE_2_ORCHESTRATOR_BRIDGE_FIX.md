# Phase 2 — Orchestrator Bridge Fix

**Status:** changes on disk, awaiting commit
**Scope:** single file (`app/services/messaging_brain/orchestrator.py`)
**Risk:** low — both changes are import-only

## What this commit does

Two import-only edits to the brain orchestrator. Both target the same function
(`_emit_kb_gaps_from_decisions`).

### 1. Remove bridge through the legacy concierge shim

The orchestrator was importing `schedule_gap_record` through
`app.services.concierge.knowledge_gap_recorder`, which is itself a thin
compatibility shim that re-exports from
`app.services.messaging_brain.knowledge.gap_recorder`.

That's a one-hop bridge inside brain code, exactly the kind of indirection the
brain-only migration's governing rule prohibits ("no bridges, no dual-caller
shared utilities"). The shim itself stays alive for now because Phase-3
concierge code (`pre_booking_auto_send.py`) still imports through it; the
shim's docstring already says "Do NOT add new imports of this module" and
notes that it dies in Phase 4/7. But the orchestrator has no reason to go
through the shim — it should reach into brain code directly.

**Before:**
```python
from app.services.concierge.knowledge_gap_recorder import schedule_gap_record
```

**After:**
```python
from app.services.messaging_brain.knowledge.gap_recorder import schedule_gap_record
```

No call-site changes; `schedule_gap_record` has the same signature in both
paths (the shim is a pure re-export).

### 2. Fix latent NameError on `MessagingLifecycle`

While reading the same function, I noticed `_emit_kb_gaps_from_decisions`
references `MessagingLifecycle.IN_STAY.value` on the `None`-lifecycle branch
but `MessagingLifecycle` was not in the orchestrator's imports. The NameError
only fires when a specialist decision triggers gap emission AND the inbound
message has `lifecycle=None`, which is why this hasn't blown up in production
yet — most inbound messages carry a lifecycle. But it's a guaranteed crash on
the branch that hits, and it lives in the same function we're already
touching, so fixing it in the same commit is cleaner than leaving a known bug
behind.

**Added to the existing imports block:**
```python
from app.services.orchestration.messaging_brain_contracts import (
    ...
    MessageClassification,
    MessagingLifecycle,   # ← added
    ModuleEvent,
    ...
)
```

`MessagingLifecycle` is defined at line ~41 of
`app/services/orchestration/messaging_brain_contracts.py`. No new dependency.

## What this commit does NOT do

- **Does not delete the shim** at `app/services/concierge/knowledge_gap_recorder.py`.
  `pre_booking_auto_send.py` (Phase 3 surface) and a couple of other concierge-
  package callers still import through it. The shim collapses naturally when
  Phase 3 unwinds the pre-booking shell.
- **Does not touch `pre_booking_auto_send.py`** or other concierge-package
  callers of the shim. Their cleanup is part of Phase 3.

## Verification

After committing, the brain has zero accidental shim hops:

```bash
# Should return only the shim file itself and intentional Phase-3 callers.
# Specifically, NO matches under app/services/messaging_brain/.
grep -rn "app\.services\.concierge\.knowledge_gap_recorder" app/ tests/
```

The existing Phase 2 verify script already covers stale moved-file paths and
will continue to pass:

```bash
bash scripts/verify_phase2_transplant.sh post-commit-2
```

Tests to run:

```bash
pytest tests/unit/test_messaging_brain_ac_slice.py \
       tests/unit/test_concierge_endpoint_brain_path.py \
       tests/unit/test_messaging_brain_contracts.py \
       tests/unit/test_email_dispatch_prebooking_brain.py \
       tests/unit/test_email_dispatch_brain_adversarial_review.py \
       tests/unit/test_email_dispatch_in_stay_brain.py \
       tests/unit/test_prebooking_brain_lifecycle.py
```

Expected: all pass. The imports being changed are not stubbed by any test
fixture (the tests patch higher-level orchestrator methods, not the gap
recorder directly).

## Suggested commit message

```
brain: wire orchestrator gap recorder direct, fix MessagingLifecycle NameError

Two import-only changes to messaging_brain/orchestrator.py, both in
_emit_kb_gaps_from_decisions:

1. schedule_gap_record now imports directly from
   app.services.messaging_brain.knowledge.gap_recorder instead of going
   through the app.services.concierge.knowledge_gap_recorder shim. The
   shim is a pure re-export of the brain implementation; the orchestrator
   had no reason to take the one-hop detour. The shim itself stays alive
   for Phase-3 concierge-package callers (pre_booking_auto_send.py) per
   its own docstring — it dies with Phase 4/7.

2. MessagingLifecycle was referenced on the lifecycle=None branch of the
   gap-emission loop but missing from the contracts import. This is a
   guaranteed NameError when a brain decision emits a gap AND the inbound
   message has no lifecycle set. Add it to the existing import block.

No call sites change. schedule_gap_record has the same signature in both
paths. Phase 2 verify script remains green.
```
