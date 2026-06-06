# Design System — Oyvoda Operator Platform

This document defines the visual and interaction language for the Oyvoda operator dashboard, positioned as a corporate operating system for vacation rental operators managing portfolios from 50 to 100,000+ units.

This supersedes the current dashboard's design language (Cormorant Garamond + dark navy + amber) for operational surfaces. The brand identity stays available for marketing and hero contexts only.

## Where this lives in the codebase

The operator dashboard is the vanilla-JS section-module application served from `app/static/dashboard/` and mounted at `/app/dashboard`. It is built on:

- `app/static/dashboard/js/router.js` — view navigation, `oyvoda:view-changed` events
- `app/static/dashboard/js/api.js` — typed fetch wrappers for every `/app/api/*` endpoint
- `app/static/dashboard/js/adapters.js` — payload normalization (snake_case → camelCase, defaults, type coercion)
- `app/static/dashboard/js/state.js` — tiny pub/sub store with `get/set/subscribe/snapshot`
- `app/static/dashboard/js/sections/*.js` — feature modules (messages, sessions, escalations, properties, knowledge, etc.), each exporting `init()`
- `app/static/dashboard/styles/tokens.css` — design tokens as CSS variables
- `app/static/dashboard/styles/dashboard.css` — component styles built on the tokens

The legacy React monolith at `frontend/dashboard/oyvoda-v10.jsx` (served at `/operator-dashboard`) is retired and will be deleted in a forthcoming cleanup ship. Do not build new design system work against that file. Do not create parallel React component files (`*.jsx`) inside `frontend/dashboard/` — the new patterns belong in `app/static/dashboard/`.

Applying the design system means:

1. Replacing the dark navy + amber tokens in `tokens.css` with the light-mode-first tokens defined below.
2. Adding primitive component styles (`.btn-primary`, `.badge-success`, `.data-table`, `.detail-panel`, etc.) to `dashboard.css`.
3. Redesigning section modules in place — `sections/messages.js` is rewritten to use the new tokens and primitives, not replaced by a new file.

## Design philosophy

**Light-mode-first, operational-density-second, marketing-aesthetic-third.**

Operators live in this interface 6-8 hours daily across messaging, maintenance, pricing, and portfolio operations. The design has to serve sustained use over impressive first impressions. Dense data displays, fast scanning, predictable patterns, and one-click reversibility win over visual flourish.

Reference benchmarks: Linear, Notion, Stripe Dashboard, Attio, Salesforce Lightning. Not Apple marketing pages, not crypto dashboards.

## Color tokens

### Surface

```
--surface-page:        #fafafa    /* Page background — off-white, not pure white */
--surface-raised:      #ffffff    /* Cards, panels, modals that lift from page */
--surface-sunken:      #f5f5f4    /* Inset areas: search bars, table headers */
--surface-overlay:     rgba(10,10,10,0.4)  /* Modal scrim */
```

### Border

```
--border-default:      #e8e8e7    /* Card borders, dividers */
--border-strong:       #d4d4d3    /* Hover state borders, emphasized dividers */
--border-hairline:     #f1f1f0    /* Table row separators, list dividers */
--border-focus:        #b8651a    /* Focus rings — uses brand */
```

### Text

```
--text-primary:        #0a0a0a    /* Headings, primary content */
--text-secondary:      #525050    /* Body text, descriptions */
--text-tertiary:       #8a8888    /* Timestamps, metadata, helper text */
--text-disabled:       #c4c2c1    /* Disabled state text */
--text-inverse:        #ffffff    /* Text on dark/colored backgrounds */
```

### Brand (used surgically — primary actions, active nav, links, focus)

```
--brand-50:            #faf0e6    /* Subtle backgrounds (hover, selected states) */
--brand-100:           #f0d4b0    /* Soft highlights */
--brand-500:           #d4791e    /* Hover state for primary actions */
--brand-600:           #b8651a    /* Default primary actions, brand color */
--brand-700:           #8a4a18    /* Pressed state */
```

### Status (semantic — never decorative)

```
--success-50:          #ecfdf5
--success-600:         #0a7d3e
--success-700:         #065f2f

--warning-50:          #fff8e6
--warning-600:         #b8650f   /* Distinct from brand — more red, less gold */
--warning-700:         #8a4a0a

--danger-50:           #fef2f2
--danger-600:          #b91c1c
--danger-700:          #8a1414

--info-50:             #eff6ff
--info-600:            #1e5fb8
--info-700:            #164a8c
```

