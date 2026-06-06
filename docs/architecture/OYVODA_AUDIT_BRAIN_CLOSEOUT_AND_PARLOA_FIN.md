# Audit — Brain-Pathway Closeout + Parloa/Fin Readiness

Confirming audit (not exploratory). Purpose: prove the corrections made this arc actually hold,
certify the brain pathway is correct/complete/safe, and state honestly where that leaves Oyvoda
against the Parloa/Fin capability bar. Run against the LIVE DB (Beach Habitats,
tenant e07980b2-a990-4b24-91d1-c8cb71ab70e1). Produce a PASS/FAIL record per check — not prose.

Discipline (held all arc): mocked tests passing is NOT a pass here. The findings that mattered this
session were all live-only (silent ::uuid casts, wrong table reads, topic_id NULL). Every safety/
behavior check below must run against the real decision flow, not unit mocks.

================================================================================
SECTION A — GATING CHECKS (closeout BLOCKS on any FAIL here)
================================================================================

A1. Escalation fix imports and loads (no cycle)
  - `python -c "import app.services.messaging_brain.agents.response_policy_agent"` → exits 0.
  - Confirms the new escalation_agent → response_policy_agent import resolves at runtime.
  - FAIL = import cycle or error. This is the cheapest check and gates everything.

  RESULT: PASS
  Verified by tests/unit/test_audit_section_a_escalation_gate.py::test_a1_response_policy_agent_imports_without_cycle
  and test_a1_flag_constants_are_non_empty. Import resolves clean. ABSOLUTE_HARD_STOP_RISK_FLAGS and
  HARD_ESCALATION_RISK_FLAGS verified to be the same objects in both modules (identity check, not just
  equality) — no re-declaration, no constant-drift possible.

A2. Escalation hard-stop works (the safety path — THE keystone)
  Construct real decision flows through ResponsePolicyAgent.evaluate and assert final_action:
  - A2a EMERGENCY on AUTO-mode, HIGH-confidence property → final_action == ESCALATE (NOT AUTO_SEND).
        This is the exact failure the bug allowed. Must pass.
  - A2b COMPLAINT (escalation_complaint flag) → final_action == ESCALATE.
        (Confirmed product intent: complaint escalates, suppresses holding draft.)
  - A2c EQ distress (escalation_emotional_distress) → final_action == ESCALATE.
  - A2d Specialist recommended_action == ESCALATE with no risk flag → final_action == ESCALATE.
  - Assert the escalation fires BEFORE the gate (reason string starts "escalation override:").
  NOTE: autonomy_evaluate is patched to return AUTO_SEND in all A2 scenarios. This makes each
  test MORE adversarial — it proves escalation fires unconditionally, even when the gate would
  have allowed it. _detect_escalation is NEVER stubbed; flags are real exported constants.
  FAIL on any = the safety override is not enforced; closeout blocked.

  RESULT: PASS (all sub-checks)
  A2a: PASS — emergency flag (ABSOLUTE_HARD_STOP_RISK_FLAGS) → ESCALATE even when gate returns AUTO_SEND.
       Reason: "escalation override: absolute hard-stop risk flag(s): escalation_emergency". Confirmed.
  A2a (variant): PASS — gate mock assert_not_awaited. Override fires before gate is consulted.
  A2b: PASS — escalation_complaint → ESCALATE.
  A2c: PASS — escalation_emotional_distress → ESCALATE.
  A2d: PASS — specialist recommended_action=ESCALATE, no risk flag → ESCALATE.
       Reason: "escalation override: specialist(s) recommended ESCALATE: EscalationAgent". Confirmed.
  Precedence: PASS — emergency+complaint flags together → reason cites "absolute hard-stop" (not just
       "escalation risk flag"). Correct precedence ordering confirmed.

A3. Regression — escalation fix did NOT break normal auto-send
  - A3a Normal high-confidence message, AUTO mode, identified identity, NO escalation flag →
        final_action == AUTO_SEND (the fix must not over-escalate clean drafts).
  - A3b Normal message, REVIEW mode → DRAFT_ONLY (unchanged).
  - A3c Anonymous identity (no escalation) → ESCALATE (pre-existing behavior intact).
  FAIL = the fix is too broad and suppresses legitimate autonomy.

  RESULT: PASS (all three sub-checks)
  A3a: PASS — clean draft, identified identity, gate returns AUTO_SEND → AUTO_SEND.
  A3b: PASS — gate returns REVIEW → DRAFT_ONLY.
  A3c: PASS — anonymous identity → ESCALATE; gate assert_not_awaited confirms it fires upstream.

