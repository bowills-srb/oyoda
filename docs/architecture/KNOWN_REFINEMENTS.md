# Known Refinements

Small, captured-but-not-blocking items found during smoke passes, plus the **active sequence** at the top so any session resume knows where work stands. Not a bug tracker — this is for cosmetic and content-quality nits, plus deliberate captured-but-deferred design choices.

When a ship touches the relevant area, the executor should check this file for items that can be cleaned up "for free" as part of that ship's work.

---

## ACTIVE SEQUENCE (top of mind)

**Environment discipline must precede Ship S production rollout.** Local verification recently produced false-positive confidence because the development runtime could fall back from Supabase to `LOCAL_DATABASE_URL` when DNS resolution failed. That behavior is acceptable for developer convenience only in development. In any production-like runtime, database resolution must hard-fail rather than silently writing to a local database.

- Production/staging/Railway runtimes must never fall back to `LOCAL_DATABASE_URL`.
- Railway production should not carry `LOCAL_DATABASE_URL` at all.
- Startup logs must name the resolved database target so environment drift is visible immediately.
- Any Ship S production smoke should explicitly name the verification environment: production, staging, local container, or local fixtures.

**Operating principle (decided, still load-bearing):** Build the long-term operational interface. Make it short-term friendly through *proportions*, not through metaphor changes. The surface stays the same shape as an operator matures from day-one inbox user to month-two auto-mode veteran; what changes is which components dominate the visible space.

This supersedes an earlier framing in this document that proposed shelving the operations view in favor of an inbox-as-default surface. That framing was wrong. The corrected read:

- A new operator does behave like an inbox user on day one — reviewing drafts, editing in place, sending the good ones, fixing knowledge gaps. That behavior is real.
- But that doesn't mean the *surface* should be inbox-shaped. It means the surface should let the queue take dominant space while the operator is still building trust.
- As the operator matures — trusts the AI, turns on auto-mode — the same surface re-proportions: queue shrinks, confidence/exception/analytics bands take more visual weight.
- Same operational shape throughout. The trust dial is the queue's size, controlled by the operator.

**Where things stand after Ship G (May 19, 2026):**

- Pre-Booking is now single-pane and email-shaped. The three-pane workspace that Ship D built is gone from the live surface; the queue *is* the surface. Detail lives in a row-anchored `?` popout. Inline Edit replaces the draft block with a textarea + Save/Cancel on the same row.
- Knowledge-gap inquiries route out of Pre-Booking entirely into a "Inquiries waiting on knowledge" section at the top of the Knowledge view, with a `Resolve in KB` button that pre-fills the existing `add-kb-modal`.
- `nb-gaps-kb` sidebar badge is a red-dot treatment when waiting inquiries exist.
- Confidence health band and Pre-Booking analytics band are both still present, in their compact above-/below-fold positions per the long-term shape.
- Code on disk is structurally verified by direct file reads. Empirical confirmation (browser smoke) is pending Railway restoration as of this update.

**Immediate next work, in order:**

