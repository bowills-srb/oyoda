# Brief — Motion Layer (Phase 5.2): the FEEL upgrade

For Claude Code. Build-ready. Read docs/architecture/FRONTEND_MIGRATION_DISCIPLINE.md
and the FEEL-vs-MOAT + FIN/PARLOA PARITY sections of OYVODA_MASTER_ROADMAP.md first.

This is the first ADDITIVE-CRAFT brick, not a migration. It adds the motion/transition
vocabulary that separates "comparable architecture" from "comparable feel" (parity axis 2,
currently NOT STARTED). It is mostly execution — but it has ONE real structural decision
(desktop detail-pane exit), already DECIDED below as Option A.

## Available tools (verified against package.json)
- `@radix-ui/react-dialog@1.1.15` — HAS built-in presence: keeps content mounted through
  its close animation, exposes `data-[state=open]` / `data-[state=closed]` for CSS hooks.
- Tailwind 3.4 — use `transition-*`, `duration-*`, `ease-*`, `animate-*`, and
  `data-[state=open]:` / `data-[state=closed]:` variants. NO framer-motion, NO presence lib.
  Motion is CSS/Tailwind + Radix data-state. Do not add dependencies.
- Respect `prefers-reduced-motion`: gate non-essential motion with `motion-reduce:` (Tailwind
  variant) so reduced-motion users get instant, no transition. REQUIRED, not optional.

## THE STRUCTURAL FACT this brick must respect (read ListDetailSurface.tsx first)
The desktop detail pane is a CONDITIONAL RENDER (`detailOpen && !isMobile ? <div> : null`).
A conditional render can animate ENTER (mount then transition in) but CANNOT animate EXIT —
React unmounts instantly on `detailOpen=false`, leaving nothing to animate out. The mobile
path already has clean in/out because Radix Dialog manages mount-through-close-animation.

### DECIDED: Option A — symmetric in/out motion on BOTH breakpoints
Desktop must animate out too, matching mobile. Two ways; PREFER the first, fall back if it
fights the layout:

- **PREFERRED — unify on Radix presence:** render the desktop pane via Radix Dialog with
  `modal={false}` (non-modal: no focus trap, no overlay, no scroll-lock — it stays a
  side-by-side pane), so it inherits the SAME `data-[state=open]/closed` presence + exit
  timing as the mobile sheet. One presence mechanism for both breakpoints. VERIFY it composes
  into the existing flex split and does NOT break the desktop pane's current Escape handling /
  focus behavior before committing to it.
- **FALLBACK — presence hook:** if non-modal Dialog fights the flex layout, add a small
  presence pattern to ListDetailSurface: keep the pane rendered while animating out, unmount
  on `transitionend` (NOT a hardcoded setTimeout — listen for the actual transition end so it
  can't desync from the CSS duration). Keep it contained and commented.

EITHER way: ListDetailSurface is the SHARED primitive (PreBooking + Escalations + future
surfaces). Symmetric motion added here is inherited by all of them for free — which is the
point. But it's a careful change to a shared component: verify PreBooking AND Escalations
both still open/close/Escape correctly, desktop AND mobile, after the change.

DO NOT try to animate ACROSS the 1024px breakpoint swap (a resize from desktop↔mobile while
open). Leave that edge un-animated; it's not worth chasing.

## The motion vocabulary (define once, keep restrained)
Premium feel comes from RESTRAINT — fast, subtle, consistent. Not bouncy, not slow.
Target durations ~120–200ms, ease-out for enters, ease-in for exits. Define a small,
consistent set and reuse it; do not invent a different timing per surface.

1. **Detail pane (the hero motion):** slide+fade. Desktop: slide in from the right a few px +
   fade; reverse on close (via Option A). Mobile sheet: slide up from bottom + fade
   (`data-[state=open]:` / `data-[state=closed]:`), backdrop fades. This is the motion an
   operator notices first.
2. **Selection feedback:** the selected list row transitions its background/border
   (`transition-colors`) rather than snapping. Subtle.
3. **Count tick-downs / metric changes:** when a queue/metric count changes after an action
   (send/resolve), a brief, subtle transition — not a slot-machine animation, just enough that
   the number doesn't hard-cut. Keep it cheap; if it's fiddly, a quick fade on the value is fine.
4. **Row settle on send/reject/resolve:** when an item leaves the queue after an action, a
   brief fade/collapse rather than an instant disappear, so the operator sees the result land.
   (Respect that the data refetch drives the actual removal — the motion is a short exit on the
   leaving row, not a fake optimistic state.)
5. **Button press / in-flight feedback:** subtle press state + the existing in-flight spinners
   stay; just ensure transitions on hover/active are smooth (`transition-colors`/`transition`).

## ABSOLUTE scope guards
- NO new dependencies. CSS/Tailwind + Radix data-state only.
- NO behavior/logic/data change. Motion is purely presentational — it must not alter WHEN
  things mount/refetch/remove, only how that transition LOOKS. (Row exit animates the leaving
  row; it does not invent optimistic removal — the refetch still owns the data.)
- NO restructure of surfaces beyond the ListDetailSurface presence change required for Option A.
- `motion-reduce:` gating on non-essential motion is REQUIRED.
- styles.css: motion lives in Tailwind utilities / Radix data-state classes, NOT new global CSS.
  No styles.css growth. preflight false. No localStorage/sessionStorage.
- Keep it RESTRAINED. Over-animation reads as cheap, not expensive. If unsure, less.

## Done when
- Detail pane animates symmetrically in AND out on BOTH desktop and mobile (Option A), via the
  preferred Radix-presence approach or the documented fallback. Verified on PreBooking AND
  Escalations, both breakpoints.
- Selection, count changes, row-exit-on-action, and button states all carry restrained,
  consistent transitions from the shared vocabulary.
- `prefers-reduced-motion` users get instant/no motion (motion-reduce: applied).
- No behavior/logic/data change; no new deps; styles.css not larger; tsc clean; preflight false.
- Commit SHA recorded. Note in the commit which Option-A path (non-modal Radix vs presence hook)
  was used and why.
