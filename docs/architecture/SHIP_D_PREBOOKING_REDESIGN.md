# Ship D — Pre-Booking Redesigned In Place

**Status:** Brief for Codex execution
**Author:** Claude, written under Hunter's direction
**Date:** May 2026
**Parent docs:**
- `docs/architecture/COMMAND_MODULE_PROPOSAL.md`
- `docs/architecture/SHIP_A_FOUNDATIONS.md`
- `docs/architecture/SHIP_B_SHELL_AND_NAV.md`
- `docs/architecture/SHIP_C_TODAY_WORKLIST.md`

---

## What this ship is

Restructure the Pre-Booking surface to match the new shell's posture — three panes, the detail rail finally consumed, AI signal indicators visible at a glance, and property/booking context anchored next to the draft instead of buried inside it.

Pre-Booking is the surface that makes Lanier money. It's where inbound inquiries turn into bookings, and where the AI's draft quality is judged in real operator time. Today the surface works (Melanie's inquiry is visible and the action buttons function), but it's the old dark queue-and-detail layout nested under the new light shell. Ship D is where that visual and operational mismatch ends.

The three-pane layout, left to right:

1. **Queue pane** — the inquiry list, filtered and sortable. Visual hierarchy emphasizes priority signals (age, confidence, unbound state, OTA source) instead of a uniform row treatment.
2. **Draft review pane** — the selected inquiry's guest message and AI draft, with edit/approve/regenerate/reject. AI signal indicators (confidence, draft source, parser used, route outcome, fallback reasons, policy flags) are surfaced in a compact band above the draft, not buried in a collapsible "Show analysis" section.
3. **Context detail rail** — the Ship B detail panel scaffold, finally consumed. Holds property profile, active/upcoming bookings, prior operator commitments, vendor intelligence for the matched property, and any open work orders attached to the property. Opens when an inquiry is selected, closes when the queue is empty or the operator dismisses it.

The detail rail is what makes this ship feel genuinely different. Today an operator reviewing a draft has to context-switch (open the property elsewhere, check vendor coverage in another tab) or trust the draft blind. With the rail consumed, all the context the AI considered is right there next to the draft, in operator-readable form. That's the difference between "review a draft" and "review a decision."

---

## What this ship is not

- Not a redesign of any other lifecycle view. In-Stay, Pre-Arrival, Post-Stay all stay as Ship B/C left them.
- Not a backend rewrite. The inquiry feed, work order service, vendor intelligence service, and booking context adapter all already exist and are already wired. Ship D composes them, doesn't change them.
- Not real-time websocket pre-booking. The existing 30s poll cadence is preserved.
- Not multi-tenant scope-aware. Single tenant, dormant scope pill, same as Ships B and C.
- Not new APIs. Every data point in the new layout comes from endpoints that already return what we need. Possible exception: one new field on the existing inquiry feed if the AI signal indicators need a value the adapter doesn't currently surface — flagged in deliverable 0 if so.
- Not a real command palette (Ship E still owns that).
- Not retirement of the legacy `oyvoda-v10.jsx` queue-v2 preview — that happens in Ship L, after Ship D proves the canonical surface carries the design weight.

**Explicit scope guard:** Under no circumstances does Ship D:
- Modify `OperationalInsightEngine`, `OperatorWorkOrderService`, `VendorIntelligenceService`, or the booking context adapter
- Modify any other lifecycle view
- Add new database tables, migrations, or columns
- Add new LLM calls
- Change the action-button contract (approve / edit / reject / regenerate) — those POST endpoints stay exactly as they are
- Touch the OTA parser pipeline (the three FIX briefs at `docs/architecture/FIX_1_*`, `FIX_2_*`, `FIX_3_*` remain captured-but-secondary, not in scope here)

If a change to a service or API seems required, stop. That is either a later ship or a captured refinement, not Ship D.

---

## Verified repo reality this brief is anchored to

These services and endpoints already exist and are used by the current Pre-Booking surface:

- `app/static/dashboard/js/sections/messages.js` — the live Pre-Booking module. Substantial existing state machine (preferences, polling, work views, scope filters, mode toggle). Detail pane is currently rendered inline within the same view.
- `/app/api/messages?stage=pre_booking&...` — inquiry feed with rich fields including `parser_source`, `route_outcome`, `confidence`, `confidence_source`, `confidence_label`, `confidence_note`, `policy_flags`, `policy_warnings`, `property_binding_candidates`, `prior_operator_commitments`. The adapter `normalizeMessageFeed` in `adapters.js` already exposes these as camelCase fields on each item.
- `app/services/operator/work_order_service.py` — `OperatorWorkOrderService`. Already returns work orders attached to a property via session/work-order joins.
- `app/services/operator/vendor_intelligence_service.py` — vendor coverage and intelligence per property.
- `app/services/messaging/booking_context_adapters.py` — booking context lookup, returns property/booking shape per inquiry.
- `app/static/dashboard/index.html` — already contains the `<aside class="detail-panel" id="detail-panel">` scaffold from Ship B with `#detail-panel-header`, `#detail-panel-title`, `#detail-panel-body`, and the `body[data-detail-open="true"]` toggle. The `openDetailPanel(title, html)` and `closeDetailPanel()` functions in `shell.js` are real and exposed on `window`.

Action POST endpoints (`/app/api/inquiries/{id}/approve`, `/edit`, `/reject`, `/regenerate`) are unchanged. Ship D's job is structural/visual, not behavioral.

---

## Deliverables, file by file

### 0. Optional one-field backend extension (only if needed)

Audit the AI signal indicators planned for the draft review band against what `normalizeMessageFeed` already exposes. The expected indicators are:

- Confidence (value + label + note) — already in adapter as `confidence`, `confidenceLabel`, `confidenceNote`
- Draft source — already exposed as `draftSource`
- Parser used — already exposed as `parserSource`
- Route outcome — already exposed as `routeOutcome`
- Fallback reason — already exposed as `fallbackReason`
- Policy flags / warnings — already exposed as `policyFlags`, `policyWarnings`
- Property match type — already exposed as `propertyMatchType`
- Property binding candidates (for unbound inquiries) — already exposed as `propertyBindingCandidates`
- Prior operator commitments — already exposed as `priorOperatorCommitments`

If all needed signals are already in the adapter, deliverable 0 is a no-op and Ship D is frontend-only. If during implementation Codex finds a signal that genuinely isn't surfaced and would meaningfully improve operator judgment, add it the same way the inbox-status reconciliation patch added fields — one targeted line, no new endpoints, no migrations. Flag any such addition in the PR.

Default assumption: deliverable 0 is a no-op.

---

### 1. `app/static/dashboard/index.html` — Pre-Booking view restructure

The current `<div id="view-prebooking">` markup uses `pb-inbox-header` and `pb-review-shell` (queue + detail in a two-pane layout, with header/filter bar above). Restructure to three panes.

The new top-level structure:

```html
<div id="view-prebooking" class="pb-shell" style="display:none">
  <!-- compact header with title, counters, and primary filter row -->
  <div class="pb-shell-header">
    <div class="pb-shell-title-row">
      <div class="pb-shell-title-block">
        <div class="page-eyebrow">Guest Messaging</div>
        <div class="page-title">Pre-Booking</div>
      </div>
      <div class="pb-shell-counters" aria-label="Queue summary">
        <span class="pb-counter"><strong id="pb-metric-pending">—</strong><span>Pending</span></span>
        <span class="pb-counter"><strong id="pb-metric-drafts">—</strong><span>Ready</span></span>
        <span class="pb-counter"><strong id="pb-metric-held">—</strong><span>Held</span></span>
        <button class="pb-counter pb-counter-action" id="pb-metric-unbound-chip" type="button">
          <strong id="pb-metric-unbound">—</strong><span>Unbound</span>
        </button>
      </div>
    </div>
    <div class="pb-shell-filter-row">
      <div class="tab-bar pb-status-tabs" id="pb-status-tabs">
        <button class="tab active" data-pb-status="pending">Pending</button>
        <button class="tab" data-pb-status="all">All</button>
        <button class="tab" data-pb-status="closed">Closed</button>
      </div>
      <div class="pb-filter-spacer"></div>
      <div class="pb-filter-control">
        <span class="pb-filter-label">Property</span>
        <select class="form-select" id="pb-property-filter">
          <option value="">All properties</option>
        </select>
      </div>
    </div>
  </div>

  <!-- three-pane work area: queue / draft review / context rail -->
  <div class="pb-workshop">
    <div class="pb-queue-pane" id="pb-queue-pane">
      <div class="empty" style="padding:48px 20px">
        <div class="empty-title">Loading messages...</div>
      </div>
    </div>
    <div class="pb-draft-pane" id="pb-draft-pane">
      <div class="pb-draft-empty">
        <div class="empty">
          <div class="empty-title">No draft selected</div>
          <div class="empty-sub">Select an inquiry on the left to review the guest message, the AI draft, and the context the AI used.</div>
        </div>
      </div>
    </div>
    <aside class="pb-context-rail" id="pb-context-rail" aria-hidden="true">
      <div class="pb-context-empty">
        <div class="empty-state">
          <div class="empty-state-title">No context yet</div>
          <div class="empty-state-description">Property, bookings, vendor coverage, and work orders for the selected inquiry will appear here.</div>
        </div>
      </div>
    </aside>
  </div>
</div>
```

The context rail (`pb-context-rail`) is a section-scoped consumer of the same visual language as the global detail panel from Ship B, but anchored inside the Pre-Booking view rather than sliding in from the global right edge. **This is intentional.** The global `#detail-panel` is reserved for cross-section context (e.g. when a Today insight click opens an inquiry detail without leaving Today). The section-scoped rail is the always-present third pane while operating Pre-Booking. Two different jobs, two different containers.

Both use the same CSS primitives (header/title/body, close button styling, empty-state copy patterns) so they feel identical. The shared primitives go in `dashboard.css` under the existing detail-panel classes.

### 2. `app/static/dashboard/styles/dashboard.css` — three-pane layout

Add styles for the new Pre-Booking shell. Specifically:

- `.pb-shell` — flex column, fills available height, no padding (panes have their own)
- `.pb-shell-header` — compact header band with title/counters and filter row
- `.pb-shell-counters` — flex row of counter chips (Pending / Ready / Held / Unbound)
- `.pb-counter` — small chip with bold number + thin label, JetBrains Mono for numbers
- `.pb-counter-action` — clickable variant (Unbound chip), amber accent when count > 0
- `.pb-workshop` — three-column grid: `minmax(360px, 1fr) minmax(520px, 1.8fr) minmax(340px, 1fr)` with right column collapsible
- `.pb-queue-pane` — virtualization-friendly scroll container, queue rows
- `.pb-draft-pane` — middle pane, scrolls independently
- `.pb-context-rail` — right rail, scrolls independently, hidden on narrow viewports under a certain breakpoint
- Responsive: under 1280px viewport, the context rail collapses to an overlay that the operator can toggle via a "Context" button in the draft pane header. Under 960px, the queue pane and draft pane stack vertically (rare for operator desks but defensive).

Reuse existing `.btn`, `.badge`, `.empty-state`, `.tab-bar`, `.form-select` primitives from earlier ships. Do not introduce new color tokens.

Migrate the existing `.pb-inbox-*`, `.pb-review-*`, `.pb-mini-count` classes out — they were the old two-pane system. Where the old class is structurally identical to a new one, keep the old class name as an alias if any test or external reference depends on it, but new markup uses the new names.

### 3. `app/static/dashboard/js/sections/messages.js` — section refactor

The existing module has substantial state and behavior; do not throw it away. Restructure the rendering layer to populate the three new panes. State machine and polling logic stay intact.

Specifically:

**Queue pane (`renderQueue`)**:
- Render inquiry rows with stronger visual hierarchy:
  - Top line: guest name + property (or "Unbound" amber chip if no property bound)
  - Second line: short message preview
  - Third line (metadata row): age, confidence chip (color-coded), parser source as small mono-font tag
  - Right edge: status pill (Pending / Ready / Held / Closed)
- The active row gets a left border accent and slightly elevated background (use the existing `--brand-600` token at low opacity)
- Click on a row sets `state.activeId` and triggers `renderDraftPane()` + `renderContextRail()`

**Draft review pane (`renderDraftPane`)**:
- Header band: guest name, property binding state, channel (Airbnb / VRBO / direct), age
- AI signal indicators band — a compact horizontal strip with chips for each surfaced signal:
  - Confidence: `<chip class="conf-{level}">{value}%</chip>` where level is high/medium/low
  - Draft source: e.g. "LLM composer" or "template fallback"
  - Parser used: e.g. "vrbo deterministic" or "airbnb llm"
  - Route outcome: e.g. "auto_draft" or "kb_gap_held"
  - Fallback reason: only if present
  - Policy flags: each as its own pill, amber for warnings, red for blocking
- Guest message body — full text, monospace-tolerant rendering for OTA-style structured bodies
- AI draft — editable in place when edit mode is active; otherwise read-only
- Action row: Approve / Edit / Regenerate / Reject buttons. Behavior unchanged from current implementation.
- Note: the existing "Show analysis" expandable goes away. Its information is now permanently visible in the signal indicators band. Verify nothing in `messages.js` depends on a `show-analysis` toggle being clickable.

**Context detail rail (`renderContextRail`)**:
- Four sections, stacked vertically, each collapsible (default expanded):
  1. **Property** — name, address line, bedrooms/baths, code. Pulled from `propertyName`, `propertyId`, and the property metadata in the inquiry feed item.
  2. **Bookings** — active booking (if any), next booking, recent past bookings. Pulled from booking context fields already on the inquiry. If no booking context is available, show "No booking context for this inquiry — typical for first-touch inquiries."
  3. **Vendor coverage** — vendor categories with vendor counts for this property. Pull from `vendor_intelligence_service` via a single GET if not already in the inquiry feed payload (probable — verify in implementation).
  4. **Open work orders** — any active work orders attached to this property. Pull from `work_order_service` if not already in the inquiry feed payload. Show count + brief list (status, summary) with a "View all" link routing to Escalations/work-order view.
- If the inquiry is unbound, the rail shows the property binding candidates section instead of property/bookings — operator can pick a binding from the rail without leaving the section.

**Selection lifecycle**:
- When `state.activeId` is set: rail opens (mobile: slide-over)
- When `state.activeId` is cleared (e.g. inquiry resolved and queue advances): rail closes if queue empty, otherwise auto-advances to next pending inquiry and re-populates rail

**Polling behavior**: keep the existing 30s polling. While the operator is mid-edit on a draft, the queue auto-refresh should NOT reload the active inquiry's draft pane (would clobber the operator's edits). The existing `activeSnapshot` mechanism in state already addresses this — preserve it.

