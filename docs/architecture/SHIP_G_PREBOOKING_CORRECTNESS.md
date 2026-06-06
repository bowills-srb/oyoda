# Ship G — Pre-Booking Single-Pane Email-Style Queue

**Status:** Ship brief for Codex execution
**Type:** Real ship. Replaces SHIP_G_PREBOOKING_CORRECTNESS.md (which is now invalid based on actual repo state).
**Author:** Claude, written under Hunter's direction
**Date:** May 2026

---

## Why this brief exists

After Ship F deployed, I wrote briefs assuming patterns that didn't actually exist in the repo. Specifically: I kept describing a "popout context rail" and "popout inquiry detail" as if they had been built. **They were not.** Reading `index.html` directly confirms the state: `view-prebooking` still contains a three-pane grid (`pb-workshop`) with `msg-list-pane`, `msg-detail-pane`, and `pb-context-rail` all rendered as permanent siblings. Selecting an inquiry doesn't open a popout — it populates the persistent right-side panes.

That's the gap that has been making every Pre-Booking ship feel like it's moving backwards. The wiring I kept patching wasn't the wiring that exists.

This brief is written from the actual repo state.

---

## The actual current state of Pre-Booking

From `app/static/dashboard/index.html`:

```html
<div id="view-prebooking" class="pb-shell">
  <div class="pb-shell-header">
    <!-- title block, counters, status tabs, property filter,
         resolution header, confidence band -->
  </div>
  <div class="pb-workshop">
    <div class="pb-queue-pane" id="msg-list-pane">...</div>      <!-- queue -->
    <div class="pb-draft-pane" id="msg-detail-pane">...</div>   <!-- AI draft / detail -->
    <aside class="pb-context-rail" id="pb-context-rail">...</aside>  <!-- property/booking/vendors -->
  </div>
  <section class="pb-band-analytics">...</section>
  <div class="pb-status-footer">...</div>
</div>
```

Three permanent panes. The right two panes fill on row select. That's why selecting an unbound inquiry occupies persistent right-side space. That's why the operator sees the AI draft visually first when reviewing — the draft pane is the middle column, dominant by position.

The Ship F brief said "context rail collapses to icon-strip with popout panels." That landed only as a hover-collapse via CSS, not as a structural change. The pane is still there.

---

## Lock the model first

**Pre-Booking is single-pane. The queue is the only persistent surface.**

- No `pb-draft-pane` as a permanent right-side column.
- No `pb-context-rail` as a permanent right-side aside.
- Three-pane grid → one-pane queue.
- Detail and context become **popouts anchored to the row**, opened by an info button (`?`) on the row. Closed by clicking outside, Esc, or clicking the button again.
- Every row is an email-shaped item — guest message text on top, AI draft below it, send/edit buttons next to the draft.

No exceptions. No "but for unbound." No "but the context is useful."

---

## Deliverables

### 1. Delete the three-pane grid

**File:** `app/static/dashboard/index.html`

In `view-prebooking`, the `<div class="pb-workshop">` block currently contains three children. Replace with a single queue-pane container:

```html
<div class="pb-workshop">
  <div class="pb-queue-pane" id="msg-list-pane">
    <!-- queue rows render here, that's all -->
  </div>
</div>
```

The `msg-detail-pane` element is deleted from `index.html`. The `pb-context-rail` element is deleted from `index.html`. The `.pb-workshop` CSS in `dashboard.css` becomes a single-column container instead of a three-column grid.

**File:** `app/static/dashboard/js/sections/messages.js`

- Delete `renderDetail()` function entirely.
- Delete `renderContextRail()` function entirely.
- Delete `renderOpsPane()` function entirely.
- Delete `renderPropertySection`, `renderBookingsSection`, `renderVendorCoverageSection`, `renderWorkOrdersSection`, `renderBindingCandidatesSection` — these all rendered context-rail content that no longer exists.
- Delete `ensureBookingContext()` if it's only consumed by the deleted rail.
- In `loadMessages()`, remove the calls to `renderDetail()`, `renderOpsPane()`, `renderContextRail()`.

**File:** `app/static/dashboard/styles/dashboard.css`

Delete all CSS rules for `.pb-draft-pane`, `.pb-context-rail`, `.pb-context-empty`, `.pb-context-head`, `.pb-context-body`, `.pb-context-section`, `.pb-context-card`, `.pb-context-stack`, `.pb-context-kicker`, `.pb-context-heading`, `.pb-context-emptycopy`, `.pb-context-copy`, `.pb-context-title`, `.pb-context-sub`, `.pb-context-section-label`.

The `.pb-workshop` rule changes from a three-column grid to a single flex/block container.

