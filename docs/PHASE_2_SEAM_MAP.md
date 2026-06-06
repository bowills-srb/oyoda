# Phase 2 Seam Map

## Goal

Phase 2-minimum objective: unblock `pre_booking_single` for the first operator.

This phase is about making the brain useful enough for pre-booking validation, not just adding more concierge agents behind `/concierge/message`.

Non-goal: replacing the legacy concierge path wholesale.


## Current State

- Phase 1 is complete.
- The messaging brain is reachable only behind `MESSAGING_BRAIN_RUNTIME`.
- Default-off behavior is verified:
  - property-level flag
  - operator-level flag
  - platform/env override
  - no flag set = legacy path
- `/concierge/message` is not the rollout-gate path for pre-booking.
- The rollout gate reads `pre_booking_inquiries.status`.
- `pre_booking_single` is measured from `pre_booking_inquiries.status`, not from concierge-message activity or brain audit records.
- The gate counts:
  - `replied`
  - `error`
- Phase 1 ships unchanged in production behind a default-off flag.
- Live Step B review has surfaced a load-bearing context gap:
  pre-booking drafts do not yet guarantee a full guidebook-aware
  grounding pass. Current context packaging is often sufficient for
  FAQ-style answers, but not yet sufficient for broad expert review
  across operator policy, portfolio recommendations, and
  market-sensitive questions.


## Architecture Principle

Message transport and PMS context are separate concerns.

Some providers give you both in one integration. Some, like Escapia, do not. Escapia is currently a split-provider case:

- message transport comes through operator inbox email
- PMS/listing/reservation context comes from Escapia

The pre-booking brain must support both patterns without redesign.

Three layers, bound at config time:

- `TransportAdapter`
  - where the inquiry arrived
  - where replies go out
  - examples: Gmail, Microsoft, future inbox providers, future PMS-native messaging

- `ContextAdapter`
  - reservation context
  - listing context
  - policy context
  - stay/booking context
  - examples: Escapia first, other PMSs later

- `Brain`
  - consumes transport + context
  - does not care whether they came from the same backend or different ones

- `ProviderBinding`
  - configuration describing which transport + context pair a property/operator uses
  - example: `Gmail transport + Escapia context`

This split is the durable fix for:

- Escapia-style PMS limitations
- partial PMS APIs
- vendor portals with context but no messaging
- inbox forwarding setups
- custom operator workflows

Session 5 establishes this seam. Do not special-case Escapia in the core orchestrator.

## Step B Closure Principle

Closing the quality gap is not just a prompt-tuning problem.

The durable fix is:

- broader structured property truth
- broader structured portfolio truth
- broader structured operator policy
- market and seasonal overlays
- guidebook extraction into first-class evidence
- a stronger second-pass adversarial reviewer

Every live-review miss should be classified into one of those buckets so
the system can improve structurally instead of one email at a time.


## Session Plan

Phase 2 is now an 8-session plan.

### Session 1

Deliverable:
- `ContextBuilderAgent` FAQ-list enhancement

Scope:
- expose full FAQ entries in context, not just `faq_count`

Dependencies:
- none

Can ship independently:
- yes

Expected tests:
- import smoke
- focused context-builder tests
- Phase 1 regression tests
- full suite vs `318 passed / 1 unrelated Alembic fail` baseline

Notes:
- this is a prerequisite commit for everything downstream that needs FAQ-backed answers

### Session 2 — SHIPPED

Deliverable:
- `HouseRulesAgent`

Dependencies:
- Session 1

Can ship independently:
- yes

Expected tests:
- per-agent unit tests
- regression tests
- full suite baseline check

Shipped behavior:
- FAQ-grounded answers via `ConciergeKnowledgeService.best_faq_answer`
- always recommends `DRAFT_ONLY` (operator review required)
- pet/smoking/cannabis terms detected as edge cases via word-boundary
  regex; confidence capped at 0.70 and `house_rules_edge_case` risk
  flag set on all such decisions
- never emits `ModuleEvent`s
- registered in `GuestMessageBrainOrchestrator.__init__` alongside
  `MaintenanceAgent`

