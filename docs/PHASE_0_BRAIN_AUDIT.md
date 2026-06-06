# Phase 0 — Oyvoda Messaging Brain Audit

**Date:** April 29, 2026
**Purpose:** Map what exists vs. what's needed for the unified messaging brain.
**Verdict:** ~65% of the brain primitives already exist. Codex underestimated the codebase. The work is **wiring + a thin orchestrator + filling specific gaps** — not rebuilding.

---

## 1. Inventory: What exists, by target architecture component

| Target component | Exists? | File(s) | Maturity |
|---|---|---|---|
| `InboundGuestMessage` contract | ✅ Partial — for email only | `app/services/messaging/inbound_normalizer.py::CanonicalInboundMessage` | Production-grade for email; needs SMS/voice/web variants |
| `MessageClassification` contract | ❌ No formal contract | — | Implicit in `router_agent.py` (returns `RoutingDecision`) |
| `GuestContextBundle` contract | ❌ No formal contract | — | Context is built but not typed; `context_builder.py` returns dicts |
| `AgentDecision` contract | ❌ No formal contract | — | — |
| `ResponsePolicyDecision` contract | ✅ Yes, named differently | `app/services/messaging/autonomy_gate.py::GateResult` | Production-grade |
| `GuestResponseDraft` contract | ❌ No formal contract | — | Implicit in `ConciergeReply` (`concierge_runner.py`) |
| `AgentAuditLog` contract | ✅ Partial — DB schema exists | `message_event_store.py` writes to `message_normalizations`, `messages`, `conversations` tables | Tables exist; no per-decision audit yet |
| `ModuleEvent` / `ModuleResponse` | ❌ Conceptually defined, not implemented | `messaging_brain_contracts.py` defines `MessagingModuleAgent` Protocol, no implementations | Stub |
| **Brain stages (intake/parse/route/retrieve/draft/review/orchestrate)** | ✅ Defined as enum | `messaging_brain_contracts.py::MessagingBrainStage` | Defined; no orchestrator consumes them |
| **Lifecycle stages (pre_booking/pre_arrival/in_stay/post_stay/ops/system)** | ✅ Defined | `messaging_brain_contracts.py::MessagingLifecycle` | Used by `email_routing.py` |
| **Module contracts (messaging/maintenance/housekeeping/scheduling/documents)** | ✅ Defined as registry | `messaging_brain_contracts.py::default_messaging_module_contracts()` | Contracts exist; no module implementations bound |
| **Agent registry / framework** | ✅ Yes | `app/services/agents/agent_framework.py` (26KB) | Generic agent framework — for pricing/market intel, not messaging brain |
| **Router (intent classification)** | ✅ Production-grade | `app/services/agents/router_agent.py::ConciergeRouter` | 7 routes, watch-layer logging, EQ analyzer, keyword sets |
| **Context builder (knowledge retrieval)** | ✅ Yes | `app/services/concierge/context_builder.py` (functions); `concierge/knowledge_service.py` (60KB) | Production |
| **Pre-booking auto-send / confidence gate** | ✅ Yes | `app/services/concierge/pre_booking_auto_send.py` (69KB) | Production |
| **Response reviewer / risk gate** | ✅ Yes | `app/services/concierge/response_reviewer.py` (15KB) | Production |
| **AI draft generation** | ✅ Yes | `app/services/concierge/ai_concierge.py` (36KB) | Production |
| **Hallucination guard** | ✅ Yes | `app/services/concierge/hallucination_guard.py` | Production |
| **Escalation detection + service** | ✅ Yes | `app/services/concierge/escalation_service.py` (27KB); `app/services/agents/escalation_handoff_agent.py` (22KB) | Production — has detector AND service AND handoff agent |
| **Channel routing (outbound)** | ✅ Production-grade | `app/services/messaging/channel_router.py` | SMS live; RCS + ABM wired pending Twilio/Apple approval |
| **Inbound transport (per-channel webhooks)** | ✅ Yes | `app/services/messaging/inbound_transport.py`, `inbound_normalizer.py`, `channel_router.py::InboundMessageHandler` | SMS + ABM webhooks defined |
| **Email pipeline (parse → route → dispatch)** | ✅ Yes | `app/services/integrations/email_pipeline.py`, `email_parser_router.py`, `email_routing.py`, `email_inbound.py`, `email_dispatch.py`, `email_reply.py` | Production for Gmail/Microsoft polling + parsing |
| **PROACTIVE GUEST JOURNEY** | ✅ **Canonicalized** | `app/services/operator/stay_proactive_runtime.py`, `stay_proactive_service.py`, `stay_action_agent.py`, `messaging_brain/proactive_trigger_adapter.py` | As of 2026-05-28 the legacy `concierge/proactive/guest_journey.py` path is deleted; proactive runtime now flows through the stay workflow + action queue + brain composition path. |
| **Per-property AI autonomy / approval mode** | ✅ Production-grade | `app/services/messaging/autonomy_gate.py` | Migration 027 has `property_ai_autonomy` table; gate evaluates `confidence + policy + escalation + mode` → `auto_send` / `review` / `blocked` |
| **Maintenance service** | ✅ Yes | `app/services/concierge/maintenance_service.py` (15KB) | Auto-tracks from messages; CRUD on events |
| **PMS connectors (Escapia, etc)** | ✅ Yes | `app/services/connectors/pms_connectors.py`, `app/services/integrations/pms/`, `app/services/agents/pms_sync_agent.py` (15KB) | Multiple providers wired |
| **Knowledge gap auto-capture** | ✅ Yes | `app/services/concierge/kb_gap_manager.py` (25KB) + `concierge.py` endpoint | When intent=unknown or confidence<0.68, auto-records gap |
| **Operator alerts** | ✅ Yes | `app/services/messaging/operator_alerts.py` | — |
| **Message event store** | ✅ Production-grade | `app/services/messaging/message_event_store.py` | Shadow-writes to `channels`, `conversations`, `messages`, `message_normalizations` tables |

