# Oyvoda Frontend State

## Scope

This document describes the current operator dashboard UI structure for `dashboard-v2`.

It is intentionally focused on:

- `Shell.tsx`
- `Router.tsx`
- sidebar structure
- topbar structure
- route hierarchy
- component hierarchy
- route-level data sources and API calls

It intentionally does not cover backend implementation details, database models, workers, or orchestration internals.

## Core Files

- [Shell.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/app/Shell.tsx)
- [Router.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/app/Router.tsx)
- [PreBookingRoute.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/PreBooking/PreBookingRoute.tsx)
- [Today/index.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/index.tsx)
- [SessionExpansion.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/SessionExpansion.tsx)
- [PropertiesRoute.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Properties/PropertiesRoute.tsx)

## Screenshot Status

Saved route screenshots are not available from this environment. The route list below reflects the full current UI structure, and these are the screens that should be captured when screenshot tooling is available:

1. `/app/v2/prebooking`
2. `/app/v2/today`
3. `/app/v2/properties`
4. `/app/v2/knowledge`
5. `/app/v2/vendors`
6. `/app/v2/settings`
7. expanded session state in `Today`
8. expanded property state in `Properties`

## Current Navigation Structure

The current navigation is flat in the UI, even though the product logic is already naturally grouped.

Current sidebar order:

1. `Pre-Booking`
2. `Today`
3. `Properties`
4. `Knowledge`
5. `Vendors`
6. `Settings`

The current app has no `Home` route.

## Current Sidebar

Source:

- [Shell.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/app/Shell.tsx)

The sidebar currently contains:

- a primary nav list
- one active-state per route
- a live queue badge on `Pre-Booking`
- chevrons on the other nav items
- a keyboard shortcut section below the nav

Sidebar behavior:

- `Pre-Booking` is the only route with a live count badge
- that badge is derived from the pre-booking feed and counts only the actionable queue bucket
- the nav does not currently express grouped sections like `Revenue`, `Operations`, or `Intelligence`

## Current Top Bar

Source:

- [Shell.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/app/Shell.tsx)

The top bar currently contains:

- Oyvoda wordmark
- workspace / tenant label
- operator identity card
- operator avatar
- operator name
- operator email
- operator menu

The operator menu currently contains:

- theme switcher
- `System`, `Light`, `Dark`
- sign-out action

Topbar role in the UI:

- global app identity
- workspace context
- operator identity
- session controls

It does not currently function as a command center or summary bar.

## Route Hierarchy

Source:

- [Router.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/app/Router.tsx)

Current route tree:

```text
/app/v2
  -> redirects to /app/v2/prebooking

/app/v2/prebooking
/app/v2/today
/app/v2/properties
/app/v2/knowledge
/app/v2/vendors
/app/v2/settings
/app/v2/components

/app/v2/*
  -> redirects to /app/v2/prebooking
```

Loading behavior:

- `Pre-Booking` loads eagerly
- `Today`, `Properties`, `Knowledge`, `Vendors`, `Settings`, and `Components` lazy-load

Layout behavior:

- all normal routes render inside `Shell`
- `/components` is treated as a design-gallery route and skips the shell chrome

## App-Level Component Hierarchy

High-level structure:

```text
Router
  Shell
    Topbar
      Brand
      Workspace identity
      Operator card
        Operator menu
    Sidebar
      Nav links
      Pre-Booking count badge
      Keyboard shortcuts
    Route outlet
      Active route surface
```

## Route-by-Route UI State

### Pre-Booking

Primary file:

- [PreBookingRoute.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/PreBooking/PreBookingRoute.tsx)

Supporting UI files:

- [PreBookingQueueShell.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/PreBooking/PreBookingQueueShell.tsx)
- [PreBookingInquiryCard.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/PreBooking/PreBookingInquiryCard.tsx)
- [PreBookingControls.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/PreBooking/PreBookingControls.tsx)
- [PreBookingAutonomyPopover.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/PreBooking/PreBookingAutonomyPopover.tsx)
- [viewModel.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/PreBooking/viewModel.ts)

What the route is in UI terms:

- a message-first operator queue
- focused on inquiry review, draft review, and reply/send workflows

Major components:

- surface header
- queue controls
- queue shell
- inquiry list
- inquiry detail / expanded card behavior
- autonomy popover
- property match / bind interactions

Current interaction model:

- URL-driven state for tab, filters, search, scope, depth, focus, and selected inquiry
- actionable queue buckets: `action`, `sent`, `held`, `closed`
- row-level state: `ready`, `needs_review`, `blocked`

Component hierarchy:

```text
PreBookingRoute
  SurfaceHeader
  PreBookingControls
  PreBookingQueueShell
    queue metrics
    queue tabs
    inquiry rows
      PreBookingInquiryCard
        draft state
        confidence state
        property binding state
        send / reject / edit actions
  PreBookingAutonomyPopover
```