### 2. Email-shaped queue row

**File:** `app/static/dashboard/js/sections/messages.js`, in `renderList()` row template.

Row structure, top to bottom, each row:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Melanie Tarbush · Beach Habitat 12 · 14m            94%       [?]       │
│                                                                          │
│  Is the lower bathroom part of the unit, or is it shared?               │
│                                                                          │
│  Draft  Yes, the lower bathroom is part of the unit. Both bathrooms…    │
│         are exclusive to your stay.            [Send]  [Edit]           │
└─────────────────────────────────────────────────────────────────────────┘
```

- **Top metadata strip:** guest name · property name (or `Unbound`) · age, with confidence percentage and a `?` info button right-aligned. Small font (~11px), dim color. Nothing else on this line.
- **Guest message** in normal email-body font (~13-14px), regular weight, primary text color. Reads like an email. No `Q:` prefix. Up to 3 lines, ellipsis if longer. **This is the first thing the operator reads after the metadata.**
- **AI draft block** below the guest message: the word **Draft** as a small dim label on the left (like an email gutter label), the draft text to its right in **slightly bolder weight** than the guest message. Up to 3 lines, ellipsis if longer.
- **Send and Edit buttons** sit immediately to the right of the draft text, on the same horizontal axis as the draft. Not at the far edge of the row, not on a separate row. Inline with the draft.
- **No status chip on the row.** No channel pill. No parser pill. No route pill. No "revenue sensitive" badge. No "knowledge gap" badge on the row (knowledge-gap items are routed out — see Deliverable 4). Only the confidence number in the metadata strip.

Row separators are thin, low-contrast dividers. Hover state is subtle. Selected/active row gets a slightly different background (very subtle) to indicate it's been clicked-into, but selecting no longer opens a side pane — it opens the popout (Deliverable 3).

Truncation rules:
- Guest message: max 3 lines, then ellipsis. Full message in the `?` popout.
- AI draft: max 3 lines, then ellipsis. Clicking Edit opens the drill-in editor with full draft.

### 3. The `?` popout — the only detail surface

**Files:** `app/static/dashboard/js/sections/messages.js`, `index.html`, `dashboard.css`.

Click the `?` button on a row → a popout opens anchored to the row, ~480-560px wide. It shows:

- **Full guest message text** (untruncated, scrollable if very long)
- **Channel** (Airbnb / Vrbo / Direct / etc.)
- **Listing ID, requested check-in / check-out, guest count** — if available
- **Property identity:** name, code, address — if bound
- **Binding candidates** — if unbound, render as a clear list
- **Confidence** with label
- **Policy warnings** if any, compact one-per-line list (no chip explosion)
- **Prior thread context** if available — collapsible
- **Resolved actions** at the bottom: large `Send` and `Edit` buttons (mirroring the row buttons but at popout scale, in case the operator wants to act from inside the popout)

What the popout does NOT show:
- Parser source, draft source, route outcome (these stay deleted from operator UI)
- Vendor coverage (that lived in the context rail; if it's needed, it lives in Properties)
- Work orders (same — Pre-Booking is not the work-order surface)
- "Revenue sensitive" badge

Close behaviors:
- Click outside the popout
- Press Esc
- Click the `?` button again
- The popout closes automatically when the operator clicks Send or Edit on a row

Positioning: anchor to the `?` button, prefer right-aligned. If it would overflow the viewport, flip to left of the row. If it would overflow vertically, scroll within the popout, never push the page.

### 4. Knowledge-gap inquiries route to the Knowledge surface

**Files:** `app/static/dashboard/js/sections/messages.js`, `app/static/dashboard/js/sections/knowledge.js`, `app/static/dashboard/js/sections/shell.js`, `index.html`.

- In `filteredItems()`, filter out items where `isKnowledgeGap(item) === true`. They do not appear in either Action queue or Resolved.
- The Knowledge surface (`view-knowledge`) gets a new section at the top: **"Inquiries waiting on knowledge."** Each row shows: guest name, property, the missing-knowledge topic (extracted from `policyWarnings`), the guest's question, age. A single action button: **"Resolve in KB"** — opens the existing `add-kb-modal` pre-filled with the question.
- The Knowledge sidebar nav item shows a **red dot** when this count > 0. The existing `nb-gaps-kb` badge element can be repurposed for this count.
- Remove the Ship E knowledge-gap exception band from `view-prebooking` (the markup wasn't actually built per my read of `index.html`, but verify and confirm absence).

When the operator resolves a gap via the modal, the existing KB-add flow runs. The next inquiry-feed poll will re-evaluate the held inquiry; if its gap is now filled, it appears in the Pre-Booking action queue normally. **No new server-side logic required** for this ship — the existing draft regeneration / next-poll behavior handles it.

### 5. Signal cleanup

Verify and remove from operator-visible UI:
- **`buildDraftMeta()`** in `messages.js` — delete entirely. It rendered draft path / parser / route outcome as a "Message Analysis" block. No surface still calls it after the drill-in is deleted, but search and confirm.
- **`renderSignalBand()`** in `messages.js` — delete entirely. The signal band was attached to the drill-in detail pane, which is now deleted.
- **`isRevenueSensitive()` predicate** stays in code but no UI consumes it. Captured for future "tighten or remove" review.
- **`pb-draft-asks` block** in the drill-in — gone with the drill-in.

The drill-in detail pane is no longer the surface where the operator works. The row is. The popout is. There is no third surface to put signals on.

### 6. Edit drill-in becomes a row-anchored editor

Clicking **Edit** on a row needs to open the draft for editing without re-introducing the deleted detail pane. The cleanest path:

- Edit replaces the row's draft block with a textarea (same content, same row width), plus **Save** and **Cancel** buttons inline.
- Saving sends the edited text via the existing `editInquiry()` flow.
- Cancel restores the row to its read-only draft state.

This keeps everything on the row. No modal, no side pane, no shell change.

For inquiries the operator needs to inspect more deeply (full thread, prior context), the `?` popout already has that — they don't need to enter Edit to read.

### 7. Unbound-only default-on-load — investigate then fix

Still unresolved after three attempts.

**Before any fix is written**, Codex runs the diagnostic:

1. Clear localStorage for the dashboard origin.
2. Hard refresh Pre-Booking. Open DevTools Network tab.
3. Capture the first `/app/api/messages` request — full URL, especially the query string.
4. Capture the response body's `unbound_only` field value.
5. Inspect `state.unboundOnly` after the load resolves (window-expose temporarily if needed).
6. Inspect the "SHOWING UNBOUND ONLY" indicator's DOM binding.

Fill in this section of the brief before patching:

```
Request URL: [paste]
Response unbound_only: [value]
state.unboundOnly after load: [value]
Indicator element: [DOM selector + what it reads from]
Root cause: [one sentence]
Fix surface: [file + line]
```

Then apply the fix. Likely one line.

### 8. Unbound message contrast

If readable contrast was a problem in the deleted context rail's binding-candidates rendering, it goes away with the rail itself. If the contrast issue lives elsewhere (e.g., in `pb-queue-row-preview` or in the new email-style row), fix the CSS color to match the primary text token. Two-minute fix.

---

## What stays

- Resolution-counts header (already shipped, works)
- Confidence health band (already shipped, works)
- Pre-Booking analytics band below the fold (already shipped, works)
- Action queue / Resolved tabs (already shipped, works)
- Send/Edit endpoint wiring (preserve, just move to row-anchored UI)
- 30s polling, `activeSnapshot` clobber protection (preserve)
- Left nav hover-expand (already shipped via Ship F)
- Reject removed (already shipped, stays gone)
- Regenerate removed from row (only exists in drill-in, which is now deleted — so Regenerate disappears entirely from operator UI for this ship; reintroduce as a popout action later if needed)

---

## Acceptance criteria

1. `view-prebooking` markup contains only `pb-queue-pane` inside `pb-workshop`. No `msg-detail-pane`, no `pb-context-rail` in the markup.
2. Each queue row shows: metadata strip, guest message, "Draft" label + AI draft, Send/Edit buttons inline with the draft. In that visual order.
3. No status chip, no channel pill, no parser pill, no "revenue sensitive" badge anywhere on the row.
4. Confidence percentage is visible in the metadata strip. Nothing else above the guest message.
5. Selecting a row does NOT open any side pane. Clicking `?` opens a popout anchored to the row.
6. The `?` popout shows full guest message, channel, listing/dates, binding candidates if unbound, confidence, policy warnings if any, prior thread context if any. NOT parser/draft-source/route-outcome. NOT vendor coverage. NOT work orders.
7. Edit on a row inlines a textarea on the same row. Save / Cancel inline. No side pane appears.
8. Knowledge-gap inquiries do NOT appear in Pre-Booking action queue or Resolved.
9. Knowledge surface shows "Inquiries waiting on knowledge" with question/property/topic and "Resolve in KB" action.
10. Knowledge nav item shows red dot when gap inquiries exist.
11. Fresh load (cleared localStorage, hard refresh) shows all pending inquiries, NOT unbound-only. Investigation findings captured in this brief before the fix.
12. `buildDraftMeta()` and `renderSignalBand()` deleted from `messages.js`. No imports of them remain.
13. Polling, activeSnapshot protection, action endpoint wiring all still work.
14. Today, Analytics, In-Stay, and other views unaffected (except Knowledge gets the new section).
15. No console errors.

---

## Implementation order

1. **Unbound-only investigation first.** Fill in findings.
2. **Delete the three-pane grid markup.** Just remove `msg-detail-pane` and `pb-context-rail` from `index.html` and the CSS. Verify Pre-Booking still loads (empty middle space is fine for now).
3. **Email-shaped row template.** Restructure `renderList()` row HTML. Get the visual order right before adding the popout.
4. **The `?` popout.** Single render function, anchored positioning.
5. **Inline edit on rows.** Replace draft block with textarea + Save/Cancel.
6. **Knowledge-gap routing.** Filter from Pre-Booking, add to Knowledge surface with `Resolve in KB` button, add nav red-dot.
7. **Signal cleanup.** Delete `buildDraftMeta`, `renderSignalBand`, and all deleted render functions from messages.js. Search the codebase for any remaining callers.
8. **Apply the unbound-only fix** at the cause identified in step 1.
9. **Contrast verify.** If the rail being deleted didn't fix it, find the offending rule.
10. **Smoke locally.** Push.

---

## Addendum — verified-from-file refinements (added May 19, 2026)

Four observations from a direct re-read of `index.html` that sharpen the deliverables. None change structure or order; they tighten what to check and what to bump.

1. **CSS cache-bust must advance past `g`.** The `dashboard.css` link in `index.html` is already on `?v=2026-05-19-g`. Any partial CSS that landed earlier today under that bust is already cached on clients. When Codex commits Ship G's CSS deletions, bump to `?v=2026-05-19-h` (or higher) so the structural deletions actually reach clients. Applies to Deliverable 1. Also bump `messages.js` cache-bust in `index.html` when the render-function deletions land.

2. **The unbound-only indicator binds to the `hidden` HTML attribute.** In `index.html`, `<div class="pb-filter-indicator" id="msg-filter-indicator" hidden>` and `<button id="msg-filter-clear">`. The indicator is shown/hidden by toggling the `hidden` attribute, not by adding/removing a class. Deliverable 7's investigation checklist gets one additional line:

   ```
   Indicator element: #msg-filter-indicator (toggled via hidden attribute)
   Toggle call site: [grep messages.js for hidden attribute writes on msg-filter-indicator]
   ```

   This is the surface where the initial `true` state gets set on fresh load. Check the toggle call site in `loadMessages()` and any boot path before patching.

3. **Knowledge view markup is already structurally friendly.** `view-knowledge` in `index.html` already has the Entries/Gaps tab bar with `#kb-entries-count` and `#kb-gaps-count` count chips, plus the `#kb-gaps-list` and `#kb-entries-list` containers. The "Inquiries waiting on knowledge" section from Deliverable 4 slots in **above** the existing `<div class="page-header">`'s sibling content — specifically, as a new section `<div id="kb-inquiries-waiting">` between `view-knowledge`'s `.page-header` and the `#kb-entries-section` block. Reuse the existing tab/badge styling rather than introducing a new visual language.

