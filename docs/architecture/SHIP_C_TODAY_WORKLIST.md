# Ship C — Today As Operator Worklist

**Status:** Brief for Codex execution
**Author:** Claude, written under Hunter's direction
**Date:** May 2026
**Parent docs:**
- `docs/architecture/COMMAND_MODULE_PROPOSAL.md`
- `docs/architecture/SHIP_A_FOUNDATIONS.md`
- `docs/architecture/SHIP_B_SHELL_AND_NAV.md`

---

## What this ship is

Replace the transitional Today surface with a real operator worklist — the first screen Lanier sees in the morning that answers a single question:

**"What should I look at right now?"**

Ship C is where the redesigned product starts feeling measurably better than the current dashboard, not just chromed differently. The transitional banner ("Today is being redesigned") goes away. The overview-content-under-Today fallback goes away. Today becomes a deliberately composed surface that pulls from existing services and arranges them around the operator's morning.

The four bands of the Today surface, in vertical order:

1. **Top: Active interrupts band.** Things requiring action right now: open escalations, urgent pre-booking drafts older than threshold, knowledge-gap-resolvable inquiries. Empty state is good news, not a bug.
2. **Insights cards.** The two highest-priority `OperationalInsight` items, rendered with action buttons that route to the right surface.
3. **Lifecycle strip.** Four counters — Pre-Booking / Pre-Arrival / In-Stay / Post-Stay — that show where guest attention is concentrated today. Each is a click-through to its lifecycle view.
4. **Portfolio glance.** A small row that gives the operator a one-glance read on portfolio health: properties active, sessions active, messages handled today, response cadence.

Below the fold: the operating posture, manager coverage, and retention cards that currently render on the transitional Today **move to Analytics**, where they belong. Today should not be the place a manager goes for cross-portfolio analysis. Today is for "what do I touch right now."

---

## What this ship is not

- Not a redesign of Pre-Booking, In-Stay, or any other lifecycle view. Those land in Ships D, F, G, J.
- Not a new API. Every data point on Today comes from endpoints that already exist.
- Not new insights logic. `OperationalInsightEngine` already runs daily and produces the four insight types we need. Ship C consumes them.
- Not a redesign of the existing overview cards (Operating Posture, Manager Coverage, Retention, Workstream Boundaries). They move to Analytics in this ship, but their internal markup and JS render functions are preserved as-is.
- Not multi-tenant scope-aware. Single tenant for now. The scope pill stays dormant.
- Not a real-time websocket surface. Today refreshes on navigation and on a manual refresh button, same cadence as everything else.

**Explicit scope guard:** Under no circumstances does Ship C:
- Modify `OperationalInsightEngine` or any service in `app/services/intelligence/`
- Modify the `/app/api/dashboard-summary` *route handler* (the service layer it calls gets one new aggregate column per deliverable 0; no new endpoint, no new query, no new table)
- Modify any other lifecycle view (Pre-Booking, In-Stay, Pre-Arrival, Post-Stay)
- Rewrite the cards being moved to Analytics — they relocate as-is
- Add new database tables, migrations, or columns
- Add new LLM calls

If a change to a service or API seems required, stop. That is a later ship, not Ship C.

---

## Verified repo reality this brief is anchored to

These services and endpoints already exist and are used by the current overview:

- `app/services/intelligence/insight_engine.py` — `OperationalInsightEngine.run_for_tenant()` returns `list[OperationalInsight]` with `insight_type`, `title`, `body`, `action_label`, `action_target`, `priority`. Consumed today by `loadInsights()` in `app/static/dashboard/js/sections/shell.js`.
- `app/api/v1/endpoints/operator_dashboard_api.py` — exposes `/app/api/dashboard-summary` returning the `dashboardSummary` shape (preBooking.pending, sessions.active, sessions.arriving, escalations.open, properties, messages30d, inbox.{...}, etc.).
- `/app/api/insights` — returns `{insights: OperationalInsight[]}`. Existing endpoint, no changes.
- `app/services/operator/dashboard_summary_service.py` — builds the dashboard summary including the inbox block fixed in the inbox-status reconciliation.

The transitional Today surface lives inside `<div id="view-today">` wrapping `<div id="view-overview">` in `app/static/dashboard/index.html`. Ship C restructures the inner content of `view-today` and migrates `view-overview` to live inside Analytics.

