# Brain-Only Unified Migration Plan — 2026-05-23

**Purpose.** This is the master coordinated plan for collapsing the two-pipeline state into a single brain-owned runtime. It supersedes:

- `LEGACY_RETIREMENT_PLAN.md`'s "shared utility — stays" classification
- `SHIP_O_DELETION_INVENTORY_2026-05-20.md` verification windows
- The earlier Phase 4.5.A–G phased sequencing (work product preserved; ordering replaced)
- The earlier `BRAIN_ONLY_RETIREMENT_AUDIT_2026-05-23.md` ship sequencing

It is informed by the dual-caller audit and the brain-path bridge audit (both completed 2026-05-23).

## Governing rules

1. **Brain-only.** Every guest-message capability either lives in `messaging_brain/` (or a brain-aligned home), or it is deleted. No bridges. No "shared utilities" that two paths call.
2. **No surface is touched halfway.** Each surface migration is end-to-end: identify capability → identify all callers (brain *and* legacy) → identify data source → define single surviving owner → rewire every caller → verify → delete old callers and modules and tables in the same coordinated track.
3. **No "delete legacy" commit before surviving wiring is complete.** No "brain rewrite" that leaves legacy callers dangling.
4. **Three caller categories** drive the action:
   - **Duplicate caller, brain already owns the work** → delete legacy caller (no new brain code).
   - **Brain caller still tunnels into legacy** → rewrite brain caller (build brain-native replacement, rewire all directions, then delete legacy).
   - **Dead code** → delete immediately, no rewire needed.
5. **Verify, then delete.** Every delete is preceded by `rg` for call sites and a focused smoke test on the brain path.
6. **BD codebase is out of scope.** The standalone business development codebase is not a deletion target and is not touched by this plan.
7. **Data preservation.** Before any table drop, parity audit against the canonical brain-owned table. Migrate anything missing. Only then drop.

---

## Phase 0 — Clear the playing field

Two things happen before any surface migration starts. They reduce noise and shrink the set of files we have to track.

### 0.1 — Delete confirmed dead code

| File | Why it's dead | Verification before delete |
|---|---|---|
| `app/services/concierge/db_session_manager.py` | References `ConciergeSessionModel`, `ConciergeMessageLogModel`, `ConciergeEscalationModel`, `ConciergeJourneyActivityModel` (with tenant mixin), `ConciergeNotificationModel` (different shape) — none of which exist in `db/models/concierge_sessions.py`. The file would crash on import. | `rg "from app.services.concierge.db_session_manager"` and `rg "import db_session_manager"` across the repo must return zero. |
| `app/services/concierge/db_service.py::ConciergeSessionStore` (the in-memory dict store at the bottom of the file) and `get_session_store()` | Superseded by `db_session_service.py`. In-memory only; no production caller. | `rg "ConciergeSessionStore\|get_session_store"` must return zero outside the file itself. |
| `app/services/concierge/kb_gap_manager.py` | Already marked RETIRED in `LEGACY_RETIREMENT_PLAN.md` item 15. | Confirm the file is actually absent; if present, delete. Also revert any migrations that ever created `kb_gaps` or `operator_gap_settings` tables. |

No behavior change. Single commit. No surface rewiring.

### 0.2 — Identify (do not yet delete) the known-safe duplicate-caller list

These were classified in the dual-caller audit as **"brain already does the work, legacy caller is duplicate."** They do **not** need a brain rewrite. They will be deleted *inside* the surface that owns them — not in a standalone "cleanup pass" — because deleting them ahead of time risks orphaning the surrounding legacy code.

The list (for reference; each entry is consumed by its owning Surface below):

| Helper | Brain caller(s) (keep) | Legacy caller(s) (delete during the owning surface) |
|---|---|---|
| `context_builder.py::retrieve_prebooking_property_evidence`, `build_prebooking_knowledge_lines`, `assess_prebooking_knowledge_richness`, `build_grounding_context`, `build_property_facts_lines` | `messaging_brain/agents/context_builder_agent.py`, `prebooking_llm_draft_agent.py`, `knowledge_gap_agent.py`, `knowledge_gap_hold_agent.py`, `grounded_fallback_agent.py` | `pre_booking_auto_send.py:1136`, `ai_concierge.py:482` |
| `operator_guidance.load_operator_guidance()` | `context_builder_agent.py:511`, `context_builder_agent.py:740`, `prebooking_llm_draft_agent.py:547`, `knowledge_gap_hold_agent.py:257` | `pre_booking_auto_send.py:1500`, `pre_booking_auto_send.py:2115` |
| `response_reviewer.review_concierge_response()` + `match_placeholder_pattern()` | `email_dispatch.py:160` (boundary), `prebooking_llm_draft_agent.py` (grounding flow) | `ai_concierge.py:483`, `pre_booking_auto_send.py:2253` |
| `hallucination_guard.check_grounding()`, `guard_response()` | Brain grounding flow (single surviving path) | `ai_concierge.py:35`, `pre_booking_auto_send.py:60` |

**Rule for these four:** keep the helper file in place during Phase 0. The brain callers are stable. When each owning surface (Phase 3 for the pre-booking ones, Phase 7 for ai_concierge) deletes its legacy caller, the helper becomes brain-only at that point. After the last surface is done, the helper module gets relocated into its proper brain home as part of Phase 8.

---

## Phase 1 — Surface: Knowledge retrieval and FAQ answering

**Why this surface first.** It owns the schema drift (`concierge_knowledge` vs `concierge_scoped_knowledge`), it has the most cross-cutting callers (brain agents + 4 operator dashboard surfaces + MCP), and every downstream surface gets simpler once it is done.

### Capability

- Property-scoped knowledge load (`get_for_property`-equivalent)
- FAQ answer selection (`best_faq_answer`-equivalent, including cross-property transfer)
- Operator dashboard KB CRUD (list, count, create, update, delete, test)
- Knowledge gap recording (write to `concierge_knowledge_gaps`)
- Historical Q&A import (read Escapia history, write FAQ records)
- Guidebook ingest (read operator-uploaded guidebook, write structured records)

### Surviving owner

`app/services/messaging_brain/knowledge/` (new module set):

