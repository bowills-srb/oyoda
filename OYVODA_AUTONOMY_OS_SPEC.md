# Oyvoda Autonomy OS Spec

## Purpose

This document defines the core product model behind Oyvoda.

The product is not the `Home` screen.
The product is not the `Review Drawer`.
The product is not `Inquiry Operations`.
The product is not `Today`.

The product is:

`Trust -> Delegation -> Autonomy`

Every major screen should exist to support that progression.

## Product Thesis

Operators do not adopt autonomy all at once.

They move through a trust journey:

1. See what the system knows.
2. Review what the system proposes.
3. Delegate safe decisions.
4. Allow autonomy within explicit boundaries.
5. Expand autonomy as trust is proven.

That means Oyvoda needs:

- a clear autonomy model
- objective trust metrics
- visible review workflows
- maturity progression at property and portfolio level

## Unified Operator Surface

Operators already live in two operational universes:

1. Pre-booking
2. Booked guest

Pre-booking includes:

- OTA inquiries
- website inquiries
- reservation team workflows
- inbox handling
- lead handling

Booked guest includes:

- PMS-linked guest context
- SMS and email support
- maintenance coordination
- cleaning and turnover coordination
- reviews and post-stay workflows

The fact that these workflows are fundamentally different does not mean operators want separate software.

It means they want a single operating system with different workspaces.

The operator should never think:

- now I am in pre-booking software
- now I am in guest messaging software

They should think:

- I am in Oyvoda

Then choose the domain they need:

- Inquiry Operations
- Guest Operations
- Maintenance Operations
- Turnover Operations
- Property Intelligence

This is one of the strongest product arguments for Oyvoda:

- one operating layer across the guest lifecycle
- different workspaces for different operational domains
- one trust model underneath all of them

## Operational Domains

The autonomy model should apply across operational domains, not just messaging.

### Inquiry Operations

Definition:

- unknown guest
- unknown booking
- pre-booking
- inbox-centric

Primary examples:

- OTA inquiries
- website inquiries
- property matching
- draft review
- direct-booking opportunity handling

### Guest Operations

Definition:

- known guest
- known reservation
- stay-centric
- lifecycle-centric

Primary examples:

- arrivals
- in-stay messaging
- departures
- feedback and review requests

### Maintenance Operations

Definition:

- issue resolution
- vendor coordination
- service recovery

Primary examples:

- maintenance escalations
- dispatch coordination
- vendor follow-through

### Turnover Operations

Definition:

- readiness between stays
- cleaning and unit status
- handoff-sensitive operational work

Primary examples:

- turnover risks
- cleaning coordination
- readiness checks

### Property Intelligence

Definition:

- property readiness
- knowledge completeness
- policy and autonomy trust posture

Primary examples:

- readiness scoring
- gap resolution
- policy coverage
- property-level autonomy eligibility

Each domain should support the same maturity ladder:

- Review Only
- Assisted
- Semi-Autonomous
- Autonomous

## 1. What Autonomy Means

Autonomy is not a binary setting.

It is a scoped operating mode that answers:

- what can the system do without approval
- what requires review
- what is blocked entirely
- what conditions must be true for higher delegation

Autonomy should always be scoped across three layers:

- property
- workflow
- portfolio

A property may be safe for one workflow and unsafe for another. A portfolio may be mostly trusted while still containing blocked properties. The model has to express that nuance directly.

## Autonomy Levels

### Level 0: Review Only

Definition:

- AI can classify, draft, summarize, and recommend
- human approval is required before any guest-facing or operator-facing action is committed

System behavior:

- drafts are generated
- actions are suggested
- no outbound send happens automatically
- no workflow execution happens automatically

Best fit:

- new operators
- new properties
- low-trust portfolios
- high-risk properties

### Level 1: Assisted

Definition:

- AI can prepare work and automate low-risk internal steps
- human still approves guest-visible decisions

System behavior:

- drafts are prefilled
- property suggestions and routing suggestions are applied
- low-risk internal categorization can happen automatically
- guest-visible sends still require review

Best fit:

- teams building trust
- mixed-quality portfolios
- operators still calibrating policy confidence

