# Downstream Uniformity Audit — 2026-05-04

Reconciliation note auditing the consumer side of the canonical
contract: components downstream of extraction that read messages,
draft state, or routing decisions. Companion to the intake path
reconciliation (`8a425df`) which covered the writer side.

This is a Phase 1b audit. It produces a mapping artifact, not code
changes. Subsequent sessions execute against the findings here.

## Purpose

The architecture document (`9ad2dc5`) commits in Section 4 to:

> "Every component downstream of extraction operates on canonical
> messages, not on source-specific representations."

This commitment is partial in current code. Some downstream components
consume `CanonicalInboundMessage` or values derived from it; others
branch on source channel or provider in ways that bypass the canonical
contract.

This note enumerates each downstream component, classifies its current
contract relationship, identifies source-aware paths that need
disposition, and recommends forward work per component.

## Scope

**In scope (components):**
- Routing (system-generated / in-stay / pre-booking decisions)
- Property resolution (mapping messages to canonical properties)
- Knowledge retrieval (property facts, operator policies, contextual data)
- Brain / response generation
- Adversarial review
- Policy enforcement (hard policy gates)
- Operator review queue
- Observability (metrics, logs, audit trails operating on canonical fields)

**Out of scope (components):**
- Reply transport (legitimately source-aware per architecture
  Section 4 permitted exceptions)
- `channel_constraints` field on canonical messages (legitimate
  carrier of source-derived constraints)
- Inbound transport adapters and extraction strategies (covered by
  intake path audit `8a425df` on the writer side)

**In scope (audit dimensions):**
- Does the component consume canonical messages or canonical-derived values?
- Does the component branch on source channel/provider/platform?
- Where source-awareness exists, is it within the permitted exceptions or genuine bypass?

**Out of scope (audit dimensions):**
- Implementation design of any canonical migration
- Performance characteristics of canonical vs source-specific paths
- Test coverage of canonical handling

## Classification legend

Each component is tagged on one axis.

- **Canonical-only** — consumes canonical messages or canonical-derived
  values, no source branching outside permitted exceptions
- **Canonical-mostly** — primarily canonical with minor source-aware
  paths that fall within or near permitted exceptions
- **Source-aware** — branches on source channel/provider/platform in
  ways that bypass the canonical contract
- **Mixed** — canonical for some operations, source-aware for others
  without clear architectural justification

## Method

The audit proceeds in three rounds:

**Round 1 — Component mapping.** Grep across `app/services/` to
locate the code surfaces for each in-scope component. Establishes
which files implement each component and provides initial signal on
contract relationship.

**Round 2 — Targeted code reads.** For components where Round 1 left
classification ambiguous, pull function signatures and call sites to
determine whether canonical messages or canonical-derived values flow
through, or whether source-specific fields drive logic.

**Round 3 — Cross-cutting safety controls.** For components where
Round 2 surfaced legacy/brain split (adversarial review, policy
enforcement), additional pulls determine whether the controls run on
both paths or only one.

For each component, classification combines all rounds. Where the
audit could not resolve a question from code alone (e.g., whether a
source-aware path is a legitimate architectural exception), the
question is recorded for architectural decision rather than guessed.

## Component inventory

The audit identified eight in-scope components. Each is classified
with rationale and notes.

### Routing

**Classification:** Mixed

**Locations:**
- `app/services/integrations/email_routing.py` — message-class routing
  (system_event / in_stay / pre_booking)
- `app/services/integrations/email_dispatch.py` — route_outcome
  recording
- `app/services/messaging_brain/agents/agent_router.py` — brain-side
  routing
- `app/services/integrations/gmail_inbox_poller.py:1255` —
  poller-side `_route_message`

**Rationale:**
The high-level routing decision is provider-neutral: classifies into
system_event, in_stay, or pre_booking based on canonical-shaped
predicates. However, the routing operates on `parsed` integration
objects, not `CanonicalInboundMessage`. Downstream dispatch threads
source-shaped fields (`parser_source`, `platform_listing_id`,
`platform_unit_id`, `parsed.platform`) into route_outcome metadata
and fallback reasons.

The routing logic is not strongly source-branching. The classification
is mixed rather than canonical-mostly because the routing surface
operates on pre-canonical types throughout, even when the decisions
themselves are provider-neutral.

### Property resolution

**Classification:** Source-aware (with architectural decision pending)

**Locations:**
- `app/services/property_canonical_service.py:29` —
  `resolve_property_code`
- `app/services/concierge/property_router.py:113` — `PropertyRouter`
- `app/services/concierge/knowledge_service.py:270` —
  `_resolve_property_external_id`
