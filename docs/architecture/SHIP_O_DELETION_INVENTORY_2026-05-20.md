# Ship O deletion inventory — May 20, 2026

This is Deliverable 1 from [SHIP_O_DELETION_ARC.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/architecture/SHIP_O_DELETION_ARC.md): target-by-target inventory, replacement path, current call sites, and delete eligibility.

## Summary

As of May 20, 2026, **Ship O is not ready to perform broad deletion yet**.

There are two distinct reasons:

1. **Verification windows have not elapsed** for the newest Brain-owned replacements.
   - Ship K: `52e3686`
   - Ship L: `6a8b53d`
   - Ship M: `8f24c79`
   - Ship N: `540c043`
   - all landed on May 20, 2026

2. **Some targets are still structurally live**, not just waiting on a window.
   - `ConciergeRunner` still has explicit endpoint call sites
   - `pre_booking_auto_send.py` still owns helper and compatibility seams that are imported at runtime
   - `PROACTIVE_TEMPLATES` is still the explicit fallback path in `/sms/proactive`
   - `StayProactiveService` is still the canonical eligibility/cadence helper

So the honest state today is:

- runtime ownership has migrated
- deletion eligibility is mixed
- Deliverable 1 can land now
- deletion commits should wait until each target is both structurally dead **and** outside its verification window

The verification windows for Targets A, B, and C all begin from the production-live dates of Ships K, L, M, and N. Those windows run in parallel; they do not need to be serialized.

---

## Target matrix

### A. `ConciergeRunner`

**Replacement path**

- reactive guest runtime: `messaging_brain` via `/concierge/message`
- proactive preview/runtime: Brain proactive path from Ship N

**Current call sites**

- `app/api/v1/endpoints/concierge.py`
  - `_handle_via_existing(...)` still calls `get_concierge_runner()`
  - `/concierge/decision` still calls `get_concierge_runner()`
- `app/api/v1/endpoints/voice.py`
  - non-prod legacy voice endpoint still calls `get_concierge_runner()`
- module/re-export references:
  - `app/services/concierge/concierge_runner.py`
  - `app/services/orchestration/concierge_runner.py`
  - `app/services/concierge/__init__.py`
  - `app/services/orchestration/__init__.py`

**Why not deletable yet**

This is not just a verification-window problem. There are still live code paths importing and calling it.

**Delete eligibility**

- **No**

**What must happen first**

1. decide whether `/concierge/message` flag-off compatibility path is still required
2. migrate or retire `/concierge/decision`
3. retire or isolate the non-prod `/voice/concierge` endpoint
4. then re-run `rg` and confirm runtime call sites hit zero

**Audit split note**

These should be treated as three separate audit commits if possible:

1. flag-off compatibility decision
2. `/concierge/decision` usage audit
3. `/voice/concierge` retirement decision

---

### B. `VoicePod.respond(...)` as a runtime owner

**Replacement path**

- session-channel Brain adapter in `app/services/messaging_brain/session_channel_adapter.py`
- `mobile_v2._run_voice_pod(...)` is now a naming seam around Brain, not a `VoicePod.respond(...)` call

**Current call sites**

Direct `VoicePod.respond(...)` references found:

- `app/services/observability/watch_layer.py`
- `app/api/v1/endpoints/knowledge.py` voice-pod test endpoint

Channel seams still named “voice pod” but no longer using `VoicePod.respond(...)`:

- `app/api/v1/endpoints/mobile_v2.py`
- `app/api/v1/endpoints/sms.py`
- `app/api/v1/endpoints/phone.py`
- `app/services/messaging/channel_router.py`

**Why not deletable yet**

Two separate blockers:

1. **verification window has not elapsed** for Ship M
2. `voice_pod.py` may still contain extractable shared utility logic even if its runtime ownership is largely gone

**Delete eligibility**

- **Not yet**

**What must happen first**

1. complete extraction audit of `voice_pod.py`
2. if shared utility remains, extract it in a separate commit
3. verify the remaining direct `respond(...)` references are gone or intentionally non-runtime
4. only then delete runtime entrypoints

The Ship M verification window starts when Ship M is live in production traffic. It runs in parallel with the other post-migration windows.