### 4. `app/static/dashboard/js/sections/messages.js` — module rename consideration

The module is named `messages.js` but it only handles Pre-Booking. Other lifecycle phases live in `sessions.js`. The naming is historical. **Do not rename in Ship D.** Renaming touches `main.js` boot order, every import, and the view-changed event handler — risk surface that's not worth taking on while restructuring the section internals. Capture as a Ship L cleanup task (when legacy code retires).

### 5. `app/static/dashboard/js/sections/shell.js` — no changes required

The global detail panel functions (`openDetailPanel`, `closeDetailPanel`) stay as they are. Pre-Booking uses its own section-scoped rail (`pb-context-rail`), not the global panel. Any future cross-section "open inquiry context from elsewhere" flow can still use the global panel without conflict.

---

## Acceptance criteria

Ship D is done when all of the following are true:

1. `/app/dashboard` → Pre-Booking opens in the new three-pane layout.
2. The queue pane shows inquiry rows with the new visual hierarchy (guest+property, preview, metadata row, status pill).
3. Selecting an inquiry populates both the draft review pane and the context detail rail.
4. The draft review pane shows the AI signal indicators band as a permanent compact strip (no "Show analysis" toggle).
5. All four AI signal indicator types render correctly when their underlying data is present (confidence, draft source, parser used, route outcome).
6. Policy flags appear as pills when present.
7. The context detail rail shows Property, Bookings, Vendor coverage, and Open work orders sections.
8. If the inquiry is unbound, the rail shows property binding candidates instead of property/bookings.
9. Action buttons (Approve / Edit / Regenerate / Reject) behave identically to before — same POST endpoints, same outcomes.
10. The 30s poll cadence is preserved; mid-edit drafts are not clobbered by refresh.
11. Melanie Tarbush's previously-unbound inquiry (if still pending in fixture/production data) renders correctly in the unbound state, with binding candidates visible in the rail.
12. Counter chips (Pending / Ready / Held / Unbound) display correct numbers and the Unbound chip is clickable to filter.
13. The Today surface, Analytics, In-Stay, Pre-Arrival stub, Post-Stay stub, and all other views are unaffected.
14. No console errors on Pre-Booking or anywhere else.
15. The Ship B global detail panel scaffold remains intact for future use by other surfaces — `openDetailPanel` and `closeDetailPanel` still work from the JS console.

