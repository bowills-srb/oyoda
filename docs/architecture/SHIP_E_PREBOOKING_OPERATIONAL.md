# Ship E — Pre-Booking Operational Surface

**Status:** Ship brief for Codex execution
**Type:** Real ship, not a spike. Replaces and supersedes `SPIKE_PREBOOKING_OPERATIONS_VIEW.md`.
**Author:** Claude, written under Hunter's direction with confirmation from Codex
**Date:** May 2026
**Parent docs:**
- `docs/architecture/INTELLIGENCE_AND_ACCESS_FOUNDATION.md`
- `docs/architecture/VERIFIED_FOUNDATION_AUDIT.md`
- `docs/architecture/SHIP_D_PREBOOKING_REDESIGN.md`
- `docs/architecture/KNOWN_REFINEMENTS.md` (see "Long-term Pre-Booking shape" section)
- `docs/architecture/SPIKE_PREBOOKING_OPERATIONS_VIEW.md` (superseded — component design preserved, surface positioning replaced)

---

## What this ship is

Evolve Pre-Booking from Ship D's three-pane workspace into the long-term operational surface — with day-one-friendly defaults that keep the queue dominant while the operator builds trust in the AI.

The decision framing (locked in `KNOWN_REFINEMENTS.md`): **build the long-term interface, make it short-term friendly through proportions.** Same surface, different defaults as operators mature. No mode switches, no separate inbox-vs-operations views, no rebuild later.

The surface, top to bottom, is:

1. Compact resolution-counts header
2. Compact confidence health band (one or two strong numbers, no histogram in this ship)
3. Compact knowledge-gap exception group (single group, property-rolled)
4. The queue, taking dominant space by default
5. Selected-inquiry drill-in (the existing Ship D three-pane workspace, repositioned)
6. Pre-Booking analytics band, below the fold (placeholder shell in this ship; populated when Phase 1 attribution lands)

Three Ship D follow-ups land as part of this ship rather than as separate patches:
- Persisted "SHOWING UNBOUND ONLY" filter on initial load (investigate and fix)
- Signal band noise on long warning payloads (truncate with hover-to-expand)
- Parser source / draft source / route outcome removed from operator eyeline

---

## What this ship is not

- Not a redesign of any other lifecycle view. In-Stay, Pre-Arrival, Post-Stay are unchanged.
- Not a backend rewrite. Resolution counts come from existing `dashboardSummary`. Confidence aggregates are pure client-side derivations over `state.items`. Knowledge gaps use existing `isKnowledgeGap()` predicate and existing inquiry data.
- Not booking-attribution-dependent. The analytics band is a placeholder shell that displays topic-frequency and inquiry-volume aggregates today, and will fill in conversion-correlated metrics when Phase 1 attribution lands.
- Not auto-mode. The auto-send toggle is a future ship. This ship makes the surface ready for auto-mode (queue compresses when auto-mode flips on), but does not add the toggle itself.
- Not network intelligence. Single-operator, single-tenant, this operator's own data only.
- Not new APIs. Every signal consumed already exists.
- Not new LLM calls.
- Not new database tables, columns, or migrations.
- Not parser-pipeline changes. The three captured FIX briefs (`FIX_1_AIRBNB_DETERMINISTIC_FIRST.md`, `FIX_2_INQUIRY_REGRESSION_CORPUS.md`, `FIX_3_DAILY_BINDING_REPORT.md`) remain captured-but-secondary, not in scope here.
- Not an RBAC change. The audit identified the pre-booking action enforcement gap (`operator_onboarding.py` approves without capability checks); closing it is Phase 3 work. This ship must not introduce new enforcement-naive code paths.

**Explicit scope guard:** Under no circumstances does Ship E:
- Modify any backend service or API endpoint
- Modify `OperationalInsightEngine`, `OperatorWorkOrderService`, `VendorIntelligenceService`, or booking-context provider
- Add database tables, columns, or migrations
- Add LLM calls
- Touch other lifecycle views
- Change action button behavior (Approve / Edit / Regenerate / Reject keep their existing endpoints and outcomes)
- Change polling cadence or `activeSnapshot` clobber protection
- Introduce server-side mutation endpoints that aren't capability-checked

