# Foundation Rebuild Phase 2: Drift Matrix and Reconciliation Plan

**Status:** Read-only audit artifact  
**Date:** 2026-05-14  
**Scope:** Production-vs-migration drift matrix, runtime patch categorization, and reconciliation migration planning

## Purpose

Phase 2 is not a schema redesign. It is the recovery step that makes the existing migration tree trustworthy again before Phases 3-10 start changing identity and property semantics.

This document answers three questions:

1. Which production tables are already described by `db/migrations`?
2. Where does production differ from what the migration tree claims?
3. Which runtime DDL patches still represent unreconciled schema behavior?

## Current Migration Reality

The active migration system is:

- `alembic.ini` → `db/migrations`
- active env → [env.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/env.py)
- active versions directory → [db/migrations/versions](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions)

Observed repo state:

- `66` files exist under `db/migrations/versions`
- current repo head is `063_llm_usage_events`
- `alembic heads` reports a single head:
  - `063_llm_usage_events`

Important correction from the earlier audit:

- the repo does have a real migration tree
- the stray [001_create_signals.py](/Users/dhuntermckenzie/Downloads/oyvoda/alembic/versions/001_create_signals.py) under `alembic/versions` is a stale artifact, not the active migration system

## Classification Legend

### Covered cleanly

Migration chain exists and production shape matches what the migration chain appears to define.

### Covered with drift

Migration chain exists, but there is a meaningful mismatch between production and what the migrations claim or imply.

### Runtime-origin but adopted

Table or columns originally came from runtime DDL, but later migrations explicitly adopted them into Alembic. Production and current migrations now broadly align.

### Runtime-only

Production/runtime behavior depends on schema mutation or creation that is not represented in the active migration tree.

### Orphaned / stale artifact

Migration artifact, runtime SQL, or schema assumption exists outside the active path and should not be treated as authoritative.

## Drift Matrix: Core Operational Tables

