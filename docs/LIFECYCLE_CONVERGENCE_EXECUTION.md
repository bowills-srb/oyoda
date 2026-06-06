# Lifecycle Convergence Execution Plan

**Goal:** Make the brain the sole decision plane for every guest message across pre-booking, pre-arrival, in-stay, and post-stay — without losing the cost/latency wins the concierge MCP pipeline currently provides. Historical note: this plan originally referenced `proactive/guest_journey.py`; that file was retired on 2026-05-28 and proactive outbound now runs through `operator/stay_proactive_runtime.py` plus the stay workflow/action queue before entering brain.

**Status going in:**
- Pre-booking closeout complete (commits through `18f055d`). Brain is sole pre-booking classifier/decider/drafter/persister.
- `PreBookingBrainOrchestrator` + `LLMComposerAgent` + specialist agents + `pre_booking_lifecycle.py` are the working pattern.
- `session_channel_adapter.run_session_channel_message` already exists and already routes session messages through brain via `phase_to_lifecycle()`. It is not currently the entry path used by `ai_concierge.get_ai_response`.
- `proactive_trigger_adapter.py` already exists and routes proactive touches into brain via `OutboundIntent`. The old `guest_journey.py` plumbing described here has since been replaced by the operator-owned proactive runtime.
- `ai_concierge.get_ai_response` runs its own MCP-driven pipeline with FAQ fast-path (LLM bypass at confidence ≥ 0.90), keyword-gated lazy context fetches (`_needs_property_facts`, `_needs_local_knowledge`, `_needs_nearby_availability`), and dual-provider routing (Groq primary, Anthropic Haiku for complex/high-value).
- `CanonicalInboundMessage` exists in `app/services/messaging/inbound_normalizer.py` and is the inbound contract every transport normalizes into.

**Architectural rule (governs every decision below):**
The brain is the sole decision plane. Specialists own structured decisions with cited evidence. The composer (`LLMComposerAgent`) is the sole LLM call site for response generation. The grounding stage is the sole post-LLM quality gate. Lifecycle is a property of the message (derived from identity + dates), not of the transport.

The concierge's two production-load-bearing capabilities — LLM-bypass at high confidence and lazy keyword-gated context fetching — get ported into brain stages so convergence is a port, not a regression.

**Closure criteria:**
1. `ai_concierge.get_ai_response` is a thin call into the brain. No parallel composer. No parallel grounding pass.
2. The brain has a fast-path stage that can exit the pipeline before specialist routing when a high-confidence deterministic answer is available (FAQ, gate code intercept, escalation).
3. The brain has a lazy context stage that fetches property facts, knowledge retrieval, and nearby-portfolio data only when intent-gating keywords match.
4. Every inbound `CanonicalInboundMessage` carries an `IdentityResolution` that brain reads to decide specialist eligibility and autonomy.
5. The proactive runtime routes through `handle_proactive_trigger` — no parallel LLM call.
6. One `confidence_source` enum covers all four lifecycle stages and the proactive path.
7. The token-based guest model (multiple tokens per property, each independent) works correctly — every brain decision is keyed off the session token's identity, not the property.

**Explicitly not in scope:**
- Replacing the LLMComposerAgent's provider chain. It stays as Anthropic Haiku → Groq → Gemini → concatenation fallback. The concierge's Groq-primary routing is replaced by composer's chain; high-value Claude routing becomes a composer-level decision based on incoming context complexity, not a parallel pipeline.
- Schema changes beyond extending the `confidence_source` enum and adding `IdentityResolution` columns where needed.
- Historical note: this line predates the 2026-05-28 cutover. The old proactive scheduler is gone; trigger production now lives on the canonical operator/stay workflow path.
- Multi-tenant rollout. Lanier remains the single test tenant.
- New outbound channels (SMS-native, PMS-native) — those are future transport work and don't change the brain's contract.