If a backend change seems required, stop. That is later work.

---

## Verified repo reality this brief is anchored to

From the verified audit (`VERIFIED_FOUNDATION_AUDIT.md`):

- **Pre-booking inquiry data carries the signals we need today:** `confidence`, `confidenceLabel`, `confidenceSource`, `draftReady`, `draftSource`, `policyFlags`, `policyWarnings`, `propertyBindingCandidates`, `routeOutcome`, `fallbackReason`, `asks`, `intent`. Scattered and provisional, but real and consumable. This ship uses them as-is; Phase 1 normalizes them later.
- **Booking attribution does not yet exist as a first-class linkage.** No conversion-correlated metrics in this ship. The confidence band uses `correctHoldPct` as the most subtle quality proxy if computable from current data; otherwise shows `—`.
- **The `messages.js` module is the active Pre-Booking section** despite the historical filename. Owns the queue, draft pane, context rail, action buttons, polling, and `activeSnapshot` protection.
- **`dashboardSummary` already exposes the data needed for the resolution-counts header.** `preBooking.pending`, `sessions.active`, `escalations.open`, `inbox.lastPolledAt`, `inbox.lastPollSummary` are all accessible via `state.get('dashboardSummary')`.
- **The Ship D three-pane (`pb-workshop` block) is intact and shipping in production.** This ship modifies what surrounds it, not the workshop itself.

Everything in this ship is frontend-only.

---

## Default proportions and the trust dial

The same surface re-proportions based on the operator's relationship with the AI. **This ship implements the day-one defaults.** Future ships (auto-mode toggle, mature-operator polish) adjust the rules.

Day-one rule, implemented in this ship:

- Queue depth defaults to **25 rows** for any operator who has not enabled auto-send
- Operator can override via a depth control: **5 / 10 / 25 / all**
- Selection persists across sessions in the existing `oyvoda.dashboard.prebooking` localStorage namespace
- Bands above the queue are compact: resolution header is one line, confidence band is one to two strong numbers, knowledge-gap exception group is a compact property-rolled list

Future rule (not implemented here, documented for context):

- When auto-send is enabled (future ship), default queue depth becomes **5 rows** and the bands take more visual weight
- The operator can still override depth manually

The mechanism is the same. The defaults are different. The surface doesn't change shape.

---

## Deliverables, top to bottom

### 1. Resolution-counts header

A single compact line at the top of `view-prebooking`, above any band:

```html
<div class="pb-resolution-header" id="pb-resolution-header">
  <span class="pb-rh-segment"><strong id="pb-rh-resolved">—</strong> resolved</span>
  <span class="pb-rh-sep">·</span>
  <span class="pb-rh-segment"><strong id="pb-rh-pending">—</strong> pending</span>
  <span class="pb-rh-sep">·</span>
  <span class="pb-rh-segment"><strong id="pb-rh-escalations">—</strong> escalations</span>
  <span class="pb-rh-sep">·</span>
  <span class="pb-rh-segment pb-rh-inbox" id="pb-rh-inbox">inbox status loading…</span>
</div>
```

Populated by a new function `renderResolutionHeader()` in `messages.js`:

- Resolved count = `summary.replied` (the existing `state.summary.sent` field from `buildSummary`)
- Pending = `state.summary.pending`
- Escalations = `dashboardSummary.escalations.open`
- Inbox status = `dashboardSummary.inbox.lastPollSummary` or `"last polled Xm ago"` if `lastPolledAt` is set, else `"inbox status unknown"`

If `inbox.lastPollError` is set, the inbox segment gets `class="pb-rh-inbox pb-rh-inbox-error"` and shows the error label. Same pattern as the existing `renderStatusLine()` treatment.

The framing is honest, not decorative. No trend arrows in this ship. No comparison to prior periods. The header tells the operator what's happening right now, period.

### 2. Compact confidence health band

