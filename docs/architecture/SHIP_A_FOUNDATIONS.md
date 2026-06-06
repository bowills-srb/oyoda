# Ship A — Frontend Foundations

**Status:** Brief for Codex execution
**Author:** Claude, written under Hunter's direction
**Date:** May 2026
**Parent doc:** `docs/architecture/COMMAND_MODULE_PROPOSAL.md`

---

## What this ship is

Replace the visual foundation of the operator dashboard with the new design system. No section logic changes. No new pages. No new APIs. Every existing section module inherits the new look the moment the CSS deploys.

This ship locks in:

1. Design tokens (the single source of truth for colors, typography, spacing, motion)
2. Primitive component classes (the building blocks every section uses)
3. Shell rule definitions (three-column layout, contextual detail panel, topbar structure)
4. One canonical table-plus-detail-panel reference pattern (the pattern every list view will follow)

After this ship, subsequent ships (B, C, D, …) can rewrite individual section modules with confidence that the foundation is right.

---

## What this ship is not

- Not a section redesign. Section modules (`messages.js`, `properties.js`, `vendors.js`, etc.) stay as they are. They will look different because they consume the new tokens, but their JS does not get rewritten.
- Not a new shell. The existing topbar, sidebar, view containers in `app/static/dashboard/index.html` stay. They may need minor tweaks to align with the new tokens, but no structural rewrite.
- Not a router change.
- Not a new API surface.
- Not a JS framework migration. Vanilla JS continues. The existing `router.js`, `api.js`, `adapters.js`, `state.js` stay exactly as they are.

This is a CSS-and-shell ship. JS untouched.

**Explicit scope guard: under no circumstances does this ship modify section JS, the router, the API client, the adapters, or any state-management code.** If a change to one of those files seems necessary to make Ship A work, the answer is that Ship A is wrong, not that the JS needs to change. Stop, escalate, do not improvise. This is the kind of scope creep that turns a one-session ship into a multi-session debugging arc — it has happened before in this repo, and the brief is written to prevent it.

---

## Deliverables, file by file

### 1. `app/static/dashboard/styles/tokens.css`

Rewrite from scratch. The current file uses dark-mode tokens (navy, ink, amber on dark). Replace with the light-mode-first palette.

**Exact tokens to define** (copy verbatim into the file):