- `scoped_knowledge_service.py` — reads/writes only `concierge_scoped_knowledge`. Methods: `list_for_property`, `count_for_tenant`, `list_dashboard_entries`, `create_dashboard_entry`, `update_dashboard_entry`, `delete_dashboard_entry`, `test_dashboard_question`, `best_faq_answer`, `best_faq_answer_with_transfer`, `import_records`, `build_property_profile`.
- `topic_registry.py` — `TOPIC_REGISTRY` constant lifted from legacy.
- `gap_recorder.py` — `record_gap_async`, `schedule_gap_record`. Writes only to `concierge_knowledge_gaps`.
- `faq_matcher.py` — pure-Python token matching/scoring logic (lifted from `_faq_match`, `_profile_similarity`, etc. in `knowledge_service.py`).
- `historical_import.py` — relocated from `message_history.py` (the Escapia history → scoped KB import path).
- `guidebook_ingest.py` — relocated from `guidebook_ingest_service.py`. Writes only to `concierge_scoped_knowledge`.

### Canonical data source after cutover

`concierge_scoped_knowledge` only. `concierge_knowledge_gaps` and `concierge_global_faq` remain as canonical brain-owned tables. `concierge_knowledge` is dropped.

### Callers to rewire (brain side — these are the bridges)

| Caller | What it currently does | What it must do after |
|---|---|---|
| `messaging_brain/agents/context_builder_agent.py:73-74,140,403,647` | Imports `ConciergeKnowledgeService`. Instantiates it. Calls `self._knowledge.get_for_property(...)` for both reactive and proactive context builds. | Import `messaging_brain.knowledge.scoped_knowledge_service.ScopedKnowledgeService`. Same method name, same shape, but reads scoped table only. |
| `messaging_brain/agents/access_agent.py:351` | Calls `ConciergeKnowledgeService.best_faq_answer()` after computing local match score. | Call brain-owned `scoped_knowledge_service.best_faq_answer()` against scoped FAQ + global FAQ. |
| `messaging_brain/agents/house_rules_agent.py:314` | Same pattern as AccessAgent. | Same fix. |
| `messaging_brain/agents/grounded_fallback_agent.py:137` | FAQ fallback step still calls legacy `best_faq_answer()`. Property/guidebook fallback above it is already brain-side. | Replace only the FAQ fallback call. The rest of the agent stays. |

### Callers to rewire (operator/dashboard side)

| Caller | What it currently does | What it must do after |
|---|---|---|
| `app/api/v1/endpoints/operator_dashboard_api.py` (11 hits + raw SQL block at L859-902) | Calls `get_concierge_knowledge_service()` for list/create/update/delete/test KB entries. Raw SQL block does direct CRUD on `concierge_knowledge`. | All calls go to `messaging_brain.knowledge.scoped_knowledge_service`. Raw SQL block is deleted and replaced with service calls. |
| `app/api/v1/endpoints/operator_app.py` | Whatever KB calls exist there (per audit notes). | Rewired to brain service. |
| `app/services/operator/dashboard_summary_service.py:11,~314` | Imports via `concierge_bridge.get_concierge_knowledge_service`. Calls `count_dashboard_entries`. | Imports directly from brain service. |
| `app/services/operator/concierge_bridge.py` | Re-export shim that exists only to import legacy KB service into operator code. | **Deleted** in this surface — once `dashboard_summary_service` is rewired, the bridge has no callers. |
| `app/mcp/servers/concierge_mcp.py::_get_faq_answer`, `_record_gap` | Calls legacy `get_concierge_knowledge_service()` and uses `get_for_property`, `best_faq_answer_with_transfer`, `record_gap`. | Either (a) rewired to brain service for the duration of the legacy `/concierge/message` lifetime, or (b) goes away with the whole concierge MCP in Phase 7. Choose (a) here because Phase 1 finishes before Phase 7. |
| `app/api/v1/endpoints/concierge.py` legacy admin endpoints (`import_concierge_knowledge`, `concierge_knowledge_coverage`) | Direct calls to legacy KB service. | These endpoints die in Phase 7. Until then, rewire them to brain service so they don't crash when the legacy service is deleted at end of Phase 1. |
| `app/api/v1/endpoints/admin_seed.py` (psycopg2 INSERT/UPDATE on `concierge_knowledge`) | Beach Habitats seed and `relink_tenant` write directly to legacy table. | Delete the legacy-table INSERT/UPDATE blocks. The seed has already run; future seeds use brain service. Keep the `properties` block untouched. |
| `app/services/concierge/scoped_knowledge_service.py:13,122,746,782` | Imports `_flush_quietly`, `_normalize_question_key` from legacy `knowledge_service.py`. The `project_to_legacy_concierge_knowledge_shape` function reads from `concierge_knowledge` as a fallback source. | Helper imports move into the brain service alongside the new `scoped_knowledge_service.py`. The projection function loses its legacy-table fallback — brain reads scoped table directly. Then this whole file gets folded into the brain home and the legacy file deleted. |
| `app/services/concierge/message_history.py:382-385` | Imports `get_concierge_knowledge_service`, writes historical FAQ extractions into legacy KB. | Rewired to brain service writing to `concierge_scoped_knowledge`. Module itself moves to `messaging_brain/knowledge/historical_import.py` in Phase 4 (Session/runtime). |
| `app/services/concierge/pre_booking_auto_send.py:67,1988` | Constructs `ConciergeKnowledgeService` and calls `best_faq_answer`. Other hits at L659,947,1195,1899,1978 are dict reads of the projected shape — those are fine. | The `best_faq_answer` call is rewired to brain service. The whole file dies in Phase 3 anyway, but during the transition window the call must work. |

### Data parity audit (gate before table drop)

Before dropping `concierge_knowledge`, run this exact check:

1. Count rows by `tenant_id` in both tables.
2. For each row in `concierge_knowledge` for tenant `e07980b2-a990-4b24-91d1-c8cb71ab70e1` (Beach Habitats):
   - Compute a canonical question key from `question`.
   - Look for the same canonical key in `concierge_scoped_knowledge` under a property-or-tenant scope row.
   - If found and answer matches: parity ✓.
   - If found and answer differs: log discrepancy. Decide per row whether the legacy answer or the scoped answer is correct. Migrate the chosen one to scoped.
   - If not found: migrate the row to `concierge_scoped_knowledge`.
3. Re-run the count check after migration. Scoped should be ≥ legacy.
4. Snapshot the legacy table to a `concierge_knowledge_archive_2026-05-23` table or to a JSON dump, just so the data isn't gone irretrievably if something we missed surfaces.
5. Only then drop.

### Execution order inside Phase 1

