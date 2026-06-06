# Foundation Rebuild Architecture

**Status:** Approved design baseline for execution  
**Date:** 2026-05-14  
**Scope:** Tenant identity, property identity, inquiry pipeline, onboarding, schema governance, and bounded self-healing

## Purpose

This document is the authoritative architecture for rebuilding Oyvoda's operator foundation without breaking Beach Habitats during the transition.

The rebuild is guided by two core ideas:

1. The operator identity layer, property layer, and inquiry pipeline are one system.
2. The base system must be deterministic; agentic behavior only appears at explicit healing points with auditability and bounded autonomy.

This document supersedes piecemeal assumptions in service code, legacy onboarding paths, and runtime schema patching.

## Design Principles

### Deterministic core first

The default system path must be cheap, fast, and migration-controlled:

- deterministic inbox parsing
- deterministic property matching
- deterministic workflow routing
- deterministic queue projection

The common path should not require an LLM or an agent.

### Agents only at known healing points

Agents are not schema substitutes. They are used only when deterministic logic:

- fails due to external format drift
- encounters ambiguous multi-source conflicts
- surfaces an unknown alias
- detects schema drift during development or startup verification

Every healing action must be bounded, logged, and reversible where applicable.

### Canonical identity everywhere

The architecture chooses one canonical business identity and one canonical property identity:

- `tenant_id` is the only canonical operator-business key
- `property_id` is the only canonical relational property key

Business-friendly identifiers like `property_code` remain important, but they are not the sole join key.

### Migrations define the schema

Service code does not create or alter schema at runtime.

- every schema change is an Alembic migration
- service code can rely on required tables and columns existing
- optional capabilities are feature-gated, not `information_schema`-gated

### Beach Habitats continuity

Beach Habitats must remain operational throughout the rebuild. This is a rolling rebuild under live traffic, not a big-bang replacement.

## Current-State Anchor

The live migration system is `db/migrations`, not the stray `alembic/versions` artifact.

Observed repo migration reality:

- `alembic.ini` points to `db/migrations`
- `db/migrations/env.py` is the active Alembic environment
- `db/migrations/versions` contains 66 migration files through `063_llm_usage_events`
- production reports revision `063_llm_usage_events`
- there is also a leftover `alembic/versions/001_create_signals.py` that is not the active migration tree

Observed operational reality from the audit:

- live production relies heavily on raw SQL services and read models
- ORM/model coverage is partial and does not describe the live operator/property system
- tenant identity is split across `tenant_id`, `company_id`, and `operator_id`
- runtime schema probing and `ALTER TABLE ... IF NOT EXISTS` patterns are compensating for drift

## Canonical Entity Model

### Tenant

Canonical business/account entity.

- one row per operator business
- keyed by `tenant_id`
- owns properties, users, inbox connections, inquiries, and knowledge

### Operator User

Human user inside a tenant.

- owner, manager, staff, super-admin scope
- authentication belongs here
- `operator_id` refers to the human/workflow actor, not the tenant

### Property

Single authoritative property entity for a tenant.

- canonical relational key: `property_id`
- stable business identifier: `property_code`
- attributes represent the best current resolved facts
- provenance never lives only on the row itself; it is backed by source records

### Canonical Property Reference

Alias or external identifier that maps to a property.

Examples:

- marketing names
- street addresses
- abbreviated addresses
- PMS property IDs
- OTA listing IDs
- website paths
- guidebook-facing names

These are not independent property entities. They are identity evidence.

### Property Source Record

Canonical provenance ledger for property facts.

- one row per source observation or source sync object
- may be linked to a property
- retains raw payload, normalized payload, observed_at, confidence, authority, and source metadata

This is the durable basis for multi-source reconciliation.

### Canonical Alias Proposal

Proposal object for unknown property references discovered in the wild.

- created by deterministic gap detection or the alias-discovery agent
- reviewed by operator or staff
- only after approval does a canonical property ref get created

### Property Conflict

First-class record of unresolved data disagreement.

- one property attribute under dispute
- competing values preserved
- may carry agent recommendation
- surfaced in operator workflow

### Message Normalization

Canonical ingress audit/event seam for inbound guest communication.

