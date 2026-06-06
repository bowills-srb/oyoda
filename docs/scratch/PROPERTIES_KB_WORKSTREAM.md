# Properties / KB Gap Operator Workflow — Remaining Work

**Status:** Workstream 1 + Workstream 2 SHIPPED (2026-05-28). Immediate criterion met; trailing 7-day criterion pending production observation. Workstream 3 (URL ingestion) still deferred. See "Shipped" and "Residuals" sections below.
**Replaces:** the prior "Properties v2 — commit A design" scratch doc (renamed and rewritten in place 2026-05-27, then renamed from `PROPERTIES_V2_DESIGN.md` to current filename for clarity)
**Pairs with:** `docs/PROPERTIES_V2_CONTRACT.md` (locked on `main` at 71ad3fa)
**Discipline:** `docs/architecture/MIGRATION_DISCIPLINE.md` — Principles 1, 3, 6
**Purpose:** anchor the next focused workstream after the 2026-05-27 brain pre-booking primary cutover. Properties + KB gap workflow is the highest-leverage post-cutover move because the brain only gets better as the KB gets better, and the new path now exercises Beach Habitats' KB on every inbound.

---

## What already shipped (Commit A, complete)

The original Commit A scope from the prior design doc landed cleanly on `main` ahead of this workstream. For the record so future readers don't redo it:

- v2 Properties route directory exists with all planned files:
  - `app/static/dashboard-v2/src/routes/Properties/PropertiesRoute.tsx`
  - `app/static/dashboard-v2/src/routes/Properties/PropertyExpansion.tsx`
  - `app/static/dashboard-v2/src/routes/Properties/DocumentUploadForm.tsx`
  - `app/static/dashboard-v2/src/routes/Properties/completeness.ts`
  - `app/static/dashboard-v2/src/routes/Properties/gapGrouping.ts`
  - `app/static/dashboard-v2/src/routes/Properties/types.ts`
  - `app/static/dashboard-v2/src/routes/Properties/index.tsx`
- Portfolio knowledge surface live (commit `7560540`)
- v0.1 polish shipped (commit `84b9969`): community filter, breakdown tooltips, gap dismiss, row alignment
- Properties contract locked (commit `71ad3fa` for `docs/PROPERTIES_V2_CONTRACT.md`)
- Shell top-bar moved (commit `9e4d93a`)

The Commit A design questions in the prior doc were all resolved during implementation. They don't need re-deciding here.

---

## Why this workstream is next

Three reasons, ranked by directness:

1. **Brain pre-booking primary just went live for Beach Habitats** (commit `0bb0e7b`, flag flipped 2026-05-27 23:26:23 UTC). Every Beach Habitats inbound now exercises property KB on the new brain path. If the KB has gaps the brain can't fill, operators see held drafts indefinitely until the gap is resolved.
2. **The brain only gets better as the KB gets better.** Phase 4 LLM instrumentation is shipping cost data. Phase 1 cutover is shipping draft quality. Neither compounds unless operators can easily see what the brain doesn't know and fix it.
3. **No other workstream has the same "compound the cutover" leverage.** Ship C Today and the admin cost dashboard both matter, but they don't directly improve brain quality. KB gap workflow does.

---

## Scope of this workstream

Three workstreams under one anchor, intended to ship sequentially. Each is independently committable. We do not bundle them.

### Workstream 1 — Properties v0.1.1 polish (small, fast)

Backlog items from the prior session that didn't make v0.1's polish pass. Each is a small, focused fix.

- **Tenant name dedup.** The top bar shows the company name. The sidebar brand shows the company name. Today both surfaces render it independently, sometimes with slightly different formatting. Pick one source of truth (likely the auth bootstrap response) and have both consume it.
- **Filtered empty state copy.** When a filter is applied and produces zero results, the empty state copy doesn't currently include the community/portfolio name that filtered it. Add the active filter into the empty-state copy so the operator sees "No properties match `Watercolor`" rather than just "No properties match".
- **`gapActionMessage` / `gapActionError` auto-clear.** When the operator dismisses or resolves a gap, the success/error toast renders but doesn't auto-clear. Operator has to manually dismiss it. Add a timeout-based auto-clear (5-7 seconds, configurable).
- **KB comment cleanup.** Codex left a local edit/comment in `app/api/v1/endpoints/operator_dashboard_api.py:603` from a prior session. Either remove it or convert to a real TODO with a tracking note. Don't let it sit untracked.