---

## 2. Endpoint sprawl / duplication report

### Concierge surfaces (multiple parallel implementations)
- `app/api/v1/endpoints/concierge.py` (33KB) — main `/concierge/message`, `/concierge/decision`, `/concierge/proactive`. Calls `ConciergeRunner` from `orchestration/`, NOT from `concierge/`.
- `app/api/v1/endpoints/sms.py` (14KB) — SMS webhook; calls `_generate_via_voice_pod()`. Different code path.
- `app/api/v1/endpoints/voice.py` (12KB) — voice webhook. Different code path.
- `app/api/v1/endpoints/messaging_webhooks.py` (7KB) — generic webhook handlers.
- `channel_router.py::InboundMessageHandler.handle_twilio_inbound()` — calls `sms.py::_generate_via_voice_pod` directly.

**Conclusion:** `/concierge/message` (HTTP), Twilio SMS webhook, and the email pipeline are **three independent entry points** that each hit different downstream code. The brain needs to unify them.

### "Concierge runner" — TWO of them
- `app/services/concierge/concierge_runner.py` (12KB) — re-exported via `__init__.py`
- `app/services/orchestration/concierge_runner.py` (12KB) — what the API endpoint actually imports

These are likely divergent. Needs reconciliation in Phase 1.

### Mobile endpoint versioning
- `mobile.py` (54KB), `mobile_v2.py` (21KB), `mobile_v3.py` (25KB) — three iterations, no consolidation.
- `operator_dashboard.py` (10KB), `operator_dashboard_v2.py` (54KB), `operator_dashboard_api.py` (232KB!) — three parallel surfaces.

**Out of scope for the brain.** Note for cleanup later.

### Historical note: old in-memory + DB-backed proactive
- This audit predated the 2026-05-28 cleanup. The old `proactive/guest_journey.py` file has since been deleted and its still-useful helpers were re-homed into `app/services/operator/stay_journey_service.py`.

**Current conclusion:** Legacy proactive path removed. Canonical proactive runtime is operator-owned and brain-backed.

---

## 3. Gap analysis: What's actually missing

Compared to the target architecture (Codex's spec, refined for Oyvoda's reality):

