# Oyvoda Frontend — Single-System Migration Discipline

## The decision (locked)

dashboard-v2 standardizes on **ONE** styling system: **Tailwind + shadcn-style
components against the existing CSS-variable token layer.** The hand-written
2,200-line `styles.css` is being **retired**, not extended.

This is a non-negotiable founder requirement: **no dual-layered system.** The
backend was bitten by entangled, coexisting approaches; the frontend will not
repeat it. A bounded migration with a finish line is acceptable; permanent
coexistence is not.

## Why this direction (the short version)

You ALREADY have both systems present:
- GOOD: `components/ui/` (button, input, select, switch, slider, checkbox,
  textarea) is real Tailwind+shadcn — `cva` variants, `cn()` merge, Radix `Slot`,
  Tailwind classes reading tokens (`bg-accent`, `text-primary`, `ring-focus`).
  This is the target. It works today.
- LEGACY: `styles.css`, ~2,200 lines of unscoped global CSS that the route
  surfaces mostly use. This is what produced orphaned dead CSS (`.detail-rail`
  family, `*-DEPRECATED-DO-NOT-USE`, the no-op `.app-frame-focused`).

Standardizing = adopt the good layer everywhere, delete the legacy file as we go.
The token layer (`--surface-*`, `--accent-*`, `--text-*`, status tones, dark mode
via `[data-theme="dark"]`) is KEPT — Tailwind already reads it (see
`tailwind.config.cjs` `theme.extend.colors` mapping every token to a utility).
Tokens are the shared foundation both systems use; they are not "the legacy system."

## The rules (read every session)

1. **The stylesheet only ever SHRINKS.** Every commit that converts a surface
   DELETES the legacy CSS it replaces, in the SAME commit. Net lines of
   `styles.css` must go down, never up. No "I'll clean it later."

2. **No new global CSS classes.** New styling lives in Tailwind utilities on the
   component, or as a new `components/ui/` primitive when it's a reusable control.
   If you reach for `styles.css`, stop — that's the system being retired.

3. **New surfaces are born native.** Home, ReviewDrawer, Escalations, the learning
   review surface — all built in Tailwind+shadcn from line one. They never touch
   `styles.css`.

4. **Tokens stay; chrome moves.** Keep using `bg-accent`, `text-primary`, etc.
   (Tailwind utilities mapped to the CSS variables). Do NOT hardcode hex values in
   components. The `:root` token block in `styles.css` is the ONE part that stays
   until the very end.

5. **`preflight: false` is the tombstone.** Tailwind's base reset is currently
   disabled because the hand-CSS owns the base layer. Re-enabling
   `preflight: true` is the LITERAL LAST STEP — it means the legacy base layer is
   gone. Until then it stays false. When it flips, the migration is done.

6. **CSS Modules are a NARROW escape hatch, not a third system.** A `*.module.css`
   file is permitted ONLY for structural layout behavior Tailwind genuinely cannot
   express — stateful parent-grid transitions, `:has()`-style parent-state layout,
   container-driven geometry. NEVER for colors, spacing, typography, borders, or
   anything a token utility already covers. Every CSS Module class requires a
   one-line comment stating which Tailwind limitation forced it. The bar is
   "Tailwind genuinely cannot do this," not "this was easier in CSS."

## Conversion order

The order is chosen so shared shell/primitives convert first (everything depends on
them), then high-traffic surfaces, then the long tail.

1. **`ListDetailSurface` primitive + PreBooking detail** ✅ `770dd65` / `95c921f`
   Converts the detail-pane pattern four surfaces will reuse.
   Deleted: `.detail-rail`/`.detail-card` family, `.queue-card-expanded` family.

2. **App shell + sidebar** ✅ `b1aa6c3`
   Deleted: `.app-shell`, `.app-sidebar`, all sidebar/topbar/chrome families.
   First CSS Module: `Shell.module.css` (grid-template-columns transition + 860px
   breakpoint). Governed use — structural-only, 20 lines, justified.

3. **ReviewDrawer** ✅ `9784b5a`
   Net-new, born native. Formalizes PreBooking detail into reusable drawer.

4. **Home** ✅ `e9952c0`
   Net-new, born native. No styles.css changes.

