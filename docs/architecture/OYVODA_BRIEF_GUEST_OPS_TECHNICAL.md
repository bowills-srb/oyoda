# Brief — Guest-Ops-Technical: migrate Today to Tailwind (NO product change)

For Claude Code. Build-ready. Read docs/architecture/FRONTEND_MIGRATION_DISCIPLINE.md
and docs/architecture/OYVODA_MASTER_ROADMAP.md first.

This is a MIGRATION brick, not a product brick. Tailwind conversion + legacy-CSS
deletion, behavior 100% preserved. The Today -> Guest Operations RENAME and any framing
is a SEPARATE later commit (Guest-Ops-Product). Different risk class; keep them apart so
a regression is attributable. This is also the LARGEST remaining migration win — Today is
the biggest legacy-CSS consumer, and converting it is what finally lets the shared
`filter-*`, `metric-*`, and `surface-header*` families delete.

## Architecture is ALREADY correct — do not redesign

Today is ALREADY session-first. The file header states it: rows are session objects
(guest + stay + property), messaging is one tool inside SessionExpansion, not the row's
identity. The four lifecycle tabs (pre_arrival / arriving / in_stay / post_stay), the
priority cards, the focus chips, the proactive indicators, the inline expansion — all
correct and shipped. DO NOT change the model. This brick MIGRATES the styling of a
correct surface; it does not redesign it.

## Files in scope

- routes/Today/index.tsx — chrome (surface-column, inline surface-header, filter-bar,
  metric-strip) + the row cards (queue-card family) + loading/empty/banner states.
- routes/Today/SessionExpansion.tsx — the expansion BLOCK styling (it already uses
  components/ui Button/Textarea; its block/layout classes are still legacy).

## Legacy families to convert -> Tailwind, then delete (grep-before-delete, Rule 1)

Today's own classes (Today is likely the last consumer — verify each, then DELETE):
- Row cards: `queue-card`, `queue-card-${tone}`, `queue-card-spine`, `queue-card-summary`,
  `queue-card-row`, `queue-card-identity`, `queue-card-property`, `queue-card-inline-meta`,
  `queue-card-age`, `queue-card-preview`, `is-selected`
- Preview lines: `queue-preview-line`, `queue-preview-tag`, `queue-preview-text`,
  `queue-preview-proactive`, `queue-preview-proactive-${tone}`, `queue-preview-priority`,
  `queue-preview-priority-${tone}`, `queue-preview-tag-${tone}`
- Queue shell: `queue-shell`, `queue-shell-head`, `queue-shell-tools`, `queue-meta`,
  `panel-title`, `queue-list`, `queue-empty`, `empty-illustration`, `empty-title`, `empty-copy`
- Skeletons: `queue-card-skeleton`, `queue-skeleton-heading`, `skeleton-line`,
  `skeleton-line-*`, `skeleton-chip`, `skeleton-chip-*`
- Banners: `queue-banner`, `queue-banner-warning`, `queue-banner-danger`,
  `queue-banner-copy`, `queue-banner-action`
- SessionExpansion block classes (read the file; convert its block/layout styling)

SHARED families — convert Today's USAGE, then DELETE ONLY IF Today was the last consumer
(grep each across the repo first; PreBooking already converted off these, so Today may now
BE the last consumer — if so, they finally die here):
- `filter-bar`, `filter-search`, `filter-input`, `filter-group`, `filter-select`
- `metric-strip`, `metric-chip`, `metric-chip-*`, `metric-chip-value`, `metric-chip-label`
- `surface-column`, `surface-summary-line`
- `surface-header*` — Today inlines this header. Convert Today's header to USE the
  SurfaceHeader component (it now has the summaryLine prop). If Today is the last inline
  consumer after this, the whole `surface-header*` family deletes — confirm via grep
  (Router fallback / Properties / Components may still inline it; if so, retain-with-note).

Record retained families + why in the COMMIT MESSAGE, not inline CSS (Rule 7).

## MUST-PRESERVE behaviors (the hard part — enumerate-and-verify)

1. Four lifecycle tabs + per-tab focus chips, with correct counts.
2. Tone semantics: `queue-card-${tone}` spine colors, proactive-indicator tones, priority
   tones -> convert to cn()-driven Tailwind keyed off the same tone values. Don't lose a tone.
3. Inline session expansion: selection, the Actions block, the four read-only blocks
   (timeline / work orders / conversation / cross-session history), stopPropagation on
   inner clicks, Escape-to-close.
4. Loading skeletons, empty states, and the auth/load failure banners (these have subtle
   logic — the banner suppresses the empty-state to avoid mis-narrating a fetch failure as
   "no guests"; preserve that).
5. Sort order within each bucket (escalations-first, etc.) — that's logic, don't touch it.
6. Action execution (executingKeys in-flight set, Reassure / Request feedback tools).

## "Share primitives, not rows" (stated rule — do NOT create a shared row)

Today's row represents a STAY SESSION; PreBooking's row represents an INQUIRY. They look
similar and will evolve differently. DO NOT factor a shared Row component. Convert Today's
row INLINE in Tailwind. Sharing is allowed ONLY for true primitives (badges, status chips,
indicators, buttons — already in components/ui and components/primitives). A SharedRow
becomes SharedRow + inquiry-exception + session-exception within months — forbidden here.

## Tokens + system

- Tailwind token utilities only; tone variants via cn() (same pattern as the converted
  PreBooking MetricChip and the shell tab state). Dark mode auto via [data-theme]; no hex.
- Use the existing components/ui + components/primitives; don't restyle those.

## ABSOLUTE scope guards

- NO product change: NO rename to "Guest Operations" (that's Guest-Ops-Product), NO new
  language, NO new metrics, NO autonomy framing. Labels stay "Today" this commit.
- NO model change, NO logic change, NO data-flow change. Styling only.
- NO shared row abstraction.
- preflight stays false. No localStorage/sessionStorage. No CSS Modules unless a genuine
  Tailwind-can't-express case appears (Rule 6 bar; the shell's :has() was the precedent —
  Today is unlikely to need one).

## Done when

- Today renders fully in Tailwind: chrome, row cards, preview lines, skeletons, banners,
  and SessionExpansion blocks.
- Today's own legacy families are DELETED; shared families DELETED if Today was last
  consumer, else RETAINED-with-note-in-commit-message. styles.css net SMALLER (this should
  be the biggest single drop yet).
- Today's header uses the SurfaceHeader component (not inline markup).
- ALL must-preserve behaviors verified across all four lifecycle tabs, light AND dark:
  tabs, focus chips, tone spines, expansion + its four blocks, skeletons, failure banners,
  action execution.
- tsc --noEmit clean. preflight false. Labels still say "Today".
- Commit SHA recorded; commit message lists any retained shared families and why.