### Level 2: Semi-Autonomous

Definition:

- AI can autonomously handle low-risk, high-confidence workflows within policy boundaries
- ambiguous, sensitive, or low-confidence cases go to review

System behavior:

- high-confidence pre-booking responses may auto-send
- repetitive guest operations can execute automatically when guardrails pass
- escalations or policy-sensitive cases route to humans

Best fit:

- operators with established confidence in AI quality
- properties with strong readiness
- workflows with measurable repeatability

### Level 3: Autonomous

Definition:

- AI is trusted to operate defined workflow categories by default
- humans supervise exceptions, risk signals, and performance outcomes

System behavior:

- system executes within scoped policy boundaries
- review focuses on anomalies, regressions, and exceptions
- operators manage trust, readiness, and exceptions rather than individual tasks

Best fit:

- mature portfolios
- highly documented properties
- low-variance policy environments
- operators using Oyvoda as an operating layer, not just a drafting tool

## Rule Model For Progression

Each autonomy level should be earned, not toggled blindly.

Progression should depend on a mix of:

- workflow trust
- property readiness
- policy coverage
- review outcomes
- escalation behavior

## What Moves A Property Up

A property should move upward when it shows:

- high knowledge coverage
- complete policy coverage
- strong draft acceptance
- low edit rate
- low exception rate
- low avoidable escalation rate
- stable operational outcomes over time

## What Moves A Property Down

A property should move downward when it shows:

- unresolved knowledge gaps
- repeated operator rewrites
- policy conflicts
- repeated human overrides
- elevated escalation rate
- bad automation outcomes
- stale or incomplete property context

## Recommended Promotion Logic

### Review Only -> Assisted

Require:

- knowledge baseline exists
- core policy topics are documented
- operator usage is active
- drafts are usually relevant even if still reviewed

### Assisted -> Semi-Autonomous

Require:

- sustained high draft acceptance
- low operator rewrite rate
- good property readiness
- policy coverage on common intents
- low risk in the relevant workflow types

### Semi-Autonomous -> Autonomous

Require:

- stable trust metrics over time
- very low exception rate
- very low avoidable escalation rate
- proven operator confidence
- clear rollback path when trust drops

## Scope Of Autonomy

Autonomy should exist at multiple layers.

### Property autonomy

Answers:

- can AI safely operate this property
- at what level
- in which workflow categories

### Workflow autonomy

Answers:

- which workflow classes are safe to automate

Examples:

- amenity Q&A
- check-in logistics
- parking instructions
- pool heat policy
- review requests
- vendor dispatch recommendations

### Portfolio autonomy

Answers:

- how much of the portfolio is ready
- where trust is concentrated
- where operator attention is still required

## 2. What Metrics Prove Trust

Trust should be measurable.

The goal is not just activity metrics. The goal is evidence that delegation is safe.

## Core Trust Metrics

### Draft Acceptance Rate

Definition:

- percentage of AI drafts sent with minimal or no substantive change

Why it matters:

- proves the system is producing usable work

### Edit Rate

Definition:

- percentage of drafts that require operator modification before send

Why it matters:

- high edit rates signal low trust or incomplete knowledge

### Escalation Rate

Definition:

- percentage of relevant workflows that escalate to human intervention

Why it matters:

- shows where autonomy breaks down

### Knowledge Coverage

Definition:

- proportion of common questions and intents with usable documented answers

Why it matters:

- autonomy cannot scale without answer coverage

### Property Readiness

Definition:

- composite readiness score covering knowledge, assets, policy, and context quality

Why it matters:

- ties trust to a concrete operating object: the property

### Policy Compliance

Definition:

- rate at which AI behavior stays within defined rules and operator-approved boundaries

Why it matters:

- the system must be safe, not just convenient

## Supporting Trust Metrics

- review-required rate
- auto-send rate
- override rate
- fallback rate
- unresolved knowledge gap count
- operator intervention time
- labor avoided
- stale-context rate
- routing accuracy
- property binding accuracy

## Recommended Trust Scorecard

Each property should have a visible trust scorecard:

