# Ship I — Knowledge Gaps Back Into Queue + Brain Fill-and-Retry Loop

**Status:** Drafted May 20, 2026 after Ships K-N completed Brain runtime ownership across pre-booking, reactive, and proactive messaging.

**Prerequisite:** Ships H, K, L, M, and N are live. Ship O is docs/audit-only so far; no deletion assumptions are required for Ship I.

**What changed since the old Ship I framing:** this is no longer a hybrid migration brief. Pre-booking runtime ownership now sits with the Brain path, but two operator-side seams are still outside that path:

- KB gap resolution still has **two save paths**:
  - dashboard raw-SQL endpoint: `app/api/v1/endpoints/operator_dashboard_api.py`
  - service/API path: `app/services/concierge/knowledge_service.py::resolve_gap()` and `app/api/v1/endpoints/concierge.py`
- manual regenerate still uses the **old endpoint-local mini-pipeline** in `app/api/v1/endpoints/operator_prebooking.py::regenerate_inquiry()`

Ship I fixes those seams and returns knowledge-gap inquiries to the operator queue as first-class Brain-owned work items.

## Decision

Knowledge-gap inquiries are still guests waiting on a reply. From the operator seat, “missing knowledge” and “low confidence” are both queue work. Ship G/Ship H made the UI honest, but they still exile gap-held inquiries to Knowledge. Ship I reverses that, and it wires “fill the gap” into a real Brain re-evaluation loop.

## What Ship I ships

Seven deliverables, in order. Backend first, UI second.

1. **Persist `blocked_by_gap_topics` on held pre-booking inquiries.**
2. **Add one shared post-KB-save retry hook and call it from both KB resolve paths.**
3. **Replace legacy manual regenerate logic with a Brain-native re-evaluation core.**
4. **Allow KB-triggered re-evaluations to auto-send when the Brain path would have auto-sent.**
5. **Put knowledge-gap inquiries back into the Action queue with a NEEDS KB row state.**
6. **Use the real Add KB modal/workflow to preview and report retry impact.**
7. **Remove the redundant “Inquiries waiting on knowledge” section from Knowledge.**

## Plain-language behavior

Path 1.5 now becomes:

1. Brain holds an inquiry because knowledge is missing.
2. The held inquiry stores which topic(s) blocked it.
3. Operator fills the missing KB entry.
4. The save path finds matching held inquiries and queues Brain re-evaluation.
5. If the regenerated draft now clears the normal Brain/policy send gates, it sends automatically.
6. If not, it comes back to the operator queue with updated confidence and the knowledge-gap state cleared.

No speculative prediction is required before save. The honest promise is “fill the gap and the Brain will try again immediately.”

## Deliverable 1 — Persist `blocked_by_gap_topics`

### What exists now

- Brain gap analysis already exists in `app/services/messaging_brain/agents/knowledge_gap_agent.py`
- held drafts already emit operator-visible knowledge-gap markers:
  - `draft_source: kb_gap_required`
  - `policy_warning: missing_property_knowledge:<topic[,topic...]>`
- but `pre_booking_inquiries` does **not** have a first-class queryable field for “which topic blocked this inquiry?”

### What Ship I does

Add `blocked_by_gap_topics` to `pre_booking_inquiries` as a `text[]`. This ship only needs a flat list of normalized topic keys; there is no per-topic nested metadata yet, so JSONB would add complexity without benefit. Populate it when a pre-booking inquiry is saved in held-for-gap state.

Source of truth:
- use the Brain gap analysis result when available
- fall back to the already-produced `missing_property_knowledge:` warning string only for compatibility/backfill

### Acceptance criteria

- migration exists for `blocked_by_gap_topics`
- Brain-held gap inquiries persist the topic list at save time
- the queue read model exposes the field
- a query for “all pending/held inquiries blocked by topic X” is possible without string parsing `policy_warnings`
- optional backfill is idempotent if included

### Anticipated files

- `db/migrations/versions/...`
- `app/services/concierge/inquiry_persistence.py`
- `app/services/messaging_brain/pre_booking_lifecycle.py`
- queue/read-model adapter files that surface inquiry rows to the dashboard

## Deliverable 2 — Shared post-save retry hook

### What exists now

There are still two KB resolve paths:

1. dashboard path used by the current UI:
   - `app/api/v1/endpoints/operator_dashboard_api.py::resolve_kb_gap`
2. service/API path:
   - `app/services/concierge/knowledge_service.py::resolve_gap()`
   - `app/api/v1/endpoints/concierge.py::resolve_concierge_knowledge_gap`

