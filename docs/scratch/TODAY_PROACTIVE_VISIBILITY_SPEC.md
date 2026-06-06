# Today — Proactive Visibility Spec

**Status:** buildable-now frontend spec
**Date:** 2026-05-28
**Purpose:** make proactive behavior visible on the Today surface **before** proactive runtime ownership is consolidated
**Pairs with:** `docs/architecture/SHIP_C_TODAY_WORKLIST.md`, `docs/architecture/SHIP_N_PROACTIVE_TO_BRAIN.md`
**Discipline:** `docs/architecture/MIGRATION_DISCIPLINE.md` — Principles 3, 4, 6

---

## Why this exists

Proactive was designed to answer the guest's likely question **before** the guest had to ask it.

Examples of the intended behavior:

- A July 4th guest, 8 weeks out, should get a useful heads-up that beach-chair demand will be substantial and they should book now.
- A guest waking up to a rainy day or red-flag beach day should receive a helpful note like "It looks like a rainy day today — let me know if I can help plan activities."
- An arrival-phase guest should get clarifying information like "You'll receive your door code on Friday after the unit has been cleaned and inspected."

That product goal is stronger than "send lifecycle reminders." The proactive system exists to reduce inbound guest questions by answering them first.

Today, proactive behavior is split across multiple backend paths, and the Today UI does not surface enough of that behavior for an operator to see what the system is doing per guest. That makes proactive consolidation risky: if three overlapping paths are live and the row shows none of them, parity bugs become guest-visible before they become operator-visible.

This spec fixes that first.

**Intent:** build the visibility layer now, using data already on the Today payload, so:

1. Lanier can see what proactive has already done for each guest.
2. We can observe overlap/duplication before refactoring proactive ownership.
3. A later runtime consolidation has a real parity instrument.

This is not the runtime-consolidation spec. It is the observability/spec surface that should land **before** consolidation.

---

## Review outcome

After auditing the code, the proactive picture is:

### What is live today

1. **Simple timed worker**
   - `app/main.py` → `_proactive_message_worker()`
   - Sends simple due milestone touches such as welcome/check-in notifications.

2. **Stay workflow proactive path**
   - `app/services/operator/stay_proactive_service.py`
   - `app/services/operator/stay_action_agent.py`
   - Determines whether a proactive touch is eligible now, enqueues `proactive_outreach`, and composes the actual draft through the Brain.

3. **Journey service paths still reachable**
   - Historical upstream origin: `app/services/concierge/proactive/guest_journey.py` (deleted on 2026-05-28; runtime now uses `app/services/operator/stay_proactive_runtime.py`)
   - Referenced by session creation, journey endpoints, Celery evaluation, and MCP helper flows.
   - Important nuance: this module is marked preserved and is **not** the canonical brain proactive runtime owner, but it is **not dead code**.

### What the Brain already owns

- Proactive draft composition:
  - `app/services/messaging_brain/proactive_trigger_adapter.py`
  - `app/services/messaging_brain/agents/proactive_outreach_agent.py`

### What the Today payload already exposes

At the list-row level:

- `welcomeSent`
- `checkinReminderSent`
- `checkoutReminderSent`
- `extendOfferSent`
- `poolHeatOffered`
- `poolHeatAccepted`
- `notificationsSent`
- `proactiveTriggeredAt`
- `journeyTracked`
- `workflow` (including `workflow.proactive`)

At the session-detail level:

- `journey`
- `journey.activities`
- `notifications`
- `workflow`
- `events`
- `handoffs`
- `workOrders`

So the current state is not "no proactive data." It is "proactive data exists, but the Today surface throws most of it away."

---

## Scope

This spec defines:

1. the collapsed-row proactive indicator
2. the stage-aware expansion blocks for proactive/journey context
3. the exact payload fields each UI piece uses
4. what is renderable now vs. what waits for a future backend field

This spec explicitly does **not**:

- consolidate proactive runtime ownership
- add a forward-looking `scheduledTouches[]` or `upcomingProactive[]` field
- change proactive cadence rules
- retire any proactive path

If the implementation seems to require changing cadence ownership, stop. That is the next workstream, not this one.

---

## Core principle

