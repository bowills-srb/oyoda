# Ship H — Pre-Booking honesty and bounded layout

**Status:** Brief written May 20, 2026. Drafted post-Ship-G empirical confirmation and post-Codex audit of the gap-fill loop (see `SESSION_RESUME_2026-05-19.md` and the audit findings logged in conversation).

**Scope discipline:** Ship H is layout, labeling, and counter honesty only. No backend behavior changes. No knowledge-gap reintegration — that is Ship I.

**Why this is its own ship, separate from Ship I:** Ship H is verifiable purely by reading the rendered UI against the brief's acceptance criteria. Ship I requires backend changes (gap-topic persistence, KB-save hooks, regeneration triggers) that have independent risk. Splitting them keeps the Ship G verification discipline: each ship is structurally inspectable in isolation.

---

## What Ship H ships

Six deliverables, executed in order. Each gets verified structurally before the next starts.

1. **Tab honesty.** Replace the single "Resolved" tab with three: **Sent**, **Held**, **Closed**.
2. **Counter honesty.** Replace the four top-right pills (PENDING / READY / HELD / UNBOUND) with an honest set that maps to operator-meaningful state.
3. **Momentum line.** A single line under the page title showing what's currently awaiting the operator and 30-day Pre-Booking throughput. (Richer "AI auto-sent today" content deferred to Ship I — see Deliverable 3.)
4. **Confidence inline with DRAFT label.** Move the confidence percentage out of the row's top-right corner and inline it with the DRAFT label on the left.
5. **Bounded scroll on Pre-Booking.** Queue scrolls internally; the page does not grow.
6. **Bounded scroll on Knowledge.** Same fix applied to the Knowledge view.

Knowledge-gap routing (`routesToKnowledge()` in `messages.js`) stays exactly as it is in Ship G. The "Inquiries waiting on knowledge" section in `view-knowledge` stays where it is. Those move in Ship I.

---

## Deliverable 1 — Tab honesty

### What's wrong now

The "Resolved" tab currently shows inquiries whose `status !== 'pending_review'`. That bucket contains three structurally different states:

- **Sent:** message went out (status `replied`, operator-sent or AI-auto-sent)
- **Held:** draft exists, was never sent (status `rejected`, `closed`, or other non-`replied` non-`pending_review` states that retain a draft)
- **Closed:** inquiry was dismissed without a reply (status `closed` with no draft, or `rejected` with no draft retained)

Calling all of these "Resolved" misleads the operator about whether the guest got a reply. Screenshots from May 20 show 148 "Resolved" items, the first three of which are clearly held drafts with confidence percentages — not sent messages.

### What Ship H does

Replace `workView` value `recently_closed` with three values: `sent`, `held`, `closed`. The tab bar renders three tabs in that order.

**State mapping (use existing inquiry fields, no new backend fields):**

- **Sent** = `status === 'replied'`. Message went out.
- **Held** = `status !== 'pending_review' && status !== 'replied' && draftText is non-empty`. Draft exists, never sent.
- **Closed** = `status !== 'pending_review' && status !== 'replied' && (no draftText OR explicitly closed without reply)`. No reply ever happened.

