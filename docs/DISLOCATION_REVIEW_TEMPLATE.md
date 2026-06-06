# Dislocation Review Template

## Purpose

Use this template for every live-message review so we stop patching ad hoc and
start building a reusable expert-review system.

## Review Record

### 1. Message Identity

- date
- operator
- property
- market
- channel
- lifecycle stage
- inquiry id / thread id

### 2. Guest Ask

- raw guest message
- normalized summary of the ask
- primary topic
- secondary topics

### 3. System Output

- parser used
- draft path
- draft text
- confidence shown
- policy warnings shown

### 4. Operator Judgment

- send as-is
- edit then send
- do not send

### 5. What Was Wrong

Classify all applicable issues:

- property truth gap
- portfolio recommendation gap
- operator policy gap
- market / seasonal context gap
- guidebook extraction gap
- parsing / turn isolation gap
- reasoning / inference gap
- unsupported certainty gap
- copy / tone gap
- workflow gap

### 6. Missing Truth Source

- guidebook
- PMS
- listing data
- operator policy
- portfolio inventory
- market context
- places / geo context
- reservation context
- turnover context
- unknown

### 7. Safe Behavior That Should Have Happened

- grounded direct answer
- grounded recommendation set
- review-first draft
- hold pending verification
- escalate

### 8. Exact Correction

- what the operator actually sent
- what the system should have said

### 9. Durable Fix

- add property field
- add operator policy field
- add market field
- improve guidebook extraction
- improve retrieval/context selection
- improve reviewer/adversarial rule
- improve routing
- improve workflow/tooling

### 10. Priority

- P0 safety / compliance
- P1 truth / trust
- P2 quality / efficiency
- P3 polish

## Example Categories

### Property Truth Gap

Example:
- “Does the unit have a washer/dryer?”
- operator knows yes
- system lacked a durable property truth field or retrieval path

### Operator Policy Gap

Example:
- “Do you offer first-time renter discounts?”
- answer depends on direct-booking posture and demand sensitivity

### Market / Seasonal Gap

Example:
- golf-cart logic in a beach market should not be assumed in a mountain market

### Guidebook Extraction Gap

Example:
- the answer exists in the uploaded guidebook but was not surfaced into the
  grounding context used for drafting

## Output Use

Each reviewed record should feed:

- the operator question backlog
- the property/portfolio/market schema backlog
- the adversarial reviewer backlog
- the retrieval/guidebook extraction backlog

This template is the bridge from “that draft looked wrong” to a reusable
system fix.