**Do not display a forward proactive schedule until there is one canonical owner of "what touch becomes due next."**

Today there are multiple overlapping proactive entrypoints. Rendering a confident future plan from one of them would be misleading if another path is still live.

So this spec is intentionally split:

- **Retrospective / currently observable touches:** render now
- **Future scheduled touches:** wait for consolidation

That keeps the UI truthful.

---

## Build now vs. wait

### Build now (existing payload)

These can land immediately with frontend work only:

1. **Collapsed-row proactive indicator**
2. **Stage-aware proactive block in the expansion**
3. **Journey milestones in a more legible form**
4. **Context-driven touch evidence from notification history**
5. **Current proactive recommendation from `workflow.proactive`**

### Wait (future backend/routing work)

These should not ship until runtime ownership is unified:

1. **Forward plan / `scheduledTouches[]`**
2. **Typed retrospective contextual-touch milestone(s)**
3. **Per-touch typed future milestones**
4. **Confidence that one schedule is the truth**

---

## Deliverable 1 — Collapsed-row proactive indicator

### Goal

Make proactive visible at scan speed on every Today row without opening the expansion.

The operator should be able to tell, from the row alone:

- whether the guest journey is being tracked
- whether any proactive touches have already happened
- whether the system currently thinks a proactive touch is due

### Data already available

List-row payload already includes:

- `journeyTracked`
- `welcomeSent`
- `checkinReminderSent`
- `checkoutReminderSent`
- `extendOfferSent`
- `poolHeatOffered`
- `poolHeatAccepted`
- `notificationsSent`
- `proactiveTriggeredAt`
- `workflow.proactive`

### Proposed row treatment

Add a compact proactive cluster to every Today row, rendered differently by state:

#### State A — no proactive activity yet

When:

- `journeyTracked` is false
- and no proactive boolean is true
- and `notificationsSent === 0`

Render:

- nothing, or a very subtle muted "no proactive activity yet"

#### State B — proactive active, touches already sent

When any of these are true:

- `welcomeSent`
- `checkinReminderSent`
- `checkoutReminderSent`
- `extendOfferSent`
- `poolHeatOffered`
- `poolHeatAccepted`
- `notificationsSent > 0`

Render:

- badge: `Agent active`
- micro-summary:
  - `Welcome sent`
  - or `2 touches sent`
  - or `Pool heat offered`

The exact copy can be derived:

- if `welcomeSent && notificationsSent <= 1` → `Welcome sent`
- else if `notificationsSent > 0` → `${notificationsSent} touches sent`
- else fallback to the most specific true milestone

#### State C — proactive due / recommended now

When:

- `workflow.proactive.eligible === true`
- and `workflow.proactive.touch_type` exists

Render:

- badge: `Proactive due`
- micro-summary from `workflow.proactive.touch_type`
  - `Arrival reminder due`
  - `In-stay check-in due`
  - `Service update due`

This is the most important row-level state, because it tells the operator the AI has a proactive recommendation waiting even if no touch has been sent yet.

### Why this matters

This solves the "in-stay scan-ability" problem immediately. Operators can see, row by row, whether the guest has already been proactively handled or is waiting for a proactive touch.

No backend change required.

---

## Deliverable 2 — Stage-aware expansion block

> **Dependency — read before building.** Deliverables 2–3 assume the four-stage Today taxonomy defined in `docs/scratch/TODAY_FOUR_STAGE_RESHAPE_SPEC.md`: **pre-arrival / arriving / in-stay / post-stay**. They must be built *after* that reshape lands, keyed off `classification.bucket`. Deliverable 1 (the collapsed-row indicator) has no such dependency and can ship on the current three-tab surface.
>
> Stage-name reconciliation: the emphasis sections below were drafted against an earlier five-phase vocabulary. Per the reshape decision, **arrival day folds into in-stay** (a guest checking in today is already on property) and **departure day folds into in-stay** (still on property until they leave); post-stay begins the day after checkout. So treat the "Arrival day" emphasis below as describing the *first day of the in-stay tab*, and "Departure / post-stay" as describing the post-stay tab. There are only four buckets to switch on: `pre_arrival`, `arriving`, `in_stay`, `post_stay`.

### Goal