1. Build the new brain module set (`scoped_knowledge_service.py`, `topic_registry.py`, `gap_recorder.py`, `faq_matcher.py`). Pure new code, no caller change yet.
2. Add brain-side smoke tests against `concierge_scoped_knowledge` to confirm `list_for_property`, `best_faq_answer`, `record_gap` work on the canonical table.
3. Rewire brain callers (`context_builder_agent`, `access_agent`, `house_rules_agent`, `grounded_fallback_agent`). One commit, all four, with focused tests showing the brain path still produces the same drafts on the Beach Habitats regression set.
4. Rewire operator callers (`operator_dashboard_api`, `operator_app`, `dashboard_summary_service`). Delete `operator/concierge_bridge.py`. Smoke-test the dashboard summary endpoint and the KB CRUD endpoints.
5. Rewire MCP and legacy-but-still-live endpoints (`concierge_mcp`, `concierge.py` admin endpoints).
6. Delete legacy-table writes in `admin_seed.py`. Confirm the function still seeds `properties` correctly.
7. Strip legacy-table reads out of `scoped_knowledge_service.py`. Update `project_to_legacy_concierge_knowledge_shape` to read scoped-only.
8. Run the parity audit. Migrate any missing rows.
9. Archive `concierge_knowledge` to a snapshot.
10. Drop `concierge_knowledge` table. Delete `db/models/concierge_knowledge.py::ConciergeKnowledgeModel` (keep the other three classes — Gap, GlobalFAQ, MaintenanceEvent — for now).
11. Delete `app/services/concierge/knowledge_service.py`.
12. Remove `ConciergeKnowledgeService` and `get_concierge_knowledge_service` from `app/services/concierge/__init__.py::_EXPORTS`.

### Delete gate for Phase 1

Before steps 10–12 are allowed:

- `rg "ConciergeKnowledgeService\|get_concierge_knowledge_service"` returns zero outside `knowledge_service.py` itself.
- `rg "FROM concierge_knowledge\b"` (excluding `concierge_knowledge_gaps`, `concierge_global_faq`, `concierge_knowledge_archive_*`) returns zero.
- `rg "concierge_knowledge\b"` in Python files outside `knowledge_service.py` returns only string-label uses (`answer_source="concierge_knowledge"`), which are cosmetic and get cleaned up in Phase 8.
- The Beach Habitats regression set passes through brain context build and FAQ answer selection.
- The dashboard summary endpoint returns the same `kb_entries` count as before (within ±1 if mid-migration race).

---

## Phase 2 — Surface: Context building and evidence assembly

**Why second.** Phase 1 made KB retrieval brain-only. This phase ensures the helpers that *consume* KB data (context builders, evidence assemblers) are also brain-only.

### Capability

Helper functions for assembling pre-booking and reactive context: property facts formatting, evidence retrieval, knowledge-richness assessment, grounding-context assembly.

### Surviving owner

`app/services/messaging_brain/context/` (new module set):

- `prebooking_context.py` — relocated from `context_builder.py`. All functions migrate as-is.
- `property_context.py` — relocated from `concierge/property_context.py::get_property_context`. Reads `pms_listings` directly.
- `operator_guidance.py` — relocated from `concierge/operator_guidance.py::load_operator_guidance`.
- `market_brain.py` + `market_source_adapters.py` — relocated from `concierge/`.

### Callers (brain side — already correct, just need import path update)

| Caller | Current import | New import |
|---|---|---|
| `messaging_brain/agents/context_builder_agent.py` | `from app.services.concierge.context_builder import ...` | `from app.services.messaging_brain.context.prebooking_context import ...` |
| `messaging_brain/agents/prebooking_llm_draft_agent.py:488` | same | same |
| `messaging_brain/agents/knowledge_gap_agent.py:261` | same | same |
| `messaging_brain/agents/knowledge_gap_hold_agent.py:245` | same | same |
| `messaging_brain/agents/grounded_fallback_agent.py` | same | same |
| `messaging_brain/agents/context_builder_agent.py:511,740` (`operator_guidance`) | `from app.services.concierge.operator_guidance import load_operator_guidance` | `from app.services.messaging_brain.context.operator_guidance import load_operator_guidance` |
| `messaging_brain/agents/prebooking_llm_draft_agent.py:547` | same | same |
| `messaging_brain/agents/knowledge_gap_hold_agent.py:257` | same | same |

### Callers (legacy side — to be removed)

| Caller | Action |
|---|---|
| `app/services/concierge/ai_concierge.py:482` (context_builder import) | Dies with `ai_concierge.py` in Phase 7. No standalone action — but the file's import path updates to the brain home so it doesn't break before Phase 7. |
| `app/services/concierge/pre_booking_auto_send.py:1136` (context_builder) | Dies with the file in Phase 3. Same approach. |
| `app/services/concierge/pre_booking_auto_send.py:1500,2115` (operator_guidance) | Same. |

### Execution order inside Phase 2

1. Create `messaging_brain/context/` directory and the four new modules. Pure copy of legacy code, no caller change yet.
2. Update brain caller imports to the new location. Run tests.
3. Update remaining legacy file imports (`ai_concierge.py`, `pre_booking_auto_send.py`) to the new location too, so deletion in Phase 3/7 doesn't trip on missing modules.
4. Delete `app/services/concierge/context_builder.py`, `operator_guidance.py`, `property_context.py`, `market_brain.py`, `market_source_adapters.py`.
5. Confirm via `rg` that the legacy paths return zero.

### Delete gate for Phase 2

`rg "from app.services.concierge.context_builder\|from app.services.concierge.operator_guidance\|from app.services.concierge.property_context\|from app.services.concierge.market_brain\|from app.services.concierge.market_source_adapters"` returns zero across the repo.

---

## Phase 3 — Surface: Pre-booking lifecycle, persistence, dispatch

**Why third.** This is the biggest entangled bridge: `messaging_brain/pre_booking_lifecycle.py` imports a large slice of `pre_booking_auto_send.py`. We have to unwind it before `pre_booking_auto_send.py` can die. The brain composer agents (pricing-policy, portfolio-matching, grounded-fallback, verification-hold, knowledge-gap, knowledge-gap-hold, response-policy, LLM-draft) already exist from Phase 4.5.A–G — this phase is the deletion that closes that migration.

### Capability

- Pre-booking inquiry intake from Escapia / email transport
- Classification (already brain via `deterministic_intake_prefilter` + `llm_intake_agent`)
- Policy enforcement (already brain via `response_policy_agent` + `platform_compliance`)
- Special-case draft handlers: pricing-policy, portfolio-match, grounded-fallback, verification-hold (already brain via dedicated agents)
- Knowledge-gap detection + hold draft (already brain via `knowledge_gap_agent` + `knowledge_gap_hold_agent`)
- LLM draft composition + grounding review (already brain via `prebooking_llm_draft_agent`)
- Persistence to `pre_booking_inquiries`
- Send / alert / timeout scheduling
- Retry path