**Draft-presence rule for Held vs Closed:** "draftText is non-empty" means a real draft, not a junk value. Empty strings, whitespace-only strings, and known placeholder strings (e.g., `'(no AI draft generated yet)'` from `draftPreviewText()` in `messages.js`, or any string that's purely the result of a fallback render) count as **no draft** and the row goes to Closed, not Held. The categorization function should normalize via `String(item.draftText || '').trim()` and check against a small allowlist of placeholder patterns before classifying as Held. This keeps legacy or malformed records from polluting the Held tab.

The state mapping logic lives in a new function `categorizeNonActive(item)` in `messages.js` that returns one of `'sent' | 'held' | 'closed'`. This is the only place that decides; all rendering reads from it.

### Acceptance criteria

- The tab bar in Pre-Booking shows three tabs: Sent, Held, Closed. In that order.
- The Action queue tab still exists as a fourth, leftmost tab (no change to its content).
- Clicking Sent shows only items where `categorizeNonActive` returns `'sent'`.
- Clicking Held shows only items where `categorizeNonActive` returns `'held'`.
- Clicking Closed shows only items where `categorizeNonActive` returns `'closed'`.
- Counts displayed next to each tab (e.g., "Held · 75") reflect the same categorization.
- The string "Resolved" does not appear anywhere in the Pre-Booking surface.
- `workViewLabel()` in `messages.js` is updated to handle the three new values.
- `localStorage` preference key for `workView` survives the rename: existing operators land on `action_queue` on next load if their stored value is the now-removed `recently_closed`.

---

## Deliverable 2 — Counter honesty

### What's wrong now

The top-right of Pre-Booking renders four pills with values like "1 PENDING / 103 READY / 75 HELD / 1 UNBOUND." These are misleading on two dimensions:

- **"READY 103"** sounds like "103 drafts ready to send" — alarming if literal. Almost certainly means "103 drafts whose confidence cleared auto-send threshold and were sent automatically" — i.e., a *resolved* count over some window, not a current-queue snapshot.
- **"PENDING 1" and "HELD 75"** likely overlap. A held draft is also "pending operator review" in the operator's mental model. Two boxes showing related slices of the same data with no relationship explained.

The result: an operator scanning the top-right sees four numbers totaling 180 and has no idea whether 180 things need her attention or 180 things have already been handled.

### What Ship H does

Replace the four pills with **two** honest counters.

The two top-right counters:

- **AWAITING YOU** — count of items currently rendered in the Action queue. Computed in the frontend from the post-filter queue slice, *not* from `summary.pending`. This matters: `summary.pending` is a raw count of `status='pending_review'` from `dashboard_summary_service.py`, while the rendered Action queue applies the `routesToKnowledge()` filter from Ship G. Those two counts diverge whenever knowledge-gap inquiries exist. AWAITING YOU is the queue-rendered slice, which is what the operator actually sees. Click → opens Action queue.
- **WAITING ON KNOWLEDGE** — count of items where `routesToKnowledge(item) === true`. Computed in the frontend in the same pass as AWAITING YOU. This is the number that currently drives the red dot on the Knowledge nav badge. Click → opens Knowledge view. (In Ship I this counter disappears because gap items move back into the queue, but in Ship H it stays as the honest representation of the Ship G design.)

Both counts are computed from the loaded item list in a single pass, no backend dependency, single source of truth.

The pills that go away: PENDING, READY, HELD, UNBOUND. Their data is not lost — Held is now a tab; READY's underlying "what the AI handled" data moves to the momentum line in whatever form is honestly computable (see Deliverable 3); UNBOUND is folded into AWAITING YOU.

### Acceptance criteria

- The top-right of Pre-Booking shows exactly two counters: AWAITING YOU and WAITING ON KNOWLEDGE.
- AWAITING YOU's value equals exactly the number of rows currently rendered in the Action queue tab. (Single source of truth — both come from the same frontend computation.)
- WAITING ON KNOWLEDGE's value equals the count of loaded items where `routesToKnowledge(item) === true`.
- Both counts are derived in the frontend from the loaded item list; neither is read from `summary.pending` or any other backend aggregate.
- The strings PENDING, READY, HELD, UNBOUND do not appear as top-right pill labels anywhere in Pre-Booking. (They may still appear inside row treatments where appropriate — that's not part of this deliverable.)
- Clicking AWAITING YOU activates the Action queue tab. Clicking WAITING ON KNOWLEDGE navigates to Knowledge.
- The counters update on each `loadMessages()` call, matching the rendered queue exactly.

### Implementation note

Compute both counts in a single pass over the loaded items in `loadMessages()` or `filteredItems()`, stash them on `state.counters = { awaitingYou, waitingOnKnowledge }`, and read from there in the render. This avoids divergence and keeps the computation honest.

---

## Deliverable 3 — Momentum line

### Why this matters

Ship G stripped the surface to honest minimalism, which Hunter correctly observed leaves the page feeling bland — particularly when the queue is empty. The missing element is *momentum*: a sense that the AI is actively doing work for the operator, even when there's nothing in her queue.

This is the Fin-inspired concept from the May 20 conversation: instead of a static snapshot of categorical state, show *flow*. The AI is working in the background. Communicate it.

### Constraint: only what's honestly computable

Before drafting this, Codex audited `dashboard_summary_service.py` and the existing `adapters.js` payload. The summary currently exposes for Pre-Booking only: `pending`, `replied_30d`, `total_30d`. Two important things are NOT available:

- **No "today" window.** The only time slice is 30 days.
- **No AI-vs-operator send attribution.** The summary cannot distinguish "AI auto-sent" from "operator sent." Per-item data does not carry a verified `triggered_by: 'auto'` vs `'operator'` field on the loaded queue list either.

This means "AI auto-sent {N} today" — the most emotionally satisfying segment — is **not honestly computable in Ship H** without backend work that doesn't exist yet. Including it would require fabricating either the attribution or the time slice, which violates the "honest signals only" principle from `KNOWN_REFINEMENTS.md`.

Ship H ships what's honest now. The richer momentum story arrives with Ship I (which adds auto-send attribution as part of the KB-fill loop work) or with a small dedicated backend ship.

### What Ship H does

Add a single line directly under the page title `Pre-Booking`. The line reads:

```
{M} drafts awaiting your review · {N} replied in last 30 days · {K} total in last 30 days
```

Where:

- **{M}** = same as AWAITING YOU counter from Deliverable 2. Computed in the frontend from the rendered queue.
- **{N}** = `summary.pre_booking.replied_30d`. Already in the existing payload from `dashboard_summary_service.py`.
- **{K}** = `summary.pre_booking.total_30d`. Already in the existing payload.

All three are honest. None require new backend fields. The "AI presenting" feeling is still served because the operator sees the throughput of the system at a glance — 30-day volume context next to today's queue depth tells her the AI is processing inquiries even when her current queue is light.

### What's deferred

Three richer signals are explicitly deferred from Ship H:

1. **"AI auto-sent today"** — requires send-attribution on the inquiry record and a today-window aggregate. Wait for Ship I to add the attribution as part of the KB-fill auto-send work, then this becomes computable.
2. **"K closed this week"** — requires a 7-day window. The summary only has 30-day. Could be added as a small backend extension if/when there's a reason.
3. **Live tick / "updated 3m ago" feel** — would require the summary endpoint to expose `last_inquiry_arrived_at` or similar. Defer until the operator workflow indicates whether this matters.

Codex or whoever picks up Ship I (or a follow-up momentum ship) should add the relevant fields then. For Ship H, ship the three honest segments above.

### Visual treatment

- Single line, full width under the page title `Pre-Booking`.
- Same typography family as the existing confidence band stats: serif numerics ("Cormorant Garamond" per current dashboard.css), labels in DM Mono small-caps.
- Numerics in `var(--white)` or equivalent; labels in `var(--dim)`.
- Dot separators between segments.
- No background fill, no border, no chrome. Just text. The restraint is the point — it should feel like a status line, not a card.

### Acceptance criteria

- A single text line exists directly under the page title `Pre-Booking`, before the existing resolution-counts strip ("0 RESOLVED · 0 PENDING · — ESCALATIONS").
- The line contains three segments separated by `·`.
- Each segment is `{number} {short label}`.
- {M} reads from `state.counters.awaitingYou` computed in Deliverable 2.
- {N} reads from `summary.pre_booking.replied_30d` via the existing summary payload path.
- {K} reads from `summary.pre_booking.total_30d` via the existing summary payload path.
- No segment fabricates or estimates a value. If any of the three is unavailable on a given load (e.g., summary endpoint failed), the segment renders `—` with a `title` attribute explaining why.
- The line uses serif numerics matching the confidence band's `pb-conf-stat-value` style.
- No new background, border, or container chrome is added.
- No backend field is added for Ship H. (The deferred richer signals get backend fields in their own ships.)

---

## Deliverable 4 — Confidence inline with DRAFT label

### What's wrong now

In the current row render, the confidence percentage sits in the top-right of each row (e.g., the "10%" or "40%" visible in the May 20 screenshots). The DRAFT label and its content sit on the left and span most of the row width. The operator's eye, when scanning a stack of rows, has to dart from the draft text (left) to the confidence (top-right corner) to know whether this row needs attention.

Fin-style and other high-density operator UIs put state *with* content, so eye-tracking is one move.

### What Ship H does

Move the confidence percentage out of the row's top-right and inline it directly after the DRAFT label.

Before: `DRAFT  Thank you for reaching out about Sea La Vie...` (with `40%` floating top-right)

After: `DRAFT · 40%  Thank you for reaching out about Sea La Vie...` (top-right becomes free space for the `?` button alone, or removed entirely)

The `?` button stays in the row (it's the only detail-surface entry point per Ship G). It can stay top-right, or move to the action row alongside Send/Edit. The brief leaves that to the executor's judgment based on visual balance, but recommends keeping it in the top-right where it is now since that's where Ship G placed it.

### Acceptance criteria

- The confidence percentage appears inline with the DRAFT label on every row that has a draft.
- The DRAFT label format is `DRAFT · {N}%`.
- No confidence percentage renders in the top-right corner of any row.
- Rows without a draft (e.g., manual-only inquiries) render no confidence segment at all — not "—", not "0%".
- The `?` button position is unchanged from Ship G unless layout balance dictates a move, in which case the executor documents the decision in the commit message.

---

## Deliverable 5 — Bounded scroll on Pre-Booking

### What's wrong now

After Ship G's structural deletion of the three-pane grid, the `.pb-workshop` container has no height constraint and no overflow behavior. The result: when the queue contains many items, the queue extends downward and the entire `.main` element scrolls. The Pre-Booking Patterns analytics band at the bottom of the page becomes effectively invisible because it's many viewport-heights below the top of the queue.

The CSS already has a working bounded-scroll pattern: `.pb-inbox-view` uses `height: calc(100vh - var(--topbar) - 48px); overflow: hidden;` with internal scrollable children. That pattern from Ship D survived Ship G's deletion but isn't applied to `.pb-workshop`.

### What Ship H does

Apply the same bounded-shell pattern to `.pb-workshop`:

```css
.pb-workshop {
  height: calc(100vh - var(--topbar) - 48px - {space taken by page header + counters + confidence band + momentum line});
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.pb-queue-pane {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
```

The exact height calculation depends on the visual elements above the queue (page header, counters, confidence band, momentum line). The executor measures these in the live page and sets the value, or uses CSS calc with sub-selectors. The page-level `.main` container retains `overflow-y: auto` but should not need to scroll under normal usage because all major sections are bounded internally.

The analytics band (`pb-analytics`, currently below the queue) should live *outside* the `.pb-workshop` container or inside its own bounded scroll. The brief's preferred treatment: keep analytics below the queue as it is now, but make it reachable via the `.main` scroll *after* the bounded queue. So the page layout becomes:

1. Header / counters / confidence band / momentum line (fixed)
2. `.pb-workshop` (bounded internal scroll, contains the queue)
3. Analytics band (scrolls into view when the user scrolls `.main` past the bounded workshop)

This preserves the Ship G hierarchy ("queue dominant; analytics below the fold") while making the analytics actually reachable.

### Acceptance criteria

- With 25+ items in the queue, the page does not grow vertically beyond the viewport unless the operator deliberately scrolls.
- Scrolling within the queue does not scroll the page header, counters, confidence band, or momentum line.
- The Pre-Booking Patterns band is reachable by scrolling `.main` past the bounded `.pb-workshop`.
- On a fresh load with an empty queue, no scrollbar appears on `.main` unless the analytics band exceeds the remaining viewport height.
- The bounded-scroll behavior is verified on three queue depths: 0 items (empty state), 5 items, 50+ items.

---

## Deliverable 6 — Bounded scroll on Knowledge

### What's wrong now

The Knowledge view has the same issue as Pre-Booking: the "Inquiries waiting on knowledge" section (added in Ship G) plus the existing entries and gaps tabs render as a tall stack and the page scrolls. The waiting-inquiries section, the active tab content, and any other Knowledge surfaces compete for vertical space without internal bounding.

### What Ship H does

Apply the same bounded-shell pattern to the top-level Knowledge view container. Identify the equivalent of `.pb-workshop` for Knowledge (likely `#view-knowledge` or its primary child container) and constrain it with `height: calc(100vh - var(--topbar) - {fixed elements})` and `overflow: hidden`, with the scrollable children inside.

The internal scrollable regions in Knowledge are:

- The "Inquiries waiting on knowledge" list (`#kb-inquiries-waiting-list` if that's the right ID)
- The active tab content (Entries list or Gaps list)

Both should scroll within their bounded containers; the Knowledge page as a whole should not grow.

### Acceptance criteria

- With many entries / many gaps / many waiting inquiries, the Knowledge page does not grow vertically beyond the viewport unless the operator deliberately scrolls.
- The Entries/Gaps tab bar stays visible while scrolling the list within a tab.
- The "Inquiries waiting on knowledge" header stays visible while scrolling the waiting-inquiries list.
- Bounded behavior is verified at three densities: empty, ~10 items, 50+ items.

---

## Verification pattern

Same discipline as Ship G:

1. Codex executes each deliverable in order.
2. After each deliverable, the executor runs `node --check` on touched JS files.
3. After all deliverables, the executor confirms the structural acceptance criteria by direct file read: tab structure visible in `messages.js`, counters visible in `index.html` and `messages.js`, momentum line visible in `messages.js`, bounded scroll properties present in `dashboard.css`.
4. Hand off to Hunter for empirical smoke before push: open Pre-Booking with a populated queue, verify each acceptance criterion in the live browser.
5. Bump cache busts: `dashboard.css` to next letter (`?v=2026-05-20-a` or whatever's next), `messages.js` to next letter, `knowledge.js` to next letter. Both `index.html` (for the CSS link) and `main.js` (for the JS import) get updated.

### Files anticipated to change

- `app/static/dashboard/index.html` — top-right counter elements, momentum line container, cache busts
- `app/static/dashboard/styles/dashboard.css` — bounded scroll for `.pb-workshop` and Knowledge view, momentum line styling, inline confidence styling
- `app/static/dashboard/js/sections/messages.js` — tab structure (replace `recently_closed` with `sent`/`held`/`closed`), counter rendering, momentum line rendering, row template (confidence inline)
- `app/static/dashboard/js/sections/knowledge.js` — bounded scroll structural changes if needed
- `app/static/dashboard/js/main.js` — cache bust bumps for `messages.js` and `knowledge.js`

### What does NOT change in Ship H

- `routesToKnowledge()` and the knowledge-gap filtering. Knowledge gaps stay out of Pre-Booking until Ship I.
- The `?` popout behavior or contents.
- Inline Edit / Send button behavior.
- Polling cadence, `activeSnapshot` clobber protection, action endpoint wiring.
- Any backend Python file. This is a pure frontend ship.

---

## Notes for the executor

- The momentum line in Ship H deliberately ships only what's honestly computable from the existing summary payload. Two richer signals were considered ("AI auto-sent today" and "K closed this week") and explicitly deferred because the backend doesn't currently expose send-attribution or 7-day windows. Don't try to fabricate them client-side. Ship I picks up the send-attribution work as part of the KB-fill auto-send loop.
- Bounded scroll is a measure-twice-cut-once kind of CSS change. Get the height calculation right by measuring against the actual visible page elements, not by guessing.
- "Sent / Held / Closed" tab counts can be expensive if computed by iterating all items every render. Use a single pass in `loadMessages()` to compute the three counts and stash them on `state.tabCounts`, then read from there in the render. Same pattern applies to the Deliverable 2 counters — single pass, stash on `state.counters`, read everywhere.
- If the bounded-scroll CSS changes feel hacky (sub-selectors, magic numbers), pause and ask whether the layout shape is wrong rather than the CSS. The right answer is probably a flex column at the `.main` level with one bounded child for the queue area and one flow child for analytics.