Verification:
- `npx tsc --noEmit -p app/static/dashboard-v2/tsconfig.json`
- Manual smoke: filter to a non-existent community, confirm empty state mentions the filter; dismiss a gap, confirm toast auto-clears

Rollback: `git revert <commit-sha>`. Frontend polish only, no schema or runtime changes.

Estimated size: one commit, ~half a session.

### Workstream 2 — KB gap operator workflow (the load-bearing piece)

The actual reason this workstream is the highest-leverage move. Properties v0.1 surfaces gaps client-grouped. What's NOT yet wired is the operator's path from "I see this gap" to "this gap is now resolved." Currently a gap surfaces, the operator sees it, but the resolution path is either:

- Add a KB note via the property expansion's note creator (works, but operator has to type the answer from memory)
- Upload a document via the property expansion's upload form (works, but operator has to find/prepare the doc)
- Dismiss the gap (works, but doesn't actually add knowledge — the brain will hit the same gap again on the next similar inquiry)

What's missing is a focused operator workflow that closes the loop. Specifically:

1. **Gap-anchored note creation.** When the operator clicks a specific gap (not just opens the property), the note creator should pre-fill the question with the gap text and place focus in the answer field. Reduces the operator's friction from "read gap, scroll to note creator, retype question, write answer, submit" to "click gap, write answer, submit."
2. **Gap-anchored document upload.** Same idea for upload: the upload form pre-tags the doc with the gap's category (house_manual, amenities, etc.) so the operator picks fewer fields.
3. **Gap resolution confirmation.** When a KB note or doc is added that should resolve a specific gap, mark that gap as `resolved` server-side. Currently the gap stays open until the gap retry runner re-checks. This is a UX latency problem more than a correctness problem — the brain will eventually pick up the new KB, but the operator's "did I fix it?" feedback loop is broken.
4. **"This is a gap the brain has hit recently" badge.** When a gap has `ask_count > 1` and a recent `last_asked_at`, surface that explicitly. Operators should prioritize "I've been asked this 5 times in the last week" over "this gap was once flagged a month ago."

Verification path for each piece:
- TypeScript compiles
- Manual smoke: open a real Beach Habitats gap, click into it, confirm pre-filled note creator → submit a real answer → confirm the gap disappears from the property's gap list within one refresh cycle
- Backend audit: confirm `kb_gaps` row transitions to `resolved` status when the matching note is created

Open question: does the existing `/app/api/kb-gaps/{id}/resolve` endpoint exist, or does this need a new backend route? Codex audits before writing frontend code.

Estimated size: two to three focused commits. Probably one session of solid work plus a verification window.

### Workstream 3 — URL ingestion (deferred unless explicitly chosen)

The prior design doc listed URL ingestion as "Commit B" — deferred from Commit A. It's still deferred. The reason: URL ingestion has its own design surface area (which URLs are safe to fetch, how to handle paywalls/auth, how to dedup against existing KB entries, how to attribute the source for grounding) and adding it now would split the operator workflow focus.

If we explicitly decide to take URL ingestion next, write a fresh anchor doc for it. Don't bundle it under this workstream.

---

## Decision criteria for "this workstream is done"

Workstreams 1 and 2 are done when both an immediate product criterion and a trailing brain-quality criterion are met.

**Immediate (workflow integrity):** ✅ MET (2026-05-28, verified at ship time)
- An operator can go from a surfaced property gap to a concrete fix action in one place, without leaving the workflow. Concretely: from the property expansion view, the operator clicks a gap, the resolution UI (note creator or upload form) is in the same view pre-anchored to that gap, the operator submits, the gap visibly resolves — no navigation away, no separate screens, no copy-paste, no manual gap dismissal.
- This is the load-bearing criterion. A workstream that achieves the trailing metric but fails this one isn't actually done — it just got lucky on volume. Workflow integrity is the thing the operator feels.
- **How it was met:** both fix paths are now gap-anchored and in-place. Note path (`9a0b661`): Resolve → inline answer field → `api.kbGaps.resolve` promotes to canonical KB scoped to the gap's property+category → held inquiries re-queued → confirmation with queued count. Document path (`89a5e55`): Upload doc → gap-anchored upload form with preset document type + gap-specific `source_label` → close-the-loop, with the gap auto-resolving ONLY when canonical ingest produced live knowledge (see Shipped section for why this distinction matters).

**Trailing (brain quality, 7 days):** ⏳ PENDING — not satisfiable until a production watch window elapses
- The brain audit query for Beach Habitats shows declining `confidence_source = gap_blocked` rate as KB gets filled in — **needs ~7 days of post-ship traffic; cannot be confirmed at ship time by definition.** Same shape as the Phase 1 cutover watch window.
- v0.1.1 polish items have all shipped and are visible on Beach Habitats' live dashboard — ✅ (Workstream 1, `9830e5b`)
- The discipline review checklist from `MIGRATION_DISCIPLINE.md` passes: no parallel surface introduced, no contract papered over with a bridge, audit-before-fix on any schema change, queryable truth maintained, hybrid states surfaced honestly — ✅ (the resolve flow routes entirely through the canonical `dashboard_kb_service`; resolution state is queryable truth via the `resolved` flag; the upload path surfaces the staged-vs-live hybrid state honestly)

The immediate criterion is verifiable the day Workstream 2 ships. The trailing criterion is the production-data confirmation that the workflow is actually being used and reducing gap-blocked drafts. Both matter; neither substitutes for the other.

---

## What this workstream is NOT

Explicit non-scope, same shape as the prior design doc:

- Not a redesign of the v2 Pre-Booking, In-Stay, or any other lifecycle view (Phase 1 cutover already shipped the brain-primary path; surface redesigns are separate ships)
- Not a backend refactor of `concierge_scoped_knowledge` or the KB schema (single canonical surface principle — don't touch it unless the trace shows a real bug)
- Not a rewrite of the gap retry runner or gap detection logic (`kb_gap_manager.py` and `kb_retry_handler.py` are real code paths; if they have bugs, that's a separate audit)
- Not Ship C Today (next workstream after this one, but not this one)
- Not the admin LLM cost breakdown dashboard (next workstream after Ship C, gated on having 7+ days of post-cutover data)
- Not URL ingestion (deferred, see Workstream 3 above)

If a change to one of those areas seems required mid-workstream, stop and write a fresh anchor doc. Don't drift.

---

## Tomorrow morning's prerequisite (10 minutes)

> **DONE (2026-05-28).** Both prerequisite queries ran clean against the tables directly (per the channel-mismatch audit, NOT through the queue service). Phase 1 verified healthy; Phase 2 broader expansion closed as not-needed. The section below is the original plan, kept as history.

Before starting Workstream 1, run the two post-cutover queries from `docs/MESSAGING_BRAIN_PREBOOKING_BEACH_HABITATS_ROLLOUT.md`:

1. **Post-flip `pre_booking_inquiries` query** — confirm new Beach Habitats inbounds since the flip have `draft_source = messaging_brain`, `status = pending_review`, non-zero `confidence`, and no `brain_exception` warnings.
2. **Post-cutover orphan audit query** — confirm `route_outcome = guest_session_routed` orphan rate has dropped following the `63e8040` reroute fix. This is the Phase 2 decision point: if orphan rate is clean, the broader contract expansion stays parked; if it's still high, that's the next workstream instead of this one.

If both queries come back clean:
- Update the rollout doc to mark Phase 1 verified
- Update `GUEST_SESSION_ORPHAN_FIX_PLAN.md` to close Phase 2's broader expansion as "not needed"
- Then proceed with this workstream

If either query reveals an issue:
- Investigate that issue first
- This workstream waits

---

## Sequencing recommendation

> **DONE (2026-05-28).** Followed as written: prerequisite check → W1 (`9830e5b`) → W2 (`9a0b661`, `89a5e55`). The queue channel fix (`ccfd1d9`) was inserted before W1 per the Path B re-rank recorded in `QUEUE_SOURCE_CHANNEL_MISMATCH.md`. Section kept as history.

1. **Tomorrow morning:** 10-minute prerequisite check (the two queries above)
2. **Then:** Workstream 1 (v0.1.1 polish) — small, fast, refamiliarizes you with the Properties code without touching anything risky
3. **Then:** Workstream 2 (KB gap operator workflow) — the load-bearing piece, takes a focused session
4. **Then stop on this workstream.** Move to Ship C Today as the next anchor doc.

Do not start Workstream 2 before Workstream 1 ships. Do not start the admin cost dashboard while Workstream 2 is in flight. One thing at a time.

---

## Shipped

Workstream 1 and Workstream 2 are live on `main`. The sequencing above (prerequisite check → W1 → W2) was followed as written; the prerequisite check came back clean (Phase 1 verified healthy against the tables directly, Phase 2 broader expansion closed as not-needed).

**Commits, in ship order:**
- `ccfd1d9` — queue channel fix (prerequisite-adjacent; see Residuals)
- `9830e5b` — Workstream 1 v0.1.1 polish (filtered empty-state copy, gap toast auto-clear, shared tenant workspaceLabel)
- `9a0b661` — Workstream 2 Commit 1: gap-anchored resolve workflow (note path) + ask-count prioritization + repeated-gap emphasis + queued-retry confirmation
- `89a5e55` — Workstream 2 Commit 2: gap-anchored document upload
- `13e9d23` — docs: close properties KB workstream checkpoint (this doc's first close)
- `7ad8813` — recency-aware gap prioritization (closed the `last_asked_at` residual; see below)

**Backend audit finding (recorded so it isn't re-derived):** the KB-gap backend was already complete and well-built before this workstream. `POST /app/api/kb-gaps/{gap_id}/resolve` already accepted `{add_to_kb, answer, notes, retry_topic}`, promoted answers to the KB via the canonical `dashboard_kb_service`, marked the gap resolved, re-queued held inquiries via `kb_post_save_retry_held_inquiries(...)`, and published realtime `kb.retry_progress` + `summary.updated`. `GET /kb-gaps` already aggregated `ask_count`. `api.kbGaps.{list,resolve,dismiss}` was already wired. So Workstream 2 was mostly frontend wiring against a correct backend — not the backend build the original plan anticipated as an open question.

**Key design decision — why "uploaded" does not always mean "resolved":** the document-upload path (`89a5e55`) auto-resolves the gap ONLY when the canonical ingest actually produced live knowledge the brain can use. When an upload merely STAGES knowledge for review, the gap stays open and the UI says so honestly. The rejected-but-easier alternative was to mark the gap resolved on upload success — that would lie to the operator whenever the document is still pending review, because the brain would keep hitting the same gap. Tying resolution to live knowledge rather than upload success keeps the gap's `resolved` state truthful to what the brain can act on (MIGRATION_DISCIPLINE Principles 4 and 6). A future reader who sees an uploaded doc with a still-open gap should understand this is intended behavior, not a bug.

**The retry count is "queued," not "completed."** `kb_post_save_retry_held_inquiries` returns `triggered_regeneration_count` — these are fire-and-forget `asyncio` tasks, not finished regenerations. The confirmation copy says "re-queued for the AI to retry," deliberately, to avoid implying the held inquiries are already resolved.

---

## Residuals (carried forward, not lost)

One known-incomplete item is deliberately left open. It does not block the workstream's completion; it is captured here so a future session doesn't mistake it for an oversight. A second item that was open at first checkpoint has since been closed and is recorded below for the trail.

1. **Queue `gmail_*` naming sweep is still deferred.** `ccfd1d9` fixed ONLY the live join channel literal (`source_channel = 'gmail'` → the canonical `'email'`). The broader `gmail_*` naming inconsistency in `prebooking_queue_service.py` (`_persist_rows`, `_load_cached_rows`, the read-model column names) and the open question of whether `mn.source_message_id = pbi.gmail_message_id` holds for non-Gmail ingest were NOT swept in. That work remains captured in `docs/scratch/QUEUE_SOURCE_CHANNEL_MISMATCH.md`, including the production queries needed to choose the safe fix shape. Not lost — parked with a written anchor.

### Closed since first checkpoint

- **`last_asked_at` recency — RESOLVED (`7ad8813`).** At the W1+W2 checkpoint, prioritization sorted by `ask_count` desc then `created_at` desc, approximating recency with first-occurrence time. The follow-up landed: `GET /kb-gaps` now returns `last_asked_at` as the most-recent observed ask across deduped duplicates (`operator_dashboard_api.py`), and the frontend sort + "last asked…" badge now use the true timestamp (`types.ts`, `PropertiesRoute.tsx`, `PropertyExpansion.tsx`). Verified with `py_compile` (backend) and `tsc --noEmit` (frontend). The recency half of the prioritization criterion is now exact, not approximate.

---

## Next (after this workstream)

This workstream is complete on the product side. The next anchors, in the order the sequencing above contemplated:

- **Queue naming sweep** (Residual 1) — has its own anchor doc; needs the production queries run first.
- **Ship C Today** — the next major surface, per the original post-W2 sequencing.
- **Admin LLM cost dashboard** — still gated on 7+ days of post-cutover data.

Write a fresh anchor doc for whichever is chosen. Do not reopen this one — it is a completed-workstream record now, not an active plan.