```css
:root {
  /* Surfaces */
  --surface-page:    #fafafa;
  --surface-raised:  #ffffff;
  --surface-sunken:  #f5f5f4;
  --surface-overlay: rgba(10,10,10,0.4);

  /* Borders */
  --border-default:  #e8e8e7;
  --border-strong:   #d4d4d3;
  --border-hairline: #f1f1f0;
  --border-focus:    #b8651a;

  /* Text */
  --text-primary:   #0a0a0a;
  --text-secondary: #525050;
  --text-tertiary:  #8a8888;
  --text-disabled:  #c4c2c1;
  --text-inverse:   #ffffff;

  /* Brand (used surgically) */
  --brand-50:  #faf0e6;
  --brand-100: #f0d4b0;
  --brand-500: #d4791e;
  --brand-600: #b8651a;
  --brand-700: #8a4a18;

  /* Status (semantic only — never decorative) */
  --success-50:  #ecfdf5;
  --success-600: #0a7d3e;
  --success-700: #065f2f;

  --warning-50:  #fff8e6;
  --warning-600: #b8650f;
  --warning-700: #8a4a0a;

  --danger-50:   #fef2f2;
  --danger-600:  #b91c1c;
  --danger-700:  #8a1414;

  --info-50:     #eff6ff;
  --info-600:    #1e5fb8;
  --info-700:    #164a8c;

  /* Typography */
  --font-sans:    'Inter', 'InterVariable', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
  --font-mono:    'JetBrains Mono', 'SF Mono', Menlo, monospace;
  --font-display: 'Cormorant Garamond', Georgia, serif;

  /* Type scale */
  --text-display:   32px;
  --text-h1:        22px;
  --text-h2:        17px;
  --text-h3:        14px;
  --text-body:      14px;
  --text-body-sm:   13px;
  --text-caption:   12px;
  --text-tiny:      11px;

  /* Spacing */
  --space-1:  4px;
  --space-2:  8px;
  --space-3:  12px;
  --space-4:  16px;
  --space-5:  20px;
  --space-6:  24px;
  --space-8:  32px;
  --space-10: 40px;
  --space-12: 48px;
  --space-16: 64px;
  --space-20: 80px;

  /* Radii */
  --radius-sm:   4px;
  --radius-md:   6px;
  --radius-lg:   8px;
  --radius-full: 9999px;

  /* Shadows */
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.04);
  --shadow-md: 0 4px 8px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
  --shadow-lg: 0 8px 24px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.04);
  --shadow-xl: 0 16px 48px rgba(0,0,0,0.12), 0 4px 8px rgba(0,0,0,0.06);

  /* Motion */
  --duration-fast:   100ms;
  --duration-medium: 200ms;
  --duration-slow:   300ms;
  --ease-default:    cubic-bezier(0.4, 0, 0.2, 1);
  --ease-emphasized: cubic-bezier(0.2, 0, 0, 1);
  --ease-decelerate: cubic-bezier(0, 0, 0.2, 1);

  /* Layout */
  --shell-nav-width:    240px;
  --shell-nav-collapsed: 56px;
  --shell-detail-min:   360px;
  --shell-detail-max:   480px;
  --shell-topbar:       48px;

  /* Legacy aliases — keep for one ship while sections migrate */
  --amber:  var(--brand-600);
  --gold:   var(--brand-500);
  --glow:   var(--brand-700);
  --green:  var(--success-600);
  --red:    var(--danger-600);
  --yellow: var(--warning-600);
  --blue:   var(--info-600);
  --ink:    var(--surface-page);
  --navy:   var(--surface-raised);
  --slate:  var(--surface-sunken);
  --mid:    var(--border-default);
  --border: var(--border-default);
  --dim:    var(--text-tertiary);
  --ghost:  var(--text-secondary);
  --white:  var(--text-primary);
  --sidebar: var(--shell-nav-width);
  --topbar:  var(--shell-topbar);
}
```

The legacy aliases section is critical. Existing section CSS uses `var(--ink)`, `var(--amber)`, etc. The aliases let everything keep working while we migrate. They get removed in a later ship after section CSS is audited.

### 2. `app/static/dashboard/styles/dashboard.css`

Do NOT rewrite from scratch. The existing file is consumed by 15 section modules; rewriting it would touch every section.

Instead:

**Append a new section at the end** of `dashboard.css` titled `/* === DESIGN SYSTEM PRIMITIVES === */` containing the primitive component classes below. Existing rules higher in the file stay untouched — they will render with the new tokens via the legacy aliases.

**Primitive classes to add:**

#### Buttons

```css
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-family: var(--font-sans);
  font-weight: 500;
  border-radius: var(--radius-md);
  border: 1px solid transparent;
  cursor: pointer;
  white-space: nowrap;
  transition: background var(--duration-fast) var(--ease-default),
              border-color var(--duration-fast) var(--ease-default);
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-sm { height: 28px; padding: 0 10px; font-size: var(--text-caption); }
.btn-md { height: 36px; padding: 0 14px; font-size: var(--text-body); }
.btn-lg { height: 44px; padding: 0 20px; font-size: var(--text-body); }

.btn-primary {
  background: var(--brand-600);
  color: var(--text-inverse);
  border-color: var(--brand-600);
}
.btn-primary:hover:not(:disabled) { background: var(--brand-500); border-color: var(--brand-500); }

.btn-secondary {
  background: var(--surface-raised);
  color: var(--text-primary);
  border-color: var(--border-default);
}
.btn-secondary:hover:not(:disabled) { background: var(--surface-sunken); }

.btn-ghost {
  background: transparent;
  color: var(--text-primary);
}
.btn-ghost:hover:not(:disabled) { background: var(--surface-sunken); }

.btn-danger {
  background: var(--danger-600);
  color: var(--text-inverse);
  border-color: var(--danger-600);
}
.btn-danger:hover:not(:disabled) { background: var(--danger-700); border-color: var(--danger-700); }
```

#### Badges

