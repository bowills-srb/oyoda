# Ship P — Brain-Era Regression Harness Modernization

**Status:** Drafted May 20, 2026 after the post-migration verification pass showed the existing synthetic inbound replay harness is structurally stale.

**Why this ship exists:** The runtime migration is complete, but the synthetic replay harness in [scripts/synthetic_inbound_pipeline_report.py](/Users/dhuntermckenzie/Downloads/oyvoda/scripts/synthetic_inbound_pipeline_report.py) still models an older set of flags, a fake DB object with no real lifecycle seam, and pre-Brain dispatch assumptions. That makes it unsafe as pre-flip or post-deploy evidence. Ship P updates the harness so it can honestly answer: "If I send representative guest traffic through the current system, what happens across channels and lifecycles?"

**Scope discipline:** This ship modernizes test/replay infrastructure only. It does not change guest-facing runtime behavior, operator UI behavior, or production feature flags.

## What Ship P ships

1. **Rebuild the synthetic replay harness around current Brain flags and seams.**
2. **Expand the replay matrix across representative channels and lifecycles.**
3. **Add explicit assertions for Ship I substrate fields where relevant.**
4. **Make the harness output usable for both pre-flip and post-deploy verification.**
5. **Document the interpretation rules so the harness cannot silently lie.**

## What is wrong now

The existing synthetic harness is not merely incomplete; it is structurally stale:

- Its fake flag service is positional and under-provisioned, which now causes `IndexError: pop from empty list` during current flag lookups.
- Its fake DB is just `object()`, which no longer satisfies the runtime seam now that dispatch flows consult DB-backed lifecycle and persistence paths.
- Its output categories (`pre_booking_new`, `pre_booking_fallback`, etc.) were shaped around an older seam and do not cleanly represent the current Brain lifecycle ownership.
- It does not model the full active Brain flag surface:
  - `MESSAGING_BRAIN_RUNTIME`
  - `BRAIN_INTAKE_PRIMARY`
  - `BRAIN_POLICY_PRIMARY`
  - `BRAIN_COMPOSER_PRIMARY`
  - `BRAIN_GAP_DETECTION_PRIMARY`
  - `BRAIN_PREBOOKING_LIFECYCLE_PRIMARY`
  - `SHIP_I_KB_RETRY_PRIMARY`
- It does not yet provide lifecycle-complete evidence for:
  - pre-booking
  - pre-arrival
  - in-stay
  - proactive pre-arrival

That means the current harness can produce false-red or false-green outcomes unrelated to the actual product.

## Deliverable 1 — Rebuild the harness around current runtime seams

### What Ship P does

Replace the positional fake-flag approach with a named fake feature-flag service keyed by actual `FeatureFlag` names. The harness must explicitly support the current runtime flag surface and return deterministic values by name, not by call order.

Replace the `db=object()` placeholder with a small fake DB/session seam that supports the current dispatch and persistence touchpoints used in replay mode. The fake DB does not need full SQL behavior; it does need to satisfy the current contracts well enough that the harness is exercising the real orchestration branches instead of failing on missing methods.

### Acceptance criteria

- The harness no longer fails with `IndexError` from flag lookup.
- The harness no longer fails because the fake DB lacks `execute` or other required runtime seam methods.
- The harness explicitly models all currently relevant Brain/Ship I flags by name.
- The harness can run end-to-end without falling back to "flag lookup failed, defaulting gate/brain off" in ordinary success cases.

## Deliverable 2 — Expand the replay matrix across channels and lifecycles

### What Ship P does

Keep the useful pre-booking cases already present, but formalize the matrix so it covers the current product surface intentionally:

- **Pre-booking**
  - Airbnb guest inquiry
  - Vrbo guest inquiry
  - direct/Gmail-style guest inquiry
  - Outlook/Microsoft-normalized email shape
  - low-confidence review case
  - true knowledge-gap hold case
- **Pre-arrival**
  - booked guest asking an arrival/check-in question
  - OTA reservation-confirmed reply that should route as pre-arrival
