# Oyvoda Escalations Route Spec

## Purpose

This document defines the build-ready UX specification for the Oyvoda `Escalations` route.

`Escalations` is the human intervention workspace.

This is where operators manage:

- exceptions
- ownership
- vendor coordination
- guest coordination
- operational risk

If `Home` is the portfolio autonomy control surface, `Escalations` is where the system exposes the cost of autonomy limits.

## Route

- `/app/v2/escalations`

## Product Role

`Escalations` should answer:

- where autonomy stops
- where human labor begins
- which issues are aging or risky
- what the next operator action should be

This route should not feel like a generic support inbox.

It should feel like:

- exception management
- coordination management
- intervention management

## Primary Questions The Route Must Answer

1. Which escalations need action first?
2. Which are high risk?
3. Which are blocked on vendors?
4. Which are blocked on guests?
5. Who owns each issue?
6. What is the next best action?

## Data Sources

Primary:

- `/app/api/escalations`

Detail and action sources:

- `/app/api/escalations/{ticket_id}/actions`
- `/app/api/escalations/{ticket_id}/actions/{action_type}/execute`
- `/app/api/escalations/{ticket_id}/assign`
- `/app/api/escalations/{ticket_id}/coordination`
- `/app/api/escalations/{ticket_id}/resolve`
- `/app/api/escalations/{ticket_id}/dispatch-vendor`
- `/app/api/escalations/{ticket_id}/handoffs`
- `/app/api/escalations/{ticket_id}/work-orders`
- `/app/api/escalations/{ticket_id}/routing-preview`

## Route Structure

```text
Escalations
  Escalation pressure hero
  Summary cards
  Queue tabs
  Filters/search
  Escalation list
  Escalation detail workspace
```

## Desktop Layout

Recommended desktop layout:

```text
Escalations
  EscalationPressureHero (full width)
  Summary row
    OpenEscalationsCard
    HighPriorityCard
    WaitingVendorCard
    WaitingGuestCard
  Filters and tabs
  Main split view
    EscalationQueue
    EscalationDetailPanel
```

## Tablet Layout

- hero full width
- summary cards in 2x2 grid
- list and detail in stacked split depending on width

## Mobile Layout

- hero first
- summary cards stacked
- queue first
- detail opens as full-screen drill-in

On mobile, detail should behave more like a task workspace than a side panel.

## Component List

- `EscalationPressureHero`
- `OpenEscalationsCard`
- `HighPriorityCard`
- `WaitingVendorCard`
- `WaitingGuestCard`
- `EscalationTabs`
- `EscalationFiltersBar`
- `EscalationQueue`
- `EscalationRow`
- `EscalationDetailPanel`
- `AssignmentCard`
- `RoutingRecommendationCard`
- `VendorDispatchCard`
- `GuestCoordinationCard`
- `WorkOrderStatusCard`
- `HandoffTimelineCard`
- `ResolutionCard`

## Component Specifications

### `EscalationPressureHero`

Purpose:

- frame the route as intervention management, not just another list

Content:

- open escalations count
- status label
- intervention trend if available
- one-line explanation

Example content:

- `12 Open Escalations`
- `4 High Priority`
- `Status: Elevated`

### `OpenEscalationsCard`

Purpose:

- show total open exception load

Content:

- open count
- change versus recent baseline if available

### `HighPriorityCard`

Purpose:

- isolate the most urgent risks

Content:

- high-priority count
- oldest high-priority age

### `WaitingVendorCard`

Purpose:

- show coordination bottlenecks outside the operator team

Content:

- waiting vendor count
- vendor-stalled oldest age if available

### `WaitingGuestCard`

Purpose:

- show issues stalled on guest response

Content:

- waiting guest count
- oldest waiting guest age if available

### `EscalationTabs`

Purpose:

- help operators move between workload buckets quickly

Recommended tabs:

- `All Open`
- `High Priority`
- `Waiting Vendor`
- `Waiting Guest`
- `Needs Assignment`
- `Ready To Resolve`

### `EscalationFiltersBar`

Purpose:

- narrow the queue without losing operational clarity

Recommended filters:

- property
- priority
- status
- assigned operator
- queue bucket
- search

### `EscalationQueue`

Purpose:

- present the ranked intervention workload

Each row should surface:

- ticket reason
- property
- guest or session context when present
- priority
- current status
- owner
- aging
- current blocker

### `EscalationRow`

Purpose:

- make the issue understandable before opening detail

Row content:

- headline summary
- priority chip
- blocker chip
- ownership
- age
- linked domain hint such as maintenance or guest issue

### `EscalationDetailPanel`

Purpose:

- provide a full intervention workspace for a selected escalation

Top-level sections:

- summary and ownership
- recommended routing or assignment
- vendor coordination
- guest coordination
- work orders
- handoffs
- resolution

The detail panel should feel like a workspace, not a static details card.

### `AssignmentCard`

Purpose:

- make ownership explicit