**Token model (critical, easy to get wrong):**
Each booked guest on a property gets a session token (`gh_xxxxxxxx`). Six guests on one property = six independent tokens, each with its own conversation state, journey progress, gate code visibility window, and feedback collection.

Every brain call for an inbound session message MUST:
- Resolve the token to its `IdentityResolution` (identified guest with reservation_id, guest_name, guest_email, guest_phone)
- Key audit records, knowledge-gap logging, and confidence persistence off the token's identity, not the property
- Make specialist decisions per-token — `MaintenanceAgent` running for token A's "AC is broken" doesn't affect token B's pipeline

The brain's `InboundGuestMessage` already carries `session_token`; the `ContextBuilderAgent` already reads it. The work here is ensuring `IdentityResolution` flows through and that no specialist or fast-path accidentally collapses two tokens' state into one.

---

## Part 1: Pre-flight audit before any commit

Before writing code, run these greps to confirm the current surface area matches the assumptions in this plan.

```bash
# Confirm ai_concierge's MCP-tool call sites — these are what becomes brain stages
rg -n "registry\.call" app/services/concierge/ai_concierge.py

# Confirm proactive trigger entry exists and what calls it today
rg -n "handle_proactive_trigger" app/

# Confirm session_channel_adapter is the brain entry for sessions today
rg -n "run_session_channel_message" app/

# Confirm the keyword-gate functions exist in their current form
rg -n "_needs_property_facts|_needs_local_knowledge|_needs_nearby_availability" app/services/concierge/ai_concierge.py

# Confirm IdentityResolution doesn't already exist somewhere
rg -n "IdentityResolution|identity_resolution" app/

# Confirm the confidence_source enum migration is 086 and where the enum is defined
rg -n "confidence_source" migrations/ db/

# Historical note: the old proactive file is gone; inspect the canonical runtime emit path instead
rg -n "emit_proactive|proactive_outreach|handle_proactive_trigger" app/services/operator/stay_proactive_runtime.py app/services/operator/stay_action_agent.py app/services/messaging_brain/
```

The plan below assumes:
- **7** MCP `registry.call` sites in `ai_concierge.py`, mostly to the `concierge` MCP server (verified pre-flight)
- `handle_proactive_trigger` exists on `GuestMessageBrainOrchestrator` and accepts an `OutboundIntent`
- `run_session_channel_message` is callable from the session message endpoint but `get_ai_response` doesn't currently route through it
- **`IdentityResolutionError` already exists** as an exception type. The new identity dataclass MUST use a different exact name to avoid collision — use `GuestIdentityResolution` throughout this doc and the code
- `confidence_source` is a Postgres enum at migration 086, used by `pre_booking_inquiries`

If any of these are wrong, **adjust the plan before executing**, not during.

---

## Part 2: The three sessions

### Session A: FastPathStage + LazyContextStage in brain

**Goal:** Add the two capabilities the brain is missing that the concierge has today. After this session, the brain can match the concierge's cost/latency profile.

**Architectural shape:**

The brain's existing pipeline is:
```
0. audit.persist_inbound()
1. IntakeAgent.classify()
2. ContextBuilderAgent.build()     ← eager today, becomes lazy
3. AgentRouter.route()
4. specialists run
5. ResponsePolicyAgent.evaluate()
5.5. emit KB gaps
6. compose_response()              ← LLM call
7. (if !ESCALATE) dispatch modules
8. audit.write()
```

After this session:
```
0. audit.persist_inbound()
1. IntakeAgent.classify()
1.5. FastPathStage                 ← NEW: try deterministic exit before specialists
        ↓ if hit: short-circuit to step 8 with confidence_source='faq_fast_path'
                  or 'escalation_routed' or 'gate_code_intercept'
2. LazyContextStage                ← REPLACES eager ContextBuilderAgent.build()
        ↓ only fetches what intent gates indicate is needed
3. AgentRouter.route()
4. specialists run
5. ResponsePolicyAgent.evaluate()
5.5. emit KB gaps
6. compose_response()
7. (if !ESCALATE) dispatch modules
8. audit.write()
```

