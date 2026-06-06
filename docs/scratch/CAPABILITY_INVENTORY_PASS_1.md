# Capability Inventory — Pass 1

**Date:** 2026-05-28
**Schema:** `docs/scratch/CAPABILITY_INVENTORY_SCHEMA.md` (read first if unfamiliar)
**Domains covered this pass:** `concierge` (only as residue/origin context for proactive), `operator` (proactive canonical path), `messaging` (compliance + retired modules + brain composition asymmetries — additive facts only, defers to tier map for architecture), `cross-system` (substantive gaps), `frontend` (dashboard-v2 coupling status)
**Domains explicitly NOT covered this pass:** `workers`, `mcp`, `vault`, `onboarding`, the rest of `operator/` and `concierge/` outside the rows below, `integrations` (Tier 1) beyond LLM-primary intake, `agents` (Tier 4 cross-cutting). See "Not yet inventoried" section.

---

## How to read this pass

Each row is a capability with a structured status. The schema doc explains the row shape. The short version: `bucket` says what the thing IS; `action_type` says what to do next; `frontend_status` says how `dashboard-v2` currently relates to it; `source_of_truth` is a file:line citation; `defers_to` cites the authoritative architectural doc when one exists; `last_verified` is the date of the read that backs the row; `upstream_origin` records where the logic originally came from (without legitimizing it as a parallel implementation); `cleanup_residue` enumerates legacy code still on disk for the same capability.

**Hard rule per the schema:** one canonical path per capability. Old code covering the same behavior is residue (tracked on the canonical row) or formally retired (its own `retired/superseded` row with citation). No "secondary but valid" rows exist in this inventory.

**Provenance note:** Rows in this pass are marked by source: `(fresh)` for a direct read at the moment of writing, `(session)` for reads done earlier in the 2026-05-28 session that produced this document, `(codex)` for facts inherited from the user-supplied discovery pass. Codex-trace rows that lack pinned file:lines are NOT in the canonical row set this pass — they are recorded in the "Unverified leads" appendix at the bottom, awaiting direct read on a future pass.

---

## Domain: `operator` (proactive canonical path)

### Stay-workflow proactive eligibility evaluation
- **bucket:** `live-on-canonical-path`
- **action_type:** `surface`
- **frontend_status:** `partially-consumed`
- **source_of_truth:** `app/services/operator/stay_proactive_service.py:28`
- **defers_to:** —
- **last_verified:** 2026-05-28 (session)
- **upstream_origin:** Lead-time and provider-specific scheduling concepts originated in the now-retired `app/services/concierge/proactive/guest_journey.py`; reusable provider/activity logic has been re-homed into `app/services/operator/stay_journey_service.py`.
- **cleanup_residue:** —
- **notes:** Canonical owner of "when does the next proactive touch become eligible." Frontend consumes via `workflow.proactive.touch_type` / `workflow.proactive.message` / `workflow.proactive.days_until_checkin` on the session detail payload. The `eligible` boolean drives the "Proactive due" row indicator (shipped commit 8038dca).

### Stay action queue for proactive touches and reactive sends
- **bucket:** `live-on-canonical-path`
- **action_type:** `surface`
- **frontend_status:** `consumed`
- **source_of_truth:** `app/services/operator/stay_action_agent.py:296` (proactive_outreach queueing); `:598` (reactive guest-send via SMS); `:701` (ops_review classification)
- **defers_to:** —
- **last_verified:** 2026-05-28 (session)
- **upstream_origin:** —
- **cleanup_residue:** —
- **notes:** Canonical executor for proactive touches. Frontend consumes via Actions block in `SessionExpansion.tsx`. The channel-specific quirk (reactive guest-send delivers via SMS, not email) is intentional behavior of this canonical executor today, not residue — but it is the asymmetry the in-stay draft parity workstream is designed to address. The asymmetry itself is captured as its own row in the messaging domain (in-stay reactive composition).