| Table | Migration coverage | Classification | Notes |
|---|---|---|---|
| `properties` | [003_create_properties.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/003_create_properties.py) | Covered cleanly | Production columns match the 64-column property canonical table shape created in `003`, including `tenant_id`, `property_code`, address fields, amenities, data-quality fields, and `property_guide_url`. |
| `canonical_property_refs` | [057_canonical_property_runtime_tables_to_alembic.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/057_canonical_property_runtime_tables_to_alembic.py) | Runtime-origin but adopted | Originally runtime-created; later adopted into Alembic. Production shape matches the adopted code-keyed design. Architectural weakness remains: keyed by `canonical_property_code`, not `property_id`, but that is a Phase 4 redesign issue, not Phase 2 drift. |
| `canonical_property_profiles` | [057_canonical_property_runtime_tables_to_alembic.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/057_canonical_property_runtime_tables_to_alembic.py) | Runtime-origin but adopted | Same pattern as refs: production matches the adoptive migration; semantic redesign deferred to Phase 4. |
| `pms_listings` | [018_pre_booking_pipeline.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/018_pre_booking_pipeline.py) | Covered cleanly | Production columns align with the migration-defined table. Table is mostly dormant (`0` rows in earlier audit), but it is not drifted. |
| `companies` | [018_pre_booking_pipeline.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/018_pre_booking_pipeline.py) | Covered cleanly | Production shape matches migration. Operationally dormant and no longer the real tenant anchor, but not a migration drift issue. |
| `operator_accounts` | [019_operator_auth.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/019_operator_auth.py) | Covered cleanly | Production includes the richer shape with `stripe_customer_id` and `stripe_subscription_id`, matching migration. |
| `operator_gmail_creds` | [019_operator_auth.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/019_operator_auth.py), [058_operator_gmail_creds_runtime_columns.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/058_operator_gmail_creds_runtime_columns.py) | Runtime-origin but adopted | Base table in `019`, poll-heartbeat fields adopted in `058`. Production matches current Alembic shape. |
| `pre_booking_inquiries` | [018_pre_booking_pipeline.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/018_pre_booking_pipeline.py), [021_runtime_tables_to_alembic.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/021_runtime_tables_to_alembic.py), [049_guest_threads_and_module_flags.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/049_guest_threads_and_module_flags.py), [056_prebooking_runtime_columns_to_alembic.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/056_prebooking_runtime_columns_to_alembic.py) | Runtime-origin but adopted | Production shape reflects base pipeline table plus later adopted Gmail/thread/parser fields. Covered, but still semantically tied to `company_id` and `property_external_id`; that is a Phase 3/4 transformation, not Phase 2 drift. |
| `gmail_processed_messages` | [021_runtime_tables_to_alembic.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/021_runtime_tables_to_alembic.py), [062_gmail_processed_message_statuses.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/062_gmail_processed_message_statuses.py) | Runtime-origin but adopted | Base runtime table adopted in `021`; retry/status columns adopted in `062`. Production matches. |
| `message_normalizations` | [036_message_normalizations.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/036_message_normalizations.py), [054_message_normalizations_composer_metadata.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/054_message_normalizations_composer_metadata.py) | Covered cleanly | Production includes the composer audit fields added in `054`. |
| `operator_prebooking_queue_read_models` | [039_operator_prebooking_queue_read_models.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/039_operator_prebooking_queue_read_models.py), [050_prebooking_queue_guest_thread.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/050_prebooking_queue_guest_thread.py) | Covered cleanly | Production includes `guest_thread_id` and matches the read-model lineage. |
| `operator_feature_flags` | [018_pre_booking_pipeline.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/018_pre_booking_pipeline.py) | Covered cleanly | Matches migration. Still `company_id`-keyed by design; identity normalization happens later. |
| `operator_settings` | [026_dashboard_tables.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/026_dashboard_tables.py) | Covered cleanly | Production shape and primary key match migration. |
| `operator_portfolios` | [040_operator_scope_foundation.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/040_operator_scope_foundation.py) | Covered cleanly | Present in production and structurally aligned, even though it currently has `0` rows. |
| `operator_portfolio_properties` | [040_operator_scope_foundation.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/040_operator_scope_foundation.py) | Covered cleanly | Same pattern as portfolios: migrated, present, largely dormant. |
| `llm_usage_events` | [063_llm_usage_events.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/063_llm_usage_events.py) | Covered cleanly | Newest migration and production target align. |
| `concierge_guest_sessions` | [008_concierge_sessions.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/008_concierge_sessions.py), [013_session_operator_reservation.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/013_session_operator_reservation.py), [015_concierge_session_pms_synced_at.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/015_concierge_session_pms_synced_at.py), [018_pre_booking_pipeline.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/018_pre_booking_pipeline.py), [021_runtime_tables_to_alembic.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/021_runtime_tables_to_alembic.py), [049_guest_threads_and_module_flags.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/049_guest_threads_and_module_flags.py) | **Covered with drift** | This is the highest-signal migration integrity problem found so far. The original migration defines `property_id` with FK to `properties.property_id`, but the canonical `properties` table uses `id`, not `property_id`. Production also contains later additive fields (`company_id`, `property_external_id`, `booking_channel`, `group_join_token`, `group_member_count`, `guest_thread_id`) from subsequent migrations and runtime patches. This table is migration-covered, but the chain is internally inconsistent and must be corrected before we trust round-trips. |

## Additional Notes on the Matrix

### Most core inbox/operator tables are not “missing from migrations”

That is the biggest positive finding in Phase 2 so far.

For the live operator path, the pattern is usually one of:

- properly migrated from the start
- runtime-created originally, then later explicitly adopted into Alembic

This is materially better than a greenfield reconstruction problem.

### Round-trip harness status

The round-trip effort has already surfaced real historical migration bugs:

- `003_create_properties`
  - duplicate enum creation behavior on fresh DBs
  - duplicate `ix_properties_tenant_id` creation via `index=True` plus explicit `op.create_index(...)`
- `011_concierge_escalations`
  - incorrect `down_revision` that bypassed `010_operator_policies_markets`

Those have now been corrected in the migration tree.

The next blocker was not a migration bug; it was a local harness gap:

- `009_knowledge_embeddings` requires the `vector` extension
- production extensions currently include:
  - `pg_stat_statements`
  - `pgcrypto`
  - `plpgsql`
  - `supabase_vault`
  - `uuid-ossp`

For the migration tree itself, the required extension set is narrower:

- `pgcrypto`
- `uuid-ossp`
- `vector`

To make Phase 2 repeatable, the repo now includes a dedicated Docker-based harness at [migration_roundtrip.sh](/Users/dhuntermckenzie/Downloads/oyvoda/scripts/migration_roundtrip.sh) that targets `pgvector/pgvector:pg15`, bootstraps the required extensions, runs `alembic upgrade head`, and compares the resulting schema to the production snapshot when available.

### The biggest remaining schema-integrity problem is not absence but inconsistency

The highest-risk example is `concierge_guest_sessions`:

- migration lineage exists
- production table exists
- later migrations assume it exists
- but the original FK contract does not match the actual `properties` primary key shape

This is exactly the class of problem that a migration round-trip harness must catch.

## Runtime Patching Categories

Phase 1 found three different categories of defensive runtime schema behavior. They should not all be treated the same.

### Category A: Runtime-origin schema that has already been adopted into Alembic

These should remain in service code only until Phase 8 removes the defensive compatibility paths.

Examples:

- `gmail_processed_messages` base table from [021_runtime_tables_to_alembic.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/021_runtime_tables_to_alembic.py)
- `pre_booking_inquiries` Gmail-thread columns from [021_runtime_tables_to_alembic.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/021_runtime_tables_to_alembic.py)
- `pre_booking_inquiries` parser/linkage columns from [056_prebooking_runtime_columns_to_alembic.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/056_prebooking_runtime_columns_to_alembic.py)
- `canonical_property_refs` / `canonical_property_profiles` adoption from [057_canonical_property_runtime_tables_to_alembic.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/057_canonical_property_runtime_tables_to_alembic.py)
- `operator_gmail_creds` heartbeat columns from [058_operator_gmail_creds_runtime_columns.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/058_operator_gmail_creds_runtime_columns.py)
- `gmail_processed_messages` status fields from [062_gmail_processed_message_statuses.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/062_gmail_processed_message_statuses.py)

Interpretation:

- these runtime patches were compensating for migration lag
- the schema is now mostly codified
- the remaining task is to remove service-level fallback logic after round-trip trust is established

### Category B: Runtime patching compensating for a real migration inconsistency

Highest-signal example:

- `concierge_guest_sessions` lineage across `008`, `013`, `015`, `018`, `021`, `049`

Interpretation:

- this is not just a late adoption problem
- the chain itself needs correction so fresh environments can reproduce the live contract safely

### Category C: Runtime-only or sidecar schema outside the core operator foundation

These do not appear to be part of the fully codified operator/onboarding migration tree yet.

Examples:

- [operator_alerts.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging/operator_alerts.py)
  - runtime columns on `operator_alert_contacts`
  - runtime tables `operator_alert_acks`, `operator_alert_log`
- [staged_rollout.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/staged_rollout.py)
  - runtime `property_rollout_phases`, `property_rollout_history`
  - runtime `approval_mode*` column additions
- [conversation_logger.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/voice/conversation_logger.py)
  - runtime `guest_conversations`, `conversation_turns`, `conversation_feedback`
- [market_amenity_attribution.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/analytics/market_amenity_attribution.py)
  - runtime analytics/property enhancement columns like `distance_to_beach_ft`, `view_type`, `pool_type`, `year_renovated`, `interior_quality`

Interpretation:

- these are real runtime schema dependencies
- they are not all in the audited production-table set because several are sidecar systems
- they should be explicitly triaged in reconciliation as either:
  - migrate into the active tree, or
  - quarantine as non-core modules until they can be migrated deliberately

### Category D: Runtime schema probing without mutation

Examples:

- `_table_exists`
- `_table_columns`

These appear throughout:

- queue services
- dashboard endpoints
- scope services
- Gmail poller
- knowledge services

Interpretation:

- these are compatibility shims, not schema-definition mechanisms
- they often exist because the migration tree and service assumptions diverged over time
- once reconciled, they should be removed phase-by-phase in Phase 8

## Reconciliation Migration Set

This is the proposed ordered migration set to make the migration tree authoritative for the current production contract.

These are planning artifacts, not yet implemented migrations.

### R1. `064_reconcile_concierge_guest_sessions_relational_contract`

Purpose:

- fix the `concierge_guest_sessions` lineage so it references the real `properties` key shape
- ensure every production column now present on the table is represented coherently by migrations

Likely work:

- correct property FK contract from stale `properties.property_id` assumption to the real properties key
- verify live additive columns are represented:
  - `pms_synced_at`
  - `property_external_id`
  - `booking_channel`
  - `company_id`
  - `group_join_token`
  - `group_member_count`
  - `guest_thread_id`

Verification queries:

- describe columns and constraints on `concierge_guest_sessions`
- verify FK target points to the actual properties key
- verify indexes expected by sessions/dashboard paths exist

Rollback:

- additive/constraint-replacement only
- no destructive data rewrite in this migration

Drafted implementation notes:

- historical correction applied in [008_concierge_sessions.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/008_concierge_sessions.py) so fresh databases reference `properties.id` instead of the invalid `properties.property_id`
- new reconciliation migration drafted at [064_reconcile_concierge_guest_sessions_relational_contract.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/064_reconcile_concierge_guest_sessions_relational_contract.py)
- `064` explicitly:
  - normalizes the `property_id` foreign key constraint
  - restores expected session indexes for `property_code`, `check_in`, `check_out`, `operator_id`, `reservation_id`, `pms_synced_at`, `company_id/property_external_id`, `group_join_token`, and `guest_thread_id`

### R2. `065_adopt_operator_alert_runtime_schema`

Purpose:

- move operator alert routing support out of runtime DDL and into Alembic

Scope:

- `operator_alert_contacts` runtime-added OOO fields
- `operator_alert_acks`
- `operator_alert_log`

Reason:

- this is operator-facing operational workflow, not an experimental sidecar

Verification queries:

- check columns on `operator_alert_contacts`
- check indexes on ack deadlines/log tables

Rollback:

- drop additive objects only if unused and safe

### R3. `066_adopt_staged_rollout_runtime_schema`

Purpose:

- move staged rollout schema into migrations

Scope:

- `property_rollout_phases`
- `property_rollout_history`
- `approval_mode`, `approval_mode_set_by`, `approval_mode_set_at`

Reason:

- rollout mode affects operator workflow and AI approval behavior, so it belongs in the authoritative tree

Verification queries:

- check rollout tables and indexes
- verify approval mode fields exist with expected defaults

### R4. `067_quarantine_or_adopt_noncore_runtime_modules`

Purpose:

- make an explicit decision on sidecar runtime-only schema rather than leaving it ambiguous

Candidate modules:

- voice conversation logging
- BD/analytics property enhancement schema
- any remaining runtime-created market/amenity tables

Two acceptable outcomes:

1. adopt into active migration tree
2. mark as non-core/deferred and ensure they are not required by boot or core operator workflows

This migration may resolve into more than one file depending on scope separation.

### R5. `068_roundtrip_guardrails_metadata`

Purpose:

- add or document any small metadata pieces needed to make round-trip verification deterministic

This may not require a DB migration at all if handled in test harness/config instead. It is listed here because Phase 2 must end with a reproducible schema-verification workflow, not just a pile of migration files.

## Verification Discipline for Reconciliation Migrations

Every reconciliation migration should have:

- a clear purpose statement
- additive/default-safe behavior where possible
- explicit verification queries
- no disruption to Beach Habitats live operations
- rollback instructions or documented irreversibility rationale

No reconciliation migration in Phase 2 should:

- rename tenant identity columns yet
- redesign property identity yet
- change operator-facing behavior semantically

Those belong in later phases once the schema foundation is stable.

## Round-Trip Test Plan

Phase 2 is not complete until the migration tree can recreate the current production contract closely enough that service code no longer relies on runtime schema mutation.

### Goal

Fresh database + `alembic upgrade head` should produce the same schema contract that core production services expect today.

### Required proof

1. create disposable empty DB
2. run `alembic upgrade head`
3. inspect resulting schema
4. compare against production snapshot for:
   - tables
   - columns
   - key indexes
   - key constraints
5. flag any remaining mismatches

### Critical pass condition

The following core tables must match closely enough to run the operator path without runtime DDL:

- `properties`
- `canonical_property_refs`
- `canonical_property_profiles`
- `operator_accounts`
- `operator_gmail_creds`
- `pre_booking_inquiries`
- `gmail_processed_messages`
- `message_normalizations`
- `operator_prebooking_queue_read_models`
- `concierge_guest_sessions`

## Recommended Immediate Next Steps

1. Review this matrix and approve the reconciliation set.
2. Implement `R1` first, because `concierge_guest_sessions` is the clearest migration-integrity issue discovered so far.
3. Implement `R2` and `R3` next to eliminate core operator/runtime DDL that still has no Alembic authority.
4. Decide whether `R4` is:
   - in-scope for the foundation rebuild, or
   - explicitly deferred as non-core sidecar modules
5. Build the round-trip verification harness before applying reconciliation migrations to production.

## Bottom Line

The encouraging result of Phase 2 so far is that the core operator/inbox schema is not a migration vacuum. Most of it is already in `db/migrations`, and several formerly runtime-created objects have already been adopted.

The main remaining problems are:

- a small number of real migration inconsistencies, led by `concierge_guest_sessions`
- a set of still-runtime-only sidecar schemas that need either adoption or explicit quarantine
- lingering service-level schema probing that can only be removed once round-trip trust is established

That means Phase 2 is a reconciliation problem, not a total reconstruction problem.
