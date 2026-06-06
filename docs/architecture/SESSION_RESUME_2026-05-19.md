# Session Resume — Oyvoda Pre-Booking

**Created:** May 19, 2026
**Last updated:** May 19, 2026 (post-Ship-G structural verification)
**For:** New session continuing Oyvoda dashboard work after Ship F deploy

---

## Ship G — status as of this update

**Code on disk: structurally verified. Empirical confirmation: still pending.**

Ship G has been executed by Codex against the brief at `docs/architecture/SHIP_G_PREBOOKING_CORRECTNESS.md`. The structural deletions and the new surfaces have been verified by direct file reads of `index.html`, `messages.js`, and `knowledge.js`:

- `view-prebooking` is now single-pane. `msg-detail-pane` and `pb-context-rail` are removed from the markup.
- Queue rows render in email shape: metadata strip → guest message → `Draft` label + AI draft → Send/Edit inline.
- The `?` popout is the only detail surface. Anchored to the row, dismisses on outside-click / Esc / button-toggle.
- Inline Edit replaces the draft block with a textarea + Save / Cancel on the same row.
- Knowledge-gap inquiries are filtered out of Pre-Booking via `routesToKnowledge()` in `filteredItems()` and routed to a new "Inquiries waiting on knowledge" section at the top of `view-knowledge`, with a `Resolve in KB` button that pre-fills the existing `add-kb-modal`.
- `nb-gaps-kb` sidebar badge is now a red-dot treatment (`nb-red-dot` class), updated from the Pre-Booking load path. CSS rule for `nb-red-dot` confirmed by Codex to exist in `dashboard.css`.
- `buildDraftMeta()`, `renderSignalBand()`, `renderDetail()`, `renderContextRail()`, `renderOpsPane()`, and the various context-rail render helpers are all removed from `messages.js` (file shrank ~71KB → ~60KB).
- Cache busts bumped: `dashboard.css?v=2026-05-19-h`, `messages.js?v=2026-05-19-i`, `knowledge.js?v=2026-05-19-a`. Transitive imports of `api.js` and `adapters.js` deliberately stay on `?v=2026-05-19-g` because those files were not modified in this ship (verified by mtime).

**What is NOT yet confirmed:**

- **AC #11 (unbound-only on fresh load).** The brief required a documented diagnostic before any patch. That diagnostic was skipped. The code reads correctly on paper — `state.unboundOnly` initializes to `false`, is not loaded from localStorage, is defensively reset to `false` in `wireViewChange()` on every navigation into Pre-Booking, the `unbound_only` query param is only sent when state is true, and the post-fetch reconciliation is `state.unboundOnly = requestedUnboundOnly && data.unboundOnly === true`. But it has not been observed in a real browser session.
- **General browser smoke.** Visual rendering, popout positioning, contrast, console errors, polling behavior — none of these have been confirmed in a real browser.

**Blocking external condition:** Railway is currently down, which has taken oyvoda.com down with it. The smoke pass cannot run until Railway is restored.

**Resume protocol when Railway is back:**

1. Clear localStorage for the dashboard origin. Hard refresh Pre-Booking.
2. **If the queue loads with all pending inquiries visible (not unbound-only):** AC #11 passes empirically. Visually confirm the row shape, the `?` popout behavior, inline Edit, the Knowledge "waiting on knowledge" section, and the red-dot nav badge. If everything checks out, Ship G is good to push.
3. **If the queue still loads as unbound-only:** stop. Do not patch. Run the diagnostic checklist exactly as written in Deliverable 7 of `SHIP_G_PREBOOKING_CORRECTNESS.md` (including the addendum hint about the `hidden` attribute on `#msg-filter-indicator`). Fill the findings in before any further code.
4. Smoke any other regressions you find as Ship H follow-ups, not Ship G blockers. The structural deletions are the load-bearing change in Ship G and they are verified.

**Non-blocking follow-up captured for later (Ship H or similar):** the Knowledge nav red dot is updated from the Pre-Booking load path. If the operator opens directly to Today or Knowledge without visiting Pre-Booking, the badge will not refresh until polling kicks in or they navigate to Pre-Booking. Worth broadening the badge-update trigger — e.g., update it on any `loadMessages` call regardless of which surface initiated it, or on the global poll — but this does not block Ship G push.

---

## Where things stand right now