1. **Empirical confirmation of Ship G** when Railway is back. Resume protocol is in `SESSION_RESUME_2026-05-19.md`. The unbound-only diagnostic is still the contingency path if AC #11 doesn't pass on fresh-session smoke.
2. **Phase 1 foundation work proceeds in parallel** (mostly backend, mostly Codex's domain):
   - Build inquiry-to-booking attribution as a first-class linkage (highest priority — the longest pole)
   - Normalize inquiry signals into a durable shape
   - Audit and unify server-side capability enforcement (starting with the pre-booking action gap identified in the verified audit)
3. **In-Stay surface design.** `view-sessions` exists in markup as the older Guest Sessions Command surface; the In-Stay-specific lifecycle view has not yet been shaped. When it gets a brief, see "Captured UX takeaways for non-Pre-Booking surfaces" below — several outside design ideas have been triaged for that surface.

---

## Scale-readiness constraints

### In-process SSE hub is single-instance only

**Observed during Ship S audit (May 21, 2026):** [`app/services/operator/realtime_hub.py`](app/services/operator/realtime_hub.py) keeps all subscriptions and replay state in process memory. That is acceptable for a single API instance and a single-operator rollout, but it does not propagate events across multiple Railway instances.

**Constraint:** If an inquiry mutation is processed on instance A while the operator's SSE stream is attached to instance B, the operator will miss the event entirely.

**Trigger for upgrade:** Before the API scales beyond one Railway instance, or before operator rollout broadens materially beyond the current Beach Habitats scope.

**Upgrade path:** Replace the in-process broadcaster with Redis pub/sub (preferred) or Postgres `LISTEN/NOTIFY`. The frontend `realtimeClient` abstraction should not need to change.

### Verification claims must name their environment

**Observed during Ship S audit (May 21, 2026):** unqualified "verified" language hid a meaningful difference between local container success, local fixture success, and production truth. DNS fallback plus missing production deployment made local verification look stronger than it was.

**Rule:** Every verification claim must explicitly state where it ran:

- production
- staging
- local container against production-backed services
- local fixtures / fallback data

Unqualified "verified" is too weak and should be treated as ambiguous.

---

## Long-term Pre-Booking shape (implemented in Ship G)

The operational Pre-Booking surface as it now exists, top to bottom — this is no longer aspirational; it's what's on disk pending empirical confirmation:

1. **Resolution-counts header.** Compact, one line. "16 of 18 resolved · 2 pending · 0 escalations · inbox last polled 3m ago." Honest status, no decoration. Reads from existing `dashboardSummary`.
2. **Confidence health band.** Compact form by default — one line of stats (sent avg confidence, held avg confidence, `correctHoldPct` if computable). Window selector (24h / 7d / 30d).
3. **The queue.** Dominant space. Default 25 rows. Operator-controlled depth via a control: 5 / 10 / 25 / all. Rows are email-shaped: metadata strip → guest message → `Draft` label + AI draft → Send/Edit inline.
4. **Row detail — `?` popout.** The only detail surface. Anchored to the row, dismisses on outside-click / Esc / button-toggle. Shows full guest message, channel, listing/dates, binding candidates if unbound, confidence, policy warnings, prior thread context. Does not show parser source, draft source, route outcome, vendor coverage, or work orders — those stay out of operator eyeline.
5. **Pre-Booking analytics band, below the fold.** Top recurring topics, top inquiry-generating properties, knowledge gap recurrence. When booking attribution lands (Phase 1), conversion-correlated topics join this band.

**Knowledge-gap exception group is now routed out of Pre-Booking entirely.** Earlier framings of this surface had a "knowledge-gap exception group" living inside Pre-Booking. Ship G moved that out to the Knowledge view per Hunter's principle that *"Pre-Booking should only contain work that is actually actionable as messaging work."* Knowledge work is knowledge work.

**Trust dial as the operator matures (unchanged):**

- **Week one:** Queue dominant (25 rows visible). Confidence band, analytics present but compact. Operator edits drafts in queue via inline Edit, sends the good ones, builds trust through doing the work.
- **Week three:** Operator shrinks queue to 10. Confidence band starts feeling meaningful as numbers accumulate. The Knowledge waiting-inquiries section becomes a frequent click.
- **Month two:** Operator toggles auto-mode on. Queue auto-collapses to 5 or to a "what was handled overnight" view. Confidence band takes dominant space. Operator is checking metrics, not triaging.

Same surface, different proportions, controlled by the operator's trust level. No metaphor switch. No separate "inbox mode" and "operations mode." One coherent surface that matures with the user.

---

## Captured UX takeaways for non-Pre-Booking surfaces

A Gemini-sourced design exploration on May 19, 2026, surfaced ideas that don't fit Pre-Booking (which is correctly minimalist after Ship G) but should be considered when each respective surface gets its brief. Captured here so they survive context loss.

### For In-Stay / Guest Sessions (`view-sessions`, future evolution)

- **Reservation-Centric, not Property-Centric.** A single property can have 4 simultaneous active guest threads at scale (in-stay, arriving in 3 days, future, recently departed). The UI must surface the reservation as the primary unit, not the property. The server-side architecture already does this; the UI must follow.
- **Lifecycle swimlanes within a property view.** When an operator opens a property at scale, they see the current in-stay reservation as the dominant card, with pre-arrival / post-stay cards subordinate. Visual treatment differentiates them (e.g., subtle green tint for in-stay, blue for future, gray for post-stay) so the operator can't accidentally send the next guest's door code to the current guest.
- **Intent grouping at the fleet level.** With 350 active stays, a flat list breaks down. Group at-a-glance by intent class (access, maintenance, housekeeping, general) so the operator can solve all 12 maintenance issues in one context block rather than 12 unrelated context switches.
- **The kill switch.** Per-thread "AI silenced for 30 minutes" with visible countdown. When a guest situation is mid-crisis, the operator needs to take over without the AI auto-drafting the next inbound message. Heavier-handed alternative — flipping the per-property AI Response Mode to Review — affects future guests too and is the wrong tool. (Variant of this captured separately below for Pre-Booking.)
- **Slash commands in the operator composer.** `/wifi`, `/checkin`, `/coordinates`, `/code` pull live PMS data into a manually-typed reply. Only useful for surfaces where the operator composes from scratch — not Pre-Booking, where the AI drafts.
- **Macro-action buttons triggered by AI parse.** Guest says "AC isn't working" → UI surfaces `[Dispatch Maintenance]`, `[Offer $50 Credit]`, `[Send AC Troubleshooting Guide]`. Blocked on the underlying ops integrations (vendor dispatch, credits API, document delivery) existing on the backend. Note for the In-Stay brief but don't try to build ahead of the integrations.

### For Today (cross-lifecycle dashboard)

- **The "Pulse" timeline.** Horizontal arrivals/departures strip for today across all properties. Clicking a departure dot jumps directly to that guest's thread to confirm the AI sent checkout instructions and the guest acknowledged. Today already has a lifecycle strip; this would be a denser timeline-shaped variant of it. Worth considering when Today gets its next pass.

### Explicitly rejected for the live operator surface

- **"Traffic Light" autonomy buckets in the sidebar (Green / Yellow / Red).** Reintroduces the noise Ship G removed. Green doesn't need UI because Green doesn't need a human; that's the point of autonomy. Today's "Needs you now" and "Patterns worth seeing" bands already surface Yellow and Red correctly.
- **The "Brain" / Dual-Pane Audit Trail in the live workspace.** Exposing the AI's reasoning chain (intent detection, API queries, applied policies, draft step) is exactly what Ship G stripped. Operators don't want to debug the AI's reasoning; they want to know "should I send this?" The audit trail belongs in the Audit Log view, which exists. Keep it there.
- **Sentiment dashboards as the primary surface.** Dribbble bait. Visually impressive, functionally low-density. The current Today bands carry the same information in less space.

---

## Captured deferred design choices

### Pre-Booking kill switch (deferred, post-Ship-G)

**Source:** Gemini-sourced design exploration on May 19, 2026, plus parallel concept needed for In-Stay.

**Idea:** Per-thread "AI silenced for N minutes" toggle on a Pre-Booking inquiry. Right now an operator can edit a draft, but there's no way to say "this conversation has gotten sensitive (chargeback threat, legal language, an irate guest about to escalate) — stop drafting for this guest until I tell you to." Without this, the next inbound message will get an auto-draft regardless of how the operator handled the previous one.

**Why deferred:** Ship G's surface is deliberately minimal and the kill switch would add per-row chrome. It also needs server-side state (a `pause_drafting_until` timestamp on the inquiry or conversation) that doesn't exist yet. Worth doing, not urgent.

**Fix surface (when picked up):**
- Backend: `pause_drafting_until` field on the conversation / inquiry record; pre-booking auto-send path skips drafting if the timestamp is in the future.
- UI: Compact control inside the `?` popout (not on the row itself) — "Pause AI on this thread for 30m / 1h / until I resume." Visible countdown when active. Auto-clears when expired.
- The per-property `AI Response Mode = Review` toggle in Properties stays as the heavier-hammer option for blanket behavior change; the kill switch is the per-conversation surgical option.

**Recommended priority:** After Ship G is empirically confirmed and pushed. Could land as part of a small Ship H polish pass alongside the Knowledge-badge-refresh-timing follow-up.

**Files involved (anticipated):**
- `app/services/operator/pre_booking_auto_send.py` (skip path when pause is active)
- A migration for the `pause_drafting_until` field
- `app/static/dashboard/js/sections/messages.js` (popout control + countdown render)

---

## Captured items from Ship D smoke (all folded into Ship G — tombstoned)

### Persisted "SHOWING UNBOUND ONLY" state on initial load

**Observed:** Ship D smoke pass. Pre-Booking initially came up filtered to unbound-only inquiries until "SHOW ALL" was clicked.

**Investigation needed:** `unboundOnly` is not in the persisted client preferences (only `mode`, `workView`, `scopeFilter` are saved). However, the state path `state.unboundOnly = !!data.unboundOnly` means the backend is reporting `unboundOnly: true` on a first-load request that should not have requested unbound-only. Either:
- The backend `/app/api/messages` endpoint is stamping `unboundOnly: true` based on session-recall state (server-side), or
- A client code path is somehow setting `state.unboundOnly = true` before the first fetch.

**Fix surface:** Resolve which side is misbehaving. Probably a 30-minute investigation:
1. Make a clean request to `/app/api/messages` with no query params and observe whether `unboundOnly: true` is in the response.
2. If yes → server-side; trace where the endpoint sets it and stop doing so for fresh sessions.
3. If no → client-side; trace where `state.unboundOnly` gets set before the first fetch.

**Files involved:**
- `app/api/v1/endpoints/operator_app.py` (or wherever `/app/api/messages` is defined)
- `app/static/dashboard/js/sections/messages.js`

**Recommended priority:** Fold into the next Pre-Booking ship. The operator's first impression is "the dashboard filtered things I didn't ask it to," which erodes trust.

---

### Signal band noise on long warning payloads

**Observed:** Ship D smoke pass. The permanent AI signal band above the draft becomes visually overwhelming when an inquiry has long policy warning text (e.g., adversarial-review payload). Each warning gets its own chip with `humanizeToken(flag)` as the value, and long values balloon the chip width and flood the middle pane.

**Cause:** `renderSignalBand()` in `messages.js` builds chips for `policyWarnings` and `policyFlags` with no length cap and no truncation. Short flags render fine; long flags wreck the layout.

**Fix surface:** Cap each chip value at ~40 characters with an ellipsis and a `title` attribute showing the full text on hover. One-line patch in the chip-construction step of `renderSignalBand()`.

A bigger fix (group multiple flags under a single "Warnings: N" expandable chip) is reasonable but is Ship K visual polish territory.

**Files involved:**
- `app/static/dashboard/js/sections/messages.js` (`renderSignalBand`)

**Recommended priority:** Fold into the next Pre-Booking ship.

---

### Parser source / draft source / route outcome should be removed from operator eyeline

**Observed:** Conversation after Ship D deploy. Hunter explicitly: "I don't think the parser and draft source need to be in the operator's eyeline, I don't think that information is relevant to them."

**Cause:** The signal band promoted these fields to a permanent compact strip above the draft because the data was there and the brief called for "all surfaced signals." But operators don't want to know which parser handled the message; they want to know whether the message is correct.

**Fix surface:** Remove `draftSource`, `parserSource`, `routeOutcome` from the chips list in `renderSignalBand()`. Keep `confidenceLabel`, `policyWarnings`, `policyFlags`. The removed fields stay available in the underlying data for engineering/support use, just not surfaced in the operator UI.

**Recommended priority:** Fold into the next Pre-Booking ship.

**Files involved:**
- `app/static/dashboard/js/sections/messages.js` (`renderSignalBand`)

---

## Setup Checklist hide-when-complete edge case (resolved)

**Resolved in commit `d84e925`.** Original Ship C smoke pass showed the Setup Checklist on Today even when "3 of 3 steps complete." First patch (`percent_complete === 100`) wasn't sufficient because the backend can report `percent_complete < 100` even with all steps done. Final fix uses three orthogonal OR conditions: `incompleteSteps.length === 0` OR `percent_complete === 100` OR `completed >= total`. Confirmed live for Lanier.

Keeping this entry as a record. No further action needed.

---

## Insight engine: raw Airbnb HTML appearing in insight body

**Observed:** Ship C smoke pass, Today → "Patterns worth seeing" band. An insight was rendered with raw HTML-looking content in its body — escaped (not executed), so safe, but visually noisy and operationally useless.

**Confirmed safe:** `renderTodayInsights()` in `today.js` passes both `title` and `body` through `escapeHtml()` before insertion. The HTML appears as literal text in the body (e.g. `&lt;div&gt;`), not as rendered markup. No XSS shape.

**Likely cause:** An `OperationalInsight` was constructed with `body` text that includes raw HTML from upstream content. The most likely path: `OperationalInsightEngine._run_gap_event_correlation` reads from a knowledge gap whose `question_text` was extracted from an Airbnb email body without HTML being stripped. Other candidate sources: pre-booking inquiry message bodies, gap detection outputs.

**Fix surface:** Either strip HTML in the insight constructor (defensive — handles any upstream source), or strip HTML at the gap-text extraction layer (root cause — stops the bad data at the boundary). Defensive strip is one line in the engine; root-cause strip requires identifying every gap-text producer.

**Recommended priority:** Defensive strip in `OperationalInsightEngine` when the engine gets its next pass. Not blocking. Good candidate for the same session that touches the insight engine for any other reason.

**Files involved:**
- `app/services/intelligence/insight_engine.py` (where the defensive strip would land)
- `app/static/dashboard/js/sections/today.js` (rendering is correct, no change needed)

---

## "Via direct" inbox activity label is generic

**Observed:** Ship B/C smoke pass, Operator Health and Today portfolio glance. The inbox activity status shows "Recent inquiry activity via direct" instead of a more specific provider label like "via vrbo" or "via airbnb."

**Cause:** The inbox-status reconciliation patch (commit chain after `233493a`) treats inbox as connected when recent inquiry activity exists with a configured inbox address. The "direct" label is the catch-all when no specific provider can be inferred from the inquiry source.

**Fix surface:** The provider inference happens in the inbox-resolution helper in `operator_dashboard_api.py`. When inquiries arrive via a specific OTA parser (vrbo, airbnb, etc.), the inquiry's `parser_used` or `source_provider` field already names the provider. Surfacing that in the resolver instead of defaulting to "direct" is small.

**Recommended priority:** Small targeted patch whenever someone is in `operator_dashboard_api.py`. Not blocking.

**Files involved:**
- `app/api/v1/endpoints/operator_dashboard_api.py` (resolver helper)
- Frontend rendering already handles whatever label the backend returns

---

## queue-v2 acceptance criteria are decoupled from production reality

**Observed:** Ship B smoke pass. The brief specified that `https://oyvoda.com/operator-dashboard#queue-v2` should still render the internal queue preview. In production, that URL resolves to the public "The Operator Experience" marketing page.

**Cause:** The internal preview lives in the legacy `frontend/dashboard/oyvoda-v10.jsx` tree, served via a different middleware path than what `oyvoda.com/operator-dashboard` resolves to publicly. The acceptance criterion checked a route that isn't reachable from the public domain.

**Fix surface:** Not a code bug — a verification-path mistake in the briefs. Future briefs should not use `/operator-dashboard#queue-v2` as a production acceptance criterion. Internal smoke checks for legacy preview routes should happen via direct Railway URL or internal hostname.

**Recommended priority:** Pattern correction for brief-writing. The legacy preview tree will be retired in Ship L regardless.

---

## Three captured FIX briefs (on disk, untracked in git)

**Status (May 19, 2026):** Three FIX briefs exist on disk in `docs/architecture/` but are untracked in git. Verified by direct file inspection.

- `docs/architecture/FIX_1_AIRBNB_DETERMINISTIC_FIRST.md` (7KB) — invert router carveout so Airbnb runs deterministic parser first. ~1 hour patch, saves LLM tokens.
- `docs/architecture/FIX_2_INQUIRY_REGRESSION_CORPUS.md` (14KB) — real Beach Habitats inquiry fixtures with mocked LLM. Zero LLM tokens.
- `docs/architecture/FIX_3_DAILY_BINDING_REPORT.md` (14KB) — cron emails daily binding stats. Zero LLM tokens.

`docs/architecture/FIX_2_REGRESSION_CORPUS.md` (0.5KB) is a self-marked-superseded tombstone to be `rm`'d.

**Note (May 19, 2026):** An earlier revision of this entry incorrectly claimed these files were NOT on disk, based on a false-negative `search_files` result. That correction has been reverted. The files are real and the original entry was substantively right.

**Recommended priority:** Captured-but-secondary. Worth `git add`'ing the three briefs (and `git rm`'ing the tombstone) so they stop being untracked. Worth executing whenever the parser pipeline gets attention. None block any other ship.

---

## `messages.js` module name doesn't match its surface

**Status:** Captured for Ship L (legacy retirement) cleanup. The module handles Pre-Booking only; other lifecycle phases live in `sessions.js`. Renaming to `prebooking.js` is a one-session cleanup that touches every import, `main.js` boot order, and the view-changed event handler. Not worth the risk surface during active surface evolution.

---

*This file should grow and shrink. Add items as smoke passes find them; remove items as they get addressed.*