Data sources:

- authenticated operator session
- pre-booking message feed
- pre-booking bootstrap payload
- autonomy state
- property link suggestions

API calls:

- `/app/auth/session`
- `/app/api/messages?stage=pre_booking`
- `/app/api/v2/prebooking/bootstrap`
- `/app/api/v2/autonomy`
- `/app/api/property-links/suggest`
- `/app/api/inquiries/:id/approve`
- `/app/api/inquiries/:id/reject`
- `/app/api/inquiries/:id/edit`
- `/app/api/inquiries/:id/bind-property`

Design reading:

- this is already close to a command center
- the current noun is still the message
- the likely design evolution is from `message queue` to `work queue`

### Today

Primary file:

- [Today/index.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/index.tsx)

Expansion file:

- [SessionExpansion.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/SessionExpansion.tsx)

Supporting UI files:

- [timeline.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/timeline.ts)
- [priorityRules.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/priorityRules.ts)
- [focusPredicates.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/focusPredicates.ts)
- [lifecycleLabels.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/lifecycleLabels.ts)
- [actionLabels.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/actionLabels.ts)

What the route is in UI terms:

- a session-first guest operations surface
- centered on the guest stay rather than individual messages

Major components:

- surface header
- lifecycle tabs
- filter controls
- session list
- inline expanded session view
- action area for operator interventions
- timeline, work-order, notification, and history blocks

Current interaction model:

- URL-driven tab, property, search, focus, and selected session
- default tab is `in_stay`
- lifecycle buckets: `pre_arrival`, `arriving`, `in_stay`, `post_stay`
- focus chips vary by tab
- selection expands inline and closes explicitly

Component hierarchy:

```text
TodayRoute
  Surface header
  SurfaceTabs
  SurfaceControls
  session roster
    session card rows
      priority strip
      stay facts
      escalation/workflow indicators
      SessionExpansion
        action block
        stay timeline
        open work orders
        conversation snippet
        cross-session history
        proactive journey block
```

Data sources:

- sessions list
- open escalations
- per-session detail
- per-session queued actions
- per-thread timeline

API calls:

- `/app/api/sessions?include_archived=false&limit=200`
- `/app/api/escalations`
- `/app/api/sessions/:id`
- `/app/api/sessions/:id/work-orders`
- `/app/api/sessions/:id/actions`
- `/app/api/threads/:id`
- `/app/api/sessions/:id/actions/:actionType/execute`
- `/app/api/sessions/:id/send-update`
- `/app/api/sessions/:id/request-feedback`

Design reading:

- the architecture is correctly centered on session context
- messaging is a supporting tool, not the primary organizing object
- this is the strongest base for a future `Guest Operations` or `Stay Operations` center

### Properties

Primary file:

- [PropertiesRoute.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Properties/PropertiesRoute.tsx)

Supporting UI files:

- [PropertyExpansion.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Properties/PropertyExpansion.tsx)
- [DocumentUploadForm.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Properties/DocumentUploadForm.tsx)
- [completeness.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Properties/completeness.ts)
- [gapGrouping.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Properties/gapGrouping.ts)
- [types.ts](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Properties/types.ts)

What the route is in UI terms:

- a property intelligence surface
- currently centered on completeness, coverage, and documentation gaps

Major components:

- metric strip
- filter/search controls
- property roster
- completeness indicators
- knowledge gap grouping
- property expansion panel
- document upload affordance

Current interaction model:

- URL-driven view mode, search, portfolio, community, status, and selected property
- supports row and grid modes
- loads deeper KB/assets only when a property is expanded

Component hierarchy:

```text
PropertiesRoute
  metric strip
  controls
  property roster
    property row or grid card
      completeness state
      gap counts
      autonomy state
      PropertyExpansion
        KB entries
        property assets
        document upload
```

Data sources:

- properties autonomy roster
- property identity report
- portfolios
- KB gaps
- property KB entries
- property assets

API calls:

- `/app/api/properties/autonomy`
- `/app/api/properties/identity-report`
- `/app/api/portfolios`
- `/app/api/kb-gaps?resolved=false`
- `/app/api/kb?property_id=...`
- `/app/api/properties/:propertyCode/assets`
- `/app/api/kb-gaps/:gapId/resolve`

Design reading:

- the route already maps cleanly to `Property Intelligence`
- the current UI question is mostly `how documented is this property?`
- the next-generation UI question should be `can AI safely operate this property?`

### Knowledge

Primary file:

- [Knowledge/index.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Knowledge/index.tsx)

What the route is in UI terms:

- a knowledge operations surface
- part library, part gap resolution queue, part guidance editor

Major components:

- surface header
- surface tabs
- surface controls
- entries list/editor
- gaps list/resolution flow
- AI guidance editor
- knowledge test tool

Current tabs:

- `entries`
- `gaps`
- `guidance`

Component hierarchy:

```text
KnowledgeRoute
  SurfaceHeader
  SurfaceTabs
  SurfaceControls
  tab body
    entries mode
      entry list
      create/edit form
    gaps mode
      gap queue
      resolve/dismiss controls
    guidance mode
      guidance editor
      test question tool
```

Data sources:

- properties roster
- knowledge entries
- KB gaps
- AI guidance

API calls:

- `/app/api/kb`
- `/app/api/kb/:id`
- `/app/api/kb/test`
- `/app/api/kb-gaps?resolved=...`
- `/app/api/kb-gaps/:id/resolve`
- `/app/api/kb-gaps/:id/dismiss`
- `/app/api/settings/ai-guidance`

Design reading:

- this is operationally important, but it is not the best next flagship surface
- much of its value should also be surfaced contextually inside `Pre-Booking`, `Properties`, and `Home`

### Vendors

Primary file:

- [Vendors/index.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Vendors/index.tsx)

What the route is in UI terms:

- a vendor directory and configuration surface

Major components:

- surface header
- controls
- category management form
- vendor create/edit form
- vendor list
- property scoping controls

Component hierarchy:

```text
VendorsRoute
  SurfaceHeader
  SurfaceControls
  category creation area
  vendor creation/edit area
  vendor list
```

Data sources:

- vendor categories
- vendors list
- properties roster for scoping

API calls:

- `/app/api/vendor-categories`
- `/app/api/vendors`
- `/app/api/properties/autonomy`
- `/app/api/properties/identity-report`

Design reading:

- important, but likely not the next strategic surface
- better treated as supporting network configuration than core operator OS home

### Settings

Primary file:

- [Settings/index.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Settings/index.tsx)

Supporting tab files:

- [AutonomyTab.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Settings/AutonomyTab.tsx)
- [AlertRoutingTab.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Settings/AlertRoutingTab.tsx)
- [TeamTab.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Settings/TeamTab.tsx)
- [PortfoliosTab.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Settings/PortfoliosTab.tsx)

What the route is in UI terms:

- an admin/control-plane surface for autonomy, alert routing, team access, and portfolios

Major components:

- surface header
- surface tabs
- autonomy settings
- alert routing settings
- team management
- portfolio management

Current tabs:

- `autonomy`
- `alert_routing`
- `team`
- `portfolios`
- `ai_guidance`

Component hierarchy:

```text
SettingsRoute
  SurfaceHeader
  SurfaceTabs
  active settings tab
    AutonomyTab
    AlertRoutingTab
    TeamTab
    PortfoliosTab
```

Data sources:

- settings base
- autonomy settings
- alert routing bundle
- team bundle
- portfolios bundle

API calls:

- `/app/api/settings`
- `/app/api/settings/alert-routing`
- `/app/api/team`
- `/app/api/team/:memberId/scopes`
- `/app/api/portfolios`
- mutations for autonomy, settings, alerts, team, and portfolios

Design reading:

- this is clearly an admin surface
- it should stay out of the main operational narrative except where autonomy settings affect operator trust and system posture

## Shared UI Structure

System components used repeatedly across routes:

- [SurfaceHeader.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/components/system/SurfaceHeader.tsx)
- [SurfaceControls.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/components/system/SurfaceControls.tsx)
- [SurfaceTabs.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/components/system/SurfaceTabs.tsx)
- [SurfaceErrorState.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/components/system/SurfaceErrorState.tsx)
- [AnchoredPanel.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/components/system/AnchoredPanel.tsx)
- [InlineError.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/components/system/InlineError.tsx)
- [ErrorBoundary.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/components/system/ErrorBoundary.tsx)

This means the current frontend already has a repeatable surface grammar:

- header
- tabs when needed
- controls row
- list or board body
- expansion/detail panel
- error state

## Current Information Architecture, Plainly

The current application structure is:

- useful
- real
- data-backed
- operationally rich

But it is still organized like a set of route-level tools rather than a single operator operating system.

Right now:

- `Pre-Booking` is the most command-center-like surface
- `Today` is the most structurally correct operations surface
- `Properties` is the clearest intelligence surface
- `Knowledge`, `Vendors`, and `Settings` are support/control surfaces

What is missing from the current UI structure:

- `Home`
- a dedicated `Escalations` route or workspace
- grouped navigation that reflects the operator mental model
- portfolio-level summary framing above the current route set

## Bottom Line

These six files are enough to understand the current operator experience:

- [Shell.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/app/Shell.tsx)
- [Router.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/app/Router.tsx)
- [PreBookingRoute.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/PreBooking/PreBookingRoute.tsx)
- [Today/index.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/index.tsx)
- [SessionExpansion.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Today/SessionExpansion.tsx)
- [PropertiesRoute.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/Properties/PropertiesRoute.tsx)

Together they show:

- the shell and navigation model
- the current operator workflow shape
- the main nouns the UI is organized around
- the best candidate surfaces for the next-generation operator OS
