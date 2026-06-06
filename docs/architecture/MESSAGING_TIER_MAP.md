# Messaging Architecture Tier Map

**Status:** Active reference. Cite this doc when answering "where does X live?" or "where should X go?"
**Last verified:** 2026-05-26 (post pre-booking closeout, lifecycle convergence, healer wiring)
**Companion docs:** `MESSAGING_ARCHITECTURE.md`, `HEALER_AGENT.md`, `INBOUND_MESSAGE_GATE.md`, `INTENT_CLASSIFICATION_LAYERS.md`

---

## Purpose

This document pins the architectural layout of Oyvoda's messaging system so contributors don't re-derive it. The system is split across four directories that look superficially similar but live at different levels of abstraction. Each split is doing real architectural work. Do not collapse them.

If you're asking "should I unify messaging/ and messaging_brain/?" — read this first. The answer is no, and the reasoning is below.

---

## The four tiers at a glance

```
┌─────────────────────────────────────────────────────────────────────┐
│  app/services/integrations/                                         │
│  Tier 1 — INBOUND TRANSPORT + PARSING                               │
│  Shaped by external systems (Gmail, OTAs, PMS, vendors)             │
│  Pollers, parsers, LLM extractor, deterministic drop patterns       │
└─────────────────────────────────────────────────────────────────────┘
                              ↓ normalized
┌─────────────────────────────────────────────────────────────────────┐
│  app/services/messaging/                                            │
│  Tier 2 — LAYER-AGNOSTIC PLUMBING                                   │
│  Identity, channel router, inbox adapters, canonical contracts,     │
│  message event store, autonomy primitives, alert routing platform   │
└─────────────────────────────────────────────────────────────────────┘
                              ↓ contracts
┌─────────────────────────────────────────────────────────────────────┐
│  app/services/messaging_brain/                                      │
│  Tier 3 — DECISION PLANE                                            │
│  Gate, fast-paths, intake, specialists, composer, grounding,        │
│  reviewer, lifecycle persistence, feature-specific consumers        │
└─────────────────────────────────────────────────────────────────────┘
                              ↑ reads signals from all tiers
┌─────────────────────────────────────────────────────────────────────┐
│  app/services/agents/                                               │
│  CROSS-CUTTING — autonomous workers operating on signals            │
│  Healers (3 kinds), knowledge curator, PMS sync, router agents      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Tier 1 — `app/services/integrations/`

**Bounded by:** External systems Oyvoda doesn't control. Every module here is named after, or shaped by, a system whose contract is set by someone else.

**Responsibility:** Get messages into and out of Oyvoda. Parse what comes in. Drop what's obviously not guest traffic. Fall back to LLM-based extraction when deterministic parsers don't match.

**Key modules:**
- `gmail_inbox_poller.py`, `microsoft_inbox_poller.py` — inbound pollers per provider
- `email_parser_router.py` — layer-1 router that picks a parser and applies deterministic drop patterns
- `ota_email_parsers.py` — Vrbo, Airbnb, Booking.com, HomeAway deterministic parsers
- `direct_email_parsers.py` — non-OTA guest email parsers
- `vendor_email_parsers.py` — vendor/operational mail parsers
- `llm_email_extractor.py` — LLM-based fallback when deterministic parsers don't match
- `email_dispatch.py` — outbound dispatch routing (`dispatch_pre_booking`, `dispatch_in_stay`, `dispatch_confirmed_guest`, `dispatch_system_event`)
- `email_reply.py`, `email_pipeline.py`, `email_inbound.py`, `email_routing.py`, `email_type_classifier.py`
- `non_guest_patterns.py` — pattern registry for messages that should never reach the brain
- `property_mention_surfaces.py` — surface-audit notes (the signal property-alias healer reads)
- `inbound_source_router.py`, `reservation_aware_routing.py`, `ota_reservation_events.py`
- `pms/` — PMS-specific connectors and contracts

**Defining test:** If an external system changed its format tomorrow, would the fix live here? If yes, this is the right tier.

**Allowed dependencies:**
- May import from: `messaging/` (Tier 2), shared infrastructure (db, models, config)
- Must NOT import from: `messaging_brain/` (Tier 3), `agents/`

---

## Tier 2 — `app/services/messaging/`

**Bounded by:** What's stable about messages regardless of source or decision. The modules here would still need to exist if you swapped out either the transport above or the brain below.

**Responsibility:** Normalize transport-layer inputs into stable contracts. Resolve identity. Route outbound through the right channel. Persist canonical messages. Provide alert dispatch primitives that any feature can call.

**Key modules:**
- `identity_resolver.py` — `GuestIdentityResolution` dataclass and resolver. Four states: identified, linked, pseudonymous, anonymous.
- `inbound_normalizer.py` — `CanonicalInboundMessage` contract; every transport normalizes into this
- `inbound_transport.py` — transport-layer normalization primitives
- `inbox_adapters.py` — outbound reply adapter (Gmail, Microsoft 365)
- `channel_router.py` — outbound channel selection based on guest preferences and channel availability
- `message_event_store.py` — canonical message persistence (`message_event_store` table)
- `autonomy_gate.py` — autonomy threshold check primitives (the platform; brain consumes it)
- `operator_alerts.py` — **ALERT ROUTING PLATFORM.** This is the generic dispatcher: alert types, contact resolution (property → operator → primary → ops fallback), active hours, OOO/vacation handling, escalation chains, ack tracking, coverage-gap fallback. Used by every feature that needs to alert an operator.
- `parser_notes_schema.py` — schema for parser-side audit notes
- `guest_messaging.py`, `human_feel.py`, `coverage_monitor.py`, `rcs_templates.py`, `booking_context_adapters.py`

**Defining test:** Would this module still need to exist if we swapped out the transport layer? If we swapped out the brain? If both answers are yes, it belongs here.

**Allowed dependencies:**
- May import from: shared infrastructure (db, models, config)
- Must NOT import from: `integrations/` (Tier 1), `messaging_brain/` (Tier 3), `agents/`

---

## Tier 3 — `app/services/messaging_brain/`

**Bounded by:** Decision logic operating on already-normalized contracts. Receives `CanonicalInboundMessage` with `GuestIdentityResolution` attached. Doesn't know what transport delivered the message.

**Responsibility:** Classify intent. Run fast-paths (FAQ, gate code, escalation). Build lazy context. Route to specialists based on identity eligibility. Compose drafts. Ground and review. Persist with the confidence contract.

**Key modules:**
- `orchestrator.py` — `GuestMessageBrainOrchestrator`, the single decision plane
- `inbound_message_gate.py` — Anthropic-classifier gate (with retry, status-code preservation, deterministic admit fallback as of `25fafa5`)
- `stages/fast_path_stage.py` — escalation / gate-code / FAQ short-circuit before specialists
- `agents/` — specialist agents (intake, maintenance, house rules, access, late checkout, booking inquiry, escalation, general, etc.), plus `llm_composer_agent.py`
- `agents/context_builder_agent.py` — lazy context loading (gated by intent keywords)
- `context/lazy_context_gates.py` — the keyword gates concierge and brain share
- `pre_booking.py`, `pre_booking_lifecycle.py`, `pre_booking_retry.py` — pre-booking lifecycle coordinators
- `session_channel_adapter.py` — in-stay / pre-arrival / post-stay entry point
- `proactive_trigger_adapter.py` — outbound proactive entry point
- `prebooking_runtime.py` — small brain-side helpers retained after closeout
- `grounding/` — `hallucination_guard.py`, `response_reviewer.py`, `prebooking_grounding.py`
- `persistence/prebooking_inquiry_store.py`, `prebooking_inquiry_types.py` — brain-owned persistence helpers
- `notifications/prebooking_review_alerts.py` — **brain-side consumer of the alert routing platform.** Formats the pre-booking review alert and dispatches it through `messaging/operator_alerts.py`'s router. (Renamed from `operator_alerts.py` to make the consumer/platform distinction unambiguous — see Naming Discipline below.)
- `audit.py`, `inbound_classification_store.py`, `kb_retry_handler.py`, `property_resolution_writeback.py`
- `knowledge/`, `intake/`, `policy/`, `modules/`, `eval/`

**Defining test:** Does this module operate on the normalized contract (`CanonicalInboundMessage`, `GuestIdentityResolution`, `GuestResponseDraft`) rather than on raw transport data? Does it make a decision about a message rather than move it around? If both answers are yes, it belongs here.

**Allowed dependencies:**
- May import from: `messaging/` (Tier 2), shared infrastructure
- May import contracts from `integrations/` (e.g. `ParsedEmailMessage`) for type purposes, but should NOT depend on transport behavior
- Must NOT import from: `agents/` (cross-cutting; the dependency goes the other way)

---

## Cross-cutting — `app/services/agents/`

**Bounded by:** Workers that operate across multiple tiers on a non-request-response schedule. Not transport, not primitives, not per-message decisions.

**Responsibility:** Audit, learn, propose, sync. Read signals from any tier; propose durable improvements to any tier subject to human approval.

**Key modules:**
- `healer_agent.py` — three proposal kinds:
  - `property_alias_suggestion` (reads Tier 1 surface-audit notes → writes Tier 2 `canonical_property_identities`)
  - `intent_classifier_keyword_suggestion` (reads Tier 3 brain classifier metadata → writes `operator_settings.extra`)
  - `prefilter_drop_pattern_suggestion` (reads Tier 1 gate-error clusters → writes `operator_settings.extra.inbound_prefilter_drop_overrides`)
- `healer_runner.py` — daily scan entry (wired into Celery beat at 05:00 UTC via `app.workers.tasks.scan_healer_proposals`)
- `knowledge_curator_agent.py`, `pms_sync_agent.py`, `router_agent.py`, `escalation_handoff_agent.py`
- `experiment_registry.py`, `concierge_health.py`, `agent_framework.py`
- `emotional_intelligence/`, `market_intelligence/`, `onboarding/`, `task_execution/`

**Defining test:** Does this worker run on a schedule (or on an external trigger) rather than as part of per-message handling? Does it cross tier boundaries to read signals or propose changes? If both yes, it belongs here.

**Allowed dependencies:**
- May import from: any tier, plus shared infrastructure
- This is the only directory that may legitimately reach into all three tiers, because its job is cross-cutting

---

## Dependency rule (enforce in review)

```
integrations/        →  messaging/          ✓
messaging_brain/     →  messaging/          ✓
agents/              →  integrations/       ✓ (cross-cutting reads)
agents/              →  messaging/          ✓ (cross-cutting reads/writes)
agents/              →  messaging_brain/    ✓ (cross-cutting reads)

