# Brief — Property-Readiness-Technical: migrate Properties to Tailwind (NO product change)

For Claude Code. Build-ready. Read docs/architecture/FRONTEND_MIGRATION_DISCIPLINE.md
and docs/architecture/OYVODA_MASTER_ROADMAP.md first.

MIGRATION brick, separate commit from the later Property-Readiness-Product reframe.
Tailwind conversion + legacy-CSS deletion, behavior 100% preserved. This is the LARGEST
and most class-heavy surface remaining — bigger than Today. Do it carefully; it is not a
fast brick. The "can Oyvoda safely operate this property" reframe is the SEPARATE product
commit — NOT here. This commit changes styling only.

## Files in scope
- routes/Properties/PropertiesRoute.tsx — chrome (surface-column, inline surface-header,
  view-toggle, form-input/form-select, properties-metric-*), row view (property-table-*),
  grid view (property-card, property-grid), and the grid-view modal (property-detail-modal).
- routes/Properties/PropertyExpansion.tsx — the detail content (property-expansion-*,
  property-gap-entry-*, property-kb-entry-*, property-asset-entry-*, document-upload-context-*).
- routes/Properties/DocumentUploadForm.tsx — check it; convert its styling if it uses
  legacy classes (it's invoked from the expansion's upload section).

## Legacy families to convert -> Tailwind, then delete (grep-before-delete, Rule 1)
Properties-owned (likely sole consumer — verify each, then DELETE):
- Chrome: `view-toggle`, `view-toggle-option`, `view-toggle-active`, `form-input`,
  `form-select` (verify form-* not shared — if Knowledge/Settings/Vendors use them, RETAIN),
  `properties-metric-strip`, `properties-metric-chip`, `properties-metric-chip-*`,
  `properties-metric-note`
- Row view: `property-table`, `property-table-row`, `property-table-row-expanded`,
  `property-table-row-summary`, `property-table-row-identity`, `property-table-row-subtitle`,
  `property-table-row-tags`, `property-table-row-tag`, `property-table-row-coverage`,
  `property-table-row-count`, `property-table-row-divider`
- Completeness chip: `property-row-completeness`, `property-row-completeness-${label}`,
  `property-row-completeness-pct`, `property-row-completeness-label`
- Grid view: `property-grid`, `property-card`, `property-card-thumb`, `property-card-title`,
  `property-card-community`, `property-card-counts`
- Modal: `property-detail-modal`, `property-detail-modal-body`
- Expansion: ALL `property-expansion-*`, `property-gap-entry-*`, `property-kb-entry-*`,
  `property-asset-entry-*`, `document-upload-context-*` families (read the file; convert each)

SHARED (convert usage, DELETE only if Properties is last consumer — grep first):
- `surface-column`, `queue-banner` (the auth/load banners), `queue-empty`/`empty-title`/`empty-copy`
- `surface-header*` — Properties inlines this header. Convert it to USE the SurfaceHeader
  component. Properties' header has a view-toggle + search + 3 selects in surface-header-controls
  — those filter controls should move OUT of the header into a SurfaceControls block (matching
  how PreBooking/Today structure filters BELOW the header), NOT crammed into SurfaceHeader's
  actions. This is the one structural cleanup allowed here because it's required to use the
  shared header component cleanly. (Per the Brick A finding: blind-stuff-into-actions is wrong;
  relocate filters to SurfaceControls.)

Record retained families + why in the COMMIT MESSAGE, not inline CSS (Rule 7).

## MUST-PRESERVE behaviors (enumerate-and-verify — this surface is intricate)
1. **Two view modes**: row view AND grid view, toggled by the view-toggle. Both must work.
2. **Two detail render paths**: inline expansion (row view) AND the grid-view MODAL
   (property-detail-modal, role=dialog, click-outside-to-close). PropertyExpansion is reused
   in BOTH — preserve both paths. The modal's click-outside (event.target === currentTarget)
   and the inline expansion's behavior both stay.
3. **Filters**: search, portfolio, community, status — all filter identically. The completeness
   calculation feeding the status filter is logic; don't touch it.
4. **The completeness chip** with its tooltip + breakdown, tone-keyed by label
   (well-documented/has-gaps/bare-bones) -> cn()-driven Tailwind, don't lose a tone.
5. **The metric strip** (total/well-documented/has-gaps/bare-bones/tagged-gaps + the unbound-gaps note).
6. **The upload flow**: gap-anchored upload context banner, the collapse/expand of the upload
   section, the close-the-loop status messages (resolved/requeued/pendingReview), the 6s timeout.
   All logic — preserve exactly.
7. **Deep-links into Knowledge** (knowledgeEntriesHref/knowledgeGapsHref), gap sort by askCount,
   the deterministic grid-card hue hash — all logic, untouched.
8. Selection model (?selected= via useUrlState, Escape closes) — same as other surfaces.

## "Share primitives, not rows" — no shared row abstraction
Properties' row/card represents a PROPERTY; it is not PreBooking's inquiry or Today's session.
Convert inline. Share only true primitives (Badge, Button — already shared). No SharedRow.

## Tokens + system
- Tailwind token utilities only; tone variants via cn() (same pattern as converted surfaces).
  Dark mode auto via [data-theme]; no hex.
- The grid-card thumb uses a computed hsl() inline style for its deterministic hue — that's a
  data-driven dynamic value, KEEP it as an inline style (it's not a theming token; Rule applies
  to static colors, not computed per-item hues).

## ABSOLUTE scope guards
- NO product reframe: NO rename to "Property Readiness", NO "can AI safely operate" language,
  NO Automation-Ready/Needs-Coverage/Blocked row states, NO new metrics. Labels stay as-is.
  (That is ALL Property-Readiness-Product, the next commit.)
- NO autonomy backend, NO autonomy scoring. (describeAutonomy already exists from approvalMode —
  leave it exactly as-is; do not extend it.)
- NO model/logic/data change. Styling only (plus the one allowed structural move: relocating
  Properties' header filters into SurfaceControls to use the shared SurfaceHeader).
- preflight false. No localStorage/sessionStorage. CSS Module only if a genuine Tailwind-can't
  case appears (Rule 6 bar; unlikely here).

## Done when
- Properties renders fully in Tailwind: chrome, row view, grid view, the grid modal, the full
  PropertyExpansion (gaps/knowledge/assets/upload), and DocumentUploadForm.
- Properties' header uses SurfaceHeader; its filters live in a SurfaceControls block.
- Properties-owned families DELETED; shared families DELETED if Properties was last consumer,
  else RETAINED-with-note-in-commit-message. styles.css net smaller.
- ALL must-preserve behaviors verified: both view modes, BOTH detail paths (inline + modal),
  all four filters, completeness chip + tooltip, metric strip, the full upload/close-the-loop
  flow, Knowledge deep-links — light AND dark mode.
- tsc --noEmit clean. preflight false. Labels unchanged ("Properties", documentation framing).
- Commit SHA recorded; commit message lists retained shared families and why.