Known gap — schedule Session 2.5 before broad canary exposure:
- service-animal / ESA branch (see "Agent Seams → HouseRulesAgent”).
  The current edge-case path is safe (it always drafts), but the
  draft text it surfaces for service-animal questions is wrong
  (it pulls from the pet-policy FAQ entry).

### Session 2.5 — PENDING (HouseRulesAgent service-animal branch)

Deliverable:
- service-animal / assistance-animal / ESA branching inside
  `HouseRulesAgent` so those questions don't draw answers from the
  ordinary pet-policy FAQ path

Scope:
- detect service-animal language before FAQ matching
- detect ESA language separately
- route service-animal questions to a cautious path: either a safe
  templated holding draft, or `requires_human_review=True`, or both
- never let a "sorry, no pets" FAQ answer be the draft body for a
  service-animal inquiry
- preserve the existing pet/smoking edge-case behavior for ordinary
  pet questions

Dependencies:
- Session 2 (shipped)

Can ship independently:
- yes

Expected tests:
- service-animal phrasing recognized (`service dog`, `service animal`,
  `assistance animal`, `medical alert dog`, `guide dog`, `ESA`,
  `emotional support`, etc.)
- service-animal questions never produce a pet-FAQ-derived draft
- ESA path distinct from service-animal path
- ordinary pet questions still hit the existing edge-case path
- regression tests against shipped Session 2 behavior
- full suite baseline check

Notes:
- this is policy-sensitive, not just a knowledge gap. Even when the
  operator authors explicit service-animal guidance, the eventual
  steady-state for ADA-adjacent topics should remain review-first by
  policy. Don't quietly relax that in a future session.

### Session 3 — SHIPPED

Deliverable:
- `AccessAgent`

Dependencies:
- Session 1

Can ship independently:
- yes

Expected tests:
- per-agent unit tests
- regression tests
- full suite baseline check

Shipped behavior:
- two evidence paths picked deliberately:
  - DIRECT FACT: wifi / check-in / check-out from
    `property_facts.{wifi,check_in,check_out}`. High confidence (0.90).
  - FAQ FALLBACK: door codes / parking / generic "how do I get in"
    via `ConciergeKnowledgeService.best_faq_answer` against
    `property_knowledge.faq`. Medium confidence (0.75 strong / 0.60 weak).
- direct fact short-circuits FAQ — the two paths are mutually exclusive
  per decision
- door-code-flavored questions get the `access_credential_answer` risk
  flag regardless of which path produced the answer (or even if no
  answer was produced). This is the structural analog of
  `house_rules_edge_case` from Session 2 — a marker future autonomy
  work cannot quietly walk past.
- always recommends `DRAFT_ONLY` (operator review required); auto-send
  eligibility for high-confidence access answers (wifi, check-in time)
  is a future session, see "Long-term target"
- never emits `ModuleEvent`s
- registered in `GuestMessageBrainOrchestrator.__init__` alongside
  `MaintenanceAgent` and `HouseRulesAgent`

Door-code carve-out:
- door codes are physical-access credentials AND per-reservation
  artifacts. Surfacing one to the wrong guest (wrong property, wrong
  reservation phase, wrong turnover state) is a security incident,
  not just a quality issue.
- the real operator model: door codes are generated late in the
  turnover cycle. The gate is housekeeping completion + operator
  walkthrough sign-off, with photo verification of items checked off.
  Only after that gate clears does the next guest receive a code,
  typically issued PROACTIVELY alongside wifi/password before arrival.
  The `access_credential_answer` flag must be honored as a hard block
  on auto-send by any future session until both reservation-phase
  context AND turnover-gate state are wired through. Auto-send on
  FAQ-match confidence alone is not safe.
- known gap — schedule Session 3.5 (see Session Plan): the agent
  needs reservation lifecycle + turnover-gate awareness before its
  door-code path is structurally trustworthy. Today's behavior
  (DRAFT_ONLY + flag) is a safe cover, not a steady-state answer.

### Session 3.5 — PENDING (AccessAgent + reservation/turnover context, operator-opt-in)

Deliverable:
- door-code path inside `AccessAgent` (or a small companion service
  it consults) that's aware of reservation lifecycle and turnover
  workflow state — BUT ONLY for operators who have explicitly enabled
  the turnover module. For operators without it, AccessAgent stays in
  its current Session 3 mode (FAQ-fallback stopgap with
  `access_credential_answer` flag + DRAFT_ONLY).

Why this is operator-opt-in, not universal:
- Some operators run their entire turnover workflow inside Oyvoda
  (e.g. Beach Habitats: housekeeping arrival/done buttons, walkthrough
  checklist, photo verification). For them, the brain can know the
  gate state and surface door codes correctly.
- Other operators run turnover entirely outside the system, or only
  want Oyvoda for guest-side concierge. Forcing them through the
  full workflow is the wrong product. Their AccessAgent just stays
  in stopgap mode and door-code questions stay review-first — which
  is the safe default anyway.
- This mirrors the Phase 1.3a `MaintenanceModule` pattern: agents emit
  decisions, modules do work, modules are opt-in via registration. The
  turnover module is the same shape, exposing a context surface the
  brain reads when present.

The Beach Habitats workflow (representative of operators who DO opt in):
  1. Previous guest checks out
  2. Housekeeping arrives → button press (start)
  3. Housekeeping completes → button press (done)
  4. Operator walkthrough → photo verification of checklist items
  5. Only after all four steps clear → next guest's code is issued
  6. Code is sent proactively (bundled with wifi + password)
     before arrival, not on guest demand.

What AccessAgent does without the turnover module enabled:
- door-code questions hit the existing Session 3 FAQ-fallback path
- `access_credential_answer` flag still fires
- DRAFT_ONLY recommendation stays in place
- this is the steady state for opt-out operators — not a degraded mode

What AccessAgent does with the turnover module enabled:
- read reservation lifecycle (`pre_arrival` / `in_stay` / `post_stay`)
  for the inbound guest's reservation
- read turnover-gate state for the property's current cycle
  (housekeeping_pending / housekeeping_complete / walkthrough_pending /
  cleared_for_issuance / code_issued)
- branch the door-code path on those:
    - reservation `in_stay` AND code already issued → retrieve and
      surface the actual issued code (not an FAQ value)
    - reservation pre-arrival AND turnover gate not yet cleared →
      polite holding draft, no code surfaced, escalation hint to ops
    - any other ambiguity → conservative draft + escalation hint
- the `access_credential_answer` flag stays in place; this session
  refines what answer the flag accompanies, not whether it fires

Dependencies:
- Session 3 (shipped)
- turnover module (separate deliverable, name TBD — see new entry
  "Turnover Module" under "Optional Modules" below). The module owns
  the housekeeping-button + walkthrough-checklist UI/data; AccessAgent
  only consumes the resulting state.
- reservation lifecycle context surface (Phase 1.4+; needed for the
  enabled path, not the opt-out path)

Can ship independently:
- yes, after the turnover module exists. The opt-out path is
  unchanged from Session 3, so existing operators see no
  behavior change.

Expected tests:
- door-code question + turnover module disabled → Session 3 behavior
  exactly (regression test)
- door-code question + turnover module enabled + reservation in_stay
  + code issued → surfaces the issued code, cites
  reservation_facts.door_code (or equivalent)
- door-code question + turnover module enabled + gate not cleared →
  holding draft, no code surfaced, missing_info notes the workflow
  blocker
- door-code question + turnover module enabled + no reservation match
  for guest → escalation recommendation
- regression vs Session 3 behavior on every opt-out path
- full suite baseline check

Notes:
- the turnover module is also the gating signal for the
  door-code-bearing variant of `ProactiveOutreachAgent`'s welcome
  packet. The base welcome packet (wifi + weather + general greeting)
  does NOT need turnover state and can ship without this dependency.
  See "ProactiveOutreachAgent" under Agent Seams below.
- this is policy-sensitive AND security-sensitive AND product-sensitive.
  Even at steady-state, ANY door-code answer should require the agent
  to positively confirm reservation match + workflow clearance —
  silence on either should be treated as "no", not "defer to FAQ."
  And operators who don't want to run the workflow should never be
  pushed into it as a precondition for using the brain.

### Session 4 — SHIPPED

Deliverable:
- `EscalationAgent`

Dependencies:
- none beyond Phase 1 runtime

Can ship independently:
- yes

Expected tests:
- per-agent unit tests
- escalation-safe behavior tests
- regression tests
- full suite baseline check

Notes:
- should land before EQ enrichment

Shipped behavior:
- single agent registered under "EscalationAgent" handles BOTH
  `complaint` and `emergency` topics; the router's
  `DEFAULT_TOPIC_TO_AGENTS` table maps both to that one name
- `intent_topic == "emergency"` → recommend `ESCALATE` with
  confidence 0.95, set `escalation_emergency` risk flag, draft
  acknowledges without minimizing and points to 911 (or local
  emergency number)
- `intent_topic == "complaint"` → recommend `DRAFT_ONLY` with
  confidence 0.85, set `escalation_complaint` risk flag, draft
  acknowledges and signals real human follow-up; no
  defensive/remedial language (no refund/comp/credit promises)
- defensive fallback for unexpected topics → ESCALATE at confidence
  0.50, with `expected_topic_complaint_or_emergency` in missing_info
  so routing-table drift is visible in the audit log
- never grounds from FAQ (no knowledge-service consultation;
  evidence_used is always [])
- never emits `ModuleEvent`s
- `escalation_emotional_distress` risk flag is reserved in vocabulary
  for Session 7 (EQ enrichment) but not populated today
- registered in `GuestMessageBrainOrchestrator.__init__` alongside
  `MaintenanceAgent`, `HouseRulesAgent`, and `AccessAgent`

Known limitation — policy-gate consumption of recommended_action:
- The agent's `recommended_action=ESCALATE` on emergency messages is
  currently advisory. `ResponsePolicyAgent` (which wraps
  `autonomy_gate`) doesn't read specialists' `recommended_action`
  directly — it computes its own `AutonomyDecision` from per-property
  autonomy mode, aggregated confidence, and escalation-block lookups.
- In practice this works out OK today because IntakeAgent classifies
  emergencies with high `urgency=EMERGENCY` and
  `requires_human_review=True`, which the policy gate's REVIEW path
  catches — but the routing happens "around" the agent's
  recommendation rather than "because of" it.
- A future policy refinement should make `recommended_action=ESCALATE`
  from any specialist a hard force on `final_action=ESCALATE`. This
  affects all escalation paths, not just EscalationAgent. Captured
  here so future autonomy work picks it up.

### Session 5

Deliverable:
- provider-agnostic pre-booking layer

Shipped:
- `app/services/messaging_brain/pre_booking.py` now defines:
  - `PreBookingInquiry`
  - provider-neutral draft/context result contracts
  - `TransportAdapter` protocol
  - `ContextAdapter` protocol
  - `PreBookingProviderBinding`
  - `PreBookingBrainOrchestrator`
  - first split-provider binding: `EmailTransportAdapter` +
    `EscapiaContextAdapter`
- `ContextBuilderAgent` now accepts an additive
  `message.metadata["context_adapter_overlay"]` seam so provider
  bindings can inject normalized PMS/property/policy context into the
  existing brain without hard-coding provider logic in the core
  orchestrator.
- The live pre-booking pipeline is intentionally NOT switched in this
  session. Session 5 establishes and verifies the seam; the production
  wrapper/integration remains a later step.

Scope:
- `PreBookingInquiry` contract
- provider-neutral draft/result contracts
- `TransportAdapter` protocol
- `ContextAdapter` protocol
- `PreBookingBrainOrchestrator`
- first binding: email transport + Escapia context

Dependencies:
- none strictly required from Sessions 2–4 to define the seam
- practically benefits from having at least some specialists available

Can ship independently:
- yes, but should stay isolated

Expected tests:
- adapter/protocol tests
- transport/context binding tests
- pre-booking orchestration tests
- regression tests
- full suite baseline check

Notes:
- this is the load-bearing session
- do not combine it with another session even if it looks small on paper
- success criterion: prove the same brain can run with split-provider binding (`email transport + Escapia context`) without special-casing Escapia in the core orchestrator
- verification result:
  - focused Session 5 tests green
  - prior agent regression slice green
  - full suite green against baseline except the same unrelated
    Alembic-head assertion

### Session 6

Deliverable:
- `BookingInquiryAgent`

Shipped:
- `BookingInquiryAgent` now handles the `booking_inquiry` topic and is
  registered by default in `GuestMessageBrainOrchestrator`.
- Two sub-cases are implemented first:
  - availability-style questions using provider-normalized requested
    dates plus canonical booking-context lookup when available
  - group-size / occupancy questions using `house_rules.max_guests`
    first, with a cautious fallback heuristic from PMS property
    context when that is the only signal available
- Always recommends `DRAFT_ONLY`, never emits `ModuleEvent`s, and
  surfaces review-first risk flags:
  - `booking_availability_unverified`
  - `booking_group_size_review`
- Session 6 depends on Session 5's seam but does NOT switch the live
  pre-booking production wrapper yet. It establishes the first real
  specialist on top of that seam.

Dependencies:
- Session 5

Can ship independently:
- yes, after Session 5

Expected tests:
- per-agent unit tests
- PMS/context lookup tests
- regression tests
- full suite baseline check

Notes:
- most lookup-heavy specialist
- intentionally placed after the provider-agnostic layer is proven
- verification result:
  - focused Session 6 tests green
  - Session 5 + prior-agent regression slice green
  - full suite should remain baseline-clean except the same unrelated
    Alembic-head assertion

### Session 7

Deliverable:
- EQ enrichment in `IntakeAgent`

Shipped:
- `IntakeAgent` now wires the repo's `EQAnalyzer` into
  `ConciergeRouter` again, but only for the router's existing
  crisis-level EQ second pass.
- This does NOT widen the route surface broadly: the router only emits
  `ESCALATE_EQ` when EQ urgency reaches `CRISIS`.
- `EscalationAgent` now populates the reserved
  `escalation_emotional_distress` risk flag on EQ-driven complaint
  paths (`matched_keyword == "eq_crisis"`).
- The effect is intentionally narrow:
  - complaint/emergency routing remains review-first
  - no new auto-send behavior is introduced
  - the EQ signal is now visible to the audit log and future policy work

Dependencies:
- Session 4

Can ship independently:
- yes

Expected tests:
- intake/EQ routing tests
- escalation refinement tests
- regression tests
- full suite baseline check

Notes:
- conservative by design: only crisis-level EQ signals route through
  `ESCALATE_EQ`
- verification result:
  - focused Session 7 tests green
  - Session 6 + prior-agent regression slice green
  - full suite should remain baseline-clean except the same unrelated
    Alembic-head assertion

### Session 8

Deliverable:
- integration hardening / follow-up pass after the new pre-booking path is live enough to exercise

Shipped:
- `dispatch_pre_booking(...)` in the live email entrypoint now checks
  `MESSAGING_BRAIN_RUNTIME` / `MESSAGING_BRAIN_SHADOW_MODE` and, when
  enabled, routes pre-booking email inquiries through the Session 5
  provider-agnostic brain seam.
- The integration is intentionally narrow:
  - brain generates the draft
  - legacy pre-booking classifier, policy checks, persistence,
    approval, timeout, and send lifecycle remain in place
  - on any brain-path failure, the live path falls back to the legacy
    draft generator instead of dropping the inquiry
- This is the first production wrapper step for pre-booking, but it is
  still safe-by-default because the runtime flag remains default-OFF.

Dependencies:
- Sessions 2–7 as needed

Can ship independently:
- likely no; this is a stabilization pass

Expected tests:
- end-to-end pre-booking flow tests
- rollout-gate status lifecycle tests
- regression tests
- full suite baseline check

Notes:
- verification result:
  - focused email-dispatch wrapper tests green
  - prior messaging/pre-booking regression slice green
  - full suite should remain baseline-clean except the same unrelated
    Alembic-head assertion


## Agent Seams

### HouseRulesAgent

Reads from context:
- `property_knowledge.faq`
- any future structured operator policy context

Optional external service calls:
- likely `ConciergeKnowledgeService.best_faq_answer(...)`

Writes back:
- `AgentDecision`

Emits `ModuleEvent`:
- no

Likely confidence/risk behavior:
- medium/high confidence when FAQ match is strong
- lower confidence when only weak FAQ evidence exists
- should prefer `DRAFT_ONLY` over aggressive certainty on pet/smoking edge cases

Known refinement (post-Session 2 — "Session 2.5"):
- service-animal / assistance-animal language must NOT be answered from
  the ordinary pet-policy FAQ path. Under the ADA, a service dog is not
  a "pet" and a draft like "sorry, no pets" for a service-animal
  question is wrong on its face, even though the current edge-case
  bias correctly holds it for review.
- the agent should detect service-animal terms (`service dog`,
  `service animal`, `assistance animal`, `medical alert dog`,
  `guide dog`, `seizure alert`, etc.) BEFORE attempting an FAQ match
  and route those into a separate cautious path.
- ESA / emotional-support-animal language is its own third path —
  not the same as service animals, not the same as ordinary pets.
  Hosts may legally treat ESAs as pets in transient lodging, but the
  legal distinction is easy to get wrong, so review-first is the
  right default until operator knowledge explicitly settles it.
- the bigger-picture target is the brain absorbing operator-authored
  policy and stopping `DRAFT_ONLY` once a topic is settled (see
  "Long-term target" below). Service-animal handling is the case
  that proves the model: even at steady-state, ADA-adjacent topics
  should remain operator-reviewed by policy, not by ignorance.

### AccessAgent

Reads from context:
- `property_facts.wifi`
- `property_facts.check_in`
- `property_facts.check_out`
- `property_knowledge.faq` for parking/pool/hot tub/grill/door-code style questions

Optional external service calls:
- likely `ConciergeKnowledgeService.best_faq_answer(...)`

Writes back:
- `AgentDecision`

Emits `ModuleEvent`:
- no

Likely confidence/risk behavior:
- high confidence for direct facts
- medium confidence for FAQ-derived amenity answers

Shipped (Session 3):
- direct-fact path for wifi/check-in/check-out lands at 0.90 confidence
- FAQ fallback lands at 0.75 strong / 0.60 weak
- door-code-flavored questions (`door code`, `lockbox`, `keypad`,
  `key`, `get in`, `how do I enter`, etc.) carry the
  `access_credential_answer` risk flag whether or not the agent
  produced an answer
- all paths recommend `DRAFT_ONLY` while Phase 2 is in the learning
  phase

Door-code carve-out:
- door codes are not amenity facts. In real operator workflows (e.g.
  Beach Habitats), they're per-reservation credentials generated late
  in the turnover cycle and gated by housekeeping + walkthrough
  sign-off. They're issued PROACTIVELY (typically bundled with wifi
  and password) just before arrival, not retrieved reactively from a
  knowledge base.