4. **`nb-gaps-kb` sidebar badge is in place.** Confirmed at the Knowledge Base sidebar nav item: `<span class="nav-badge nb-amber" id="nb-gaps-kb" style="display:none"></span>`. Deliverable 4's "red dot on Knowledge nav when gap inquiries exist" repurposes this element. Either keep `nb-amber` (current class) and update count via `textContent`, or swap to a red-dot variant if you want the visual distinction Hunter described. Hunter said red dot — so add a `nb-red-dot` modifier class and use that.

---

## Notes for the executor

- This ship is structurally simpler than F. It deletes more than it adds. The remaining surface is: queue rows + popout + inline edit + knowledge routing. Don't reintroduce a side pane under any name.
- The goal is high signal density on each row, not minimalism. The row should be packed with the right information in the right order — metadata → guest question → draft + actions. If you find yourself adding a chip or pill or label that doesn't help the operator decide and act, stop.
- The popout is the only detail surface. There is no other detail surface. Resist the urge to build a second one for any case.
- Inline Edit is intentionally lightweight. The textarea replaces the draft block on the row, the row grows slightly, Save commits, Cancel restores. That's it.
- The unbound-only investigation is non-negotiable. Three failed attempts means we look before we patch.
- When in doubt about whether something should still be in the operator UI, the test is: "does this answer a question the operator is actively asking?" If no, it goes.
- Cache-bust every file touched.

---

*End of Ship G brief.*
