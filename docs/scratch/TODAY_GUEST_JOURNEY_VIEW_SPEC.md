# Today — Guest Journey View-Mode Spec

**Status:** buildable-now frontend spec
**Date:** 2026-05-28
**Purpose:** add a chronological "Journey" view-mode to the Today row expansion that shows everything done for a confirmed guest — proactive touches, guest messages, brain replies, and operational events — as one time-ordered stream
**Pairs with:** `docs/scratch/TODAY_PROACTIVE_VISIBILITY_SPEC.md`, `docs/scratch/TODAY_FOUR_STAGE_RESHAPE_SPEC.md`
**Precedes:** the in-stay draft parity surface (separate spec, written after this ships)

---

## Why this exists

The operator needs to see, on demand, what has been done for a guest across the whole stay — not as four separate panels (journey milestones, notifications, messages, events) but as one chronological narrative: welcome sent → beach-chair nudge → guest reply → check-in → conditions touch → guest question → brain reply.

Scope decision (2026-05-28): the guest journey **begins at booking**, when identity is confirmed (name, email, phone, reservation). There is no attempt to stitch anonymous pre-booking inquiries to a guest. The journey is the confirmed-guest session and everything logged against it from booking forward. Pre-booking remains a separate, pre-identity, message-first surface with no journey.

Access decision: the operator only views a journey for a guest **currently reachable in a Today tab** (pre-arrival / arriving / in-stay / post-stay). No standalone surface is needed, because every guest worth viewing is already a Today row. So the journey is a **view-mode inside the existing `SessionExpansion.tsx`**, not a new route. It is reached on demand by toggling the expanded row from its default "Blocks" view to "Journey".

This is a **read surface**. It shows the record. It has no approve / edit / send / act controls. Actioning lives in the Blocks view (the existing Actions block) and, later, in the in-stay draft parity surface. See the hard boundary below.

---

## What already exists

`routes/Today/timeline.ts` → `deriveTimeline(detail)` already merges into one time-ordered array:

- journey flags (welcome, check-in reminder, checkout reminder, extend offer) — boolean + timestamp
- stay events (`detail.events`) — housekeeping, vendor, walkthrough, etc., with failed/blocked → alert tone
- open escalations (`detail.openEscalations`) — alert dots by createdAt
- turnover lifecycle (started, ready)

It sorts ascending by `occurredAt`, with timestamp-less dots landing at the end. It is read-only by design (its own comment says so).

So roughly 70% of the journey merge is built. What `deriveTimeline` does NOT include — and what makes a journey distinct from the current ops strip — is the **conversation and proactive-send layer**:

- `detail.messages` — guest turns (`direction: 'inbound'`) and operator/brain turns (`direction: 'outbound'`), with `content`, `createdAt`, `intent`
- `detail.notifications` — proactive sends (welcome, reminders, and the contextual weather/flag touches), with `notificationType`, `channel`, `status`, `sentAt`

The journey view = extend the existing merge to fold in messages + notifications, tag every entry by source, and render it as a vertical timeline instead of a horizontal dot strip.

---

## Scope

This spec defines:

1. a view-mode toggle in the expansion (Blocks ↔ Journey)
2. a `deriveJourney(detail)` function that extends the existing merge with messages + notifications and tags each entry by source
3. the vertical timeline rendering
4. the read-only boundary

This spec explicitly does **not**:

- add any send / approve / edit / decline control to the journey view
- create a new route or surface
- change the detail payload or any backend
- attempt cross-session (multi-stay) history stitching — the journey is the current confirmed session; cross-session history remains the existing "Prior history with this guest" block in the Blocks view
- build the in-stay held-draft parity surface (separate, later spec)

If building this seems to require a send control or a backend field, stop — that's the in-stay draft workstream, not this one.

---

## Hard boundary — read-only

**The journey view renders history. It never sends, approves, edits, or declines anything.**

This matters because the journey will faithfully display things that are *not* fully resolved — e.g. an in-stay brain reply that was held as an `ops_review` action with no first-class send path (per the brain-wiring trace, 2026-05-28). The journey shows that this happened. It is NOT the place to fix it. The temptation will be to add an "approve & send" button next to a held draft entry in the timeline; do not. That capability is the in-stay draft parity surface, built separately, because it sends real guest messages and reconciles the email/SMS executor split. The journey view is a window; the parity surface is a control panel. Keep them separate.

Implementer guard: the journey timeline entries are presentational only. No entry carries an onClick that triggers an API call. If an entry needs to deep-link somewhere (e.g. "open this escalation"), that's navigation, not action, and is out of scope for v1 — render it inert.

---

## Deliverable 1 — view-mode toggle

In the expansion header (`SessionExpansion.tsx`), add a two-option toggle: **Blocks** (current default — actions, timeline strip, work orders, conversation, prior history) and **Journey** (the new chronological stream).