- the `access_credential_answer` flag must be honored by any future
  session that relaxes `DRAFT_ONLY → AUTO_SEND` for access topics.
  Auto-send for door codes requires reservation-phase context AND
  turnover-gate state (housekeeping complete, walkthrough cleared,
  code issued for this reservation) — see Session 3.5 and the
  "Turnover gate state" Context Gap. Confidence threshold alone is
  not sufficient.
- the FAQ-fallback path in AccessAgent is a stopgap that catches
  door-code questions when no proactive issuance has happened. It
  is not the steady-state answer model.

### EscalationAgent

Reads from context:
- message text
- classification urgency/topic
- any future EQ enrichment
- future escalation workflow context if available

Optional external service calls:
- likely escalation-related services later

Writes back:
- `AgentDecision`

Emits `ModuleEvent`:
- maybe later, but not required to ship the first version

Likely confidence/risk behavior:
- should bias toward empathy + human review
- one agent handles both `complaint` and `emergency`, branching internally on urgency/topic

Shipped (Session 4):
- emergency branch: confidence 0.95, recommended_action=ESCALATE,
  `escalation_emergency` risk flag (hard-stop signal future autonomy
  work must never auto-send through), draft mentions 911 / local
  emergency number, draft does NOT promise specific timing for
  human response