A single-line band below the header. Two numbers, that's it:

```html
<section class="pb-ops-band pb-band-confidence" id="pb-band-confidence">
  <div class="pb-band-header">
    <div class="pb-band-eyebrow">Confidence health</div>
    <div class="pb-band-window-control">
      <select class="form-select form-select-sm" id="pb-confidence-window">
        <option value="24h">24h</option>
        <option value="7d" selected>7d</option>
        <option value="30d">30d</option>
      </select>
    </div>
  </div>
  <div class="pb-band-body" id="pb-band-confidence-body">
    <div class="pb-conf-compact-line">
      <span class="pb-conf-stat">
        <span class="pb-conf-stat-value" id="pb-conf-sent-value">—</span>
        <span class="pb-conf-stat-label">avg confidence on sent · <span id="pb-conf-sent-count">—</span> drafts</span>
      </span>
      <span class="pb-conf-divider"></span>
      <span class="pb-conf-stat">
        <span class="pb-conf-stat-value" id="pb-conf-held-value">—</span>
        <span class="pb-conf-stat-label">held for review · <span id="pb-conf-held-count">—</span> drafts · <span id="pb-conf-correct-hold">—</span> correct holds</span>
      </span>
    </div>
  </div>
</section>
```

Populated by `renderConfidenceBand()` which computes from `state.items` filtered by `state.confidenceWindow`:

- **Sent stat:** of items where `status === 'replied'` and `confidence` is present, compute the average. Display as percentage with tier color (`high` ≥ 0.9 green, `medium` ≥ 0.7 amber, `low` red). Display count.
- **Held stat:** of items where `status === 'pending_review'` and the draft was held (`confidenceSource === 'fallback_placeholder'` OR `isKnowledgeGap(item)` OR `fallbackReason` is set), compute the average. Display count.
- **`correctHoldPct`:** of items that were once held and are now `replied`, what percent did the operator approve. If the data shape doesn't support this calculation cleanly today, show `—` and a `title` tooltip: `"Will populate once inquiry signal normalization lands"`. **No fabrication.**

The window selector defaults to `7d`, persists to `oyvoda.dashboard.prebooking.{operatorKey}.confidenceWindow`. Selecting a window re-renders the band over the current `state.items` without re-fetching. If the feed's available window is shorter than the selected window (e.g., 200 items only covers 4 days but operator picked 30d), surface that honestly: `"Showing N days of activity available in current load"`.

No histogram in this ship. No trend-vs-prior in this ship. Compact is the point.

If the window has fewer than 10 inquiries total, show `"Not enough activity to compute reliable signals — try a longer window"` in place of the numbers.

### 3. Compact knowledge-gap exception group

Single exception group: knowledge gaps, property-rolled.

```html
<section class="pb-ops-band pb-band-exceptions" id="pb-band-exceptions">
  <div class="pb-band-header">
    <div class="pb-band-eyebrow">Knowledge gaps blocking AI drafts</div>
    <div class="pb-band-meta" id="pb-band-exceptions-meta">—</div>
  </div>
  <div class="pb-band-body" id="pb-band-exceptions-body">
    <div class="pb-band-empty">Loading…</div>
  </div>
</section>
```

Populated by `renderKnowledgeGapBand()` consuming `computeKnowledgeGapGroups(state.items)` which returns:

```javascript
{
  total: N,                       // total knowledge-gap inquiries (filtered by isKnowledgeGap)
  byProperty: [
    {
      propertyId: 'BHA12',
      propertyName: 'Beach Habitat 12',
      count: 5,
      topGapTopic: 'pet policy',   // most-frequent gap topic across this property's items
      sampleInquiryIds: [...]
    },
    ...                            // sorted by count desc, max 5 rows in this ship
  ]
}
```

Render:
- If `total === 0`: small green "All clear" empty state — `"No knowledge gaps blocking AI drafts right now."`
- Otherwise: a compact list of property cards. Each card shows property name, gap count, recurring topic, and a `"Review"` button. Clicking `"Review"` sets `state.property = propertyId`, clears `state.unboundOnly`, and reloads — effectively filtering the queue below to just that property's items.
- Meta in header: `"{total} inquiries held across {byProperty.length} properties"`

