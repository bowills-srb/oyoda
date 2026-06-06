# Brief — Keyboard Navigation (density tiering, part 1 of FEEL axis 3)

For Claude Code. Build-ready. Read docs/architecture/FRONTEND_MIGRATION_DISCIPLINE.md
and the FIN/PARLOA PARITY section (axis 3, density) of OYVODA_MASTER_ROADMAP.md first.

ADDITIVE-CRAFT brick (like motion), not a migration. Adds keyboard-first navigation to the
list surfaces — j/k to move, Enter to open, Escape to close. This is the highest-value piece
of density tiering: it's what makes a high-volume operator (clearing 73 items) feel the
product was built for them, and the shell already advertises keyboard shortcuts
(KeyboardHint) that the surfaces don't yet honor — so it also closes a small broken promise.

SCOPE NOTE: this brick is keyboard nav ONLY. NOT bulk-select (that implies bulk actions,
which is a trust/autonomy product decision — deferred until the autonomy model is settled).
NOT compact row mode (optional, separate, low value). Just keyboard nav.

## The shared seam (verified)
Every surface drives selection through `?selected=` via useUrlState (shared), with
{ replace: true }. BUT each surface computes its OWN ordered visible list
(PreBooking visibleEntries, Today visibleEntries per bucket, Escalations its sorted list,
Properties visibleProperties) with surface-specific filtering/sorting. So the ordered list
of "what's selectable and in what order" is per-surface; the selection param is shared.

Therefore: build a SHARED hook, fed per-surface data. Do NOT try to compute the list inside
the hook — the surface owns its ordering.

## Build: `useListKeyboardNav` (shared hook)
Location: shared/ (beside url-state). Contract:

```ts
useListKeyboardNav({
  itemIds: string[];          // the CURRENT visible/filtered ordered list (surface-supplied)
  selectedId: string;         // current ?selected= value ("" if none)
  onSelect: (id: string) => void;   // surface's open handler (sets ?selected=, replace:true)
  onClose: () => void;        // surface's close handler (clears ?selected=)
  enabled?: boolean;          // default true; surface can disable (e.g. modal open)
}): void
```

Behavior:
- **j / ArrowDown**: move selection to next id in itemIds. If none selected, select first.
- **k / ArrowUp**: move to previous. If none selected, select first.
- **Enter**: if an item is focused-but-not-open, open it (onSelect). (On surfaces where j/k
  already opens via ?selected=, Enter is a no-op or re-affirms — keep consistent per surface.)
- **Escape**: onClose (coordinate with existing Escape handlers — see below).
- Movement respects ONLY itemIds (the filtered/visible list), never a full unfiltered list.
- At the ends: STOP (don't wrap) — wrapping disorients in long queues. Consistent across surfaces.

## The edge cases that make or break it (REQUIRED)
1. **Focus-in-input guard:** j/k/Enter must NOT fire while the operator is typing in the search
   box, a filter select, or an edit textarea. Check document.activeElement / event.target tag
   (INPUT, TEXTAREA, SELECT, contenteditable) and bail. Without this, typing "jk" in search moves
   the queue — feels broken.
2. **Escape coordination:** surfaces ALREADY have Escape handlers (close selection). Don't
   double-bind or fight them. Either route the existing Escape through the hook, or have the hook
   not bind Escape where the surface already does — pick one, be consistent, no double-close.
3. **Selection visibility:** when j/k moves selection, the newly-selected row must scroll into
   view if off-screen (scrollIntoView with block:nearest). A selection you can't see is useless
   in a 73-item queue.
4. **enabled gating:** when a modal/sheet is open (e.g. Properties grid modal, mobile sheet),
   the hook should be disabled or its keys scoped so they don't move the underlying list behind
   the modal.
5. **prefers-reduced-motion:** scrollIntoView behavior should be "auto" (instant) under reduced
   motion, "smooth" otherwise.

## Roll-out: prove on PreBooking first, then extend
1. Build the hook, wire it into PreBooking (Inquiry Operations) — the densest review loop, the
   proving ground. Verify all edge cases there.
2. Then wire into Escalations, Guest Operations (Today), Property Readiness (row view; grid view
   may stay mouse-driven or scope keys carefully around the modal).
Each surface supplies its own itemIds from its existing visible-list memo. No surface
re-implements the key handling — they all use the one hook.

## ABSOLUTE scope guards
- Keyboard nav ONLY. NO bulk-select, NO bulk actions, NO compact mode.
- NO change to selection logic, filtering, sorting, or data — the hook DRIVES the existing
  onSelect/onClose, it doesn't replace them.
- NO new dependencies. Plain DOM keydown + the existing handlers.
- Don't break existing mouse interaction or the existing Escape behavior.
- styles.css: a focus/selected ring may need a Tailwind class on rows if not already present —
  use existing token utilities, no new global CSS. preflight false. No localStorage/sessionStorage.

## Done when
- `useListKeyboardNav` exists in shared/, fed per-surface itemIds + handlers.
- PreBooking: j/k moves through the VISIBLE queue, Enter opens, Escape closes, selection scrolls
  into view, keys don't fire while typing in search/edit, no double-close. Verified.
- Extended to Escalations, Guest Operations, Property Readiness (row view) with the same hook.
- Existing mouse + Escape behavior intact on all surfaces.
- tsc --noEmit clean. styles.css not larger. preflight false.
- Commit SHA recorded. (Consider one commit for the hook+PreBooking, a second for the roll-out
  to other surfaces, so a regression is attributable.)