`app/static/dashboard/js/sections/overview.js` renders today via `loadDashboardSummary()`, `loadHealth()`, `loadMessagingObservability()`, `loadAudit()`, plus the four supplemental render functions (`renderOpsOverview`, `renderBoundaryOverview`, `renderManagerCoverage`, `renderRetentionOverview`). The first four functions stay tied to Today; the four supplemental render functions move to Analytics.

---

## Deliverables, file by file

### 0. `app/services/operator/dashboard_summary_service.py` — one-line extension

The pre-booking pending block in `_compute_live_summary()` already runs this SQL:

```sql
SELECT
    COUNT(*) FILTER (WHERE status = 'pending_review') AS pending,
    COUNT(*) FILTER (WHERE status = 'replied' AND received_at >= NOW() - INTERVAL '30 days') AS replied_30d,
    COUNT(*) FILTER (WHERE received_at >= NOW() - INTERVAL '30 days') AS total_30d
FROM pre_booking_inquiries
WHERE company_id = CAST(:tid AS uuid)
  AND archived_at IS NULL
```

Add one more aggregate column to that same query — no new SQL statement, no new table read:

```sql
EXTRACT(EPOCH FROM (NOW() - MIN(received_at) FILTER (WHERE status = 'pending_review'))) / 60 AS oldest_pending_age_minutes
```

In the `_fetchone_or` defaults dict for `pb_row`, add `"oldest_pending_age_minutes": 0`. In the return dict, add `"oldest_pending_age_minutes": int(pb_row["oldest_pending_age_minutes"] or 0)` to the `pre_booking` block.

Also update `default_dashboard_summary()` to include `"oldest_pending_age_minutes": 0` in the `pre_booking` block so degraded responses have the field.

Finally, update the adapter in `app/static/dashboard/js/adapters.js` (`normalizeDashboardSummary`) to surface this as `preBooking.oldestPendingAgeMinutes` on the frontend-facing shape — same naming convention as the other camelCase fields.

That's the entire backend change. One column added to one query that's already running. The cached-summary path will pick up the field automatically once `_persist_summary` writes a new summary on next refresh. No migration. No new endpoint.

---

### 1. `app/static/dashboard/index.html`

#### Restructure `view-today`

Replace the current contents of `<div id="view-today">` with the new four-band layout. The inner `<div id="view-overview">` is moved (cut, not copied) into Analytics — see deliverable 2 below.

The new `view-today` markup, in order:

**Page header (kept, refined).**

```html
<div class="page-header">
  <div class="page-title-group">
    <div class="page-eyebrow" id="today-greeting-eyebrow">Good morning</div>
    <div class="page-title" id="today-greeting">Today</div>
    <div class="page-sub" id="today-sub">Loading your morning briefing…</div>
  </div>
  <div class="page-actions">
    <button class="btn btn-primary" onclick="refreshToday()">↻ Refresh</button>
  </div>
</div>
```

Drop the `.today-transition-note` banner. The redesign is over for this surface.

**Band 1 — Active interrupts.**

```html
<div class="today-band today-interrupts" id="today-interrupts-band">
  <div class="today-band-header">
    <div class="today-band-label">Needs you now</div>
    <div class="today-band-meta" id="today-interrupts-meta">—</div>
  </div>
  <div class="today-interrupts-list" id="today-interrupts-list">
    <div class="empty-state">
      <div class="empty-state-title">Loading…</div>
    </div>
  </div>
</div>
```

Populated by JS (deliverable 3). When empty, shows a clean "All clear — nothing demanding attention right now" state in green, not gray. That's the desired morning state.

**Band 2 — Insights.**

```html
<div class="today-band today-insights" id="today-insights-band">
  <div class="today-band-header">
    <div class="today-band-label">Patterns worth seeing</div>
    <div class="today-band-meta" id="today-insights-meta">—</div>
  </div>
  <div class="today-insights-list" id="today-insights-list">
    <div class="empty-state">
      <div class="empty-state-title">Loading insights…</div>
    </div>
  </div>
</div>
```

Renders the top two `OperationalInsight` items from `/app/api/insights`. If none, shows "No new patterns detected yet — insights appear once your AI handles enough sessions."