`topGapTopic` is derived from `policyWarnings` entries that start with `missing_property_knowledge:`. Strip the prefix and humanize. If multiple warnings on a single inquiry, pick the most common across the property's items. If empty, show `"recurring questions"` as a fallback label.

Only knowledge gaps in this ship. Other exception groups (unbound inquiries, low-confidence held drafts, policy-flagged inquiries) are deliberately deferred to keep this ship focused.

### 4. The queue, with depth control

The existing Ship D queue rendering stays. What changes:

- A **depth control** in the queue's group head: a small inline control offering `5 / 10 / 25 / all`. Default `25` for new operators. Persisted to `oyvoda.dashboard.prebooking.{operatorKey}.queueDepth`.
- `visibleItems()` truncates to the depth setting (after all other filters). If `all`, no truncation.
- The "Action queue" group head shows `"Pending operator review"` as today, plus the depth control on the right side. Count reflects the total *before* depth truncation, with truncation indicated: e.g., `"Showing 25 of 47"` if truncated.

The queue takes the dominant vertical share by default. CSS rule: `.pb-queue-pane` becomes `flex: 1 1 auto; min-height: 480px` (or whatever value lands 25 rows visible without scrolling on a typical operator laptop viewport). The bands above are sized by their content; the queue absorbs the remainder.

When the operator picks `5` or `10`, the queue pane shrinks proportionally and the bands above effectively gain more visual weight without their own dimensions changing. That's the trust dial mechanism — depth controls the proportions.

### 5. Selected-inquiry drill-in (preserved)

The existing Ship D three-pane workspace (`.pb-workshop`) is the drill-in state when a queue row is selected. Markup, JS rendering, action buttons, polling protection, and `activeSnapshot` all preserved.

Two changes within the drill-in:

- **Signal band cleanup (Ship D follow-up):** remove `draftSource`, `parserSource`, `routeOutcome` chips from `renderSignalBand()`. Keep `confidenceLabel`, `policyWarnings`, `policyFlags`, `fallbackReason`. The removed fields remain available in `state.items` for engineering/support; they just don't appear in the operator's UI.
- **Signal band truncation (Ship D follow-up):** each chip's `value` text caps at 40 characters with ellipsis. Add a `title` attribute with the full text. One-line patch to the chip construction in `renderSignalBand()`.

Editing-in-place stays the primary action. Send / Regenerate / Reject behave identically.

### 6. Pre-Booking analytics band (placeholder shell)

A band below the queue, scrolled to. Visible structure, deliberately limited content this ship:

```html
<section class="pb-ops-band pb-band-analytics" id="pb-band-analytics">
  <div class="pb-band-header">
    <div class="pb-band-eyebrow">Pre-Booking patterns</div>
    <div class="pb-band-meta">last <span id="pb-analytics-window">7</span> days</div>
  </div>
  <div class="pb-band-body" id="pb-band-analytics-body">
    <div class="pb-band-empty">Loading…</div>
  </div>
</section>
```

Populated by `renderAnalyticsBand()` consuming `computeAnalyticsAggregates(state.items, state.confidenceWindow)`:

- **Top recurring topics:** count of inquiries by `intent` field (existing), plus by humanized `asks` entries. Show top 5 with counts.
- **Top inquiry-generating properties:** count of inquiries grouped by `propertyName` over the window. Show top 5 with counts.
- **Knowledge gap recurrence:** the same `byProperty` list from the exception group, but with totals across the full window not just current pending. Show count of distinct properties with gaps.

Conversion-correlated metrics are explicitly absent in this ship. The band copy reads honestly: `"Conversion correlation will appear once inquiry-to-booking attribution is live."` This is a placeholder shell, not a fake.

The band uses the same window as the confidence band (`state.confidenceWindow`). Re-renders when the window changes.

### 7. The three Ship D follow-ups, summarized