- stores parser outcome, property candidates, match result, route outcome, and composer metadata

### Pre-Booking Inquiry

Operator-actionable inquiry projection for the pre-booking workflow.

- references tenant and, once bound, property
- should never be the only place where identity truth lives

### Queue Read Model

Dashboard-optimized projection for the pre-booking inbox.

- denormalized for speed
- refreshed deterministically from canonical workflow state

### Healing Event

Single audit trail for self-healing actions.

- parser healing
- schema drift proposals
- alias proposals
- conflict recommendations/resolutions

## Canonical Naming Decisions

### Tenant identity

Canonical name: `tenant_id`

Implications:

- `company_id` becomes a legacy transitional field only
- `operator_id` is never used as the tenant surrogate
- request context, auth, queue queries, and write paths converge on `tenant_id`

### Property identity

Canonical key: `property_id`

Secondary stable business identifier: `property_code`

Implications:

- `canonical_property_refs` must FK to `property_id`
- `message_normalizations`, `pre_booking_inquiries`, and read models must gain `property_id`
- `selected_property_code` remains during transition, then becomes a convenience field instead of the only identity field

## Target Schema

### tenants

- `id uuid primary key`
- `slug text unique`
- `display_name text`
- `legal_name text null`
- `status text`
- `plan text`
- `primary_email text null`
- `primary_phone text null`
- `pms_provider text null`
- `settings_jsonb jsonb not null default '{}'`
- `created_at timestamptz`
- `updated_at timestamptz`

Indexes:

- unique `slug`
- `status`

### operator_users

- `id uuid primary key`
- `tenant_id uuid not null references tenants(id)`
- `email text not null`
- `password_hash text not null`
- `name text not null`
- `role text not null`
- `status text not null`
- `last_login_at timestamptz null`
- `created_at timestamptz`
- `updated_at timestamptz`

Indexes:

- unique `(tenant_id, email)`
- `tenant_id, role`

### operator_inbox_connections

- `id uuid primary key`
- `tenant_id uuid not null references tenants(id)`
- `operator_user_id uuid null references operator_users(id)`
- `provider text not null`
- `watched_email text not null`
- `credential_ref text not null`
- `status text not null`
- `last_polled_at timestamptz null`
- `last_poll_success boolean null`
- `last_poll_summary text null`
- `last_poll_error text null`
- `last_messages_found integer null`
- `last_new_pending_inquiries integer null`
- `created_at timestamptz`
- `updated_at timestamptz`

Indexes:

- unique `(tenant_id, watched_email)`
- `tenant_id, provider`

### properties

- `id uuid primary key`
- `tenant_id uuid not null references tenants(id)`
- `property_code text not null`
- `display_name text not null`
- `marketing_name text null`
- `status text not null`
- `address_line1 text not null`
- `address_line2 text null`
- `city text null`
- `state text null`
- `postal_code text null`
- `country text not null default 'US'`
- `community text null`
- `bedrooms numeric null`
- `bathrooms numeric null`
- `sleeps integer null`
- `property_type text null`
- `guidebook_url text null`
- `source_summary jsonb not null default '{}'`
- `attribute_confidence jsonb not null default '{}'`
- `last_verified_at timestamptz null`
- `retired_at timestamptz null`
- `created_at timestamptz`
- `updated_at timestamptz`

Indexes:

- unique `(tenant_id, property_code)`
- `tenant_id, status`
- `tenant_id, retired_at`
- `tenant_id, community`

### canonical_property_refs

- `id uuid primary key`
- `tenant_id uuid not null references tenants(id)`
- `property_id uuid not null references properties(id)`
- `provider text not null`
- `ref_kind text not null`
- `ref_value text not null`
- `normalized_ref_value text not null`
- `confidence numeric not null`
- `source text not null`
- `metadata jsonb not null default '{}'`
- `created_at timestamptz`
- `updated_at timestamptz`

Indexes:

- unique `(tenant_id, provider, ref_kind, normalized_ref_value)`
- `property_id`
- `tenant_id, ref_kind`

### property_source_records