```css
.badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  font-size: var(--text-tiny);
  font-weight: 500;
  font-family: var(--font-sans);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border-radius: var(--radius-sm);
  border: 1px solid;
  white-space: nowrap;
}
.badge-default { background: var(--surface-sunken); color: var(--text-secondary); border-color: var(--border-default); }
.badge-brand   { background: var(--brand-50);      color: var(--brand-700);      border-color: var(--brand-100); }
.badge-success { background: var(--success-50);    color: var(--success-600);    border-color: #bbf7d0; }
.badge-warning { background: var(--warning-50);    color: var(--warning-600);    border-color: #fde68a; }
.badge-danger  { background: var(--danger-50);     color: var(--danger-600);     border-color: #fecaca; }
.badge-info    { background: var(--info-50);       color: var(--info-600);       border-color: #bfdbfe; }
```

#### Status dots

```css
.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot-filled   { background: currentColor; }
.status-dot-outlined { background: transparent; border: 1.5px solid currentColor; }
.status-dot-default  { color: var(--border-strong); }
.status-dot-brand    { color: var(--brand-600); }
.status-dot-success  { color: var(--success-600); }
.status-dot-warning  { color: var(--warning-600); }
.status-dot-danger   { color: var(--danger-600); }
```

#### Data table

```css
.data-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-variant-numeric: tabular-nums;
}
.data-table thead th {
  position: sticky;
  top: 0;
  background: var(--surface-sunken);
  padding: 10px 16px;
  text-align: left;
  font-size: var(--text-tiny);
  font-weight: 500;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-tertiary);
  border-bottom: 1px solid var(--border-default);
}
.data-table tbody td {
  padding: 12px 16px;
  font-size: var(--text-body-sm);
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-hairline);
  vertical-align: middle;
}
.data-table tbody tr {
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-default);
}
.data-table tbody tr:hover { background: var(--surface-sunken); }
.data-table tbody tr.is-selected {
  background: var(--brand-50);
  box-shadow: inset 3px 0 0 var(--brand-600);
}
.data-table td.col-numeric  { text-align: right; }
.data-table td.col-mono     { font-family: var(--font-mono); font-size: var(--text-caption); color: var(--text-secondary); }
.data-table td.col-tertiary { color: var(--text-tertiary); }
```

#### Detail panel

```css
.detail-panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: var(--shell-detail-max);
  max-width: 100vw;
  background: var(--surface-raised);
  border-left: 1px solid var(--border-default);
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  z-index: 50;
  transform: translateX(100%);
  transition: transform var(--duration-medium) var(--ease-emphasized);
}
.detail-panel.is-open { transform: translateX(0); }
.detail-panel-header {
  padding: 18px 20px;
  border-bottom: 1px solid var(--border-hairline);
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-shrink: 0;
}
.detail-panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 0;
}
.detail-panel-section {
  padding: 18px 20px;
  border-bottom: 1px solid var(--border-hairline);
}
.detail-panel-section:last-child { border-bottom: none; }
.detail-panel-section-label {
  font-size: var(--text-tiny);
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-tertiary);
  margin-bottom: 8px;
}
.detail-panel-footer {
  padding: 12px 16px;
  border-top: 1px solid var(--border-default);
  background: var(--surface-raised);
  display: flex;
  gap: 8px;
  align-items: center;
  flex-shrink: 0;
}
.detail-panel-close {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  font-size: 18px;
  border-radius: var(--radius-sm);
  flex-shrink: 0;
}
.detail-panel-close:hover { background: var(--surface-sunken); color: var(--text-primary); }
```

#### Empty state

```css
.empty-state {
  padding: 48px;
  text-align: center;
  color: var(--text-secondary);
}
.empty-state-title {
  font-size: var(--text-h2);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
  font-family: var(--font-sans);
}
.empty-state-description {
  font-size: var(--text-body);
  line-height: 1.5;
  margin-bottom: 20px;
}
```

#### Stat card