**Band 3 — Lifecycle strip.**

```html
<div class="today-band today-lifecycle">
  <div class="today-band-header">
    <div class="today-band-label">Where guests are today</div>
  </div>
  <div class="today-lifecycle-strip">
    <button class="today-lifecycle-cell" onclick="navigate('prebooking')">
      <div class="today-lifecycle-label">Pre-Booking</div>
      <div class="today-lifecycle-value" id="today-lc-prebooking">—</div>
      <div class="today-lifecycle-sub" id="today-lc-prebooking-sub">pending review</div>
    </button>
    <button class="today-lifecycle-cell" onclick="navigate('prearrival')">
      <div class="today-lifecycle-label">Pre-Arrival</div>
      <div class="today-lifecycle-value" id="today-lc-prearrival">—</div>
      <div class="today-lifecycle-sub" id="today-lc-prearrival-sub">arriving soon</div>
    </button>
    <button class="today-lifecycle-cell" onclick="navigate('instay')">
      <div class="today-lifecycle-label">In-Stay</div>
      <div class="today-lifecycle-value" id="today-lc-instay">—</div>
      <div class="today-lifecycle-sub" id="today-lc-instay-sub">active now</div>
    </button>
    <button class="today-lifecycle-cell" onclick="navigate('poststay')">
      <div class="today-lifecycle-label">Post-Stay</div>
      <div class="today-lifecycle-value" id="today-lc-poststay">—</div>
      <div class="today-lifecycle-sub" id="today-lc-poststay-sub">follow-up</div>
    </button>
  </div>
</div>
```

The lifecycle cells are buttons (clickable), styled as plate-like cards that highlight on hover. Each routes to its lifecycle view.

**Important:** Pre-Arrival and Post-Stay counts come from `dashboardSummary` if available. If the underlying counts don't exist yet (the lifecycle phases aren't tracked separately in the current summary), the cells show `—` with the existing sub copy. Do NOT invent counts. Do NOT scrape sessions.js or filter session data to produce a count. If the data isn't in dashboardSummary, the cell renders `—`.

This matches the Ship B discipline: don't fake data.

**Band 4 — Portfolio glance.**

```html
<div class="today-band today-glance">
  <div class="today-band-header">
    <div class="today-band-label">Portfolio at a glance</div>
  </div>
  <div class="today-glance-row">
    <div class="today-glance-cell">
      <div class="today-glance-label">Properties</div>
      <div class="today-glance-value" id="today-glance-properties">—</div>
    </div>
    <div class="today-glance-cell">
      <div class="today-glance-label">Open escalations</div>
      <div class="today-glance-value red" id="today-glance-escalations">—</div>
    </div>
    <div class="today-glance-cell">
      <div class="today-glance-label">Messages handled (30d)</div>
      <div class="today-glance-value green" id="today-glance-messages">—</div>
    </div>
    <div class="today-glance-cell">
      <div class="today-glance-label">Inbox status</div>
      <div class="today-glance-value" id="today-glance-inbox">—</div>
    </div>
  </div>
</div>
```

#### Move overview cards to Analytics

The current Analytics view (`<div id="view-analytics">`) keeps its existing performance stat-grid and adds the four migrated cards from the transitional Today:

- Operating Posture (`ov-ops-card`)
- Workstream Boundaries (`ov-boundary-card`)
- Manager Coverage (`ov-manager-card`)
- Retention & Follow-Up (`ov-retention-card`)
- Operator Health table (the system status table — `#ov-sys-table` row container)
- PMS Integration and Active Channels cards
- SLO metrics card (`slo-card`)
- Insights card (`insights-card`) — this gets removed entirely because Today now hosts insights; do not duplicate

Cut the markup from `view-today` / `view-overview` and paste it into `view-analytics`, preserving IDs and class names exactly so the existing `overview.js` render functions keep working. Wrap them in a section header inside Analytics:

```html
<div class="analytics-section-header">
  <div class="analytics-section-title">Operating posture</div>
  <div class="analytics-section-sub">How the system is configured and how the team is covering it.</div>
</div>
```

Then the migrated cards, in two-column grid as they currently are.