### Truly missing (must build)
1. **Universal `InboundGuestMessage` contract.** `CanonicalInboundMessage` exists but is email-shaped. Need a channel-agnostic version that SMS/voice/email/web all map to.
2. **`GuestContextBundle` Pydantic contract.** Context is assembled in multiple places returning untyped dicts. Need one type that flows through the orchestrator.
3. **`AgentDecision` contract.** Each specialist needs to emit a structured decision the policy gate can consume.
4. **`GuestMessageBrainOrchestrator` itself.** This is the single piece of new code that ties everything together. ~200 lines.
5. **`AgentAuditLog` per-message-decision table + writer.** Existing `messages` and `message_normalizations` tables capture inbound; nothing captures `(classification, agent_path, decisions, policy, final_draft)`. Need a new table or columns.
6. **Specialist module dispatchers.** Maintenance, housekeeping, access, late-checkout, local-recommendation, escalation — these need thin classes that wrap existing services and emit `AgentDecision`. Most existing logic is already there in `concierge/maintenance_service.py`, `concierge/dining_service.py`, `concierge/event_planning_service.py`, etc.
7. **Two-axis intent classification.** Current `ConciergeRouter` returns one of 7 routes. The brain wants `(type=question/problem/request, topic=access/maintenance/checkout/...)`. The existing keyword sets translate cleanly; just needs the schema.
8. **Email → unified brain wiring.** The email pipeline currently has its own three-way dispatch (`system_event`/`in_stay`/`pre_booking`). It should map parsed email → `InboundGuestMessage` → orchestrator.
9. **Proactive trigger orchestration through the same brain.** Completed on 2026-05-28 by routing scheduled proactive work through `app/services/operator/stay_proactive_runtime.py` → stay workflow/action queue → `OutboundIntent` → orchestrator → channel router.

### Already strong (just wire it in)
1. Channel routing (outbound) — `channel_router.py` is excellent, just plug it as the orchestrator's send tool.
2. Per-property autonomy gate — `autonomy_gate.py` IS the `ResponsePolicyAgent` Codex described, just with a different name.
3. Router/keyword classification — `router_agent.py::ConciergeRouter` IS the IntakeAgent + AgentRouter combined, just refactor its output to two-axis.
4. Knowledge / FAQ / context — `concierge/knowledge_service.py` + `context_builder.py` already do this; wrap as `ContextBuilderAgent`.
5. Escalation detection — `escalation_service.py::EscalationDetector` already does this; wrap as `EscalationAgent`.
6. Pre-booking confidence — `pre_booking_auto_send.py` already does this; folds into `ResponsePolicyAgent` alongside `autonomy_gate`.

### Parts to retire
1. Legacy `ProactiveJourneyService` (in-memory) — deleted on 2026-05-28 along with the old `guest_journey.py` path.
2. Whichever `concierge_runner.py` is stale (need to diff `concierge/` vs `orchestration/` — likely the `concierge/` one is older).
3. Per-channel dispatch in `email_pipeline.py` once the brain is wired.

---

## 4. The real architectural picture

```
                    ┌────────────────────────────────────────────┐
                    │         GuestMessageBrainOrchestrator       │
                    │              (NEW — ~200 lines)             │
                    └──────────────┬─────────────────────────────┘
                                   │
       ┌───────────────────────────┼─────────────────────────────────────┐
       │                           │                                     │
       ▼                           ▼                                     ▼
  Inbound paths              Specialist agents                    Outbound paths
                            (thin wrappers over services)
  • SMS webhook              • IntakeAgent
    (sms.py)                   wraps router_agent.py
  • Email pipeline           • ContextBuilderAgent                • ChannelRouter
    (email_pipeline.py)        wraps context_builder.py +           (channel_router.py)
  • /concierge/message         knowledge_service.py                  → SMS / RCS / ABM
    (concierge.py)           • AccessAgent
  • Voice webhook              wraps property knowledge          • Email reply
    (voice.py)               • MaintenanceAgent                    (email_reply.py)
  • Proactive triggers         wraps maintenance_service.py
    (guest_journey.py)       • LateCheckoutAgent                  Audit
                               wraps existing late-checkout
                               logic in concierge_runner.py        • message_event_store
                             • LocalRecommendationAgent              (existing — extend)
                               wraps event_planning_service.py +   • NEW agent_audit_logs
                               dining_service.py                     table
                             • EscalationAgent
                               wraps escalation_service.py
                             • ProactiveOutreachAgent
                               wraps GuestJourneyService

  Policy gate (one place):
  • ResponsePolicyAgent  =  autonomy_gate.py + pre_booking_auto_send (confidence) + response_reviewer (risk)
```

