# Foundation Rebuild — Scale Acceptance Criteria

**Target:** 100,000 properties across 1,000 operators  
**Status:** Authoritative for all foundation rebuild phases

This document is the gate. No phase is considered complete until every applicable criterion below is verified. If a criterion cannot be satisfied, that's not "ship and iterate" — that's a blocker that gets addressed in this phase or explicitly carried forward with an issue/ADR.

Every PR that touches operational code paths must reference this document and state which criteria it satisfies or impacts.

## Why this exists

We have a pattern of "this works at 45 units, ship it." That pattern got us into the drift situation we're rebuilding out of. Multi-tenancy, indexing, and connection management decisions made for one operator do not survive 1000. By codifying acceptance criteria up front, we stop re-discovering scale issues retroactively.

## Category A: Tenant isolation (every operational query)

**A1.** Every SQL query that reads or writes operational data MUST be scoped by `tenant_id` in the WHERE clause. No queries that scan across tenants except for explicit super-admin endpoints.

**A2.** Every operational table MUST have `tenant_id` as the leading column of at least one index used by the dominant query patterns for that table.

**A3.** No code path may use one operator's data to satisfy another operator's request. Includes caches: `tenant_id` must be part of any cache key.

**A4.** No environment variable based per-operator configuration. All operator-scoped configuration lives in the database, keyed by `tenant_id`. Existing `GMAIL_REFRESH_TOKEN_{CODE}` style env vars must be retired before scale work is considered complete.

## Category B: Indexing for scale

**B1.** Every dashboard read query MUST execute in `<200ms p95` against a table populated with the equivalent of 10,000 rows per operator and 100 active operators (1M rows total).

**B2.** Every hot-path lookup (canonical property resolution, dedup checks, message normalization writes) MUST use a covering index. `EXPLAIN ANALYZE` shows index scan, not seq scan.

**B3.** Required indexes on operational tables (verify present before phase complete):

- `pre_booking_inquiries (tenant_id, status, created_at DESC)`
- `pre_booking_inquiries (tenant_id, gmail_thread_id)` where `reply_via_gmail = true`
- `concierge_guest_sessions (tenant_id, guest_email)` for active sessions
- `concierge_guest_sessions (tenant_id, check_out) WHERE status NOT IN ('expired','closed')`
- `message_normalizations (tenant_id, source_message_id)` UNIQUE
- `message_normalizations (tenant_id, property_id, sent_at DESC)`
- `operator_prebooking_queue_read_models (tenant_id, status, updated_at DESC)`
- `operator_prebooking_queue_read_models (tenant_id, property_id)`
- `canonical_property_refs (tenant_id, normalized_ref_value)`
- `canonical_property_refs (property_id)`
- `properties (tenant_id, property_code)` UNIQUE
- `properties (tenant_id, status, retired_at)`
- `llm_usage_events (tenant_id, created_at DESC)`
- `gmail_processed_messages (operator_id, processing_status, processed_at DESC)`
- `property_ingest_events (tenant_id, created_at DESC)`

**B4.** Fuzzy matching (`ILIKE`, `LIKE` with leading wildcard, `LOWER` on dynamic columns) is BANNED on hot-path queries. Required matches must use trigram indexes (`pg_trgm` GIN/GIST) or normalized lookup columns indexed exactly.

**B5.** No `information_schema` queries on hot paths. Schema must be deterministic after Phase 8. Runtime schema introspection patterns (`_table_columns`, `_table_exists`) must be removed.

## Category C: Partitioning and retention

**C1.** Time-series tables MUST be partitioned by month or week before they exceed 10M rows projected. Identified tables:

- `message_normalizations` — partition by month
- `gmail_processed_messages` — partition by month
- `llm_usage_events` — partition by week or month
- `parser_pattern_observations` (Phase 5) — partition by month
- `healing_events` (Phase 5) — partition by month
- `property_ingest_events` — partition by month

**C2.** Retention policy MUST be defined for every event/audit table. Default: 90 days hot, 1 year warm, archive or aggregate beyond.

**C3.** Dashboard queries MUST read only recent partitions (last 30 days) unless explicitly requested. Historical views use separate code paths that scan archive partitions.

## Category D: Connection and concurrency

**D1.** Every async DB session MUST roll back cleanly on exception before returning. The May 2026 aborted-transaction poisoning pattern must not regress. Either:

- Use `_safe_rollback` pattern consistently in except clauses, OR
- Use SQLAlchemy session context managers that auto-rollback

**D2.** Connection pool sizing MUST account for 1000 operators with peak concurrency:

- Worker processes × max connections per worker × replicas
- PgBouncer/Supabase pooler configuration documented
- Connection acquisition timeout configured (default fail-fast, not wait forever)