messaging/           →  integrations/       ✗ (would invert layering)
messaging/           →  messaging_brain/    ✗ (would invert layering)
messaging_brain/     →  integrations/       ✗ (brain shouldn't depend on transport)
integrations/        →  messaging_brain/    ✗ (transport shouldn't depend on decision)
```

If a PR introduces a forbidden import direction, that's a layering violation. Push back in review.

---

## Naming discipline (the alert-files lesson)

Two files at different tiers can have similar names if they live at different abstraction levels — but the names should make the relationship obvious. The original layout had `messaging/operator_alerts.py` (the routing platform) and `messaging_brain/notifications/operator_alerts.py` (a pre-booking-specific consumer of that platform). Same filename, different abstraction levels, ambiguous on read.

Renamed (2026-05-26) to:
- `messaging/operator_alerts.py` — the routing platform (unchanged)
- `messaging_brain/notifications/prebooking_review_alerts.py` — the pre-booking review alert consumer

Public function renamed: `_alert_operator_for_review` → `send_prebooking_review_alert` (dropped the leading underscore because the function is called from outside its module).

**The rule:** If a module is a feature-specific consumer of a generic platform, name it after the feature, not after the platform. Same-name-in-different-directories invites the wrong inference about consolidation.

---

## When to consolidate (almost never)

The architectural test for consolidation is the swap test: would you ever want to swap one layer without touching the other?

- **Add a new PMS transport tomorrow.** Tier 1 changes; Tier 2 unchanged; Tier 3 unchanged. ✓ Tier 1 is correctly bounded.
- **Replace `inbound_normalizer.py` with a new contract shape.** Tier 1 needs new adapters; Tier 3 needs to read the new contract. Both change, each through one clean interface. ✓ Tier 2 is correctly bounded.
- **Rewrite the brain with different specialists / different LLM providers.** Tier 1 unchanged; Tier 2 unchanged; Tier 3 changes extensively. ✓ Tier 3 is correctly bounded.

The healers don't fit this test because they cross all three tiers by design — that's their job. They belong in `agents/` precisely because they're cross-cutting.

If you find yourself proposing to merge tiers, ask: "Would this make external-format churn, contract changes, and brain changes collide in one directory?" If yes, the merge is the wrong move.

---

## Known current-state vs target-state inconsistencies

One deliberate layering inconsistency exists today and is documented for honesty:

**Operator knowledge ownership is conceptually a Tier 2 concern.** Storage, scope resolution, FAQ records, retrieval contracts, and document upload all describe what the operator knows and how it's stored — they should survive a brain rewrite.

**Some of the current implementation lives in Tier 3.** Specifically:
- `app/services/messaging_brain/knowledge/scoped_knowledge_service.py`
- `app/services/messaging_brain/knowledge/property_faq.py`
- `app/services/messaging_brain/knowledge/global_faq.py`
- `app/services/messaging_brain/knowledge/historical_import.py`
- `app/services/messaging_brain/knowledge/dashboard_kb_service.py`
- `app/services/messaging_brain/knowledge/topic_registry.py`

And ingestion lives in a pre-tier-model location:
- `app/services/concierge/guidebook_ingest_service.py`

**The product pathway uses the v2 adapter layer as the stable seam.** The v2 frontend at `app/static/dashboard-v2/src/api/index.js` exposes operator knowledge management through `api.kb.*`, `api.kbGaps.*`, `api.portfolios.*`, `api.properties.*`, document upload endpoints, and `api.settings.aiGuidance.*`. The adapter layer abstracts over the underlying module placement, so the layering inconsistency is not a product blocker.

**The long-term target** is to consolidate operator knowledge ownership under `app/services/messaging/knowledge/` with the layout sketched in `docs/OPERATOR_KNOWLEDGE_SUBSTRATE_CARRYFORWARD.md`. That migration is deferred until a product trigger justifies it (reuse pressure, testing friction, permissioning complexity, or intelligence-layer cross-scope reads).

**Triggers that would make the migration worth doing.** Each is a specific, observable signal — not a feeling. When you find yourself in one of these situations, the deferral has expired and the migration becomes the right next move.

1. **A second backend consumer needs the same scoped knowledge contract.** Today the brain is the only consumer of knowledge ownership data. If the operator intelligence layer (Workstream C), a new analytics module, an export pipeline, or any other backend service starts needing to read scoped knowledge, that's the trigger. Signal: more than one `from app.services.messaging_brain.knowledge.scoped_knowledge_service import ...` outside `messaging_brain/`.
2. **Permissioning logic starts duplicating across layers.** If operator role/permission work introduces access control patterns like "this user can edit property X's knowledge but not portfolio Y's," and the access checks end up living in the API layer AND the service layer AND the brain because there's no single ownership boundary, that's the trigger. Signal: scope-resolution logic appearing in more than one tier.
3. **Changes to knowledge ownership require unrelated brain changes.** If a PR that should be "add a new document type" or "add a new scope level" ends up touching `messaging_brain/orchestrator.py` or specialist agents because the modules are co-located, that's the trigger. Signal: knowledge-only PRs growing brain-side diffs.
4. **Workstream C (operator intelligence) needs stable retrieval contracts.** When pricing/intelligence modules need to consume operator knowledge as a signal source, they shouldn't have to import from `messaging_brain/` (which would create a Tier 3 → intelligence-layer dependency that violates the brain's role as decision-only). Signal: intelligence code importing from `messaging_brain/knowledge/`.
5. **Retrieval behavior starts being shared outside the brain path.** If anyone other than `context_builder_agent` and `faq_answering` is calling the retrieval interface (a CLI tool, a reporting job, a webhook handler), that's the trigger. Signal: callers of `scoped_knowledge_service.get_*` outside `messaging_brain/`.
6. **Testing friction.** If knowledge-layer tests start having to import or mock brain-internal modules, that's the trigger. Signal: test files in `tests/unit/test_*knowledge*` or `test_*scoped*` importing from `messaging_brain/agents/` or `messaging_brain/orchestrator.py`.

Until one of those fires, the modules stay where they are. The adapter layer protects the product pathway either way.

**For new operator-knowledge work in the meantime:** add features through the adapter layer (extend endpoints, extend frontend api client, extend backend services in their current locations). Do not start the migration speculatively.

---

## Data flow reference (pre-booking inbound, with tier annotations)

```
Gmail/Microsoft inbox
   │
   ▼  Tier 1: integrations/
gmail_inbox_poller.py  or  microsoft_inbox_poller.py
   │
   ▼
email_parser_router.py  (deterministic drop, parser selection)
   │
   ├─→ ota_email_parsers.py  (deterministic OTA match)
   ├─→ direct_email_parsers.py  (deterministic direct match)
   └─→ llm_email_extractor.py  (LLM fallback when deterministic fails)
   │
   ▼  Tier 2: messaging/
inbound_normalizer.py  →  CanonicalInboundMessage
   │
   ▼
identity_resolver.py  →  attaches GuestIdentityResolution
   │
   ▼  Tier 3: messaging_brain/
email_dispatch.py  →  dispatch_pre_booking
   │
   ▼
inbound_message_gate.py  (Anthropic classifier, with retry)
   │
   ▼
GuestMessageBrainOrchestrator
   │   ├─→ IntakeAgent  →  classification
   │   ├─→ FastPathStage  →  maybe short-circuit (FAQ / gate code / escalation)
   │   ├─→ ContextBuilderAgent  →  lazy context load
   │   ├─→ AgentRouter  →  specialists (identity-eligibility gated)
   │   ├─→ LLMComposerAgent  →  draft (multi-provider chain)
   │   ├─→ response_reviewer + hallucination_guard
   │   └─→ pre_booking_lifecycle  →  persistence with confidence_source
   │
   ▼  Tier 2: messaging/
operator_alerts.py  (routing platform: contact resolution, escalation, OOO)
   ▲
   │  invoked by Tier 3:
prebooking_review_alerts.py  →  send_prebooking_review_alert(...)

```

Daily 05:00 UTC, asynchronously:
```
   Cross-cutting: agents/
healer_runner.py  →  scan_all_tenants
   │
   ▼
healer_agent.py reads signals from:
   ├─→ Tier 1: message_normalizations (gate errors, drop reasons), property_mention_surface_audit
   └─→ Tier 3: brain_classifier_metadata (escalation events)
   │
   ▼
clusters, drafts proposals, writes to healer_proposals (status='pending')
   │
   ▼
Human approval via /healer/proposals/{id}/approve  →  writes back to:
   ├─→ canonical_property_identities  (Tier 2 matching surface)
   └─→ operator_settings.extra  (Tier 1 prefilter overrides, Tier 3 keyword overrides)
```

---

## TL;DR for someone landing in the codebase

- **Adding a new OTA parser, a new transport, a new email format adapter?** `app/services/integrations/`
- **Adding a new identity resolution path, a new outbound channel, a new canonical contract field, a new alert primitive?** `app/services/messaging/`
- **Adding a new specialist agent, a new fast-path, a new lifecycle coordinator, a new feature-specific alert consumer?** `app/services/messaging_brain/`
- **Adding a new healer, a new cross-cutting scheduled worker, a new sync agent?** `app/services/agents/`

If you're not sure which tier something belongs to, read the "defining test" section for each tier above. If the answer still isn't obvious, the new module probably needs splitting along the tier boundary rather than landing in one tier whole.

Do not collapse the tiers.
