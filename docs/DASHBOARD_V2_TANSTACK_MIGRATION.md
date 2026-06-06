# Dashboard V2 TanStack Migration

This document is the implementation contract for migrating `app/static/dashboard-v2/` from route-local server state to TanStack Query without rewriting the operator app.

## Scope

- Keep building on `app/static/dashboard-v2/`
- Preserve URL-driven view state via `useUrlState`
- Preserve local UI state in component `useState`
- Move network-backed state, cache freshness, refetches, and invalidation into TanStack Query

## Current Status

Completed in this migration pass:
- TanStack Query provider and shared query client are wired at app entry
- typed query keys exist under `src/lib/query/queryKeys.ts`
- typed request client exists at `src/api/client.ts`
- Pre-Booking domain types, API functions, normalizer, queries, and mutations live under `src/domain/prebooking/`
- auth and autonomy now have typed domain API/types modules
- Pre-Booking and the shell subscribe directly to TanStack cache instead of the old custom store
- app-level realtime bridge is mounted and refetches query-backed Pre-Booking data
- the legacy custom store files under `src/store/` have been removed
- Today domain types, API functions, normalizers, queries, and mutations live under `src/domain/today/`
- Today list, selected detail, selected actions, and selected thread timeline are query-backed
- Today action execution paths use typed TanStack mutations instead of route-local API wiring

## Local UI State vs Server State

Keep local:
- search input drafts before commit
- dialog, popover, and menu open state
- inline edit text before save
- keyboard focus and transient selection helpers
- URL state already managed by `useUrlState`

Move to TanStack Query:
- session payload
- autonomy payload
- pre-booking message feed
- today session lists, detail, actions, and thread timelines
- property roster, identity report, portfolios, gaps, assets, property KB
- knowledge entries, KB gaps, and AI guidance
- vendors and vendor categories
- settings, alert routing, team, scopes, and portfolios

## Current Route Mapping

### Pre-Booking

Current:
- custom bootstrap cache snapshot still lives in route
- session, autonomy, and pre-booking feed are now query-backed
- app-level realtime bridge replaces route-local SSE
- route still owns some bootstrap freshness/orchestration concerns

Migration target:
- queries: `auth.session`, `autonomy.current`, `prebooking.feed`
- mutations: inquiry approve/reject/edit/bind/send/regenerate
- realtime: invalidate pre-booking and autonomy keys
- remove bootstrap snapshot logic once initial-load UX is reworked around query cache

### Today

Current:
- route-local `useEffect` fetch for list + escalations
- per-session detail, action, and thread caches
- manual post-action refetch

Migration target:
- queries for list, detail, actions, thread timeline
- mutations for execute action, send update, request feedback, vendor dispatch
- replace local caches with keyed query data

Current status:
- list, open escalations, selected detail, selected actions, and selected thread timeline are now query-backed
- action execution, reassure, and request-feedback flows use typed mutation hooks
- remaining work is route decomposition and any additional today-specific realtime events the backend may expose later

### Properties

Current:
- load-all orchestration in route
- lazy property detail cache in component state
- full reload after KB gap resolution

Migration target:
- queries for roster, identity, portfolios, gaps
- detail queries for property KB and assets
- mutation invalidation for gap resolution and uploads

### Knowledge

Current:
- route-local tab switch loader
- `refreshTick` invalidation pattern

Migration target:
- tab-scoped queries for entries, gaps, guidance
- mutations for create/update/delete entry, resolve/dismiss gap, guidance save, KB test

### Vendors

Current:
- route-local bulk load
- `refreshTick` mutation reload

Migration target:
- queries for categories, vendor list, property metadata joins
- mutations invalidate list/category keys

### Settings

Current:
- tab-based branching loader
- `refreshTick` reload pattern
- nested scope fetches per team member

Migration target:
- tab-scoped queries for settings, alert routing, team, scopes, portfolios
- mutations invalidate only affected tabs

## Query Key Rules

- Use domain-first keys from `src/lib/query/queryKeys.ts`
- Do not call `api.*` directly from route components once a domain query module exists
- Prefer narrow invalidation over page-wide reloads
- Realtime should invalidate queries, not become a parallel state system

## Legacy Cleanup Targets

Delete when replacement is confirmed:
- `frontend/dashboard/oyvoda-v10.jsx`
- `frontend/dashboard/QueueReview.jsx`
- `frontend/demo/`
- `app/static/dashboard-v2/src/App.tsx` after stale imports are verified gone

Keep until feature parity is confirmed:
- `app/static/dashboard/`

## UI Standardization Boundary

This section is the current guardrail for ongoing `dashboard-v2` cleanup while the UI is still actively being designed.

### Standardized in `dashboard-v2`

These are now shared primitives or shared structural seams and should generally be reused instead of reimplemented:

- server-state boundary:
  - typed domain API + adapter/normalizer + TanStack Query flow
- shared system shells:
  - `SurfaceHeader`
  - `SurfaceControls`
  - `SurfaceTabs`
  - `SurfaceErrorState`
  - `InlineError`
  - `ErrorBoundary`
- shared UI controls:
  - `Button`
  - `Input`
  - `Select`
  - `Textarea`
  - `Checkbox`
  - `Switch`
  - `Slider`
- shared overlay infrastructure:
  - `useDismissibleLayer`
  - `AnchoredPanel`

### Intentionally Still Bespoke

These are still route-specific on purpose because they either only exist once today or their visual/interaction design is still evolving:

- `Properties` row/grid view toggle
- `Today` metric chips and focus-chip strip
- `Pre-Booking` metric chip strip
- native file input in `DocumentUploadForm`
- route-specific badges and status pills
- route-specific queue/list card layouts

The rule is:
- standardize repeated mechanics
- keep one-off visual language local until a second real consumer exists

### Safe Next Standardization Targets

These look repeated enough to be good future consolidation candidates:

- queue banner action chrome between `Today` and `Properties`
- repeated filter-bar wrappers around search + grouped selects
- repeated metric/toggle controls if a second surface adopts the same interaction shape
- `Badge` if and only if a second badge system emerges or its variants begin drifting

### Legacy Retirement Blockers

The repo-root `frontend/` directory is not safe to delete yet.

Current blockers:
- `scripts/build-dashboard.js` compiles `frontend/dashboard/oyvoda-v10.jsx`
- `scripts/build_dashboard.py` reads the same legacy source
- `app/api/v1/endpoints/_dashboard_bundle.py` and `_dashboard_html.py` still reference the legacy dashboard output
- `app/static/dashboard/shell.html` still documents the legacy compiled source
- multiple architecture docs still describe the old path as a live or recently retired reference surface

So the correct order is:
1. finish `dashboard-v2` replacement where needed
2. retire the legacy dashboard build/mount path explicitly
3. then delete `frontend/dashboard/`, `frontend/demo/`, and related legacy scripts/docs in one coordinated pass

## Recommended Migration Order

1. Pre-Booking
2. Today
3. Properties
4. Knowledge
5. Vendors
6. Settings