### Basic proactive message worker
- **bucket:** `retired/superseded`
- **action_type:** `build` (execute the retirement — verify canonical parity, then delete)
- **frontend_status:** `n/a`
- **source_of_truth:** `app/main.py:260`
- **defers_to:** —
- **last_verified:** 2026-05-28 (session)
- **upstream_origin:** Predates the stay-workflow canonical path. Its behavior is now subsumed by `stay_proactive_service` + `stay_action_agent` + brain composition.
- **cleanup_residue:** This file IS the residue. It currently produces the `welcomeSent` / `checkinReminderSent` booleans the frontend reads. **Migration problem:** until the canonical path proves parity on these milestone touches, removing this worker would leave a gap.
- **notes:** Architectural direction (stay-workflow + brain canonical) explicitly supersedes this. Not yet deleted because canonical-path milestone-touch parity has not been verified against real Lanier traffic. Action is `build` because executing the retirement requires real work (parity verification, deletion); it's neither passive `leave alone` nor a green-field `surface`.

---

## Domain: `messaging`

Per the schema's `defers_to` rule, every row in this domain cites the tier map. The inventory carries only additive facts (frontend coupling, surfacing status, retirement, residue). For architectural truth on these capabilities, read `docs/architecture/MESSAGING_TIER_MAP.md` directly.

### Brain composition for proactive outreach
- **bucket:** `live-on-canonical-path`
- **action_type:** `surface`
- **frontend_status:** `partially-consumed`
- **source_of_truth:** `app/services/messaging_brain/agents/proactive_outreach_agent.py:1`; entry point `app/services/messaging_brain/proactive_trigger_adapter.py:220`
- **defers_to:** `docs/architecture/MESSAGING_TIER_MAP.md` (Tier 3 — Decision Plane)
- **last_verified:** 2026-05-28 (session)
- **upstream_origin:** —
- **cleanup_residue:** —
- **notes:** Canonical composer for proactive outbound. Frontend shows the composed text in queued actions but does not yet render a forward schedule of upcoming touches. Forward-plan UI is gated on a `scheduledTouches[]` field that does not yet exist (see frontend-domain row).

### LLM-primary intake — email parser router
- **bucket:** `live-on-canonical-path`
- **action_type:** `leave alone`
- **frontend_status:** `n/a`
- **source_of_truth:** `app/services/integrations/email_parser_router.py:490` (LLM-first); `:507` (deterministic fallback); `:476` (structured reservation-event bypass)
- **defers_to:** `docs/architecture/MESSAGING_TIER_MAP.md` (Tier 1 — Inbound Transport + Parsing)
- **last_verified:** 2026-05-28 (session; user-confirmed via test verification)
- **upstream_origin:** Earlier deterministic-first parsing; consolidated to LLM-primary this session.
- **cleanup_residue:** —
- **notes:** Tests assert the new behavior in `tests/unit/test_email_parser_router_routing.py` and `test_brain_intake_primary.py`. Cascade into composition resolved the generic-reply symptom previously visible in Pre-booking drafts.

### LLM-primary intake — brain orchestrator
- **bucket:** `live-on-canonical-path`
- **action_type:** `leave alone`
- **frontend_status:** `n/a`
- **source_of_truth:** `app/services/messaging_brain/orchestrator.py:511`
- **defers_to:** `docs/architecture/MESSAGING_TIER_MAP.md` (Tier 3 — Decision Plane)
- **last_verified:** 2026-05-28 (session; user-confirmed via test verification)
- **upstream_origin:** Earlier deterministic-keyword classification.
- **cleanup_residue:** —
- **notes:** Brain intake labels primary path `llm_primary`; deterministic keyword fallback only fires if the LLM chain falls through.