- Default to Blocks. The operator opts into Journey when they want the narrative.
- Local component state (`useState`), not URL state — the view-mode is an ephemeral per-open preference, not a deep-linkable thing. (If later we want it to persist across opens, that's a small follow-up; not v1.)
- The toggle controls only what renders below the header; the close affordance and the row identity stay constant across both modes.

---

## Deliverable 2 — `deriveJourney(detail)`

Add to `timeline.ts` (it already owns the merge logic and the `SessionDetail` type). Do NOT duplicate `deriveTimeline` — `deriveJourney` is a richer sibling that reuses the same sources and adds two more.

### Entry shape

```
type JourneySource = "proactive" | "guest" | "brain" | "event" | "milestone";

type JourneyEntry = {
  key: string;
  source: JourneySource;
  label: string;
  body: string | null;        // message text / touch preview, when present
  occurredAt: string | null;
  tone: "done" | "alert" | "pending" | "info";
  inferredContextual?: boolean; // see contextual-touch note
};
```

### Sources to merge

1. **Booking-confirmed anchor** — synthesize one `milestone` entry at the start: "Booking confirmed — journey begins", dated from the session's earliest known timestamp (reservation/created). This gives the timeline a head and reinforces the "journey starts at booking" model.
2. **Everything `deriveTimeline` already produces** — journey flags, events, escalations, turnover. Reuse it; map its `TimelineDot`s into `JourneyEntry`s (`milestone`/`event` source, carry tone).
3. **Messages** (`detail.messages`) — each becomes an entry: `source: 'guest'` for inbound, `source: 'brain'` for outbound (brain/operator-composed). `body` = `content`. Label like "Guest asked · {channel-or-intent}" / "Replied". Include confidence/auto-sent context in the label where the message carries it.
4. **Notifications** (`detail.notifications`) — proactive sends. `source: 'proactive'`. `body` = the touch preview if available. This is where welcome/reminder sends AND the contextual weather/flag touches appear.

### Ordering

Same as `deriveTimeline`: ascending by `occurredAt`, timestamp-less entries at the end. The booking-confirmed anchor sorts first (earliest timestamp).

### De-duplication

Note: a proactive touch may appear BOTH as a journey flag (e.g. `welcomeSent`) AND as a notification row. Collapse these — prefer the notification (it has channel + status + body) and drop the bare flag when a matching notification exists for the same touch. If matching is unreliable, show the flag only when no notification covers it. Do not render the welcome twice.

---

## Deliverable 3 — contextual-touch tagging

Reuse the heuristic from the proactive visibility spec (Deliverable 3 note): when a notification's type is generic, infer the contextual category from body/content (mentions weather / rain / flag / heat / avalanche / red-flag) and set `inferredContextual: true`. Render inferred-contextual entries with a distinct, labeled treatment ("inferred · conditions") — **never asserted as a typed fact**.

Same caveat as that spec: the detail payload does not currently expose notification body, so this inference is metadata-only until the cheap backend unlock (expose notification body) lands. Build the tagging so it activates automatically once body is available, but do not claim conditions-classification it can't actually make today. If body is absent, the entry renders as a plain proactive touch with no conditions tag.

---

## Deliverable 4 — rendering

Vertical timeline. Each entry: a source-colored dot on a connecting spine, a label row (label + timestamp), and an optional body (the message/touch text, quoted/indented).

- **Source encodes color**, consistently: proactive = success/green tone, guest = info/blue, brain = info/blue (distinguished from guest by label + alignment, not a third color — keep to ≤2 ramps), event/milestone = neutral/tertiary, alert (failed event, open escalation) = danger.
- Body text (message content, touch preview) indented under its entry, visually quoted.
- Inferred-contextual entries carry the labeled "inferred · conditions" marker.
- Empty state: if a journey has only the booking anchor and nothing else (a freshly-booked pre-arrival guest), render the anchor plus a calm "No touches yet — proactive will begin as the stay approaches." Do NOT render a wall of empty sections. (This is the pre-arrival hollow-row risk from the proactive spec; the journey view must read calm, not broken, for low-activity guests.)

---

## Copy guardrails

Same as the proactive visibility spec: this is an operational guest-support record, not a marketing log. Avoid "campaign", "sequence", "automation". Prefer plain operational phrasing: "Welcome sent", "Guest asked about late checkout", "Replied", "Red-flag beach day note".

---

## Success criteria

- Opening any Today row and switching to Journey shows that guest's confirmed-session history as one chronological stream, across mediums.
- Proactive touches, guest messages, and brain replies are visually distinguishable by source at a glance.
- A freshly-booked pre-arrival guest's journey reads calm (anchor + "nothing yet"), not hollow.
- No entry in the journey view triggers a send/approve/edit/decline. It is provably read-only.
- A held in-stay brain reply appears in the journey as history (showing the asymmetry exists) without offering a send control (that's the next surface).

---

## Not in this spec / sequence

1. **This** — journey view-mode (read-only), build now.
2. **Next, after this ships** — the in-stay draft parity surface (held drafts as a first-class operator reply action; surfacing in_stay KB-gap state inline). Separate spec, written after the journey lands and real Lanier data sharpens the visibility-vs-send-loop decision. Sends real guest messages; reconciles the email/SMS executor split; reads the autonomy gate. Deliberate, separately-spec'd build.