---

### C. `PROACTIVE_TEMPLATES`

**Replacement path**

- Brain proactive composition from Ship N

**Current call sites**

- `app/api/v1/endpoints/sms.py`
  - fallback branch in `/sms/proactive`

**Why not deletable yet**

This fallback is still live by design. It now fires only on named Brain composition failure and logs:

- `composer_fallback_template_used`

But Ship N landed today, so there is no reliability window yet showing that fallback is unused.

**Delete eligibility**

- **No**

**What must happen first**

1. measure proactive Brain compose reliability in production
2. confirm fallback usage is zero or acceptably near-zero over the named window
3. then delete templates

**Suggested success criterion**

The measurement window starts when Ship N is live in production traffic. Deletion eligibility should require one of:

- a named minimum send volume with zero fallback hits, or
- a named time window where fallback hits remain below a small explicit threshold

Recommended starting rule for this target:

- at least **50 proactive sends** with `composer_fallback_template_used = 0`, or
- **14 days** of production traffic with fallback hits `<= 1%`

If the team chooses a different threshold, it should be named before deletion rather than decided ad hoc after the fact.

---

### D. `StayProactiveService`

**Replacement path**

- none for cadence/eligibility yet; Brain only replaced message-body ownership

**Current call sites**

- `app/services/operator/stay_workflow_service.py`
  - `workflow["proactive"] = get_stay_proactive_service().evaluate(...)`

**Why not deletable yet**

Ship N intentionally kept this as the canonical eligibility/cadence helper.

**Delete eligibility**

- **No**

**What must happen first**

Either:

1. keep it permanently as canonical cadence helper

or

2. migrate cadence logic elsewhere in a dedicated ship, then re-evaluate deletion

Today it is not a deletion target.

---

### E. `pre_booking_auto_send.py`

**Replacement path**

- Brain pre-booking lifecycle in:
  - `app/services/messaging_brain/pre_booking_lifecycle.py`
  - Brain agents from `4.5.A-G`

**Current call sites**

Confirmed runtime/compatibility imports:

- `app/services/messaging_brain/pre_booking_lifecycle.py`
  - imports `PreBookingPipelineOrchestrator`, save/send/alert helpers
- `app/services/integrations/email_dispatch.py`
  - still has fallback path to `process_pre_booking_inquiry_with_draft(...)`
- `app/workers/tasks.py`
  - imports pre-booking send helpers
- `app/services/concierge/inquiry_persistence.py`
- `app/services/concierge/pre_booking_handler.py`
- `app/api/v1/endpoints/operator_prebooking.py`
- `app/services/integrations/gmail_inbox_poller.py`

Test call sites also remain, especially for parity around the 4.5 migration:

- multiple `tests/unit/test_*agent.py`
- `tests/unit/test_prebooking_*`

**Why not deletable yet**

This target is still structurally live. The Brain lifecycle cutover happened, but the compatibility shell and helper imports are still active.

**Delete eligibility**

- **No**

**What must happen first**

1. audit symbol groups inside `pre_booking_auto_send.py`
2. identify which are:
   - dead orchestration
   - still-live helper seams
   - still-live compatibility callers
3. move surviving helpers to clearer shared homes if needed
4. remove one logical symbol-group at a time

This target is not a single delete. It is a staged collapse.

---

## Practical next order

The next sensible work is:

1. **Target A audit ship**
   - decide flag-off compatibility fate
   - decide `/concierge/decision` fate
   - confirm whether `/voice/concierge` can be retired now

2. **Target E audit ship**
   - symbol-group inventory for `pre_booking_auto_send.py`
   - identify the first actually-deletable logical group

3. **Target B extraction audit**
   - decide whether `voice_pod.py` contains shared utility worth extracting before deletion

Targets C and D are explicitly not ready today.

These audits can land now while the production windows are elapsing, because they are not deletion commits.

---

## Bottom line

The honest status on May 20, 2026:

- **Ship O can start with inventory and symbol-group audits**
- **Ship O should not yet do broad deletion commits**

The migration arc succeeded in moving ownership. The deletion arc now needs patience and proof.