**Setup Checklist (`onboarding-card`)** — stays on Today, not Analytics. Place it directly below the page header and above the Interrupts band, so a new operator sees their setup state before anything else. The existing `loadOnboardingStatus()` already controls visibility via `display: none`, so the card only appears when onboarding is genuinely incomplete. No JS change required — just keep the existing markup in `view-today` in this position.

Once onboarding is complete and the card hides itself, the Interrupts band moves up visually to take the dominant top-of-page slot. That's the intended progression: while a new operator is setting up, the checklist is the morning surface; after that, the worklist is.

### 2. `app/static/dashboard/js/sections/overview.js`

Rename to `today.js` for clarity. The file's responsibility shifts from "render the legacy overview" to "render the Today worklist."

Three new render functions, in addition to the existing `loadDashboardSummary` etc. which are kept but refactored to populate the new Today band IDs:

```javascript
async function renderTodayInterrupts() {
  const summary = state.get('dashboardSummary');
  const insights = state.get('operatorInsights') || [];
  const host = document.getElementById('today-interrupts-list');
  const meta = document.getElementById('today-interrupts-meta');
  if (!host) return;

  const items = [];

  // Open escalations are always interrupts
  const openEsc = Number(summary?.escalations?.open || 0);
  if (openEsc > 0) {
    items.push({
      kind: 'escalations',
      title: `${openEsc} open escalation${openEsc === 1 ? '' : 's'}`,
      body: 'Guest issues waiting on human attention.',
      action: 'Open Escalations',
      target: 'escalations',
      priority: 'high',
    });
  }

  // High-priority insights become interrupts
  const urgentInsights = insights.filter((i) => i.priority === 'high' && i.insight_type === 'service_risk');
  urgentInsights.forEach((ins) => {
    items.push({
      kind: 'service_risk',
      title: ins.title,
      body: ins.body,
      action: ins.action_label || 'Review',
      target: ins.action_target || 'escalations',
      priority: 'high',
    });
  });

  // Pre-booking becomes an interrupt under either of two conditions:
  //   (a) pending count >= INTERRUPT_PREBOOKING_THRESHOLD
  //   (b) oldest pending draft is older than INTERRUPT_PREBOOKING_AGE_HOURS
  // The OR catches the "small but stale" case: a queue of 2 drafts that have
  // been sitting for 4 hours is more urgent than a queue of 8 that just arrived.
  const INTERRUPT_PREBOOKING_THRESHOLD = 5;
  const INTERRUPT_PREBOOKING_AGE_HOURS = 2;
  const pbPending = Number(summary?.preBooking?.pending || 0);
  const pbOldestAgeMinutes = Number(summary?.preBooking?.oldestPendingAgeMinutes || 0);
  const pbStale = pbOldestAgeMinutes >= INTERRUPT_PREBOOKING_AGE_HOURS * 60;
  if (pbPending >= INTERRUPT_PREBOOKING_THRESHOLD || pbStale) {
    const titleText = pbStale && pbPending < INTERRUPT_PREBOOKING_THRESHOLD
      ? `${pbPending} pre-booking draft${pbPending === 1 ? '' : 's'} waiting over ${INTERRUPT_PREBOOKING_AGE_HOURS}h`
      : `${pbPending} pre-booking drafts pending review`;
    const bodyText = pbStale
      ? 'The oldest draft has been waiting longer than usual. Work through the queue before it grows.'
      : 'Several drafts are pending. Working through them keeps response time tight.';
    items.push({
      kind: 'prebooking_backlog',
      title: titleText,
      body: bodyText,
      action: 'Open Pre-Booking',
      target: 'prebooking',
      priority: pbStale ? 'high' : 'medium',
    });
  }

  // Update meta count
  if (meta) meta.textContent = items.length === 0 ? 'All clear' : `${items.length} item${items.length === 1 ? '' : 's'}`;

  if (items.length === 0) {
    host.innerHTML = `
      <div class="today-all-clear">
        <div class="today-all-clear-icon">✓</div>
        <div class="today-all-clear-title">All clear</div>
        <div class="today-all-clear-sub">Nothing demanding attention right now. Your AI is handling things.</div>
      </div>
    `;
    return;
  }

  host.innerHTML = items.map(renderInterruptCard).join('');
  host.querySelectorAll('[data-target]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const t = btn.getAttribute('data-target');
      if (t && window.navigate) window.navigate(t);
    });
  });
}
```

