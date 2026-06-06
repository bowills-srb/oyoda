# Brief — Inline-Header Sweep: consolidate to SurfaceHeader, kill surface-header*

For Claude Code. Build-ready. Read docs/architecture/FRONTEND_MIGRATION_DISCIPLINE.md
and docs/architecture/OYVODA_MASTER_ROADMAP.md first.

MIGRATION brick. Mechanical. No product change. This is the consolidation the Brick A
finding flagged: multiple surfaces hand-roll inline `<header className="surface-header">`
markup instead of using the SurfaceHeader component. Routing them all through the
component lets the `surface-header*` family (and likely `surface-column`) finally delete.

## The consumers (verify with grep first)

Inline `surface-header*` markup remains in: Router.tsx (loading fallback), Home, Components,
Knowledge, Settings, Vendors. Grep `surface-header` and `surface-kicker` / `surface-title` /
`surface-subtitle` / `surface-header-copy` / `surface-header-controls` to get the exact
current set before editing — the list may have shifted as other bricks landed.

## What to do

For EACH inline-header consumer: replace the hand-rolled `<header className="surface-header">…`
block with the `<SurfaceHeader title=… subtitle=… kicker=… actions=… summaryLine=… />`
component. The component already exists, is Tailwind, and has these props (kicker, title,
subtitle, actions, summaryLine). Map the inline markup's content onto the props.

THE NUANCE (Brick A lesson — do NOT blind-replace): some inline headers may carry extra
structure the component's props don't cover (embedded controls/toolbars, like Properties
had). For each consumer:
- If it's header COPY only (title/kicker/subtitle/summaryLine) -> straight swap to SurfaceHeader.
- If it has embedded CONTROLS in surface-header-controls -> the controls move into a
  SurfaceControls block (as Properties did in 724866d), NOT crammed into SurfaceHeader.actions,
  UNLESS they're genuinely header-level actions (a single button), in which case `actions` is fine.
- If the component's props genuinely can't express something parametric -> EXTEND SurfaceHeader's
  props (add an optional prop) rather than keep a second header implementation. The goal is ONE
  header component flexible enough for every surface.

## Delete after the sweep (Rule 1, grep-before-delete)

Once NO inline `surface-header*` markup remains anywhere, DELETE the family from styles.css:
`surface-header`, `surface-header-copy`, `surface-kicker`, `surface-title`, `surface-subtitle`,
`surface-header-controls`, and any `surface-header*` responsive/dark rules. Also re-check
`surface-column`: if these same surfaces were its last consumers, it deletes too — grep to
confirm. Record what deleted vs retained in the COMMIT MESSAGE (Rule 7).

CAUTION: Router.tsx's inline header is a LOADING FALLBACK (renders before the route loads).
Make sure the SurfaceHeader swap there still renders correctly in the suspense/loading state —
it has no live data, so pass static strings. Verify the app still shows a sensible header
during route load.

## ABSOLUTE scope guards
- NO product change. NO renames. NO new metrics. NO layout redesign beyond the
  controls-into-SurfaceControls relocation where required (same authorized move as Properties).
- Behavior preserved on every touched surface: Home, Knowledge, Settings, Vendors, Components,
  and the Router loading state.
- This brick does NOT convert the Knowledge/Settings/Vendors BODIES (their `knowledge-*`,
  `settings-*`, `autonomy-*`, `filter-*` families stay for their own conversion bricks). It ONLY
  consolidates their HEADERS. Stay scoped to the header swap + surface-header*/surface-column deletion.
- preflight false. No localStorage/sessionStorage.

## Done when
- Every surface uses the SurfaceHeader component; NO inline `surface-header*` markup remains
  (grep returns nothing outside SurfaceHeader.tsx itself).
- `surface-header*` family DELETED from styles.css; `surface-column` deleted if now unused
  (else retained-with-note). styles.css net smaller.
- SurfaceHeader extended with any parametric prop a consumer genuinely needed (noted in commit).
- Home / Knowledge / Settings / Vendors / Components headers render correctly; Router loading
  fallback renders a sensible header. Light AND dark.
- tsc --noEmit clean. preflight false.
- Commit SHA recorded; commit message lists deleted vs retained families.