### KB gap recording at orchestrator level
- **bucket:** `live-on-canonical-path`
- **action_type:** `surface`
- **frontend_status:** `partially-consumed`
- **source_of_truth:** `app/services/messaging_brain/orchestrator.py:1048` (canonical KB gap emission); `:1101` (stage-tagged scheduling — in_stay gaps possible)
- **defers_to:** `docs/architecture/MESSAGING_TIER_MAP.md` (Tier 3)
- **last_verified:** 2026-05-28 (session)
- **upstream_origin:** Earlier gap-recording lived in `kb_gap_manager` (now retired) and partially in `app/services/concierge/knowledge_gap_recorder.py` (status to be verified by direct read on next pass — see Unverified leads).
- **cleanup_residue:** Possibly `app/services/concierge/knowledge_gap_recorder.py` — needs direct read to determine whether it is still called for this behavior or already migrated. Recorded in Unverified leads.
- **notes:** In-stay-tagged KB gaps ARE produced by the orchestrator. Pre-booking surfaces them in its review queue with explicit draft/gap semantics; Today does NOT surface in_stay-tagged gaps inline. This is the asymmetry the in-stay draft parity workstream will address.

### Pre-booking brain orchestrator (forced-review path)
- **bucket:** `live-on-canonical-path`
- **action_type:** `leave alone`
- **frontend_status:** `consumed`
- **source_of_truth:** `app/services/integrations/email_dispatch.py:954`, `:977`, `:981` (`force_approval_mode="required"`); review queue surfaced via `app/api/v1/endpoints/operator_prebooking.py:1119`
- **defers_to:** `docs/architecture/MESSAGING_TIER_MAP.md` (Tier 3)
- **last_verified:** 2026-05-28 (session brain-wiring trace)
- **upstream_origin:** —
- **cleanup_residue:** —
- **notes:** The reference implementation of "brain draft → review queue → approve/edit/send." Forces operator review on all pre-booking inquiries via dedicated persistence (`pre_booking_inquiries`). The in-stay parity workstream is shaped to bring this loop to in-stay sessions.

### In-stay reactive brain composition + send-loop asymmetry
- **bucket:** `live-on-canonical-path` (composition); the missing parity surface is its own row in cross-system
- **action_type:** `surface`
- **frontend_status:** `partially-consumed`
- **source_of_truth:** `app/services/integrations/email_dispatch.py:1085` (in-stay routing); `:1151` (AUTO_SEND email path); `:1177`, `:1183` (ops_review action queueing); `app/services/messaging_brain/session_channel_adapter.py:117` (`run_session_channel_message`); brain orchestrator wraps `GuestMessageBrainOrchestrator.handle_inbound_message(...)`. Today UI treatment at `app/static/dashboard-v2/src/routes/Today/actionLabels.ts:59`.
- **defers_to:** `docs/architecture/MESSAGING_TIER_MAP.md` (Tier 3)
- **last_verified:** 2026-05-28 (session brain-wiring trace)
- **upstream_origin:** —
- **cleanup_residue:** —
- **notes:** Brain composes in-stay reactive replies via `GuestMessageBrainOrchestrator`. Held drafts become `ops_review` actions with draft text in `payload.message_text`. Today renders the action but does NOT treat it as a guest-send affordance; the reactive guest-send executor delivers via SMS, not email (see operator-domain stay_action_agent row). So a held in-stay *email* draft has no first-class send affordance. The composition is canonical; the parity surface is a separate gap (cross-system row below).

### Phone in-stay reactive brain composition
- **bucket:** `live-on-canonical-path`
- **action_type:** `surface`
- **frontend_status:** `partially-consumed`
- **source_of_truth:** `app/api/v1/endpoints/phone.py:402`
- **defers_to:** `docs/architecture/MESSAGING_TIER_MAP.md` (Tier 3)
- **last_verified:** 2026-05-28 (codex)
- **upstream_origin:** —
- **cleanup_residue:** —
- **notes:** Phone uses the same session-channel brain path as in-stay email. Inherits the same send-loop asymmetry concerns where applicable.

