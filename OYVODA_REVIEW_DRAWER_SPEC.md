# Oyvoda Review Drawer Spec

## Purpose

This document defines the Review Drawer as a core product component in Oyvoda.

The drawer is not just a detail panel.

It is the operational trust engine of the product.

Its job is to convert AI output into operator trust by making every proposed action:

- understandable
- reviewable
- measurable
- teachable

The Review Drawer exists to support the Oyvoda product model:

`Trust -> Delegation -> Autonomy`

## Product Role

The drawer is the place where operators decide:

- what to trust
- what to approve
- what to correct
- what to block
- what to escalate

If the drawer is weak:

- operators will not trust autonomy
- operators will not delegate safely
- autonomy levels will stall

That means the drawer is a system component, not just a UI surface.

## Primary Use Cases

The Review Drawer should be reusable across multiple product surfaces.

Primary uses:

- pre-booking inquiry review
- guest-operation action review
- escalation action review
- property-readiness exception review

The first and most mature implementation should be Inquiry Operations, because that is where the current UI already has the clearest review loop.

## Core Questions The Drawer Must Answer

Every drawer instance should answer:

1. What does the system want to do?
2. Why does it want to do it?
3. How confident is it?
4. What evidence supports the recommendation?
5. What risk or blocker exists?
6. What should the operator do next?
7. What will the system learn from the operator’s decision?

## Review Drawer Principles

### 1. Action first

The top of the drawer should lead with the proposed action, not with raw message history or metadata.

Examples:

- Send this reply
- Hold for review
- Request property binding
- Escalate to operator

### 2. Confidence must be explained

Confidence should never be presented as just a number.

The drawer should show:

- confidence level
- why confidence is high or low
- what matched successfully
- what was missing or ambiguous

### 3. Risk must be obvious

The operator should not have to hunt for blockers.

The drawer should immediately surface:

- missing property binding
- knowledge gaps
- policy warnings
- ambiguous intent
- confidence below threshold

### 4. Operator decisions should feel consequential

Every approval, edit, rejection, or escalation should feel like it teaches the system something.

The drawer should reinforce that the operator is calibrating trust, not just clearing tasks.

### 5. Raw detail should be secondary

The drawer should progressively disclose context.

Order:

1. action
2. confidence
3. draft or proposed move
4. rationale
5. risk
6. raw supporting context

## Current UI Relationship

Current related implementation for Inquiry Operations:

- [PreBookingInquiryCard.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/PreBooking/PreBookingInquiryCard.tsx)
- [PreBookingQueueShell.tsx](/Users/dhuntermckenzie/Downloads/oyvoda/app/static/dashboard-v2/src/routes/PreBooking/PreBookingQueueShell.tsx)

Today, the selected inquiry expands inline inside the queue card within the current `/app/v2/prebooking` route.

That current expanded card already includes pieces of the future drawer:

- action guidance
- property binding workflow
- draft preview
- send/reject/edit actions

The next step is to formalize this into a consistent review drawer model that can be used across surfaces.

## Recommended Component Direction

Short term:

- evolve the current expanded inquiry card into a drawer-style review experience

Long term:

- promote a reusable `ReviewDrawer` system component that can be invoked by `Inquiry Operations`, `Guest Operations`, and `Escalations`

## Review Drawer Anatomy

```text
Review Drawer
  Action summary
  Confidence + trust summary
  Proposed draft or action
  Evidence and rationale
  Risks and blockers
  Operator decision bar
  Learning feedback
  Secondary context
```

## Target Component Hierarchy

```text
ReviewDrawer
  ReviewActionHeader
  ConfidenceSummaryCard
  TrustSignalsRow
  ProposedActionPanel
  ProposedDraftPanel
  EvidencePanel
  RiskBlockersPanel
  PolicyBoundaryPanel
  OperatorDecisionBar
  LearningFeedbackPanel
  ContextAccordion
```

## Component Definitions