- **In-stay**
  - guest operational question that should route through the Brain in in-stay lifecycle
  - session-channel adapter shape (SMS/mobile/phone-style envelope)
- **Proactive**
  - booking-triggered welcome preview
  - pre-arrival proactive touch

The cases can remain synthetic, but each one must map to a real runtime lifecycle and expected outcome.

### Acceptance criteria

- The harness matrix explicitly labels each case with:
  - source channel
  - provider/source route
  - lifecycle
  - expected routing class
  - expected outcome class
- At least one Outlook/Microsoft-normalized inbound case exists.
- At least one true KB-gap pre-booking case exists and expects hold behavior with a non-empty topic list.
- At least one pre-arrival and one in-stay case exist and run through current Brain lifecycle paths.
- At least one proactive case exists and runs through the current Brain proactive adapter/specialist path.

## Deliverable 3 — Assert Ship I substrate behavior when applicable

### What Ship P does

For pre-booking knowledge-gap cases, the harness should not merely assert "held for review." It should also assert the current substrate fields and semantics that Ship I depends on:

- `policy_warnings` includes `missing_property_knowledge:*`
- `blocked_by_gap_topics` is non-empty and matches the warning topic(s)
- if a retry/re-evaluation path is exercised in harness mode, the outcome labeling distinguishes:
  - `auto_fresh`
  - `auto_kb_retry`
  - `operator`

This keeps the harness useful for future Ship I flag flips and KB-retry regressions.

### Acceptance criteria

- A knowledge-gap replay case fails if it produces empty `blocked_by_gap_topics`.
- A knowledge-gap replay case fails if warning topics and blocked topics disagree.
- Outcome labeling distinguishes fresh auto-send from KB-retry auto-send where the case reaches those paths.

## Deliverable 4 — Produce operator-readable and engineer-readable output

### What Ship P does

The harness should emit a concise summary that is useful to both engineering and rollout operations:

- case name
- lifecycle
- channel/provider
- parser result
- gate result
- dispatch result
- hold/send/review classification
- notes on fallback if any

The output should make it obvious whether a failure belongs to:

- parser layer
- routing/gate layer
- Brain orchestration
- persistence/retry substrate

### Acceptance criteria

- Output is grouped or filterable by lifecycle and channel.
- A failing case indicates which stage failed.
- Fallbacks are surfaced explicitly and never counted as normal success.

## Deliverable 5 — Document the rules for using harness results

### What Ship P does

Add a short operator/engineering note describing when the harness is acceptable evidence:

- acceptable for pre-flip synthetic verification
- acceptable for post-deploy synthetic verification
- not a substitute for at least one real production smoke when the feature touches operator-facing UI
- not acceptable evidence if the harness itself is on stale contracts

This is the governance layer that prevents the exact problem we just found.

### Acceptance criteria

- The ship adds a short runbook or note alongside the harness describing how to interpret results.
- The note explicitly says a structurally stale harness cannot be used as rollout evidence.

## Verification pattern

1. Run the harness after the modernization changes and confirm the matrix completes without stale-harness errors.
2. Run the existing targeted lifecycle/channel unit suite:
   - parser/router
   - inbound transport
   - Brain endpoint lifecycle routing
   - pre-booking Brain dispatch
   - confirmed-guest / pre-arrival
   - in-stay Brain dispatch
   - session-channel adapter
   - proactive trigger adapter
3. Confirm at least one KB-gap synthetic case asserts non-empty `blocked_by_gap_topics`.

## What does NOT change in Ship P

- No production feature flags are flipped by this ship.
- No operator dashboard UI changes.
- No new Brain runtime behavior is introduced for guests.
- No deletion-arc work is bundled in.

## Recommended commit order

1. Harness seam rebuild (flags + fake DB)
2. Matrix expansion (new lifecycle/channel cases)
3. Output/reporting polish + runbook note

## Notes for the executor

- Treat the current harness as untrusted until Deliverable 1 is complete.
- Do not paper over stale-harness failures by loosening assertions; update the seam so the harness reflects current runtime truth.
- Keep the replay matrix intentionally representative, not exhaustive. The point is strong deployment evidence, not every conceivable email shape.