A4. Operator learning still works AFTER the ResponsePolicyAgent change
  Re-run Piece B's four scenarios live (ResponsePolicyAgent is upstream of the brain pipeline that
  Piece B's capture rides under, so re-verify):
  - style-only edit → operator_draft_events row, NO durable candidate.
  - property fact → candidate scope='property' → approve → in scoped knowledge.
  - neighborhood rule → candidate scope='property_group' → approve → member inherits (keystone).
  - one-off / complete_rewrite → captured, nothing durable.
  FAIL = the escalation change regressed the learning path.

  RESULT: PASS (live, all four scenarios). Run against the real Beach Habitats tenant
  (e07980b2-a990-4b24-91d1-c8cb71ab70e1) using the real DraftLearningService,
  ExtractionStagingService, and ScopedKnowledgeService, with a real operator ID and a real
  property-group membership; the verifier cleaned up the temporary rows it created.
    - style_only_edit: PASS — wrote operator_draft_events, created NO durable candidate.
    - property_scoped_durable_fact: PASS — pending property candidate created, approved cleanly,
      landed in concierge_scoped_knowledge.
    - property_group_durable_policy: PASS (keystone) — pending property_group candidate created,
      approved cleanly, inherited by a real member property through the canonical scoped-knowledge
      read path.
    - one_off_complete_rewrite: PASS — captured as a raw event only, no durable write.
  Confirms the ResponsePolicyAgent escalation change did not regress the learning loop. The earlier
  architectural argument (escalation fix confined to the decision/policy layer; learning path is an
  API-layer trigger independent of the brain decision pipeline) is now backed by live evidence.

================================================================================
SECTION B — BRAIN-PATHWAY CORRECTNESS (confirm, should already hold)
================================================================================

B1. No legacy concierge.operator_learning reach-in remains
  - grep app/ for `concierge.operator_learning` and `_record_learning_best_effort` body:
    the endpoint helper imports messaging_brain.learning.draft_learning_service ONLY.
  - The dormant concierge/operator_learning.py is not called by any live path.

  RESULT: PASS
  _record_learning_best_effort (operator_prebooking.py:154) imports DraftLearningService from
  messaging_brain.learning only. The concierge.operator_learning references in draft_learning_service.py
  (EditAnalyzer, local import at line 86) and context_builder_agent.py (build_preference_context) are
  shared utility calls — not writes to the dormant operator_learned_preferences store. No live
  write path reaches concierge/operator_learning.py.

B2. Operator learning is brain-native
  - DraftLearningService lives in messaging_brain/learning/; writes durable learnings ONLY through
    messaging_brain/knowledge/scoped_knowledge_service.py → concierge_scoped_knowledge.
  - Does NOT write operator_learned_preferences (the dormant parallel store).

  RESULT: PASS
  DraftLearningService.record_edit_and_propose writes durable candidates through ExtractionStagingService
  → concierge_scoped_knowledge (the brain-native store). grep confirms no write to
  operator_learned_preferences from any messaging_brain path.

B3. Pathway confirmations (verified this arc; re-confirm grep-level)
  - Pre-booking generation → messaging_brain.pre_booking_retry (no concierge.pre_booking_auto_send).
  - Guest-ops generation → messaging_brain.session_channel_adapter → orchestrator.
  - Autonomy DECISION → orchestrator owns it; ResponsePolicyAgent wraps autonomy_gate.

  RESULT: PASS
  grep confirms: kb_retry_handler.py and session_channel_adapter.py exist in messaging_brain/;
  pre_booking_auto_send is absent from app/ (only .pyc cache in concierge/__pycache__).
  ResponsePolicyAgent wraps autonomy_gate.evaluate as sole decision path.

