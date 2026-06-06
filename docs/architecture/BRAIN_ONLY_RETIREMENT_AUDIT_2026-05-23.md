# Brain-Only Retirement Audit — 2026-05-23

**Decision context.** Hunter is overruling the existing retirement plan's notion of "shared utility — stays where it is." The new rule is binary: every capability either lives inside `messaging_brain/` (and only `messaging_brain/` calls it), or it's deleted. No two-pipeline state. No bridges. No legacy modules that the brain happens to call. The `LEGACY_RETIREMENT_PLAN.md` "out of scope" list is no longer authoritative.

The schema drift on `concierge_knowledge` is the canonical example of why: the table exists in two shapes (declared JSONB in migration 004, present in legacy Q&A shape in production), and `knowledge_service.py` carries dual-shape handling code, and the audit endpoint keeps breaking on the drift. The fix is not smarter dual-shape handling — the fix is one table (`concierge_scoped_knowledge`), one service (brain-owned), one path.

This document is the corrected inventory. Each module under `app/services/concierge/` (and the cross-cutting modules under `app/services/operator/` and `app/mcp/`) is classified into one of four buckets:

- **ABSORB** — capability is used by the brain. The brain-relevant logic moves into a brain-owned module. Legacy file deleted afterward.
- **RETIRE** — capability is legacy-only. The brain doesn't need it. File deleted.
- **DEAD** — the module is already non-functional (broken imports, no callers, dead code from a prior migration). Delete immediately.
- **KEEP-PATH-NEUTRAL** — genuinely path-neutral infrastructure (DB session, identity normalization, etc.) that doesn't sit between guest input and concierge response. Stays where it is.

Tables get the same treatment: one canonical table per concern, owned by the brain, with the legacy table dropped.

The audit is followed by a recommended execution order. Verification windows from `SHIP_O_DELETION_INVENTORY_2026-05-20.md` are not respected — per Hunter's instruction we delete now and watch what happens, since the dual-pipeline carrying cost is larger than the rollback cost.

---

## Module inventory

### `app/services/concierge/`

