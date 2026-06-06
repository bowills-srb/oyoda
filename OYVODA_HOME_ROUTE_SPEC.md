# Oyvoda Home Route Spec

## Purpose

This document defines the build-ready UX specification for the Oyvoda `Home` route.

`Home` is not a generic dashboard.

It is the portfolio-level control surface for autonomy.

The hero concept of the route is:

- `Portfolio Autonomy`

Everything else on the screen exists to explain:

- what the current autonomy posture is
- why that score is what it is
- what is helping trust grow
- what is blocking deeper delegation

## Route

- `/app/v2/home`

## Product Role

`Home` is the bridge between the operator’s major domains:

- Inquiry Operations
- Guest Operations
- Property Intelligence
- Escalations

Operators should arrive on this screen and understand both sides of the business without switching systems:

- unknown guest / inquiry-side work
- known guest / stay-side work

This is where the “single OS, multiple workspaces” model becomes visible.

## Primary Questions Home Must Answer

1. What is the portfolio autonomy score right now?
2. Is trust improving or regressing?
3. Why is the score what it is?
4. Which operational domain needs attention first?
5. What is blocking deeper delegation?
6. Where is human labor concentrated today?

## Data Sources

Primary:

- `/app/api/dashboard-summary`
- `/app/api/sessions`
- `/app/api/escalations`
- `/app/api/kb-gaps?resolved=false`

Secondary or future-enrichment:

- autonomy summary endpoint derived from portfolio/property readiness
- property readiness aggregates
- trust trend source

## Route Structure

```text
Home
  Portfolio Autonomy hero
  Why this score row
  Operational domains row
  Escalation + knowledge row
  Property readiness row
  Attention feed
```

## Desktop Layout

Recommended desktop grid:

```text
Row 1
  PortfolioAutonomyHero (full width)

Row 2
  TrustDriverCard
  TrustDriverCard
  TrustDriverCard
  TrustDriverCard

Row 3
  InquiryOperationsCard
  GuestOperationsCard

Row 4
  EscalationPressureCard
  KnowledgeHealthCard

Row 5
  PropertyReadinessCard
  InboxHealthCard

Row 6
  AttentionFeedCard (full width)
```

## Tablet Layout

- hero full width
- trust drivers in 2x2 grid
- domain cards stacked in pairs
- attention feed full width

## Mobile Layout

- hero first
- trust drivers stacked
- domain cards stacked
- escalations and knowledge stacked
- property readiness and inbox stacked
- attention feed last

On mobile, the route should feel like a prioritized briefing, not a compressed analytics dashboard.

## Component List

- `PortfolioAutonomyHero`
- `TrustDriverCard`
- `InquiryOperationsCard`
- `GuestOperationsCard`
- `EscalationPressureCard`
- `KnowledgeHealthCard`
- `PropertyReadinessCard`
- `InboxHealthCard`
- `AttentionFeedCard`

## Component Specifications

### `PortfolioAutonomyHero`

Purpose:

- establish the portfolio’s autonomy posture
- make the product thesis visible in one glance

Content:

- workspace name
- portfolio autonomy score
- current status label
- autonomy tier distribution
- trend over time
- one-line interpretation

Example content:

- `Beach Habitats`
- `Portfolio Autonomy 78%`
- `63 Autonomous · 29 Assisted · 21 Review Only`
- `+6% this month`
- `Status: Healthy`

Visual priority:

- largest text on screen
- strong separation from secondary metrics
- score and tier distribution grouped tightly

Interaction:

- optional clickthrough into autonomy posture detail later
- no heavy controls in v1

### `TrustDriverCard`

Purpose:

- explain why the portfolio autonomy score is what it is

Recommended instances:

1. Draft Acceptance
2. Knowledge Coverage
3. Escalation Rate
4. Policy Compliance or readiness support metric

Shared content model:

- metric name
- current value
- directional trend if available
- brief interpretation

Examples:

- `Draft Acceptance 97%`
- `Knowledge Coverage 93%`
- `Escalation Rate 1.2%`

UX rule:

- this row should answer “why is Portfolio Autonomy 78%?”

### `InquiryOperationsCard`

Purpose:

- summarize the inquiry-side operational domain

Content:

- inquiries today
- automated count
- approved count
- edited count
- review-required count
- knowledge-blocked count

CTA:

- `Open Inquiry Operations`

Key rule:

- do not imply attributable revenue
- this card is about inquiry handling and delegation quality

### `GuestOperationsCard`

Purpose:

- summarize the known-guest / stay-side operational domain

Content:

- active stays
- arrivals
- departures
- issues in progress
- sessions needing intervention

CTA:

- `Open Guest Operations`

### `EscalationPressureCard`

Purpose:

- make human intervention load visible

Content:

- open escalations
- high-priority escalations
- waiting vendor
- waiting guest

CTA:

- `Open Escalations`

### `KnowledgeHealthCard`

Purpose:

- show where missing knowledge is limiting autonomy

Content:

- critical gaps
- frequently asked unresolved topics
- properties blocking automation

CTA:

- `Open Property Intelligence`

### `PropertyReadinessCard`

Purpose:

- summarize how many properties are safe for deeper delegation

Content:

- automation-ready properties
- partially ready properties
- blocked properties
- top blocker category

CTA:

- `Open Properties`

### `InboxHealthCard`

Purpose:

- confirm whether inquiry intake is functioning

Content:

- inbox connected
- provider
- last poll time
- last poll success or failure
- new pending inquiries found

Design rule:

- this should be compact and operational, not a dominant card

### `AttentionFeedCard`

Purpose:

- provide the operator with a short prioritized briefing

Content examples:

- oldest blocked inquiry
- highest-risk escalation
- property with largest knowledge blocker
- stale review queue warning
- sudden regression warning

Design rule:

- limited to the highest-signal items
- should read like an operator briefing, not an activity log

## Visual Hierarchy Rules

### Rule 1

`Portfolio Autonomy` must visually dominate the screen.

### Rule 2

Trust drivers sit directly beneath the hero and explain it.

### Rule 3

Inquiry Operations and Guest Operations appear side by side as sibling domains.

### Rule 4

Escalations and Knowledge represent blockers and exceptions, not the product hero.

### Rule 5

Property readiness should be framed as the supply side of autonomy.

## Information Hierarchy

Top of screen:

- autonomy posture
- trust explanation

Middle of screen:

- operational domain summaries

Lower on screen:

- blockers
- readiness
- inbox health
- attention feed

## Empty State Behavior

If some datasets are unavailable, the route should still render and degrade gracefully.

Examples:

- if trend data is unavailable, hero still shows current score
- if inbox status is unavailable, inbox card shows `Status unavailable`
- if kb gaps fail, knowledge card falls back to `Unable to load gaps`

The screen should avoid collapsing just because one supporting card fails.

## Loading Behavior

Recommended loading behavior:

- hero skeleton first
- trust driver skeleton row
- card-level skeletons beneath

The route should not block first paint waiting for every secondary card.

## Error Behavior

Preferred pattern:

- localized card-level errors where possible
- route-level failure only if the hero cannot render at all

If `/app/api/dashboard-summary` fails entirely:

- show route-level error state
- offer retry

If one secondary source fails:

- keep the rest of the route visible

## Interaction Model

Home is primarily navigational and diagnostic.

It is not a heavy editing surface.

Interactions should mostly be:

- open Inquiry Operations
- open Guest Operations
- open Escalations
- open Properties
- open Knowledge context indirectly through Properties

## Route Copy Principles

The copy should sound:

- operational
- trust-aware
- calm
- explicit

Avoid:

- exaggerated AI language
- fake precision
- attribution-heavy language around revenue

Preferred phrases:

- `Portfolio Autonomy`
- `Needs review`
- `Blocked by missing knowledge`
- `Human intervention load`
- `Properties ready for delegation`

Avoid:

- `Revenue generated`
- `Conversion won`
- `Autopilot`

## Relationship To Other Surfaces

`Home` is not where operators do deep work.

`Home` should point operators toward the right workspace:

- Inquiry Operations for pre-booking and unknown-guest work
- Guest Operations for booked-guest work
- Escalations for human intervention
- Property Intelligence for readiness and knowledge

## Current Implementation Mapping

Current route files that this spec builds on:

- [Shell.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/app/Shell.tsx)
- [Router.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/app/Router.tsx)

New route target:

- `app/static/dashboard-v2/src/routes/Home/index.tsx`

Likely supporting files:

- `app/static/dashboard-v2/src/routes/Home/HomeRoute.tsx`
- `app/static/dashboard-v2/src/routes/Home/cards/PortfolioAutonomyHero.tsx`
- `app/static/dashboard-v2/src/routes/Home/cards/TrustDriverCard.tsx`
- `app/static/dashboard-v2/src/routes/Home/cards/InquiryOperationsCard.tsx`
- `app/static/dashboard-v2/src/routes/Home/cards/GuestOperationsCard.tsx`
- `app/static/dashboard-v2/src/routes/Home/cards/EscalationPressureCard.tsx`
- `app/static/dashboard-v2/src/routes/Home/cards/KnowledgeHealthCard.tsx`
- `app/static/dashboard-v2/src/routes/Home/cards/PropertyReadinessCard.tsx`
- `app/static/dashboard-v2/src/routes/Home/cards/InboxHealthCard.tsx`
- `app/static/dashboard-v2/src/routes/Home/cards/AttentionFeedCard.tsx`

## Implementation Notes

The route should be implemented using the existing v2 surface grammar:

- `SurfaceHeader`
- card-based sections
- existing shell/topbar/sidebar
- existing theme system

It should feel native to the current v2 app, even though the information architecture is evolving.

## Success Criteria

The route succeeds when an operator can answer, within a few seconds:

- what is our current autonomy posture
- why is it at that level
- which domain needs attention right now
- what is blocking more delegation

## Final Statement

`Home` should make Oyvoda feel like one operating system across the guest lifecycle.

It should not just report activity.

It should explain autonomy.
