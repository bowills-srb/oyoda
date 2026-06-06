# Messaging Architecture

Architectural commitments for Oyvoda's inbound messaging pipeline. This
document defines the contract every extraction strategy must satisfy,
the operating modes the system uses to handle messages, the knowledge
substrate those modes reason from, and the observability requirements
that make the system diagnosable in production.

This is a design commitment document, not an implementation plan. It
constrains what gets built and how components fit together, but does
not propose specific migrations or refactors. Reconciliation of the
existing codebase against these commitments is a separate workstream.

## 1. Thesis and Principles

### Thesis

Oyvoda commits to one canonical message contract. Extraction strategies
are pluggable behind that contract. Validation, policy enforcement,
brain processing, and observability operate on the canonical shape
regardless of which extraction strategy produced it.

### Why this thesis

The system handles inbound messages from heterogeneous sources:
email-bridged OTA forwards via Gmail, the same forwards via Outlook,
direct PMS communications APIs (Guesty, Track, others), and operator
direct channels. Each source has different shape, different reliability
characteristics, and different parsing requirements.

A pure deterministic architecture cannot handle the long tail of
formats. A pure agentic architecture imposes inference cost and
reliability risk on common-case extraction that is already
deterministically solvable. Neither is the right default for Oyvoda's
operator base or scaling shape.

A canonical contract with pluggable extraction resolves this. Common
formats use deterministic extraction. Novel or heterogeneous formats
use agentic extraction. Both produce the same shape. Everything
downstream of extraction operates on that shape uniformly.

### Operating principles

The architecture commits to the following principles. These constrain
all subsequent design choices.

- **One canonical contract.** Every inbound message, regardless of
  source or extraction strategy, becomes a `CanonicalInboundMessage`
  with a defined field set. Downstream components consume the
  canonical shape, not source-specific representations.

- **Pluggable extraction.** Extraction strategies are interchangeable
  behind the contract. Adding a new channel or PMS integration means
  adding an extraction strategy, not modifying downstream components.

- **Operator data is authoritative.** The system treats operator-provided
  property data as ground truth. Collections marked exhaustive are
  reasoned about under closed-world assumption. The system does not
  hedge against the operator's own data.

- **Objective answers, structured facts for subjective questions.** The
  system answers factual questions confidently from operator data. For
  guest-judgment questions (family-friendly, romantic, accessible), the
  system provides relevant structured facts and lets the guest decide.
  The system does not make subjective recommendations on the operator's
  behalf.

- **Generate-and-check.** Wherever an agentic component produces output
  that affects the world, an independent check verifies that output
  before action. The check may be deterministic (policy gates), agentic
  (adversarial review against ground truth), or human (operator
  approval).

- **Observability is part of the contract.** Production code paths that
  handle persistence, mutation of system state, or external integration
  must emit structured error logs on all exception paths. Silent
  exception swallowing is not acceptable in load-bearing code.

- **Operator review captures knowledge.** The operator review period is
  not only a safety mechanism. It is a data acquisition phase. Edits,
  rejections, and corrections feed back into the system's knowledge
  base, sharpening future drafts and reducing future escalation.

## 2. The Canonical Contract

The canonical contract is the architectural commitment that makes
pluggable extraction viable. Every extraction strategy must produce a
`CanonicalInboundMessage` conforming to this contract. Every downstream
component consumes only canonical messages.

### Field set

The current baseline contract is implemented as the
`CanonicalInboundMessage` dataclass in
`app/services/messaging/inbound_normalizer.py`. The field set documented
below describes the contract as it stands today. It is the working
baseline, not a frozen final shape: as new extraction strategies and
downstream needs surface, the contract evolves under the rules in
"Contract evolution" below.

The fields below describe the working baseline:

**Identity and routing**
- `source_channel` — the canonical channel value (e.g. `"email"`)
- `source_provider` — the sub-classifier within the channel
  (e.g. `"gmail"`, `"microsoft"`, `"vrbo_email"`)
