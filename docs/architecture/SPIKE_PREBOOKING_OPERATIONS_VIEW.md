# Spike — Pre-Booking Operations View

**Status:** Spike brief for Codex execution
**Type:** Spike, not Ship — designed to validate a metaphor, not to be final
**Author:** Claude, written under Hunter's direction with input from Codex
**Date:** May 2026
**Parent docs:**
- `docs/architecture/INTELLIGENCE_AND_ACCESS_FOUNDATION.md`
- `docs/architecture/VERIFIED_FOUNDATION_AUDIT.md`
- `docs/architecture/SHIP_D_PREBOOKING_REDESIGN.md`
- `docs/architecture/KNOWN_REFINEMENTS.md`

---

## What this spike is

A minimal proof that the **operations-view metaphor** is the right center for Pre-Booking. Replace the *top* of the current Pre-Booking surface with two new bands — Confidence Health and one Exception Group — while keeping the existing Ship D three-pane workspace below as the queue layer.

This is a *spike*, not a *ship*. The goal is to put real bands on real data in front of Lanier and feel whether the metaphor lands. If it feels right, subsequent ships expand it (more exception groups, intelligence band, collapsible queue, drill-in refinement). If it doesn't, we've spent a day and we know more before committing to the larger build.

The spike is deliberately small. It does not redesign anything below the new bands. It does not modify backend services. It does not introduce a new data layer. It is the smallest thing that can validate the metaphor.

---

## Why this matters

The arc from Ship A through Ship D made Pre-Booking look like a modern operator surface. But the queue-first metaphor it inherited is wrong for a product whose claim is "AI-handled guest messaging." A 10-unit operator wants reassurance, not a queue to work through. A 1000-unit operator wants oversight, not a queue to work through. Neither wants what Pre-Booking currently is.

The foundation doc commits to confidence + exceptions + intelligence as the right surface, with the queue demoted to a trust dial. This spike is the first real-world test of that commitment.

If the spike lands well, the path forward is clear: evolve Pre-Booking in place, then bring the same pattern (confidence health → exception streams → stage-specific intelligence → collapsible queue) to In-Stay, Pre-Arrival, Post-Stay. The lifecycle nav from Ship B finally fills with surfaces that match the product's claim.

---

## What this spike is not

- Not a redesign of Pre-Booking's full surface. Below the new bands, the existing three-pane workspace stays exactly as Ship D left it.
- Not the final operations view. This is two bands; the final shape includes a Pre-Booking analytics band and a collapsible queue treatment, neither of which is built here.
- Not a backend change. Every signal the spike consumes already exists in `dashboardSummary`, the messages feed, or computable from those two sources client-side.
- Not network intelligence. No network signals, no derivative product surfaces, no cross-operator data. Just operator-facing aggregates over this operator's own pre-booking activity.
- Not a conversion analytics surface. Booking attribution is not yet wired (per the verified audit), so any "conversion-correlated" claim would be storytelling. The spike's confidence-health band uses operator-action signals as proxy quality measures, not conversion outcomes.
- Not a fix for the known Ship D follow-ups (persisted Unbound-only filter; signal-band noise on long warning payloads). Those remain captured-but-secondary refinements.
- Not a parser/draft-source removal pass. The signal band still shows what it currently shows in the three-pane drill-in. Removing parser/draft-source from operator eyeline is the *next* refinement after the spike validates the metaphor.
- Not an RBAC change. The audit identified the pre-booking action enforcement gap; closing it is Phase 3 work, not spike work. The spike must not introduce new enforcement-naive code paths.

**Explicit scope guard:** Under no circumstances does the spike:
- Modify any backend service or API
- Modify the `OperationalInsightEngine`, `OperatorWorkOrderService`, `VendorIntelligenceService`, or booking-context provider
- Add new database tables, columns, or migrations
- Add new LLM calls
- Touch the OTA parser pipeline
- Modify any view other than Pre-Booking
- Change action button behavior, polling cadence, or `activeSnapshot` clobber protection in the existing Ship D code

If a change to backend or another section seems required, stop. That is later work.

---

## Verified repo reality this brief is anchored to

From the verified audit (`VERIFIED_FOUNDATION_AUDIT.md`):