- `id uuid primary key`
- `tenant_id uuid not null references tenants(id)`
- `property_id uuid null references properties(id)`
- `source_type text not null`
- `source_key text not null`
- `payload jsonb not null`
- `normalized_payload jsonb not null default '{}'`
- `confidence numeric null`
- `is_authoritative boolean not null default false`
- `observed_at timestamptz not null`
- `last_verified_at timestamptz null`
- `metadata jsonb not null default '{}'`
- `created_at timestamptz`
- `updated_at timestamptz`

Indexes:

- unique `(tenant_id, source_type, source_key)`
- `property_id`
- `tenant_id, source_type`

### canonical_alias_proposals

- `id uuid primary key`
- `tenant_id uuid not null references tenants(id)`
- `proposed_property_id uuid null references properties(id)`
- `ref_value text not null`
- `ref_kind text not null`
- `evidence_jsonb jsonb not null default '{}'`
- `confidence numeric null`
- `status text not null`
- `decided_by uuid null references operator_users(id)`
- `decided_at timestamptz null`
- `created_at timestamptz`
- `updated_at timestamptz`

Indexes:

- `tenant_id, status`
- `proposed_property_id`
- `tenant_id, ref_value`

### property_conflicts

- `id uuid primary key`
- `tenant_id uuid not null references tenants(id)`
- `property_id uuid not null references properties(id)`
- `attribute_name text not null`
- `competing_values_jsonb jsonb not null`
- `status text not null`
- `recommended_resolution_jsonb jsonb null`
- `resolution_source text null`
- `resolved_at timestamptz null`
- `created_at timestamptz`
- `updated_at timestamptz`

Indexes:

- `property_id, status`
- `tenant_id, status`
- `tenant_id, attribute_name`

### parser_patterns

- `id uuid primary key`
- `tenant_id uuid null references tenants(id)`
- `source_type text not null`
- `source_family text not null`
- `pattern_name text not null`
- `fingerprint text not null`
- `fingerprint_version text not null`
- `normalizer_version text not null`
- `extraction_rules jsonb not null`
- `confidence_baseline numeric null`
- `generated_by text not null`
- `status text not null`
- `provenance_jsonb jsonb not null default '{}'`
- `created_at timestamptz`
- `updated_at timestamptz`

Indexes:

- unique `(coalesce(tenant_id, '00000000-0000-0000-0000-000000000000'), source_type, source_family, fingerprint, fingerprint_version, normalizer_version)`
- `status`

### parser_pattern_observations

- `id uuid primary key`
- `pattern_id uuid not null references parser_patterns(id)`
- `message_fingerprint text not null`
- `success boolean not null`
- `latency_ms integer null`
- `confidence numeric null`
- `metadata jsonb not null default '{}'`
- `created_at timestamptz`

Indexes:

- `pattern_id, created_at desc`
- `message_fingerprint`

### schema_expectations_runs

- `id uuid primary key`
- `service_name text not null`
- `expectation_version text not null`
- `outcome text not null`
- `results_jsonb jsonb not null`
- `created_at timestamptz`

This is an audit table only. Schema expectations themselves are code-owned.

### healing_events

- `id uuid primary key`
- `tenant_id uuid null references tenants(id)`
- `domain text not null`
- `trigger_type text not null`
- `input_ref text null`
- `action_type text not null`
- `outcome text not null`
- `confidence numeric null`
- `approved_by uuid null references operator_users(id)`
- `metadata jsonb not null default '{}'`
- `created_at timestamptz`

Indexes:

- `tenant_id, domain, created_at desc`
- `domain, outcome, created_at desc`

### message_normalizations

Retained as the canonical messaging audit seam with additive target changes:

- `tenant_id uuid not null references tenants(id)`
- `property_id uuid null references properties(id)`
- `selected_property_code text null`
- `selected_property_match_type text`
- `property_binding_candidates jsonb not null default '[]'`
- `route_outcome text`
- `draft_source text`
- `fallback_reason text`

Indexes:

- `tenant_id, source_message_id`
- `tenant_id, property_id, sent_at desc`
- `tenant_id, route_outcome, sent_at desc`

### pre_booking_inquiries

Retained as workflow projection with additive target changes:

- `tenant_id uuid not null references tenants(id)`
- `property_id uuid null references properties(id)`
- `property_code text null`
- legacy `company_id` and `property_external_id` retained only during migration