Ship F (`04fcdeb`) deployed to production at Railway deploy `cf2d0109`. The deploy was technically successful but **the UI shape Ship F intended did not fully land structurally.** The "context rail collapsed to popout" pattern was supposed to delete the three-pane grid; instead the three-pane grid is still in `index.html` and only CSS hover behavior was added. That is the root of the regression Hunter has been describing — every fix written after Ship F was written against a popout pattern that doesn't exist in the code.

This was discovered by reading `app/static/dashboard/index.html` directly. `view-prebooking` still contains:

```html
<div class="pb-workshop">
  <div class="pb-queue-pane" id="msg-list-pane">...</div>
  <div class="pb-draft-pane" id="msg-detail-pane">...</div>
  <aside class="pb-context-rail" id="pb-context-rail">...</aside>
</div>
```

Three permanent panes. The right two fill on row select. Selecting an unbound inquiry occupies persistent right-side space. The AI draft is visually dominant because it lives in the middle pane.

**The current Ship G brief** at `docs/architecture/SHIP_G_PREBOOKING_CORRECTNESS.md` reflects this verified state and prescribes deletion of the three-pane grid, replacement with a single-pane email-style queue, popout-only detail, knowledge-gap routing out of Pre-Booking, and the unbound-only investigation-before-fix discipline.

---

## What Hunter has been asking for, plainly

Stated across multiple turns:

1. **Pre-Booking is a single-pane queue.** The right-side "Unbound Inquiry" card and the context rail are both gone from persistent UI. Detail lives in a popout reached from the row.
2. **Each row reads like an email.** Guest message text on top in normal email-body font. Below it, the word **Draft** as a small label on the left, with the AI draft text to its right in slightly bolder weight. Send and Edit buttons inline with the draft, not at the far end of a separate row.
3. **No noise on the row.** Confidence percentage in the top metadata strip is fine. Status chips, channel pills, parser pills, "revenue sensitive" badges, "knowledge gap" badges — all gone.
4. **Knowledge-gap inquiries leave Pre-Booking entirely.** They route to the Knowledge surface where the operator fills the gap. The Knowledge nav item gets a red dot when gap inquiries exist.
5. **The Pre-Booking active-state pill** in the left nav was dark grey while other nav items used a different active treatment. Visual bug to fix.
6. **High signal density, not minimalism.** "Sleek, fast, task-shaped" — operator can read question, glance at draft, hit Send. The product principle Codex named: *"Pre-Booking should only contain work that is actually actionable as messaging work."*

---

## The unbound-only bug (still open, three failed fixes)

Symptom: Pre-Booking loads with the queue filtered to "SHOWING UNBOUND ONLY" on a fresh session. Operator has to click "Show all" to see the real queue.

Three patches attempted, all incorrect:
- Patch 1: added `requestedUnboundOnly && !!data.unboundOnly` guard in `loadMessages()` client-side — didn't resolve it.
- Patch 2: added a stronger reset path on Pre-Booking enter — didn't resolve it.
- Patch 3: filtered draft-source-style content from warnings (unrelated, but bundled in same ship F cleanup).

Suspected actual causes, none verified:
- `/app/api/messages` endpoint in `app/api/v1/endpoints/operator_prebooking.py` echoes `unbound_only` back in the response top-level field. Client reads `state.unboundOnly = !!data.unboundOnly` in some path.
- The `api.js` query-string builder filters out `null`, `undefined`, empty string — but NOT `false`. So a client param `unbound_only: false` may get serialized as `&unbound_only=false` and FastAPI may parse the literal string "false" as truthy depending on version/middleware.

The fix discipline is investigation-first. Ship G's brief includes an explicit pre-execution diagnostic step that must be completed before any code is written. Findings section in the brief gets filled in, then the one-line fix.

---

## What's already shipped and working

These are correct in production and should not be re-touched:

- **Today surface** (Ship C) — "Needs you now," "Patterns worth seeing," lifecycle strip, glance row. Setup Checklist correctly hides when complete (commit `d84e925`).
- **Lifecycle nav** (Ship B) — Today / Pre-Booking / Pre-Arrival / In-Stay / Post-Stay / Properties / Operations / Account.
- **Pre-Booking surface skeleton** — title block, counters, status tabs (Action queue / Resolved), property filter, resolution header, confidence band, analytics band below the fold.
- **Send / Edit / Regenerate / Reject backend wiring** at the inquiry-action endpoints (`approve`, `edit`, `reject`, `regenerate`). Reject is no longer in the UI but the endpoint still exists.
- **30s polling** with `activeSnapshot` clobber protection for mid-edit drafts.
- **Left nav hover-expand** — CSS-based, works.