**Step A1: Extend `confidence_source` enum**

Migration adding values to the Postgres enum:
- `faq_fast_path` — answer came from FAQ deterministic match, no LLM call ran
- `escalation_routed` — message routed to human handoff before composer
- `gate_code_intercept` — gate code time-locked deterministic response
- `session_composer` — session-message LLM composition (for distinguishing in-stay from pre-booking `model_composer`)
- `proactive_trigger` — outbound message generated from a proactive trigger

Verify the migration is additive only; don't rename existing values. The dashboard's `_confidence_meta` function in `operator_prebooking.py` needs corresponding label additions but its existing branches keep working.

**Step A2: `FastPathStage`**

New file: `app/services/messaging_brain/stages/fast_path_stage.py`.

The stage runs after `IntakeAgent.classify()` and before `ContextBuilderAgent`. It tries three checks in order, returning early if any hit:

1. **Escalation check** — port `concierge.check_escalation` logic into a brain-side check. If escalate=True, return a `FastPathResult` with `confidence_source='escalation_routed'`, response text from `_escalation_response()`, recommended_action=ESCALATE.

2. **Gate code intercept** — port `intercept_gate_code_request` logic. If the message matches gate-code intent + session is identified + time window valid + property has active code, return the code with `confidence_source='gate_code_intercept'`.

3. **FAQ fast-path** — port `get_faq_answer` logic. If FAQ confidence ≥ 0.90 for an identified property, return the answer with `confidence_source='faq_fast_path'`.

Stage returns `Optional[FastPathResult]`. None means "no fast-path hit, continue to context builder + specialists."

The brain orchestrator's `handle_inbound_message` checks for the fast-path result after `IntakeAgent.classify()` and short-circuits the rest of the pipeline if present. **The audit row still gets written** with the fast-path's confidence_source; this is non-negotiable for the per-token audit requirement.

**Step A3: `LazyContextStage`**

The current `ContextBuilderAgent.build()` eagerly assembles the full context bundle. Replace this with a stage that:

1. Always loads minimum-viable context (session_token resolution, identified-guest fields, reservation_facts)
2. Conditionally loads heavier context based on classification + keyword gates:
   - `property_facts` only if `_needs_property_facts(text)` or classification.intent_topic in `{maintenance, access, house_rules, late_checkout}`
   - `retrieved_knowledge` only if `_needs_local_knowledge(text)` or classification.intent_topic == `local_recommendation`
   - `nearby_portfolio` only if `_needs_nearby_availability(text)`
   - `market_context` only if classification.intent_topic in `{booking_inquiry, pricing}`
   - `bd_insight` only if BD service's `should_generate(text)` returns true

The keyword-gate functions (`_needs_*`) port directly from `ai_concierge.py` into a brain-side helper module. They're pure functions.

Implementation note: `ContextBuilderAgent` stays as the class; its `build()` method changes from "load everything" to "load what's needed." The seam is internal to the agent. Specialists that depend on now-conditional fields handle absence gracefully (already a contract in the codebase — see `MaintenanceAgent._cite_evidence` which only cites keys that are present in `evidence_keys`).

**Step A4: Feature flags**

Both new stages behind feature flags:
- `MESSAGING_BRAIN_FAST_PATH_STAGE` — defaults off, on for Lanier
- `MESSAGING_BRAIN_LAZY_CONTEXT_STAGE` — defaults off, on for Lanier

This lets us verify the brain produces identical pre-booking outcomes with these stages on, before depending on them for session messages.

**Step A5: Tests**