- `source_thread_id` — provider-native thread identifier
- `source_message_id` — provider-native message identifier
- `sender_role` — `"guest"`, `"operator"`, or other defined role
- `sender_display_name` — parsed display name
- `sender_address` — parsed sender address (lowercased)

**Temporal and subject**
- `sent_at` — message send time
- `raw_subject` — original subject line if present

**Content**
- `latest_guest_turn` — the latest message in the thread, attributable
  to the guest
- `prior_thread_context` — preceding thread content
- `full_message_text` — full body of the latest message

**Extracted intent and policy state**
- `structured_asks` — list of extracted asks attributable to the guest
- `prior_operator_commitments` — list of prior operator commitments
  inferred from the thread context
- `property_binding_candidates` — list of candidate property bindings
  for downstream resolution
- `channel_constraints` — channel-specific constraints (response time
  windows, response length limits, etc.)

**Provenance**
- `parser_used` — identifier of the extraction strategy that produced
  this canonical message
- `parser_version` — version of the extraction strategy
- `parser_notes` — structured notes from the extraction strategy
- `latest_turn_confidence` — extraction strategy's confidence in
  `latest_guest_turn`
- `latest_turn_extracted` — whether the latest turn was reliably
  separated from thread context

**Guest identity**
- `guest_name` — normalized guest name
- `guest_email` — normalized guest email

### Contract guarantees

The contract makes the following guarantees to downstream components:

- **Source-agnostic shape.** A canonical message produced from a Gmail
  inbox poller, a Microsoft Graph poller, an Escapia API integration,
  or any future extraction strategy presents the same field set. No
  downstream component branches on source.

- **Provenance preserved.** Every canonical message carries
  `parser_used`, `parser_version`, and `parser_notes`. Downstream
  components can reason about extraction quality without depending on
  source-specific shape.

- **Confidence is explicit.** `latest_turn_confidence` and
  `latest_turn_extracted` give downstream components signal about
  extraction quality. Components that need high-confidence input
  (e.g., autonomous send decisions) can gate on these fields.

### Contract obligations on extraction strategies

Every extraction strategy commits to:

- Populating all required fields with valid values
- Reporting its own provenance accurately via `parser_used` and
  `parser_version`
- Reporting confidence honestly — extraction strategies do not
  inflate `latest_turn_confidence` to bypass downstream gating
- Producing identical canonical output for semantically equivalent
  inputs across runs (determinism within strategy; agentic strategies
  must address this through prompt design, temperature settings, or
  output validation)

### Contract evolution

The canonical contract is not frozen. New fields may be added when a
real architectural need arises across multiple extraction strategies.
Field additions follow a strict rule: existing extraction strategies
must continue to produce valid canonical messages without modification,
and existing downstream components must continue to operate without
regression. New fields default to safe values; they do not become
required without explicit migration.

## 3. Extraction Strategies

Extraction strategies are the pluggable layer that converts
source-specific inbound data into canonical messages. The architecture
commits to multiple extraction strategies operating in parallel, each
appropriate to a class of input.

### Deterministic extraction

Deterministic extraction handles known, stable formats. It uses
parsers, regular expressions, format-specific field extractors, and
deterministic transformation logic. It produces a canonical message
without LLM inference.

Deterministic extraction is the default for:

- OTA-forwarded emails with stable formats (Airbnb, VRBO, Booking
  forwarded via Escapia or similar bridges)
- Direct PMS API responses where the response shape is documented and
  stable
- System-generated messages with predictable structure

Deterministic extraction is preferred where applicable because it is:

- Fast (no inference latency)
- Cheap (no inference cost)
- Reproducible (same input produces same output)
- Auditable (every transformation is traceable to source code)

Deterministic extraction is appropriate when:

- The input format is stable and documented
- Coverage of expected variants is high
- Failure modes are visible (extraction fails loudly rather than
  silently producing wrong output)

### Agentic extraction

Agentic extraction handles novel, heterogeneous, or low-coverage
formats. It uses LLM inference to interpret message content and
produce a canonical message.