### Surviving owner

`messaging_brain/pre_booking_lifecycle.py` (already exists, today imports from legacy) becomes the sole orchestrator. Helpers move to:

- `messaging_brain/pre_booking_persistence.py` — `save_inquiry_from_canonical`, `_insert_pre_booking_inquiry`, `_resolve_guest_thread_id_for_save`, `_save_inquiry` (relocated from `concierge/inquiry_persistence.py` and `pre_booking_auto_send.py`).
- `messaging_brain/pre_booking_dispatch.py` — `_send_via_escapia`, `_alert_operator_for_review`, `_schedule_timeout_send`, `_schedule_timeout_auto_send`, `_log_required_mode_event` (relocated from `pre_booking_auto_send.py`).
- `messaging_brain/integrations/escapia_inbox_poller.py` — relocated from `concierge/pre_booking_handler.py`. Calls brain lifecycle directly, not `process_pre_booking_inquiry`.

### Callers (brain side — currently bridging into legacy)

| Caller | Current state | Target state |
|---|---|---|
| `messaging_brain/pre_booking_lifecycle.py:8` | Imports `PreBookingPipelineOrchestrator`, `PreBookingInquiryInput`, `PreBookingClassificationStage`, `PreBookingDecisionStage`, `PreBookingDraftStage`, `SaveInquiryResult`, `InquirySaveContext`, plus the persistence/send/alert helpers from `pre_booking_auto_send.py`. | Stops importing from legacy. The struct types move into `messaging_brain/pre_booking.py` (already exists). The helpers move per the above breakdown. The orchestrator class itself is deleted in favor of the brain lifecycle. |
| `messaging_brain/pre_booking_retry.py` | Imports `pre_booking_auto_send` pieces and the Gmail poller's property-context loader. | Imports from brain persistence + dispatch modules. |
| `app/services/integrations/email_dispatch.py` | Still imports `_build_prebooking_grounding_context`, `_fallback_draft`, `review_concierge_response`, and has a fallback path to `process_pre_booking_inquiry_with_draft`. | The grounding context builder and fallback come from brain. The fallback path is deleted (brain lifecycle is the only path). `match_placeholder_pattern` imports from `messaging_brain/grounding/response_reviewer.py` (Phase 6 relocation; until then from current location). |
| `app/workers/tasks.py` | Imports pre-booking send helpers from legacy. | Imports from `messaging_brain.pre_booking_dispatch`. |

### Callers (legacy side — to be removed)

| Caller | Action |
|---|---|
| `app/services/concierge/pre_booking_handler.py` | Whole file relocated to `messaging_brain/integrations/escapia_inbox_poller.py`. Its single call into `process_pre_booking_inquiry` becomes a call into the brain lifecycle. |
| `app/services/concierge/inquiry_persistence.py` | Whole file relocated to `messaging_brain/pre_booking_persistence.py`. |
| `app/services/concierge/pre_booking_auto_send.py` | Deleted in its entirety at the end of this phase. All capabilities have already migrated (Phase 4.5.A–G work product) or now relocate in this phase. |
| `app/services/concierge/intent_classification_escalator.py` | Deleted. Brain has prefilter + LLM intake. |

### Symbol-group deletion order inside `pre_booking_auto_send.py`

Per the existing `SHIP_O_TARGET_E_SYMBOL_GROUPS.md` ordering, but executed in one phase rather than across verification windows:

1. **Group 1** (portfolio/pricing/grounded-fallback/verification helpers) — brain has all four dedicated agents already. Delete.
2. **Group 2** (knowledge-gap internals) — brain has `knowledge_gap_agent`. Delete.
3. **Group 3** (policy/send-decision: `AutoSendPolicy`, `SendDecision`, `PolicyCheckResult`, `check_inquiry_policy`, `make_send_decision`, `_apply_special_draft_source_policy`, `_get_approval_mode`, `_load_auto_send_policy`) — brain has `response_policy_agent` + `platform_compliance`. Delete.
4. **Group 4** (LLM draft + provider orchestration + grounding: `generate_inquiry_draft`, `_call_prebooking_*`, `_ordered_prebooking_providers`, `_ground_inquiry_draft`, `_build_prebooking_grounding_context`, `_is_usable_draft`, `_build_reasoning_notes`, `_fallback_draft`) — brain has `prebooking_llm_draft_agent`. Delete.
5. **Group 5** (struct types `PreBookingInquiryInput`, `PreBookingClassificationStage`, `PreBookingDecisionStage`, `PreBookingDraftStage`, `SaveInquiryResult`, `InquirySaveContext`) — move to `messaging_brain/pre_booking.py`.
6. **Group 6** (persistence/send/alert helpers) — move to `messaging_brain/pre_booking_persistence.py` and `pre_booking_dispatch.py`.
7. **Group 7** (orchestration shell: `PreBookingPipelineOrchestrator`, `process_pre_booking_inquiry`, `process_pre_booking_inquiry_with_draft`) — delete after lifecycle cutover.
8. Delete the file.

### Execution order inside Phase 3

1. Create `messaging_brain/pre_booking_persistence.py` and `pre_booking_dispatch.py` modules. Copy the symbol groups 5+6 into them. Update internal cross-references.
2. Create `messaging_brain/integrations/escapia_inbox_poller.py` from `concierge/pre_booking_handler.py`. Wire to the brain lifecycle's intake function instead of `process_pre_booking_inquiry`.
3. Update `messaging_brain/pre_booking_lifecycle.py` to stop importing from `pre_booking_auto_send.py`. Use brain agents and brain helpers throughout. The orchestrator class previously used as a compatibility evaluator is replaced with direct brain pipeline calls.
4. Update `messaging_brain/pre_booking_retry.py` to import from brain helpers.
5. Update `app/services/integrations/email_dispatch.py` to remove the fallback path to legacy. Imports come from brain modules.
6. Update `app/workers/tasks.py` to import send helpers from `messaging_brain/pre_booking_dispatch.py`. Also update the `import_historical_messages_for_operator` and `void_stale_drafts_for_operator` paths to use the brain modules (these get fully relocated in Phase 4 with the rest of `message_history.py`).
7. Run regression: Christina Moser case + Beach Habitats production inquiries flow through brain only.
8. Delete symbol groups 1–4 from `pre_booking_auto_send.py` (deterministic helpers superseded by brain agents).
9. Delete symbol group 7 (orchestrator shell).
10. Delete `pre_booking_auto_send.py` entirely.
11. Delete `pre_booking_handler.py` (now relocated).
12. Delete `inquiry_persistence.py` (now relocated).
13. Delete `intent_classification_escalator.py`.