---

## Suggested implementation order

1. Add the new CSS for `.pb-shell`, `.pb-workshop`, `.pb-context-rail`, etc. without touching markup yet. Verify the styles don't leak to other views.
2. Replace the `<div id="view-prebooking">` markup with the new three-pane structure. Verify the section still renders (mostly empty) without JS changes.
3. Refactor `messages.js` rendering layer to populate the new pane IDs. Start with the queue pane — get rows rendering.
4. Add the draft review pane rendering, including the AI signal indicators band.
5. Add the context detail rail rendering, including all four sections.
6. Test selection lifecycle: click row → both panes populate → resolve inquiry → queue advances and rail re-populates.
7. Smoke test action buttons (approve / edit / regenerate / reject) to confirm behavior preserved.
8. Smoke test polling: leave Pre-Booking open for 30+ seconds with a draft in edit mode, verify edits aren't clobbered.
9. Smoke test unbound inquiry rendering with Melanie's fixture if still available; otherwise verify against any pending unbound row.
10. Smoke test all other views to confirm no regression.

---

## Smoke test checklist

After implementation, manually check:

- Pre-Booking loads in the new three-pane layout
- Counter chips show correct numbers and Unbound chip is clickable
- Status tabs (Pending / All / Closed) filter the queue
- Property filter narrows the queue correctly
- Selecting a row populates both draft and rail
- AI signal indicators render permanently above the draft (not behind a toggle)
- Confidence chip is color-coded
- Policy flag pills appear when present
- Approve / Edit / Regenerate / Reject all work as before
- Context rail shows property, bookings, vendor coverage, open work orders
- Unbound inquiry shows binding candidates in the rail
- Mid-edit drafts survive a 30s poll refresh
- The global detail panel from Ship B still opens via `openDetailPanel(...)` in the console
- Today, Analytics, In-Stay, all other views unaffected
- No console errors