**D3.** No long-running transactions in operational code paths. Operations that touch multiple tables MUST commit between phases or use savepoints. Specifically: brain pipeline (intake → context → agents → policy → compose → dispatch → audit) cannot hold one transaction the whole way.

**D4.** Background jobs (polling, queue sync, healing) MUST use a job queue with concurrency controls. Cannot rely on "everyone polls every 5 minutes" — needs:

- Per-operator polling staggered to avoid thundering herd
- Per-tenant rate limits on expensive operations (LLM calls, vector index)
- Retry with exponential backoff for transient failures
- Dead-letter queue for permanently failing jobs

## Category E: Cost control

**E1.** Per-tenant LLM cost MUST be tracked in `llm_usage_events` for every call. No untracked LLM invocations.

**E2.** Cost guard MUST alert when:

- Any operator's daily LLM spend exceeds `$1.00` (tunable per plan)
- System-wide hourly spend deviates `>50%` from rolling baseline
- Single tenant's hourly spend exceeds expected pattern by `>3x`

**E3.** Tiered processing discipline:

- Tier 0 (deterministic non-guest filtering) MUST handle `≥70%` of traffic with zero LLM cost
- Tier 1 (parser pattern cache) MUST handle `≥20%` of remaining traffic with zero LLM cost (target after Phase 5)
- Tier 2 (cheap LLM — Groq for routine extraction) MUST handle `≥80%` of remaining LLM-required traffic
- Tier 3 (Anthropic) used only when Tier 2 declines or returns low confidence
- Tier 4 (agent healing) used only when patterns truly novel — rate-limited per tenant

**E4.** LLM call retry policy MUST be bounded. No infinite retries. Failures count against monthly budget but don't compound.

**E5.** Vector embeddings (`knowledge_embeddings` writes) MUST be batched. No per-property re-embedding on import; only delta updates.

## Category F: Self-service onboarding (no engineering touchpoints)

**F1.** A new operator MUST be able to complete signup → inbox connection → property data upload → first message processed without any engineering intervention.

**F2.** Property upload flow MUST handle:

- Unknown columns (preserved in metadata, surfaced for mapping review)
- Missing required fields (clear validation errors, not silent failures)
- Duplicate detection across name/address variants (operator confirms or merges)
- Multi-source attribution (operator-provided > PMS > scraped > guidebook)

**F3.** Operator MUST have UI to manage:

- Property records (add/edit/retire, never delete)
- Canonical aliases (marketing names, OTA IDs, address variants)
- Source authority preferences (which source wins per attribute)
- Conflict resolution (when sources disagree)

**F4.** Onboarding flow MUST be measurably testable end-to-end:

- Smoke test simulating new operator signup + property load + inbound message
- Test runs in CI without external dependencies (mock Gmail, mock LLM)
- Failure of smoke test blocks deploys

## Category G: Failure isolation

**G1.** A failure for one operator MUST NOT affect any other operator. Verified by:

- Polling errors caught per-operator, don't propagate
- Brain pipeline exceptions don't poison shared state
- One operator's runaway costs don't starve others' LLM quota
- Schema drift for one tenant doesn't crash queries for others

**G2.** Silent failures are BANNED on operational paths. Specifically:

- No `try: ... except Exception: pass` without logging at WARNING or ERROR
- No `return 0` / `return None` / `return {}` on swallowed exception without surfaced metric
- Schema mismatches MUST raise (after Phase 8), not silently degrade

**G3.** Dashboard "X count" displays MUST reflect actual data state. No catches that silently return 0 when the underlying query fails. If the query can't run, the UI shows an error, not a wrong number.

**G4.** Reply send failures MUST be visible to operators. No silent failures on guest reply send.

## Category H: Schema integrity

**H1.** Production schema MUST be fully described by migrations. No tables, columns, or indexes created at runtime by service code.

**H2.** Migration round-trip MUST pass on every release:

- Fresh DB + run all migrations = schema matches production snapshot
- Verified in CI before deploy

**H3.** Schema expectations MUST be code-owned and verified at startup:

- Services declare expected tables/columns
- Startup health check verifies, fails loud on mismatch
- Boot does NOT silently fall back to defensive patching

**H4.** Schema changes ALWAYS via migration. No ad-hoc `ALTER TABLE` in service code. The `MIGRATION_SQL` strings in service files must be retired after Phase 8.

## Category I: Multi-source data reconciliation

**I1.** Every property attribute that can come from multiple sources MUST carry source attribution:

- `value`, `source`, `source_authority`, `last_verified_at`, `confidence`

**I2.** When sources disagree, the system MUST:

- Surface the conflict via `property_conflicts` table
- Apply per-attribute authority rules deterministically
- Never silently overwrite higher-authority data with lower-authority data

