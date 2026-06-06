# Oyvoda Operator OS Blueprint

## Purpose

This is the target-state UI blueprint for Oyvoda as an operator operating system.

It is not a PMS.

It is the intelligence layer that sits above PMS platforms and helps operators:

- understand what needs attention
- trust where automation is safe
- intervene where human labor matters
- improve property readiness over time

## Product Positioning

Operators already have PMS tools.

Oyvoda should not compete with:

- Escapia
- Guesty
- Hostaway
- Track
- Streamline

Oyvoda should sit above them and answer:

- what deserves attention right now
- what can be automated safely
- where human labor is leaking
- which properties are blocking autonomy

## Core Principle

Pre-booking messages are not reliably attributable to bookings or revenue.

Because inbound pre-booking traffic often arrives without strong identity or booking linkage, the UI should not present:

- revenue generated
- booking conversion
- attributed pre-booking revenue
- attributed post-booking tieback from anonymous inquiry traffic

Instead, pre-booking should emphasize:

- workload
- response velocity
- automation rate
- review burden
- high-intent opportunities
- direct-booking opportunities
- knowledge blockers
- labor avoided

## Unified Operator Surface

Operators already live in two operational universes:

1. pre-booking
2. booked guest

Pre-booking includes:

- OTA inquiries
- website inquiries
- reservation teams
- inbox workflows
- lead handling

Booked guest includes:

- PMS-linked guest support
- SMS and email communications
- maintenance coordination
- cleaning and turnover workflows
- reviews and post-stay handling

The workflows are different, but the operator does not want separate software for each universe.

They want one operating system with different workspaces.

The operator should never think:

- now I am in pre-booking software
- now I am in guest messaging software

They should think:

- I am in Oyvoda

Then choose the workspace they need.

That is a major part of the product moat:

- one operating layer across the guest lifecycle
- the PMS remains the source of record
- Oyvoda becomes the autonomy layer above it

## Target Information Architecture

### Primary navigation

```text
Home

Inquiry Operations

Guest Operations
  Escalations

Property Intelligence
  Properties
  Knowledge

Network
  Vendors

Admin
  Settings
```

Supporting route mapping:

- `Inquiry Operations` maps to current `Pre-Booking`
- `Guest Operations` maps to current `Today`
- `Escalations` becomes a first-class route
- `Property Intelligence` maps to `Properties` and `Knowledge`

## Route Plan

### New route

- `/app/v2/home`

### New route recommended next

- `/app/v2/escalations`

### Existing routes retained

- `/app/v2/prebooking`
- `/app/v2/today`
- `/app/v2/properties`
- `/app/v2/knowledge`
- `/app/v2/vendors`
- `/app/v2/settings`

## Shell Evolution

Current shell is a good base and should be preserved structurally.

What changes:

- add `Home` as first route
- group sidebar items by operational domain
- allow a summary/status strip in the topbar or immediately below it
- preserve operator menu and workspace identity

### Target shell structure

```text
Shell
  Topbar
    Brand
    Workspace identity
    Global status strip
    Operator identity/menu
  Sidebar
    Home
    Inquiry Operations
    Guest Operations
      Escalations
    Property Intelligence
      Properties
      Knowledge
    Network
      Vendors
    Admin
      Settings
  Route outlet
```

## Screen 1: Home

### Route

- `/app/v2/home`

### Purpose

Portfolio-level command center.

This is the first screen operators should land on. It should explain:

- the portfolio’s autonomy posture
- what is healthy
- what is blocked
- what needs review
- where human intervention is required

The hero concept of the screen should be:

- `Portfolio Autonomy`

### Data sources

- `/app/api/dashboard-summary`
- `/app/api/kb-gaps?resolved=false`
- `/app/api/sessions`
- `/app/api/escalations`

### Home layout

```text
Home
  Portfolio Autonomy hero
  Why this score row
  Domain operations row
  Escalation + knowledge row
  Property readiness row
  Recent activity / exceptions row
```

### Components

- `PortfolioAutonomyHero`
- `PortfolioHealthCard`
- `InquiryOperationsCard`
- `InquiryWorkQueueCard`
- `GuestOperationsCard`
- `EscalationPressureCard`
- `KnowledgeHealthCard`
- `PropertyReadinessCard`
- `InboxHealthCard`
- `AttentionFeedCard`

### Card definitions

#### `PortfolioAutonomyHero`

Purpose:

- establish the portfolio’s autonomy posture
- communicate current trust level and direction of travel

Content:

- workspace name
- portfolio autonomy percentage
- properties by autonomy tier
- month-over-month trend
- current status
- one-line interpretation

Example copy:

- `Good morning, Beach Habitats`
- `Portfolio Autonomy 78%`
- `63 Autonomous · 29 Assisted · 21 Review Only`
- `+6% this month`
- `Status: Healthy`

#### `PortfolioHealthCard`

Purpose:

- explain why the portfolio autonomy score is what it is

Content:

- draft acceptance
- knowledge coverage
- escalation rate
- policy compliance or readiness support signal

Example copy:

- `Draft Acceptance 97%`
- `Knowledge Coverage 93%`
- `Escalation Rate 1.2%`

#### `InquiryOperationsCard`

Purpose:

- summarize inquiry handling without pretending it is attributable revenue

Content:

- total message volume
- automated count
- reviewed count
- escalated count
- automation rate

#### `InquiryWorkQueueCard`

Purpose:

- represent inquiry-handling load

Content:

- inquiries today
- awaiting review
- high-intent inquiries
- direct-booking inquiries
- knowledge-blocked inquiries

#### `GuestOperationsCard`

Purpose:

- summarize active stay operations

Content:

- active stays
- arrivals
- departures
- issues in progress

#### `EscalationPressureCard`

Purpose:

- make human labor and risk visible

Content:

- open escalations
- high-priority escalations
- waiting vendor
- waiting guest

#### `KnowledgeHealthCard`

Purpose:

- show where automation is blocked by missing knowledge

Content:

- critical gaps
- frequently asked unresolved topics
- properties blocking automation

#### `PropertyReadinessCard`

Purpose:

- tie property intelligence to operational safety

Content:

- automation-ready properties
- partially ready properties
- blocked properties
- top blockers

#### `InboxHealthCard`

Purpose:

- show whether inbound intake is functioning

Content:

- inbox connected
- provider
- last polled
- last poll success/failure
- new pending inquiries found

#### `AttentionFeedCard`

Purpose:

- give operators a short prioritized attention list

Content:

- top blocked inquiry bucket
- highest-risk escalation
- property with biggest knowledge block
- stale review queue warning

## Screen 2: Inquiry Operations

### Route

- `/app/v2/prebooking`

### Purpose

Inquiry-handling and draft-review workspace.

### Design shift

Current concept:

- message queue

Target concept:

- work queue

### Layout

```text
Inquiry Operations
  Header
  Work queue summary strip
  Queue mode tabs
  Filters/search
  Inquiry list
  Inquiry detail panel
```

### Components

- `InquiryOperationsHeroStrip`
- `ActionNeededCard`
- `ReviewQueueCard`
- `AutomationEligibleCard`
- `InquiryOperationsFiltersBar`
- `InquiryQueueList`
- `InquiryWorkbenchPanel`
- `PropertyBindingPanel`
- `DraftReviewPanel`
- `AutonomyDecisionPopover`

### Summary cards

#### `ActionNeededCard`

Content:

- unbound inquiries
- knowledge gaps
- policy conflicts

#### `ReviewQueueCard`

Content:

- drafts needing review
- median confidence
- oldest waiting item

#### `AutomationEligibleCard`

Content:

- safe-to-send count
- high-confidence count
- low-risk direct booking leads

### Primary metrics

Use:

- inquiries handled
- average response time
- AI draft rate
- send rate
- review-required rate
- high-intent count
- direct-booking count
- knowledge-blocked count
- estimated labor avoided

Do not use:

- attributed revenue
- conversion rate unless explicitly caveated and truly measurable

## Home Screen Principle

`Home` should not feel like a generic executive dashboard.

It should feel like the control surface for portfolio autonomy.

That means:

- `Portfolio Autonomy` is the hero concept
- workload, knowledge, and escalations explain the score
- Inquiry Operations and Guest Operations appear as separate domains beneath the same trust model
- the operator should understand both current posture and what is preventing deeper delegation

## Screen 3: Today / Guest Operations

### Route

- `/app/v2/today`

### Purpose

Session-first operational center for live stays.

### Organizing model

This route should be organized around stay lifecycle, not messages.

Target sections:

- Arriving
- In Stay
- Departing
- Issue Resolution

### Layout

```text
Today
  Header
  Lifecycle summary strip
  Tab rail
  Focus filters
  Session roster
  Session detail expansion
```

### Components

- `TodayLifecycleHero`
- `ArrivalsSummaryCard`
- `InStaySummaryCard`
- `DeparturesSummaryCard`
- `IssueResolutionSummaryCard`
- `TodayFocusChips`
- `SessionRoster`
- `SessionCard`
- `SessionExpansion`
- `SessionActionRail`
- `WorkOrderPanel`
- `ConversationPanel`
- `JourneyTimelinePanel`

### Design priorities