### Delete gate for Phase 3

- `rg "from app.services.concierge.pre_booking_auto_send\|import pre_booking_auto_send"` returns zero.
- `rg "process_pre_booking_inquiry\|process_pre_booking_inquiry_with_draft\|PreBookingPipelineOrchestrator"` returns zero outside the deleted file.
- `rg "from app.services.concierge.pre_booking_handler\|from app.services.concierge.inquiry_persistence\|from app.services.concierge.intent_classification_escalator"` returns zero.
- The Christina Moser regression and the Beach Habitats production set both pass cleanly through brain-only pre-booking.

---

## Phase 4 — Surface: Session and mobile runtime entry

**Why fourth.** Now that KB and pre-booking are brain-owned, the inbound message path itself needs to be free of concierge-namespace imports.

### Capability

- Session token resolution
- Session creation from PMS booking confirmation
- Mobile chat ingestion (`/c/{token}/chat`)
- Voice/SMS/RCS/Apple Messages channel routing
- Property context resolution per session
- Gate-code intercept
- Historical message import (Escapia history)
- Stale draft voiding

### Surviving owner

`messaging_brain/sessions/` (new module set) + existing `messaging_brain/session_channel_adapter.py`:

- `session_service.py` — relocated from `concierge/db_session_service.py`. All `DatabaseSessionService` methods, the journey/activity ops, and `get_db_session_service`.
- `guest_thread.py` — relocated from `concierge/guest_thread_service.py`.
- `thread_property_inheritance.py` — relocated from `concierge/thread_property_inheritance.py`.
- `gate_code.py` — relocated from `concierge/escapia_unified.py::GateCodeService` only (the rest of `escapia_unified.py` is duplicate of brain dispatch and dies).
- `messaging_brain/integrations/escapia_history.py` — relocated from `concierge/message_history.py`. FAQ write target is the brain scoped-knowledge service.

### Callers (brain side — currently bridging into legacy)

| Caller | Bridge | Fix |
|---|---|---|
| `messaging_brain/session_channel_adapter.py:117` | Imports `concierge.property_router`. | Replace with `messaging_brain/context/property_context.py` (Phase 2) + a brain-native property resolver. The tiered fallback (PMS → DB → session JSON → empty) collapses to a single brain read because the brain owns the `pms_listings` reads via `BookingContextAdapter` already. |
| `app/api/v1/endpoints/mobile_v3.py:632,~810` | Imports `from app.services.concierge.db_session_service import DEFAULT_TENANT_ID, get_db_session_service, DatabaseSessionService`. | Imports from `messaging_brain/sessions/session_service.py`. Same function names, same return types. |
| `app/api/v1/endpoints/mobile_v2.py`, `phone.py`, `sms.py` | (Per audit: each was once a `VoicePod.respond` caller; some may already be on brain channel router.) | Confirm each calls `run_session_channel_message` from `messaging_brain/session_channel_adapter.py` and nothing else. Delete any remaining `VoicePod` import. |
| `app/services/concierge/db_session_service.py::create_session` and `upsert_from_guest_session` | Currently called from legacy runtime paths. | Move with the rest of the service into brain; legacy callers go away in Phase 7. |
| `app/services/concierge/ai_concierge.py::intercept_gate_code_request` | Imports from `escapia_unified.py`. | Brain lifecycle gains an equivalent intercept at the inbound point. Then `ai_concierge.py` dies in Phase 7. |
| `app/workers/tasks.py::import_historical_messages_for_operator`, `void_stale_drafts_for_operator` | Imports `HistoricalMessageImporter`, `StaleMessageDetector`, `OrphanMessageHandler` from `concierge/message_history.py`. | Imports from `messaging_brain/integrations/escapia_history.py`. |
| `app/workers/tasks.py::poll_escapia_messages_for_operator` | Uses `concierge/pre_booking_handler.py::get_escapia_message_service`, calls into `concierge/message_history.py::process_incoming_message`, and `pre_booking_auto_send.py` functions. | Already partly fixed in Phase 3 (poller relocated). The `process_incoming_message` path moves into `messaging_brain/integrations/escapia_history.py`. |

### Callers (legacy side — to be removed)

| Caller | Action |
|---|---|
| `app/services/concierge/property_router.py` | Deleted at end of phase. Brain has its own property resolution. |
| `app/services/concierge/db_session_service.py` | Whole file relocates to brain in step 1; legacy file deleted at end of phase. |
| `app/services/concierge/guest_thread_service.py` | Relocated, deleted. |
| `app/services/concierge/thread_property_inheritance.py` | Relocated, deleted. |
| `app/services/concierge/escapia_unified.py` | `GateCodeService` relocated; rest is duplicate of brain dispatch. Deleted. |
| `app/services/concierge/message_history.py` | Relocated, deleted. |
| `app/services/concierge/guest_session.py` (in-memory `GuestSessionManager`, `SessionPhase`, `GuestSession`) | Deleted. Brain uses DB-backed session service. |
| `app/services/concierge/group_session.py` | Audit-confirm zero callers, then delete. |
| `app/services/concierge/sms_service.py` | Audit-confirm: brain uses `channel_router`, not this. Delete. |
| `app/services/concierge/notification_service.py` | Audit-confirm: brain proactive uses different path. Delete. |
| `app/services/concierge/conversation_history_service.py` | Audit before deletion: confirm brain has equivalent. If yes, delete. If no, ABSORB into `messaging_brain/sessions/`. |
| `app/services/concierge/guest_profile_service.py` | Repeat-guest memory. Audit: if brain reads `session_data.get("guest_profile")` anywhere, ABSORB. Otherwise delete with the rest of legacy concierge runtime. |
| `app/services/concierge/post_booking_routing.py` | Audit: classify ABSORB or RETIRE based on whether brain references it. |

### Execution order inside Phase 4