- `app/services/integrations/gmail_inbox_poller.py:2095` —
  `_resolve_property_code`

**Rationale:**
The canonical service's `resolve_property_code` accepts source-specific
identifiers as first-class inputs:

```python
async def resolve_property_code(
    self,
    tenant_id: UUID,
    *,
    platform_listing_id: str = "",
    platform_unit_id: str = "",
    property_name: str = "",
    platform: str = "",
) -> str:
```

Property resolution is explicitly reasoning over source-originated
identity shapes. The poller's resolver call site threads
`parsed.platform_listing_id`, `parsed.platform_unit_id`, and
`parsed.platform` directly into the canonical service's signature.

**Architectural question:**
Property identity is inherently cross-platform: Vrbo, Airbnb,
Booking, and direct PMS integrations each use different identifier
formats. Resolving them requires knowing what kind of identifier
exists. This is structurally similar to how `channel_constraints`
is a permitted exception — source-specific data legitimately
required for cross-boundary operations.

The architecture document does not currently carve out property
identity as a permitted exception. It should explicitly decide:
either property identity is a legitimate exception (and the audit's
finding becomes a documentation gap rather than a debt finding), or
property identity should be canonicalized at the contract boundary
(and the source-aware classification stands as debt).

This question cannot be resolved from code alone. It is recorded in
the open questions section.

### Knowledge retrieval

**Classification:** Canonical-mostly

**Locations:**
- `app/services/concierge/knowledge_service.py` — primary surface
- `app/services/messaging_brain/agents/house_rules_agent.py:46` —
  imports knowledge service
- `app/services/messaging_brain/agents/access_agent.py:87` — imports
  knowledge service
- `app/services/messaging_brain/agents/context_builder_agent.py:68` —
  imports knowledge service
- `app/services/messaging_brain/pre_booking.py:109` —
  `operator_policies` field on brain inquiry

**Rationale:**
Knowledge retrieval operates on tenant + property identity, not on
source channel or provider. The `knowledge_service` is shared
across the brain and the legacy concierge path. The same retrieval
results feed `messaging_brain/agents/*` and `pre_booking_auto_send`.

Some downstream consumers (e.g., `pre_booking_auto_send.py:852`'s
`pet_ok = operator_policies.get("pet_policy") == "allowed"`) read
retrieved knowledge through pre-canonical patterns, but the
retrieval itself does not branch on source.

### Brain / response generation

**Classification:** Canonical-mostly

**Locations:**
- `app/services/messaging_brain/pre_booking.py:335` —
  `PreBookingBrainOrchestrator`
- `app/services/messaging_brain/orchestrator.py:191` —
  `GuestMessageBrainOrchestrator`
- `app/services/concierge/pre_booking_auto_send.py:1926` —
  `PreBookingPipelineOrchestrator` (legacy)
- `app/services/concierge/pre_booking_auto_send.py:2300` —
  `process_pre_booking_inquiry_with_draft` (legacy)

**Rationale:**
The newer `messaging_brain` orchestration uses an explicit
provider-neutral intermediate shape:

```python
@dataclass(frozen=True)
class PreBookingInquiry:
    """Provider-neutral inbound pre-booking inquiry."""
```

It carries source-ish metadata (`transport_provider`,
`context_provider`, `platform`) but converts to the brain's
inbound contract via `inquiry.to_inbound_message(...)` before
handling. That is the partial-migration pattern: a provider-neutral
shape sitting one layer above a canonical contract, converting at
the boundary.

The legacy `pre_booking_auto_send` orchestration runs alongside the
newer brain. Whether they handle different traffic, run redundantly,
or one supersedes the other is not fully clarified by this audit.
Both orchestrations exist; the brain-side is more canonical-aware.

### Adversarial review

**Classification:** Mixed (with material asymmetry between paths)

**Locations:**
- `app/services/concierge/pre_booking_auto_send.py:1799` —
  `return fallback, "fallback_adversarial_review"`
- `app/services/concierge/hallucination_guard.py` —
  `check_grounding`
- `app/services/concierge/response_reviewer.py:310` —
  `review_concierge_response` adversarial prompt
- `app/services/messaging_brain/` — **no hits** for
  `review_concierge_response` or `check_grounding`

**Rationale:**
Adversarial review exists in the legacy concierge path. The reviewer
accepts a legacy text bundle (`guest_message`, `draft_response`,
`source_context`, `lifecycle_stage`, `property_name`), not a
canonical message object. Both Anthropic and Groq adversarial
backends are wired in.