- Draft Acceptance
- Edit Rate
- Knowledge Coverage
- Policy Coverage
- Escalation Pressure
- Autonomy Level

Each portfolio should also have an aggregate scorecard:

- percent of properties automation ready
- percent of inquiries safe for delegation
- percent of guest operations handled without intervention
- critical blockers
- trust trend

## 3. What A 10-Unit Operator Sees

A 10-unit operator needs clarity, not abstraction overload.

They are likely:

- close to the day-to-day work
- reviewing many decisions themselves
- using Oyvoda to save time, not manage a large org chart

## Recommended 10-unit view

Prioritize:

- today’s work queue
- what is safe to send
- what needs review
- what is blocked by missing knowledge
- which property needs documentation work

## What matters most

- draft acceptance
- time saved
- properties blocking automation
- unresolved knowledge gaps
- open issues requiring manual follow-up

## UX emphasis

- fewer executive metrics
- more task-centered review flow
- very visible review drawer
- strong property readiness guidance

## Recommended language

- Safe to send
- Needs review
- Blocked by missing knowledge
- This property is not ready for autonomy

## 4. What A 500-Unit Operator Sees

A 500-unit operator needs management visibility and system control.

They are likely:

- running teams
- supervising many properties
- measuring exception load and staffing
- thinking in trends, risk, and delegation capacity

## Recommended 500-unit view

Prioritize:

- portfolio readiness
- autonomy rate
- exception volume
- escalation pressure
- property cohorts by maturity
- trust trends over time

## What matters most

- percentage of portfolio at each autonomy level
- properties blocked by trust gaps
- labor required by exceptions
- vendor and escalation pressure
- operator review burden by team or portfolio

## UX emphasis

- summary layers before task detail
- cohort and rollup views
- trends and drift detection
- segmentation by portfolio and property cluster

## Recommended language

- Portfolio autonomy posture
- Properties ready for delegation
- Human intervention load
- Trust regression detected

## 5. How The Review Drawer Behaves

The Review Drawer is one of the most important components in the system.

It is where trust gets built or lost.

If it is weak, operators will never move toward autonomy.

The drawer is not just a UI panel. It is the operational trust engine of the product.

## Review Drawer purpose

The drawer should answer:

- what the system wants to do
- why it wants to do it
- what evidence supports it
- what risks or blockers exist
- what the operator can do next

## Review Drawer principles

### Principle 1: Action first

The top of the drawer should show the proposed action, not raw detail.

Examples:

- Send this reply
- Hold for review
- Request property binding
- Escalate to operator

### Principle 2: Explain confidence

Operators should understand:

- why the system is confident
- what it matched on
- what knowledge or policy it used
- what uncertainty remains

### Principle 3: Make risk visible

The drawer should clearly call out:

- missing property binding
- knowledge gaps
- policy warnings
- confidence below threshold
- ambiguous guest intent

### Principle 4: Make trust measurable

The operator should feel they are training the system every time they approve, edit, reject, or escalate.

### Principle 5: Collapse irrelevant detail

The drawer should not drown the operator in backend state.

It should progressively disclose:

- proposed action
- rationale
- evidence
- expanded raw context

## Review Drawer structure

```text
Review Drawer
  Action summary
  Confidence + trust summary
  Proposed draft or action
  Evidence and rationale
  Risks and blockers
  Operator actions
  Secondary context
```

## Review Drawer components

- `ReviewActionHeader`
- `ConfidenceSummaryCard`
- `TrustSignalsRow`
- `ProposedDraftPanel`
- `EvidencePanel`
- `RiskBlockersPanel`
- `PolicyBoundaryPanel`
- `OperatorDecisionBar`
- `LearningFeedbackPanel`
- `ContextAccordion`

## Drawer states

### Ready

Used when:

- property is bound
- knowledge exists
- policy checks pass
- confidence is high

Primary CTA:

- Send

### Needs Review

Used when:

- confidence is moderate
- draft is usable but not fully trusted

Primary CTAs:

- Edit and send
- Approve

### Blocked

Used when:

- no property binding
- unresolved knowledge gap
- policy conflict
- no safe draft

