# Today Surface — Scalability Work Item

**Status:** Captured, not scheduled. Step 4 does not depend on this.
**Owner:** Backend (Hunter).
**Trigger:** First tenant with >200 active sessions, or noticeable client-side
filtering lag during Today rendering.

## Why this exists

The Today surface in `dashboard-v2` currently uses a prototype data shape:

- Single fetch of `GET /app/api/sessions?include_archived=false&limit=200` on
  mount of `routes/Today/index.tsx`.
- Client-side classification via `shared/lifecycle/windows.ts::classifyForToday`
  to bucket sessions into `pre_arrival` / `in_stay` / `post_stay` /
  `out_of_window` using a 7-day window in each direction.
- Client-side filtering by property + search + per-tab focus chips, all
  against the in-memory 200-session slice.
- Tab counts and visible rows both derived from the same fetched set.

This shape ships the visibility prototype cheaply and gets the operator a
real lifecycle queue today. It is not the long-term model for tenants with
hundreds of concurrent stays. This document captures the contract and the
upgrade path so the eventual swap is mechanical instead of architectural.

## The three scaling pressures, in order of when they bite

### 1. Tab-count accuracy

The first thing that breaks at scale is the operator's mental model of "how
much is happening." A tenant with 50 in-stay sessions and 300 pre-arrival
sessions within the 7-day window cannot see accurate tab counts from a
200-session fetch.

The natural backend addition is a small summary endpoint that returns just
the counts the Today header and tabs need, honoring the window policy:

```
GET /app/api/sessions/today-summary
→ {
    "windows": {
      "pre_arrival_days": 7,
      "post_stay_days": 7
    },
    "buckets": {
      "pre_arrival": { "total": N, "focus": { "arriving_today": N, "needs_welcome": N, "unbound": N } },
      "in_stay":     { "total": N, "focus": { "escalations": N, "stuck_work_orders": N, "checkout_due": N } },
      "post_stay":   { "total": N, "focus": { "turnover_blocked": N, "review_window": N } }
    }
  }
```

The focus subcounts mirror the per-tab focus chips wired in step 4. Each
chip's number on the strip should come from this summary, not from
re-counting the in-memory list, because at scale the in-memory list won't
have everything the chip needs to count over.

The frontend already has the right seam to consume this: the `useMemo`
that computes `tabCounts` from `byBucket` is the swap point. Replace its
input from the local list with the summary payload.

### 2. Row rendering at scale

Visible rows scale with the active tab × current filters, not with the
full session set. The operator looking at the in-stay tab with property
filter `LANIER_001` does not need the 300 pre-arrival sessions in memory.

The natural shape is a paginated row fetch driven by the active tab:

```
GET /app/api/sessions?phase=in_stay
  &lifecycle_window_days=7
  &property_code=LANIER_001
  &focus=escalations
  &cursor=<opaque>
  &limit=50
→ { sessions: [...], next_cursor: "...", has_more: true }
```

Two specific additions to the existing endpoint:

- **`lifecycle_window_days`** — server-side enforcement of the same 7-day
  window the client currently enforces in `classifyForToday`. The client
  policy can stay (for in-flight fetches and offline-ish recovery) but the
  server applies the same bound so a request for `phase=pre_arrival` does
  not return sessions 30 days out.
- **`focus`** — server-side subcount filter matching the chip set.
  Implemented as a small switch over the same predicate logic the frontend
  uses today, so behavior is identical regardless of where the filter runs.

`cursor` + `next_cursor` give us a stable pagination contract that works
for both initial load and "load more." Limit stays bounded (50 is fine; 200
becomes the upper limit per request).

The frontend swap is: replace the single `api.sessions.list({...})` fetch
on mount with a tab-keyed fetch that re-runs when `activeTab` / `focus` /
`propertyFilter` changes. The classification, sort, and row rendering all
keep working as-is because they operate on the entries-of-the-active-tab
shape, which is what the paginated endpoint already returns.

### 3. Real-time updates

When step 5 wires SSE / real-time, the current "refetch the whole 200 on
every event" strategy becomes very expensive. The right pattern for SSE is
**patch by session ID**:

- SSE event arrives with `session_id` and an event type
  (`session.updated`, `escalation.opened`, `vendor.dispatched`, etc.)
- Client re-fetches just that session via `api.sessions.detail(id)` and
  merges it into the in-memory list keyed by `sessionId`
- Tab counts re-fetch the summary endpoint, not the full list

If sessions arrive that the client doesn't have yet (a brand-new check-in
opens an in-stay row that wasn't fetched), the merge inserts the session
into the right bucket via `classifyForToday` and a count refresh confirms
it. The active tab's row list re-renders.

If sessions leave (a stay archives), the patch removes them from local
state without a full refetch.

This patch-by-ID pattern works whether or not the row list is paginated;
it's strictly more important when it is. Premature SSE wiring would force
us to design this before we feel where the operator actually wants
real-time updates, which is why step 5 — not step 4 — is the right time.

## What ships now vs later

**Now (no work):** the prototype shape stays. `limit: 200` is documented
in the route as a known constraint, not an oversight.

**When triggered (separate backend commit):**
1. Add `GET /app/api/sessions/today-summary` with the shape above.
2. Add `lifecycle_window_days` and `focus` parameters to
   `GET /app/api/sessions`.
3. Add cursor-based pagination to the same endpoint.

Estimated effort: half a day for the summary endpoint, half a day for the
window/focus params, full day for cursor pagination including the read-model
adjustments. Total: ~2 days of focused backend work.

**Step 5 onward:** patch-by-ID SSE handlers in the frontend, consuming
`session.updated` and friends from the existing operator realtime hub.

## Sequencing relative to other backend work

This is **separate from** the `/sms/*` hardening item. Different files,
different invariants, different urgency. The SMS hardening is a security
issue and should land before any Today v1.5 proactive-send feature. The
Today scalability item is an operational scaling concern and should land
before Beach Habitats hits ~200 concurrent sessions or before a second
operator at similar scale onboards.

## Discipline note

The scope discipline that has held through steps 1–3 (and is held by
step 4) is: do not widen the backend surface until the frontend has a
concrete consumer for it. This document does not authorize any backend
work. It captures the contract so that **when** the trigger hits, the
implementation does not have to re-derive the why.

If a future session opens with "Today is slow, let's add pagination," the
right move is to open this doc, confirm the trigger conditions match, and
implement against the contract here. If the trigger is something this doc
didn't anticipate (e.g., a tenant with thousands of properties rather
than thousands of sessions), update this doc before writing code.