5. **Escalations** ✅ `3776ffc`
   Net-new, born native. Proves ReviewDrawer optional-region contract.

6. **Brief A — SurfaceControls / SurfaceHeader / SurfaceTabs** ✅ `9aa067e`
   Shared chrome primitives → Tailwind.
   Deleted: `surface-controls`, `tab-strip`, `tab-list`, `tab-pill` (+variants),
   `tab-count` (+variants). styles.css: 55,155 → 53,357 bytes.

7. **Brief B-technical — PreBooking chrome** ✅ `9aa067e`
   filter-bar/search/input/group/select, metric-strip/chip → Tailwind in
   PreBookingControls.tsx. surface-column, surface-status → Tailwind in
   PreBookingRoute.tsx. SurfaceHeader: summaryLine prop added.
   Deleted: `surface-status` (sole consumer). Retained (shared consumers remain):
   filter-*, metric-*, surface-column, surface-summary-line.
   styles.css: 53,357 → 52,801 bytes.

8. **Brief B-product — PreBooking work-queue reframe** ⬜ next
   Product language + UX changes separated from the technical chrome brick.

9. **Inline-header consolidation sweep** ⬜ deferred
   Router.tsx, Home/HomeRoute.tsx, Today/index.tsx, Properties/PropertiesRoute.tsx,
   Components/index.tsx all hardcode `surface-header` markup directly instead of
   using the SurfaceHeader component. These block deletion of the surface-header*
   family. Fix: extend SurfaceHeader props to cover each inline variant, then
   sweep all call sites. Deletes: surface-header, surface-header-copy,
   surface-kicker, surface-title, surface-subtitle, surface-header-controls.

10. **Today/Properties/Knowledge/Settings/Vendors chrome** ⬜ long tail
    Deletes their respective filter-*/metric-* (shared with PreBooking — already
    converted there), surface-column (8 consumers), plus surface-specific families.

11. **Finish line** ⬜
    `styles.css` reduced to `:root`/`[data-theme]` token blocks + minimal base.
    Move tokens to `tokens.css` or `@layer base`. Flip `preflight: true`. Done.

## Fragmented-header pattern (recorded — action deferred to step 9)

Brief A surfaced that `surface-header` is hardcoded inline in Router.tsx (loading
fallback), Home/HomeRoute.tsx, Today/index.tsx, Properties/PropertiesRoute.tsx,
and Components/index.tsx — NOT going through the SurfaceHeader component.
"Born-native" Home actually hand-rolled its header in legacy CSS rather than using
the converted primitive. This is two implementations of one thing, and it blocks
the surface-header* deletion. The fix is not blind replacement — check each inline
variant, extend SurfaceHeader props where needed (the `actions` prop already covers
`surface-header-controls`; the `summaryLine` prop added in Brief B covers
`surface-summary-line`), then sweep. One component flexible enough for every surface.

## Velocity note

Hunter chose foundation-correct over ship-fast-this-month. Conversion is done
properly per surface, not rushed. Feature work and migration are the SAME work —
building Home (a feature) IS a migration step. You are not pausing features to
migrate; the features ARE the migration, executed in the right system.

## Violation log

This log exists because a discipline that hides its own breaches is theater.

- **`38e344e` — Rule 2 violated.** Added `.queue-layout*` as new global classes.
  Root cause: original brief specified a legacy-system contract.
  **Corrected in `95c921f`.** Removed the block; ListDetailSurface now owns
  structural layout as conditional Tailwind utilities driven by `detailOpen` prop.
  **Lesson:** primitive-owns-structure pattern; callers pass no layout class strings.

- **`b1aa6c3` — first CSS Module, introduced deliberately within bounds (NOT a
  violation).** Shell conversion needed the hover/focus sidebar expansion
  (parent-grid transition) and 860px responsive override. `Shell.module.css`
  (20 lines) holds only `grid-template-columns` transition + breakpoint override.
  Also added `css-modules.d.ts` (type decl for `*.module.css`). This is Rule 6
  used correctly: scoped, structural-only, justified. The next CSS Module must
  clear the same bar. styles.css −12KB in same commit.