1. Create `messaging_brain/sessions/` and move/copy the four service files (`session_service.py`, `guest_thread.py`, `thread_property_inheritance.py`, `gate_code.py`).
2. Create `messaging_brain/integrations/escapia_history.py` from `concierge/message_history.py`. Rewire its FAQ write to the brain scoped-knowledge service.
3. Replace `session_channel_adapter.py:117` `property_router` import with brain-native resolution. Verify reactive + in-stay flows.
4. Update `mobile_v3.py`, `mobile_v2.py`, `phone.py`, `sms.py` imports. Confirm each is on `run_session_channel_message` and nothing else.
5. Add brain-side gate-code intercept at the inbound point.
6. Update `workers/tasks.py` imports for historical import, stale drafts, gate code, session creation.
7. Resolve open audit items: `group_session.py`, `sms_service.py`, `notification_service.py`, `conversation_history_service.py`, `guest_profile_service.py`, `post_booking_routing.py`. For each, confirm caller graph and either ABSORB or mark for deletion in Phase 7.
8. Delete `property_router.py`, `db_session_service.py`, `guest_thread_service.py`, `thread_property_inheritance.py`, `escapia_unified.py`, `message_history.py`, `pre_booking_handler.py` (already gone from Phase 3), `guest_session.py`, and any of the audited modules confirmed RETIRE.

### Delete gate for Phase 4

- `rg "from app.services.concierge.property_router\|from app.services.concierge.db_session_service\|from app.services.concierge.guest_thread_service\|from app.services.concierge.thread_property_inheritance\|from app.services.concierge.escapia_unified\|from app.services.concierge.message_history\|from app.services.concierge.guest_session"` returns zero.
- Mobile, phone, SMS endpoints all route through `run_session_channel_message` — no `VoicePod.respond` callers remain.
- Beach Habitats live traffic on `/c/{token}/chat` still produces responses.
- Escapia inbox poll and historical-import workers run cleanly.

---

## Phase 5 — Surface: Intake and classification

**Why fifth.** Classification has multiple layers (deterministic prefilter, LLM intake, escalation). Some pieces are clean, some still wrap legacy. Once the prior phases are done, this is the last cross-cutting bridge.

### Capability

- Deterministic keyword-based intent classification (with operator overrides)
- LLM-based intent escalation when deterministic confidence is below threshold
- Escalation detection (urgent/high/medium triggers)
- Topic classification

### Surviving owner

`messaging_brain/intake/` (new module set) + existing brain agents:

- Existing: `messaging_brain/agents/deterministic_intake_prefilter.py`, `llm_intake_agent.py`, `intake_agent.py`, `agent_router.py`, `escalation_agent.py`.
- `messaging_brain/intake/thresholds.py` — moved from `concierge/intent_classification_escalator.py` threshold loading logic.
- `messaging_brain/intake/topic_classifier.py` — relocated from `concierge/topic_classifier.py`.

### Callers (brain side — currently bridging into legacy)