### `ReviewActionHeader`

Purpose:

- state the proposed action in one line

Content:

- action verb
- surface-specific object
- urgency or queue state
- age or freshness

Examples:

- `Send this pre-booking reply`
- `Bind this inquiry before sending`
- `Escalate this guest issue to an operator`

### `ConfidenceSummaryCard`

Purpose:

- explain how safe the proposal is

Content:

- confidence band
- explanation sentence
- major matched signals
- major uncertainty

Output examples:

- `High confidence: property bound, answer covered by knowledge, no policy warnings`
- `Moderate confidence: property match is strong, but answer contains incomplete amenity details`
- `Low confidence: no safe property binding and unresolved knowledge gap`

### `TrustSignalsRow`

Purpose:

- present the key trust inputs compactly

Signals:

- property bound or unbound
- knowledge covered or blocked
- policy clear or warned
- confidence high or medium or low
- autonomy-eligible or review-required

### `ProposedActionPanel`

Purpose:

- show the exact action Oyvoda wants to take

Examples:

- send reply
- hold and request review
- bind property and regenerate
- escalate to human

### `ProposedDraftPanel`

Purpose:

- display the actual guest-facing output when relevant

Content:

- AI draft
- editable text region when editing is allowed
- before-send preview treatment

### `EvidencePanel`

Purpose:

- show why the system made its recommendation

Evidence sources may include:

- matched property
- matched knowledge topics
- parser-extracted asks
- prior operator commitments
- policy checks
- route outcome

### `RiskBlockersPanel`

Purpose:

- make all blockers explicit

Possible blockers:

- no property binding
- unresolved knowledge gap
- policy conflict
- no safe draft
- ambiguous guest intent
- low confidence

### `PolicyBoundaryPanel`

Purpose:

- explain whether the action sits inside approved operating rules

Content:

- safe within policy
- policy warning
- policy blocked

### `OperatorDecisionBar`

Purpose:

- give the operator the next actions without friction

Actions should include:

- approve and send
- edit then send
- reject and close
- bind property
- escalate
- mark knowledge gap
- flag policy issue

### `LearningFeedbackPanel`

Purpose:

- tell the operator what their decision teaches the system

Examples:

- `Sending without edits increases trust for this workflow`
- `Manual property binding improves future matching`
- `Escalating for ambiguity marks this pattern as unsafe for automation`

### `ContextAccordion`

Purpose:

- hold raw or secondary detail outside the main decision flow

Examples:

- original guest message
- prior thread context
- extracted asks
- parser source
- route outcome details
- raw metadata

## Drawer States

The drawer should normalize all review experiences into a small set of clear states.

### Ready

Used when:

- property is bound
- knowledge exists
- policy checks pass
- confidence is high

Primary CTA:

- `Send`

Drawer tone:

- confident
- streamlined
- low-friction

### Needs Review

Used when:

- confidence is moderate
- draft is usable but not fully trusted

Primary CTAs:

- `Edit and send`
- `Approve`

Drawer tone:

- attentive
- cautionary but not blocked

### Blocked

Used when:

- no property binding
- unresolved knowledge gap
- policy conflict
- no safe draft

Primary CTAs:

- `Bind property`
- `Resolve knowledge`
- `Escalate`

Drawer tone:

- explicit
- problem-solving

### Exception

Used when:

- model behavior falls outside expected patterns
- guest intent is sensitive
- potential compliance issue exists

Primary CTA:

- `Route to operator`

Drawer tone:

- high-attention
- risk-first

## Decision Outcomes And Learning

Every decision in the drawer should write back into the trust model conceptually, even if the initial UI does not expose every internal signal yet.

### Approve and send

Teaches:

- the draft was trustworthy
- the workflow may support more delegation

### Edit then send

Teaches:

- the draft was directionally useful but incomplete
- trust should improve only if edit volume remains low

### Reject and close

Teaches:

- the proposed action was wrong or unnecessary
- trust should not increase