Neither path currently triggers held-inquiry retries after save.

### What Ship I does

Create one shared service function, for example:

`kb_post_save_retry_held_inquiries(...)`

It should:

1. identify the saved gap/topic
2. find held/pending inquiries whose `blocked_by_gap_topics` include that topic
3. enqueue Brain re-evaluation for each match
4. return a structured list of what was queued

Both resolve paths call this shared function after the gap is successfully resolved.

### Response contract

The save response should stay fast and return only what is knowable synchronously:

`triggered_regenerations: [{inquiry_id, topic, scheduled_at}]`

and summary counts such as:

- `triggered_regeneration_count`

It should **not** wait for all retries to finish before returning.

Actual outcomes:

- `sent_count`
- `returned_to_queue_count`
- `failed_count`

should come from a follow-up status read model or polling endpoint keyed off the save action / inquiry IDs. Ship I should not fake these counts synchronously.

### Critical constraint

Do **not** pretend the save paths are already unified. Ship I must hook both current paths. Unification can happen later, but missing the dashboard path would miss the live UI.

### Acceptance criteria

- one shared retry-hook function exists
- both KB resolve paths call it
- save remains responsive; retries run asynchronously
- both responses include the same `triggered_regenerations` list shape
- both responses include `triggered_regeneration_count`
- zero matching held inquiries returns an empty list, not a false success story

### Anticipated files

- `app/api/v1/endpoints/operator_dashboard_api.py`
- `app/services/concierge/knowledge_service.py`
- new module such as `app/services/messaging_brain/kb_retry_handler.py`

## Deliverable 3 — Brain-native re-evaluation core

### What exists now

The current manual regenerate endpoint in `app/api/v1/endpoints/operator_prebooking.py::regenerate_inquiry()` still:

- reloads Gmail if possible
- re-classifies locally
- calls legacy helper functions directly
- updates `pre_booking_inquiries` itself

That bypasses the current Brain pre-booking runtime contract.

### What Ship I does

Extract a reusable Brain-native re-evaluation function that:

1. rebuilds a `PreBookingInquiry` (or equivalent canonical input) from the stored inquiry row plus refreshed thread content when available
2. runs the same Brain pre-booking flow used for fresh inquiries
3. persists the new draft/confidence through the existing lifecycle/persistence seam

Manual regenerate should become a thin HTTP wrapper over this shared core.

### Critical constraint

Ship I should **reuse** the current Brain contracts and lifecycle shell:

- `PreBookingInquiry`
- `PreBookingDraftResult`
- `PreBookingBrainOrchestrator`
- `run_brain_pre_booking_lifecycle(...)` / `execute_pre_booking_lifecycle(...)`

Do not create a second re-evaluation vocabulary or another mini-pipeline.

### Acceptance criteria

- a callable re-evaluation service exists outside the endpoint
- manual regenerate calls it instead of reproducing the old legacy logic inline
- KB-triggered retry calls the same function
- failures are logged and isolated per inquiry

### Anticipated files

- `app/api/v1/endpoints/operator_prebooking.py`
- new module such as `app/services/messaging_brain/pre_booking_retry.py`
- possibly `app/services/messaging_brain/pre_booking_lifecycle.py`

## Deliverable 4 — Send-or-return using the existing Brain gates

### What exists now

Fresh Brain-owned pre-booking inquiries already go through the Brain policy/composition/lifecycle path before send or review.

What does **not** exist yet:

- KB-triggered retries that use the same gates
- first-class send attribution on the inquiry row
- a summary aggregate for “AI auto-sent today”

### What Ship I does

After a KB-triggered re-evaluation:

- if the resulting Brain decision is equivalent to “send now,” send it
- otherwise keep it in the queue with updated draft/confidence

Also add `triggered_by` to `pre_booking_inquiries` with explicit values:

- `auto_fresh`
- `auto_kb_retry`
- `operator`

Then expose `ai_sent_today` in dashboard summary as:

- sends where `triggered_by IN ('auto_fresh', 'auto_kb_retry')`
- within today’s window

### Acceptance criteria

- KB-triggered retries use the same send/review gates as normal Brain pre-booking
- auto-send after KB resolve records `triggered_by = 'auto_kb_retry'`
- operator send records `triggered_by = 'operator'`
- fresh Brain auto-send records `triggered_by = 'auto_fresh'`
- summary payload exposes `ai_sent_today`

### Anticipated files

- `db/migrations/versions/...`
- `app/services/messaging_brain/pre_booking_lifecycle.py`
- `app/services/operator/dashboard_summary_service.py`
- relevant operator send/update endpoints