The current expansion spends its real estate on actions, timeline, work orders, recent conversation, and prior history. That is useful, but it does not foreground proactive/journey context even though the detail payload already contains it.

The expansion should change emphasis by guest stage.

### New block

Add a dedicated **Proactive journey** block inside `SessionExpansion.tsx`, using the already-normalized fields from `detail.journey`, `detail.journey.activities`, `detail.notifications`, and `detail.workflow.proactive`.

This is not a replacement for the timeline strip. It is a semantic block answering:

**What have we already done proactively for this guest, and what is the system suggesting next?**

For in-stay guests especially, it should also answer:

**Has the guest already received today's conditions-aware touch, or are we still leaving that likely question unanswered?**

### Stage emphasis

#### Pre-arrival

Foreground:

- welcome sent / pending
- check-in reminder sent / pending
- activity interests from `journey.activities`
- current proactive recommendation from `workflow.proactive`

Suggested block order:

1. journey milestones
2. activity interests / planning
3. proactive recommendation
4. recent notifications

This is the stage where proactive is most planning-heavy.

#### Arrival day

Foreground:

- welcome sent
- check-in reminder sent
- arrival-day proactive recommendation
- notifications sent today

This is where the guest is asking:

- where is the door code
- what time do I get in
- do I have what I need right now

So the block should privilege arrival certainty over generic lifecycle history.

#### In-stay

Foreground:

- conditions-aware touch evidence (weather / beach flag / local conditions)
- current proactive recommendation from `workflow.proactive`
- service-update reassurance if present
- weather / market-driven touch evidence from `notifications`
- pool heat offered / accepted

This is the place the current UI is weakest. In-stay should tell the operator:

- has the guest already been proactively checked on
- has the guest already received the important context-driven touch for today's conditions
- is the system backing off
- is a reassurance or nudge currently recommended

This matters because the most differentiated proactive behavior is not the generic lifecycle milestone. It is the contextual touch that answers a likely guest question before they ask it:

- rainy day → "want help planning activities?"
- red-flag beach day → safety note / alternative plans
- peak-demand holiday lead time → "book beach chairs now"

Even though these touches currently surface through generic notification history, the expansion should treat them as a first-class thing the operator looks for in the in-stay stage.

#### Departure / post-stay

Foreground:

- checkout reminder sent
- extend offer sent / response
- feedback-related actions (already surfaced elsewhere)

This is lower-volume but still part of the same truth surface.

---

## Deliverable 3 — What the proactive block renders

### 1. Journey milestones

Use `detail.journey` booleans/timestamps:

- `welcomeSent`, `welcomeSentAt`
- `checkinReminderSent`, `checkinReminderSentAt`
- `checkoutReminderSent`, `checkoutReminderSentAt`
- `extendOfferSent`, `extendOfferSentAt`, `extendOfferResponse`
- `poolHeatOffered`, `poolHeatAccepted`

Render as a short list or badge strip with timestamps where present.

### 2. Activity interests

Use `detail.journey.activities`.

Render grouped by status:

- `not_discussed`
- `info_provided`
- `booked`
- `handled`
- `not_interested`

This is where the richer proactive intent starts to show up operationally:

- beach chairs
- groceries
- golf
- fishing
- bikes

Even if runtime ownership is not unified yet, surfacing this state makes the operator’s mental model much clearer.

### 3. Current proactive recommendation

Use `detail.workflow.proactive`.

Render:

- `touch_type`
- `message`
- `receptiveness_score`
- `allowed_touch_family`
- `backoff_active`
- `backoff_reason`

This is the real "what would the system do next right now?" block available today.

Important:

- this is **current recommendation**, not forward schedule
- label it accordingly
- do not imply it is a full journey plan

Suggested label:

- `Current proactive recommendation`

Not:

- `Upcoming touches`
- `Scheduled plan`

### 4. Contextual touches and recent notifications

Use `detail.notifications`.

This is where the strongest differentiated proactive behavior most likely surfaces today:

- weather-driven touches
- red-flag / beach-safety touches
- local-conditions nudges
- demand-aware reminders that were sent as guest notifications

These are not "just another notification" in product meaning. They are the clearest evidence that Oyvoda is proactively answering the guest's likely question before the guest asks it.

