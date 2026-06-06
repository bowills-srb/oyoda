# Expert Review System Plan

## Goal

Move Oyvoda from:

- single-pass draft generation with limited guardrails

to:

- high-context expert review with grounded drafting, second-pass critique,
  and targeted follow-up when truth is missing

## What Exists Today

Today the live path has pieces of the right architecture:

- transport parsing
- context loading
- specialist agents
- response reviewer / adversarial review
- policy gating
- operator review path

But these pieces are not yet assembled into a full investigative loop.

## What Is Missing

### 1. Full Context Packaging

The system too often drafts from:

- parsed message
- partial property data
- partial FAQ
- limited operator policy

instead of from:

- full property truth
- portfolio truth
- operator policy
- market and seasonal context
- guidebook-extracted structured facts

### 2. Investigation Before Drafting

The system needs a pre-draft phase that can ask:

- do we already know the answer?
- if not, which source should be checked?
- is this property-specific, portfolio-specific, operator-specific, or
  market-specific?
- do we have conflicting evidence?

### 3. Stronger Second-Pass Critique

The adversarial layer needs to do more than just flag obvious risk.

It should check:

- unsupported certainty
- property vs portfolio confusion
- market/season mismatch
- policy mismatch
- missing guidebook evidence
- contradiction with known facts

### 4. Better Escalation of Missing Truth

When truth is missing, the system should not just write softer copy. It should:

- log the exact missing field
- route the gap to the right schema bucket
- create a durable operator/data request

## Phase A: Fast Gap Closure

### Deliverables

- operator context schema
- dislocation review template
- operator intake workflow
- market overlay design
- guidebook extraction audit

### Success Condition

Every bad or awkward live draft can be traced to a named gap class instead of
anecdotal debugging.

## Phase B: Full Expert Review Loop

### Pre-Draft Investigation

For each message:

1. classify the question type
2. identify required truth domains
3. assemble all available evidence
4. detect missing or conflicting truth
5. decide:
   - answer directly
   - recommend from DB
   - review-first
   - hold for missing truth
   - escalate

### Draft

Draft only after the investigation phase chooses the correct path.

### Post-Draft Critique

Run a second-pass reviewer that can:

- reject unsupported claims
- downgrade overconfident copy
- detect category confusion
- force review or hold where needed

## Operator Delivery Plan

These schematics should reach operators through three channels:

### 1. Internal Review Sheet

First use the schema internally to determine which fields can be inferred from:

- guidebooks
- PMS/listing data
- existing knowledge base
- portfolio records

Operators should not be asked for data we already possess.

### 2. Operator Intake Checklist

After internal extraction, send operators a short targeted checklist only for:

- unresolved policy fields
- unresolved property facts
- unresolved recommendation preferences
- market-specific overrides

### 3. Dashboard Knowledge Tasking

Longer-term, Oyvoda should surface these as actionable operator tasks:

- missing golf-cart policy
- missing discount posture
- missing bed-layout detail
- missing neighborhood anchor

## Guidebook Closure Requirement

Guidebooks are likely the largest immediate untapped source of truth.

The system should:

- ingest guidebooks fully
- extract structured facts
- map them to schema fields
- expose those facts as first-class grounding evidence

If the answer exists in the guidebook, the drafting path should not behave as
if the property is unknown.

## Market-Agnostic Rule

All core logic should remain market-agnostic.

Market-specific behavior must come from overlays, not hardcoded assumptions.

Examples:

- golf-cart relevance at a beach market
- ski-shuttle relevance in mountain markets
- pool-heat questions in winter sunbelt markets
- rainy-day recommendations by region and season

## Immediate Next Steps

1. Audit guidebook extraction against the new schema
2. Identify which schema fields already exist in the DB
3. Build the first operator-targeted intake sheet from unresolved fields only
4. Expand the adversarial reviewer to check for market/operator/property mismatch
5. Make missing-field logging first-class in the live review loop