**Rule:** Status colors only communicate status. Brand amber never used to indicate warning. Warning colors never used decoratively.

### Dark mode (future — toggle, not default)

Dark mode is a user preference, not the default. When users enable it:
- `--surface-page: #0f0f0e`
- `--surface-raised: #1a1a18`
- `--surface-sunken: #232321`
- All text colors invert proportionally
- Brand stays the same hue, slightly desaturated for contrast

Dark mode ships in a later phase. For now: light only.

## Typography

### Font stack

```
--font-sans: 'Inter', 'InterVariable', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
--font-mono: 'JetBrains Mono', 'SF Mono', Menlo, monospace;
--font-display: 'Cormorant Garamond', Georgia, serif;  /* Hero/marketing only */
```

**Inter** for everything operational. Designed for screens, excellent at small sizes, good tabular figures, used by every corporate operating system worth benchmarking against.

**JetBrains Mono** for code, audit IDs, timestamps where alignment matters.

**Cormorant Garamond** reserved exclusively for: marketing landing pages, login welcome, an occasional hero header where editorial tone is appropriate. Never used for body text, table content, form labels, or button copy.

### Type scale

```
--text-display:    32px / 600 / -0.02em   /* Hero only, used 1-2x per surface */
--text-h1:         22px / 600 / -0.01em   /* Page titles */
--text-h2:         17px / 600 / -0.005em  /* Section headings */
--text-h3:         14px / 600 / normal    /* Subsection, card titles */
--text-body:       14px / 400 / normal    /* Default body, form inputs */
--text-body-sm:    13px / 400 / normal    /* Table rows, secondary content */
--text-caption:    12px / 500 / +0.04em / uppercase  /* Labels, timestamps */
--text-tiny:       11px / 500 / +0.04em   /* Badge text, micro-labels */
```

Line heights:
- Headings: 1.3
- Body: 1.5
- Single-line UI (buttons, badges): 1

### Tabular figures

Anywhere numbers appear in tables, metrics, or scannable lists, apply `font-variant-numeric: tabular-nums`. This keeps columns aligned regardless of digit width.

## Spacing scale

```
--space-1:   4px
--space-2:   8px
--space-3:   12px
--space-4:   16px
--space-5:   20px
--space-6:   24px
--space-8:   32px
--space-10:  40px
--space-12:  48px
--space-16:  64px
--space-20:  80px
```

Use multiples of 4px. Avoid arbitrary values like 13px or 22px — they create subtle inconsistency across surfaces.

## Layout

### Page shell

Three-column layout, always:

```
┌──────┬──────────────────────────────┬────────────┐
│ Nav  │ Main content                 │ Detail     │
│ 240px│ Fluid (min 600px)            │ 360-480px  │
│      │                              │ (when used)│
└──────┴──────────────────────────────┴────────────┘
```

**Left nav (240px fixed):**
- Persistent product navigation
- Logo at top, user menu at bottom
- Sections grouped: Messaging, Properties, Maintenance (future), Pricing (future), Settings
- Sticky, never scrolls with content

**Main content (fluid):**
- Page title + breadcrumb at top
- Content scrolls independently
- Minimum readable width 600px, maximum measured by content

**Right detail panel (360-480px, slide-in):**
- Appears when an item is selected in the main content
- Slides in from right with animation (200ms ease-out)
- Closes via X button, Escape key, or clicking outside
- Used for: inquiry review, property detail, work order details, contact details
- This is the pattern that solves "the page is congested" — list densely on the left, show full detail on the right when needed

### Content density

- Tables for collections >10 items
- Cards for collections ≤6 items where each needs visual weight
- Group-and-count headers when displaying many items: "45 properties · 12 with attention needed"
- Inline status (small colored dot + label) when scanning hundreds of rows
- Hover-to-reveal actions on table rows
- Bulk selection on every list view

## Radii

```
--radius-sm:    4px    /* Inputs, small buttons, badges */
--radius-md:    6px    /* Default buttons, cards */
--radius-lg:    8px    /* Modals, large surfaces */
--radius-full:  9999px /* Pills, avatars */
```

No exaggerated rounding. 12-16px radii feel consumer-friendly but unprofessional for operational software. Stripe Dashboard, Linear, Attio all use 4-8px.