Indexes:

- `tenant_id, status, created_at desc`
- `tenant_id, property_id`

### operator_prebooking_queue_read_models

Retained as UI projection with additive target changes:

- `tenant_id uuid not null references tenants(id)`
- `property_id uuid null references properties(id)`
- denormalized `property_code`, `property_name`, `status`, `is_unbound`

Indexes:

- `tenant_id, status, updated_at desc`
- `tenant_id, property_id`

## Deterministic Operations Layer

This layer handles the common path cheaply and predictably.

### Inbox parsing

- inbound message classified by source family and fingerprint
- parser pattern registry consulted first
- deterministic extraction rules applied where pattern exists
- fallback deterministic parsers remain available by source family
- only if deterministic parsing fails does healing/LLM fallback begin

### Property matching

- inbound hints become `property_binding_candidates`
- matcher resolves candidates against `canonical_property_refs`
- if successful, write `property_id` and `selected_property_code`
- if unresolved, mark unbound and continue workflow safely

### Routing

- confidence rules choose pre-booking, in-stay, escalation, or system-event paths
- no agent decision required on the common path

### Read model sync

- canonical workflow writes project into queue read model
- dashboard reads only from deterministic projections plus explicit property filters

## Agentic Healing Layer

Agents only activate at bounded healing points.

### Healing point 1: parser format drift

Trigger:

- unknown fingerprint
- deterministic extraction fails
- extraction produces insufficient required fields

Flow:

1. compute fingerprint with explicit `fingerprint_version`
2. check `parser_patterns`
3. if no active pattern or extraction fails, trigger healing
4. agent generates candidate extraction rules
5. validate candidate against recent successful examples of same `source_family`
6. if validated, save as `candidate`
7. after three successful live uses, promote to `active`
8. write every step to `healing_events`

Important boundaries:

- agent never rewrites history automatically
- parser promotion does not trigger historical replay
- reprocessing is a separate explicit job

### Healing point 2: schema drift detection

Trigger:

- startup schema integrity check fails
- development schema check detects mismatch

Flow:

1. code-declared schema expectations evaluated against live DB
2. results written to `schema_expectations_runs`
3. boot fails loudly on missing critical schema
4. optional agent can generate a migration proposal and rationale
5. migration remains human-authored or human-approved

Important boundaries:

- agent does not apply migrations
- service code does not patch schema at runtime

### Healing point 3: multi-source property conflicts

Trigger:

- new `property_source_record` disagrees with current resolved property fact
- authority rules do not provide a clear winner

Flow:

1. preserve new source record
2. consult deterministic authority rules
3. if clear winner, update resolved property fact and log it
4. if ambiguous, create `property_conflicts` row
5. agent may recommend a resolution using freshness, provider trust, and evidence
6. operator or staff approves if required
7. read models refresh deterministically after resolution

### Healing point 4: alias discovery

Trigger:

- inbound message contains unmatched property name/address/listing hint
- inquiry is routed as unbound

Flow:

1. surface unbound inquiry in operator workflow
2. create alias discovery job
3. agent searches connected sources for likely property match
4. create `canonical_alias_proposals` row with evidence and confidence
5. operator approves or rejects
6. on approval, write `canonical_property_refs` and refresh matcher-related projections

Important boundaries:

- agent proposes aliases
- agent does not write canonical refs directly

## Formal Autonomy Tiers

### Auto-apply allowed

- parser candidate promotion after validation and success threshold
- freshness updates
- confidence score refreshes
- deterministic authority-rule updates where the winner is explicit

### Human approval required

- schema migrations
- canonical alias additions
- substantive property fact changes where authority rules are ambiguous
- conflict resolutions based on recommendation rather than explicit rule

### Never autonomous

- guest communications
- data deletion
- overriding explicit operator decisions
- fabricating property identity without evidence

## Schema Expectations Model

Schema expectations are code-owned. They are not authored in a database table.

Recommended implementation shape:

- each service declares required tables/columns/indexes in code or config
- startup health check evaluates expectations
- results written to `schema_expectations_runs`
- drift during development can invoke an agent proposal flow for migration scaffolding

This ensures the expectation source of truth is version-controlled and changes with code review.