- messages are supporting detail
- guest, stay, property, and issue state are the primary nouns
- operator actions should sit above read-only detail

## Screen 4: Escalation Workspace

### Route

- `/app/v2/escalations`

### Priority

This is the most important new surface after `Home`.

### Why it matters

This is where:

- human labor lives
- vendor coordination happens
- service cost accumulates
- operator intervention creates the most value

### Existing backend capability already supports it

The current platform already has:

- escalation workflows
- assignments
- handoffs
- work orders
- dispatch logic
- routing preview
- coordination notes

The UI just does not surface them as a first-class workspace yet.

### Data sources

- `/app/api/escalations`
- `/app/api/escalations/{ticket_id}/actions`
- `/app/api/escalations/{ticket_id}/actions/{action_type}/execute`
- `/app/api/escalations/{ticket_id}/assign`
- `/app/api/escalations/{ticket_id}/coordination`
- `/app/api/escalations/{ticket_id}/resolve`
- `/app/api/escalations/{ticket_id}/dispatch-vendor`
- `/app/api/escalations/{ticket_id}/handoffs`
- `/app/api/escalations/{ticket_id}/work-orders`
- `/app/api/escalations/{ticket_id}/routing-preview`

### Layout

```text
Escalations
  Header
  Pressure summary strip
  Queue lanes or filtered list
  Escalation detail workspace
    assignment
    routing
    vendor dispatch
    guest coordination
    work orders
    handoffs
    resolution
```

### Components

- `EscalationHeroStrip`
- `OpenEscalationsCard`
- `HighPriorityCard`
- `WaitingVendorCard`
- `WaitingGuestCard`
- `EscalationQueue`
- `EscalationLaneTabs`
- `EscalationFiltersBar`
- `EscalationDetailPanel`
- `AssignmentCard`
- `RoutingRecommendationCard`
- `VendorDispatchCard`
- `GuestCoordinationCard`
- `WorkOrderStatusCard`
- `HandoffTimelineCard`
- `ResolutionCard`

### Queue groupings

Recommended tabs:

- `All Open`
- `High Priority`
- `Waiting Vendor`
- `Waiting Guest`
- `Needs Assignment`
- `Ready To Resolve`

### Detail workspace priorities

The detail view should answer:

- what happened
- who owns it
- what is blocking resolution
- what communication is pending
- what vendor action is active
- what the next best operator action is

## Screen 5: Properties / Property Intelligence

### Route

- `/app/v2/properties`

### Purpose

Property-level AI readiness workspace.

### Design shift

Current question:

- how documented is this property

Target question:

- can AI safely operate this property

### Layout

```text
Properties
  Header
  Readiness summary strip
  Filters/search
  Property roster
  Property detail panel
```

### Components

- `PropertyReadinessHero`
- `AutomationReadyCard`
- `PartiallyReadyCard`
- `BlockedPropertiesCard`
- `TopBlockersCard`
- `PropertyFiltersBar`
- `PropertyRoster`
- `PropertyReadinessRow`
- `PropertyReadinessPanel`
- `KnowledgeCoverageCard`
- `PolicyCoverageCard`
- `AssetCoverageCard`
- `OpenGapsCard`
- `AffectedInquiryImpactCard`

### Row states

Recommended visible property states:

- `Automation Ready`
- `Needs Coverage`
- `Blocked`

### Example property outputs

Ready state:

- `Knowledge Coverage 92%`
- `Assets 8`
- `Gaps 0`
- `Policy Coverage Complete`

Blocked state:

- `Missing parking instructions`
- `Missing pool heat policy`
- `Affected inquiries: 17`

## Screen 6: Knowledge / Knowledge Readiness

### Route

- `/app/v2/knowledge`

### Purpose

Knowledge should remain a dedicated surface, but its strongest signals should also surface elsewhere.

### Role in the OS

- source of truth editor
- gap resolution queue
- guidance and answer-quality control

### Components

- `KnowledgeEntriesWorkspace`
- `GapResolutionQueue`
- `GuidanceEditor`
- `KnowledgeTestBench`

### UX principle

Knowledge is a foundational system surface, but not the primary day-to-day landing experience.

## Screen 7: Vendors

### Route

- `/app/v2/vendors`

### Role

Supporting network configuration surface.

### Components

- `VendorDirectory`
- `CategoryManager`
- `PropertyScopeEditor`
- `VendorProfileEditor`

### Priority

Keep as part of the platform, but do not prioritize ahead of `Home` and `Escalations`.

## Screen 8: Settings

### Route

- `/app/v2/settings`

### Role

Administrative control plane.

### Components

- `AutonomySettingsPanel`
- `AlertRoutingPanel`
- `TeamAccessPanel`
- `PortfolioPanel`
- `AIGuidancePanel`