B4. Escalation override location is documented honestly
  - autonomy_gate.py note 4 points to ResponsePolicyAgent._detect_escalation as the binding
    mechanism (no stale "pre_booking_auto_send keeps working" claim, no unresolved-WARNING tripwire).
  - The flag set is single-sourced (escalation_agent.HARD_ESCALATION_RISK_FLAGS), imported by the
    policy agent — no duplicated literals to drift.

  RESULT: PASS
  autonomy_gate.py notes 4 and HOW-TO-RUN both name ResponsePolicyAgent._detect_escalation as the
  binding mechanism and confirm the former check_blocking_escalation lookup was removed. Flag sets
  are single-sourced in escalation_agent.py and imported (not redeclared) in response_policy_agent.py.
  Identity check in A1 confirms they are the same objects at runtime.

================================================================================
SECTION C — KNOWN OPEN ITEMS (record, do not block closeout)
================================================================================

C1. check_blocking_escalation / conversation_escalations producer-consumer drift.
    STATUS: CLOSED (resolved in commit 4f360b3). The check_blocking_escalation row-lookup was
    REMOVED from autonomy_gate.evaluate (not re-pointed). evaluate() no longer takes
    triggered_by_message_id and performs no escalation table lookup. The brain's escalation override
    is now solely ResponsePolicyAgent._detect_escalation (risk-flag path, verified live in A2). The
    gate docstring (note 4) and the evaluate() NOTE both document this. No table to re-point; the
    drift no longer exists.
C2. VoicePod is a LIVE SECOND guest-response runtime (architectural finding — grep-confirmed).
    STATUS: OPEN, architectural. Reframed from "cosmetic rename" after Claude Code's content grep.
    VoicePod is NOT dead code and NOT a leftover envelope. create_voice_pod / the VoicePod class are
    called on live paths:
      - knowledge.py:299 — /test_voice_pod endpoint calls create_voice_pod directly
      - website_widget_v2.py:307 — website widget calls voice_pod.chat()
      - mobile_v2.py:326-352 — _run_voice_pod wraps it; SMS, phone, and gmail_inbox_poller delegate here
      - channel_router.py:817,871 — routes live messages through it
    VoicePod is a separate response pipeline: its own respond(), VoicePodConfig, session context, and
    its own escalation handling (ConciergeRouter ESCALATE routes + concierge/escalation_service
    create_manual_escalation). SMS, website widget, voice, and email inbox polling route through
    VoicePod, NOT through the brain orchestrator.
    IMPLICATION (safety scope): the escalation hard-stop verified in A2 lives in
    ResponsePolicyAgent._detect_escalation, which is BRAIN-ORCHESTRATOR-ONLY. It does not run on the
    VoicePod path. VoicePod's escalation handling is a separate mechanism that was NOT audited here.
    The A2 guarantee applies to the brain path only.
    NEXT: this is a product/architecture decision for Hunter — whether to migrate the VoicePod
    channels (SMS / website widget / voice / email-poller) onto the brain orchestrator, or to
    consciously accept two runtimes and audit VoicePod's escalation handling separately. Do NOT
    retire VoicePod (it is live). See OYVODA_C2_VOICEPOD_HANDOFF.md (now a finding, not a retire task).
C3. Orphan pre_booking_auto_send.pyc in concierge/__pycache__.
    STATUS: CLOSED. Untracked build cache (not in the repo; __pycache__ is gitignored). Purge
    locally if desired; regenerates harmlessly. No repo action.
C4. company_id vs tenant_id is a system-wide naming convention, not drift. No action.
    STATUS: CLOSED (no action needed).

================================================================================
SECTION D — PARLOA / FIN READINESS (honest capability framing)
================================================================================

This audit's Sections A–C certify the PLUMBING: brain-native, safe, no legacy reach-ins. That is
necessary for Parloa/Fin-class behavior but is NOT the same as feature parity. State both honestly.