## Read-Model Refresh Rules

Read-model updates must be deterministic and explicit.

### Alias approval

Effects:

- invalidate canonical matcher cache for the affected tenant/property
- future inquiries can bind immediately
- existing historical rows remain unchanged unless an explicit reprocess job runs

### Property fact resolution

Effects:

- update `properties`
- refresh affected workflow/read-model projections that denormalize the changed fact
- write resolution outcome to `healing_events`

### Parser promotion

Effects:

- applies to future messages only
- no historical rewrite unless an explicit reprocess job is run

## Integration Map

### Inbox poller and parser pipeline

Current dependency:

- inbox credentials
- parser/router logic
- dynamic property lookup

Target dependency:

- `operator_inbox_connections`
- `parser_patterns`
- deterministic parser family contracts
- `message_normalizations`
- `canonical_property_refs`

Required changes:

- credential lookup keyed by `tenant_id`
- fingerprint registry lookup before parser fallback
- no `_table_columns` or `ALTER TABLE` logic in parser path

Verification:

- real inbound fixture persists normalization row with parser observation and property candidates

### Brain path (`app/services/messaging_brain/pre_booking.py`)

Current dependency:

- `PreBookingInquiry`
- hint forwarding
- property_code-centric resolution

Target dependency:

- same neutral inquiry contract
- property resolution returns `property_id` and `property_code`
- audit writes preserve both

Verification:

- direct email address mention resolves to bound property
- OTA subject/property name resolves to bound property

### Canonical matching service

Current dependency:

- code-keyed refs
- mixed direct property table probing
- optional `pms_listings`

Target dependency:

- `canonical_property_refs(property_id)`
- `properties`
- `property_source_records`
- deterministic authority rules

Verification:

- alias, address, property code, website path, PMS ID, and OTA listing ID resolution all return the same property

### Pre-booking handler and dispatch

Current dependency:

- `company_id`
- `property_external_id`
- status text workflow

Target dependency:

- `tenant_id`
- `property_id`
- `property_code`

Verification:

- normalization outcome updates flow through to actionable inquiry and queue row

### Read-model sync

Current dependency:

- dynamic property joins
- runtime table-existence checks

Target dependency:

- explicit FKs and required schema

Verification:

- queue sync works without querying `information_schema`

### Dashboard read paths

Current dependency:

- queue read model
- recent activity-derived property filter behavior

Target dependency:

- queue read model plus active property catalog
- deterministic unbound and inactive behavior

Verification:

- dashboard shows bound property, unbound count, and stable filters

### Property import paths

Current dependency:

- heuristic field aliasing
- raw properties upsert
- opportunistic canonical ref creation

Target dependency:

- `properties`
- `property_source_records`
- canonical ref writes through one service
- `property_conflicts` when attributes disagree

Verification:

- spreadsheet import creates valid property, source records, refs, and conflict rows where appropriate

### Knowledge service

Current dependency:

- text property external IDs
- mixed portfolio/global semantics

Target dependency:

- `property_id`
- compatibility `property_code`
- clear all-properties sentinel only where explicitly intended

Verification:

- property-scoped knowledge retrieval works for bound property and portfolio-scoped content

### Operator signup and account creation

Current dependency:

- `operator_accounts`
- partial onboarding semantics

Target dependency:

- `tenants`
- `operator_users`
- `operator_inbox_connections`
- one canonical onboarding flow

Verification:

- signup creates a fully working tenant environment that can ingest properties and inbox traffic

### LLM usage tracking

Current dependency:

- tenant-attributed usage events

Target dependency:

- unchanged tenant attribution
- optional `operator_user_id` attribution where useful
- healing activity separately attributable by domain

Verification:

- healing-related LLM calls and standard draft-related LLM calls remain traceable

### Defensive runtime patching locations

Current dependency:

- `_table_exists`
- `_table_columns`
- `CREATE TABLE IF NOT EXISTS`
- `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`

Target dependency:

- none in operational services
- replaced by migrations and startup schema verification

Verification:

- grep-based enforcement and integration tests run cleanly after removal phase

## Defensive Runtime Patching Removal Plan

This architecture treats runtime schema mutation as temporary legacy behavior to be removed.