### Platform compliance rule evaluation (ADA, service animals, ESA, etc.)
- **bucket:** `live-on-canonical-path`
- **action_type:** `surface`
- **frontend_status:** `no-endpoint-yet`
- **source_of_truth:** `app/services/messaging_brain/policy/platform_compliance.py:1`; ADA/service-animal/ESA logic surfaced via `app/services/messaging_brain/agents/context_builder_agent.py:1067`; consumed by `app/services/messaging_brain/agents/house_rules_agent.py:225`; missing-knowledge hold behavior at `platform_compliance.py:109`; final policy gate at `app/services/messaging_brain/agents/response_policy_agent.py:1`
- **defers_to:** `docs/architecture/MESSAGING_TIER_MAP.md` (Tier 3 — Decision Plane)
- **last_verified:** 2026-05-28 (codex)
- **upstream_origin:** —
- **cleanup_residue:** —
- **notes:** Substrate for super-admin universal compliance rules. The mechanism exists; the *content* (which rules are populated, with what immutability discipline) is the open question. Frontend does not currently surface "universal/immutable rule" vs "operator-editable knowledge" — that's the three-category UI the conversation called for. No v2 API endpoint exposes the rules layer yet.

### Tenant scope-switching for super-admin
- **bucket:** `live-on-canonical-path`
- **action_type:** `surface`
- **frontend_status:** `no-endpoint-yet`
- **source_of_truth:** `app/api/v1/endpoints/operator_app.py:764`; audit doc `docs/architecture/TENANT_ISOLATION_AUDIT.md:106`
- **defers_to:** `docs/architecture/TENANT_ISOLATION_AUDIT.md`
- **last_verified:** 2026-05-28 (codex)
- **upstream_origin:** —
- **cleanup_residue:** —
- **notes:** No dashboard-v2 surface exposes super-admin scope-switching yet. This is the access primitive the universal-compliance-rules UI would build on top of.

### `kb_gap_manager` (retired)
- **bucket:** `retired/superseded`
- **action_type:** `leave alone`
- **frontend_status:** `n/a`
- **source_of_truth:** `docs/architecture/LEGACY_RETIREMENT_PLAN.md:169`, `:171`; `docs/architecture/PHASE_4_5_G_BRIEF.md:1`; `docs/architecture/BRAIN_ONLY_RETIREMENT_AUDIT_2026-05-23.md:71`
- **defers_to:** `docs/architecture/LEGACY_RETIREMENT_PLAN.md`
- **last_verified:** 2026-05-28 (codex)
- **upstream_origin:** —
- **cleanup_residue:** —
- **notes:** Explicitly retired. The canonical KB-gap recording is the orchestrator path (see row above). Do not light up `kb_gap_manager`.

### `messaging_brain/grounding/hallucination_guard.py` (live grounding utility, composer integration pending)
- **bucket:** `complete-but-unwired`
- **action_type:** `build` (wire into composer)
- **frontend_status:** `n/a`
- **source_of_truth:** `app/services/messaging_brain/grounding/hallucination_guard.py:1`; composer-integration deferral noted at `app/services/messaging_brain/agents/llm_composer_agent.py:79`
- **defers_to:** `docs/architecture/MESSAGING_TIER_MAP.md` (Tier 3 — grounding/)
- **last_verified:** 2026-05-28 (codex)
- **upstream_origin:** An older `concierge.hallucination_guard` was the precursor; superseded by relocation to messaging_brain/grounding. The older path's retirement-doc citation is unpinned and recorded in Unverified leads.
- **cleanup_residue:** —
- **notes:** File is built; composer integration is explicitly future work per the composer agent's own comment. This is the kind of capability the "decline to draft when uncertain" architectural pattern depends on. Direct read recommended on next pass to confirm composer-integration status hasn't moved.

---

## Domain: `frontend` (dashboard-v2)

### v2 router — mounted surfaces
- **bucket:** `live-on-canonical-path`
- **action_type:** `surface`
- **frontend_status:** `consumed`
- **source_of_truth:** `app/static/dashboard-v2/src/app/Router.tsx:57`
- **defers_to:** —
- **last_verified:** 2026-05-28 (session)
- **upstream_origin:** —
- **cleanup_residue:** —
- **notes:** Seven routes mounted: prebooking, today, properties, knowledge, vendors, settings, components. Action is `surface` because two of the seven (Knowledge, Settings) are still explicit placeholders — the router as a capability has unfinished surfacing work. The placeholder status of those two routes is what the action points at; the other five are live and don't need work, but a capability with any pending surfacing earns the `surface` action overall. Components is a chrome-less dev-only design gallery, deliberately excluded from nav.