## Shadows

```
--shadow-sm:   0 1px 2px rgba(0,0,0,0.04)
--shadow-md:   0 4px 8px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)
--shadow-lg:   0 8px 24px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.04)
--shadow-xl:   0 16px 48px rgba(0,0,0,0.12), 0 4px 8px rgba(0,0,0,0.06)
```

Use sparingly. Most cards don't need shadows — borders are enough. Reserve shadows for: modals, dropdowns, slide-in panels, command palette.

## Motion

```
--duration-fast:    100ms   /* Color/opacity transitions */
--duration-medium:  200ms   /* Slide-in, fade-in */
--duration-slow:    300ms   /* Page transitions, complex animations */

--ease-default:     cubic-bezier(0.4, 0, 0.2, 1)
--ease-emphasized:  cubic-bezier(0.2, 0, 0, 1)   /* Slide-ins */
--ease-decelerate:  cubic-bezier(0, 0, 0.2, 1)   /* Entries */
```

Motion should be felt, not seen. If an animation calls attention to itself, it's too slow or too elaborate. Operations software needs to feel snappy.

## Component primitives

The following primitives exist as the building blocks of every page. Inconsistency dies when every page uses these instead of inline ad-hoc styling.

### Button

```jsx
<Button variant="primary | secondary | ghost | danger" size="sm | md | lg">
  Label
</Button>
```

Variants:
- **primary**: filled brand color, white text — primary action per surface (one max)
- **secondary**: bordered, dark text — common actions
- **ghost**: no border, no fill, text only — tertiary actions, table inline actions
- **danger**: filled red — destructive actions (delete, reject)

Sizes:
- **sm**: 28px height, 12px text — table inline, dense UI
- **md**: 36px height, 14px text — default
- **lg**: 44px height, 14px text — hero CTAs, modal primary actions

### Badge

```jsx
<Badge tone="default | success | warning | danger | info">Label</Badge>
```

For status, categorization, counts. Pill-shaped, small text, semantic tone. Never decorative — if there's no status to communicate, don't use a badge.

### DataTable

```jsx
<DataTable
  columns={[
    { key: 'name', label: 'Property', sortable: true },
    { key: 'inquiries', label: 'Open inquiries', align: 'right' },
    { key: 'mode', label: 'Mode', render: (row) => <Badge>{row.mode}</Badge> }
  ]}
  rows={properties}
  onRowClick={(row) => openDetail(row)}
  virtualizeAfter={50}
  stickyHeader
/>
```

Virtualized after 50 rows. Sticky header. Column-level filtering. Click-to-open-detail-panel. Tabular numeric figures by default. Hairline row separators.

### DetailPanel

```jsx
<DetailPanel open={selected !== null} onClose={() => setSelected(null)} width={420}>
  <DetailPanel.Header title={selected?.name} onClose={...} />
  <DetailPanel.Body>{/* content */}</DetailPanel.Body>
  <DetailPanel.Footer>{/* actions */}</DetailPanel.Footer>
</DetailPanel>
```

Slides in from right. Width 360-480px. Has clear header with title and close, body that scrolls, footer pinned to bottom for actions.

### Input

```jsx
<Input label="Property name" hint="Used in guest replies" error={errors.name} />
```

Always has a label above. Hint text below in tertiary color. Error replaces hint, danger color. Focus ring uses brand.

### EmptyState

```jsx
<EmptyState
  icon="inbox"
  title="You're caught up"
  description="Last reply sent at 11:42 AM · 23 auto-sent today, 0 held for review"
  action={<Button>View today's activity</Button>}
/>
```

Empty states must say something. "No items" is forbidden. Every empty state explains why it's empty and what to do or expect.

### StatCard

```jsx
<StatCard label="Open inquiries" value={12} trend={{ direction: 'down', value: '-3 from yesterday' }} />
```

Dense metric tile. Label on top, large value, optional trend indicator. Tabular numeric figures.

### CommandPalette (⌘K)

Triggered by Cmd+K. Searches across: properties (by name or code), inquiries (by guest name or message text), settings pages, actions ("turn on auto for Sea La Vie"). Single keyboard-driven entry point to the entire application. Modal overlay, 600px wide, centered.

This is the single feature that makes 1,000-unit operators feel like power users. Not optional.

## Banned patterns