- **Pre-booking inquiry data carries the signals we need today:** `confidence`, `confidenceLabel`, `confidenceSource`, `draftReady`, `draftSource`, `policyFlags`, `policyWarnings`, `propertyBindingCandidates`, `routeOutcome`, `fallbackReason`. These are scattered and provisional — not the final intelligence contract — but they are real and consumable. The spike uses them as-is, accepting one refactor pass later when Phase 1 normalizes the shape.
- **Booking attribution does not yet exist as a first-class linkage.** The spike cannot show conversion-correlated metrics. It uses operator-action proxies instead (approval rate, edit rate, held-and-then-approved rate as "AI was right to hold" signal).
- **The `messages.js` module is the active Pre-Booking section** (despite the historical filename). It owns the queue, the draft pane, the context rail, the action buttons, the polling, and the `activeSnapshot` protection. The spike adds *new* bands above the existing structure rather than rewriting it.
- **The `view-prebooking` container in `index.html`** wraps `.pb-shell-header` and `.pb-workshop`. New bands sit between the header and the workshop without touching the workshop's three-pane layout.

Everything below this brief is a frontend-only change to `messages.js`, `index.html` (the Pre-Booking section), and `dashboard.css`.

---

## Deliverables

### 1. `app/static/dashboard/index.html` — insert two new bands

Inside `<div id="view-prebooking">`, between the `.pb-shell-header` block and the `.pb-workshop` block, add a new `.pb-ops-bands` container holding two bands:

```html
<div class="pb-ops-bands" id="pb-ops-bands">

  <!-- Band 1: Confidence Health -->
  <section class="pb-ops-band pb-band-confidence" id="pb-band-confidence">
    <div class="pb-band-header">
      <div>
        <div class="pb-band-eyebrow">Confidence health</div>
        <div class="pb-band-title">How the AI is doing</div>
      </div>
      <div class="pb-band-controls">
        <select class="form-select form-select-sm" id="pb-confidence-window">
          <option value="24h">Last 24 hours</option>
          <option value="7d" selected>Last 7 days</option>
          <option value="30d">Last 30 days</option>
        </select>
      </div>
    </div>
    <div class="pb-band-body" id="pb-band-confidence-body">
      <div class="pb-band-empty">Loading confidence signals…</div>
    </div>
  </section>

  <!-- Band 2: Exception group (knowledge gaps) -->
  <section class="pb-ops-band pb-band-exceptions" id="pb-band-exceptions">
    <div class="pb-band-header">
      <div>
        <div class="pb-band-eyebrow">Exceptions</div>
        <div class="pb-band-title">Why these need you</div>
      </div>
      <div class="pb-band-controls" id="pb-band-exceptions-meta">—</div>
    </div>
    <div class="pb-band-body" id="pb-band-exceptions-body">
      <div class="pb-band-empty">Loading exceptions…</div>
    </div>
  </section>

</div>
```

This sits *above* `.pb-workshop`. The workshop is untouched. The bands collapse to zero height if their data is unavailable (defensive — see acceptance criterion 12).

### 2. `app/static/dashboard/styles/dashboard.css` — band styling

Add styles using existing Ship A tokens. No new color tokens.

- `.pb-ops-bands` — flex column, padding consistent with `.pb-shell-header`, gap between bands
- `.pb-ops-band` — card-like container, rounded, border, subtle elevation
- `.pb-band-header` — flex row with eyebrow/title on left and controls on right
- `.pb-band-eyebrow` — JetBrains Mono, small, uppercase, dim
- `.pb-band-title` — Inter, weight 500, slightly larger
- `.pb-band-controls` — flex row, right-aligned, small form controls
- `.pb-band-body` — content area, padding consistent across bands
- `.pb-band-empty` — centered, dim, friendly empty-state copy
- `.pb-conf-summary` — grid of two large stat blocks side-by-side (sent confidence, held confidence)
- `.pb-conf-stat` — single stat block with eyebrow, value, sub
- `.pb-conf-stat-value` — Cormorant Garamond serif, large (32px), color-coded by tier
- `.pb-conf-stat-sub` — small, dim, descriptive
- `.pb-conf-histogram` — small inline distribution bar (5 buckets: very low / low / medium / high / very high)
- `.pb-conf-histogram-cell` — colored proportional segment
- `.pb-exception-card` — left-border accent (amber for warning, red for blocking), padding, hover state
- `.pb-exception-meta` — JetBrains Mono, small, dim — count and time range
- `.pb-exception-title` — Inter, weight 500
- `.pb-exception-body` — Inter, regular, slightly dim
- `.pb-exception-action` — right-aligned button using existing `.btn .btn-sm` primitives