In the rendered block, this should appear as a first-class proactive category, not as a generic catch-all footer under lifecycle history.

Today they are still represented through the generic notifications array, so the first version of the UI should render them there. But the block should frame them as **context-driven touches**, not as generic delivery history.

Render the last few with:

- type
- channel
- sent/delivered state
- sent time

**Implementer note — finding the contextual touch in an untyped array.**
Contextual touches are precisely the touches that do *not* have a distinguishing `notificationType` today — that absence is the reason the typed retrospective field is listed under "wait for backend." So a naive render of raw `notificationType` will make a rainy-day note, a checkout reminder, and a delivery receipt look identical, and the in-stay "did today's conditions touch go out?" question becomes unanswerable at a glance — quietly degrading this promoted first-class category back into footer noise.

To prevent that in v1, the UI should **infer the contextual category from the notification body/content when the type is generic** — a best-effort client-side classification (e.g. body mentions weather / rain / flag / heat / avalanche / red-flag conditions → render as a conditions-aware touch with distinct treatment). This is explicitly a **heuristic for the visibility layer only**, not a source of truth: label it as inferred, never assert it as a typed fact, and plan to replace it with the typed retrospective contextual-touch field once runtime ownership is consolidated. The heuristic exists so the in-stay conditions question is answerable now; the typed field exists so it's answerable *reliably* later.

This is the operator’s proof of what actually went out, including the conditions-aware touches that make proactive more than lifecycle reminders.

---

## Deliverable 4 — Explicit render-now / wait-later boundary

This boundary must be written into the implementation comments and kept clear in the UI copy.

### Render now

- milestone booleans
- milestone timestamps
- notification history
- journey activity state
- current proactive recommendation

### Wait for a future backend field

- `scheduledTouches[]`
- `upcomingProactive[]`
- "next touch fires on June 3"
- ordered future journey plan
- notification body/content on `detail.notifications`, so the visibility-layer heuristic can inspect the actual guest-touch text instead of only metadata
- typed contextual-touch milestone(s), for example a first-class field indicating that a weather / beach-flag / market-conditions proactive touch was sent

Reason:

Until proactive runtime ownership is unified, a future-looking schedule would be projecting certainty the system does not yet have.

There is also a second future modeling gap worth naming now so it is not lost in consolidation: conditions-aware touches are currently visible only through generic notification history, and the current detail payload does not expose notification body/content. That means the visibility layer can only do best-effort metadata inference today. The cheaper unlock is to expose notification body/content in the detail payload so the existing heuristic can inspect the actual guest-touch text. The richer long-term fix is the typed retrospective contextual-touch field, which would make the conditions-aware touch visible as first-class truth rather than inferred evidence.

---

## Copy guardrails

This surface should speak in a way that matches the product intent: proactive is about getting ahead of the guest’s question.

Good examples:

- `Welcome already sent`
- `Arrival reminder due`
- `Current proactive recommendation`
- `2 guest touches already sent`
- `System is backing off after recent outreach`

Avoid:

- `automation`
- `campaign`
- `template`
- `sequence`

Those words frame proactive as a marketing system. This is an operational guest-support system.

---

## Success criteria

### Immediate

- An operator can scan Today and tell which guests:
  - have already received proactive outreach
  - are currently due for a proactive touch
  - are being backed off
- An operator can open a row and understand the guest’s proactive state without leaving Today.

### Later

- This visibility surface becomes the parity instrument for proactive runtime consolidation.
- After consolidation, it is obvious from the same row/expansion whether duplicate or missing touches were introduced.

---

## Not in this spec

- runtime consolidation / keep-migrate-retire plan
- migration of `guest_journey.py`
- deletion of `_proactive_message_worker`
- projection of future scheduled touches

Those come next, after this visibility layer lands.

---

## Recommended next sequence

1. Ship this frontend visibility work.
2. Observe real Lanier guests with the new visibility surface.
3. Write the proactive runtime seam map (`keep / migrate / retire`) using what the operator can now actually see.
4. Consolidate ownership onto:
   - eligibility: `stay_proactive_service`
   - composition: `messaging_brain`
   - execution: `StayActionAgent`
5. Only then add a truthful `scheduledTouches[]` field if still needed.