```css
.stat-card {
  background: var(--surface-raised);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.stat-card-label {
  font-size: var(--text-tiny);
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-tertiary);
}
.stat-card-value {
  font-size: var(--text-h1);
  font-weight: 600;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
}
.stat-card-trend {
  font-size: var(--text-caption);
  color: var(--text-secondary);
}
.stat-card-trend-up    { color: var(--success-600); }
.stat-card-trend-down  { color: var(--danger-600); }
```

### 3. `app/static/dashboard/index.html`

Two minimal changes:

**Change 3a — Google Fonts.** Replace the `<link>` to Cormorant Garamond + DM Sans with:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Cormorant+Garamond:wght@500;600&display=swap" rel="stylesheet">
```

Inter becomes the primary operational font. Cormorant stays available for marketing surfaces but is loaded with fewer weights.

**Change 3b — Body font.** Find the body or html selector in the inlined `<style>` block (if any) and confirm `font-family: var(--font-sans)`. If `dashboard.css` already sets this, no change needed.

Do not touch anything else in `index.html` in this ship. The topbar, sidebar, view containers, modals all stay. They will look different because of the token swap.

### 4. `docs/architecture/DESIGN_SYSTEM.md`

Already exists. No edits in this ship — it stays as the reference for what the system is. Subsequent ships extend it with per-primitive usage notes as they ship.

### 5. Smoke test

After deploy:

- Load `/app/dashboard` in a logged-in operator session.
- Confirm: page background is off-white (`#fafafa`), not dark navy.
- Confirm: type is rendering in Inter (not DM Sans).
- Confirm: every existing section (Overview, Pre-Booking, Sessions, Escalations, Knowledge, Vendors, Properties, etc.) loads without errors.
- Confirm: clicking nav items still navigates correctly.
- Confirm: in any section with a button, the button now reads as "amber on white" not "amber on dark."

This is a visual regression check, not a feature check. The point is to verify that the legacy aliases bridge correctly so no section breaks during the token swap.

---

## Acceptance criteria

1. `tokens.css` rewritten with the exact token list above. Legacy aliases section present so existing CSS keeps working.
2. `dashboard.css` has a new `=== DESIGN SYSTEM PRIMITIVES ===` section appended at the end containing all the primitive classes defined above. No existing rules removed or modified.
3. `index.html` font links updated to Inter + JetBrains Mono + Cormorant.
4. All 15 existing section pages at `/app/dashboard` load and render without errors after deploy. Visual style is changed (light mode); functionality is unchanged.
5. The new primitive classes are usable (`<button class="btn btn-primary btn-md">Approve</button>` renders correctly) even though no section module uses them yet.
6. **Queue V2 preview remains renderable after Ship A token swap.** The Queue V2 surface lives in the legacy React tree (`frontend/dashboard/oyvoda-v10.jsx`, compiled into `app/static/dashboard/oyvoda-dashboard.js`, served at `/operator-dashboard`) and is wired in the top nav with hash route `#queue-v2`. Opening `/operator-dashboard#queue-v2` after Ship A must show the existing three-column preview with no broken layout, invisible text, or collapsed controls. Ship A may restyle this surface incidentally through tokens and primitives, but **must not change its routing, interaction model, or page structure.** Note: the legacy React tree is scheduled for retirement (Ship L), but Queue V2 is the canonical visual reference for the redesign and stays accessible until then.
7. A short PR description documenting the change at the file level.

---

## What ships after

**Ship B — Shell + nav restructure.** Move from the existing topbar+sidebar markup to the new three-column shell. Reorganize nav to lifecycle-spine. Topbar with scope picker, ⌘K trigger stub, alerts bell.

Ship A makes Ship B's CSS work cleaner because the primitive classes already exist.

---

## Notes for the executor

- This ship is intentionally narrow. Do not expand scope to redesign any section module. That work belongs in Ships D, F, G, H, I, J.
- The legacy aliases in `tokens.css` are a bridge, not a permanent fixture. Subsequent ships migrate section CSS off the aliases section by section, then a final cleanup ship removes them.
- Use the existing cache-busting pattern (`?v=2026-05-XX-a` query string) when committing — every section module already does this, and the new tokens.css load needs to invalidate browser caches the same way.
- No JS changes in this ship. If something seems to need JS, it belongs in a later ship.

---

*End of Ship A brief.*