Primary CTAs:

- Bind property
- Resolve knowledge
- Escalate

### Exception

Used when:

- model behavior falls outside expected patterns
- guest intent is sensitive
- potential compliance issue exists

Primary CTA:

- Route to operator

## Drawer operator actions

The operator decision bar should support:

- approve and send
- edit then send
- reject and close
- bind property
- escalate
- mark knowledge gap
- flag policy issue

## What The Drawer Teaches The System

Each operator decision should strengthen the trust model.

Examples:

- send without edits -> increases trust
- small edits -> minor quality correction
- large rewrite -> trust penalty
- reject due to policy -> policy boundary signal
- escalate due to ambiguity -> ambiguity boundary signal
- bind property manually -> matching improvement signal

## Maturity Progression

The product should show operators that maturity is earned.

### Operator maturity progression

#### Stage 1: Oversight

- reviews everything
- learns system behavior
- corrects outputs frequently

#### Stage 2: Delegation

- begins approving quickly
- trusts low-risk categories
- relies on the drawer for exceptions

#### Stage 3: Supervision

- manages exceptions more than drafts
- tracks trust metrics
- configures autonomy intentionally

#### Stage 4: Portfolio Management

- manages trust at scale
- thinks in readiness cohorts, workload, and intervention cost

### Property maturity progression

#### Stage 1: Unknown

- weak documentation
- inconsistent context
- no reliable automation trust

#### Stage 2: Documented

- common questions covered
- policy baseline exists
- still review-heavy

#### Stage 3: Ready

- strong knowledge coverage
- low edit burden
- low policy ambiguity

#### Stage 4: Autonomous

- consistently safe
- exception-driven oversight only

### Portfolio maturity progression

#### Stage 1: Tool-assisted

- AI helps operators
- review burden remains high

#### Stage 2: Selectively delegated

- some properties and workflows are trusted
- mixed posture across the portfolio

#### Stage 3: Mostly autonomous

- most repetitive workflows are delegated
- operator labor concentrates in exceptions

#### Stage 4: Autonomy-managed

- trust, drift, and readiness are actively managed
- humans supervise the system rather than micromanage tasks

## What Home Should Eventually Visualize

Home should visualize the autonomy model, not invent it.

That means Home should answer:

- what the portfolio autonomy score is
- what level of autonomy the portfolio is operating at
- where trust is strong
- where trust is weak
- what is blocking deeper delegation
- how much human review load remains

The hero concept of the screen should be:

- Portfolio Autonomy

Everything else should roll up to that:

- inquiry trust
- guest-operation trust
- knowledge coverage
- escalation pressure
- property readiness

Recommended hero structure:

- workspace name
- portfolio autonomy percentage
- properties by autonomy tier
- trend over time

Recommended supporting explanation:

- Draft Acceptance
- Knowledge Coverage
- Escalation Rate
- Policy Compliance or equivalent trust-support metric

## What Inquiry Operations Should Visualize

Inquiry Operations should show:

- safe delegation opportunities
- review burden
- knowledge blockers
- direct-booking opportunity signals
- trust quality for inquiry handling

## What Today Should Visualize

Today should show:

- which live guest workflows are operating safely
- which sessions need intervention
- where escalations are increasing human cost

## What Properties Should Visualize

Properties should show:

- readiness for autonomy
- missing knowledge or policy coverage
- impact of gaps on real operations

## What Escalations Should Visualize

Escalations should show:

- where autonomy stops
- where human labor begins
- what type of exception the system cannot safely resolve

## Build Order Recommendation

Do not start with `Home` as a visual project alone.

Lock the autonomy model first.

Recommended order:

1. autonomy model and trust spec
2. review drawer behavior
3. property and portfolio maturity model
4. Home
5. Escalations
6. refined Inquiry Operations
7. refined Today
8. refined Properties

## Final Statement

The center of the Oyvoda product is not a dashboard.

It is a system that helps operators decide:

- what to trust
- what to delegate
- what to review
- what to block
- when a property or portfolio is ready for more autonomy

If that model is clear, every screen becomes easier to design.