Removal classes:

1. required operational schema checks  
   Replace with migrations plus startup verification.

2. optional module capability checks  
   Replace with feature/capability configuration, not table existence.

3. legacy compatibility branches  
   Remove after transition windows close.

Enforcement target by the end of the rebuild:

- no business service uses `_table_exists` or `_table_columns` to decide whether required schema exists
- no business service executes `CREATE TABLE IF NOT EXISTS`
- no business service executes `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`

## Migration Recovery Plan (Phase 2)

Phase 2 is not inventing migrations from scratch. It is restoring trust in the existing migration tree and proving that migrations can recreate the live schema state we depend on.

### Objectives

1. verify the active migration tree in `db/migrations`
2. reconcile production schema against the migration tree and live service assumptions
3. identify missing or drifted objects
4. create a baseline recovery plan that makes future migrations safe

### Inputs

- production schema audit snapshot from Part 1
- current active migration tree in `db/migrations/versions`
- runtime patch locations discovered in audit
- current production Alembic revision `063_llm_usage_events`

### Deliverables

1. migration inventory report
   - all active revisions
   - branch points and merge points
   - tables/columns introduced by migration file

2. production-vs-migration drift matrix
   - object exists in migration and prod
   - object exists in migration but not prod
   - object exists in prod but not migration
   - type/default/index/constraint mismatches

3. baseline recovery migration strategy
   - additive reconciliation migrations only
   - no destructive changes during recovery

4. round-trip verification harness
   - empty DB
   - `alembic upgrade head`
   - schema inspection
   - compare against expected baseline

5. discipline update
   - reaffirm `docs/SCHEMA_MIGRATION_POLICY.md`
   - add contribution note or ADR reference if needed

### Phase 2 Execution Sequence

1. enumerate migration tree and heads
2. map migrations to live production objects
3. identify orphan production objects and stale migration artifacts
4. define baseline expected schema snapshot from migrations
5. compare baseline against production snapshot
6. author reconciliation migrations only after the diff is understood
7. prove upgrade path in a disposable database

### Phase 2 Non-Goals

- no tenant normalization yet
- no property FK redesign yet
- no onboarding rewrite yet
- no data migrations that change live business meaning

Phase 2 is about restoring schema governance, not shipping product behavior changes.

## Tenant Identity Normalization Plan (Phase 3)

Decision:

- canonical name: `tenant_id`

Migration strategy:

1. create `tenants`
2. backfill one tenant per live operator account/business
3. add `tenant_id` to legacy `company_id` tables
4. dual-write `tenant_id` and `company_id`
5. convert reads to `tenant_id`
6. stop writing `company_id`
7. drop `company_id` after coverage proves no dependency remains

`operator_id` remains human/workflow identity only.

## Property Entity Rebuild Plan (Phase 4)

This is the highest-integration phase.

It includes:

- `properties` canonical row shape
- `canonical_property_refs` FK to `property_id`
- `property_source_records`
- Beach Habitats manual data reconciliation
- matcher updates
- queue and dashboard updates
- property import updates

Verification gate:

- inbox -> normalization -> property binding -> pre_booking_inquiries -> queue read model -> dashboard must still work end-to-end

## Parser Pattern Registry and Healing Plan (Phase 5)

Core components:

- `parser_patterns`
- `parser_pattern_observations`
- fingerprint computation with versioning
- validation workflow for candidate patterns
- `healing_events` for parser domain

Success criterion:

- deterministic pattern lookup handles common provider formats
- unknown drift becomes a proposal/validation workflow rather than a silent parser failure

## Onboarding Consolidation Plan (Phase 6)

Canonical onboarding flow:

- extend the DB-backed signup flow
- create tenant, owner user, inbox connection shell, and initial onboarding state
- deprecate conversational/session and JSON-registry parallel systems or reduce them to helpers behind the canonical flow

Success criterion:

- a new operator can create an account and enter one coherent onboarding workflow

## Source Attribution, Conflict Resolution, and Agent Layer (Phase 7)

Core components:

- `property_source_records`
- `property_conflicts`
- `canonical_alias_proposals`
- operator conflict/approval UI
- agent recommendation flows

Success criterion:

- no property fact is silently overwritten without provenance
- unresolved ambiguity becomes visible operational work instead of hidden drift

## Schema Integrity Monitor and Runtime Patching Removal (Phase 8)

Core components:

- code-owned schema expectation declarations
- `schema_expectations_runs`
- startup verification
- removal of runtime schema mutation and probing from core services

Success criterion:

- missing schema fails loudly at startup or in CI, not in production traffic

## Beach Habitats De-Hardcoding (Phase 9)

This phase removes operator-specific defaults from shared runtime paths.

Targets include:

- default tenant fallbacks
- Beach Habitats-specific sender/domain assumptions in shared parsers
- 30A market defaults in operator-generic flows
- branding/config moved to tenant-scoped settings

Success criterion:

- the system behaves like a platform with one tenant configured, not a Beach Habitats app with multi-tenant aspirations

## End-to-End Verification (Phase 10)

Required end-state proofs:

- Beach Habitats daily operations remain intact
- new-operator simulation works end-to-end
- inquiry flow works end-to-end
- healing events ledger shows real activity
- no defensive runtime patching remains in operational services
- schema is fully represented by migrations
- tenant identity and property identity are canonical everywhere

## Coverage Matrix

Mandatory integration coverage during the rebuild:

- signup creates tenant, owner user, inbox connection
- spreadsheet property import creates property, source records, refs
- guidebook/document import enriches without duplicate creation
- inbound Gmail message persists normalization row
- property candidates resolve to canonical property
- brain path updates normalization outcome and inquiry projection
- queue sync produces dashboard-visible row
- unbound alias flow creates proposal
- conflict detection produces `property_conflicts`
- parser healing creates pattern candidate and observation trail
- schema expectation checks write `schema_expectations_runs`
- llm usage events continue across deterministic and healing flows

Known coverage gaps to close:

- migration round-trip reconstruction
- onboarding end-to-end tests
- read-model refresh tests after alias approval and conflict resolution
- parser promotion validation tests
- guest-session optional capability tests

## Execution Plan

### Phase 1

Architectural design. Completed in this document.

### Phase 2

Migration recovery. 1-2 days.

### Phase 3

Tenant identity normalization. 2-3 days.

### Phase 4

Property entity rebuild. 4-5 days.

### Phase 5

Parser pattern registry and healing infrastructure. 3-4 days.

### Phase 6

Onboarding consolidation. 2-3 days.

### Phase 7

Source attribution, conflict resolution, and alias proposal workflows. 3-4 days.

### Phase 8

Schema integrity monitor and removal of defensive patching. 2-3 days.

### Phase 9

Beach Habitats de-hardcoding. 1-2 days.

### Phase 10

End-to-end verification. 2-3 days.

Total estimate: 3-4 weeks of focused work.

## Architectural Decision Summary

1. `tenant_id` is the sole canonical business identity key.
2. `property_id` is the sole canonical relational property key.
3. `property_code` remains a stable business identifier, not the only join key.
4. `canonical_property_refs` must FK to `property_id`.
5. `property_source_records` is the provenance ledger for multi-source data.
6. `property_conflicts` is a first-class workflow surface.
7. `canonical_alias_proposals` is the only agent path for alias discovery; agents do not write canonical refs directly.
8. parser healing is bounded by fingerprinted pattern validation.
9. schema expectations are code-owned; database only stores verification runs.
10. all healing actions are logged to `healing_events`.
11. read-model refreshes are deterministic and explicit.
12. service-level runtime schema mutation is removed by design.

## What This Architecture Delivers

If executed as designed, Oyvoda ends up with:

- migration-controlled deterministic schema
- canonical tenant and property identity
- property provenance and conflict handling
- bounded parser self-healing
- proposal-first alias discovery
- startup schema integrity verification
- auditable self-healing behavior
- deterministic read-model refreshes
- continuity for Beach Habitats during migration
- a credible path to self-serve onboarding for new operators

## What This Architecture Deliberately Does Not Promise

- full autonomy
- zero manual data review forever
- agent-controlled schema changes
- agent-controlled guest messaging
- unlimited flexibility without governance

This is a platform foundation with bounded healing, not an unconstrained autonomous system.