Content:

- current owner
- assignment controls
- ownership status

### `RoutingRecommendationCard`

Purpose:

- show recommended path or routing preview

Content:

- suggested team or handler
- routing reason
- confidence or rationale if available

### `VendorDispatchCard`

Purpose:

- manage external service handoff

Content:

- vendor state
- dispatch action
- dispatch status
- next vendor-related step

### `GuestCoordinationCard`

Purpose:

- manage communication obligations to the guest

Content:

- last guest update
- pending communication need
- coordination note entry or action state

### `WorkOrderStatusCard`

Purpose:

- show the operational state of related work orders

Content:

- work order count
- active state
- ETA or dispatch state
- last actor

### `HandoffTimelineCard`

Purpose:

- preserve intervention history and shared context

Content:

- assignment changes
- coordination updates
- work-order transitions
- resolution attempts

### `ResolutionCard`

Purpose:

- close the loop

Content:

- resolution action
- closure summary
- follow-up requirement if any

## Interaction Model

### Queue behavior

- selecting a row opens the detail workspace
- selection should persist until explicitly changed
- sorting should prioritize urgency and blockage

### Detail behavior

- detail should support action-taking, not just reading
- actions should refetch or patch relevant list/detail state

### Close behavior on smaller screens

- back to queue
- explicit close
- preserve current filter context

## Visual Hierarchy Rules

### Rule 1

The route should lead with intervention pressure, not generic stats.

### Rule 2

The queue should make blockers obvious before selection.

### Rule 3

The detail panel should put ownership and next action above raw history.

### Rule 4

Vendor and guest coordination should be visible as separate coordination modes.

## Empty State Behavior

If there are no escalations:

- show a reassuring empty state
- reinforce that this means exception pressure is low
- provide navigation back to `Guest Operations` or `Home`

Example empty copy:

- `No open escalations`
- `Guest and property issues requiring intervention will appear here.`

## Loading Behavior

Recommended loading behavior:

- hero skeleton
- summary skeleton row
- queue skeleton
- detail skeleton only after a row is selected

## Error Behavior

Preferred error handling:

- route-level error only if base escalations list fails entirely
- otherwise use localized card or panel errors

If queue loads but detail action fails:

- preserve context
- show inline action error
- do not collapse the selected escalation

## Route Copy Principles

The route should sound:

- operational
- calm
- explicit
- urgency-aware

Preferred language:

- `Needs assignment`
- `Waiting vendor`
- `Waiting guest`
- `Ready to resolve`
- `Human intervention load`

Avoid language that feels:

- vague
- ticketing-tool generic
- chat-support generic

## Relationship To Other Surfaces

`Escalations` sits between:

- `Guest Operations`
- `Maintenance Operations`
- `Turnover Operations`

It is the cross-domain exception workspace.

It should not be buried under `Guest Operations` forever, even if that is where the first data source overlap exists.

## Current Implementation Mapping

Current backend capability already exists for much of this route.

Relevant API surface:

- `/app/api/escalations`
- assignment
- coordination
- dispatch
- handoffs
- work orders
- routing preview
- resolve

New route target:

- `app/static/dashboard-v2/src/routes/Escalations/index.tsx`

Likely supporting files:

- `app/static/dashboard-v2/src/routes/Escalations/EscalationsRoute.tsx`
- `app/static/dashboard-v2/src/routes/Escalations/components/EscalationPressureHero.tsx`
- `app/static/dashboard-v2/src/routes/Escalations/components/EscalationQueue.tsx`
- `app/static/dashboard-v2/src/routes/Escalations/components/EscalationDetailPanel.tsx`
- `app/static/dashboard-v2/src/routes/Escalations/components/AssignmentCard.tsx`
- `app/static/dashboard-v2/src/routes/Escalations/components/RoutingRecommendationCard.tsx`
- `app/static/dashboard-v2/src/routes/Escalations/components/VendorDispatchCard.tsx`
- `app/static/dashboard-v2/src/routes/Escalations/components/GuestCoordinationCard.tsx`
- `app/static/dashboard-v2/src/routes/Escalations/components/WorkOrderStatusCard.tsx`
- `app/static/dashboard-v2/src/routes/Escalations/components/HandoffTimelineCard.tsx`
- `app/static/dashboard-v2/src/routes/Escalations/components/ResolutionCard.tsx`

## Implementation Notes

The route should use the existing v2 shell and surface grammar.

It should feel structurally related to:

- `Today`
- the future `ReviewDrawer`

But it should present a stronger workspace model than either a plain queue or a passive detail card.

## Success Criteria

The route succeeds when an operator can answer quickly:

- what needs intervention first
- what is blocked
- who owns the issue
- what the next best action is
- whether the issue is guest-facing, vendor-facing, or internal

## Final Statement

`Escalations` is where Oyvoda makes the boundaries of autonomy visible.

It should make intervention feel coordinated, prioritized, and explicit rather than chaotic.