### v2 API client — exposed-but-unconsumed endpoints
- **bucket:** `complete-but-unwired`
- **action_type:** `surface`
- **frontend_status:** `exposed-but-unconsumed`
- **source_of_truth:** `app/static/dashboard-v2/src/api/index.js:50` (general structure); specific endpoints at `:157` (gateway credentials), `:261` (escalations), `:324` (notifications), `:329` (admin/LLM usage)
- **defers_to:** —
- **last_verified:** 2026-05-28 (codex)
- **upstream_origin:** —
- **cleanup_residue:** —
- **notes:** v2 API client exposes admin/LLM usage, escalations, notifications, gateway credentials, and full settings tabs with no routed UI. Knowledge UI is similarly exposed but its route is a placeholder. These are the most concrete "capability exists, UI doesn't" rows.

### Today four-stage lifecycle taxonomy
- **bucket:** `live-on-canonical-path`
- **action_type:** `surface` (further work — stage-aware proactive expansion shipped per commit 2d17a86, but pre-arrival lazy-load is a tracked debt)
- **frontend_status:** `consumed`
- **source_of_truth:** `app/static/dashboard-v2/src/shared/lifecycle/windows.ts:118` (classifier split); `app/static/dashboard-v2/src/routes/Today/lifecycleBoundaries.test.ts:1` (boundary tests)
- **defers_to:** `docs/scratch/TODAY_FOUR_STAGE_RESHAPE_SPEC.md`
- **last_verified:** 2026-05-28 (session)
- **upstream_origin:** —
- **cleanup_residue:** —
- **notes:** Pre-arrival / arriving / in-stay / post-stay tabs live. Pre-arrival is lazy-load deferred per v1 simplicity decision (tracked in `docs/TODAY_SCALABILITY_WORK_ITEM.md`).

### `classifyForArrivals` (deliberately-throwing stub)
- **bucket:** `scaffolded-and-pending`
- **action_type:** `leave alone`
- **frontend_status:** `n/a`
- **source_of_truth:** `app/static/dashboard-v2/src/shared/lifecycle/windows.ts:174`
- **defers_to:** `docs/scratch/TODAY_FOUR_STAGE_RESHAPE_SPEC.md`
- **last_verified:** 2026-05-28 (session)
- **upstream_origin:** —
- **cleanup_residue:** —
- **notes:** Was reserved for a separate Arrivals surface; that surface was NOT built per the four-stage reshape decision (pre-arrival lives inside Today instead). The throw remains so no one half-builds it.

### Guest journey timeline view-mode
- **bucket:** `scaffolded-and-pending` (spec written, build not yet started)
- **action_type:** `build`
- **frontend_status:** `n/a` (spec only, no code yet)
- **source_of_truth:** `docs/scratch/TODAY_GUEST_JOURNEY_VIEW_SPEC.md:1` (spec); `app/static/dashboard-v2/src/routes/Today/timeline.ts:1` (`deriveTimeline` already exists and covers ~70% of the merge)
- **defers_to:** —
- **last_verified:** 2026-05-28 (session)
- **upstream_origin:** —
- **cleanup_residue:** —
- **notes:** First post-Today workstream. Spec committed (273b7bd). Followed by in-stay draft visibility (Workstream B) and parity (Workstream C) workstreams per the sequencing decision.

### Notification body on session detail payload
- **bucket:** `substantive-gap-not-built`
- **action_type:** `build`
- **frontend_status:** `no-endpoint-yet`
- **source_of_truth:** `app/static/dashboard-v2/src/adapters/index.js` (the `normalizeSessionDetail` function — notification entries carry id/type/channel/recipient/status/sentAt/deliveredAt/externalId/errorMessage but NOT body/content)
- **defers_to:** —
- **last_verified:** 2026-05-28 (session)
- **upstream_origin:** —
- **cleanup_residue:** —
- **notes:** The cheap backend unlock that would activate the body-based contextual-touch inference heuristic (see `docs/scratch/TODAY_PROACTIVE_VISIBILITY_SPEC.md` Deliverable 3). One field addition. PII-awareness noted: body contains guest-facing text; expose with deliberate posture, not reflexively. Highest-leverage backend gap surfaced this session.

