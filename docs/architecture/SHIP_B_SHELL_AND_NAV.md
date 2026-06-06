# Ship B — Shell And Nav Restructure

**Status:** Brief for Codex execution  
**Author:** Claude, written under Hunter's direction  
**Date:** May 2026  
**Parent docs:**  
- `docs/architecture/COMMAND_MODULE_PROPOSAL.md`  
- `docs/architecture/SHIP_A_FOUNDATIONS.md`

---

## What this ship is

Restructure the operator dashboard shell and navigation so the product **feels** like the new command module, while continuing to use the existing section modules underneath.

Ship B introduces:

1. A new shell hierarchy in `index.html`
2. A lifecycle-spine navigation model
3. A real three-column page frame with a dormant detail-panel rail
4. A subtle topbar command surface (`⌘K`, scope, alerts) wired as stubs
5. Router support for the new view names
6. Stub lifecycle views where no real section exists yet

Ship B **does not** redesign section internals. Existing section modules stay in place and are re-anchored under the new shell.

This is the “new frame, old rooms” ship.

---

## What this ship is not

- Not `Today` as a finished surface. `Today` lands in Ship C.
- Not the redesigned pre-booking queue. That lands in Ship D.
- Not a real command palette. That lands in Ship E.
- Not a detail-panel rollout across sections. The panel container is structural only in Ship B.
- Not a data-model rewrite.
- Not new APIs.
- Not a section-module rewrite.

If a section currently renders through `sections/messages.js`, `sections/sessions.js`, `sections/vendors.js`, etc., Ship B keeps that module and changes the frame around it.

---

## Verified repo reality this brief is anchored to

The current dashboard sections are:

- `overview`
- `prebooking`
- `sessions`
- `escalations`
- `knowledge`
- `gaps`
- `vendors`
- `team`
- `properties`
- `analytics`
- `llm-usage`
- `market`
- `audit`
- `settings`

The current `app/static/dashboard/js/sections/` directory also contains:

- `notifications.js`
- `shell.js`

Those are **infrastructure modules**, not primary nav destinations. Ship B must preserve whatever existing notification access exists in the topbar or shell interactions, but it does not need to create a sidebar destination for `notifications`.

The current router is in:

- `app/static/dashboard/js/router.js`

The current live shell is in:

- `app/static/dashboard/index.html`

The `queue-v2` preview exists separately in the legacy `v10` preview tree and remains a smoke surface only. Ship B must **not** absorb or rewrite that preview.

---

## Ship B philosophy

The right cut is:

- **Wire the shell**
- **Wire the nav**
- **Re-anchor old sections**
- **Stub what does not exist yet**

The wrong cut is:

- rewrite every section at once
- force `messages.js` to become the final pre-booking queue now
- fake `Pre-Arrival` and `Post-Stay` by building brittle filter logic into `sessions.js`

Ship B is successful if the product posture changes immediately, even though most screens are still the old section content living inside the new frame.

---

## Deliverables, file by file

### 1. `app/static/dashboard/index.html`

Restructure the shell markup.

#### Replace the current sidebar information architecture

The current nav buckets are:

- Operations
- Intelligence
- Management & System

Replace them with this new structure:

#### Section A — Guest Messaging

- `Today`
- `Pre-Booking`
- `Pre-Arrival`
- `In-Stay`
- `Post-Stay`

#### Section B — Your Properties

- `Properties`
- `Vendors`
- `Knowledge`

#### Section C — Operations

- `Escalations`

#### Section D — Account

- `Analytics`
- `Audit`
- `Settings`

Keep `Team`, `LLM Usage`, `Market Intelligence`, and any true admin-only links hidden behind a lower-priority treatment or admin grouping. Do not promote them into the main operator posture.

#### New topbar requirements

Update the topbar so it contains:

- left: Oyvoda wordmark + sidebar collapse
- center: breadcrumb / current view label
- right:
  - scope pill: `Beach Habitats 30A`
  - command trigger button: `⌘K`
  - alerts bell
  - settings / sign out cluster

The scope pill is **dormant**. It does not open a picker yet. Single tenant only.

The `⌘K` trigger is a **stub**. It opens a lightweight placeholder modal saying:

`Command search ships in Ship E.`

with a dismiss button.

Do not build search logic in Ship B.

#### Add dormant detail panel rail

Add a right-side detail rail container to the shell with:

- fixed width using the Ship A tokens
- hidden by default
- close button
- header slot
- body slot

Ship B does not integrate existing sections with this rail yet. It just establishes the DOM structure and CSS hooks for later ships.

Suggested IDs/classes:

- `#detail-panel`
- `#detail-panel-header`
- `#detail-panel-body`
- `body[data-detail-open="true"]`

#### Add lifecycle placeholder views

Because only some lifecycle views exist as real sections today, add placeholder containers in `index.html`:

- `view-today`
- `view-pre-arrival`
- `view-post-stay`

Use **two different strategies**:

- `Today` is transitional, not a hard stub
- `Pre-Arrival` and `Post-Stay` are visible stubs

#### `Today` transitional rule

`Today` should render the current `overview` content inside the new shell, with a lightweight banner or eyebrow stating that the surface is being redesigned.

Suggested copy:

- `Today is being redesigned`
- `The operator worklist lands in Ship C. Current overview remains available until then.`

This preserves a useful home surface for Lanier between Ship B and Ship C.

#### `Pre-Arrival` and `Post-Stay` stub rule

These should use the existing card/empty-state patterns and say clearly:

- title
- one-sentence explanation
- `Coming next`

Suggested copy:

- `Pre-Arrival`: “Pre-arrival workflows will land as a dedicated lifecycle view in a later ship.”
- `Post-Stay`: “Post-stay follow-up and retention workflows will land in a later ship.”

Do not hide these views. Visible stubs are acceptable and intentional.

---

### 2. `app/static/dashboard/js/router.js`

Update the router to support the new shell view names.

#### New canonical views for Ship B

Use these view names:

- `today`
- `prebooking`
- `prearrival`
- `instay`
- `poststay`
- `properties`
- `vendors`
- `knowledge`
- `escalations`
- `analytics`
- `audit`
- `settings`

#### Mapping rules

Map them as follows:

- `today` → show `view-today` transitional surface using the current overview content
- `prebooking` → existing `view-prebooking`
- `prearrival` → show `view-pre-arrival` stub
- `instay` → existing `view-sessions`
- `poststay` → show `view-post-stay` stub
- `properties` → existing `view-properties`
- `vendors` → existing `view-vendors`
- `knowledge` → existing `view-knowledge`
- `escalations` → existing `view-escalations`
- `analytics` → existing `view-analytics`
- `audit` → existing `view-audit`
- `settings` → existing `view-settings`

Do **not** attempt to remap `sessions.js` into separate pre-arrival and post-stay filtered modes in this ship.

That logic does not exist cleanly today and would create a brittle pseudo-surface.

#### Backward compatibility

Preserve compatibility with old view names during the transition:

- `overview` should redirect to `today`
- `sessions` should redirect to `instay`
- `market`, `team`, `gaps`, `llm-usage` may remain accessible if there are existing hidden links or admin surfaces, but they are no longer first-class in the primary nav

The breadcrumb labels should match the new language:

- `Today`
- `Pre-Booking`
- `Pre-Arrival`
- `In-Stay`
- `Post-Stay`
- `Properties`
- `Vendors`
- `Knowledge`
- `Escalations`
- `Analytics`
- `Audit`
- `Settings`

---

### 3. `app/static/dashboard/styles/dashboard.css`

Extend the shell styling to support the new layout, but do **not** undo Ship A.

Add:

- shell grid support for a detail rail
- nav section hierarchy styling for the new buckets
- topbar scope pill styling
- command trigger styling
- stub view styling
- detail panel show/hide states

Do not rewrite section-specific styles here.

Ship B CSS should only touch:

- shell
- nav
- topbar
- stub containers
- detail panel frame

Do not chase per-section spacing bugs in this ship unless they make the app unusable.

---

### 4. `app/static/dashboard/js/sections/shell.js`

If needed, add **small** shell-only behaviors here:

- opening/closing the placeholder `⌘K` modal
- opening/closing the dormant detail panel
- syncing body data attributes for shell state

Do not move section logic into `shell.js`.

No data fetching belongs here.

---

## Explicit scope guard

Under no circumstances does Ship B:

- rewrite `sections/messages.js`
- rewrite `sections/sessions.js`
- add new APIs
- add real search
- add real scope switching
- add lifecycle filtering logic to `sessions.js`
- port `queue-v2`
- redesign pre-booking internals

If a change seems to require deep edits to section modules, stop. That is a later ship, not Ship B.

---

## Acceptance criteria

Ship B is done when all of the following are true:

1. `/app/dashboard` opens in the new shell with the new navigation hierarchy.
2. Clicking `Pre-Booking` still loads the existing pre-booking section.
3. Clicking `In-Stay` still loads the existing sessions section.
4. Clicking `Today`, `Pre-Arrival`, and `Post-Stay` shows intentional stub views, not broken sections.
5. The topbar shows the scope pill, `⌘K` trigger, alerts bell, and existing settings/logout controls.
6. The `⌘K` trigger opens a placeholder modal and closes cleanly.
7. The dormant detail panel can be opened/closed structurally if the shell JS exposes a test hook, but no section is required to use it yet.
8. Existing working sections (`prebooking`, `sessions`, `vendors`, `properties`, `knowledge`, `escalations`, `analytics`, `audit`, `settings`) still load with no console errors.
9. The legacy `overview` route no longer acts as the home surface; it redirects or aliases to `today`.
10. `/operator-dashboard#queue-v2` still renders and behaves exactly as before. Ship B must not disturb the preview route.

---

## Suggested implementation order

1. Update `index.html` shell and nav markup
2. Update `router.js` view registry and aliases
3. Add stub views
4. Add topbar stub controls
5. Add detail panel shell container
6. Add shell CSS
7. Smoke-test existing sections
8. Smoke-test `/operator-dashboard#queue-v2`

---

## Smoke test checklist

After implementation, manually check:

- `/app/dashboard`
- click `Today`
- click `Pre-Booking`
- click `In-Stay`
- click `Pre-Arrival`
- click `Post-Stay`
- click `Properties`
- click `Vendors`
- click `Knowledge`
- click `Escalations`
- click `Analytics`
- click `Audit`
- click `Settings`
- open and close `⌘K`
- collapse and re-expand sidebar
- `/operator-dashboard#queue-v2`

If any existing section throws console errors, fix the shell integration, not the section architecture.

---

## What ships next

If Ship B lands cleanly:

- **Ship C**: `Today` as a real worklist surface
- **Ship D**: Pre-Booking redesigned in place
- **Ship E**: real `⌘K`

Ship B is the posture shift. Ship C and D are where the product starts feeling truly new.