All inbound channels → `InboundGuestMessage` → Orchestrator → agents → `GuestResponseDraft` + `ResponsePolicyDecision` → outbound via ChannelRouter → audit log.

Proactive triggers also enter the Orchestrator (different entry shape: `OutboundIntent` instead of `InboundGuestMessage`) so they get the same context, policy, and audit.

---

## 5. Updated implementation sequence

**Codex's 18 steps were sequenced for a greenfield brain. Oyvoda is brownfield.** The right order is:

| Phase | Work | Estimated effort |
|---|---|---|
| **1** | **Reconcile contracts.** Open `messaging_brain_contracts.py`, add `InboundGuestMessage`, `MessageClassification`, `GuestContextBundle`, `AgentDecision`, `GuestResponseDraft`. Don't touch existing `MessagingBrainStage`/`MessagingLifecycle`/`MessagingModuleContract`/`MessagingConnectionContract` — extend, don't replace. | Half day |
| **2** | **Create `app/services/messaging_brain/orchestrator.py`.** Implement `GuestMessageBrainOrchestrator.handle_inbound_message()` and `.handle_proactive_trigger()`. Wire in: existing `ConciergeRouter` (intake), existing `context_builder.py` (context), one specialist (start with KnowledgeAgent — simplest), existing `autonomy_gate.evaluate()` (policy), existing `channel_router.send()` (outbound). | 1 day |
| **3** | **Add `agent_audit_logs` table + writer.** New migration. Single insert per orchestrator call. | Half day |
| **4** | **Wire `/concierge/message` through the orchestrator behind a feature flag.** Existing endpoint stays as fallback. | Half day |
| **5** | **Add `MaintenanceAgent` + `EscalationAgent`.** Both are wrappers over existing services. | 1 day |
| **6** | **Wire proactive `evaluate_triggers()` through the orchestrator.** Reuse audit/policy/channel routing. | Half day |
| **7** | **Wire email pipeline through the orchestrator.** `email_pipeline.process_routed_email()` maps parsed → `InboundGuestMessage` → orchestrator. Old three-way dispatch retired. | 1 day |
| **8** | **Add remaining specialists.** AccessAgent, LateCheckoutAgent, LocalRecommendationAgent, HouseRulesAgent. Each is a thin wrapper. | 1-2 days each |
| **9** | **End-to-end tests.** AC-not-working, door-code, late-checkout, rainy-day-kids, refund-complaint, welcome-on-booking. | 1 day |

**Total: ~7-10 days of focused work to get the unified brain live**, vs. the 3-4 weeks Codex's plan implies because Codex didn't know what already existed.

---

## 6. Decisions still needed from Hunter

1. **Which `concierge_runner.py` is canonical?** The one in `orchestration/` (used by API) or `concierge/` (re-exported via `__init__`)?
2. **`agent_audit_logs` schema:** new table, or columns on `messages`?
3. **Feature flag mechanism:** existing `app/services/feature_flags.py` or env var?
4. **First specialist to build after IntakeAgent + ContextBuilderAgent:** Knowledge (simplest, validates the spine) or Maintenance (highest user value)?

---

## 7. The framework verdict (final)

**Custom orchestration with Pydantic contracts. NOT LangGraph. NOT a new framework.**

Rationale:
- ~65% of the brain primitives already exist as plain Python classes/functions.
- Adopting LangGraph would orphan `autonomy_gate`, `channel_router`, `router_agent`, `message_event_store`, `guest_journey`, and require rewriting them as graph nodes.
- IRIS uses custom orchestration; Oyvoda should match for cognitive consistency.
- The "checkpoint/resume" capability LangGraph markets is solved here by `message_event_store` + Celery tasks. The `evaluate_triggers()` pattern in `guest_journey.py` is exactly the resume pattern.
- Adding LangGraph means two paradigms across IRIS + Oyvoda. Bad bet for a solo builder.

The orchestrator itself is ~200 lines of Python. It's not where complexity lives — complexity lives in the existing services, which is correct.
