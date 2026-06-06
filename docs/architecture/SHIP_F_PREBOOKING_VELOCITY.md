# Ship F — Pre-Booking Velocity, Density, and Resolved Queue

**Status:** Ship brief for Codex execution
**Type:** Real ship, builds on Ship E
**Author:** Claude, written under Hunter's direction with input from Codex
**Date:** May 2026
**Parent docs:**
- `docs/architecture/SHIP_E_PREBOOKING_OPERATIONAL.md`
- `docs/architecture/KNOWN_REFINEMENTS.md`

---

## What this ship is

Ship E got the operational metaphor right but missed on velocity. Experienced operators want to move through the queue fast — read the AI draft, decide, hit send, move on. They don't want to scroll, they don't want to drill into a separate workspace for routine sends, and they don't want details unless they ask for them.

This ship tunes Pre-Booking for that velocity, plus introduces the resolved queue separation, plus addresses the two Ship E follow-up bugs Codex found in the smoke pass.

The shape after this ship:

1. **Left nav auto-collapses to icons** when an operator enters a page. Expands on hover or click. Frees significant horizontal space.
2. **Pre-Booking nav pill bug fixed** (the dark grey active state that doesn't match other nav items).
3. **Context rail collapses to a small icon-button** on the right edge by default. Opens as a popout panel when clicked. Frees significant horizontal space.
4. **Queue rows are dense and operable inline.** Top metadata line is compact (small font). AI draft preview reads as one or two lines of legible text directly on the row. Inquiry message tucked behind an info icon (question mark) popout. Inline Send and Edit buttons on each row.
5. **Action buttons are Send and Edit only.** Reject removed entirely. Regenerate removed from the row; stays accessible in the drill-in as a secondary control with a sane rate limit.
6. **Resolved queue separation.** Sent items leave the action queue. A clear "Resolved" tab shows recent sends so the operator can see what they handled. Follow-ups from guests automatically resurface threads back into the action queue (server-side behavior — verified, not built).
7. **Ship E follow-ups folded in:**
   - Unbound-only default-on-load: investigate server-side now that client-side path is closed, fix where the misbehavior actually lives.
   - Draft source still visible in drill-in: the leak is in `buildDraftMeta()`, not `renderSignalBand()`. Remove the offending rows.

---

## What this ship is not

- Not a backend rewrite. Resolved queue separation uses existing status filtering. Guest follow-up resurfacing is server-side and assumed to work; this ship verifies but doesn't change.
- Not auto-mode. The toggle is still a future ship.
- Not new APIs unless the unbound-only investigation forces one targeted server fix.
- Not new database tables, columns, migrations, or LLM calls.
- Not a redesign of other lifecycle views. In-Stay, Pre-Arrival, Post-Stay all unchanged. The left-nav collapse applies globally to the shell, however, so other views inherit the horizontal-space gain.
- Not a Today redesign. The Today "Patterns worth seeing" HTML noise remains captured in `KNOWN_REFINEMENTS.md` for the insight engine's next pass.
- Not the parser/draft-source-as-warning content fix. If Codex finds that the "draft source: messaging brain" string is coming through `policyWarnings` content from upstream rather than from the signal band itself, fixing the upstream content is a separate small follow-up, captured but not in this ship.

**Explicit scope guard:** Under no circumstances does Ship F:
- Modify any backend service unless the unbound-only investigation conclusively requires one targeted fix
- Add database tables, columns, migrations, or LLM calls
- Touch other lifecycle view rendering (the global left-nav collapse is shell-level CSS/JS, applied uniformly)
- Add server-side mutation endpoints that aren't capability-checked
- Build the auto-mode toggle
- Build a real-time websocket layer

---

## Deliverables

### 1. Left nav hover-to-expand

**Goal:** The left nav stays collapsed to icons by default. It expands only while the operator's cursor is over it. Cursor leaves, it collapses again. Pure hover behavior. No toggles, no pins, no preference persistence.

**Files:** `app/static/dashboard/index.html` (shell), `app/static/dashboard/styles/dashboard.css`, possibly `app/static/dashboard/js/sections/shell.js` only if CSS-only hover doesn't handle it cleanly.

**Behavior:**
- Default state at all times: nav is **collapsed** (~56px wide), showing only icons. Tooltips on hover show the label text via `title` attribute or a CSS tooltip pattern.
- Cursor enters the nav region: nav expands to full width (~220px) showing icons + labels. Use a small delay (~100-150ms) on collapse to prevent flickering when the cursor briefly leaves and re-enters during normal mouse movement.
- Cursor leaves the nav region: nav collapses back to icon-only.
- Click an icon: navigates. Nav stays expanded as long as cursor remains over it; collapses naturally when cursor moves away.
- The collapsed state must show icons with clear visual hierarchy: active item is highlighted, hover state on individual icons is visible, badges (knowledge-gap red dot, etc.) are still visible at small size.
- The expanded state is purely transient — never persisted, never pinned, never preference-saved. Every page load, every session, every operator: starts collapsed.

**Visual fix:** The Pre-Booking active-state pill is currently a darker grey than other active nav items. Fix the CSS so all active nav items share the same active-state treatment, in both collapsed and expanded states.

**Implementation note:** This is almost certainly achievable with CSS `:hover` alone on the nav container, with a `transition` on width. No JS state machine needed. If a JS path is required (e.g., for the small collapse delay), keep it minimal — just a `setTimeout` on `mouseleave` that a `mouseenter` cancels. No preference persistence, no toggle wiring.

### 2. Context rail collapses to a popout button

**Goal:** The Pre-Booking context rail (`#pb-context-rail`) is too wide to live permanently on the right edge. Make it collapsible.

**Files:** `app/static/dashboard/index.html` (Pre-Booking view markup), `app/static/dashboard/styles/dashboard.css`, `app/static/dashboard/js/sections/messages.js`.

**Behavior:**
- Default state: context rail is **collapsed** to a thin vertical strip on the right edge (~40px wide) with a stack of small section icons (Property, Bookings, Vendors, Work Orders).
- Clicking any icon expands the rail to a popout panel (~360-400px wide) showing the section content. The panel sits on top of the queue (overlay), not pushing it.
- Clicking outside the popout, or clicking the open icon again, collapses the rail.
- Esc key also closes the popout.
- The rail shows a small unread-style indicator dot on an icon when that section has notable content (e.g., binding candidates exist for an unbound inquiry, or open work orders).

**Persistence:** The collapsed/expanded state is not persisted across sessions — the rail always opens collapsed on a fresh inquiry select. The popout closes when the operator selects a different inquiry.

### 3. Queue row redesign for velocity

**Goal:** Each queue row is dense enough to scan 25 inquiries on one screen, but readable enough that the operator can decide and act without entering a separate drill-in.

**Files:** `app/static/dashboard/js/sections/messages.js` (`renderList()` row template), `app/static/dashboard/styles/dashboard.css`.

**Row structure:**

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ Lanier ⋅ Beach Habitat 12 ⋅ 14m ⋅ 94%        [Send] [Edit] [?]                  │
│ "Hi! Yes, the pool is heated November through March. Heated to 84°F. Just let..."│
└─────────────────────────────────────────────────────────────────────────────────┘
```

- **Top metadata line** (one line, ~11-12px font, dim color): guest name · property name (or `Unbound`) · age · confidence chip
- **Draft preview** (one to two lines, ~13-14px font, normal weight, primary text color): the AI draft, truncated with ellipsis. **This is what the operator reads to decide.** Up to 2 lines visible; longer drafts are truncated. Click the info icon to expand.
- **Right-aligned inline action buttons:**
  - `Send` (primary, only present when AI draft exists and inquiry is `pending_review` and property is bound)
  - `Edit` (secondary, opens the drill-in editor)
  - `?` info icon (opens the popout — see Deliverable 4)
- **No status pill on the row** (status is implicit — if it's in the action queue, it's pending review)
- **No channel pill, no parser pill, no route pill** — those are noise the operator doesn't need
- **Knowledge gap indicator:** if the inquiry has a knowledge gap, a small amber dot replaces the Send button (Edit is still available). Hover shows "Held for knowledge gap — see Knowledge."

**Visual treatment:**
- Use the same active-row highlight pattern as today, but lighter
- Active row (selected for drill-in) gets a left-edge accent
- Hover state on the row is subtle — operators are clicking, not browsing
- Row height: ~60-72px depending on draft preview length

**Unbound rows:**
- Top line shows `Unbound` (amber pill) instead of property name
- Send button is **disabled** with hover text: "Bind to a property to send"
- Edit is still available (the operator can manually compose and edit)
- Info icon shows binding candidates as the first popout section
- Knowledge gap dot is independent — an unbound + knowledge-gap row shows both indicators

### 4. Info icon popout (inquiry detail on demand)

**Goal:** The guest's inquiry message and all the contextual signals live behind a question-mark icon. The operator clicks when they want details, not by default.

**Files:** `app/static/dashboard/js/sections/messages.js`, `app/static/dashboard/styles/dashboard.css`.

**Behavior:**
- Click the `?` icon on a row: opens a small popout (~480-560px wide) anchored to the row, showing:
  - Full guest inquiry message text
  - Channel (Airbnb / Vrbo / direct)
  - Listing ID, dates if present
  - Confidence chip (full label)
  - Knowledge gap indicator with topic, if present
  - Policy warnings, if any, with full text
  - Binding candidates (if unbound)
- Popout closes on: click outside, Esc, or clicking the `?` again
- Popout is read-only — actions still live on the row

**Critically:** the popout does NOT show parser source, draft source, route outcome, fallback reason, or any other internal plumbing details. Those remain hidden from operator eyeline.

### 5. Action button discipline

**Goal:** Send and Edit are the inline actions. Reject is gone. Regenerate is demoted to drill-in only with rate limiting.

**Files:** `app/static/dashboard/js/sections/messages.js`.

**Changes:**

- **Reject button removed everywhere.** Remove from row template, remove from drill-in action row, remove the `handleReject()` function wiring, remove the `rejectInquiry()` API call wiring if no other path uses it (verify before deleting). The `rejectInquiry` API function itself stays available for any future internal use, but no UI surfaces it.
- **Regenerate removed from row template.** Keep in drill-in as a secondary button.
- **Regenerate rate-limited in drill-in.** After clicking Regenerate, the button disables for 60 seconds and shows a countdown ("Regenerate in 45s"). This prevents the "hit regenerate over and over hoping for better" antipattern. The 60s threshold is a constant at the top of the file, easy to tune later.
- **Send button on row:** clicking sends without entering drill-in. Same `handleSend()` logic as today, but invoked from the row context — the row's inquiry ID becomes the action target. Confirmation flash appears on the row briefly, then the row is removed from the action queue on the next reload (within 30s, or immediately via `loadMessages({force: true})` after send).
- **Edit button on row:** clicking enters the drill-in workspace with the editor open (same as today's "Edit draft" flow). Operator can adjust and Send from drill-in.

**Send-from-row gating (held / low-confidence drafts):**
- If the draft is held (knowledge gap, fallback placeholder, etc.): Send button is hidden, only Edit available. The operator must enter drill-in to act.
- If the draft is low confidence (< 0.7): Send button is present but visually treated with caution (amber border, hover text: "Low confidence — review before sending").
- High and medium confidence drafts: Send button is the primary visual action on the row, no caution treatment.

### 6. Resolved queue separation

**Goal:** Sent items leave the action queue. A clear "Resolved" tab shows what the operator handled. Follow-ups resurface threads automatically.

**Files:** `app/static/dashboard/index.html` (Pre-Booking view markup), `app/static/dashboard/js/sections/messages.js`.

**Changes:**

- **Status tabs near the queue header** become the primary navigation between Action queue and Resolved:
  - `Action queue` (default) — `state.workView = 'action_queue'`, shows pending_review only. This is the existing behavior.
  - `Resolved` — `state.workView = 'recently_closed'`, shows replied/closed items from the last 7 days. Renamed from "Closed" to "Resolved" to match operator vocabulary.
  - The old "All" tab is removed — the action/resolved split is cleaner.
- **Resolved queue treatment:**
  - Same row template as action queue but with a "Sent ⋅ Xm ago" line instead of action buttons
  - Optionally show the actual sent reply text (not the original AI draft if it was edited)
  - Read-only — no Send, no Edit
  - Info icon still works for inquiry details
- **Resolved count visible:** the Resolved tab label shows count: "Resolved (12)" so the operator can see at a glance how much they've handled.
- **Follow-up resurfacing (verify, don't build):** when a guest replies on a previously-resolved thread, a new inquiry row should appear in the action queue (server-side behavior). The smoke pass verifies this works end-to-end. If it doesn't work, that's a separate ship — captured but not in scope here.

**Stable session anchor:** if an operator is in the Resolved view when they send something from elsewhere (unlikely but possible), reload doesn't yank them back to Action queue. The current `state.workView` persists.

### 7. Ship E follow-up bugs

**Bug 1: Unbound-only default-on-load.**

The client-side fix (`state.unboundOnly = requestedUnboundOnly && !!data.unboundOnly`) was correct but Codex still saw the filter on initial load in production. Either:
- Server-side: `/app/api/messages` is stamping `unboundOnly: true` even when no client param requested it
- Cache-related: some cached state path is still hydrating `state.unboundOnly = true` before first fetch

**Investigation step (do this first, before patching):** Make a clean `/app/api/messages` request with no query parameters from the browser console as Lanier. Observe the response. If `unboundOnly: true` comes back, it's server-side. If `unboundOnly: false`, it's client-side state hydration.

If server-side, find the endpoint handler (likely in `operator_app.py` or `operator_prebooking.py`) and trace where `unboundOnly` is being set in the response. Stop doing that for fresh sessions.

If client-side, trace where `state.unboundOnly` is being assigned `true` before `loadMessages()` runs for the first time. Likely candidates: preference loading (we don't currently persist `unboundOnly` — verify), metric filter restoration, or the unbound-chip click handler firing on init.

**Bug 2: Draft source still visible in drill-in.**

The signal band cleanup in Ship E removed `draftSource`/`parserSource`/`routeOutcome` from `renderSignalBand()`. But `buildDraftMeta()` still includes them. Specifically, lines like:

```js
rows.push({
  label: 'Draft path',
  value: humanizeToken(draftSource) || 'model',
});
// ... and
if (selected.routeOutcome) {
  rows.push({ label: 'Route outcome', value: humanizeToken(selected.routeOutcome) });
}
// ... and
if (selected.parserSource || selected.sourceProvider) {
  rows.push({ label: 'Parser', value: ... });
}
```

These rows render in the "Message Analysis" block which still appears in some drill-in path. Codex's verification step: trace where `buildDraftMeta()` is currently called and verify whether the block is still rendering. If yes (likely — search for `buildDraftMeta(` in the file), remove the three offending row pushes (Draft path, Route outcome, Parser). Keep the operator-relevant rows (Latest turn, Property binding, Policy warnings, Message refs).

Codex flagged that the visible text was "WARNING draft source: messaging brain" which looks more like `policyWarnings` content than `buildDraftMeta`. **Both paths need checking.** If a policy warning contains "draft source: messaging brain" as content, that's an upstream content bug (the policy flag generator is including internal plumbing in user-facing warning text). Fix it at the source if found — or filter it client-side as a defensive cleanup if the upstream fix is risky. The defensive client-side filter would be: in `renderSignalBand()` and `buildDraftMeta()`, skip any policy warning whose text contains "draft source:", "parser:", or "route:" substrings. Quick guard, no upstream change required.

---

## Files involved

- `app/static/dashboard/index.html` — shell nav structure, Pre-Booking view markup
- `app/static/dashboard/styles/dashboard.css` — nav collapse, row redesign, popouts, button states
- `app/static/dashboard/js/sections/shell.js` — nav collapse JS, hover-expand wiring, preference persistence
- `app/static/dashboard/js/sections/messages.js` — row template, action wiring, popout rendering, regenerate rate limit, status tab restructure, info-icon popout, draft-meta cleanup
- Possibly one backend file if unbound-only investigation finds a server-side cause

Cache-bust the import strings on any files touched.

---

## Acceptance criteria

The ship is done when all of the following are true:

1. Left nav stays collapsed to icons whenever the cursor is not over it. Expands smoothly on cursor enter, collapses smoothly on cursor leave with a small anti-flicker delay. No pin toggle, no persistence — same behavior every session.
2. Pre-Booking active-state pill matches the visual treatment of other nav items (no dark grey).
3. Context rail in Pre-Booking defaults to a thin icon-strip on the right edge; clicking an icon opens a popout panel; Esc or click-outside closes it.
4. Each queue row shows: compact top metadata line, 1-2 line AI draft preview, inline Send + Edit + ? buttons.
5. Send on a row sends the inquiry without entering drill-in; flash confirmation appears; row removes from action queue within 30s.
6. Send button is hidden on held drafts; visually treated with caution on low-confidence drafts; primary on high/medium confidence drafts; disabled on unbound rows.
7. Edit on a row enters drill-in with the editor open.
8. `?` info icon opens a popout with full guest inquiry, channel, confidence, knowledge gap detail, policy warnings, binding candidates — but NO parser/draft-source/route data.
9. Reject button is removed from every UI surface.
10. Regenerate is removed from the row template; in drill-in it rate-limits to once per 60 seconds with visible countdown.
11. Status tabs are "Action queue" and "Resolved" only (no "All").
12. Resolved tab shows recently-sent items, read-only, with sent timestamp.
13. Resolved tab label shows count.
14. After sending, item disappears from Action queue on next refresh.
15. Unbound-only filter does NOT appear on a fresh page load (Bug 1 fixed at the actual point of failure).
16. Drill-in no longer shows draft source, parser source, route outcome anywhere — including the Message Analysis block (Bug 2 fixed).
17. Polling, `activeSnapshot` clobber protection, action button outcomes all preserved.
18. Today, Analytics, In-Stay, all other views unaffected (except for inheriting the left-nav collapse).
19. No console errors anywhere.

---

## Suggested implementation order

1. **Left nav collapse.** Shell-level work. Verify it doesn't break any other view's rendering. CSS + small JS for hover/click/pin behavior.
2. **Pre-Booking nav pill color fix.** One CSS rule.
3. **Context rail popout.** Markup restructure, CSS for collapsed/expanded states, JS for click/Esc/outside-click.
4. **Queue row redesign.** Row template rewrite, CSS for the new dense row, inline action buttons.
5. **Send-from-row wiring.** Hook the new inline Send button to existing `handleSend()` with the row's inquiry as the active item.
6. **Info icon popout.** Markup + render function for the popout, CSS for positioning and overlay.
7. **Action button discipline.** Remove Reject, demote Regenerate, add rate limit. Update drill-in action row.
8. **Status tabs restructure.** Rename "Closed" to "Resolved", remove "All", update count display.
9. **Resolved queue treatment.** Read-only row template variant for resolved items.
10. **Ship E follow-up Bug 1 (unbound-only).** Investigate first (clean API request), then patch where the misbehavior actually lives.
11. **Ship E follow-up Bug 2 (draft source in drill-in).** Trace `buildDraftMeta()` and policy warning content, fix where the leak is.
12. **Smoke test in dev.** Walk the acceptance criteria. Push and deploy when clean.

---

## Smoke test checklist

After implementation, manually verify as Lanier:

- Nav stays collapsed at idle
- Hovering over the nav region expands it; moving cursor away collapses it
- Tooltips on collapsed icons show labels
- Brief mouse-out doesn't cause flicker (small collapse delay works)
- No persistence across sessions — nav always starts collapsed
- Pre-Booking active state matches other nav items visually
- Context rail starts collapsed; clicking an icon opens popout; Esc/click-outside closes
- Queue rows are dense — 25 visible on one screen without scrolling on a standard laptop viewport
- AI draft preview is readable on the row
- Send on a bound + high-confidence row sends and removes from queue
- Send is disabled on unbound rows; held drafts hide the Send button
- Edit on a row opens drill-in editor
- ? popout shows inquiry + signals, no parser/draft-source data
- Reject button gone everywhere
- Regenerate gone from rows; in drill-in shows 60s rate limit countdown after click
- Status tabs: "Action queue" and "Resolved" only
- Resolved tab shows sent items with timestamps
- Resolved count badge updates correctly
- Fresh-load (clear localStorage, hard refresh) shows all pending, not unbound-only
- Drill-in does NOT show draft source, parser, or route outcome anywhere
- Today and other views unaffected
- No console errors

---

## What ships after this

**Phase 1 backend work continues in parallel:** booking attribution (longest pole), inquiry signal normalization, capability enforcement audit. These remain Codex's domain for backend ships.

**Future Pre-Booking ships:**
- **Auto-mode toggle.** When confidence is earned, the toggle compresses the queue further and shifts the bands to dominant. Same surface, different proportions.
- **Additional exception groups in the band.** Unbound, low-confidence held, policy-flagged.
- **Confidence band expansion.** Histogram, trend-vs-prior, conversion overlay once attribution lands.
- **Analytics band fill-out.** Conversion-correlated topics when attribution lands.

**Other lifecycle surfaces** (In-Stay, Pre-Arrival, Post-Stay) get the same row-velocity treatment in their own ships, each scoped to that phase's actions.

---

## Notes for the executor

- The left nav collapse is the change with the widest blast radius. Verify other views (Today, Analytics, In-Stay, Settings, etc.) still render correctly with a 56px-wide nav. Active-state highlights, badges, and the icon-only treatment must all work at the smaller width.
- The hover-expand should feel snappy but not twitchy. Pure CSS `:hover` with a `transition: width 150ms ease` on the nav container is likely the cleanest path. If a small JS delay on collapse is needed to prevent flicker when the cursor grazes the edge, keep it minimal.
- The row redesign is the highest-impact change for operator velocity. Get the row height and font sizes right before adding any of the other deliverables — Lanier should be able to see 25 rows on a normal laptop viewport without scrolling.
- The Send-from-row flow needs to feel **fast.** Clicking Send shouldn't open any modal, shouldn't require a confirmation dialog, shouldn't make the operator wait. Optimistic UI — flash confirmation immediately, do the API call in the background, handle the failure case if the server rejects.
- Regenerate rate limit at 60s: this should be enforced client-side only (not a server-side rate limit). The button visibly disables and shows countdown.
- The info-icon popout positioning is non-trivial. Anchor to the icon, but flip orientation if the popout would overflow the viewport. Use a portal pattern if needed to escape any overflow:hidden ancestors.
- For the unbound-only Bug 1: investigate first, patch second. The investigation step (clean API request from console) takes 2 minutes and tells you where to fix. Skipping it risks fixing the wrong side.
- For Bug 2: `buildDraftMeta()` is one place; `policyWarnings` content is another. Both need checking. Defensive client-side filter (skip warnings whose text starts with "draft source:", "parser:", "route:") is a safe fallback if upstream isn't in scope.
- The "Resolved" rename from "Closed" is small but operator-meaningful. "Closed" implies a ticket was killed; "Resolved" implies work was completed. Match the operator's mental model.
- This ship is structurally bigger than Ship E but every individual change is scoped tight. Discipline matters — don't expand any one deliverable beyond what's specified.

---

*End of Ship F brief.*