These are folded into the ship rather than separate patches:

a. **Unbound-only filter persistence (server vs client investigation).** Investigate by making a clean `/app/api/messages` request with no query params and observing the response. If `unboundOnly: true` comes back from the server, fix it server-side. If the client is somehow setting `state.unboundOnly = true` before the first fetch, fix it client-side. Either way, the fix is small and lives in the file Codex identifies during investigation. The acceptance criterion is: fresh load shows all inquiries, not unbound-only, until the operator explicitly filters.

b. **Signal band truncation.** Covered in Deliverable 5.

c. **Parser/draft-source/route-outcome removal from operator eyeline.** Covered in Deliverable 5.

---

## Files involved (frontend only)

- `app/static/dashboard/index.html` (Pre-Booking view markup restructure)
- `app/static/dashboard/styles/dashboard.css` (new compact-band styles, queue depth control, resolution header)
- `app/static/dashboard/js/sections/messages.js` (new render functions, depth control wiring, follow-ups)
- `app/static/dashboard/js/adapters.js` (only if a new normalized field is needed; default assumption is no changes)

Backend: nothing, unless the unbound-only investigation finds a server-side cause, in which case one targeted backend fix in the offending endpoint.

---

## Acceptance criteria

The ship is done when all of the following are true:

1. `/app/dashboard` → Pre-Booking shows the new surface: resolution header, confidence band, knowledge-gap exception group, queue with depth control, drill-in workspace, analytics band.
2. Resolution header displays correct counts from `dashboardSummary` and updates on each poll.
3. Confidence band shows sent and held average confidence with counts. `correctHoldPct` shows a real value or `—` (never fabricated).
4. Confidence window selector defaults to 7d, offers 24h/7d/30d, persists across reloads, re-renders without server fetch.
5. Knowledge-gap exception group shows property-rolled rows when gaps exist, with working "Review" buttons that filter the queue to the chosen property.
6. Knowledge-gap empty state appears with calm copy when no gaps exist.
7. Queue depth control offers 5/10/25/all, defaults to 25 for operators without auto-mode, persists across reloads.
8. Queue truncates to depth selection and shows "Showing N of M" when truncated.
9. Selecting a queue row opens the drill-in workspace exactly as Ship D did.
10. Signal band in drill-in no longer shows parser source, draft source, or route outcome chips.
11. Signal band chips with long values are truncated at 40 chars with full text on hover.
12. Unbound-only filter does NOT persist across sessions on fresh load.
13. Action buttons (Approve / Edit / Regenerate / Reject) work identically to Ship D — same endpoints, same outcomes.
14. The 30s poll cadence is preserved; mid-edit drafts are not clobbered.
15. Pre-Booking analytics band shows top topics, top properties, and knowledge-gap recurrence with honest "conversion correlation pending attribution" copy.
16. Today, Analytics, In-Stay, Pre-Arrival, Post-Stay, and all other views are unaffected.
17. No console errors anywhere.
18. No new server-side mutation endpoints introduced.

---

## Suggested implementation order

1. **Resolution-counts header.** Smallest, lowest risk. Markup, CSS, `renderResolutionHeader()`. Verify with live data.
2. **Confidence band (compact form).** Markup, CSS, `computeConfidenceHealth()`, `renderConfidenceBand()`, window selector wiring.
3. **Knowledge-gap exception group.** Markup, CSS, `computeKnowledgeGapGroups()`, `renderKnowledgeGapBand()`, "Review" button wiring.
4. **Queue depth control.** Modify queue group head, add depth selector, update `visibleItems()` truncation, persist preference.
5. **Layout proportions.** CSS tuning so queue takes dominant space, bands are compact, drill-in fills the remaining viewport when active.
6. **Ship D follow-ups in `renderSignalBand()`.** Remove parser/draftSource/routeOutcome chips, add value truncation with title attribute.
7. **Unbound-only investigation and fix.** Investigate server vs client. Apply minimal fix where the misbehavior lives.
8. **Analytics band (placeholder shell).** Markup, CSS, `computeAnalyticsAggregates()`, `renderAnalyticsBand()`.
9. **Smoke test in dev.** Walk the acceptance criteria. Push and deploy when clean.