New test files:
- `tests/unit/test_fast_path_stage.py` — covers all three short-circuit paths and the no-hit pass-through. Includes a test that confirms the audit row is written with the correct `confidence_source` even when fast-path hits.
- `tests/unit/test_lazy_context_stage.py` — covers each gate (property_facts on/off, knowledge on/off, nearby on/off) and the minimum-viable always-loaded fields.

Existing pre-booking tests should pass unchanged with both flags on, because pre-booking's intake currently routes to specialists that need full context — the lazy stage loads what they need.

**Verification before merging:**
- Pre-booking test battery passes with both flags on for Lanier
- A "wifi?" session message produces a row with `confidence_source='faq_fast_path'` if a property FAQ exists, otherwise `confidence_source='session_composer'` after going through specialists
- A gate-code message during the time-locked window returns the code with `confidence_source='gate_code_intercept'` and never calls the composer
- Operator alert SMS still fires for ESCALATE outcomes

**Estimated size:** 1 session, ~6-8 commits.

---

### Session B: IdentityResolution + autonomy gate

**Goal:** Add a structured identity signal to the inbound contract. Use it to enable auto-send for identified guests on high-confidence answers.

**Architectural shape:**

```python
@dataclass(frozen=True)
class GuestIdentityResolution:
    """Resolved guest identity for a CanonicalInboundMessage.

    Named GuestIdentityResolution (not IdentityResolution) to avoid
    collision with the existing IdentityResolutionError exception type
    in app/services/identity/dual_write.py.
    """
    state: str  # 'identified' | 'linked' | 'pseudonymous' | 'anonymous'
    reservation_id: str = ''
    session_token: str = ''
    guest_name: str = ''
    guest_email: str = ''
    guest_phone: str = ''
    resolution_source: str = ''  # 'session_token' | 'reservation_match' | 'ota_thread' | 'none'
    confidence: float = 0.0  # how confident we are in the identity match
```

State semantics:
- **identified**: reservation_id + session_token + guest_name + at least one of email/phone. Brain can auto-send if other gates allow.
- **linked**: guest_email matches a known reservation but we don't have a current session token. Brain reviews; operator approves; the next message gets a session token created and becomes identified.
- **pseudonymous**: OTA-masked email, display name, no reservation match. This is the standard pre-booking case. Brain always operator-reviews.
- **anonymous**: no usable identity signal. Brain handles defensively (likely escalation).

**Step B1: Add `IdentityResolution` to `CanonicalInboundMessage`**

Extend the dataclass in `app/services/messaging/inbound_normalizer.py`:

```python
@dataclass
class CanonicalInboundMessage:
    # ... existing fields ...
    identity: Optional[IdentityResolution] = None  # populated by transport adapter
```

Backwards compatibility: when `identity` is None, brain treats it as pseudonymous. Existing pre-booking tests don't break.

**Step B2: Build `IdentityResolver`**

New file: `app/services/messaging/identity_resolver.py`. Pure function that takes the parsed transport message and returns an `IdentityResolution`:

```python
async def resolve_identity(
    parsed: ParsedEmailMessage | SessionMessage,
    *,
    db: AsyncSession,
    tenant_id: UUID,
) -> IdentityResolution:
    # 1. If session_token present, look it up in concierge_guest_sessions.
    #    If active → identified.
    # 2. If guest_email present and matches a reservation_id in pms_bookings,
    #    populate identified fields. → identified or linked depending on
    #    whether a session exists yet.
    # 3. If OTA-masked email pattern (matches *.airbnb.com, vrbo.com etc),
    #    → pseudonymous.
    # 4. Else → anonymous.
```

**Step B3: Wire `IdentityResolver` into all transport entry points**

Three transports populate `CanonicalInboundMessage.identity` today:
- `gmail_inbox_poller._shadow_persist_canonical_message` builds the canonical and persists it
- `session_channel_adapter.run_session_channel_message` builds an inbound for session messages
- (Future) PMS-native and SMS-native transports

For each, add a call to `resolve_identity()` and set `.identity` on the canonical before handing off to brain.