The newer `messaging_brain` path does not invoke
`review_concierge_response` or `check_grounding`. A grep across
`app/services/messaging_brain/` returned no calls.

This is the audit's most consequential finding. The architecture
commits to generate-and-check as a structural pattern: wherever
agentic output affects the world, an independent check verifies
before action. The legacy path implements this. The brain path,
which is the more canonical-aware orchestration, does not appear to.

The split is not "two equivalent implementations of adversarial
review." It is "adversarial review present on one path, absent on
the other."

### Policy enforcement

**Classification:** Mixed (with material asymmetry between paths)

**Locations:**
- `app/services/messaging_brain/agents/response_policy_agent.py` —
  newer brain-side policy agent
- `app/services/concierge/pre_booking_handler.py:485` —
  `InquiryPolicyChecker` (Escapia handler path)
- `app/services/concierge/pre_booking_auto_send.py` —
  `check_inquiry_policy` and per-intent policy lambdas (legacy
  primary path)

**Rationale:**
The brain-side `response_policy_agent` is, per its own inline
comment, a shell:

> "Phase 1.3: policy_warnings is always [] — no policy linter yet.
> Phase 1.4+: feed in pre_booking_auto_send confidence checks,
> knowledge-gap warnings, etc."

Substantive policy logic remains in two legacy locations:

1. `pre_booking_auto_send.py` — the primary email-bridged path's
   `check_inquiry_policy` with per-intent rules, pricing-flag logic,
   and pet-policy resolution
2. `pre_booking_handler.py` — the Escapia handler's own
   `InquiryPolicyChecker`

This is structurally analogous to the adversarial finding: the
newer brain-side surface exists but does not yet enforce. Policy
enforcement is not yet uniformly centralized behind the newer brain
architecture.

### Operator review queue

**Classification:** Canonical-mostly

**Locations:**
- `app/services/operator/prebooking_queue_service.py:27` —
  `sync_draft`
- `app/services/operator/prebooking_queue_service.py:381` —
  `INSERT INTO operator_prebooking_queue_read_models`

**Rationale:**
The queue read model stores substantively canonical-aligned fields:

```python
INSERT INTO operator_prebooking_queue_read_models (
    tenant_id, guest_thread_id, draft_id, thread_id, source_message_id, platform,
    source_provider, guest_name, guest_email, message_text,
    latest_guest_turn, prior_thread_context, draft_text, final_reply,
    intent, asks_json, policy_flags, policy_warnings,
    property_external_id, property_name, property_binding_candidates,
    selected_property_code, property_match_type, route_outcome,
    draft_source, fallback_reason, prior_operator_commitments,
    confidence, latest_turn_confidence, latest_turn_extracted,
    ...
)
```

Most fields here are canonical-derived (`source_message_id`,
`source_provider`, `latest_guest_turn`, `prior_thread_context`,
`property_binding_candidates`, `selected_property_code`,
`property_match_type`, `route_outcome`, `draft_source`,
`latest_turn_confidence`, `latest_turn_extracted`). Some legacy
fields persist (`platform`).

The queue is fed from multiple writers (Path 1, Path 2, Path 3 from
the intake audit), so its inputs are upstream-mixed even though its
shape is largely canonical-aligned. The classification is canonical-mostly
because the read model itself is structured around canonical fields,
even when legacy upstream feeders convert into that shape at the
seam.

### Observability

**Classification:** Canonical-mostly

**Locations:**
- `app/services/messaging_brain/audit.py:169-170, 247-250` —
  audit records use `source_channel`, `source_message_id`,
  `source_provider`
- `app/services/messaging_brain/agents/maintenance_agent.py:226-227` —
  same pattern
- `app/services/messaging_brain/modules/maintenance_module.py:282-283` —
  same pattern
- `app/services/messaging/message_event_store.py` (post-`a9b09ef`) —
  configured logger, structured error logs

**Rationale:**
Within the `messaging_brain` surface, observability is canonical-aligned.
Audit records, maintenance modules, and module payloads all carry
canonical fields (`source_channel`, `source_message_id`,
`source_provider`) as structured signal.

The legacy concierge surface's observability coverage is thinner. The
2026-05-03 incident showed `message_event_store.py` had no logger at
all until `a9b09ef`. The intake-path audit's exception-path patch
(`c7f463f`) addressed three specific writers. Beyond those, the
broader observability state of the legacy surface is not exhaustively
audited (E5 scope).

The component-level observability that this audit checked is
canonical-mostly. The deeper surface-level observability audit (E5)
remains pending.

