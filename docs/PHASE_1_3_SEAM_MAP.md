# Phase 1.3 Seam Map

**Date:** April 29, 2026
**Status:** Reading pass complete. No code written yet.
**Purpose:** Document every seam between the messaging brain and existing services
before writing any 1.3 code. Refined per-file write plan at the end.

---

## Critical architectural finding: ordering constraint is real

`autonomy_gate.evaluate(triggered_by_message_id=...)` requires the **internal
DB UUID** of the inbound message (the `messages.message_id` row), not the
source-provider message ID.

That UUID is returned by `message_event_store.persist_canonical_inbound_message()`
in the `"message_id"` field of its result dict.

**Therefore the orchestrator pipeline order is fixed:**

```
1. Adapter: InboundGuestMessage → CanonicalInboundMessage
2. message_event_store.persist_canonical_inbound_message(db, tenant_uuid, canonical)
   → returns {"normalization_id": ..., "message_id": <UUID>, ...}
3. IntakeAgent.classify(message)
4. ContextBuilderAgent.build(message, classification)
5. AgentRouter.route(classification)
6. Specialists run; emit AgentDecisions with ModuleEvents (not yet dispatched)
7. ResponsePolicyAgent.evaluate(
       triggered_by_message_id = step-2-uuid,  ← key wiring
       confidence = avg specialist conf,
       stage = lifecycle-mapped,
       property_id = step-4-context,
       policy_warnings = []  # phase 1.3 has no warnings yet
   )
8. Compose response from decisions + policy
9. If policy.final_action != ESCALATE: dispatch ModuleEvents to modules
   (modules respect shadow_mode flag — skip side effects in shadow)
10. message_event_store.update_normalization_outcome(
       source_channel, source_message_id,
       route_outcome=classification.intent_topic,
       draft_source="messaging_brain",
       selected_property_code=...,
       fallback_reason=... (if any)
    )
11. AgentAuditRecord finalized; logged at INFO; full record returned
```

Steps 2 and 7 are the highest-risk wiring. Tested explicitly in 1.3a.

---

## Per-file seam findings

### 1. `app/services/messaging/autonomy_gate.py`

**Use:** `evaluate(db, *, tenant_id: UUID, property_id: Optional[UUID], stage: str, confidence: float, policy_warnings: list, triggered_by_message_id: Optional[UUID] = None) -> GateResult`

**Translation table** (autonomy_gate ↔ messaging brain contracts):

| autonomy_gate                          | brain                                  |
|----------------------------------------|----------------------------------------|
| `AutonomyDecision.AUTO_SEND`           | `RecommendedAction.AUTO_SEND`          |
| `AutonomyDecision.REVIEW`              | `RecommendedAction.DRAFT_ONLY`         |
| `AutonomyDecision.BLOCKED_BY_ESCALATION` | `RecommendedAction.ESCALATE`         |
| `GateResult.approval_mode_at_decision` | `ResponsePolicyDecision.approval_mode_at_decision` |
| `GateResult.blocking_escalation_id` (UUID) | `ResponsePolicyDecision.blocking_escalation_id` (str) |
| `GateResult.reason`                    | `ResponsePolicyDecision.reasons[0]`    |

**Stage translation** — autonomy_gate accepts `"all" | "pre_booking" | "booked_pre_arrival" | "in_stay" | "post_stay"`. Our `MessagingLifecycle` uses `"pre_arrival"` (no `"booked_"` prefix). Map:

| MessagingLifecycle | autonomy_gate stage |
|---|---|
| `PRE_BOOKING`  | `"pre_booking"` |
| `PRE_ARRIVAL`  | `"booked_pre_arrival"` |
| `IN_STAY`      | `"in_stay"` |
| `POST_STAY`    | `"post_stay"` |
| `OPS`          | `"all"` |
| `SYSTEM`       | `"all"` |

**Type conversions needed:**
- `tenant_id`: brain has `str`, gate wants `UUID`. Use `UUID(message.tenant_id)`.
- `property_id`: brain has `Optional[str]`, gate wants `Optional[UUID]`. Try-cast or pass None.
- `triggered_by_message_id`: gate wants `Optional[UUID]`. The persist call returned a string; cast back: `UUID(persist_result["message_id"])` if present.

---

### 2. `app/services/messaging/message_event_store.py`

**Two functions used:**

`persist_canonical_inbound_message(db, tenant_id: UUID, normalized: CanonicalInboundMessage) -> Dict[str, Optional[str]]`
- Takes a `CanonicalInboundMessage` dataclass (NOT our Pydantic InboundGuestMessage).
- Returns dict with keys: `normalization_id`, `message_id`, `conversation_id`, `channel_id`. **`message_id` is the value we need for autonomy_gate.**
- Fail-open: returns `{}` on any DB exception.