**I3.** Beach Habitats's 37+ known conflicts (bedroom/bathroom mismatches across guidebook/spreadsheet/website/VRBO) MUST resolve cleanly under new architecture. Verified by end-to-end test against actual production data sample.

## Category J: Self-healing layer

**J1.** Parser format drift MUST trigger candidate pattern generation (not blind LLM fallback for every message).

**J2.** Agentic resolutions MUST be auditable via `healing_events` ledger. Every autonomous action logged with:

- `trigger`, `input`, `action`, `outcome`, `confidence`, `approved_by`

**J3.** Autonomy tiers MUST be enforced in code:

- Auto-apply: parser candidate promotion after history validation, freshness updates
- Human approval: schema migrations, canonical alias additions, substantive property fact changes
- Never autonomous: guest comms, deletions, overriding operator decisions

**J4.** Confidence thresholds MUST be tunable per-tenant. Some operators will trust auto-resolution more than others.

## Category K: Observability at scale

**K1.** Every operational event MUST emit structured logs with `tenant_id`, `operator_id`, and a correlation ID.

**K2.** Per-tenant dashboards MUST exist for Oyvoda staff:

- Inbound volume, processed/failed counts
- LLM cost per tenant per day
- Unbound inquiry rate
- Conflict resolution backlog
- Healing event activity

**K3.** Alerts MUST fire on:

- Per-tenant cost anomaly (Category E2)
- Per-tenant error rate spike (`>5x` baseline)
- Schema integrity check failure
- Migration round-trip failure
- DLQ backlog growth

## How to use this document

### For each phase of foundation rebuild (Phase 2-10)

1. At phase kickoff, list which criteria are in-scope for the phase.
2. At phase completion, verify each in-scope criterion is satisfied.
3. Note any criteria that are deferred to later phases (with reason).
4. PR description references criteria addressed.

### For ongoing work after rebuild

Any PR that touches operational code paths must self-certify against the relevant criteria. Reviewers reject PRs that introduce violations.

### For Hunter and Claude

When considering an architectural decision, the test is: "Does this work at 100k units / 1000 operators?" If the answer is "yes" — proceed. If "probably" or "with caveats" — find the specific criterion at risk and address it.

## Phase mapping (which criteria each phase satisfies)

**Phase 2 (Migration recovery):** `H1`, `H2` partial  
**Phase 3 (Tenant identity normalization):** `A1`, `A2`, `A3`, `A4`  
**Phase 4 (Property entity rebuild):** `B3` (property indexes), `I1`, `I2`  
**Phase 5 (Parser pattern registry):** `E3`, `J1`, `J2` partial, `C1` partial  
**Phase 6 (Onboarding consolidation):** `F1`, `F2`, `F3` partial, `F4`  
**Phase 7 (Source attribution + agent layer):** `I1`, `I2`, `I3`, `J2`, `J3`, `J4`  
**Phase 8 (Schema integrity):** `H3`, `H4`, `B5`, `G2`, `G3`  
**Phase 9 (Beach Habitats de-hardcoding):** `A4`, `G1`  
**Phase 10 (End-to-end verification):** Re-verify all categories

**Cross-phase (must be addressed throughout):**

- `D1` (rollback discipline) — every phase that touches DB code
- `E1`, `E2` (cost tracking) — every phase that touches LLM code
- `G2` (no silent failures) — every phase
- `K1` (structured logging) — every phase

## Current state assessment (as of foundation rebuild start)

### Already meets criteria

- `A1` partial: most queries use `tenant_id`, some use `company_id` (Phase 3 normalizes)
- `B3` partial: `canonical_property_refs` unique index exists, some others
- `E1`: `llm_usage_events` captures every call (Phase G observability work)
- `E3`: tiered processing partly in place (Phase A/B/C parsing)

### Known violations to address

- `A4`: `GMAIL_REFRESH_TOKEN_{CODE}` env var pattern still in `build_gmail_poller`
- `B4`: `ILIKE` fuzzy matching in `_find_active_session` and `property_canonical_service` name fallback
- `B5`: `_table_columns()` and `_table_exists()` patterns throughout `gmail_inbox_poller.py`
- `C1`: no partitioning anywhere
- `D3`: brain pipeline holds one session for full pipeline
- `E2`: no cost alerting yet
- `F3`: no operator property management UI
- `G2`: `try/except: pass` patterns in multiple services
- `H1`: defensive runtime patching in `gmail_inbox_poller.py`, `property_import_service.py`, others
- `H3`: no startup schema integrity check
- `I1`: property attributes lack source attribution
- `I2`: no conflict surfacing
- `J1`, `J2`, `J3`, `J4`: self-healing layer doesn't exist yet

This list represents the actual gap between current state and scale readiness. Foundation rebuild phases address it systematically.