---

## What's broken or wrong right now

- **Three-pane grid is still in `view-prebooking`.** Needs structural deletion (Ship G Deliverable 1).
- **Row template shows guest preview but AI draft is not visible on the row itself** — operator only sees it after selecting a row. Needs email-shaped row (Ship G Deliverable 2).
- **Unbound-only loads on fresh session.** Needs investigation, not another patch (Ship G Deliverable 7).
- **Knowledge-gap inquiries appear in Pre-Booking action queue.** Should route to Knowledge (Ship G Deliverable 4).
- **`buildDraftMeta()` still includes draft path / parser / route outcome** rows that may render in some drill-in path. Delete entirely (Ship G Deliverable 5).
- **"Revenue sensitive" badge** fires on weak signals (e.g., third-floor question). Remove from UI, keep predicate in code for future tightening.
- **Unbound message text contrast** is reportedly unreadable. Likely lives in the deleted context-rail rendering — verify after the rail deletion.
- **Pre-Booking nav active pill color** is darker grey than other active nav items. CSS fix.

---

## Operating principles locked in over this arc

These survived multiple iterations and are settled:

1. **Build the long-term operational interface, make it short-term friendly through proportions.** Same surface for day-one and month-two operators; queue dominant by default, bands compact; trust dial = queue depth controlled by operator. No mode switches.
2. **Pre-Booking only contains work that is actionable as messaging work.** Knowledge-gap items are knowledge work, not queue work — they live in Knowledge.
3. **High signal density, not minimalism.** Strip the parts that don't help the operator act. Keep what does, even if the result still feels information-rich.
4. **Honest signals only.** No fabricated metrics. If a value can't be computed truthfully (e.g., `correctHoldPct` without enough resolved-held data), show `—` with a tooltip.
5. **Geographic agnosticism is a hard constraint.** All systems take lat/long and geofence inputs, not 30A-specific hard-codes.
6. **No fake AI draft conversion-correlated metrics until booking attribution lands** (Phase 1 backend work).
7. **Operator-facing intelligence is distilled, not raw.** Operators never see parser source, draft source, route outcome, fallback reason in the UI.
8. **Investigate before patching repeat bugs.** The unbound-only bug has burned three rounds. Diagnose then fix.
9. **"On disk" ≠ "in git" ≠ "live in production."** Verify each transition.
10. **Compare before tombstone.** Don't write briefs from memory of code state — read the code first.

---

## Architecture documents on main

All these are committed and survive session resets:

- `docs/architecture/INTELLIGENCE_AND_ACCESS_FOUNDATION.md` — RBAC model, inquiry intelligence model, network intelligence and compounding loop, geographic agnosticism, six-phase build sequence.
- `docs/architecture/VERIFIED_FOUNDATION_AUDIT.md` (commit `b0ac584`) — verified what exists today: PMS booking ingestion is real, inquiry-to-booking attribution is the longest pole, scope model and capability flags exist, pre-booking action endpoint in `operator_onboarding.py` enforces tenant access but not scoped capability.
- `docs/architecture/KNOWN_REFINEMENTS.md` — captured smaller items, active sequence at the top.
- `docs/architecture/SHIP_A_FOUNDATIONS.md` through `SHIP_F_PREBOOKING_VELOCITY.md` — historical record of each ship.
- `docs/architecture/SHIP_G_PREBOOKING_CORRECTNESS.md` — current ship to execute, rewritten against verified repo state on May 19, 2026.
- `docs/architecture/SPIKE_PREBOOKING_OPERATIONS_VIEW.md` — superseded by Ship G's framing, kept for component reference.

Three FIX briefs exist on disk in `docs/architecture/` but are untracked in git (verified May 19, 2026 by direct file inspection): `FIX_1_AIRBNB_DETERMINISTIC_FIRST.md` (7KB), `FIX_2_INQUIRY_REGRESSION_CORPUS.md` (14KB), `FIX_3_DAILY_BINDING_REPORT.md` (14KB). There is also a `FIX_2_REGRESSION_CORPUS.md` (0.5KB) self-marked-superseded tombstone that should be deleted, not committed. An earlier note in this resume incorrectly said these files weren't on disk — that note was based on a false-negative `search_files` result and has been corrected. Captured-but-secondary; none block any other ship.

