# Brain Prebooking Lifecycle Primary Safety

Date: 2026-05-27
Tenant: Beach Habitats (`e07980b2-a990-4b24-91d1-c8cb71ab70e1`)
Status: investigation complete, no-flag-flip recommendation until explicit go/no-go review

## Question

What does `brain_prebooking_lifecycle_primary = true` actually change, and is it safe to enable for Beach Habitats right now?

## Current live state

Beach Habitats currently has:

- `messaging_brain_runtime = true`
- `messaging_brain_llm_intake = true`
- `brain_intake_primary = false`
- no tenant override for `brain_prebooking_lifecycle_primary`

Because `brain_prebooking_lifecycle_primary` is absent, it resolves to the environment default in
[app/services/feature_flags.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/feature_flags.py:564),
which is `false`.

That means [dispatch_pre_booking](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/email_dispatch.py:895)
currently does:

```python
if not runtime_enabled or not brain_lifecycle_primary:
    return await _persist_fallback("brain_runtime_not_primary")
```

So every Beach Habitats pre-booking inbound currently saves a fallback/held row instead of entering the live brain lifecycle.

## What flips when the flag is ON

With both:

- `messaging_brain_runtime = true`
- `brain_prebooking_lifecycle_primary = true`

the code path becomes:

1. `PreBookingBrainOrchestrator().handle(...)`
2. `_review_brain_pre_booking_draft(...)`
3. `run_brain_pre_booking_lifecycle(...)`
4. `execute_pre_booking_lifecycle(...)`
5. canonical persistence via `save_inquiry_from_canonical(...)`
6. normalization outcome update + gap recording in `email_dispatch.py`

Relevant code:

- [app/services/integrations/email_dispatch.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/email_dispatch.py:912)
- [app/services/messaging_brain/pre_booking_lifecycle.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/pre_booking_lifecycle.py:240)

This is a real lifecycle cutover, not just an intake-classifier flip.

## What it does not do

- It does not enable autonomous send here. `email_dispatch.py` forces `approval_mode="required"` into the brain lifecycle call.
- It does not bypass operator review for Beach Habitats pre-booking.
- It does not keep using the fallback placeholder draft; it writes a brain-owned draft path instead.

## Production evidence check

Current production query result: no enabled rows were found for `brain_prebooking_lifecycle_primary` in `operator_feature_flags`.

Interpretation:

- there is no live tenant-level evidence in production today that this exact lifecycle-primary flag is actively serving traffic
- the flag exists and the code path is implemented
- but the absence of enabled tenants means this is still effectively a first live rollout if we flip it for Beach Habitats

## Risk read

### Good news

- The flag is isolated from `messaging_brain_llm_intake`; rollback is one setting.
- With the flag OFF, current behavior remains fallback-safe.
- The lifecycle path persists through the canonical pre-booking save seam (`save_inquiry_from_canonical`), not a parallel table.

### Risks

- No tenant currently appears to be running this exact flag live.
- The older Beach Habitats rollout doc
  [docs/MESSAGING_BRAIN_PREBOOKING_BEACH_HABITATS_ROLLOUT.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/MESSAGING_BRAIN_PREBOOKING_BEACH_HABITATS_ROLLOUT.md:19)
  is stale relative to the current code because it describes `messaging_brain_runtime` as the key gate, while the live code now also requires `brain_prebooking_lifecycle_primary`.
- Enabling the flag will increase LLM/runtime work per inbound because the lifecycle path will now run orchestration + review + canonical save instead of the cheap fallback placeholder.

## Recommendation

No blind flip.

Recommended next step before enablement:

1. Run a targeted replay/regression pass against the current brain pre-booking lifecycle seams.
2. Confirm at least one representative Beach Habitats inquiry produces:
   - saved inquiry row
   - `draft_source = messaging_brain`
   - expected held/review-required outcome
3. Only then enable `brain_prebooking_lifecycle_primary` for Beach Habitats.

## Go / No-Go

- Go: only after a targeted replay/regression verification pass.
- No-Go right now: yes, do not flip based on current evidence alone.