## Current state read

The audit reveals three distinct findings, each with separate
architectural implications.

**Finding 1: One architectural fact, multiple symptoms.**

The eight component classifications are not eight separate findings.
They reflect a single architectural fact: a partial migration toward
the canonical contract is in progress, with the migration furthest
along in `messaging_brain/` and furthest behind in legacy concierge
orchestration and integrations.

The components downstream of extraction split cleanly along this
line:
- `messaging_brain/` surfaces (knowledge retrieval, brain, queue
  read model, audit/observability) are canonical-mostly
- Legacy concierge surfaces (pre_booking_auto_send orchestration,
  pre_booking_handler, response_reviewer) are pre-canonical or
  source-aware
- Integration surfaces (email_routing, email_dispatch, poller
  resolvers) operate on pre-canonical `parsed` shapes

The pattern is consistent. There is not a different problem in each
component; there is one structural migration in progress, surfacing
differently per component.

**Finding 2: Uneven safety guarantees from partial migration.**

The most consequential finding. Two of the architecture's load-bearing
downstream controls — adversarial review and policy enforcement —
are materially absent on the newer brain path. They exist on the
legacy concierge path and have been built up substantially there.
On the brain path, the corresponding agents are either not invoked
(adversarial review) or shells without enforcement (policy agent).

The architecture commits to generate-and-check as a structural
pattern. Today, that pattern is enforced for inquiries that flow
through the legacy path. Inquiries that flow through the brain path
do not get the same safety guarantees.

This is a real production-relevant gap, not just structural debt.
Operators relying on adversarial review to catch hallucinations get
that guarantee from one path and not the other. Whether a specific
inquiry gets adversarially reviewed depends on which orchestration
handled it.

Observed exposure as of 2026-05-04 is limited: 7 of 266 inquiries in
the last 30 days show brain-path evidence (3 with normalization
attribution, 4 additional with policy_warnings evidence only),
concentrated on 2026-05-03. The gap is real and actively producing
live drafts without uniform safety controls; it is not yet at scale.

**Finding 3: Property identity is an architectural decision, not just a
classification.**

Property resolution is the only component that is genuinely
source-aware by design intent rather than by migration debt. The
canonical service explicitly accepts platform-specific identifiers
as first-class inputs because property identity is a cross-boundary
concern — different platforms use different identifier formats.

This may be a legitimate permitted exception that the architecture
document does not yet name. Or it may be debt that should be
canonicalized. The decision requires architectural judgment about
whether property identity belongs in the same exception category as
reply transport and channel constraints.

This finding is recorded as an open question rather than a gap.
The classification (source-aware) reflects current code behavior;
the disposition is pending architectural decision.

## Gap analysis

The architectural commitment from Section 4 of the architecture
document requires every component downstream of extraction to operate
on canonical messages. Current state per component:

| Component | Classification | Gap from commitment |
|-----------|----------------|---------------------|
| Routing | Mixed | Operates on pre-canonical `parsed` types; high-level decisions are provider-neutral but the surface is not canonical-typed |
| Property resolution | Source-aware | Resolver accepts platform-specific identifiers as first-class inputs; pending architectural decision on permitted exception status |
| Knowledge retrieval | Canonical-mostly | Minor gap; some downstream consumption uses pre-canonical patterns |
| Brain | Canonical-mostly | Newer orchestration is canonical-aligned; legacy orchestration runs alongside |
| Adversarial review | Mixed (asymmetric) | Present on legacy path, absent on brain path |
| Policy enforcement | Mixed (asymmetric) | Substantive logic on legacy path, brain-side agent is a shell |
| Operator review queue | Canonical-mostly | Read model is canonical-aligned; upstream feeders are mixed |
| Observability (component-level) | Canonical-mostly | `messaging_brain` surfaces canonical; legacy surface coverage thinner |

The broader gap statement: the partial migration creates uneven
behavior across what the architecture commits to as uniform
downstream processing.

## Recommended forward work

The forward work splits into three priorities. Sequencing reflects
the asymmetric-safety finding (Finding 2) being the highest-priority
gap, followed by structural migration work, with the property
identity decision as a separate architectural item.

### Priority 1 — Close the safety control asymmetry

These items address the production-relevant gap from Finding 2: the
brain path produces drafts without the safety controls that exist on
the legacy path.

1. **Decide whether brain-path drafts go through the legacy
   adversarial reviewer.** The simplest disposition is wiring the
   brain's draft output into `review_concierge_response` before it
   surfaces to operators. The reviewer accepts a text bundle, not a
   canonical message, so adapting brain output to that bundle is a
   small interface change rather than a redesign.