### Bind property

Teaches:

- the property matching system lacked enough confidence
- future matching should improve

### Escalate

Teaches:

- this case exceeded autonomy boundaries
- the workflow may need tighter rules or stronger knowledge

### Mark knowledge gap

Teaches:

- the system lacked answer coverage
- property readiness is lower than assumed

### Flag policy issue

Teaches:

- the system entered unsafe territory
- the workflow should be constrained more aggressively

## Surface-Specific Behavior

### Inquiry Operations

Primary noun:

- inquiry

Primary operator decisions:

- send
- edit
- reject
- bind
- mark knowledge gap

Most important trust signals:

- property binding accuracy
- draft quality
- knowledge coverage
- policy safety

### Today

Primary noun:

- session action

Primary operator decisions:

- approve action
- send update
- reassure guest
- request feedback
- escalate issue

Most important trust signals:

- booking/session context completeness
- workflow risk
- escalation pressure
- guest-impact sensitivity

### Escalations

Primary noun:

- intervention decision

Primary operator decisions:

- assign
- dispatch vendor
- coordinate guest response
- hand off
- resolve

Most important trust signals:

- severity
- SLA or aging
- ownership clarity
- vendor readiness
- exception type

## Interaction Model

### Open behavior

The drawer should open from a selected queue item or action row.

### Close behavior

Closing should be explicit.

Recommended close patterns:

- close button
- escape key
- explicit back-to-queue action on compact layouts

### Persistence

The drawer should preserve operator context when possible:

- active selection
- edit state if safe
- review state until action resolves

### Mobile behavior

On narrow screens, the drawer should behave like a full-screen review sheet rather than a side panel.

## Layout Recommendations

### Desktop

Preferred model:

- right-side drawer over list context

Alternative:

- inline expansion only as a temporary implementation state

### Tablet

Preferred model:

- large slide-over drawer

### Mobile

Preferred model:

- full-screen takeover sheet

## Data Contract Expectations

The drawer needs enough structured data to explain trust, not just enough to display content.

Minimum data expected:

- proposed action type
- draft text if applicable
- confidence
- property binding status
- knowledge gap status
- policy warning status
- intent classification
- matched evidence
- operator action availability

For pre-booking, much of this already exists in `MessageFeedItem`.

Useful current fields:

- `propertyId`
- `propertyName`
- `draftText`
- `intent`
- `asks`
- `propertyBindingCandidates`
- `propertyMatchType`
- `routeOutcome`
- `autonomyDecision`
- `fallbackReason`
- `confidence`
- `confidenceSource`
- `draftSource`
- `confidenceLabel`
- `confidenceNote`
- `draftReady`
- `policyFlags`
- `policyWarnings`
- `blockedByGapTopics`

## Visual Language

The drawer should visually separate:

- trust
- action
- evidence
- risk

Recommended visual priorities:

- strong action header
- concise trust summary near the top
- visible blocker section when applicable
- muted raw context below the fold

The UI should feel:

- operational
- calm
- explicit
- high-signal

It should not feel:

- chatty
- opaque
- overloaded with backend detail

## Rollout Plan

### Phase 1

Formalize the current pre-booking expanded card into a true review drawer spec and visual pattern.

### Phase 2

Refactor into a reusable `ReviewDrawer` component with pre-booking as the first implementation.

### Phase 3

Adopt the same drawer model in `Today`.

### Phase 4

Adopt the same drawer model in `Escalations`.

## Success Criteria

The Review Drawer is successful when:

- operators understand why the system made a recommendation
- operators can act quickly without losing context
- blockers are obvious
- operator actions feed the trust model cleanly
- review begins to feel like delegation management rather than message triage

## Final Statement

The Review Drawer is where Oyvoda turns AI output into operator trust.

If the drawer is clear, operators can delegate.
If operators can delegate, autonomy can expand.
If the drawer is weak, the product stalls at suggestion mode.
