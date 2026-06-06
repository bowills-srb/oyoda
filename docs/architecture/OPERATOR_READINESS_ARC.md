# Operator Readiness Arc

This document is the forward-looking companion to `LEGACY_RETIREMENT_PLAN.md`. It tracks the sequence of ships that take Oyvoda from "architecture is sound but operator can't yet trust it" to "operator runs their business on it daily."

## The goal that governs every ship in this arc

Oyvoda is an automated AI guest-messaging system. It is not an inbox. The operator's experience should be: messages arrive, the AI handles them, the operator reviews escalated patterns and success metrics. Not: the operator logs in daily to review a queue of held drafts.

The path to that experience is gradual and operator-controlled:

1. Operator sees drafts the AI produces (REQUIRED mode, manual review)
2. Operator builds confidence by approving and editing drafts over a small number of days
3. Operator flips specific properties to AUTO mode when comfortable, one click in the dashboard
4. Operator can flip back to REQUIRED at any moment if something starts to go wrong
5. Eventually the whole tenant operates in AUTO mode, with the operator looking at metrics and escalations rather than individual drafts

The system must support each step of this path. The work below builds out the gaps.

## Terminology

- **Property Knowledge** — the umbrella term for what the AI knows about a property. Sources include Breezeway-ingested data, website scraping, PMS sync, booking history fallback, and direct operator entry. Internal field names like `guidebook_knowledge` are existing code; in operator-facing UI and new code, use "Property Knowledge."
- **Property Knowledge Sources** — the upstream sources we can ingest from (Breezeway, website scraper, PMS, booking history, manual entry)
- **Property Knowledge Status** — per-property dashboard view: what's loaded, from which source, when last refreshed

## Ship sequence

### Ship 1 — Queue restoration (forward flow)

Initialize rollout state for all 45 active Beach Habitats properties in REQUIRED mode, clear the 507-row backlog to `backlog_held` status, deploy the writeback patch (already committed at 28fc0ca).

**Outcome**: Lanier opens the dashboard to an empty queue. New inquiries arrive, get brain-processed, become drafts in her queue. She reviews and approves them manually. The 14-day-old backlog is gone from view.

**Detailed spec**: `PHASE_4_5_OPS_SHIP_1.md` (existing brief — updated)

### Ship 2 — Per-property AUTO toggle

Add the operator-facing endpoint and UI control that calls `StagedRolloutService.set_approval_mode()` for a specific property. Lanier can flip individual properties to AUTO or back to REQUIRED with one click. Tenant-wide flip available as a bulk action.

**Outcome**: Lanier owns when each property starts auto-sending. Engineering is not in the loop.

**Detailed spec**: `PHASE_4_5_OPS_SHIP_2.md`

### Ship 3 — Composer overhaul including CLARIFY

Two pieces shipping together because they're entwined:

**Composer prompt overhaul:**
- Universal voice/craft layer at top of system prompt (avoid corporate phrasings, never invent organizational entities, never add unrequested disclaimers, match guest energy)
- Operator-specific voice/persona section (reads from new `operator_ai_guidance` fields)
- Tightened negative constraints with specific banned phrases from observed failures
- Temperature 0.3 → 0.5
- Sentence cap 2-3 → 2-5

**CLARIFY action:**
- New `CLARIFY` value in `RecommendedAction` enum
- Specialist agents identify when missing context is *askable of the guest* vs *not askable* (e.g. "group size" is askable, "is the pool heated" is not)
- Specialist emits CLARIFY with `clarification_questions` list when askable gaps exist
- Composer prompt has a CLARIFY mode: acknowledge, share one relevant fact if available, ask the specific questions
- Policy agent treats CLARIFY differently (clarifying questions are safer to auto-send than substantive drafts)
- Audit captures clarification turns so the next inbound has context

**Outcome**: Drafts feel like a thoughtful human is replying. The Taylor-style dodge becomes a Taylor-style "love the idea — how many in your group, and what are you thinking for the celebration?" CLARIFY responses become the safest auto-send candidates.

**Detailed spec**: `PHASE_4_5_OPS_SHIP_3.md`

### Ship 4 — Property Knowledge & Voice settings UI

Operator-facing settings pages for:
- House rules editor (existing `operator_ai_guidance.guidance_text` — needs clean UI)
- Voice/persona editor (new field describing how the operator talks)
- Example replies editor (new field, 3-5 examples of operator-written replies)
- Property Knowledge Status dashboard (per-property: what's loaded, from which sources, last refreshed, reconcile button)

**Outcome**: Lanier can write her voice, her house rules, and example replies in the dashboard. She can see which properties have complete property knowledge and trigger reconciliation for any that are sparse.

**Detailed spec**: `PHASE_4_5_OPS_SHIP_4.md`

### Ship 5 — Pre-booking review workflow UI

Focused work on the review experience itself:
- Side-by-side layout: guest message + AI draft + property context
- Action buttons: Approve, Edit & Approve, Reject (existing), Dismiss (new), Confirm CLARIFY questions (new for Ship 3 outputs)
- Per-property auto-mode badge in the queue
- Bulk actions: select multiple → bulk Dismiss
- Empty states: "You're up to date — last reply sent at 2:34 PM"
- Confidence and reasoning visible on each draft

**Outcome**: Reviewing drafts is fast and pleasant, not a chore. Bad drafts get dismissed in two clicks. Good drafts get approved in one.

**Detailed spec**: `PHASE_4_5_OPS_SHIP_5.md`

### Ship 6 — Property-binding parser fixes

Diagnose and fix the 43-row property-binding gap across ingress paths (`generic_gmail_parser`, `pre_booking_transport_adapter`, `llm_email_extractor_groq`, etc.) that aren't reliably resolving property names to canonical codes.

**Outcome**: Inbound inquiries reliably bind to the correct property. The remaining unbound cases are genuinely unbindable (non-guest emails, true noise) rather than resolution failures.

**Detailed spec**: `PHASE_4_5_OPS_SHIP_6.md`

## Operating discipline through the arc

- **Each ship is small enough to deploy and observe in one cycle.** No ship in this arc should require multiple sessions or extensive coordination.
- **Each ship ends with a verification step.** What does the operator see, what does the data show, what is the next decision unblocked.
- **Every ship preserves operator control.** Lanier should always have a one-click rollback for anything we've enabled. Engineering should not be in the loop for normal operational decisions.
- **No more architecture migration until the operator can use the product.** The 4.5 brain migration arc is paused. The work in this arc is product quality, content, and UI — different muscle than what we've been exercising.

## What this arc does NOT cover

- The Brain canary observation work (4.5.M measurements) continues independently
- The 4.5.A-D deletion ships (removing legacy duplicates after parity is verified) wait until the canary has produced real measurement data
- The 4.5.E knowledge-gap detection migration is deferred until the operator-readiness arc is far enough along that we're confident in the brain handling traffic
- Future operator onboarding (operators 2, 3, N) is not in scope — this arc is about Beach Habitats specifically becoming a working production deployment

## Status legend

For each ship, status moves through:
- **PLANNED** — brief written, not yet started
- **IN_PROGRESS** — Codex actively building
- **DEPLOYED** — code in production, observation window in progress
- **VERIFIED** — observation window cleared, ship is settled