| Module | Legacy caller? | Brain caller? | Both? | Classification | Notes |
|---|---|---|---|---|---|
| `__init__.py` (`_EXPORTS` re-export shim) | Yes (lazy re-exports of `ConciergeRunner`, `ConciergeKnowledgeService`, `EscalationService`, `GuestSessionManager`, `NotificationService`, `DiningReservationService`, `EventPlanningService`) | No | n/a | **RETIRE** | The re-export module exists only to support the legacy concierge runtime. Once the runtime is gone the shim has no callers. |
| `concierge_runner.py` | Yes (`/concierge/message` flag-off, `/concierge/decision`, `/voice/concierge`) | No | No | **RETIRE** | The legacy reactive runtime. Brain (`messaging_brain/orchestrator.py`, `session_channel_adapter.py`) owns reactive concierge. Already a Ship O target (A1/A2/A3). Delete all three endpoints with it. |
| `ai_concierge.py` | Yes (`/concierge/message`'s `_handle_via_existing` path, plus `concierge_intelligence.smart_generate` calls it as a Gemini fallback) | No (brain has `LLMComposerAgent`, `grounded_fallback_agent`, `verification_hold_agent` etc.) | No | **RETIRE** | Entire MCP-driven pipeline duplicates brain pipeline. |
| `concierge_intelligence.py` (`smart_generate`, dual-provider routing, conversational intent detection) | Yes (called by `ai_concierge.py`) | No (brain has its own routing in `llm_composer_agent.py` and `prebooking_llm_draft_agent.py`) | No | **RETIRE** | Whole intelligence layer is duplicate of brain composer. Hunter asked for one composer — keep the brain's. |
| `context_builder.py` (`build_grounding_context`, `build_property_facts_lines`, `build_prebooking_knowledge_lines`, `retrieve_prebooking_property_evidence`, `assess_prebooking_knowledge_richness`) | Yes (`ai_concierge.py`, `pre_booking_auto_send.py`) | **Yes** (`messaging_brain/agents/context_builder_agent.py` and `messaging_brain/agents/prebooking_llm_draft_agent.py` both import it) | **Yes — DUAL CALLER** | **ABSORB** | This is the textbook "shared utility that's actually a dual-caller." Move all functions into `messaging_brain/context/prebooking_context.py`. Update brain imports. Delete the legacy module with the rest of legacy. |
| `hallucination_guard.py` (`check_grounding`, `guard_response`) | Yes (`ai_concierge.py`, `pre_booking_auto_send.py`) | **Yes** (`messaging_brain/agents/prebooking_llm_draft_agent.py`) | **Yes — DUAL CALLER** | **ABSORB** | Pure functions. Move to `messaging_brain/grounding/hallucination_guard.py`. Brain only. |
| `response_reviewer.py` (`review_concierge_response`, `match_placeholder_pattern`) | Yes (`ai_concierge.py`, `pre_booking_auto_send.py`) | **Yes** (`messaging_brain/agents/prebooking_llm_draft_agent.py`, `email_dispatch.py` boundary guard) | **Yes — DUAL CALLER** | **ABSORB** | Move to `messaging_brain/grounding/response_reviewer.py`. The placeholder regex set lives there; `email_dispatch.py` imports `match_placeholder_pattern` from the brain home. |
| `operator_guidance.py` (`load_operator_guidance`) | Yes (`pre_booking_auto_send.py`) | **Yes** (`messaging_brain/agents/llm_composer_agent.py`) | **Yes — DUAL CALLER** | **ABSORB** | One DB query. Move to `messaging_brain/context/operator_guidance.py`. |
| `knowledge_service.py` (the whole `ConciergeKnowledgeService` class) | Yes (`endpoints/concierge.py`, `endpoints/operator_dashboard_api.py`, `endpoints/admin_seed.py`, `pre_booking_auto_send.py`, `mcp/servers/concierge_mcp.py`, `operator/concierge_bridge.py`, `operator/dashboard_summary_service.py`, `message_history.py`) | **Yes** (`messaging_brain/agents/context_builder_agent.py` imports `ConciergeKnowledgeService` and calls `get_for_property`, plus `knowledge_gap_recorder.py` which is called by both pipelines) | **Yes — DUAL CALLER, the canonical drift case** | **ABSORB** | Build new `messaging_brain/knowledge/scoped_knowledge_service.py` that reads/writes only `concierge_scoped_knowledge`. Migrate the brain's import. Migrate dashboard endpoints to read from it. Delete `knowledge_service.py` AND drop the `concierge_knowledge` table in the same change set. This is the schema drift fix. |
| `scoped_knowledge_service.py` | Yes (its own legacy module imports `_flush_quietly`, `_normalize_question_key` from `knowledge_service.py`; reads from both `concierge_knowledge` and `concierge_scoped_knowledge` during a projection) | **Yes** (brain calls it indirectly via `knowledge_service.py`'s projection function; brain's own `context_builder_agent.py` and `prebooking_llm_draft_agent.py` consume the dict shape) | Both | **ABSORB** | Move into `messaging_brain/knowledge/`. Strip the `project_to_legacy_concierge_knowledge_shape` function — once `concierge_knowledge` is dropped, no projection is needed. Brain reads scoped table directly. |
| `knowledge_topic_registry.py` (`TOPIC_REGISTRY`) | Yes (`pre_booking_auto_send.py`'s `detect_missing_knowledge`) | **Yes** (`scoped_knowledge_service.py`, `messaging_brain/agents/knowledge_gap_agent.py` once that absorbs gap detection) | Both | **ABSORB** | Static data structure. Move to `messaging_brain/knowledge/topic_registry.py`. |
| `knowledge_gap_recorder.py` (`record_gap_async`, `schedule_gap_record`) | Yes (`ai_concierge.py`, `pre_booking_auto_send.py` via grounding flow) | **Yes** (`messaging_brain/agents/prebooking_llm_draft_agent.py` indirectly via grounding) | Both | **ABSORB** | Move to `messaging_brain/knowledge/gap_recorder.py`. The gap-write target is `concierge_knowledge_gaps` (which stays — see table inventory below). |
| `guidebook_ingest_service.py` | No (called by `endpoints/operator_properties.py::reconcile`) | No | n/a | **ABSORB → relocate** | This is the canonical guidebook ingest path. It needs to live somewhere brain-adjacent, not under `concierge/`. Move to `app/services/ingestion/guidebook_ingest.py`. Writes go to `concierge_scoped_knowledge`. |
| `property_context.py` (`get_property_context`) | Yes (`ai_concierge.py`, `concierge_mcp.py`'s `get_property_basics`, `pre_booking_auto_send.py`) | **Yes** (brain agents read property context dict shape indirectly) | Both | **ABSORB** | Move to `messaging_brain/context/property_context.py`. The function reads `pms_listings` + a small JSON cache. Brain-only. |
| `property_router.py` (`PropertyRouter`, `ResolvedPropertyContext`) | Yes (legacy mobile_v2, voice path) | No (brain reads `pms_listings` directly via its own adapters) | No | **RETIRE** | The tiered-resolution complexity isn't needed in the brain path. Brain has `messaging_brain/booking_context_types.py` and the BookingContext adapters. Delete. |
| `db_session_service.py` (`DatabaseSessionService`) | Yes (legacy MCP servers, `concierge_runner`, `ai_concierge`) | **Yes** (`endpoints/mobile_v3.py` calls `get_db_session_service` to look up by token) | Both | **ABSORB** | Session lifecycle is brain-needed. Move to `messaging_brain/sessions/session_service.py`. The functions (`get_session_by_token`, `create_session`, `add_message`, journey ops) move with it. |
| `db_session_manager.py` | No callers found; **references `ConciergeSessionModel`, `ConciergeMessageLogModel`, `ConciergeEscalationModel` which do not exist** in `db/models/concierge_sessions.py` | No | n/a | **DEAD** | Would crash on import. Delete immediately. |
| `db_service.py` (`get_property_amenities`, `check_next_booking`, `get_property_for_concierge`, `get_market_demand`, `ConciergeSessionStore` in-memory) | Yes (legacy concierge paths) | **Yes** (`messaging_brain/agents/pricing_policy_agent.py` uses `get_market_demand`) | Both | **ABSORB partial / RETIRE partial** | `get_market_demand` → move to `messaging_brain/pricing/market_demand.py`. `get_property_amenities`, `check_next_booking`, `get_property_for_concierge` → either move to brain or delete if brain already has equivalent reads (it does — via `BookingContextAdapter`). `ConciergeSessionStore` (in-memory dict store) is **DEAD** — superseded by `db_session_service`. |
| `dining_service.py` (`DiningReservationService`, dining MCP tool backend) | Yes (`mcp/servers/concierge_mcp.py::search_restaurants`, `check_dining_availability`, `create_dining_reservation`) | No (brain has no dining agent yet) | No | **RETIRE** | The dining workflow is concierge MCP only. If brain ever needs dining, it absorbs this then. For now, delete with the concierge MCP. |
| `event_planning_service.py` | Yes (`endpoints/concierge.py::event_planning_shortcut`) | No | No | **RETIRE** | Event-planning shortcut is in the legacy concierge endpoint that's being retired. |
| `escalation_service.py` (`EscalationService`, `EscalationDetector`, `EscalationTicket`) | Yes (legacy concierge MCP) | **Yes** (`messaging_brain/agents/escalation_agent.py` is the brain replacement) | Both | **RETIRE** | Brain already has its own `EscalationAgent`. The brain doesn't need the legacy detector logic. Delete `escalation_service.py`. Migrate any data table it owns to the brain agent. |
| `escapia_unified.py` (gate code service, booking-confirmed session creation, platform reply routing) | Yes (`ai_concierge.py::intercept_gate_code_request`, `pre_booking_auto_send.py`) | No (brain doesn't have a gate-code intercept yet; brain's pre-booking dispatch in `pre_booking_lifecycle.py` does its own Escapia reply) | No (mostly legacy with one canonical helper) | **ABSORB** | The `GateCodeService` is a real capability. Move to `messaging_brain/integrations/escapia_gate_code.py`. The `EscapiaUnifiedMessageHandler.send_platform_reply` overlaps with brain's pre-booking dispatch — consolidate into the brain's dispatch path. |
| `guest_session.py` (`GuestSession`, `SessionPhase`, `GuestSessionManager` in-memory) | Yes (legacy runtime) | No | No | **RETIRE** | In-memory session manager. Superseded by `db_session_service`. Delete. |
| `group_session.py` | Need to check — but its name suggests grouped guest sessions for legacy proactive | TBD | TBD | **likely RETIRE** | Not in active brain path; verify it's unreferenced by brain. |
| `guest_profile_service.py` | Yes (`ai_concierge.py` reads `session_data.get("guest_profile")`) | Possibly | TBD | **ABSORB** | Repeat-guest memory snippet is a useful capability. Move to brain if it's actually being read. |
| `guest_thread_service.py` (`get_guest_thread_service`, `ensure_session_thread`) | Yes (`db_session_service.py`) | **Yes** (`messaging_brain/pre_booking_lifecycle.py` and lifecycle threads use it) | Both | **ABSORB** | Move to `messaging_brain/sessions/guest_thread.py`. |
| `inquiry_persistence.py` (`save_inquiry_from_canonical`) | Yes (`pre_booking_auto_send.py`) | **Yes** (`messaging_brain/pre_booking_lifecycle.py`) | Both | **ABSORB** | Pre-booking persistence. Move to `messaging_brain/pre_booking_persistence.py`. |
| `intent_classification_escalator.py` (`classify_with_escalation`) | Yes (`pre_booking_auto_send.py::PreBookingPipelineOrchestrator.classify`) | No (brain has `deterministic_intake_prefilter.py` + `llm_intake_agent.py`) | No | **RETIRE** | Brain's intake replaces this whole module. |
| `maintenance_service.py` | Yes (legacy concierge maintenance flow) | **Yes** (`messaging_brain/agents/maintenance_agent.py` exists) | Both — likely | **RETIRE** | Brain has `MaintenanceAgent`. If `maintenance_service.py` writes to a maintenance-events table the brain agent should read, move that table read into the brain agent and delete the legacy service. |
| `market_brain.py` (`build_market_brain_bundle`, `format_market_brain_context`) | Yes (`ai_concierge.py`, `operator/stay_workflow_service.py`) | Yes (brain pricing/context paths may use it) | Both | **ABSORB** | Move to `messaging_brain/context/market_brain.py`. |
| `market_source_adapters.py` | Yes (called by `market_brain.py`) | Yes (indirect via market_brain) | Both | **ABSORB** | Goes with `market_brain.py`. |
| `message_history.py` (`HistoricalMessageImporter`, `StaleMessageDetector`, `OrphanMessageHandler`, `process_incoming_message`) | Yes (`workers/tasks.py::import_historical_messages_for_operator`, `workers/tasks.py::void_stale_drafts_for_operator`, `pre_booking_handler.py`, `pre_booking_auto_send.py`) | **Yes** (line 382 imports `get_concierge_knowledge_service` and writes historical FAQ data to it) | Both | **ABSORB** | Move to `messaging_brain/integrations/escapia_history.py`. Rewire the FAQ write target to `concierge_scoped_knowledge`. |
| `notification_service.py` (`GuestNotificationService`) | Yes (legacy proactive path) | No (brain's proactive lives in `messaging_brain/proactive_trigger_adapter.py` and dispatches via channel routers) | No | **RETIRE** | If brain ever needs notification helpers absorb at that time. |
| `operator_bridge.py` (re-export of `get_prebooking_queue_service`) | Yes (concierge endpoints) | Yes (brain consumes the queue indirectly) | Both — but it's just a re-export | **RETIRE** | The bridge exists to bridge legacy. Delete the bridge. Callers import `get_prebooking_queue_service` directly from `app/services/operator/prebooking_queue_service.py`. |
| `operator_learning.py` (`OperatorLearningService`, `EditAnalyzer`, `build_preference_context`, `rebuild_platform_intelligence`) | Yes (legacy edit-capture in `pre_booking_auto_send.py`) | **Yes** (`messaging_brain/agents/llm_composer_agent.py` after Phase 4.5.B) | Both | **ABSORB** | Move to `messaging_brain/learning/operator_learning.py`. Tables stay (`operator_learned_preferences`, `operator_draft_events`, `platform_learning_events`, `platform_intelligence`) — they're data, not legacy. |
| `portfolio_availability_service.py` (`PortfolioAvailabilityService::find_available_nearby`) | Yes (`mcp/servers/concierge_mcp.py::find_nearby_available`, `ai_concierge.py`) | Possibly via `portfolio_matching_agent.py` | TBD | **ABSORB** | Move to `messaging_brain/portfolio/availability.py`. The portfolio-matching brain agent already exists; collapse logic into it or have it call this. |
| `post_booking_routing.py` | TBD — not previously read | TBD | TBD | **ABSORB or RETIRE** | Audit before next action. Likely a brain capability if it exists. |
| `pre_booking_auto_send.py` (the legacy orchestrator — 2000+ lines) | Yes (the whole legacy pre-booking pipeline) | Yes (`messaging_brain/pre_booking_lifecycle.py` instantiates `PreBookingPipelineOrchestrator` for compatibility) | Both | **RETIRE — staged collapse** | Already on Ship O Target E with documented symbol-group order. Under Hunter's accelerated rule we just do all the groups now. End state: this file deleted, all symbols either migrated into brain or gone. |
| `pre_booking_handler.py` (Escapia inquiry polling) | Yes (worker entry) | Yes (brain orchestrator will be called from here) | Both | **ABSORB** | This is the transport layer that pulls inquiries from Escapia. Move to `messaging_brain/integrations/escapia_inbox_poller.py`. Stops calling `process_pre_booking_inquiry`; calls brain orchestrator directly. |
| `proactive/guest_journey.py` (`GuestJourneyService`, `ActivityStatus`, `get_extend_stay_offer`, `get_activity_info`) | Historical as of 2026-05-28 | **Replaced by** `app/services/operator/stay_proactive_runtime.py`, `stay_journey_service.py`, `messaging_brain/proactive_trigger_adapter.py`, `messaging_brain/agents/proactive_outreach_agent.py` | Retired | **DONE** | File deleted on 2026-05-28 after helper logic was re-homed into the canonical operator + brain path. |
| `sms_service.py` | TBD — likely the legacy SMS sender; brain uses `channel_router` | Likely no | No | **RETIRE** if confirmed | Audit-required. |
| `thread_property_inheritance.py` | Yes (used by guest_thread_service) | Yes (called from brain pre-booking lifecycle) | Both | **ABSORB** | Move with `guest_thread_service`. |
| `topic_classifier.py` | Yes (legacy) | **Yes** (brain agents read it) | Both | **ABSORB** | Move to `messaging_brain/intake/topic_classifier.py`. |
| `bd_insight_service.py` (`ConciergeBDInsightService::generate_summary`, `should_generate`) | Yes (`ai_concierge.py`) | No (brain has no BD insight injection yet) | No | **RETIRE** | If brain wants the velocity-nudge feature, absorb it then. For now BD-insight is a legacy concierge feature and ai_concierge is the only caller. |
| `conversation_history_service.py` | TBD | TBD | TBD | **ABSORB or RETIRE** | Audit-required. Likely needed for brain conversation history. |
| `kb_gap_manager.py` | None — already retired per LEGACY_RETIREMENT_PLAN.md item 15 | n/a | n/a | **DELETED ALREADY** | Confirm the file is actually gone (was marked RETIRED). |

### `app/services/operator/`

| Module | Classification | Notes |
|---|---|---|
| `concierge_bridge.py` (re-exports `get_concierge_knowledge_service`) | **RETIRE** | Bridge to legacy. The one caller (`dashboard_summary_service.py`) gets rewired to brain. |
| `dashboard_summary_service.py` (uses `count_dashboard_entries`) | **ABSORB → rewire** | Rewire `count_dashboard_entries` call to the new brain-owned scoped-knowledge service. Same caller, brain target. |
| `prebooking_queue_service.py` | **KEEP-PATH-NEUTRAL** | Operator-side read model for the dashboard. Doesn't sit in the message pipeline. Stays. |
| `stay_workflow_service.py`, `stay_proactive_service.py`, etc. | **KEEP-PATH-NEUTRAL** | Operator-facing workflow read models, distinct concern from guest-message brain pipeline. |
| `historical_thread_evaluator.py` | **KEEP-PATH-NEUTRAL** | Operator tool. Not in guest message flow. |
| `handoff_service.py`, `work_order_service.py` | **KEEP-PATH-NEUTRAL** | Operator workflow side. |

### `app/mcp/servers/`

| Module | Classification | Notes |
|---|---|---|
| `concierge_mcp.py` (the legacy concierge MCP server: `get_property_basics`, `get_session_context`, `check_escalation`, `get_journey_state`, `get_activity_info`, `search_restaurants`, `check_dining_availability`, `create_dining_reservation`, `check_extend_eligible`, `get_faq_answer`, `record_gap`, `find_nearby_available`, `get_proactive_message`) | **RETIRE** | This MCP exists to let the legacy `ai_concierge.py` pipeline call into in-process services as if they were tools. The brain doesn't use MCPs that way — it calls services directly. Delete the whole server. Anything genuinely useful that's not already in the brain gets ABSORBED with the source module. |
| `knowledge_mcp.py` (wraps `LibrarianAgent`) | **AUDIT** | If the brain reads vector knowledge through a different path, retire. If `LibrarianAgent` is canonical, keep but rename out of MCP. |
| `detector_mcp.py`, `eq_mcp.py`, `governance_mcp.py`, `neighborhood_intel_mcp.py`, `pms_mcp.py`, `sanitizer_mcp.py`, `scraper_mcp.py`, `signal_mcp.py` | **AUDIT** | Each needs a "does brain call this, does anyone call this" check before classification. |

### `app/api/v1/endpoints/`

| Endpoint | Classification | Notes |
|---|---|---|
| `concierge.py` (legacy `/concierge/message`, `/concierge/decision`, `concierge_knowledge_coverage`, `import_concierge_knowledge`) | **RETIRE** | Replaced by `/c/{token}/chat` (mobile_v3) and brain channel router. |
| `voice.py` (`/voice/concierge` non-prod) | **RETIRE** | NON-PROD endpoint, easy delete. |
| `operator_dashboard_api.py` (KB CRUD endpoints) | **REWIRE** | Endpoints stay, but they call the brain-owned scoped-knowledge service instead of `ConciergeKnowledgeService`. |
| `admin_seed.py` (writes to `concierge_knowledge` table) | **REWIRE** | The Beach Habitats seed already ran. Delete the `concierge_knowledge` write block; keep the `properties` block. Future seeds write to `concierge_scoped_knowledge` only. |
| `audit.py` | **already brain-side** | Latest v4/v5 patches already query `concierge_scoped_knowledge`. Once `concierge_knowledge` is dropped, the dual-table code paths simplify. |
| `mobile_v3.py`, `messaging_webhooks.py` | **already brain-side** | Confirmed clean from prior audit. |
| `mobile_v2.py`, `phone.py`, `sms.py` | **AUDIT** | SHIP_O Target B (`VoicePod.respond`) territory. Need to verify each has been moved to `run_session_channel_message` already. |
| `knowledge.py` (`/knowledge/voice-pod/test`, `/knowledge/retrieve`, `/knowledge/index/*` deprecated) | **AUDIT** | Most index endpoints already return 410. Voice-pod test endpoint goes with VoicePod retirement. |

---

## Table inventory

| Table | Status | Notes |
|---|---|---|
| `concierge_knowledge` (legacy Q&A schema) | **DROP** | The drift source. Delete after migrating any remaining writes off it. |
| `concierge_scoped_knowledge` | **KEEP — canonical** | The brain-owned KB table. All reads and writes go here. |
| `concierge_knowledge_gaps` | **KEEP — canonical** | Gap recorder writes here. Brain's `knowledge_gap_agent` reads here. |
| `concierge_global_faq` | **KEEP — canonical** | Cross-property FAQ store. Used by brain FAQ retrieval. |
| `concierge_maintenance_events` | **KEEP if brain uses, else AUDIT** | If `messaging_brain/agents/maintenance_agent.py` reads it, keep. If only the legacy maintenance service touches it, drop. |
| `concierge_guest_sessions` | **KEEP — canonical** | Session row. Brain uses via `session_channel_adapter`. |
| `concierge_guest_journeys`, `concierge_journey_activities` | **KEEP — canonical** | Brain proactive uses these. |
| `concierge_messages` | **KEEP — canonical** | Brain conversation history. |
| `concierge_notifications` | **AUDIT** | Need to confirm brain uses this and not a different table. |
| `concierge_escalations` | **AUDIT** | If brain's escalation_agent writes here, keep. Otherwise migrate to a brain-owned escalations table. |
| `pre_booking_inquiries`, `message_normalizations` | **KEEP — canonical** | Operator-facing queue. Brain owns the writes. |
| `operator_learned_preferences`, `operator_draft_events`, `platform_learning_events`, `platform_intelligence` | **KEEP — canonical** | Operator-learning data. Brain owns. |
| `concierge_dining_reservations` | **DROP** if dining service retires | If `dining_service.py` is RETIRE-classified, this table goes with it. |
| `gate_code_deliveries` | **KEEP if gate-code intercept absorbs into brain** | Audit log. |
| `kb_gaps`, `operator_gap_settings` | **CONFIRM ABSENT** | `kb_gap_manager.py` was supposed to write here but the tables don't exist in production. Confirm no migration ever created them and clean up the migration history if needed. |

---

## Recommended execution order

The retirement plan's verification windows are bypassed. Each delete is verified by `rg` for call sites and a focused smoke test on the brain path. Order is chosen to minimize risk of breaking the production path while in flight.

### Ship 1 — Dead code cleanup (zero risk)
1. Delete `db_session_manager.py` (references models that don't exist; broken on import).
2. Delete `db_service.py::ConciergeSessionStore` (in-memory dict; superseded).
3. Delete `kb_gap_manager.py` if not already gone.
4. Confirm `kb_gaps` and `operator_gap_settings` migrations are absent or revert them.

This ship has no behavior change.

### Ship 2 — Schema drift fix (knowledge service into brain)
This is the high-priority work because it ends the drift you keep hitting.

1. Create `app/services/messaging_brain/knowledge/scoped_knowledge_service.py` — brain-owned, reads/writes `concierge_scoped_knowledge` only. Methods: `list_for_property`, `count_for_tenant`, `record_gap` (delegates to `gap_recorder` below), `list_dashboard_entries`, `create_dashboard_entry`, `update_dashboard_entry`, `delete_dashboard_entry`, `test_dashboard_question`, `best_faq_answer`, `import_records`.
2. Create `app/services/messaging_brain/knowledge/topic_registry.py` — move `TOPIC_REGISTRY` constant from legacy.
3. Create `app/services/messaging_brain/knowledge/gap_recorder.py` — move `record_gap_async`, `schedule_gap_record`. Writes go to `concierge_knowledge_gaps`.
4. Rewire all brain imports of `app.services.concierge.knowledge_service` → `app.services.messaging_brain.knowledge.scoped_knowledge_service`. Specifically: `messaging_brain/agents/context_builder_agent.py:73-74`.
5. Rewire `endpoints/operator_dashboard_api.py` (11 hits + raw SQL block at L859–902) to the new brain service. Raw SQL block deleted in favor of service calls.
6. Rewire `endpoints/concierge.py` legacy admin endpoints (`import_concierge_knowledge`, `concierge_knowledge_coverage`) — these get deleted in Ship 4, but stub them to call the brain service in the meantime if they still need to function.
7. Rewire `mcp/servers/concierge_mcp.py::_get_faq_answer` and `_record_gap` to the new brain service. (These go away with Ship 4 anyway, but they need to work in the meantime so the legacy `/concierge/message` flag-off doesn't crash before its own retirement.)
8. Rewire `operator/dashboard_summary_service.py` to import the brain scoped-knowledge service directly. Delete `operator/concierge_bridge.py`.
9. Delete `endpoints/admin_seed.py` legacy `concierge_knowledge` INSERT/UPDATE blocks. Beach Habitats data already seeded; no re-seed needed. Future seeds use brain service.
10. Migration: drop the `concierge_knowledge` table.
11. Delete `app/services/concierge/knowledge_service.py`.
12. Delete `db/models/concierge_knowledge.py::ConciergeKnowledgeModel` (keep `ConciergeKnowledgeGapModel`, `ConciergeGlobalFAQModel`, `ConciergeMaintenanceEventModel` — those are still canonical until separately audited).
13. Remove `ConciergeKnowledgeService` and `get_concierge_knowledge_service` from `app/services/concierge/__init__.py::_EXPORTS`.

End state: one KB table, one KB service, brain-owned, no drift.

### Ship 3 — Cross-cutting "dual caller" absorptions
Each is a small, focused commit.

1. Move `context_builder.py` → `messaging_brain/context/prebooking_context.py`. Rewire brain and legacy imports.
2. Move `hallucination_guard.py` → `messaging_brain/grounding/hallucination_guard.py`.
3. Move `response_reviewer.py` → `messaging_brain/grounding/response_reviewer.py`. Rewire `email_dispatch.py` placeholder check to import from brain.
4. Move `operator_guidance.py::load_operator_guidance` → `messaging_brain/context/operator_guidance.py`.
5. Move `knowledge_topic_registry.py` (already done in Ship 2 above).
6. Move `property_context.py` → `messaging_brain/context/property_context.py`.
7. Move `db_session_service.py` → `messaging_brain/sessions/session_service.py`. Update `mobile_v3.py` and any other caller imports.
8. Move `guest_thread_service.py` → `messaging_brain/sessions/guest_thread.py`.
9. Move `inquiry_persistence.py` → `messaging_brain/pre_booking_persistence.py`.
10. Move `operator_learning.py` → `messaging_brain/learning/`.
11. Historical note: this proposed move was superseded by the 2026-05-28 cleanup. The old file was deleted and its useful helper logic re-homed into `app/services/operator/stay_journey_service.py`; runtime ownership moved to `stay_proactive_runtime.py`.
12. Move `market_brain.py` + `market_source_adapters.py` → `messaging_brain/context/market_brain.py`.
13. Move `topic_classifier.py` → `messaging_brain/intake/topic_classifier.py`.
14. Move `message_history.py` → `messaging_brain/integrations/escapia_history.py`. Rewire FAQ write target to brain scoped-knowledge service.
15. Move `pre_booking_handler.py` → `messaging_brain/integrations/escapia_inbox_poller.py`. Change its inquiry-processing call from `process_pre_booking_inquiry` → brain orchestrator entry.
16. Move `escapia_unified.py::GateCodeService` → `messaging_brain/integrations/escapia_gate_code.py`. Delete the rest of `escapia_unified.py` (overlap with brain's pre-booking dispatch).
17. Move `portfolio_availability_service.py` → `messaging_brain/portfolio/availability.py`. Fold into `portfolio_matching_agent` if natural.
18. Move `guidebook_ingest_service.py` → `app/services/ingestion/guidebook_ingest.py`. Updates writes to `concierge_scoped_knowledge`.

### Ship 4 — Retire the legacy concierge runtime entirely
1. Delete `endpoints/concierge.py` (all of it — `/concierge/message`, `/concierge/decision`, `concierge_knowledge_coverage`, `import_concierge_knowledge`). The flag-off compatibility we lose: explicit accept that brain is the only runtime now.
2. Delete `endpoints/voice.py` (non-prod).
3. Delete `app/services/concierge/concierge_runner.py` and `app/services/orchestration/concierge_runner.py` (re-export shim).
4. Delete `app/services/concierge/ai_concierge.py`.
5. Delete `app/services/concierge/concierge_intelligence.py`.
6. Delete `app/services/concierge/property_router.py`.
7. Delete `app/services/concierge/escalation_service.py` (brain has its own agent).
8. Delete `app/services/concierge/maintenance_service.py` (brain has its own agent).
9. Delete `app/services/concierge/dining_service.py` and the dining MCP tool wiring.
10. Delete `app/services/concierge/event_planning_service.py`.
11. Delete `app/services/concierge/notification_service.py`.
12. Delete `app/services/concierge/guest_session.py` (in-memory; superseded by brain session service from Ship 3).
13. Delete `app/services/concierge/bd_insight_service.py`.
14. Delete `app/services/concierge/intent_classification_escalator.py` (brain has prefilter + LLM intake).
15. Delete `app/services/concierge/operator_bridge.py` (re-export shim).
16. Delete `app/services/concierge/__init__.py::_EXPORTS` for everything just deleted. The remaining exports (if any) go to brain.
17. Delete `app/mcp/servers/concierge_mcp.py`. Update `app/mcp/registry.py` to remove the registration.

### Ship 5 — Retire `pre_booking_auto_send.py`
Already documented in `SHIP_O_TARGET_E_SYMBOL_GROUPS.md`. Under accelerated rule, do all symbol groups in one push:
1. Group 1: portfolio/pricing/grounded-fallback/verification helpers. The brain has all four agents already. Delete.
2. Group 2: knowledge-gap internals. Brain has `knowledge_gap_agent`. Delete.
3. Group 3: policy/send-decision. Brain has `response_policy_agent` and `platform_compliance`. Delete.
4. Group 4: LLM provider orchestration and grounding. Brain has `prebooking_llm_draft_agent`. Delete.
5. Groups 5+6: helpers moved out in Ship 3.
6. Group 7: orchestration shell. `messaging_brain/pre_booking_lifecycle.py` stops calling `PreBookingPipelineOrchestrator`, calls brain orchestrator directly. Delete `process_pre_booking_inquiry`, `process_pre_booking_inquiry_with_draft`, `PreBookingPipelineOrchestrator`.
7. Delete `app/services/concierge/pre_booking_auto_send.py`.

### Ship 6 — Final cleanup
1. `app/services/concierge/__init__.py` reduced to only path-neutral exports (likely none — the dir gets deleted entirely if nothing remains).
2. Delete `app/services/concierge/` if empty.
3. Update `LEGACY_RETIREMENT_PLAN.md` — everything flips to RETIRED. Or replace the doc with a short note pointing to this audit.
4. Search the whole repo for `from app.services.concierge` imports. Should be zero.
5. Search for any remaining `concierge_knowledge` references (table or class name). Should be zero.

---

## Open audit items

Things I didn't read deeply enough to classify with certainty in this pass:

- `app/services/concierge/group_session.py` — likely RETIRE, need to confirm zero brain calls.
- `app/services/concierge/post_booking_routing.py` — purpose unknown from this pass.
- `app/services/concierge/sms_service.py` — likely RETIRE (brain uses `channel_router`), confirm.
- `app/services/concierge/conversation_history_service.py` — likely brain-side, confirm.
- `app/services/concierge/guest_profile_service.py` — repeat-guest memory; confirm brain uses it.
- `app/services/concierge/thread_property_inheritance.py` — confirm caller graph.
- `app/services/concierge/maintenance_service.py` — confirm brain's `MaintenanceAgent` doesn't import it; if it does, ABSORB instead of RETIRE.
- `app/services/concierge/escalation_service.py` — confirm brain's `EscalationAgent` is fully independent.
- `app/mcp/servers/` (other than concierge_mcp and knowledge_mcp) — full audit pass needed.
- `app/api/v1/endpoints/mobile_v2.py`, `phone.py`, `sms.py` — confirm `VoicePod.respond` removal status.
- `db/models/concierge_escalations.py`, `concierge_dining_reservations.py` — confirm whether the brain reads these tables.

Each of these should be resolved before the corresponding Ship runs. None of them block Ship 1 or Ship 2.

---

## Database layer note

There is no second "legacy database layer" still active. The system uses:
- `app/db/session.py` for the async session factory (one engine, one factory).
- `db/models/*` for ORM models (`Base` from `db.models.core`).
- `app/models/*` for newer SQLAlchemy 2.0-style models (`Base` from `app.models.base`).

The split between `db/models/` and `app/models/` is messy but they hold different tables, not duplicate tables, and both use the same `app/db/session.py` engine. There's nothing to remove at the DB layer itself — the cleanup is at the model/service level and is covered above.

The only "dead DB-layer" finding is `app/services/concierge/db_session_manager.py`, which references model classes that don't exist (`ConciergeSessionModel`, `ConciergeMessageLogModel`, `ConciergeEscalationModel`). That's the file that gets deleted in Ship 1.

---

## What this audit explicitly throws away

- The `SHIP_O_DELETION_INVENTORY_2026-05-20.md` verification windows. We delete now and watch production.
- The `LEGACY_RETIREMENT_PLAN.md` "out of scope" list. Everything is in scope.
- The phased 4.5.A-G migration sequencing for the inside of `pre_booking_auto_send.py`. We treat the whole file as deletable once Ship 3 finishes the helper extractions.
- The "shared utility" category as a stable end state. Modules are either brain or gone.

What it does **not** throw away:
- The data in `concierge_scoped_knowledge`, `concierge_knowledge_gaps`, `concierge_global_faq`, and the other canonical tables.
- The Beach Habitats production traffic. Brain is already serving it via `mobile_v3.py` → `run_session_channel_message`. The retirements below remove dual paths, not the live brain path.
- The Phase 4.5.A-G migration *work product*. Brain agents (`deterministic_intake_prefilter`, `llm_composer_agent`, `pricing_policy_agent`, `portfolio_matching_agent`, `grounded_fallback_agent`, `verification_hold_agent`, `knowledge_gap_agent`, `response_policy_agent`) all exist. Ship 5 is just the deletion that closes out the migration the brain already did.