- No gradient buttons or gradient backgrounds on operational surfaces (gradients OK on marketing hero only)
- No Cormorant Garamond outside the display/hero scope
- No emoji in operational UI (badges, buttons, table cells) — emoji belong in messaging content where the guest used them
- No "fun" empty states ("Looks like there's nothing here! 🎉") — corporate operating systems take operators seriously
- No animations longer than 300ms — feels sluggish
- No more than one primary button per visible surface — primary means primary
- No dropdown menus deeper than two levels — flatten or split into separate menus
- No floating decorative elements (the floating demo bar is acceptable on marketing surfaces, never on the operator dashboard itself)

## Examples

### Inquiry queue row

```
┌────────────────────────────────────────────────────────────────┐
│ ● Taylor Molina        Sea La Vie · 111VW         AUTO   11:42 │
│   "We'd like to celebrate with our family after eloping..."    │
│                                                                │
│ ● Carri Bevil          517 Eastern Lake · 517EL  REQUIRED 11:28│
│   "Are there beach chairs? Any towels included?..."            │
└────────────────────────────────────────────────────────────────┘
```

- Status dot (left): unread = filled brand, read = hollow
- Guest name: text-body / weight 600
- Property: text-body-sm / text-secondary
- Mode badge: AUTO (brand) or REQUIRED (default tone)
- Timestamp: text-body-sm / text-tertiary / tabular nums
- Message preview: text-body-sm / text-secondary / truncate at one line
- Hover: surface-sunken background
- Click: opens detail panel on right

### Property table row

```
┌──────────────────────────────────────────────────────────────────────┐
│ ☐  Sea La Vie               111VW     8 entries     AUTO     2 open  │
│ ☐  517 Eastern Lake         517EL    12 entries    REQUIRED   1 open │
│ ☐  31 Gardenia              31GARD   35 entries    REQUIRED   0 open │
└──────────────────────────────────────────────────────────────────────┘
```

- Checkbox for bulk selection
- Property name (bold) and code (mono, secondary)
- Knowledge entry count (link — opens knowledge tab)
- Approval mode (badge)
- Open inquiry count (link — opens queue filtered to this property)
- Hover row: surface-sunken
- Bulk actions appear in toolbar when ≥1 selected

## What this document is NOT

- Not a complete component library spec (each primitive needs its own deeper spec)
- Not a brand identity document (the Oyvoda brand — logo, marketing aesthetic — lives elsewhere)
- Not exhaustive coverage of every surface (settings forms, billing, onboarding flows will need additional patterns)
- Not opinionated about iconography yet (icon system spec is a follow-up — likely Lucide or Heroicons, outline style)

## Adoption path

1. **Ship 7a — Tokens swap.** Rewrite `app/static/dashboard/styles/tokens.css` with the light-mode-first palette and typography defined above. Adjust `dashboard.css` where existing rules reference the old tokens. No section logic changes — every section module gets the new look the moment the CSS deploys.
2. **Ship 7b — Primitive component classes.** Extend `dashboard.css` with the primitive class system (`.btn`, `.btn-primary`, `.btn-secondary`, `.btn-ghost`, `.btn-danger`, `.badge`, `.badge-success`, `.badge-warning`, `.badge-danger`, `.badge-info`, `.data-table`, `.detail-panel`, `.empty-state`, `.stat-card`, `.command-palette`). Document each in this file as you go.
3. **Ship 7c+ — Section redesigns.** Rewrite section modules in place, one per ship, to use the new tokens and primitive classes. Order: `sections/messages.js` (pre-booking queue) → `sections/properties.js` (the congested page Hunter flagged) → `sections/knowledge.js` + voice/persona editor → `sections/overview.js` (dashboard landing) → remaining sections.
4. **Ship 7d — Legacy retirement.** Delete `frontend/dashboard/oyvoda-v10.jsx`, `scripts/build-dashboard.js`, `app/static/dashboard/oyvoda-dashboard.js`, `app/api/v1/endpoints/_dashboard_html.py`, `app/api/v1/endpoints/operator_dashboard.py`. Remove the `/operator-dashboard` route mount from `app/main.py`. Drop the `build:dashboard` script from `package.json`. This kills the drift surface permanently.

No big-bang rewrite. Each section gets touched once, in its own ship. The legacy React monolith stays parked at `/operator-dashboard` until 7d but is treated as dead code — no design work, no feature work, no inline-style fixes go into it.