- complaint branch: confidence 0.85, recommended_action=DRAFT_ONLY,
  `escalation_complaint` risk flag (review-first marker), draft
  acknowledges without committing to refunds/comps/credits or
  pre-apologizing for fault
- defensive branch: confidence 0.50, recommended_action=ESCALATE
  for any unexpected topic that lands here (e.g. routing-table drift)
- no FAQ grounding; evidence_used is always []
- no ModuleEvents emitted
- `escalation_emotional_distress` risk flag reserved for Session 7
  EQ enrichment, declared in agent vocabulary but not populated yet

Open copy consideration — liability-tone calibration on complaints:
- The shipped complaint template includes "I'm sorry you're dealing
  with this." That phrasing is sympathy-language, not fault-language,
  and is legally defensible in most US jurisdictions (many states
  have explicit apology laws protecting sympathy expressions). It's
  the right default for general-population guest concerns.
- HOWEVER: in STR specifically, some operators — or their insurance
  carriers — are sensitive about ANY brain-generated language that
  could be read as soft fault-admission, especially during damage
  disputes, refund negotiations, or pre-litigation communications.
  "I'm sorry you're dealing with this" can land that way depending
  on the situation.
- This is NOT a categorical risk like ADA-adjacent topics or
  credential exposure (which are hard-stops). It's a copy-tuning
  consideration. The DRAFT_ONLY default already gives liability-sensitive
  operators full editorial control before send.