Then `renderTodayInsights()`, `renderTodayLifecycle()`, `renderTodayGlance()` follow the same pattern — pull from existing state, render to the new band IDs, no new fetches.

The existing `loadDashboardSummary()` is kept and extended to also populate the new Today IDs (`today-lc-prebooking`, `today-glance-properties`, etc.) alongside the legacy IDs (which now live in Analytics). The old IDs still need to be set so Analytics keeps working.

`refreshToday()` is the new entry point:

```javascript
export async function refreshToday() {
  await Promise.all([
    loadDashboardSummary(),
    loadInsights(),
    loadHealth(),
    loadMessagingObservability(),
  ]);
  renderTodayInterrupts();
  renderTodayInsights();
  renderTodayLifecycle();
  renderTodayGlance();
}
```

Exposed on `window.refreshToday`. The `refreshAll()` function is kept for Analytics. The view-changed event listener fires `refreshToday()` when `today` becomes active.

Time-of-day greeting in the eyebrow ("Good morning" / "Good afternoon" / "Good evening" based on operator's local time, with a fallback to "Hello" if locale is unknown). One small `setGreeting()` helper.

### 3. `app/static/dashboard/styles/dashboard.css`

Add styles for the new Today layout, using Ship A tokens. Specifically:

- `.today-band` — section wrapper with bottom margin
- `.today-band-header` — flex row with label + meta on opposite ends
- `.today-band-label` — uppercase eyebrow, JetBrains Mono, dim color
- `.today-band-meta` — small JetBrains Mono on the right
- `.today-interrupts-list` — vertical stack
- `.today-interrupt-card` — card with left-border priority color, action button on right
- `.today-all-clear` — centered, green, calm. Empty state is intentional and welcoming.
- `.today-insights-list` — vertical stack, similar to interrupts but lower visual weight
- `.today-lifecycle-strip` — four-column grid (responsive: two columns under 800px)
- `.today-lifecycle-cell` — large clickable cell, value in Cormorant Garamond serif at 32px
- `.today-glance-row` — four-column grid, smaller cells than lifecycle
- `.today-glance-cell` — flat, no borders, just label + value

Reuse existing `.btn`, `.badge`, `.empty-state` primitives from Ship A. Do not introduce new color tokens — semantic statuses (red/amber/green) come from existing tokens.

### 4. `app/static/dashboard/index.html` — Analytics section

Add the migrated cards under the existing Analytics page header. The Analytics view becomes:

1. Existing performance stat-grid (sessions, AI messages, pre-booking sent, escalations) — kept
2. **NEW section:** "Operating posture" with the four moved cards
3. **NEW section:** "System health" with the moved Operator Health table, PMS Integration, Active Channels, SLO metrics
4. Existing two-column grid (KB Health + Pre-Booking Performance) — kept

This is a move, not a rewrite. All IDs and class names stay identical so the existing JS render functions in `today.js` (formerly `overview.js`) populate them without modification.

### 5. `app/static/dashboard/js/router.js`

No router changes. `today` is already a registered view. The Today view DOM container (`view-today`) just has new internal markup; its visibility toggle stays the same.

The view-changed event listener in `shell.js` currently calls `loadOnboardingStatus()` and `loadInsights()` when Today becomes active. Update it to call `refreshToday()` instead, which already handles both.

---

## Acceptance criteria

Ship C is done when all of the following are true:

1. `/app/dashboard` opens with the new Today worklist as the home surface.
2. The transitional banner ("Today is being redesigned") is gone.
3. The four bands render in order: Interrupts, Insights, Lifecycle, Portfolio glance.
4. When there are zero open escalations and zero high-priority insights and pre-booking pending is below 5, the Interrupts band shows "All clear" in green.
5. When there is at least one open escalation, it appears in the Interrupts band with a working "Open Escalations" button that routes correctly.
6. The Lifecycle strip shows the four phases. Pre-Booking and In-Stay cells show real counts from `dashboardSummary`. Pre-Arrival and Post-Stay cells show `—` if no live count is available (no fake data).
7. When pre-booking is below the count threshold but the oldest pending draft is older than 2 hours, the Interrupts band shows a high-priority `prebooking_backlog` card with the "waiting over Xh" framing, not the count-based framing. Verifiable by manipulating fixture data.
8. Clicking any lifecycle cell navigates to its lifecycle view.
9. The Portfolio glance row shows properties, open escalations, messages handled, and inbox status — pulled from the existing `dashboardSummary`.
10. The Analytics page now contains the migrated cards (Operating Posture, Workstream Boundaries, Manager Coverage, Retention, Operator Health table, PMS Integration, Active Channels, SLO metrics) and renders them correctly.
11. Lanier's view shows the inbox-status reconciliation result correctly in the Portfolio glance band's "Inbox status" cell.
12. No console errors on `/app/dashboard`.
13. `/operator-dashboard#queue-v2` is unaffected (preserved per Ship A guarantee — note that this URL resolves to a marketing page in production; the smoke check is structural, not visual).
14. All other lifecycle views (Pre-Booking, In-Stay, Pre-Arrival stub, Post-Stay stub, Properties, Vendors, Knowledge, Escalations, Audit, Settings) still load with no regressions.

---

## Suggested implementation order

1. Move overview cards out of `view-today` and into `view-analytics` in `index.html`. Verify Analytics still renders before continuing.
2. Add the new Today band markup inside `view-today`.
3. Add CSS for the new Today layout.
4. Rename `overview.js` → `today.js`. Update imports in `main.js` if needed.
5. Add the four `renderToday*` functions and `refreshToday()` entry point.
6. Update view-changed listener to call `refreshToday()`.
7. Smoke test in dev before push.

---

## Smoke test checklist

After implementation, manually check:

- `/app/dashboard` loads with the new Today worklist
- The Interrupts band shows correctly populated cards or the "All clear" empty state
- The Insights band shows up to 2 insights, or its empty state
- The Lifecycle strip shows four cells, all clickable, all routing correctly
- The Portfolio glance shows properties, escalations, messages, and inbox status
- The "↻ Refresh" button works and re-fetches data
- Clicking through to Pre-Booking, In-Stay, Pre-Arrival, Post-Stay all work
- Analytics page renders all the migrated cards correctly
- Settings and Audit are unaffected
- The greeting eyebrow says the correct time of day
- No console errors

If any band fails to populate, the failure mode should be the band's empty-state copy, not a crashed page.

---

## What ships next

**Ship D — Pre-Booking redesigned in place.** This is the signature surface. Pre-Booking is what makes Lanier money. Ship D introduces the three-pane layout (queue / draft review / context detail rail), the AI signal indicators, and the work order / vendor context in the detail panel. The detail panel scaffold landed in Ship B; Ship D is where it finally gets used.

Ship D is also where the queue-v2 preview's design vocabulary actually lands in the canonical surface, retiring the v10 preview's reason for existing.

---

## Notes for the executor

- Do not call new APIs. Every data point on Today comes from `dashboardSummary`, `insights`, or constants. If a piece of data isn't available from an existing endpoint, the band shows `—` or its empty state. No new fetches.
- Preserve all existing IDs and class names when migrating cards to Analytics. The render functions in `today.js` (formerly `overview.js`) populate by ID — breaking those IDs will silently break Analytics.
- The "All clear" empty state for Interrupts is intentional and welcoming. Lanier should feel good when her morning briefing is empty, not feel like the dashboard is broken. Green checkmark, calm copy, no "loading" or "no data" framing.
- Time-of-day greeting uses the operator's local time if available via the existing operator state, otherwise falls back to UTC. Don't fetch a new timezone endpoint.
- The pre-booking interrupt fires on EITHER `pending >= INTERRUPT_PREBOOKING_THRESHOLD` (default 5) OR `oldestPendingAgeMinutes >= INTERRUPT_PREBOOKING_AGE_HOURS * 60` (default 2 hours). The age branch catches the "small but stale" case — a queue of 2 drafts sitting for 4 hours is more operationally urgent than a fresh queue of 8. Both thresholds are constants at the top of the function and easy to tune later.
- Pre-Arrival and Post-Stay lifecycle counts: if the data isn't there, the cell renders `—`. Do not filter sessions or invent counts. The brief is explicit: no fake data.

---

*End of Ship C brief.*