2. **Decide whether brain-path drafts go through the legacy policy
   checker.** Similar disposition for `check_inquiry_policy`. Brain
   output gets policy-gated before it surfaces.

3. **Or alternatively: move adversarial review and policy enforcement
   to canonical-typed implementations.** Larger scope, but produces
   the architecturally clean target state. Either of these
   capabilities could be promoted to operate on canonical messages
   directly, then both paths consume the same enforcement surface.

The choice between (1+2) and (3) is a sequencing question. (1+2) is
faster to ship and closes the asymmetry sooner. (3) is the long-term
architectural target. (1+2) does not preclude (3); it can be the
intermediate step.

### Priority 2 — Continue the canonical migration

These items address Finding 1: the partial migration is incomplete,
and continued canonicalization closes the remaining downstream
uniformity gap.

4. **Migrate routing to operate on canonical messages.** Change
   `email_routing` and `email_dispatch` signatures to accept
   `CanonicalInboundMessage` (or a wrapper) instead of `parsed`
   integration objects. Routing decisions stay the same; the inputs
   become canonical-typed.

5. **Decide the legacy pre_booking_auto_send orchestration's
   disposition.** Either retire it in favor of brain orchestration
   alone, or migrate it behind the canonical contract. Today both
   exist. Long-term, only one architectural path should remain.

6. **Resolve queue read model legacy fields.** Fields like `platform`
   in the queue read model duplicate information available
   canonically. Decide whether these are retained for compatibility
   or migrated out.

### Priority 3 — Resolve the property identity decision

7. **Architectural decision: Is property identity a permitted
   exception?** If yes, document it in the architecture document
   alongside reply transport and channel constraints. If no, design
   the canonicalization that lets resolvers accept canonical inputs
   while internally reasoning over platform-specific identifiers.

This is a single architectural decision, not a multi-step migration.
Its outcome determines whether the source-aware classification on
property resolution is debt or documented exception.

### Sequencing summary

```text
Priority 1 (Safety asymmetry)     →  closes the production-relevant gap
        ↓
Priority 2 (Canonical migration)  →  closes structural debt
        ↓
Priority 3 (Property identity)    →  parallel architectural decision
```

Priority 1 is the most actionable today. Priority 2 has a soft
dependency on Issue 3 resolution (canonical seam reliability).
Priority 3 is independent and can proceed at any time as a focused
architectural decision session.

## Open questions

The audit identifies the following questions that this note cannot
resolve:

1. **Is property identity a permitted exception?** The audit's most
   important architectural-decision-needed item. Determines whether
   property resolution's source-aware classification is debt or
   documented permitted behavior.

2. **Why does the legacy pre_booking_auto_send orchestration still
   run alongside the brain orchestration?** Both exist. Whether they
   handle different traffic, run redundantly, or one supersedes the
   other is not clarified by this audit. Resolution would establish
   whether the legacy orchestration should be retired or migrated.

3. **What is the actual safety asymmetry impact today?** *(resolved
   2026-05-04)*. A query against `pre_booking_inquiries` and
   `message_normalizations` over the last 30 days returned 3
   inquiries with `draft_source='messaging_brain'` normalization
   attribution and 4 additional with `policy_warnings` brain
   evidence (totaling 7 of 266 inquiries). All concentrated on
   2026-05-03. Brain-path traffic is real but currently small
   relative to total volume. No dual-attribution rows observed in
   the 7-day sample, indicating inquiries flow through one path or
   the other, not both simultaneously. The asymmetry is producing
   live drafts but is not yet at scale; calibration is reflected in
   Finding 2.

4. **Should brain-path drafts be wired through the legacy reviewers,
   or should reviewers be promoted to canonical?** The Priority 1
   recommendation names both options without picking. The choice
   affects sequencing and effort.

5. **Are there downstream surfaces this audit missed?** The audit
   covered `app/services/concierge/`, `app/services/messaging_brain/`,
   `app/services/integrations/`, and `app/services/operator/`. It
   did not exhaustively audit `app/api/`, `app/workers/`, or any
   frontend code. Reasoning sites in those surfaces would need
   separate investigation (E5 scope).

## Out of scope

This note does not:

- Make code changes to any component
- Define migration timelines for source-aware components
- Specify the implementation shape of canonicalization changes
- Audit the writer side of the canonical contract (covered by `8a425df`)
- Audit reply transport or extraction strategies
- Resolve outstanding items from prior audits or operational backlog
- Decide which source-aware paths are migrated, retired, or maintained