- Future work — tracked rather than blocked:
    - Phase 4+ template work should treat operator-level
      "liability tone preference" as a first-class input to
      LLM-composed copy alongside emotional registers, brand voice,
      and situational context.
    - If operator feedback during canary surfaces this as a real
      pain point before Phase 4, an interim per-operator
      "strict-acknowledgment-only" setting could swap the
      complaint template for a more neutral phrasing
      ("Thank you for letting us know. I've passed your message to
      the team to follow up with you personally."). This is
      cheap; we'd add it when we have evidence rather than
      preemptively.
    - Do not silently change the default copy without operator
      review — some operators specifically value the sympathy
      acknowledgment for guest-relations reasons, and removing it
      to placate a different segment is the wrong move.

Known limitation (carry-forward to future autonomy work):
- the agent's `recommended_action=ESCALATE` is advisory; the policy
  gate doesn't currently consume it directly. See Session 4 SHIPPED
  notes above. Today the right behavior emerges from IntakeAgent's
  high urgency + requires_human_review + autonomy_gate's REVIEW
  routing. A future policy refinement should make any specialist's
  ESCALATE recommendation a hard force on final_action.

### BookingInquiryAgent

Reads from context:
- PMS/listing/reservation context from `ContextAdapter`

Optional external service calls:
- yes, likely via provider-agnostic pre-booking context layer

Writes back:
- `AgentDecision`

Emits `ModuleEvent`:
- no

Likely confidence/risk behavior:
- highly dependent on lookup quality
- should be conservative until the context adapter seam is proven


## Context Gaps

- `ContextBuilderAgent` currently exposes `faq_count`, not the full `faq` list.
- Legacy facts only include:
  - `wifi`
  - `check_in`
  - `check_out`
- House rules and most amenities live in FAQ entries, not structured facts.
- Operator policy data is not yet in brain context.
- HouseRulesAgent will be limited until policy/context surfaces are richer.
- **Reservation lifecycle** is not yet in brain context. Today
  `ContextBuilderAgent` infers a coarse lifecycle from intent type only
  (SYSTEM_EVENT → SYSTEM, else IN_STAY). Real lifecycle inference
  (pre_arrival / in_stay / post_stay from the reservations table) is
  Phase 1.4+. This is needed for the door-code-bearing variants of
  AccessAgent (Session 3.5, opt-in) and ProactiveOutreachAgent.
- **Turnover gate state** is an OPTIONAL context surface, populated
  only when an operator has enabled the turnover module (see
  "Optional Modules" below). When present, agents read fields like
  housekeeping_pending / housekeeping_complete / walkthrough_pending /
  cleared_for_issuance / code_issued. When absent, the brain operates
  exactly as it does today and door-code questions stay in
  AccessAgent's FAQ-fallback stopgap mode. The brain must NEVER assume
  this surface is present — it's an enhancement for operators who
  want it, not a precondition for the brain to function.


## Optional Modules

Some operator workflows are valuable but not universal. The brain
should enable them for operators who want them, without forcing the
workflow on operators who don't. The Phase 1.3a `MaintenanceModule`
established the pattern: agents emit decisions, modules do work,
modules are opt-in via registration, the brain degrades gracefully
when a module isn't registered.

This section catalogs optional modules — both shipped and planned —
so future sessions know which behaviors to gate behind module
presence rather than assuming universal availability.

Design principles for optional modules:
- the brain works correctly without any optional module enabled
- enabling a module enhances behavior; disabling it returns to the
  baseline, never breaks the baseline
- modules expose context surfaces that agents READ. They don't
  reach back into agents. Agents check for the presence of
  the surface and degrade gracefully when absent
- module enablement is per-operator (and possibly per-property),
  surfaced through the same feature-flag plumbing the messaging
  brain itself uses (`MESSAGING_BRAIN_RUNTIME` etc.)
- shipping a new optional module never requires changes to operators
  who don't enable it

### Maintenance Module — SHIPPED (Phase 1.3a)

- Owner: `app/services/messaging_brain/modules/maintenance_module.py`
- Triggers: `ModuleEvent` from `MaintenanceAgent`
- Surfaces back: writes to `concierge_maintenance_events` and
  `operator_work_orders`; no context surface (one-way)
- Opt-in mechanism: registered in `ModuleRegistry` at orchestrator
  construction time; shadow mode at the module-execution boundary

### Turnover Module — PLANNED (operator-opt-in, prerequisite for Session 3.5)

- Purpose: documents and tracks the property-turnover workflow
  between guests — housekeeping arrival/completion, operator
  walkthrough, photo verification, door-code issuance.
- Why it's optional: some operators run turnover entirely outside
  the system (Phase 1 "concierge-only" use case), some run it
  partially (housekeeping outside, walkthrough inside), some run
  it end-to-end inside Oyvoda (e.g. Beach Habitats). The brain
  must work for all three.
- Surfaces produced when enabled (read by agents):
  - turnover-gate state for the property's current cycle:
    `housekeeping_pending` / `housekeeping_complete` /
    `walkthrough_pending` / `cleared_for_issuance` / `code_issued`
  - per-reservation door-code value, populated only after the gate
    clears (likely via `reservation_facts.door_code` or a similar
    ContextAdapter-backed surface)
  - photo-verification metadata (count, last verified at, blocking
    items if any)
- Consumers:
  - `AccessAgent` (Session 3.5): door-code path becomes accurate
    rather than FAQ-fallback. Without the module, AccessAgent stays
    in stopgap mode — correct steady state for opt-out operators.
  - `ProactiveOutreachAgent` (planned): door-code-bearing welcome
    packet is conditionally part of the proactive outreach. Without
    the module, the proactive welcome packet still ships (wifi +
    weather + general greeting); it just doesn't include a door
    code, because there isn't one to include yet.
- Operator UX (out of scope for this seam map; documented separately):
  housekeeping arrival/done buttons, walkthrough checklist,
  photo upload + verification flow.
- Phase placement: this is post-Phase-2 module work. Session 3.5
  cannot ship until the module exists, but Session 3 (shipped)
  is unaffected.

### Future optional modules (placeholders — add as they're proposed)

- Vendor-routing module (post-Phase-2): extends `MaintenanceModule`
  with vendor dispatch, ETA tracking, invoice handling.
- Operator-policy module (post-Phase-2): structured policy data
  that supplements FAQ for HouseRulesAgent and others.

## Pre-Booking Integration Map

Inbound flow:
- email transport (Gmail/Microsoft today)
- `TransportAdapter`
- provider-neutral pre-booking inquiry object
- brain

Context enrichment:
- brain calls `ContextAdapter`
- Escapia is the first context adapter

Outbound flow:
- brain returns a draft
- `TransportAdapter` sends via the same email rail

Escapia note:
- Escapia is a context source, not the message transport
- do not model Escapia as the core message service

Status lifecycle:
- rollout gate reads `pre_booking_inquiries.status`
- brain’s role is draft generation, not approval/send
- approval/send flow remains separate and must keep updating:
  - `pending_review`
  - `approved`
  - `replied`
  - `error`

Recommended integration pattern:
- use a `process_inquiry_via_brain(...)`-style wrapper
- do not replace the legacy path wholesale on first pass


## Translation Tables

### InquiryMessage → InboundGuestMessage

Provisional mapping:
- `message_text` → `text`
- `thread_id` → thread-like identity / metadata
- platform/provider value → `source_provider`
- `property_external_id` → `property_code`
- `company_id` → `tenant_id`
- guest identity fields → guest metadata
- synthetic message ID where needed if the upstream shape lacks one

### GuestResponseDraft → InquiryDraft

Provisional mapping:
- `response_text` → draft body
- escalation/review state → approval/review handling

### Pre-booking intents → likely brain topics

Provisional mapping:
- `PET_POLICY` → `house_rules`
- `PROPERTY_AMENITIES` → `access`
- `AVAILABILITY_CHECK` → `booking_inquiry`
- pricing / discount / refund style traffic → `complaint` or escalate path
- local-area questions → `local_recommendation`

These mappings are provisional and should be validated during Session 5.


## Flag / Routing Notes

- `MESSAGING_BRAIN_RUNTIME`
- `MESSAGING_BRAIN_SHADOW_MODE`

Existing concierge brain routing condition lives in [app/api/v1/endpoints/concierge.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/concierge.py).

Recommendation:
- reuse `MESSAGING_BRAIN_RUNTIME` for Phase 2 unless the read pass later proves pre-booking needs a separate rollout gate
- do not pre-emptively split the flag surface


## Known Risks

- pre-booking and concierge are separate systems
- operator policy dependency for house rules
- FAQ matching quality
- booking inquiry is lookup-heavy
- EQ integration must come after `EscalationAgent`
- split-provider pattern will recur
- specialist `recommended_action=ESCALATE` is currently advisory —
  `ResponsePolicyAgent` doesn't consume it directly. The de-facto
  emergency routing today comes from IntakeAgent's high urgency +
  `requires_human_review` + `autonomy_gate`'s REVIEW path; the
  agent's recommendation rides alongside but doesn't drive the
  outcome. A future policy refinement should make any specialist's
  ESCALATE a hard force on `final_action`. Until that lands, future
  autonomy work that loosens DRAFT_ONLY → AUTO_SEND must explicitly
  honor the `escalation_emergency` and `escalation_complaint` risk
  flags as hard blocks, regardless of confidence.
- ADA-adjacent topics (service animals, accessibility accommodations,
  fair-housing protected classes) are policy-sensitive, not just
  knowledge-sensitive. The two-question ADA limit on what an operator
  may ask a service-animal handler means even a mature, knowledge-rich
  brain should likely keep these review-first by policy. Do not relax
  that in service of the "grounded auto-send is the steady state" goal
  without explicit legal review.
- physical-access credentials (door codes, lockbox combos, gate codes)
  are credential-shaped AND workflow-gated. In real operator practice
  (e.g. Beach Habitats) they're generated late in the turnover cycle,
  released only after housekeeping + walkthrough clearance, and
  issued proactively bundled with wifi/password rather than retrieved
  reactively. AccessAgent flags these with `access_credential_answer`
  and that flag must remain a hard block on auto-send. Door-code
  auto-send specifically requires the optional turnover module to be
  enabled AND its context to confirm the gate has cleared for the
  current reservation — see Session 3.5 and the "Optional Modules"
  section. Confidence threshold alone is never sufficient relaxation,
  and operators without the turnover module enabled stay in the
  FAQ-fallback stopgap mode permanently — that's correct, not a gap.


## Long-term target (post-Phase 2)

The end-state for the brain is not perpetual `DRAFT_ONLY`. As operator
knowledge accumulates and agents learn to distinguish settled topics
from unsettled ones, the policy gate should allow auto-send when:

- the answer is grounded in operator-authored knowledge
- the agent recognizes the question correctly
- no risk flags are present
- the property's autonomy policy permits it

The progression is:

- now: `DRAFT_ONLY` everywhere while we learn what operators want
- next: `DRAFT_ONLY` everywhere except a small allowlist of
  high-confidence, low-risk topics (door codes, wifi, check-in time)
- mature: `AUTO_SEND` on grounded answers; `DRAFT_ONLY` on ambiguous;
  `ESCALATE` on emergency / complaint / policy gaps

Carve-out: ADA-adjacent topics stay review-first regardless of
knowledge maturity. See "Known Risks" above.

Phase 4+ template/copy work — inputs to consider:
When LLM-composed copy replaces today's templated drafts, the
composer should treat the following as first-class inputs, not
afterthoughts:
- emotional register (calm informational, warm conversational,
  apologetic but neutral, urgent without panicking, etc.)
- operator brand voice (settable at operator level)
- operator liability-tone preference (settable at operator level
  — some STR operators specifically want sympathy acknowledgment
  on complaints for guest-relations reasons; others, or their
  insurance carriers, want strict neutrality during damage or
  refund situations. See EscalationAgent's "Open copy consideration"
  note above.)
- situational context (lifecycle phase, prior message history,
  detected urgency, EQ signals from Session 7)
- known carve-outs (ADA-adjacent must remain review-first; emergency
  must always include 911 reference; door-code answers gated on
  Turnover Module state)

This is captured here so future sessions don't quietly walk away from
the carve-out while pushing for less drafting overall.


## Phase 1 Handoff State

- Phase 1 is complete and pushed
- brain is reachable from `/concierge/message`
- default-off canary confirmed
- no operator sees new behavior until the flag is explicitly enabled
- Phase 2 work should stay behind the same safe-by-default philosophy


### Session 9 — SHIPPED

Annotation:
- committed to git as part of the Session 12 catch-up commit `316e8c2`

Deliverable:
- `LLMIntakeAgent` — LLM-based intent classifier for the messaging brain

Dependencies:
- Sessions 5–8 (provider-agnostic pre-booking layer + EQ enrichment + integration hardening)
- Anthropic and/or Groq API key in worker environment

Files (new):
- `app/services/messaging_brain/agents/llm_intake_agent.py`
- `tests/unit/test_llm_intake_agent.py`
- `tests/unit/test_llm_intake_agent_smoke.py`

Files (modified):
- `app/services/orchestration/messaging_brain_contracts.py`
  - Added `sub_intents: List[str]` and `extracted_constraints: Dict[str, Any]`
    fields to `MessageClassification` (additive, optional, defaults preserve
    existing-caller compatibility)
  - Added `ClassifierMetadata` model
  - Added `classifier_metadata: Optional[ClassifierMetadata]` field to
    `AgentAuditRecord`
  - Added `ClassifierMetadata` to `__all_per_message_contracts__`
- `app/services/messaging_brain/orchestrator.py`
  - Constructor now builds both `IntakeAgent` (keyword) and `LLMIntakeAgent`
    when no intake is injected. Injected-intake test seam preserved.
  - Added `_select_intake()` that resolves the LLM-vs-keyword choice at
    message-handling time using the `MESSAGING_BRAIN_LLM_INTAKE` flag.
    Flag-lookup failures fall back safely to keyword.
  - `handle_inbound_message()` calls `classify_with_metadata()` when the
    selected intake supports it (LLM path), else `classify()` (keyword
    path with synthesized minimal metadata). Attaches metadata to the
    audit record.
- `app/services/feature_flags.py`
  - Added `MESSAGING_BRAIN_LLM_INTAKE` flag constant
  - Added `is_messaging_brain_llm_intake_enabled()` lookup function
  - Default OFF for all tenants

Behavior:
- Provider chain: Anthropic Claude Haiku 4.5 (primary) → Groq llama-4-scout
  (secondary) → keyword `IntakeAgent` (ultimate fallback).
- Per-provider timeout: 2.5s. Total budget: 4.0s. Keyword fallback has no
  timeout (local matching).
- Same `MessageClassification` output contract as keyword intake. Two new
  fields (`sub_intents`, `extracted_constraints`) populated by LLM path,
  empty when keyword ran.
- Stateless across calls. Safe to share one instance across concurrent
  message handlers (no mutable per-call state on the agent).
- Topic coercion enforced: pre-booking sub-intents (pricing, availability,
  amenities, group_size, sleeping_arrangement, portfolio_search) coerce to
  `booking_inquiry` with the original moved to `sub_intents`.
- Early-check-in / late-checkout-shaped topics coerce to `late_checkout`
  preserving existing brain semantics.
- `system_*` topics from `KNOWN_INTENT_TOPICS` are reserved for proactive
  outreach and coerce to `general` if emitted on inbound classification.
- Heavy coercion (invalid JSON, missing required field, invalid topic,
  malformed constraints) forces `requires_human_review = True` regardless
  of model output.
- Light one-way sub_intent normalization (snow_chains → road_access,
  discount_request → discount, etc.) — five rules total, intentionally
  small.
- Every coercion path produces an audit note in
  `ClassifierMetadata.coercion_notes` for queryability.

Production status:
- Code lands; flag stays OFF. No production traffic affected.
- Session 12 (shadow-mode rollout for Beach Habitats) is when the flag
  gets flipped on for any real operator traffic.

Open questions (surfaced during Session 9 design, deferred to later sessions):

1. Should `late_checkout` split into `arrival_timing` and `departure_timing`?
   Mary's case (early check-in) is the canonical example. The current brain
   semantics group both under `late_checkout` (reflected in the existing
   keyword `IntakeAgent` translation), which the LLM prompt preserves.
   Real operator behavior on these may show that the split matters.
   Revisit when there's data.

2. The brain taxonomy lacks a `reservation_logistics` /
   `payment_coordination` topic. Matthew's case is the canonical example
   (existing-reservation payment-handling logistics). The Session 9
   classifier puts these in `general` with `requires_human_review = True`,
   which is operationally safe but architecturally awkward. A future
   taxonomy session may add a dedicated topic.

3. The `dispatch_pre_booking` legacy path uses its own keyword classifier
   in `app/services/concierge/pre_booking_auto_send.py` (the
   `InquiryIntentClassifier`). That's the path Beach Habitats actually
   runs on today. Session 9 doesn't touch that classifier — the brain's
   `LLMIntakeAgent` only takes effect when `MESSAGING_BRAIN_RUNTIME` is
   on for the operator. The architectural commitment is that future
   operators run on the brain, not the legacy path; until that cutover
   (Session 13), the legacy keyword classifier still ships drafts for
   live traffic.


## Resume Line

Resuming Oyvoda Phase 2 — start with Session 10 (Eval infrastructure).

Sessions 2–9 are shipped:
  - Sessions 2–4: HouseRulesAgent, AccessAgent, EscalationAgent in brain
  - Session 5: Provider-agnostic pre-booking layer
  - Session 6: BookingInquiryAgent
  - Session 7: EQ enrichment in IntakeAgent
  - Session 8: dispatch_pre_booking integration with shadow-mode + flag-gating
  - Session 9: LLMIntakeAgent (keyword IntakeAgent retained as fallback)

Session 10 scope:
  - Eval set table (`brain_eval_cases`)
  - Nightly job comparing keyword vs LLM classifier against the eval set
  - Per-market accuracy reporting (foundation for multi-operator scaling)
  - First seed cases: the 7 Session 9 golden-set messages plus operator
    contributions as they accumulate

Success criterion: have a measurable accuracy number for each classifier
that updates nightly, broken out by market type. This is what makes the
multi-operator partner conversation real — quality changes become
observable rather than vibes-based.

Note: Sessions 11–13 (ContextBuilderAgent parity, shadow-mode rollout,
brain cutover for Beach Habitats) all depend on Session 10 being
shipped first. We need eval before flipping any flags for real traffic.

Note: Sessions 2.5 and 3.5 remain open as scheduled refinements.


### Session 11 — SHIPPED

Annotation:
- committed to git as part of the Session 12 catch-up commit `316e8c2`

Deliverable:
- `ContextBuilderAgent` parity with the legacy concierge path's evidence assembly

Scope:
- brought guidebook richness scoring, property evidence retrieval, and
  learned-preference loading into the brain via shared concierge helpers,
  behind a new feature flag, default OFF

Architectural decision:
- share read-only retrieval helpers from
  `app/services/concierge/context_builder.py` rather than reimplement on
  the brain side
- bounded coupling cost since legacy goes away in Session 13; reimplementation
  cost would compound across the shadow window
- `build_prebooking_knowledge_lines` deliberately not shared because it returns
  rendered string lines, which is the wrong abstraction level for the brain
- `build_preference_context` shared as a temporary string adapter and flagged
  for future structured replacement

Steps shipped:

1. Raw guidebook retention
   - added `extract_guidebook_knowledge()` in new
     `app/services/messaging_brain/agents/context_builder_adapters.py`
   - added `guidebook_knowledge` to `GuestContextBundle`
   - wired into `build()` and `build_for_proactive()`
   - left existing `_extract_facts()` behavior unchanged
   - focused unit tests cover populated / partial / empty / malformed / `None`
     inputs and the shallow-copy boundary
   - existing `_extract_facts`, `AccessAgent`, and `HouseRulesAgent` test
     suites stayed green

2. Legacy-shape adapter
   - added `to_legacy_prebooking_property_data()` to
     `context_builder_adapters.py`
   - allowlists `facts`, `sections`, `faq` only, so future fields in
     `guidebook_knowledge` do not silently leak into the legacy contract
   - cross-system contract tests import the real shared concierge helpers and
     verify they consume adapter output without drift
   - assertions deliberately stay loose on score values and label pinning to
     avoid wrong-direction coupling on concierge's scoring algorithm

3. Flag-gated runtime wiring
   - added `MESSAGING_BRAIN_RICH_CONTEXT` /
     `OYVODA_MESSAGING_BRAIN_RICH_CONTEXT`, default OFF
   - added `is_messaging_brain_rich_context_enabled()` in
     `app/services/feature_flags.py`, matching the existing brain-flag pattern
   - added `_load_rich_context()` as the single seam for Session 12 shadow
     rollout
   - added `guidebook_richness`, `guidebook_evidence`,
     `learned_preferences_block` to `GuestContextBundle`
   - wired both `build()` and `build_for_proactive()`
   - failure handling matches legacy precedent:
     - warning log + empty defaults for shared-helper failures
     - debug log + empty string for preference-context failures
   - inbound path uses `classification.intent_topic`
   - proactive path uses `intent.trigger_type`
   - proactive path passes `message_text=""`, so `guidebook_evidence` is
     naturally `[]` on proactive; message-driven retrieval semantics preserved
     without synthesizing
   - focused unit tests on `_load_rich_context()` cover gate behaviors, happy
     path, partial-failure modes, argument-passing correctness, and the
     proactive empty-message contract

4. End-to-end public-method tests
   - appended new tests to `tests/unit/test_context_builder_agent_faq.py`
   - covered flag-off and flag-on through `build()` and `build_for_proactive()`
   - covered argument flow for message text, intent topic, and trigger type
   - covered `db_session=None` short-circuit and partial preference failure
     through the public methods
   - added a regression guard that the existing FAQ contract is undisturbed
     when rich context is on
   - used explicit `rich_context_on` / `rich_context_off` fixtures to make
     test flag state unambiguous
   - left the existing tests alone so they continue to exercise the off-path
     implicitly through the default-off env

5. Real-Postgres integration test
   - added `tests/integration/test_context_builder_agent_rich_context_postgres.py`
   - used a co-located `real_db_for_brain` fixture rather than Session 10's
     `real_db`, because the `brain_eval_*` table guard is the wrong abstraction
     for this path
   - seeded concierge knowledge through
     `ConciergeKnowledgeService.create_dashboard_entry()` instead of raw SQL or
     ORM inserts, so the test does not pin column names
   - patched the flag at the Python layer because the cross-system contract
     under test is brain -> knowledge service -> concierge helpers, not
     brain -> feature flag service
   - asserted:
     - `guidebook_knowledge` populates from real upstream data
     - richness label is in the valid non-`none` set
     - evidence retrieval returns at least one wifi-relevant hit for a
       wifi-targeted message
     - preference block is empty string for an unseeded operator, matching
       `build_preference_context`'s no-data contract
   - cleanup bounded by per-test `tenant_id` + `property_external_id` token
   - operational note: the first in-sandbox run failed because `asyncpg` could
     not reach Postgres under sandbox network restrictions; the authoritative
     pass was the out-of-sandbox rerun. Sandboxed runners should skip this test
     or run it outside the sandbox.

6. Eval / serialization sanity check
   - resolved by inspection; no code change
   - Session 10's eval recorder persists classifier outputs only
     (`actual_intent_topic`, `actual_sub_intents`, `actual_review`, etc.)
   - `scripts/run_brain_eval.py` does not invoke `ContextBuilderAgent`
   - therefore there is no bundle-serialization contract to pin and no eval
     smoke test that would meaningfully exercise rich context
   - the four new bundle fields are intentionally out of scope for the
     existing eval pipeline

Known gap (not in scope, not blocking):
- eval harness covers classifier outputs only
- rich-context fields (`guidebook_richness`, `guidebook_evidence`,
  `learned_preferences_block`) have no golden-case coverage
- Session 12 shadow-mode production signal is the primary regression detector
- if that signal proves insufficient, a future session should extend the eval
  harness to invoke `ContextBuilderAgent` and record bundle snapshots

Discipline notes for future sessions:
- the "ground truth via paste, not injected reads" rule held throughout
  Session 11 and prevented multiple guess-and-fail loops; continue it
- the split between share / reimplement / temporary adapter is worth
  re-examining at Session 13 cutover
- the temporary string adapter for `build_preference_context` is the most
  likely cleanup candidate; the two pure-function shares can stay until the
  legacy file is deleted
- ownership of the richness-scoring magic numbers
  (`0.08`, `0.1`, `0.03`, `0.4`, `0.75`) remains ambiguous; concierge wrote
  them and brain inherits them. Settle ownership before Session 13.

Sessions 12 and 13 unblocked:
- Session 12: shadow-mode rollout flips `MESSAGING_BRAIN_RICH_CONTEXT` on for
  production tenants and compares brain vs. legacy
- Session 13: cutover; legacy path retired


### Session 12 — SHIPPED — `7e25c6a`

Deliverable:
- shadow-mode observation infrastructure for `MESSAGING_BRAIN_RICH_CONTEXT`

Scope:
- added production-safe shadow logging for the rich-context seam so the brain
  can compute rich-context fields, record what would have happened, and still
  return empty values while the real rich-context flag remains off

Files (new):
- `app/services/messaging_brain/agents/rich_context_shadow_store.py`
- `db/migrations/versions/052_rich_context_shadow_observations.py`
- `tests/unit/test_context_builder_agent_rich_context_shadow.py`
- `tests/unit/test_rich_context_shadow_store.py`
- `tests/integration/test_rich_context_shadow_store_postgres.py`

Behavior:
- added `MESSAGING_BRAIN_RICH_CONTEXT_SHADOW` /
  `OYVODA_MESSAGING_BRAIN_RICH_CONTEXT_SHADOW`, default OFF
- added `rich_context_shadow_observations` table
  (`052_rich_context_shadow_observations`, `down_revision =
  "051_brain_eval_tables"`)
- each shadow row stores:
  - tenant
  - property
  - message id
  - intent
  - richness / evidence / preferences as computed under the shadow path
  - typed `shadow_exceptions` JSONB capturing per-sub-computation failures
- added `rich_context_shadow_store.py` writer with:
  - `ShadowExceptionEntry` and `ShadowExceptions` `TypedDict`s
  - SQLAlchemy `text()` + named params, matching Session 10's eval store style
  - internal commit, matching inbound-path write-helper convention
  - warning-log + swallow behavior so shadow logging can never affect the
    guest path
- extended `ContextBuilderAgent._load_rich_context()` with optional
  `message_id`
- when rich context is OFF and shadow is ON and `message_id` is present:
  - compute richness / evidence / preferences
  - write one observation row
  - return `({}, [], "")` so production behavior is unchanged
- split the old combined helper try-path into three separate try blocks
  (richness, evidence, preferences) so shadow rows can attribute failures
  per sub-computation and still keep partial successes
- left `to_legacy_prebooking_property_data()` unwrapped because it is a pure,
  infallible adapter
- updated `build()` to thread `message.message_id`
- proactive callers stay unaffected because shadow lookup is skipped when
  `message_id` is absent

Verification:
- migration applied successfully:
  `051_brain_eval_tables -> 052_rich_context_shadow_observations`
- verification slice: 46 passed total
- real-Postgres writer integration: 3 passed outside sandbox
- in-sandbox integration now skips cleanly instead of erroring during fixture
  teardown

Apply-time corrections folded in:
- bumped `tests/unit/test_alembic_history.py` to the new head revision
- updated two older `_load_rich_context()` tests in
  `tests/unit/test_context_builder_agent_rich_context.py` to match the
  intentional split-try partial-success behavior
- fixed a latent integration-fixture cleanup bug where `pytest.skip()` inside
  the connectivity check could leave teardown trying to reuse a closed session

Boundary note:
- Sessions 9, 10, and 11 had been applied to the worktree but never committed
  to git
- catch-up commit `316e8c2` (`Catch up Sessions 9-11 messaging brain work`)
  backfilled that uncommitted work in the same boundary-cleanup pass
- per the `(b1)` decision, stacked spine files
  (`feature_flags.py`, `context_builder_agent.py`,
  `messaging_brain_contracts.py`,
  `test_context_builder_agent_rich_context.py`) were committed in their
  current state rather than being unpicked into per-session hunks

Threads carried forward:
- ownership of the richness-scoring magic numbers remains ambiguous
  (concierge wrote them; brain currently inherits them)
- eval harness still covers classifier outputs only; if shadow signal proves
  insufficient, a future session should extend eval to invoke
  `ContextBuilderAgent` and record bundle snapshots
- acceptable-divergence threshold is intentionally data-dependent and should be
  answered from actual shadow rows, not by pre-deciding a threshold now
- sandboxed runners still need the import-guard + connectivity-smoke-check
  skip pattern for Postgres integration tests

Discipline correction:
- `SHIPPED` now means committed to git, with the SHA recorded in the session
  record
- `APPLIED` / `VERIFIED` is the weaker claim for work that is present in the
  worktree and tested but not yet committed
- this correction surfaced because four sessions of previously "shipped"
  work were discovered to be uncommitted and had to be backfilled in
  `316e8c2`

Session 13 dependency:
- legacy cutover depends on Session 12 rollout producing enough divergence
  signal to declare the rich-context path safe
- first tenant remains Beach Habitats
- rollout starts by enabling `MESSAGING_BRAIN_RICH_CONTEXT_SHADOW`
  per-tenant so observations land in `rich_context_shadow_observations`
  before any Session 13 cutover decision