Responsive: under 800px viewport, the two confidence stats stack vertically. Bands remain visible on all viewports.

### 3. `app/static/dashboard/js/sections/messages.js` — new render functions

Add three new functions to the existing module. Do not rewrite anything that exists. Wire the new functions into the existing `loadMessages()` flow.

#### `computeConfidenceHealth(items, windowKey)`

A pure function that takes the current `state.items` and the selected window (`'24h'` | `'7d'` | `'30d'`) and returns:

```javascript
{
  windowLabel: 'Last 7 days',
  sentDrafts: {
    count: 24,
    avgConfidence: 0.91,
    avgConfidenceLabel: 'high',
    avgConfidenceTier: 'high',     // 'high' | 'medium' | 'low'
    pctHighConfidence: 78,         // % at >= 0.9
    histogram: [0, 1, 4, 12, 7],   // counts per tier bucket
    trendVsPrior: null,            // null in spike; populated later when we have stored aggregates
  },
  heldDrafts: {
    count: 6,
    avgConfidence: 0.58,
    avgConfidenceLabel: 'low',
    avgConfidenceTier: 'low',
    correctHoldPct: 67,            // % of held that the operator subsequently approved (AI was right to hold)
                                   // Computed from items where status went held → replied with low edit_distance
                                   // Honest fallback: null if not computable from current data
    histogram: [3, 2, 1, 0, 0],
    trendVsPrior: null,
  },
  notEnoughData: false,            // true if total < 10 inquiries in window — show friendly empty state
}
```

A "sent draft" is any item where `status === 'replied'` and the AI produced a draft. A "held draft" is any item where `status === 'pending_review'` and the AI either produced a low-confidence draft or held for a knowledge gap.

The `correctHoldPct` is the most subtle calculation and the most operationally interesting. In the spike, compute it as: of items that were once held (we can infer from `confidenceSource === 'fallback_placeholder'` or `draftHeldReason` if present), how many were subsequently approved (status `replied`). If the data doesn't support this calculation cleanly, surface `null` and the band shows "—" with a tooltip explaining it'll become computable once Phase 1 lands. **No fabrication.**

Window filtering uses `occurredAt`. If a window key produces fewer than 10 inquiries, set `notEnoughData = true`.

#### `computeKnowledgeGapExceptions(items)`

A pure function that returns the knowledge-gap exception group:

```javascript
{
  total: 3,                        // count of inquiries with KB gap
  byProperty: [
    { propertyName: 'Beach Habitat 12', count: 5, topGap: 'pet policy' },
    { propertyName: 'Beach Habitat 4',  count: 2, topGap: 'parking' },
  ],
  items: [                         // the actual inquiries, max 5 in spike
    { inquiryId, guestName, propertyName, gapSummary, occurredAt },
    ...
  ],
}
```

A "knowledge gap" inquiry is one where `isKnowledgeGap(item)` returns true (function already exists in `messages.js`). The grouping by property is what makes this band feel different from the queue — Lanier sees "Beach Habitat 12 has 5 knowledge gap inquiries; the recurring question is pet policy" rather than five individual rows to triage.

For the spike, just knowledge gaps. Other exception groups (low confidence, unbound, policy holds) come in subsequent ships once the metaphor is validated.

#### `renderConfidenceHealthBand()`

Reads from `computeConfidenceHealth(state.items, state.confidenceWindow)` and populates `#pb-band-confidence-body`. Two-stat grid layout: sent on the left (green/amber/red value depending on tier), held on the right (the held value is *not* red — held drafts being low-confidence is good if `correctHoldPct` is high; the framing matters).

Below the two stats, a small inline histogram showing the confidence distribution of sent drafts. The histogram is a row of five colored segments sized proportional to count. Hover any segment shows "N drafts at confidence X–Y%."

If `notEnoughData` is true, show an empty state: "Not enough activity in this window to compute reliable signals. Try a longer window, or check back as more inquiries flow."

#### `renderKnowledgeGapExceptionBand()`

Reads from `computeKnowledgeGapExceptions(state.items)` and populates `#pb-band-exceptions-body`. Render structure:

- If `total === 0`: empty state, green checkmark, "No knowledge gaps surfacing right now. Your AI is finding answers."
- Otherwise: a small list of property-grouped cards. Each card shows property name, count, recurring topic. Each card has a "Review" button that filters the queue below to those inquiries (set `state.property` and reload, or apply a local filter — Codex's choice based on what's cleaner with existing code).

Update `#pb-band-exceptions-meta` with `${total} inquiry${total === 1 ? '' : 'ies'} held for knowledge gaps`.

#### Wiring into existing flow

In `loadMessages()`, after the existing `renderList()` and friends, add:

```javascript
renderConfidenceHealthBand();
renderKnowledgeGapExceptionBand();
```

Add a state field `state.confidenceWindow = loadPreference('confidenceWindow', '7d')` at module load. Wire the `#pb-confidence-window` select change handler to update state, save preference, and re-render the band (no need to re-fetch — pure client computation).

The bands re-render on every `loadMessages()` (initial load and 30s polls). No additional network calls.

### 4. No other file changes

Specifically NOT changing:

- `app/static/dashboard/js/sections/today.js`
- `app/static/dashboard/js/sections/shell.js`
- `app/static/dashboard/js/sections/sessions.js`
- Any backend file
- Any other lifecycle view
- The `pb-workshop` markup or its three-pane structure
- The signal band rendering (`renderSignalBand` stays exactly as Ship D left it — parser/draftSource cleanup is a separate follow-up)

---

## Acceptance criteria

The spike is done when all of the following are true:

1. `/app/dashboard` → Pre-Booking shows two new bands above the existing three-pane workspace: Confidence Health and Exceptions.
2. The Confidence Health band displays two stats side-by-side: sent confidence (count and average, color-coded by tier) and held confidence (count, average, and `correctHoldPct` if computable).
3. The confidence window selector defaults to "Last 7 days" and offers 24 hours, 7 days, 30 days. Selecting a window updates the band without re-fetching from the server. The selection persists across reloads via the existing `oyvoda.dashboard.prebooking` localStorage namespace.
4. A small inline histogram below the stats shows the confidence distribution of sent drafts in the selected window.
5. When fewer than 10 inquiries exist in the window, the band shows a friendly empty state instead of misleading averages.
6. The Exceptions band shows knowledge-gap groupings by property, with count and recurring topic surfaced per group.
7. If zero knowledge-gap inquiries exist, the band shows a green "All clear" empty state.
8. The existing three-pane workspace (queue, draft pane, context rail) renders unchanged below the new bands.
9. Action buttons (Approve / Edit / Regenerate / Reject) work identically to Ship D — same endpoints, same outcomes.
10. The 30s poll cadence is preserved; mid-edit drafts are not clobbered.
11. The known Ship D follow-ups (persisted Unbound-only filter on first load; signal-band noise on long warnings) are unchanged — those are still captured for a separate cleanup.
12. If any band fails to compute (no data, error in the pure function), it shows its empty state — it does not break the surface.
13. No other view (Today, Analytics, In-Stay, etc.) is affected.
14. No console errors on Pre-Booking or anywhere else.
15. `correctHoldPct` shows `—` (not a fabricated number) if the calculation isn't supported by current data shapes.

---

## What we are watching for after deploy

This is a spike, so the *deploy* isn't the finish line — the *feedback* is.

Two qualitative tests, both done by Lanier opening the surface:

**Test 1 — Does the morning briefing land?**

Open Pre-Booking cold. Does the confidence health band tell her something useful in under five seconds? Does she look at it and feel reassurance (or warranted concern) about how the AI is doing? Or does it feel like decoration on top of the real surface (the queue) underneath?

If the band lands, she'll look at it first and the queue second. If it doesn't, she'll scroll past it. That's the signal.

**Test 2 — Do the exception groups feel different from the queue?**

The whole point of grouping knowledge-gap inquiries by property is to convert "5 individual items to triage" into "1 actionable pattern: Beach Habitat 12 needs pet policy added." Does seeing it grouped change what she'd do? Or does she ignore the grouping and click through to the queue anyway?

If the grouping changes her behavior — she goes to Knowledge and adds the pet policy entry, not to the queue and approves five drafts — the metaphor is right. If she still treats it as a queue, the grouping is cosmetic and we need to rethink.