**Step B4: Brain reads identity**

`ContextBuilderAgent` (now lazy) reads `message.identity` and:
- Populates `reservation_facts` from the identity payload (reservation_id, check_in, check_out come from PMS lookup keyed on reservation_id)
- Makes identity-dependent specialists eligible (e.g. `LateCheckoutAgent` requires identified state; for pseudonymous messages it doesn't even register as eligible)

`ResponsePolicyAgent` reads `message.identity.state` and the composed `GuestResponseDraft.confidence`:
- pseudonymous + any confidence → DRAFT_ONLY (operator review)
- identified + confidence ≥ autonomy_threshold + no escalation flags + no missing evidence → AUTO_SEND eligible
- identified + confidence below threshold → DRAFT_ONLY
- anonymous → ESCALATE

The autonomy threshold defaults to 0.85 and is configurable per tenant. **Default behavior for Lanier in Session B: autonomy_threshold = 1.0 (effectively never auto-send).** This ships the contract without changing operator-facing behavior. Lowering the threshold to enable real auto-send is a separate operator-facing rollout, not part of convergence.

**Step B5: Tests**

- `tests/unit/test_identity_resolver.py` — covers all four states across email and session inputs
- `tests/unit/test_brain_identity_eligibility.py` — confirms specialists only run when identity allows, and policy correctly chooses DRAFT_ONLY vs AUTO_SEND vs ESCALATE
- `tests/unit/test_pre_booking_identity.py` — confirms pre-booking flow with pseudonymous identity behaves identically to today (regression guard)

**Verification:**
- Pre-booking pseudonymous message → identity.state='pseudonymous', flows through brain unchanged from current behavior, ends as DRAFT_ONLY
- Identified session-token in-stay message → identity.state='identified', flows through brain, ends as DRAFT_ONLY (because Lanier's autonomy_threshold=1.0)
- Brain confidence ≥ 0.85 on an identified message with autonomy_threshold lowered to 0.85 → AUTO_SEND eligible (verified in test with custom threshold; not enabled in production)

**Estimated size:** 1 session, ~5-7 commits.

---

### Session C: Migrate `ai_concierge.get_ai_response`, wire proactive triggers

**Goal:** Remove the parallel concierge composer pipeline. Route session messages through brain. Wire `guest_journey.py` outbound through `handle_proactive_trigger`. Verify token isolation.

**Architectural shape:**

After Sessions A and B, the brain has:
- Fast-path stage (LLM bypass at high confidence)
- Lazy context stage (intent-gated fetches)
- Identity resolution (per-token state)
- Composer with multi-provider chain
- Grounding + reviewer
- Per-message audit via `AgentAuditRecord` keyed on the internal message UUID

Everything `ai_concierge.py` does is now either replicated in the brain (FAQ fast-path, escalation, lazy context, grounding) or available as an enrichment service the brain can consume (BD insight, market brain, nearby portfolio — these stay where they are and become context overlays brain reads).

**Step C1: Thin `get_ai_response` to a brain call**

Replace `ai_concierge.get_ai_response`'s body with:

```python
async def get_ai_response(
    message: str,
    property_context: dict,
    guest_name: str,
    property_name: str,
    operator_id: str = "op_beach_habitats",
    property_code: Optional[str] = None,
    session_token: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    tenant_id: Optional[str] = None,
) -> str:
    result = await run_session_channel_message(
        message_text=message,
        db_session=...,
        db_row=...,  # session row resolved from token
        session_tenant_id=tenant_id,
        token=session_token,
        channel='web_session',
        source_provider='concierge_runner',
        fallback_support_phone=property_context.get('support_phone'),
        fallback_lifecycle=MessagingLifecycle.IN_STAY,
    )
    return result.response_text
```

`run_session_channel_message` already exists and already routes through brain. It needs minor updates to use the lazy context stage and identity resolution from Sessions A/B, but the entry point is the same.

**Step C2: Delete the parallel composer surface**

Delete from `ai_concierge.py`:
- `_generate_response` (the legacy direct-LLM-call function with Groq primary + Claude fallback)
- `_apply_grounding_and_gap_policy` (now lives in brain pipeline)
- `_resolve_guest_session_pipeline` (its escalation/FAQ checks are now in `FastPathStage`)
- `_keyword_fallback` (offline safety net, replaced by brain's concatenation fallback)
- The `from app.services.concierge.concierge_intelligence import smart_generate` path

Delete `concierge_intelligence.py` if nothing else imports from it. Otherwise leave the `extract_*` signal extractors (location, weather, guest composition) as a utility module — they're not parallel composer, they're contextual enrichment that brain's lazy context stage can optionally consume.

**Step C3: Wire proactive triggers through brain**

Historical note: before the 2026-05-28 cleanup, `proactive/guest_journey.py` emitted proactive touches through the concierge outbound dispatcher. That file is now deleted; the canonical proactive runtime is `operator/stay_proactive_runtime.py`.

Wire them through `handle_proactive_trigger` instead:

```python
# Historical note: this sketch referred to the now-deleted proactive file.
# The live cutover point is the operator-owned proactive runtime.
intent = OutboundIntent(
    trigger=proactive_touch_to_trigger(touch_type, lifecycle=lifecycle),
    lifecycle=stay_phase_to_lifecycle(phase),
    session_token=token,
    tenant_id=tenant_id,
    property_code=property_code,
    payload={
        'touch_type': touch_type,
        'guest_name': guest_name,
        # ... touch-specific context
    },
)
draft = await get_messaging_brain_orchestrator().handle_proactive_trigger(intent)
# draft.response_text is what gets sent via the channel dispatcher
```

`proactive_trigger_adapter.py` already has `proactive_touch_to_trigger`, `stage_to_lifecycle`, `stay_phase_to_lifecycle`, and `choose_channel`. Use them.

**Step C4: Token isolation verification**

Before declaring convergence done, run a test that exercises the per-token model:

1. Create two active sessions for the same property: token_A and token_B
2. Send a maintenance message via token_A: "the AC is broken in the master"
3. Send a property-knowledge message via token_B: "what's the wifi?"
4. Assert:
   - token_A's audit row shows `MaintenanceAgent` ran with category=hvac
   - token_B's audit row shows `FastPathStage` hit FAQ with `confidence_source='faq_fast_path'`
   - Neither audit row references the other token's state
   - `MaintenanceAgent`'s module event for token_A doesn't fire on token_B
   - Knowledge gap recording is keyed off the correct token

This test is the load-bearing verification for the closure criterion "the token-based guest model works correctly."

**Step C5: Tests**

- `tests/unit/test_session_channel_brain_entry.py` — covers `get_ai_response` routes to brain, identity is resolved, fast-path hits work, lazy context loads correctly
- `tests/integration/test_per_token_isolation.py` — the multi-token test above
- `tests/unit/test_proactive_trigger_through_brain.py` — covers each touch_type going through `handle_proactive_trigger` and producing an audit row with `confidence_source='proactive_trigger'`
- Update existing concierge tests that mocked `_generate_response` to mock the brain entry instead

**Closure greps:**

```bash
# No parallel composer
rg -n "from app.services.concierge.concierge_intelligence import smart_generate" app/
rg -n "_generate_response|_apply_grounding_and_gap_policy" app/services/concierge/ai_concierge.py
# Both should return zero

# Proactive triggers route through brain
rg -n "handle_proactive_trigger" app/services/operator/stay_proactive_runtime.py app/services/operator/stay_action_agent.py app/services/messaging_brain/

# No direct LLM calls in ai_concierge.py
rg -n "groq|anthropic\\.com|api\\.openai\\.com|generativelanguage" app/services/concierge/ai_concierge.py
# Should return zero
```

**Estimated size:** 1 session, ~6-8 commits.

---

## Part 3: Rollback signals

Stop and revert if any of these happen during any session:

- Pre-booking row written with wrong `confidence_source` (regression of pre-booking closeout)
- Session message returns wrong text or stale guest name (token isolation broken)
- FAQ fast-path returns answers for the wrong property
- Maintenance event fires on wrong token
- Latency on in-stay messages increases by more than ~150ms p95 (we promised concierge-economy parity)
- Brain throws on identified messages that worked under concierge pipeline
- Operator dashboard shows duplicate rows or stops rendering session messages
- Proactive trigger fires twice (once via old path, once via brain) — wiring bug, fix immediately

Rollback is `git revert <commit>`. Don't stack commits on broken state.

---

## Part 4: Commit sequence summary

**Session A:** ~6-8 commits
- A1: confidence_source enum migration
- A2: FastPathStage with all three short-circuit paths
- A3: LazyContextStage replacing eager build
- A4: Feature flags wired
- A5: Tests
- Verification commit if any small fixes shake out

**Session B:** ~5-7 commits
- B1: IdentityResolution dataclass on CanonicalInboundMessage
- B2: IdentityResolver implementation
- B3: Wire into gmail_inbox_poller, session_channel_adapter
- B4: Brain reads identity, ResponsePolicyAgent gates on it
- B5: Tests
- Verification

**Session C:** ~6-8 commits
- C1: get_ai_response → brain
- C2: Delete parallel composer surface
- C3: Proactive triggers through handle_proactive_trigger
- C4: Token isolation test
- C5: Test updates
- Closure greps
- Tracking entry

**Total:** roughly 17-23 commits across 3 sessions.

---

## Part 5: Tracking entry (Step 13 equivalent)

After Session C lands:

> Lifecycle convergence complete as of [commit hash]. Brain is sole decision plane for every inbound guest message across pre-booking, pre-arrival, in-stay, and post-stay, and for every proactive outbound message. `ai_concierge.get_ai_response` is now a thin entry into `run_session_channel_message` which routes through `GuestMessageBrainOrchestrator`. FastPathStage handles deterministic short-circuits (FAQ ≥ 0.90, gate code intercept, escalation routing) before specialists run. LazyContextStage replaces eager context fetching with intent-gated lazy fetches matching the concierge's cost profile. `IdentityResolution` on `CanonicalInboundMessage` distinguishes identified / linked / pseudonymous / anonymous states and gates specialist eligibility plus autonomy. `confidence_source` enum extended: `faq_fast_path`, `escalation_routed`, `gate_code_intercept`, `session_composer`, `proactive_trigger`. Per-token isolation verified via multi-token integration test. Proactive outbound now routes through `app/services/operator/stay_proactive_runtime.py` and the stay workflow/action queue before entering `handle_proactive_trigger`, producing the same audit trail as inbound. No parallel LLM composers remain. Concierge MCP tools that wrap deterministic logic stay as-is (they're the underlying implementations the brain stages call); the composer-bypass parallel pipeline is gone. Autonomy gate ships with `autonomy_threshold=1.0` for Lanier — operators still review every message in production. Lowering the threshold to enable real auto-send is a separate operator-facing rollout decision, not part of convergence.

---

## Part 6: One reminder

Token isolation is the easiest thing to break and the hardest to detect after the fact. Every brain decision, every audit row, every knowledge gap log, every module event must be keyed off the session token's identity, never the property. The multi-token integration test in C4 is the gate.

The two capability ports (fast-path + lazy context) are the load-bearing pieces. If those don't match concierge's cost/latency profile, convergence is a regression, not a win. Verify before declaring Session A done.

The proactive wiring is small but easy to double-fire. Confirm the old emission path is fully removed when the brain path is added, not running in parallel.

Hand to Claude Code. Execute sequentially. Don't merge sessions.
