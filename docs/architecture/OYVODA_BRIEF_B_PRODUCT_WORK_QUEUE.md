# Brief B-product — Inquiry Operations: Message Queue -> Work Queue reframe

For Claude Code. Build-ready. Read docs/architecture/FRONTEND_MIGRATION_DISCIPLINE.md
and docs/architecture/OYVODA_MASTER_ROADMAP.md first.

This is a PRODUCT brick — language, emphasis, and trust-framing. It is a SEPARATE commit
from the B-technical chrome conversion (already landed, 9aa067e). Different risk class:
if something regresses, the commit boundary says whether chrome (technical) or workflow
(product) caused it. Build this ON TOP of the converted chrome, as its own SHA.

## Critical scope-setting: this is SMALL and SURGICAL, not a redesign

B-technical already converted the chrome to Tailwind AND the structure is already
action-shaped: tabs are Action/Sent/Held/Closed, the lead metric is "Awaiting you,"
chips are Draft ready / Knowledge gaps / Unbound / Sent today. The work-queue BEHAVIOR
already exists in PreBookingRoute (getRowState ready/needs_review/blocked,
getNextStepGuidance produces "Next step: ..." verbs, auto-advance on send/reject).

So this brick is NOT a rebuild. It is finishing the FRAMING: making the verb-first,
"what needs you" model the dominant axis in language and presentation. If you find
yourself restructuring layout, rewriting the queue logic, or changing data flow — STOP,
you've overscoped. The behavior is right; this is about how it READS to the operator.

## What to actually change

### 1. Surface identity: "Pre-Booking" -> "Inquiry Operations"
Per the Blueprint IA, the surface is named Inquiry Operations (route stays
/app/v2/prebooking). Update the SurfaceHeader title/kicker and the sidebar nav label in
Shell.tsx to "Inquiry Operations". Keep the route path unchanged (no router/redirect
churn). This is the product-name alignment the Blueprint specifies.

### 2. Verb-first framing in the header summary
Use the new SurfaceHeader.summaryLine prop (added in B-technical) to state the work-queue
posture: lead with what needs the operator, not message volume. E.g. a line built from
real counts: "N awaiting your review · M ready to send · K blocked". Honest, count-driven,
no fabricated metrics. This makes "this is your work queue" explicit without new UI.

### 3. Language pass (the core of the brick)
The framing should consistently express WORK, not MESSAGES. Audit the operator-facing
strings in PreBookingControls, PreBookingRoute, PreBookingDetailPanel, and the row/card
components, and shift message-noun language to work-noun language where it appears:
- "messages" / "inquiries in the queue" -> the queue is WORK to clear, framed as items
  needing a decision (review / send / resolve).
- Lean on the existing getNextStepGuidance verbs — make that "Next step" guidance
  visually prominent in the row and detail, since it's the work-queue's core signal.
- Tabs/chips already read well (Action, Awaiting you, Draft ready) — leave them; don't
  rename what's already action-framed.
Do NOT invent new metrics or trust scores here. (Trust signals beyond what exists —
confidence band display, etc. — are fine to surface MORE prominently if already computed,
but do not compute anything new. No autonomy score — that's the autonomy backend, not built.)

### 4. Make the row's "what to do next" the dominant element
In the row/card, the next-step verb (from getNextStepGuidance) should be the most
prominent thing after the guest/property identity — above secondary detail. This is the
single change that most makes it FEEL like a work queue rather than a message list. Use
the existing guidance data; reorder/emphasize, don't recompute.

## Tokens + system
- Tailwind token utilities only; dark mode auto; no hex. Use components/ui primitives.
- Any emphasis change uses existing tokens (text-primary for the dominant verb, etc.).

## ABSOLUTE scope guards
- This is language + emphasis. NO layout restructure, NO queue-logic rewrite, NO data-flow
  change, NO new computed metrics, NO autonomy score.
- Do NOT touch the chrome conversion (it's done) except to use summaryLine and update the
  title. Do NOT touch styles.css (this brick adds/deletes no CSS — it's a framing pass).
  If styles.css changes at all, something is off.
- Do NOT touch Today, Properties, Escalations, the learning chain, or the autonomy backend.
- Route path stays /app/v2/prebooking (rename the LABEL, not the route).
- preflight false. No localStorage/sessionStorage.

## Done when
- Surface reads as "Inquiry Operations" (header + nav label); route path unchanged.
- summaryLine states the work posture from real counts (awaiting / ready / blocked).
- Operator-facing language consistently frames WORK (decisions to make) over MESSAGES.
- The next-step verb is the dominant row element after identity.
- NO behavior/logic/data change; NO new metrics; styles.css unchanged.
- tsc --noEmit clean. preflight false.
- Commit SHA recorded (separate from the B-technical SHA).