---

## Domain: `cross-system`

### Raw-to-structured extraction pipeline
- **bucket:** `substantive-gap-not-built`
- **action_type:** `build`
- **frontend_status:** `n/a`
- **source_of_truth:** Retention policy at `app/services/operator/message_retention_service.py:14`; purge enforcement at `:159` (deletes `message_normalizations` on the structured-signal window). Existing narrower extractors at `app/services/concierge/message_history.py:349` and `app/services/concierge/operator_learning.py:121`. No canonical extraction job found.
- **defers_to:** —
- **last_verified:** 2026-05-28 (codex)
- **upstream_origin:** —
- **cleanup_residue:** —
- **notes:** Substantive backend gap, not surfacing. Retention policy purges raw on a window; structured signal is supposed to outlive it; nothing guarantees raw becomes structured before purge. Crosses `operator/`, `concierge/`, brain. Worth its own short design doc when prioritized.

### In-stay draft parity surface
- **bucket:** `substantive-gap-not-built`
- **action_type:** `build`
- **frontend_status:** `no-endpoint-yet`
- **source_of_truth:** Gap surfaced by the brain-wiring trace this session. Composition exists (see messaging-domain in-stay reactive row); the parity *surface* (editable draft, approve/edit/send on the guest's channel, autonomy-reason shown, email/SMS reconciliation) does not.
- **defers_to:** —
- **last_verified:** 2026-05-28 (session)
- **upstream_origin:** —
- **cleanup_residue:** —
- **notes:** Workstream C per the sequencing decision. Sends real guest messages; reconciles the email/SMS executor split documented in the operator-domain stay_action_agent row. Earns its own spec.

### Unified "decline to draft when uncertain" primitive
- **bucket:** `substantive-gap-not-built`
- **action_type:** `defer`
- **frontend_status:** `n/a`
- **source_of_truth:** Pattern observed three times this session (proactive consolidation, in-stay reactive parity, compliance/ESA). The component pieces exist on the canonical brain path: `platform_compliance.py:58`, `:109`; `response_policy_agent.py:1`, `:247`; `messaging_brain/grounding/hallucination_guard.py:1` (composer integration pending). A unified primitive that all three call into does NOT exist.
- **defers_to:** `docs/architecture/MESSAGING_TIER_MAP.md` (for the policy/grounding pieces that would constitute it)
- **last_verified:** 2026-05-28 (session synthesis)
- **upstream_origin:** —
- **cleanup_residue:** —
- **notes:** Recurring architectural pattern. Each instance currently solves the "I shouldn't be confident here, route this with framing" problem in its own way. Action is `defer` because the design decision (single unified primitive vs. coordinated paths) is not ready to be made; trigger is the pattern's fourth instance, at which point a spec earns the work. If the design call gets made earlier, the action moves to `build`.

---

## Not yet inventoried

These domains were not covered in this pass. Each line states why and what would unblock a future pass.

- **`operator`** (the rest of `app/services/operator/`) — autonomy persistence, alert routing details, message retention internals beyond the row above. Future pass should walk the directory and inventory each service.
- **`concierge`** (the rest of `app/services/concierge/`) — `message_history.py`, `operator_learning.py`, `knowledge_gap_recorder.py`, `event_planning_service.py`, etc. Touched only as upstream-origin/cleanup-residue context this pass. Future pass should determine which are still canonical, which are residue, which are retired.
- **`workers`** (`app/workers/`) — Celery tasks and schedulers. Proactive runtime now points at `stay_proactive_runtime.py`; future pass should enumerate the rest of the scheduled tasks and their triggers.
- **`mcp`** (`app/mcp/`) — MCP server tools. Proactive journey/proactive message helpers now point at `stay_journey_service.py`; future pass should enumerate the remaining MCP tools and their canonical-path status.
- **`vault`** (`app/services/vault/`) — codex flagged one stub at `secure_vault.py:325`; otherwise not inventoried.
- **`onboarding`** (`app/services/agents/onboarding/`) — operator onboarding flows. Not touched this session.
- **`agents`** (`app/services/agents/` outside `onboarding/`) — healers, knowledge curator, PMS sync, router agent, escalation handoff. Tier-4 cross-cutting per the tier map but not inventoried row-by-row.
- **`integrations`** (`app/services/integrations/`) — Tier 1 parsers, pollers, dispatch. Partially touched via LLM-primary intake rows. Many parsers and dispatch paths not yet inventoried.
- **Property knowledge ownership migration** — flagged in `MESSAGING_TIER_MAP.md` as a documented deferral with explicit triggers. Future pass should include it as an explicit row.

---

## Unverified leads (not in the canonical row set)

These items came from the codex discovery pass or earlier session synthesis but lack a directly-read file:line citation suitable for a canonical row. They are recorded here so they aren't lost, and so a future pass knows to verify them by direct read before extending them into proper inventory rows.

- **`app/services/concierge/knowledge_gap_recorder.py`** — Codex's discovery pass identified this as the surviving gap-recording path on disk after `kb_gap_manager` retirement. Status (canonical, residue, or fully migrated into orchestrator) is not pinned. Direct read needed to determine.
- **`concierge.hallucination_guard` retirement doc citation** — The retirement claim is recorded by codex but not pinned to a specific line in a retirement doc. Pin to `LEGACY_RETIREMENT_PLAN.md` (or wherever the formal retirement lives) on next pass.
- **`app/static/dashboard-v2/src/shared/lists/useCursorList.ts:31`** — Codex flagged as a stub. Stub status confirmed by line citation; the relationship to the Today `limit=200` scalability work item is unverified. Direct read needed to understand what it stubs.
- **`app/api/v1/endpoints/concierge.py:1103`** — Codex flagged as an explicit stub for early check-in evaluation. Direct read needed to confirm exact status.
- **`app/services/vault/secure_vault.py:325`** — Codex flagged as an explicit stub. Direct read needed.

---

## Provenance summary

Rows verified by **fresh file read** this session (highest confidence):
- v2 router mounted surfaces
- `classifyForArrivals` stub
- Today four-stage lifecycle taxonomy + boundary tests
- `timeline.ts` `deriveTimeline`
- Notification body absent on session detail payload (`normalizeSessionDetail`)

Rows verified by **session trace** (file read happened earlier in this 2026-05-28 conversation; cited file:lines accurate):
- All `messaging_brain` orchestrator paths (in-stay routing, KB gap emission, pre-booking forced-review)
- `stay_proactive_service`, `stay_action_agent`
- LLM-primary intake (both email parser and orchestrator) — also user-confirmed via tests
- `guest_journey.py` upstream-origin context before retirement

Rows verified by **codex trace** (user's discovery pass; not directly read by Claude this session — but pinned to file:lines):
- `platform_compliance.py` ADA/ESA logic
- `operator_app.py:764` super-admin scope-switching
- `messaging_brain/grounding/hallucination_guard.py` composer-integration deferral
- `message_retention_service.py` retention windows + enforcement
- `kb_gap_manager` retirement (doc-pinned)
- Phone in-stay path (`phone.py:402`)
- v2 API client unsurfaced endpoints enumeration

Items flagged as **Unverified leads** (recorded but not canonical rows):
- `concierge/knowledge_gap_recorder.py` status
- `concierge.hallucination_guard` retirement doc-pin
- `useCursorList.ts:31` stub purpose
- `concierge.py:1103` early-check-in stub
- `secure_vault.py:325` stub

**Recommendation for next pass:** prioritize promoting the Unverified leads to canonical rows by direct read, then expand into the "Not yet inventoried" domains. The `operator/` and `concierge/` interiors are highest priority because both produced significant residue findings this pass; resolving them sharpens every adjacent row.