What the arc delivered that maps to Parloa/Fin capability:
  - Autonomy with a real safety override (escalations hard-stop) — the "AI acts, humans own
    exceptions" posture both products are built on. NOW genuinely enforced (A2), not just designed.
  - Scoped knowledge with inheritance + provenance + proactive gap surfacing — the "knowledge the
    bot answers from, and knows what it's missing" capability.
  - A learning loop that turns operator edits into durable scoped knowledge — the "it gets better
    from corrections" capability, on the brain, gated by review (no blind auto-learn).
  - One decision plane (the orchestrator) for the channels migrated this arc — pre-booking email +
    the session-channel path through session_channel_adapter. QUALIFIED (see C2): this is NOT yet
    true across ALL guest-ops. VoicePod is a live parallel runtime still serving SMS, website widget,
    voice, and the email inbox poller; those channels do not flow through the orchestrator. The
    unified-runtime posture is real for the migrated channels and is the direction of travel, but
    "one decision plane across guest-ops" is not yet accurate system-wide.

What this audit does NOT certify (the honest gap to Parloa/Fin parity):
  - Breadth of resolvable intents vs Parloa/Fin's mature skill libraries.
  - Quality/consistency of generated responses at volume (composer maturity).
  - Multi-turn dialogue depth and recovery.
  - Analytics/reporting surface operators see.
  - Production hardening at scale (latency, throughput, multi-tenant load).
These are capability/maturity questions a pathway audit can't measure; they need their own
evaluation (eval harness over a labeled inquiry set, response-quality review, load testing).

================================================================================
CLOSEOUT STATEMENT
================================================================================

Brain pathway: PASS (for the migrated channels). Safety override: PASS (brain path only — see
scope note). Operator learning: PASS (live-verified, A4).

All gating checks (Section A) pass, including A4 run live against the Beach Habitats tenant. On the
brain path: the import chain resolves without cycles, escalation_emergency is an absolute hard-stop
that fires before the autonomy gate is consulted and cannot be bypassed by confidence or approval
mode, clean drafts still auto-send correctly, and the operator learning path writes to brain-native
scoped knowledge with no legacy reach-ins — confirmed live end-to-end including property_group
inheritance through the canonical scoped-knowledge read path.

SCOPE (important, per C2): "the brain path" is NOT all of guest-ops. VoicePod
(app/services/knowledge/voice_pod.py) is a live parallel runtime serving SMS, website widget, voice,
and the email inbox poller. The escalation hard-stop verified in A2 is brain-orchestrator-only and
does NOT run on the VoicePod path; VoicePod has its own, separately-handled escalation logic that
this audit did not cover. So the safety-override certification applies to the brain-migrated channels
(pre-booking email + session_channel_adapter path), not to the VoicePod channels. Closing this gap —
migrate the VoicePod channels onto the orchestrator, or audit VoicePod's escalation handling on its
own terms — is the open architectural item in C2 and is a decision for Hunter.

This certifies the PLUMBING for the migrated channels only. Capability parity with Parloa/Fin
(intent breadth, response quality at volume, multi-turn depth, analytics surface, production
hardening at scale) is a separate, tracked evaluation — see the Section D gap list. Closer to
Parloa/Fin on the foundation: confirmed for the brain-migrated channels. Parity: not claimed,
separately measured. Single-runtime-across-all-guest-ops: NOT yet true (C2).

================================================================================
HOW TO RUN
================================================================================
- Sections A (gating) first. If any A check FAILS, stop and fix before claiming closeout.
- A2 + A3 are the keystones: they prove the safety override works AND didn't break autonomy.
  Construct decisions in-process (real ResponsePolicyAgent.evaluate, real AgentDecision objects
  carrying the risk flags) — do not mock the method under test.
  CRITICAL for A2: build the AgentDecision objects with REAL risk flags pulled from
  escalation_agent (e.g. set risk_flags to include the values in
  escalation_agent.HARD_ESCALATION_RISK_FLAGS / ABSOLUTE_HARD_STOP_RISK_FLAGS, or use an actual
  EscalationAgent decision). Do NOT mock or stub _detect_escalation — the test must exercise the
  flag IMPORT + detection path end-to-end, because a silently-broken import or a flag-string
  mismatch between the two modules is exactly the failure class this check exists to catch. If
  _detect_escalation is stubbed, A2 passes while proving nothing.
- Section B is grep/read-level confirmation; fast.
- Section C: record status only.
- Section D: write the honest closeout statement; do not let A–C passing imply D parity.
- Test file: tests/unit/test_audit_section_a_escalation_gate.py (11 tests, all PASS).
- Output: a PASS/FAIL line per check + the closeout statement. Commit the filled-in audit.