---

## Smoke test checklist

After implementation, manually verify on the live dashboard as Lanier:

- Pre-Booking loads with resolution header at top showing correct counts
- Confidence band shows sent and held averages with reasonable values for the 7d window
- `correctHoldPct` shows a real value or `—` (verify it's not fabricated by inspecting one held-then-replied inquiry)
- Confidence window switches between 24h/7d/30d without fetching, persists across reload
- Knowledge-gap band shows property-rolled groups (or "All clear" if none)
- "Review" button in a knowledge-gap group filters the queue correctly
- Queue depth control offers 5/10/25/all and defaults to 25
- Truncation indicator ("Showing 25 of 47") appears correctly
- Selecting a queue row opens the drill-in three-pane workspace
- Signal band in drill-in shows confidence, warnings, policy flags — NOT parser, draft source, route outcome
- Long warning text in signal band is truncated with full text on hover
- Fresh load (after clearing localStorage) does not show unbound-only filter
- Approve / Edit / Regenerate / Reject all work as before
- Mid-edit drafts survive a 30s poll refresh
- Analytics band below the queue shows topics, properties, knowledge-gap recurrence
- Analytics band shows the honest "conversion correlation pending attribution" copy
- Today, Analytics, In-Stay, all other views unaffected
- No console errors anywhere

---

## What ships after this

**Phase 1 backend foundation continues in parallel.** The audit identified four jobs (attribution, signal normalization, capability enforcement, no rebuild). Codex executes these as separate backend ships, mostly independent of this UI ship.

**Future Pre-Booking ships:**
- **Auto-mode toggle.** When operator's confidence in the AI is earned, a toggle flips Pre-Booking into auto-send mode. Default queue depth drops to 5. Bands take more visual weight. Same surface, different defaults.
- **Additional exception groups.** Unbound inquiries, low-confidence held drafts, policy-flagged inquiries each become their own compact group as the data warrants.
- **Confidence band expansion.** Once Phase 1 attribution and signal normalization land, the confidence band gets the histogram, the trend-vs-prior comparison, and conversion-correlation overlays.
- **Analytics band fill-out.** Conversion-correlated topics, recurring questions impact scoring, network benchmarks (when network intelligence layer is online).

**Other lifecycle surfaces (In-Stay, Pre-Arrival, Post-Stay) get the same operational shape** in their own ships, each scoped to that phase's signals.

---

## Notes for the executor

- The ship is intentionally **compact-first** for bands. Resist the urge to add histograms, trend arrows, or dense data displays until they earn the space. The confidence band is two numbers in this ship. The exception group is one group. Discipline matters here.
- `correctHoldPct` calculation: if you can't compute it cleanly from current data, return `null` and show `—` with a tooltip. **Do not fabricate.** The whole point of the band is honest signal.
- The depth control is a small select element, not a slider or a fancy interaction. Keep it boring.
- The "Review" button on knowledge-gap rows reuses the existing property filter mechanism (`state.property = ...; loadMessages({force: true})`). No new filter machinery.
- The Cormorant Garamond serif is fine for the large stat numbers in the confidence band if it reads well at the compact size. If it doesn't, use Inter at heavy weight instead — typography polish is Ship K territory anyway.
- The bands re-render on every poll. Pure client-side derivations over `state.items`. No new API calls. If the existing 200-item feed isn't enough to compute confidence over a 30-day window, surface that honestly in the empty state rather than fetching more.
- Do not introduce new enforcement-naive code paths. Read-only client-side computation is fine; do not add new action endpoints, do not modify existing action endpoints.
- The three Ship D follow-ups are folded into this ship; they should not be separate commits. One commit, one ship, one deploy.
- The analytics band's `"conversion correlation pending attribution"` copy is intentional and important. It signals to the operator (and to us when we look at it later) that this band is honest about what it doesn't yet know.

---

*End of Ship E brief.*