---

## What ships next

**Ship E — real command palette.** With Pre-Booking redesigned, the operator's workflow patterns are clearer and the command palette can be designed around them rather than against an unknown UI. Ship E gives ⌘K real search across inquiries, properties, vendors, knowledge entries, and actions.

After Ship E, the surface sequence is F (Properties), G (In-Stay), H (Knowledge + Voice & Persona), I (Vendors), J (Pre-Arrival + Post-Stay), K (visual polish), L (legacy retirement), M (multi-tenant scope). Ship D is the load-bearing one because it proves the redesigned product can carry the most-used surface in the dashboard.

---

## Notes for the executor

- The detail panel scaffold from Ship B is shared CSS primitives, not a shared DOM container. Pre-Booking uses its own section-scoped rail (`#pb-context-rail`). Future surfaces can use either pattern depending on whether context is section-internal or cross-section.
- Do not call new APIs unless deliverable 0 finds a genuinely missing signal. If you find yourself wanting a new endpoint, stop and write down what's missing — that's a captured refinement, not a Ship D deliverable.
- The existing `messages.js` module is significant code with real production state. Preserve the state machine, polling, preference persistence, and active-snapshot logic. The refactor is rendering-layer only.
- The "Show analysis" toggle going away is a real behavior change — verify no event listener or test depends on it before removing.
- Counter chips use JetBrains Mono for numbers (existing pattern) and Inter for labels. Don't introduce Cormorant Garamond in this surface; serif values are reserved for the Today lifecycle strip and Analytics display values.
- The context rail's four sections (Property / Bookings / Vendor coverage / Work orders) should each collapse cleanly with a chevron. Default expanded; operator preference for collapsed state can be persisted in `localStorage` under the existing `oyvoda.dashboard.prebooking` namespace.
- This is the surface Lanier touches the most. After deploy, watch for any latency change in the inquiry-feed render path — three panes rendering instead of two could cost a few hundred milliseconds on initial paint. If it does, the queue pane should be the first to render (it's what she's looking at first) and the rail can come in on a tiny delay.

---

*End of Ship D brief.*