| Caller | Bridge | Fix |
|---|---|---|
| `messaging_brain/agents/intake_agent.py` | Wraps `app/services/agents/router_agent.py::ConciergeRouter`. | Either replace with LLM intake + deterministic prefilter as the canonical intake stack (matching Phase 4.5.A's architectural intent), or accept the existing brain agents as the canonical intake and delete `IntakeAgent`'s wrap entirely. Decision: keep `LLMIntakeAgent` + `DeterministicIntakePreFilter` as the canonical pair; delete `IntakeAgent` if the wrap is the only legacy bridge. |
| `messaging_brain/agents/deterministic_intake_prefilter.py` | Imports `concierge.intent_classification_escalator` for threshold config. | Move threshold config into `messaging_brain/intake/thresholds.py`. Read from there. |
| `messaging_brain/orchestrator.py:103` | Imports `knowledge_gap_recorder` (Phase 1, fine, that's now brain) and `intent_classification_escalator` (legacy). | Threshold loading moves to `messaging_brain/intake/thresholds.py`. |
| `app/services/agents/router_agent.py::ConciergeRouter` | This is in `app/services/agents/`, not under `concierge/`. But it's still legacy-pattern code. | Audit: confirm what calls it. If only `IntakeAgent` does and `IntakeAgent` is being deleted, then `router_agent.py` is also dead and goes. |

### Callers (legacy side — to be removed)

| Caller | Action |
|---|---|
| `app/services/concierge/intent_classification_escalator.py` | Threshold loading moves to brain. Then deleted. |
| `app/services/concierge/topic_classifier.py` | Relocated to brain. |
| `app/services/concierge/escalation_service.py` | Audit-confirm brain's `escalation_agent.py` is independent. If yes, delete the legacy service. If brain reads any data table the legacy service owns (`concierge_escalations`?), migrate the read into the brain agent first. |
| `app/services/agents/router_agent.py::ConciergeRouter` | If `IntakeAgent` was its only caller and `IntakeAgent` is deleted, this dies too. |

### Execution order inside Phase 5

1. Audit `app/services/agents/` and `app/services/concierge/escalation_service.py` for caller graphs.
2. Create `messaging_brain/intake/thresholds.py`. Move threshold-loading logic from `intent_classification_escalator.py`. Update `deterministic_intake_prefilter.py` and `orchestrator.py` imports.
3. Move `topic_classifier.py` to `messaging_brain/intake/topic_classifier.py`. Update callers.
4. Decide on `IntakeAgent`: delete or keep as a thin orchestration wrapper around the two brain agents. (Probably delete; the two brain agents can be called directly from the orchestrator.)
5. Confirm `escalation_agent.py` is fully independent. Migrate any necessary data-table reads into it.
6. Delete `intent_classification_escalator.py`, `topic_classifier.py`, `escalation_service.py`, and `router_agent.py` if confirmed unreferenced.

### Delete gate for Phase 5

- `rg "from app.services.concierge.intent_classification_escalator\|from app.services.concierge.topic_classifier\|from app.services.concierge.escalation_service"` returns zero.
- `rg "from app.services.agents.router_agent"` returns zero (assuming the audit confirmed it can be deleted).
- The deterministic resolution rate on Beach Habitats traffic is unchanged (the threshold migration was a pure relocation).

---

## Phase 6 — Surface: Maintenance, pricing, market, gap recording, grounding helpers

**Why sixth.** These are narrower bridges that haven't blocked the earlier phases. They get cleaned up after the major surfaces.

### Capability

- Maintenance event classification + storage (maintenance request → event row)
- Pricing/market demand lookup
- Market brain bundle (live conditions, alerts, events)
- Knowledge gap recording write path
- Grounding helpers (hallucination_guard, response_reviewer)

### Surviving owner

- `messaging_brain/modules/maintenance_module.py` — already exists; absorbs the legacy `maintenance_service.py` helpers.
- `messaging_brain/pricing/market_demand.py` — relocated from `concierge/db_service.py::get_market_demand`.
- `messaging_brain/context/market_brain.py` — already moved in Phase 2.
- `messaging_brain/knowledge/gap_recorder.py` — already moved in Phase 1.
- `messaging_brain/grounding/hallucination_guard.py`, `response_reviewer.py` — relocated from `concierge/` now that all legacy callers are gone (Phases 3 and 7 will have removed them).

### Callers (brain side)

| Caller | Bridge | Fix |
|---|---|---|
| `messaging_brain/modules/maintenance_module.py:63` | Imports `_category_for`, `_severity_for`, and the maintenance event-write service from `concierge/maintenance_service.py`. | Relocate those helpers into the module itself or into `messaging_brain/modules/maintenance_helpers.py`. The event-write goes to `concierge_maintenance_events` (still canonical) but via brain-owned code. |
| `messaging_brain/agents/pricing_policy_agent.py:7` | Imports `concierge.db_service.get_market_demand`. | Relocate to `messaging_brain/pricing/market_demand.py`. |
| `app/services/operator/stay_workflow_service.py:19` | Imports `concierge.market_brain`. | Operator side — Phase 2 already relocated `market_brain.py` to `messaging_brain/context/`. Update this import to the brain location. |

### Callers (legacy side — to be removed)

| Caller | Action |
|---|---|
| `app/services/concierge/maintenance_service.py` | Helpers relocated. File deleted. |
| `app/services/concierge/db_service.py::get_market_demand` | Function relocated. The remaining utility functions (`get_property_amenities`, `check_next_booking`, `get_property_for_concierge`) audit: brain already has `BookingContextAdapter`. Delete legacy functions and the whole file. |
| `app/services/concierge/db_service.py::ConciergeSessionStore` and `get_session_store` | Already deleted in Phase 0. |

### Execution order inside Phase 6

1. Relocate `maintenance_service.py` helpers into `messaging_brain/modules/`. Update `maintenance_module.py` imports.
2. Relocate `get_market_demand` to `messaging_brain/pricing/market_demand.py`. Update `pricing_policy_agent.py`.
3. Audit remaining functions in `db_service.py`. If brain has equivalents, delete. If not, ABSORB.
4. Relocate `hallucination_guard.py` and `response_reviewer.py` from `concierge/` to `messaging_brain/grounding/`. Update remaining callers (`email_dispatch.py`, brain agents).
5. Delete `concierge/maintenance_service.py`, `db_service.py`, `hallucination_guard.py`, `response_reviewer.py`.

### Delete gate for Phase 6

- `rg "from app.services.concierge.maintenance_service\|from app.services.concierge.db_service\|from app.services.concierge.hallucination_guard\|from app.services.concierge.response_reviewer"` returns zero.

---

## Phase 7 — Legacy runtime deletion (the bulk delete)

**Why seventh.** Every surface migration is done. The legacy concierge runtime no longer has any callers because the brain has absorbed or replaced every bridge. This phase is the bulk deletion that closes out the dual-pipeline state.

### What gets deleted

| File / endpoint | Reason it can be deleted now |
|---|---|
| `app/api/v1/endpoints/concierge.py` (all of it: `/concierge/message`, `/concierge/decision`, `concierge_knowledge_coverage`, `import_concierge_knowledge`) | Brain runtime is the only path. The flag-off compatibility for `/concierge/message` is explicitly given up. |
| `app/api/v1/endpoints/voice.py` (`/voice/concierge` non-prod) | Already non-prod. |
| `app/services/concierge/concierge_runner.py` | No callers after `/concierge/message` and `/voice/concierge` are gone. |
| `app/services/orchestration/concierge_runner.py` (re-export shim) | Same. |
| `app/services/concierge/ai_concierge.py` | The legacy MCP-driven pipeline. No callers after `/concierge/message` is gone. |
| `app/services/concierge/concierge_intelligence.py` | Called only by `ai_concierge.py`. Goes with it. |
| `app/services/concierge/dining_service.py` | Called only by `concierge_mcp.py`. Goes with the MCP. |
| `app/services/concierge/event_planning_service.py` | Called only by the legacy `/concierge/message` endpoint. Goes with it. |
| `app/services/concierge/bd_insight_service.py` | Called only by `ai_concierge.py`. Goes with it. (If brain wants the velocity-nudge feature, ABSORB at that time.) |
| `app/services/concierge/operator_bridge.py` (re-export of `get_prebooking_queue_service`) | Bridge to legacy. Callers import directly from `app/services/operator/prebooking_queue_service.py` after Phase 1. |
| `app/services/concierge/portfolio_availability_service.py` | If brain's `portfolio_matching_agent.py` already has equivalent or has been wired through it. Otherwise ABSORB into the agent first. (Audit-required.) |
| `app/services/concierge/guidebook_ingest_service.py` | Phase 1 moved it to `app/services/ingestion/`. Legacy location deleted. |
| `app/services/concierge/proactive/guest_journey.py` | Completed on 2026-05-28. The file was deleted; MCP/mobile/operator/worker callers were repointed to `app/services/operator/stay_journey_service.py` and `stay_proactive_runtime.py`, and helper text/provider logic was re-homed there. |
| `app/mcp/servers/concierge_mcp.py` | The whole legacy concierge MCP server. No brain-side caller. |
| `app/mcp/servers/knowledge_mcp.py` | Audit: if brain has direct access to `LibrarianAgent` and doesn't go through this MCP, delete. |
| `app/services/concierge/__init__.py` `_EXPORTS` | Every export was for a now-deleted module. Reduce to empty or delete the file. |

### Execution order inside Phase 7

1. Final audit pass to confirm zero callers remain for each deletion target.
2. Delete endpoint files first (`concierge.py`, `voice.py`).
3. Delete service files (`concierge_runner.py`, `ai_concierge.py`, `concierge_intelligence.py`, `dining_service.py`, `event_planning_service.py`, `bd_insight_service.py`, `operator_bridge.py`, `portfolio_availability_service.py` if confirmed, `proactive/guest_journey.py` if confirmed). Historical note: `proactive/guest_journey.py` was deleted on 2026-05-28.
4. Delete MCP servers (`concierge_mcp.py`, `knowledge_mcp.py` if confirmed). Update `app/mcp/registry.py`.
5. Clear `concierge/__init__.py::_EXPORTS`.

### Delete gate for Phase 7

- `rg "from app.api.v1.endpoints.concierge\|from app.api.v1.endpoints.voice"` returns zero.
- `rg "from app.services.concierge.concierge_runner\|from app.services.orchestration.concierge_runner\|from app.services.concierge.ai_concierge\|from app.services.concierge.concierge_intelligence\|from app.services.concierge.dining_service\|from app.services.concierge.event_planning_service\|from app.services.concierge.bd_insight_service\|from app.services.concierge.operator_bridge"` returns zero.
- The Beach Habitats `/c/{token}/chat` live traffic still works.

---

## Phase 8 — Final cleanup

### What gets done

1. `app/services/concierge/__init__.py` is reduced to an empty file (or the whole directory deleted if no files remain).
2. `db/models/concierge_knowledge.py` is reduced to just `ConciergeKnowledgeGapModel`, `ConciergeGlobalFAQModel`, `ConciergeMaintenanceEventModel` (or the gap/FAQ/maintenance models are moved to dedicated brain-aligned files; the cosmetic split is up to taste).
3. Cosmetic cleanup: `answer_source="concierge_knowledge"` string labels in the brain code get renamed to `answer_source="scoped_knowledge"`. This is purely cosmetic but ends the last vestige of the old name.
4. Update `LEGACY_RETIREMENT_PLAN.md` and `SHIP_O_DELETION_ARC.md` — every item flips to RETIRED. Or replace both docs with a short note pointing to this plan and to the audit.
5. Repo-wide grep: `rg "from app.services.concierge"` should return either zero or only the path-neutral imports we explicitly kept (likely zero).
6. Repo-wide grep: `rg "concierge_knowledge\b"` in non-archive contexts should return zero.
7. Update `docs/architecture/` index docs to reflect the new module layout.

### Delete gate for Phase 8

Repo is in a state where any future engineer (or Claude session) reading the codebase can ask "where does X happen?" and the answer is in `messaging_brain/`. There is no second runtime.

---

## Open audit items (resolve in their respective phase)

Each of these needs a brief read before its phase executes. None block Phase 0 or Phase 1.

| Item | Phase that needs the answer | Question |
|---|---|---|
| `app/services/concierge/group_session.py` | Phase 4 | Any caller? If not, RETIRE. |
| `app/services/concierge/post_booking_routing.py` | Phase 4 | Purpose? ABSORB or RETIRE? |
| `app/services/concierge/sms_service.py` | Phase 4 | Brain uses `channel_router`. Confirm no caller. RETIRE. |
| `app/services/concierge/conversation_history_service.py` | Phase 4 | Brain reads `concierge_messages` directly. Confirm no brain caller of this service. RETIRE. |
| `app/services/concierge/guest_profile_service.py` | Phase 4 | Brain reads `session_data.get("guest_profile")`. Where does that get populated? If by this service, ABSORB to `messaging_brain/sessions/`. |
| `app/services/concierge/thread_property_inheritance.py` | Phase 4 | Caller graph confirmed (Phase 4 inventory says ABSORB). |
| `app/services/concierge/maintenance_service.py` | Phase 6 | Brain's `MaintenanceAgent` and `maintenance_module.py` confirmed independent or absorbing helpers? |
| `app/services/concierge/escalation_service.py` | Phase 5 | Brain's `EscalationAgent` confirmed independent? Migrate any data-table reads. |
| `app/mcp/servers/` (detector, eq, governance, neighborhood_intel, pms, sanitizer, scraper, signal) | Phase 7 | Each: does brain call this? If no, retire. If yes, relocate. |
| `app/api/v1/endpoints/mobile_v2.py`, `phone.py`, `sms.py` | Phase 4 | Confirm each is fully on `run_session_channel_message`. Delete any `VoicePod.respond` reference. |
| `db/models/concierge_escalations.py`, `concierge_dining_reservations.py` | Phase 5, Phase 7 | Brain reads these? Migrate or drop. |
| `app/services/agents/router_agent.py::ConciergeRouter` | Phase 5 | Only caller is `IntakeAgent`. If `IntakeAgent` deletes, this dies. |

---

## Surface dependency graph (visual reference)

```
Phase 0: Dead code + opportunistic duplicates
  │
  ├──> Phase 1: KB retrieval + FAQ answering
  │       (drops concierge_knowledge table, removes biggest bridge)
  │
  ├──> Phase 2: Context building + evidence assembly
  │       (relocates shared helpers, depends on Phase 1 for KB seam)
  │
  ├──> Phase 3: Pre-booking lifecycle + persistence + dispatch
  │       (deletes pre_booking_auto_send.py, depends on Phases 1+2)
  │
  ├──> Phase 4: Session + mobile runtime entry
  │       (independent of Phase 3 but easier after pre-booking is brain-only)
  │
  ├──> Phase 5: Intake + classification
  │       (independent, but easier after Phase 3 because brain orchestrator is canonical)
  │
  ├──> Phase 6: Maintenance + pricing + market + grounding helpers
  │       (narrower; cleans up the last bridge surfaces)
  │
  ├──> Phase 7: Legacy runtime bulk deletion
  │       (only possible after Phases 1-6 — every bridge is gone)
  │
  └──> Phase 8: Final cleanup + doc updates
```

Phases 1, 2, 3 are sequential dependencies. Phase 4 can run in parallel with Phase 3 after Phase 2 is done. Phase 5 can run in parallel with Phase 4. Phase 6 can run any time after Phase 1. Phase 7 requires all of 1–6 done. Phase 8 is housekeeping.

---

## Verification discipline across all phases

For every phase:

- Before any delete: `rg` proves zero callers.
- Before any table drop: parity audit + archive snapshot.
- After each surface: Beach Habitats production regression set runs through brain only. Christina Moser case + at least 5 representative production messages (pet inquiry, pricing, portfolio search, amenity ask, gate-code ask).
- Commit messages cite the surface and the deleted symbols.
- After each phase: `LEGACY_RETIREMENT_PLAN.md` (or replacement doc) updated.

---

## What this plan deliberately does not do

- No "brain rewrite week" followed by "legacy deletion week." Every surface is end-to-end in its own phase.
- No verification windows. Hunter overruled this — we delete now and watch production.
- No preservation of "shared utility" as a permanent category. Helpers either live in `messaging_brain/` or they're gone.
- No touching the BD codebase.

---

## Immediate next action

Phase 0 (Section 0.1). Three dead-code deletions, single commit, no behavior change:

1. `app/services/concierge/db_session_manager.py`
2. `app/services/concierge/db_service.py::ConciergeSessionStore` and `get_session_store`
3. `app/services/concierge/kb_gap_manager.py` (confirm absent or delete)

Then Phase 1 begins.