Agentic extraction is the default for:

- Email forwards from PMS systems or formats not yet covered by
  deterministic extraction
- Operator messages that mix structured and unstructured content
- Edge cases where deterministic extraction fails or produces
  low-confidence output
- New channel integrations where format variation is high during
  initial rollout

Agentic extraction is appropriate when:

- Input formats are heterogeneous or change frequently
- Deterministic coverage is incomplete
- Format normalization across the long tail is more valuable than
  per-format engineering

### Strategy selection

The system selects extraction strategy based on signal known at intake
time, not after attempted extraction. Selection inputs include:

- Source channel and provider
- Sender domain or address patterns
- Subject line patterns (where deterministic extractors register
  pattern signatures)
- Operator-level configuration (some operators may opt their channels
  into agentic extraction by default)

Where deterministic extraction is selected and fails, the system falls
back to agentic extraction rather than producing a malformed canonical
message. Fallback is logged at WARNING with the deterministic failure
reason; the canonical message produced by the agentic fallback carries
`parser_notes` reflecting the fallback path.

### Strategy versioning

Extraction strategies are versioned. The canonical message records
`parser_used` and `parser_version` so downstream components and
operators can attribute behavior to specific extraction logic. Version
changes are deliberate: deterministic strategy version bumps reflect
parsing rule changes, agentic strategy version bumps reflect prompt or
model changes.

### What extraction strategies do not do

Extraction strategies produce canonical messages. They do not:

- Make routing decisions (handled in downstream routing)
- Generate guest responses (handled by the brain)
- Apply policy gates (handled in policy enforcement)
- Decide whether to send autonomously (handled by send/hold decision)

Extraction is bounded to the conversion of source-specific input into
canonical shape.

## 4. Downstream Uniformity

Every component downstream of extraction operates on canonical
messages, not on source-specific representations. This is the
architectural commitment that makes the canonical contract worthwhile.

### Components downstream of extraction

The following components consume canonical messages and produce no
source-specific behavior:

- **Routing.** The decision of whether a message is system-generated,
  in-stay, or pre-booking operates on canonical fields. Routing logic
  does not branch on source channel or provider beyond what the
  canonical fields already express.

- **Property resolution.** Mapping a canonical message to a canonical
  property (or escalating on ambiguous match) operates on
  `property_binding_candidates` and operator-provided property data.

- **Knowledge retrieval.** Retrieval of property facts, operator
  policies, and contextual data operates on canonical message fields
  plus resolved property identity.

- **Brain (response generation).** The brain consumes the canonical
  message plus retrieved knowledge. It does not branch on source
  channel.

- **Adversarial review.** Verification of brain-produced drafts
  against retrieved ground truth operates on the canonical message
  and the draft, not on source-specific signals.

- **Policy enforcement.** Hard policy gates (must-include, must-not-include,
  rate quoting, escalation triggers) operate on canonical messages and
  drafts.

- **Operator review queue.** The queue presents canonical messages and
  drafts uniformly to operators regardless of source.

- **Observability.** Metrics, logs, and audit trails record canonical
  fields. Source-specific debugging requires drilling through provenance,
  not through a source-specific observability surface.

### Why uniformity matters

Source-specific behavior past extraction creates compounding cost. Each
new channel or PMS integration requires touching every downstream
component that branched on source. Bug fixes must be applied per-source.
Metrics become incomparable across sources. Trust in the system
degrades because behavior varies in ways that aren't visible to
operators.

Uniformity inverts this. New channels are added by writing a new
extraction strategy. Downstream components don't change. Bug fixes
apply universally. Metrics are comparable. Operators see consistent
behavior across their channel mix.

### Permitted source-aware behavior

A small set of components legitimately need source-aware behavior:

- **Reply transport.** Sending a reply requires source-specific
  outbound logic (Gmail send vs. Microsoft Graph send vs. PMS API
  reply). This is a transport concern, not an architecture concern,
  and is handled by reply adapters paired with inbox adapters.