These are not measurable in metrics yet (the spike doesn't add analytics). They are answered by Lanier using the surface for a day or two and telling Hunter what she did.

---

## What ships after the spike

The spike's outcome determines the next ship:

**If the spike lands:**
- Ship D' (Pre-Booking operations evolution) — adds Pre-Booking analytics band (top topics, top inquiry-generating properties, knowledge gap impact), collapsible queue (default 5, expandable to 25 or all), and the parser/draftSource removal pass from operator eyeline.
- Then In-Stay, Pre-Arrival, Post-Stay each redesigned around the same pattern (confidence health → exceptions → stage-specific intelligence → collapsible queue).
- Phase 1 foundation work (signal normalization, topic classification, booking attribution, property aggregates) proceeds in parallel as backend infrastructure.

**If the spike doesn't land:**
- We learn what specifically didn't work (the bands feel decorative? the confidence framing is wrong? the exception grouping is unclear?) and adjust before committing to the full evolution.
- Worst case: we keep Ship D's three-pane as the Pre-Booking surface and rethink the operations metaphor at a deeper level before propagating it to other lifecycle phases.

Either way, the spike costs a day and answers a question that's blocking the rest of the redesign sequence.

---

## Notes for the executor

- The spike is frontend-only. If you find yourself wanting to change a service or endpoint, stop. That's later.
- Use existing primitives: `.btn`, `.badge`, `.empty-state`, `.form-select`. No new color tokens.
- The `correctHoldPct` calculation is the subtle one. If you can't compute it cleanly from current data, return `null` and show `—` in the UI. **Do not fabricate or approximate.** The whole point of the band is that it tells the truth about AI quality.
- The Cormorant Garamond serif is fine for the large confidence values — that's its job. If it visually clashes with the Inter / JetBrains Mono mix in the rest of Pre-Booking, that's a Ship K visual polish concern, not a spike concern.
- The exception band is intentionally limited to knowledge gaps for the spike. Resist the urge to add low-confidence, unbound, or policy-flag groups now. One group, well-rendered, is enough to test the metaphor.
- The "Review" button on each exception card can apply a local filter or set `state.property`. Whichever is cleaner with the existing `messages.js` state machine. The button needs to *do* something useful, not just demonstrate that grouping is possible.
- The bands re-render on every poll. They are pure client-side derivations over `state.items`. No new API calls. If the existing 200-item feed isn't enough to compute the confidence health over a 30-day window, surface that honestly in the empty state rather than fetching more.
- If the existing feed's window is shorter than the user's selected window (e.g., 200 items only covers 4 days of activity, but the user picked 30 days), the band should say so: "Showing 4 days of activity available in current load."
- Do not introduce new enforcement-naive code paths. Read-only client-side computation is fine; do not add new action endpoints, do not modify existing action endpoints.

---

## Suggested implementation order

1. Add the new markup to `index.html` between header and workshop. Verify the existing surface still renders with the new (empty) bands present.
2. Add the CSS for the bands. Verify visual consistency with Ship A tokens and existing surfaces.
3. Add `computeConfidenceHealth()` as a pure function. Console-log its output against real data to verify the calculations are sane.
4. Add `renderConfidenceHealthBand()`. Verify it renders correctly across the three window sizes.
5. Add the window selector wiring and preference persistence.
6. Add `computeKnowledgeGapExceptions()` as a pure function. Console-log against real data.
7. Add `renderKnowledgeGapExceptionBand()`. Verify property grouping and "Review" button behavior.
8. Wire both renders into `loadMessages()`.
9. Smoke test in dev: verify bands render, queue still works, actions still work, polling preserves edits, no console errors.
10. Push and deploy when clean.

---

## Smoke test checklist

After implementation, manually verify on the live dashboard:

- Pre-Booking loads with two new bands above the existing three-pane workspace.
- Confidence Health band shows sent + held stats with the 7-day window selected by default.
- Window selector changes update the band without server fetch and persist across reloads.
- The histogram below the stats renders proportionally.
- Empty state copy appears cleanly when window has too little data.
- Exceptions band shows knowledge-gap groups by property.
- "All clear" empty state appears when no knowledge gaps exist.
- "Review" buttons on exception cards either filter the queue or navigate appropriately.
- The three-pane workspace below renders identically to Ship D.
- Approve / Edit / Regenerate / Reject all work as before.
- Mid-edit drafts survive a 30s poll refresh.
- Today, Analytics, In-Stay, all other views unaffected.
- No console errors anywhere.

---

*End of spike brief.*