## Component Rollout Plan

### Phase 1

Build the operator OS skeleton:

1. `Home`
2. grouped sidebar navigation
3. route-level framing updates for `Inquiry Operations`, `Guest Operations`, and `Properties`
4. `Escalations` route shell

### Phase 2

Build detailed operational surfaces:

1. `Inquiry Operations`
2. `Stay Operations Center`
3. `Escalation Workspace`
4. `Property Readiness`

### Phase 3

Refine contextual intelligence:

1. cross-surface knowledge signals
2. autonomy trust indicators
3. attention feed / portfolio anomaly detection

## Exact Implementation Targets

### Route creation

Create:

- `/app/v2/home`
- `/app/v2/escalations`

### Home components

- `AutonomyHeroCard`
- `PortfolioHealthCard`
- `InquiryOperationsCard`
- `InquiryWorkQueueCard`
- `GuestOperationsCard`
- `EscalationPressureCard`
- `KnowledgeHealthCard`
- `PropertyReadinessCard`
- `InboxHealthCard`
- `AttentionFeedCard`

### Escalations components

- `EscalationHeroStrip`
- `OpenEscalationsCard`
- `HighPriorityCard`
- `WaitingVendorCard`
- `WaitingGuestCard`
- `EscalationQueue`
- `EscalationDetailPanel`
- `AssignmentCard`
- `RoutingRecommendationCard`
- `VendorDispatchCard`
- `GuestCoordinationCard`
- `WorkOrderStatusCard`
- `HandoffTimelineCard`
- `ResolutionCard`

### Home data sources

- `dashboard-summary`
- `kb-gaps`
- `sessions`
- `escalations`

### Escalations data sources

- `escalations`
- escalation actions
- assignment
- coordination
- dispatch
- handoffs
- work orders
- routing preview

## Guardrails

### Do

- design around operator attention
- make automation trust visible
- emphasize workload, readiness, and exceptions
- connect property intelligence to operational impact
- surface human labor clearly

### Do not

- design Oyvoda like a PMS
- treat message volume as the primary noun everywhere
- imply revenue attribution where the identity chain is weak
- bury escalations inside other surfaces

## Data Delivery Posture (pull now, push later)

Oyvoda's surfaces sit on a three-tier spectrum of data liveness. Naming the current
tier prevents two opposite mistakes: over-building real-time too early, and assuming
the dashboard is more live than it is.

```text
Static report            -> fixed data, no refresh
Dynamic dashboard        -> live backend data, fetched/refetched (PULL)   <- Oyvoda is here
Real-time command center -> server pushes updates instantly (PUSH)        <- future layer
```

**Current state: dynamic dashboard, pull-based.** Every surface is driven by live
server state via TanStack Query - fetched on load, refetched on staleness/interval,
mutations write back and re-fetch. This is genuinely dynamic (not a static report), but
it is PULL: an escalation that fires server-side appears on the operator's screen at the
next refetch, not the instant it happens. Today's own code already flags this - it notes
a single 200-row fetch with client-side bucketing as a prototype shape and defers
"SSE patch-by-ID updates" to a scalability work item.

**Why pull is correct for v1.** For a 10-unit operator, polling/refetch is invisibly
sufficient. The gap between server truth and screen only becomes a product issue at high
volume (a 500-unit operator with escalations firing continuously), which is exactly where
the real-time layer earns its place - and not before.

**Future real-time layer (deferred, its own workstream - NOT folded into surface bricks):**
SSE or WebSockets, patch-by-ID updates, live queue counts, real-time escalation alerts,
push notifications for urgent items, and stale-state indicators. Sequenced AFTER the
surface build-out (Home -> Review Drawer -> Escalations -> Inquiry/Guest Operations
refinement -> real-time push), and is its own brick, not a thing that hides inside
"finish the surfaces."

**The one intentional exception - autonomy snapshots are periodic by design.** The
Portfolio Autonomy trend ("52% -> 84% over six months") does NOT want real-time updates;
it wants consistent historical capture on a schedule. So the autonomy snapshot job is
deliberately the "static-cadence" piece of an otherwise dynamic system. That is a
feature, not a gap - build the periodic snapshot now even though the trend is empty until
enough time passes, because history cannot be backfilled.

## Final Shape

The target operator OS is:

- `Home` for portfolio posture
- `Inquiry Operations` for lead-handling operations
- `Today` for stay operations
- `Escalations` for human intervention
- `Properties` for AI readiness
- `Knowledge` for system learning
- `Vendors` for network configuration
- `Settings` for governance

That is the right abstraction for the product you actually have.