- **Channel constraints.** Response time SLAs, character limits, and
  formatting constraints are channel-specific. These are captured in
  `channel_constraints` on the canonical message itself, so downstream
  components remain canonical-only.

These exceptions are constrained: source-specific transport, and
source-derived constraints carried through the canonical shape.
Anything else branching on source is architectural debt.

## 5. Operating Modes

The system operates on canonical messages through five distinct modes.
Each mode has a defined role, defined inputs, and defined seams to
adjacent modes.

### Mode 1: Deterministic

The deterministic mode handles operations where rules are stable,
auditable, and reproducible. Examples:

- Property resolution from explicit identifiers
- Routing decisions based on canonical fields
- Policy gates that enforce hard constraints
- Send/hold decisions in review-required mode
- Status transitions in operator queues
- Idempotency and deduplication

Deterministic mode is the default. Other modes are invoked only where
deterministic logic is insufficient.

### Mode 2: Agentic primary

The agentic primary mode handles reasoning under uncertainty. It is
the LLM-based mode that produces analysis, drafts, or decisions when
deterministic logic cannot. Examples:

- Response draft generation (the brain)
- Disambiguation of guest intent when structured asks are insufficient
- Synthesis of property facts plus retrieved context into coherent
  responses

The agentic primary mode operates on canonical messages plus retrieved
knowledge. It produces output that flows into the generate-and-check
pattern: the output is checked before it affects the world.

### Mode 3: Adversarial

The adversarial mode is a structural guard, not a primary actor. It
takes the output of the agentic primary mode and verifies it against
factual ground truth. It does not soften confident applications of
correct data; it identifies drafts that contradict ground truth or
overstate certainty.

The adversarial mode's checks include:

- Claims in drafts match retrieved property facts
- Quoted policies match operator-provided policy data
- Closed-world claims (e.g., "this property does not have a hot tub")
  are correctly grounded in collections marked exhaustive
- Confidence expressed in drafts matches the confidence the system
  actually has

The adversarial mode produces one of three outcomes: pass (draft
proceeds), fail with specific objection (draft is held or regenerated
with the objection as additional context), or uncertain (draft is
flagged for operator review with the objection surfaced).

### Mode 4: Human escalation

The human escalation mode handles cases where the system's competence
is insufficient. Examples:

- Drafts the adversarial mode flags as failed
- Inquiries with low extraction confidence
- Inquiries on topics not covered by operator-provided knowledge
- Questions requiring operator-specific judgment or authority

Human escalation is not a fallback; it is a deliberate routing decision
when the system recognizes it should not autonomously handle a case.
Operators receive escalations through the same review queue that
handles review-required drafts; the escalation context is surfaced so
operators can act efficiently.

### Mode 5: Learning loop

The learning loop converts operator actions on the review queue into
durable system improvements. The loop captures:

- **Knowledge gaps.** Edits that add property facts, operator policies,
  or constraints become structured updates to the operator's knowledge
  base.
- **Style preferences.** Edits that change tone, phrasing, or
  formatting become signals about operator brand voice.
- **Hard rejections.** Drafts the operator rejects with reason indicate
  classes of error to detect earlier.
- **Approval patterns.** Drafts approved without edit indicate
  extraction and brain logic are working correctly for that class of
  inquiry.

The learning loop is not an emergent property of operator review. It is
a deliberate subsystem that classifies operator actions and routes
each class to the appropriate updater. Building this subsystem is part
of the architectural commitment, not a side effect of having a review
queue.

### How modes compose

Modes compose through the generate-and-check pattern: agentic primary
produces, adversarial checks, deterministic gates enforce, and human
escalation handles cases the system declines to autonomously resolve.
The learning loop runs continuously, capturing signal from operator
actions across all modes.

No mode is the "right" mode for the system as a whole. The right mode
for any specific operation is the one that matches the certainty,
stakes, and observability needs of that operation.

## 6. Knowledge Architecture

Operator data is the substrate the system reasons from. The knowledge
architecture defines what data the system holds, how it's structured,
and how it composes during reasoning.