## Deliverable 5 — Put knowledge-gap inquiries back into Action queue

### What exists now

`app/static/dashboard/js/sections/messages.js` still routes knowledge-gap inquiries out of the queue via:

- `isKnowledgeGap(...)`
- `routesToKnowledge(...)`
- `filteredItems()` exclusions

### What Ship I does

Return these inquiries to `Action queue` and render a row variant:

`NEEDS KB · missing: {topic}`

Behavior:

- replaces `DRAFT · {N}%` for true gap-held rows
- shows the missing topic directly
- replaces Send/Edit with one inline action: `Fill KB`
- visually distinct but quiet

The `?` detail popout should show:

- missing topic(s)
- whether other inquiries share this topic
- the underlying guest message context

### Acceptance criteria

- `filteredItems()` no longer excludes knowledge gaps from the queue
- Action queue shows NEEDS KB rows
- Fill KB is the only inline action for those rows
- the row uses stored `blocked_by_gap_topics` when available; legacy warning parsing is fallback-only

### Anticipated files

- `app/static/dashboard/js/sections/messages.js`
- `app/static/dashboard/styles/dashboard.css`

## Deliverable 6 — Use the real Add KB modal/workflow

### What exists now

There is no true Resolve modal yet. The current Knowledge gap resolve path uses:

- `window.prompt(...)` in `app/static/dashboard/js/sections/knowledge.js`

The queue-side waiting-inquiries helper currently reuses the existing Add KB modal by pre-filling it.

### What Ship I does

Ship I should stop talking about a fictional existing modal and instead use the actual Add KB modal/workflow as the shared resolve surface.

Required UI behavior:

- queue-side `Fill KB` opens the Add KB modal pre-filled from the inquiry/topic
- Knowledge gap resolve uses the same modal/workflow instead of `window.prompt(...)`
- before save, show retry preview when count > 0:
  - `Saving this will retry 3 held drafts.`
- after save, show actual outcome:
  - `Retried 3 drafts: 2 sent, 1 returned to your queue.`

The post-save outcome line should be driven by the asynchronous retry-status surface introduced in Deliverable 2, not by blocking the save response.

### Acceptance criteria

- `window.prompt(...)` gap resolution is removed
- one shared modal/workflow is used by queue and Knowledge
- preview count is omitted when zero
- post-save feedback reflects backend result, not guesswork

### Anticipated files

- `app/static/dashboard/js/sections/knowledge.js`
- `app/static/dashboard/index.html`
- optionally API surface for preview impact if the UI needs a preflight count

## Deliverable 7 — Remove “Inquiries waiting on knowledge” from Knowledge

Once gap-held inquiries return to Action queue, the separate Knowledge waiting section becomes redundant.

### Acceptance criteria

- waiting-on-knowledge section removed from Knowledge view
- `renderWaitingInquiries()` and callers removed
- Knowledge badge no longer uses “guest waiting” urgency semantics
- Entries/Gaps management remains intact

### Anticipated files

- `app/static/dashboard/index.html`
- `app/static/dashboard/js/sections/knowledge.js`
- `app/static/dashboard/js/sections/messages.js`
- `app/static/dashboard/styles/dashboard.css`

## What Ship I does not change

- Ship H tab honesty, momentum line, or bounded layout
- Ship O deletion sequencing
- proactive/VoicePod/runtime migration work from Ships K-N
- Bayesian confidence decomposition

## Bayesian follow-up — still a good idea?

**Yes, but not as part of Ship I.**

It is still a good future direction because the operator-facing question remains valid:

- “Why is this 65%?”
- “If I fill this topic, will it likely send?”

But it is still the wrong next ship because Ship I first needs to create the missing factual substrate:

1. persisted blocked-gap topics on inquiries
2. send attribution (`triggered_by`)
3. real retry outcome data:
   - retried
   - auto-sent after retry
   - returned to queue
4. a clean single-path re-evaluation loop

Without that substrate, a Bayesian layer would still be estimating over noisy or missing signals. After Ship I runs in production for a few weeks, the Bayesian work becomes much better grounded:

- which topics most often unblock auto-send
- which kinds of gaps still return for operator review
- how much confidence actually moved after KB fill

That future ship should remain a separate effort.

## Recommendation

Ship I should be written and executed now as a **single-path Brain feature ship**.

The order should be:

1. backend field + retry hook
2. Brain-native re-evaluation
3. send attribution + summary metric
4. UI reintegration of knowledge gaps into queue
5. shared Add KB modal flow
6. Knowledge cleanup

Then revisit Bayesian decomposition with production retry data instead of theory.