`update_normalization_outcome(db, tenant_id: UUID, source_channel: str, source_message_id: str, *, route_outcome: str = "", draft_source: str = "", selected_property_code: str = "", selected_property_match_type: str = "", fallback_reason: str = "") -> None`
- Keyed by `(tenant_id, source_channel, source_message_id)` — uses original SOURCE message ID.
- Fail-open: silent rollback on exception.

**Adapter required:** `InboundGuestMessage → CanonicalInboundMessage`. Lives in audit.py or in a new helper. Fields map mostly 1:1; the brain shape is a strict superset of what canonical needs.

---

### 3. `app/services/agents/router_agent.py::ConciergeRouter`

**Constructor:** `ConciergeRouter(context, eq_analyzer=None, watch=None, session_id="unknown")`. **All three optional dependencies accept None.** Context is duck-typed — only needs `.property_code` and `.operator_id` attributes (read with `getattr` defaults).

**For IntakeAgent:** pass a tiny dataclass with just those two fields. No EQ analyzer for 1.3 (we'll keep `_eq=None`). No watch layer (`_watch=None`).

**Method:** `await router.route(message: str, conversation_turns: int = 0, history: Optional[list] = None) -> RoutingDecision`

**Translation: ConciergeRouter Route → (IntentType, intent_topic, urgency, requires_human_review)**

| Route | Trigger keyword check | IntentType | intent_topic | urgency | review |
|---|---|---|---|---|---|
| `ESCALATE_URGENT` | always emergency | `PROBLEM` | `emergency` | `EMERGENCY` | `True` |
| `ESCALATE_HIGH` | trigger ∈ `{"refund","compensation","money back","disgusting","unacceptable","filthy","dirty"}` | `PROBLEM` | `complaint` | `HIGH` | `False` |
| `ESCALATE_HIGH` | otherwise (broken/leak/ac/pest/etc.) | `PROBLEM` | `maintenance` | `HIGH` | `False` |
| `ESCALATE_HIGH` | trigger == `"conversation_length"` | `REQUEST` | `general` | `HIGH` | `True` |
| `ESCALATE_EQ` | always | `PROBLEM` | `complaint` | `HIGH` | `True` |
| `QUICK_ANSWER` | always | `QUESTION` | `access` | `MEDIUM` | `False` |
| `PMS_QUERY` | trigger ∈ `{"late checkout","early check-in","extend my stay","extra night"}` | `REQUEST` | `late_checkout` | `MEDIUM` | `False` |
| `PMS_QUERY` | otherwise | `QUESTION` | `booking_inquiry` | `MEDIUM` | `False` |
| `KNOWLEDGE_LOOKUP` | trigger ∈ `{"pet","smoke","rule","quiet","trash"}` | `QUESTION` | `house_rules` | `LOW` | `False` |
| `KNOWLEDGE_LOOKUP` | trigger ∈ `{"restaurant","eat","food","dining","activity","things to do","near","nearby","local"}` etc. | `QUESTION` | `local_recommendation` | `LOW` | `False` |
| `KNOWLEDGE_LOOKUP` | otherwise | `QUESTION` | `general` | `LOW` | `False` |
| `LLM_GENERAL` | always | `QUESTION` | `general` | `MEDIUM` | `False` |

Confidence is derived from the route: `ESCALATE_*` → 0.92, `QUICK_ANSWER` → 0.88, `PMS_QUERY` → 0.80, `KNOWLEDGE_LOOKUP` → 0.75, `LLM_GENERAL` → 0.55.

The `RoutingDecision.reason` flows into `MessageClassification.reason`. The `RoutingDecision.trigger` flows into `MessageClassification.matched_keyword`. The `Route.value` flows into `MessageClassification.matched_route`.

---

### 4. `app/services/operator/work_order_service.py`

**Use:** `get_operator_work_order_service().create_or_refresh_work_order(...)`

**Highly idempotent.** Dedupe key = `(tenant_id, workflow_type, workflow_ref)`. Re-running on the same message updates rather than inserts.

**MaintenanceModule call:**

```python
result = await wo_service.create_or_refresh_work_order(
    session,
    tenant_id=tenant_id_str,
    workflow_type="messaging_brain_maintenance",
    workflow_ref=inbound.message_id,  # source message ID — stable per-message
    property_code=inbound.property_code or None,
    issue_category="maintenance",
    priority=severity,  # "low"|"medium"|"high" from category classifier
    summary=summary_text,
    details=inbound.text,
    dispatch_state="opened",
    last_actor_label="messaging_brain",
    payload={
        "module_event_id": module_event.event_id,
        "concierge_event_id": concierge_event_id_or_None,  # ← LINK to concierge event
        "category": event_type,
        "guest_id": inbound.guest_id,
        "guest_phone": inbound.guest_phone,
        "reservation_id": inbound.reservation_id,
        "source_channel": inbound.channel,
        "source_message_id": inbound.message_id,
    },
)
```

**Vendor fields stay null** for 1.3 — operator-only routing. Plumbing supports vendor add-on later.

**No dry-run mode.** Shadow mode skips the call entirely.

---

### 5. `app/services/concierge/maintenance_service.py`

**Two writers exist** — they go to different tables:
- `concierge/maintenance_service.py` writes to `concierge_maintenance_events` (lightweight tracking, dedupe, severity classifier, optional notifications)
- `operator/work_order_service.py` writes to `operator_work_orders` (operational dispatch, vendor lifecycle, ETA, invoicing)

**MaintenanceModule writes both, with explicit linking** (see "Maintenance dual-table ownership rule" below).

**Use from concierge/maintenance_service:**
- `MAINTENANCE_KEYWORDS` constant for category mapping (`"ac" → "hvac"`, `"leak" → "plumbing"`, etc.)
- `_severity_for(text)` for high/medium/low
- `_category_for(text)` for the category string
- `auto_track_from_message(...)` to write the concierge event
  - Returns dict with `created` (the event row) or `resolved` (if it was a resolution message)
  - **Already idempotent via 72-hour dedupe window**

---

### 6. `app/services/concierge/knowledge_service.py`

**ContextBuilderAgent uses three methods (already used by existing endpoint):**

```python
knowledge = await knowledge_service.get_for_property(
    session=session, tenant_id=tenant_uuid,
    property_id=brain_property_uuid_or_none,
    property_external_id=brain_property_code_or_none,
)
property_profile = knowledge_service.build_property_profile(knowledge)
# knowledge.facts, knowledge.faq, knowledge.sections, knowledge.property_context
```

The `knowledge` object has `.facts`, `.faq`, `.sections`, `.property_context` attributes.

**Evidence keys ContextBuilderAgent populates** (when present in knowledge):
- `property_facts.wifi`, `property_facts.check_in`, `property_facts.check_out`, `property_facts.hvac_type` (etc.)
- `property_knowledge.faq_count`
- `property_knowledge.sections.overview` (etc.)

For the AC slice, `property_facts.hvac_type` and `property_facts.thermostat_location` are the relevant evidence keys MaintenanceAgent will cite.

---

### 7. `app/services/messaging/inbound_normalizer.py::CanonicalInboundMessage`

This is a `@dataclass` (not Pydantic). The brain's `InboundGuestMessage` is Pydantic. Need an adapter.

**Adapter location:** `app/services/messaging_brain/audit.py`.

---

### 8. `app/api/v1/endpoints/concierge.py::handle_message`

**1.3b modification:** flag check at the top, pass-through to existing logic when off.

```python
@router.post("/message", response_model=MessageResponse)
async def handle_message(...):
    flags = get_feature_flags(session)
    if await flags.is_enabled(
        FeatureFlag.MESSAGING_BRAIN_RUNTIME,
        company_id=str(tenant.company_id),
        property_code=request.property_external_id,
    ):
        shadow_mode = await flags.is_enabled(
            FeatureFlag.MESSAGING_BRAIN_SHADOW_MODE,
            company_id=str(tenant.company_id),
            property_code=request.property_external_id,
        )
        return await _handle_via_brain(request, tenant, session, shadow_mode=shadow_mode)
    # Existing path — unchanged
```

`MessageResponse` shape stays bit-for-bit identical.

---

## Architectural design rules (locked for Phase 1.3 and beyond)

These are the non-negotiable rules that this design depends on. Any future
work that breaks them is a regression. They're documented here AND repeated
as comments at the top of `orchestrator.py` and `maintenance_module.py`
because the constraints are not obvious from reading either file in isolation.

### Rule 1: Inbound persistence runs BEFORE policy evaluation

`autonomy_gate.evaluate()` requires the internal `messages.message_id` UUID,
which only exists after `persist_canonical_inbound_message` writes the
inbound row. The orchestrator MUST call `persist_inbound()` before
`policy.evaluate()`. Reordering this for "performance" or "cleanliness" will
break escalation blocking and produce silently-wrong policy decisions.

### Rule 2: MaintenanceModule is the single owner of the dual-table relationship

The brain never writes `concierge_maintenance_events` or `operator_work_orders`
directly. Only `MaintenanceModule.handle_event()` writes either table, and
it ALWAYS writes both in the same call so they cannot disagree.

The work order's `payload_json["concierge_event_id"]` references the concierge
event ID. That's the explicit link. Future readers can join the two tables
via that field.

If you find code outside `maintenance_module.py` writing to either table:
either it's pre-existing legacy code (leave it alone in Phase 1) or it's a
bug (fix it).

### Rule 3: The work order is the operational spine for vendor follow-up

When vendor routing arrives in a future phase, vendor flow MUST update the
existing work order, never create a parallel record. The dispatch_state
lifecycle on `operator_work_orders` is sufficient for the entire vendor flow
(opened → contacting_vendor → accepted → scheduled → en_route → on_site →
work_completed → awaiting_verification → verified → closed).

The future shape:
- Guest issue → MaintenanceAgent → MaintenanceModule creates work order (Phase 1)
- VendorRoutingModule reads work order, picks vendor, updates work order
  (`dispatch_state="contacting_vendor"`, `vendor_id`, `vendor_name`,
  `vendor_phone`)
- Vendor responds → updates work order (`dispatch_state="accepted"`,
  `eta_minutes`, `tracking_url`)
- Brain's proactive layer reads work order state and emits
  `OutboundIntent(trigger_type="maintenance_eta_update")` so the guest
  gets the ETA via the same channel/audit/policy path
- Vendor finishes → updates work order (`dispatch_state="work_completed"`)
- Operator verifies → updates work order (`verification_state="verified"`,
  `dispatch_state="closed"`)

The brain's MaintenanceAgent doesn't change. The brain's pipeline doesn't
change. New module is added; orchestrator's module registry gains one entry.

### Rule 4: Modules own the work, agents own the decision

Agents emit ModuleEvents. They DO NOT call services that write to operational
tables. If an agent finds itself directly invoking a write-side service,
that's the signal to extract a module.

### Rule 5: Shadow mode is at the module execution boundary

Agents always run regardless of shadow mode — they classify, build context,
emit events. Modules check `shadow_mode` and skip side-effecting writes when
true. Audit shadow-writes still happen in shadow mode (that's how operators
validate the brain works before flipping the live switch).

---

## Refined per-file write plan for 1.3a

Implementation files (in dependency order):

1. `messaging_brain/audit.py` — adapter + dual-entry audit writer
2. `messaging_brain/modules/__init__.py`
3. `messaging_brain/modules/base.py` — protocol + registry
4. `messaging_brain/modules/maintenance_module.py` — dual-table writer, shadow-aware
5. `messaging_brain/agents/response_policy_agent.py` — wraps autonomy_gate
6. `messaging_brain/agents/context_builder_agent.py` — wraps knowledge_service
7. `messaging_brain/agents/maintenance_agent.py` — uses _category_for + _severity_for
8. `messaging_brain/agents/intake_agent.py` — wraps ConciergeRouter
9. `messaging_brain/orchestrator.py` — modified: real defaults, dispatch, shadow
10. `messaging_brain/__init__.py` — modified: export new symbols
11. `messaging_brain/agents/__init__.py` — modified: export new agents
12. `tests/unit/test_messaging_brain_ac_slice.py` — five test cases

Total: ~9 new files, 3 modified.

---

## Surprises that shaped the plan

1. **Two maintenance writers in different tables.** Documented as Rule 2.

2. **Stage names don't match between brain and autonomy_gate.** Translation lives in ResponsePolicyAgent.

3. **`_LEGACY_SCHEMA = True` in knowledge_service.** Use `get_for_property` (public method); don't query directly.

4. **Audit shadow-writes inbound BEFORE the orchestrator runs.** Documented as Rule 1.

5. **`work_order_service` is fully idempotent.** `inbound.message_id` as `workflow_ref` means retries → same work order.

---

## Verification gates for 1.3a (locked)

1. Full project test suite green vs. last-known-green baseline (`38b66ae`).
2. Brain-only tests green (`tests/unit/test_messaging_brain_*`).
3. **Ordering test** passes: explicit assertion that `persist_canonical_inbound_message` is called before `autonomy_gate.evaluate`.
4. **Shadow mode test** passes: no work order created, no concierge event created, audit still written.
5. **Evidence-key contract test** passes: `MaintenanceAgent.evidence_used` is populated from context when context has hvac fields, empty when not.
6. JSON round-trip of full `AgentAuditRecord` still clean (regression from 1.2).
7. **Linking test**: work order payload contains `concierge_event_id` referencing the concierge event written in the same module call.

## Verification gates for 1.3b (locked)

1. All 1.3a gates still green.
2. Concierge endpoint tests: flag OFF → existing behavior bit-for-bit identical.
3. Concierge endpoint tests: flag ON → orchestrator invoked, response shape matches `MessageResponse`.
4. Concierge endpoint tests: flag ON + shadow ON → orchestrator invoked, no work order, audit written.
5. Manual test: AC message with flag OFF → behavior unchanged.
6. Manual test: AC message with flag ON, shadow ON → audit row visible, no work order.
7. Manual test: AC message with flag ON, shadow OFF → work order created, audit row visible, work order payload contains concierge_event_id link.
8. Rollback recipe documented in commit message and verified with `disable_property()`.