### Three layers of knowledge

The system reasons from three present layers of operator and external
data, plus one cross-operator intelligence layer that is target state
(described later in this section).

The three present layers:

**Layer 1: Operator-provided property data.** Authoritative for the
property itself. Includes amenity lists, house rules, included items,
operational notes, brand voice samples, escalation triggers, and
operator policies. Captured during onboarding and maintained by the
operator.

**Layer 2: External location data.** Authoritative for the area around
the property. Includes nearby points of interest (Google Places),
geographic context (lat/long-derived attributes), and area
characteristics (urban vs. rural, beach vs. mountain, etc.). Retrieved
from external sources, not maintained by the operator.

**Layer 3: Time-bound event data.** Authoritative for what is happening
near the property during a specific stay window. Includes local events,
seasonal characteristics, and date-specific context. Retrieved from
external sources, scoped to the dates relevant to a specific inquiry.

These layers compose during reasoning. A guest question about
restaurants near the property is answered from Layer 2. A question
about whether the property has a pool is answered from Layer 1. A
question about what's happening near the property next weekend is
answered from Layer 3 scoped to the guest's stay dates.

### Closed-world reasoning

For Layer 1 collections marked exhaustive, the system reasons under
closed-world assumption: absence of an attribute means the attribute
is not present. The amenity list is the canonical example. If beach
chairs are not listed and the list is marked exhaustive, the system
states that the property does not include beach chairs.

Closed-world reasoning has explicit prerequisites:

- The collection must be marked exhaustive in the data model
- The operator must accept the closed-world contract during onboarding
- The system must distinguish exhaustive from partial collections at
  reasoning time

For Layer 2 and Layer 3, closed-world reasoning does not apply. These
layers are open-world by nature: external data is incomplete, and the
system reasons from what it knows without inferring from absence.

For partial Layer 1 collections (operational notes, FAQs, edge cases),
closed-world reasoning also does not apply. The system answers from
what is present and is honest when something is not covered.

### Hierarchical property data

Operators with multi-property portfolios provide data hierarchically:

- **Operator level.** General policies, brand voice, escalation
  preferences. Apply to all properties unless overridden.
- **Property group level.** Shared characteristics across properties
  in a complex, building, or geographic cluster. Apply to all
  properties in the group unless overridden.
- **Property level.** Property-specific data. Overrides higher levels
  where present.

The data model supports inheritance: a property-level record inherits
from its property group, which inherits from the operator. Onboarding
captures data at the most general scope where it applies, and the
system propagates downward.

### Objective answers, structured facts for subjective questions