---

## Phase 1 backend work, ready to start

From the audit, the four concrete backend jobs:

1. **Inquiry-to-booking attribution** as a first-class linkage. The longest pole. Trust-ranked matching: PMS reservation ID → guest email/phone → property+dates+name → OTA reservation identifiers.
2. **Normalize inquiry signals** into the canonical `InquirySignals` shape described in the foundation doc.
3. **Audit and unify server-side capability enforcement.** Starting target: the pre-booking draft action path in `operator_onboarding.py` which checks tenant access but not scoped capability.
4. **Do not rebuild** what already exists: PMS sync, guest-session creation from bookings, scope metadata.

These can run in parallel with the frontend Ship G. Mostly Codex's domain.

---

## Key code paths

Verified files, not from memory:

- `/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard/index.html` (114KB, contains `view-prebooking` and all other view markup)
- `/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard/js/sections/messages.js` (71KB — owns Pre-Booking queue, drill-in, action wiring, polling. Up from 53KB pre-Ship-F.)
- `/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard/js/sections/today.js` (renamed from overview.js)
- `/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard/js/sections/shell.js` (nav, banner, detail panel host)
- `/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard/js/sections/knowledge.js` (15KB — will host gap-inquiry section per Ship G)
- `/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard/js/api.js` (Pre-Booking API wrapper; the query-string filter at the messages.list builder is a suspect for the unbound-only bug)
- `/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard/styles/dashboard.css`
- `/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator_prebooking.py` (77KB — `/app/api/messages` lives here; echoes `unbound_only` in response)
- `/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator_onboarding.py` (action enforcement gap)
- `/Users/dhuntermckenzie/Downloads/oyvoda/app/services/operator/prebooking_queue_service.py` (read-model for queue rows)
- `/Users/dhuntermckenzie/Downloads/oyvoda/app/services/operator/scope_service.py` (real RBAC scope filtering)

---

## Operator context

- **First operator:** Beach Habitats 30A, tenant `e07980b2-a990-4b24-91d1-c8cb71ab70e1`, 43+ properties at oyvoda.com. Primary user: "Lanier," a lawyer. Smart, articulate, has been giving sharp feedback that has pushed several design corrections through this arc.
- **Deploy:** Railway, Cloudflare CDN, Supabase backend, GitHub `huntermckenzie/oyvoda`.
- **Hunter is the sole developer.** Uses Claude for architecture/review in chat, Codex CLI for implementation. Strong session discipline — commits docs in isolation, structured resume lines.

---

## How to resume cleanly

1. **Read `SHIP_G_PREBOOKING_CORRECTNESS.md` end to end.** It's tight and current.
2. **Verify `view-prebooking` in `index.html` still contains the three-pane grid** before doing anything. If it's already been deleted, the brief may have started executing without my visibility — sync with Hunter on status.
3. **Codex runs the unbound-only diagnostic first.** Fills in the Investigation Findings section of the brief before any code.
4. **Execute Ship G in the order listed in the brief.** Investigation → grid deletion → email row → popout → inline edit → knowledge routing → signal cleanup → unbound fix → contrast verify → smoke → push.
5. **Verification pattern:** Codex commits locally first, hands back for a diff-and-read pass, then pushes after sign-off. Same pattern as Ships A-F.

---

## What I (Claude) got wrong this round, for the next session's awareness

- I wrote multiple briefs assuming the popout pattern existed in Ship F when it did not. The fix was structural deletion of the three-pane grid in `index.html`, which I never verified had landed. Briefs written from memory of intent rather than from code state.
- I packed too much into single ship briefs trying to "make it correct in one pass." Smaller, faster ships with clear acceptance criteria would have surfaced the gap earlier.
- I called for an "audit" repeatedly but didn't actually do the audit — I'd describe what I thought the audit would show. The current Ship G brief is the first one written from a real read of `index.html`.
- The unbound-only bug ate three rounds because I kept patching guessed causes. The current Ship G brief blocks the fix on a documented diagnostic.

**Discipline correction for the next session:** before writing any brief that references "the current state of X," read X first. `view`/`read_text_file` on the actual file, not memory. Confirm what exists before prescribing what to change.

---

*End of resume file.*