For objective questions ("does this property have a pool"), the system
answers from the knowledge layers. For subjective questions ("is this
place family-friendly"), the system does not answer with a judgment.
Instead, it provides relevant structured facts (crib availability,
pool fencing, distance to attractions, recent guest review themes) and
lets the guest synthesize the judgment.

This is an architectural commitment, not a UX choice. Subjective
judgments made on the operator's behalf create liability when they
fail to match a specific guest's threshold. Structured facts shift
that judgment to the guest where it belongs.

### The Oyvoda intelligence layer

**Target state. Not currently implemented.**

The Oyvoda intelligence layer is the cross-operator knowledge the
system accumulates from operating. When realized, it will not be
visible to individual operators and will not expose any operator's
data. Its scope includes:

- **Question pattern knowledge.** What guests actually ask in different
  contexts. Informs onboarding prompts (e.g., "operators with beach
  properties commonly need beach access information") and extraction
  strategies (e.g., parsing improvements based on observed inquiry
  patterns).
- **Response pattern knowledge.** Edit patterns across operators reveal
  what response shapes work well. Informs brain prompt improvements
  and style guidance.
- **Adversarial pattern knowledge.** Classes of claim that tend to be
  wrong. Informs adversarial review's targeting and confidence.
- **Onboarding gap knowledge.** Fields that, when missing, lead to
  high escalation rates. Informs onboarding prioritization for new
  operators.

This layer is named as an explicit architectural commitment because
it produces network effects: every operator's experience improves
the system for every other operator. It is also intended as the
system's structural moat. New entrants can build LLM-based reply
systems; they will not be able to replicate years of accumulated
cross-operator pattern knowledge without operating at scale for
years.

The layer does not exist today. Capturing the data needed to build
it later is a present-tense concern: data structures and ingestion
pathways need to be designed now to support aggregation later, even
before the aggregation infrastructure itself is built.

## 7. Observability Commitment

Production code paths that handle persistence, mutation of system
state, or external integration must be observable. Silent exception
swallowing is not acceptable in load-bearing code.

This commitment is stated as an architectural principle because it
proved load-bearing in practice. A canonical persistence outage on
2026-05-03 was undetectable for hours because the affected module
lacked usable production error logging and silently swallowed
exceptions. Every metric, verification query, and audit join
downstream of that module produced incomplete data without surfacing
any error signal. The underlying lesson is architectural:
observability is a property of the contract, not infrastructure
layered on top.

### Scope of the commitment

The commitment applies to modules in the load-bearing message-processing
surface:

- Inbound transport adapters (Gmail, Microsoft, future PMS API
  integrations)
- Extraction strategies (deterministic and agentic)
- Canonical persistence (`message_event_store` and any future canonical
  data writers)
- Routing and dispatch
- Brain orchestration and agents
- Adversarial review
- Operator queue read and write paths
- Reply transport

The commitment does not apply to:

- Pure utility modules (string formatting, date manipulation, etc.)
- Optional cache reads where silent fallback is correct behavior
- Read-only opportunistic prefetches

The distinction is whether silent failure can corrupt state or hide
correctness issues. Load-bearing modules cannot; utility modules can.

### Required observability properties

Every module in scope commits to:

- **Configured logger.** The module imports a logger and binds it at
  module level via `logging.getLogger(__name__)`. No module in scope
  is permitted to lack a logger.
- **Structured error logging.** Every `except` block that does not
  re-raise must log at ERROR or WARNING with `exc_info=True`. Catching
  and silently swallowing exceptions is not permitted in scope.
- **Correlation context.** Error logs include the canonical message
  identifiers (typically `source_message_id` or equivalent) so a
  failure can be traced to a specific message without log scraping
  across timestamps.
- **Failure outcomes are queryable.** Errors that affect persistence
  or routing must produce a queryable signal — either a status row,
  a counter, or a structured log entry that production log search
  can find. Silent error states that are only diagnosable through
  data inference are not acceptable.

### Logger level discipline

The system uses log levels with discipline:

- **DEBUG.** Development-time diagnostic output. Not retained in
  production. Not relied on for production diagnosis.
- **INFO.** Normal operational signal. Retained in production but not
  the primary surface for failures.
- **WARNING.** Recoverable failures. Fallback paths invoked, partial
  results produced, retries pending. Searchable in production logs.
- **ERROR.** Unrecoverable failures in a specific operation. Always
  includes traceback via `exc_info=True`. Searchable in production
  logs and surfaceable as alerts.

Production diagnosis assumes WARNING and ERROR are searchable. DEBUG
is not a substitute for either.

### Generate-and-check observability

The generate-and-check pattern requires symmetric observability across
agentic generation and adversarial verification:

- The agentic primary mode logs the canonical message identifier and
  the draft it produced
- The adversarial mode logs the same identifier and its
  pass/fail/uncertain decision plus rationale
- Failures of either are logged at ERROR with traceback

This makes generate-and-check auditable: any draft can be traced from
intake through generation through adversarial review through send/hold
decision through operator action.

### Observability as part of contract review

Adding new code to the load-bearing surface includes an observability
review: does the new module have a logger, do all exception paths log
appropriately, are correlation identifiers carried through? Modules
that fail this review are not production-ready, regardless of test
coverage or feature completeness.

## 8. Current State vs. Target State

Mapping the architectural commitments above against the current
codebase. Each commitment is tagged as one of:

- **Implemented.** The commitment is substantially realized in code.
  Minor gaps may exist but the architecture matches.
- **Partial.** The commitment is partially realized. Reconciliation
  work is needed but the foundation exists.
- **Gap.** The commitment is not realized. Building it is greenfield
  work or requires substantial modification.

This mapping is high-level. Detailed reconciliation belongs to a
separate workstream.

### Canonical contract: implemented (with caveats)

`CanonicalInboundMessage` exists in
`app/services/messaging/inbound_normalizer.py` with a defined field
set covering identity, content, intent extraction, provenance, and
guest identity. Both Gmail and Microsoft extraction paths produce
canonical messages.

Caveats: the contract is implicit in the dataclass definition rather
than documented as an architectural artifact. Field semantics are
inferred from usage, not specified. Promoting the contract to a
first-class artifact (this document plus inline schema documentation)
is the reconciliation work.

### Pluggable extraction: partial

The codebase has provider abstraction via `inbox_adapters.py`
(`build_inbox_adapter`, `build_reply_adapter`). Gmail and Microsoft
adapters are real and produce canonical messages. The architectural
pattern of "extraction strategy as plugin behind canonical contract"
is broadly realized for inbox-derived messages.

Gaps: agentic extraction does not yet exist as a strategy. A direct
PMS API integration path would need to be added when the first such
operator onboards. The strategy-selection logic is currently
hardcoded by provider rather than extensible to new strategy types.

### Operator data as authoritative: partial

The system retrieves operator-provided property data and reasons from
it. Closed-world reasoning is partially supported but not enforced as
an architectural commitment: collections are not explicitly marked
exhaustive vs. partial, and reasoning logic does not consistently
distinguish them.

Gap: schema additions to mark collections exhaustive, plus reasoning
logic that respects the marking, plus onboarding flow that captures
operator commitment to closed-world for marked collections.

### Objective answers, structured facts for subjective questions: gap

The current brain does not consistently distinguish objective
factual questions from subjective judgment questions. Both classes
get treated as response-generation tasks. The architectural
commitment to provide structured facts for subjective questions
without rendering judgment is not enforced.

Gap: prompt-level and policy-level enforcement of the
objective-vs-subjective distinction, plus operator-facing
documentation of what the system will and will not answer.

### Generate-and-check pattern: partial

The adversarial review concept is real in the codebase. The
`fallback_adversarial_review` draft source value indicates that an
adversarial path produces drafts under some conditions. The pattern
of "agentic produces, adversarial checks before action" is partially
realized.

Gaps: the adversarial check is not consistently applied to all
brain-produced drafts. Calibration of the adversarial agent's
strictness is not surfaced as a deliberate engineering metric.
Adversarial decisions are not consistently logged with the structure
needed for post-hoc review.

### Operator review captures knowledge: gap

The operator review queue exists and supports approve/edit/reject
actions. `operator_draft_events` captures edit and rejection events
with original and edited text. The data is being captured.

What does not exist: the learning loop subsystem that classifies
operator actions (knowledge gap vs. style preference vs. constraint
update vs. true mistake) and routes each class to the appropriate
updater (property facts, brand voice, policy, etc.). Today, edits
are stored but not absorbed into structured knowledge updates.

### Three layers of knowledge: partial

Layer 1 (operator-provided property data) is the most realized. Layer
2 (external location data) is referenced architecturally but the
Google Places integration and lat/long-derived attributes are not yet
woven into reasoning. Layer 3 (time-bound event data) is not
implemented.

Gap: Layer 2 retrieval and Layer 3 acquisition are net-new build.
Layer 1 maintenance (operator periodic review prompts, freshness
tracking) is also incomplete.

### Hierarchical property data: gap

The current data model treats properties as flat. Multi-property
operators provide data per-property without inheritance from operator
or property-group level. The architectural commitment to hierarchical
data with inheritance is not realized.

Gap: schema additions for property groups, inheritance resolution
logic, and onboarding flow that captures data at the appropriate
scope.

### Oyvoda intelligence layer: gap

The system does not currently aggregate cross-operator pattern data.
Question patterns, response patterns, adversarial patterns, and
onboarding gap patterns are not captured in a form that informs
future operator onboarding or reasoning.

Gap: cross-cutting analytics infrastructure that aggregates
anonymized signal across operators and exposes it to onboarding,
extraction, and brain prompt construction.

### Observability commitment: partial

Most load-bearing modules have configured loggers (verified
2026-05-03 via grep across `app/services/messaging/`,
`app/services/integrations/`, `app/services/concierge/`, and
`app/services/messaging_brain/`). The recent fix `a9b09ef` closed
the most acute gap (`message_event_store.py` had no logger).

Gaps: structured error logging discipline is not enforced
consistently — modules with configured loggers may still have
exception paths that don't log appropriately. Correlation context
(canonical message identifiers in error logs) is not uniformly
applied. The "observability is part of contract review" practice is
not yet a routine part of code review.

### Operating modes: partial

Four of the five modes — deterministic, agentic primary, adversarial,
and human escalation — exist in working form in the codebase. The
learning loop is the exception: data capture exists
(`operator_draft_events` records edits and rejections with original
and edited text), but the deliberate subsystem that classifies operator
actions and routes them to structured updaters does not exist. The
loop's *inputs* are being collected; the loop itself has not been
built.

The architectural framing of these modes as a coherent set with
defined seams is new (this document). Reconciliation will reveal where
modes overlap, where seams are unclear, and where mode-specific
behavior has leaked across boundaries.

### Downstream uniformity: partial

Most components downstream of extraction operate on canonical
messages or values derived from them. Some source-specific behavior
persists in places that should be canonical-only — for example, the
existence of a separate `EscapiaMessageService.process_inquiry(...)`
path alongside the email-dispatch path suggests source-specific
ingestion logic that may not fully respect the canonical contract.

Gap: audit and reconciliation of any downstream component that
branches on source channel or provider beyond the permitted
exceptions (reply transport, channel constraints).

### Summary

The architectural foundation is more realized than not. The canonical
contract, provider abstraction, operating modes (with the learning
loop exception noted above), and observability infrastructure all
exist in working form. Several load-bearing seams are still
inconsistent — particularly around the learning loop, closed-world
reasoning enforcement, and downstream uniformity in places where
source-specific ingestion paths persist.

The major commitments still requiring deliberate build-out:

- The learning loop as a deliberate subsystem
- Layer 2 and Layer 3 knowledge integration
- Hierarchical property data
- The Oyvoda intelligence layer as cross-operator infrastructure
- Closed-world reasoning enforcement
- Objective-vs-subjective question handling

These gaps are not blockers for current operation. They are the
expansion path from the current single-operator rollout to the
multi-operator, multi-channel target state.

The implementation/partial/gap tags in this section are provisional.
They reflect the current understanding from this conversation and
recent investigation work, not a fresh codebase audit. Subsequent
reconciliation work may sharpen or revise any specific tag.

## 9. Out of Scope

This document does not:

- Propose specific implementation details for any commitment
- Define migration timelines or sequencing across the gaps in Section 8
- Decide infrastructure questions deferred from the 2026-05-02 topology
  snapshot (worker tier configuration, Celery consumer mystery, deploy
  pipeline divergence)
- Specify the schema of the canonical contract beyond the current field
  set in `CanonicalInboundMessage`
- Decide whether existing code paths that diverge from these
  commitments are repaired in place or replaced
- Define how operators are onboarded onto channels covered by extraction
  strategies that do not yet exist (agentic, direct PMS API)
- Resolve outstanding architectural debt items from prior sessions
  (channel convention mismatch, normalization persistence issues,
  fail-open patterns in non-message-event-store modules)

This document also does not redefine the closure status of prior
sessions. Session 14 remains correctly closed. The 2026-05-02 topology
snapshot remains a current-state record, not a target-state document.
This architecture document is the target-state companion to those
artifacts; reconciliation between them is forward work.
