## Phase 3 Tenant Identity Design

Date: 2026-05-14
Status: Design only. No Phase 3 migrations should begin until this document is
reviewed and approved.

Phase 3 exists to normalize tenant identity across the operational schema and
code paths. This is not a local refactor. It touches auth, inbox ingestion,
brain orchestration, queue projections, dashboard queries, and newly adopted
Phase 2 tables.

The core constraint is simple:
- business/account identity must converge on `tenant_id`
- user identity must converge on `operator_user_id` or equivalent user-scoped
  keys
- `company_id` can no longer remain the hidden alternative tenant key

This must be executed as a staged transition, not a big-bang cutover.

## Deploy Mechanic Note

Current deployment behavior matters for migration discipline:
- `railway.toml` is configured with:
  - `preDeployCommand = "env ALEMBIC_USE_DIRECT_URL=true alembic upgrade head"`
- if Railway auto-deploys `main`, then pushes to `main` can also auto-apply all
  pending migrations before the new app version becomes live

Implication:
- pre-apply gates for high-stakes migrations must run before merging or pushing
  to `main`, not afterward
- approved operational approach for Phase 3:
  - keep Railway auto-migrate for additive and reversible work
  - treat push/merge to `main` as the execution gate
  - add explicit destructive guards for irreversible migrations such as:
    - Phase 3F legacy column drops
    - later defensive-patching removals
    - future tenant/operator destructive cleanup work

Recommended destructive guard shape:
```python
if not os.getenv("ALLOW_DESTRUCTIVE_MIGRATION"):
    raise RuntimeError("Destructive migration; requires explicit approval")
```

Open operational note:
- local repo configuration proves the migration-on-deploy mechanism exists
- if needed, deployment history should be checked separately in Railway to
  confirm which deploy advanced production from `067` to `069`

## A. Target Canonical Model

### `tenants`

Canonical business/account entity.

Meaning:
- one row per operator business
- one stable UUID used to scope all operator-owned operational data
- the only valid cross-service organization identifier

Responsibilities:
- business name and branding root
- plan and status
- operator-level feature configuration root
- tenant-level integration ownership root

Scale-readiness requirement:
- hot-path tenant reads should go through an application-level cache keyed by
  `tenant_id`
- cache TTL should be short, around 60 seconds
- cache invalidation should consider `updated_at` or equivalent tenant version
- hot-path operational code should not perform repeated direct tenant table
  lookups when cached data is sufficient
- bulk admin-style listing operations can bypass cache

### `operator_users`

Canonical login/auth entity.

Meaning:
- one row per human user
- belongs to one tenant
- used for authentication, authorization, and assignment

Responsibilities:
- login email
- password or external auth identity
- role / permissions
- session and audit attribution

Required indexes:
- unique `(tenant_id, email)` for tenant-scoped login lookup
- `(tenant_id, role)` for permission and role queries
- `(email)` for password reset and cross-tenant uniqueness checks

### `operator_accounts` decomposition

Current reality:
- `operator_accounts` is the real production anchor today
- it mixes tenant/business identity with owner-user/login concerns

Target:
- split its responsibilities into:
  - `tenants`
  - `operator_users`

Transitional recommendation:
- keep `operator_accounts` during Phase 3 as a compatibility table or
  compatibility read surface
- do not hard-remove it during the first tenant normalization pass
- treat it as the backfill source of truth for:
  - tenant creation
  - initial owner user creation

### `companies` disposition

Current reality:
- `companies` exists but is not the real production source of truth
- legacy code and documentation still talk in `company_id` terms

Target disposition:
- deprecate `companies` as a canonical identity table
- if compatibility is needed, retain it only as:
  - a legacy view
  - or a read-only compatibility mirror
- do not continue expanding it as a live business entity

Recommendation:
- Phase 3 should treat `companies` as deprecated legacy structure
- later cleanup can decide whether it becomes:
  - a compatibility view
  - or a hard-removed table

## B. Identity Key Normalization

### Canonical rule

All operational tables converge on `tenant_id UUID`.

### Deprecation rule

`company_id` columns are transitional only:
- backfilled
- dual-written temporarily
- then removed

### User identity rule

`operator_id` must mean user identity, not tenant identity.

That means:
- `operator_id` may remain in user-scoped or audit-scoped tables
- but it must not continue acting as a surrogate for tenant identity

### Transition choice

Use a dual-write transition, not a hard cutover.

Reason:
- too many live code paths still read and write mixed keys
- Phase 3 affects operational pipelines
- rollback is much safer while both columns exist

## C. Per-Table Migration Plan

Below is the required per-table baseline for Phase 3.

### `operator_accounts`

Current:
- carries `tenant_id`
- also acts as both business/account and owner-user record

Target:
- decomposed into `tenants` + `operator_users`

Backfill need:
- yes
- this is the backfill source of truth for initial tenant creation

Code paths to update:
- [operator_signup.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator_signup.py)
- [operator_auth_service.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/auth/operator_auth_service.py)
- [operator_app.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator_app.py)
- dashboard auth and user resolution flows

Migration sequence:
1. create `tenants`
2. create `operator_users`
3. backfill one tenant per `operator_accounts` row
4. backfill initial owner user per account
5. keep `operator_accounts` as compatibility layer during transition

### `companies`

Current:
- no canonical tenant key role
- legacy table with obsolete semantics

Target:
- deprecated
- possible compatibility view only

Backfill need:
- likely no authoritative backfill role

Code paths to update:
- docs and legacy dependencies still referencing `company_id`
- older endpoints and compatibility helpers

Migration sequence:
1. stop treating `companies` as source of truth
2. optionally replace with compatibility view
3. remove live write paths later

### `pre_booking_inquiries`

Current:
- keyed by `company_id`

Target:
- keyed by `tenant_id`

Backfill need:
- yes
- resolve `company_id` to the corresponding tenant from `operator_accounts`

Code paths to update:
- inbox ingestion save path
- pre-booking handler
- operator endpoints reading inquiry queues
- dashboard read-model sync

Migration sequence:
1. add nullable `tenant_id`
2. backfill from `company_id`
3. dual-write both keys
4. switch reads to `tenant_id`
5. stop writing `company_id`
6. drop `company_id`

### `message_normalizations`

Current:
- already keyed by `tenant_id`

Target:
- keep `tenant_id`

Backfill need:
- likely no

Code paths to update:
- verify all upstream callers propagate `tenant_id`
- ensure no fallback `company_id` translation remains in adapters

Migration sequence:
1. verify
2. tighten assumptions in code

### `properties`

Current:
- keyed by `tenant_id`

Target:
- keep `tenant_id`

Backfill need:
- no

Code paths to update:
- property import
- canonical services
- property management UI later phases

Migration sequence:
1. verify
2. ensure no code still expects `company_id` joins

### `canonical_property_refs`

Current:
- keyed by `tenant_id`

Target:
- keep `tenant_id`

Backfill need:
- no

Code paths to update:
- canonical matcher
- property binding logic

### `canonical_property_profiles`

Current:
- keyed by `tenant_id`

Target:
- keep `tenant_id`

Backfill need:
- no

Code paths to update:
- profile-loading paths in property context loaders

### `llm_usage_events`

Current:
- keyed by `tenant_id`

Target:
- keep `tenant_id`

Backfill need:
- no

Code paths to update:
- optional later addition of `operator_user_id` attribution
- ensure all LLM callers pass canonical tenant identity only

### `operator_market_links`

Current:
- keyed by `company_id`

Target:
- keyed by `tenant_id`

Backfill need:
- yes

Code paths to update:
- [market_intelligence.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/market_intelligence.py)
- dashboard market queries

Migration sequence:
1. add `tenant_id`
2. backfill from `company_id`
3. dual-write
4. switch reads
5. remove `company_id`

### `property_incidents`

Current:
- keyed by `company_id`

Target:
- keyed by `tenant_id`

Backfill need:
- yes

Code paths to update:
- [incidents.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/incidents.py)
- dashboard incidents panels

Migration sequence:
1. add `tenant_id`
2. backfill
3. dual-write
4. switch reads and writes
5. remove `company_id`

### `operator_prebooking_queue_read_models`

Current:
- keyed by `tenant_id`

Target:
- keep `tenant_id`

Backfill need:
- no

Code paths to update:
- queue projection writers
- dashboard read endpoints

### `operator_policies`

Current:
- keyed by `operator_id`
- but current usage treats `operator_id` as tenant surrogate

Target:
- add canonical `tenant_id`
- reserve `operator_id` for future user-level attribution only if needed

Backfill need:
- yes
- map current `operator_id` values to tenants

Code paths to update:
- [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py)
- policy-loading paths in concierge and messaging services

Migration sequence:
1. add `tenant_id`
2. backfill from existing `operator_id` surrogate values
3. dual-read and dual-write
4. switch all reads to `tenant_id`
5. remove tenant-surrogate dependency on `operator_id`

### `gmail_processed_messages`

Current:
- keyed by `operator_id`

Target:
- add `tenant_id`
- treat current `operator_id` as tenant-surrogate legacy scope, not actor identity

Backfill need:
- yes
- resolve `operator_id` through `operator_accounts`

Code paths to update:
- Gmail poller
- dedupe logic
- Gmail diagnostics

End-of-Phase-3 decision:
- `gmail_processed_messages.operator_id` should not survive as an ambiguous
  tenant surrogate
- preferred path:
  - add `tenant_id`
  - dual-write during transition
  - stop relying on `operator_id` for scoping
  - remove the column after the grace period unless a real user-attribution use
    case is established
- if future attribution is needed, that should become a separate
  `operator_user_id`, not a reused `operator_id`

Migration sequence:
1. add `tenant_id`
2. backfill from `operator_id`
3. dual-write
4. update dedupe and diagnostics to use `tenant_id`
5. remove `operator_id` unless a separate explicit attribution need is proven

### `concierge_guest_sessions`

Current:
- mixed: `tenant_id`, `operator_id`, `company_id`
- `operator_id` has now been verified as a provider/operator branding
  identifier, not a tenant surrogate and not a human actor key

Target:
- `tenant_id` is canonical
- `operator_id` is retired entirely
- `company_id` removed

Backfill need:
- yes for any rows missing canonical alignment

Code paths to update:
- stay workflow service
- operator analytics
- mobile/session endpoints
- proactive journey logic

Migration sequence:
1. verify every row has trustworthy `tenant_id`
2. stop reading `company_id`
3. dual-write only where needed for `company_id` during the transition
4. remove `company_id`
5. move branding lookup to tenant-scoped data resolved via `tenant_id`
6. remove `operator_id` because it is a legacy branding/provider identifier
   that no longer belongs on the session record

Disposition decision:
- recommended and now-designated path: retire `operator_id`
- rationale:
  - branding is tenant-level metadata
  - session-level storage of branding identity is redundant
  - the column does not represent a human actor and should not be repurposed
    into `operator_user_id`

Affected code:
- GuestSession dataclass
- GuestSessionManager serialization
- DB model -> GuestSession conversion
- any branding loaders currently reading `operator_id` from the session row

Branding lookup strategy after `operator_id` retirement:
- branding should be resolved through a per-tenant branding cache keyed by
  `tenant_id`
- cache values should include:
  - operator name
  - logo URL(s)
  - primary color
  - support phone/email
  - concierge persona / branding fields
- cache TTL should be long, around 1 hour, because branding rarely changes
- cache invalidation should run when tenant branding fields update
- cache miss path falls through to tenant-table lookup

This avoids replacing a session-local field with an unbounded per-session DB
lookup cost at scale.

### `concierge_messages`

Current:
- no direct tenant key; joins through `session_id`

Target:
- retain join-through-session in the near term
- optional future direct `tenant_id` denormalization if performance requires it

Backfill need:
- not required for initial normalization if join-through-session remains

Code paths to update:
- stay workflow reads
- analytics endpoints
- canary monitoring

### `concierge_notifications`

Current:
- no direct tenant key; joins through `session_id`

Target:
- same as `concierge_messages`

Backfill need:
- no immediate backfill if session join remains canonical

### `concierge_guest_journeys`

Current:
- carries `tenant_id`

Target:
- keep `tenant_id`

Backfill need:
- no

Code paths to update:
- journey reads in operator dashboard
- stay workflow service

### `concierge_journey_activities`

Current:
- no tenant key; joins through `journey_id` then session

Target:
- keep indirect join initially
- consider direct `tenant_id` later only if performance requires it

### `concierge_dining_reservations`

Current:
- keyed by `operator_id`

Target:
- add `tenant_id`
- treat current `operator_id` as tenant-surrogate scope unless proven otherwise

Backfill need:
- yes

Code paths to update:
- dining service

End-of-Phase-3 decision:
- preferred path:
  - add `tenant_id`
  - backfill from current `operator_id`
  - shift reads and writes to `tenant_id`
  - remove `operator_id` unless a real human-actor meaning is identified
- if the product later needs operator-user attribution for manual reservation
  actions, that should use a distinct `operator_user_id`

### `concierge_onboarding_sessions`

Current:
- no tenant key

Target:
- keep session store for now
- optional tenant attachment later if onboarding sessions become operator-scoped

Backfill need:
- no historical backfill needed immediately

## D. Transition Strategy

### Phase 3A: Create canonical identity tables

- create `tenants`
- create `operator_users`
- backfill from `operator_accounts`
- verification:
  - every `operator_accounts` row has one tenant
  - every operator has an initial owner user
- monitoring posture:
  - Phase 3A is schema-only
  - no existing production code path should depend on these new tables yet
  - after post-apply verification succeeds, Phase 3B may begin immediately
  - no multi-day waiting window is required between 3A and 3B

### Phase 3B: Add `tenant_id` to company-keyed tables

Target first wave:
- `pre_booking_inquiries`
- `operator_market_links`
- `property_incidents`
- any other still-`company_id` tables in active use

Verification:
- no null `tenant_id` after backfill

Monitoring posture:
- Phase 3B is also schema-only
- it prepares operational tables for later code changes, but does not switch
  live reads or writes yet
- after post-apply verification succeeds, Phase 3C drafting may begin
- no multi-day waiting window is required between 3B and 3C drafting

Scale-readiness requirement:
- large-table backfills must be batched, not single-statement full-table
  updates
- use batch sizes in the 10k-50k row range
- each batch should use an index-friendly bounded predicate, such as:
  - id range
  - created_at range
- commit between batches to release locks
- backfills must be resumable
  - track progress in a separate table, checkpoint record, or equivalent
- run large backfills during lower-traffic windows where possible

This is especially important for tables that will grow into the millions of
rows, such as:
- `pre_booking_inquiries`
- `gmail_processed_messages`
- `message_normalizations` in any future rewrite or rekey path

### Phase 3C: Dual-write transition

- update code to write both `tenant_id` and legacy key
- keep reads on old key temporarily where necessary
- this is a code-change phase, not a migration-file phase
- deploy of the code change constitutes the apply
- initial Phase 3C scope is intentionally narrow based on writer audit:
  - `pre_booking_handler.py::_save_draft`
  - `pre_booking_auto_send.py::_insert_pre_booking_inquiry`
  - `incidents.py` create handler
- `operator_market_links` is deferred from Phase 3C:
  - active reads exist
  - no live writer path was found in the current codebase
  - when operator-signup-to-market-link wiring is built later, that writer
    should be greenfield on canonical `tenant_id` directly rather than
    transitioned from a legacy dual-write path
- secondary updaters on existing rows must still be audited per path before
  assuming no 3C change is needed

Verification:
- inserts and updates produce both values consistently
- divergence assertion is the primary correctness signal:
  - writers must resolve canonical `tenant_id` from operator context
  - writers must determine the legacy `company_id` value they would otherwise
    write
  - before writing, assert `tenant_id == company_id`
  - on divergence during Phase 3C:
    - log loudly
    - raise/fail the write visibly
    - do not silently write inconsistent identity data
- implementation should use a shared helper rather than per-writer duplication
- recommended helper location:
  - `app/services/identity/dual_write.py`
  - keep it small and explicit rather than hiding identity logic inside a broad
    auth or common utility module
- recommended helper shape:
  - explicit input values, not a large framework-specific context object
  - return `(tenant_id, company_id)` for the dual-write call site
  - raise a dedicated `IdentityResolutionError` on divergence
- current Phase 3C writers already pass around the needed identity input:
  - in `pre_booking_handler.py`, `draft.inquiry.company_id` is the effective
    tenant UUID context today
  - in `pre_booking_auto_send.py`, `company_id` parameters and request context
    objects are already the effective tenant UUID context today
  - in `incidents.py`, the current request payload still carries `company_id`;
    Phase 3C should resolve canonical tenant identity from request/operator
    context and assert that it matches the payload value before dual-writing
- current production reality makes this especially useful:
  - `company_id` on the first Phase 3C tables is already the tenant UUID value
  - any mismatch is therefore a real identity-resolution bug, not a harmless
    translation difference

Scale-readiness requirement:
- dual-write should be staggered to avoid multiplying write load across too
  many hot tables at once
- preferred discipline:
  - one table in dual-write at a time
  - complete dual-write -> read cutover -> legacy-write freeze on one table
    before starting the next
- if overlapping dual-write windows are unavoidable, monitor:
  - connection pool saturation
  - write latency per affected table
  - replication lag, if replicas exist

Monitoring posture:
- this is the first Phase 3 step that needs a real waiting window
- hold a 3-7 day observation period after dual-write goes live
- the real failure mode here is divergence between legacy and canonical writes

### Phase 3D: Read cutover

- update code reads to prefer `tenant_id`
- add monitoring for old-key read fallbacks
- this is a code-change phase, not a migration-file phase

Verification:
- dashboard, queue, inbox, and operator workflows still function

Real-time monitoring requirement during cutover windows:
- query latency p50 / p95 / p99 per affected endpoint
- error rates per service
- DB connection wait time
- slow query log review
- old-key fallback rate
- Beach Habitats-specific health and traffic behavior

Alert thresholds:
- p95 latency degradation greater than 50 percent from baseline
- error rate spike greater than 3x baseline
- slow query spike above baseline
- non-zero old-key fallback rate after the expected cutover window

Monitoring posture:
- this is also a real waiting-window boundary
- hold a 7-14 day observation period after reads prefer `tenant_id`
- use that window to catch missed code paths, query-plan regressions, or cold
  tenant indexes before freezing legacy writes

### Phase 3E: Legacy key freeze

- stop writing `company_id`
- legacy column becomes read-only compatibility surface
- this is a code-change phase, not a migration-file phase

Verification:
- monitoring confirms no code path still depends on legacy writes

Monitoring posture:
- keep a brief stabilization window before irreversible cleanup
- the purpose is to confirm that no hidden dependency still expects legacy
  writes once dual-write stops

### Phase 3F: Legacy key removal

- remove `company_id` columns after monitoring window
- optional cleanup or rename work for overloaded `operator_id` columns
- this returns to a migration-file phase because it is destructive and
  irreversible at the schema layer
- apply the explicit destructive guard before Railway is allowed to run it

Verification:
- round-trip still passes
- no residual code references to dropped key

## E. Code Update Plan

The following service groups must be updated deliberately per phase.

### High complexity services

These have mixed identity assumptions, broader blast radius, or defensive
patterns that make them riskier to update.

- [gmail_inbox_poller.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/gmail_inbox_poller.py)
  - multiple identity propagation seams
  - mixes operational writes with defensive schema and fallback behavior
  - likely the highest-risk service to normalize incorrectly
- [property_canonical_service.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/property_canonical_service.py)
  - multiple lookup paths
  - canonical property resolution depends on correct tenant scoping
  - should be treated as a high-sensitivity service during the transition

Recommendation:
- do not start Phase 3 by changing these first
- use lower-complexity read/write paths to establish confidence, then update
  these once the key model is already behaving predictably

### Medium complexity services

- [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py)
  - active `operator_policies` SQL currently uses `operator_id`
- [market_intelligence.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/market_intelligence.py)
  - `operator_market_links` still company-keyed
- [incidents.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/incidents.py)
  - `property_incidents` still company-keyed

### Low complexity services

- message event store and message normalization writers already operating on
  `tenant_id`
- LLM usage event writers
- property canonical write service paths that already receive canonical
  `tenant_id`

These should be used early in execution to prove the migration pattern before
touching the highest-risk components.

### Auth services

- [operator_auth_service.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/auth/operator_auth_service.py)
- signup, session creation, and current-user resolution

### Brain orchestrator and adapters

- inbox normalization adapters
- messaging brain contracts and payload builders
- pre-booking brain path and dispatch

### Inbox poller

- Gmail poller
- dedupe ledger writes
- operator lookup and tenant scoping

### Queue read-model service

- pre-booking queue projections
- any operator workflow projections consuming inquiry identity

Specific Phase 3D note:
- read-models must be refreshed or invalidated when reads cut over from
  `company_id` to `tenant_id`
- required refresh target:
  - `operator_prebooking_queue_read_models`
- any other projections derived from `pre_booking_inquiries` should be
  re-synced as part of the read cutover window

### Dashboard read endpoints

- operator dashboard
- operator pre-booking
- incidents
- market intelligence
- stay/session views

### LLM usage tracking

- ensure all calls remain scoped by canonical `tenant_id`
- optionally later enrich with `operator_user_id`

### Property canonical service

- keep tenant scoping explicit everywhere
- remove any residual company-based joins or assumptions

### Operator API endpoints

- upsell rates / policies
- orphan resolution
- onboarding status
- market link resolution

### Guest session model and manager

- [concierge_sessions.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/models/concierge_sessions.py)
- [guest_session.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/guest_session.py)
- [db_session_service.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/db_session_service.py)

Required Phase 3 change:
- remove `operator_id` as session-level branding identifier
- load branding through tenant-scoped metadata using `tenant_id`

## F. Rollback Strategy

Rollback is easiest in the schema-only phases and becomes progressively harder
once live code changes begin.

### During Phase 3A-3B

Rollback path:
- drop new structures or new columns if needed
- old code paths are still authoritative
- decisions can be made immediately after post-apply verification without a
  long observation window

### During Phase 3C-3D

Rollback path:
- revert code to prior read preference
- keep both columns
- do not drop backfilled data
- use the monitoring windows to decide whether the next cutover step is safe

### During Phase 3E

Rollback path:
- resume dual-write if monitoring shows residual dependencies

### After Phase 3F

Rollback becomes much harder because legacy columns are gone.

Therefore:
- Phase 3F should only happen after a monitoring window
- no legacy column drop should occur in the same deploy as a read cutover

## G. Discipline Guardrails

Every Phase 3 migration and code change should explicitly reference the scale
criteria it advances.

### Tenant isolation

- `A1`: every operational query scoped by `tenant_id`
- `A2`: tenant-leading indexes on dominant query paths
- `A3`: no cross-tenant leakage through reads or caches
- `A4`: move operator-scoped config out of env-var patterns over time

### Indexing

- `B3`: ensure new `tenant_id` columns are backed by the required indexes

At-scale index creation discipline:
- all large-table index creation in Phase 3 should use Postgres concurrent
  index creation
- preferred Alembic pattern:
  - `op.create_index(..., postgresql_concurrently=True)`
- migration sets that create concurrent indexes must be structured so they are
  not wrapped in a standard transaction block that defeats concurrency

This is especially important for Phase 3 tenant-key indexes on:
- `pre_booking_inquiries`
- `operator_market_links`
- `property_incidents`
- `operator_policies`
- `gmail_processed_messages`

### Connection and transaction discipline

- `D1`: clean rollback on DB exceptions
- `D3`: no long-running transactions spanning full operational pipelines

### Failure behavior

- `G2`: no silent failures during transition
- every old-key fallback should be observable, not hidden

### Schema integrity

- `H1`: schema described by migrations only
- `H2`: round-trip must continue passing after every Phase 3 migration set

Operational commit discipline:
- every Phase 3 migration-set commit message should explicitly state which
  scale criteria it advances
- recommended template:
  - `Phase 3X: <description>`
  - `Advances:`
  - `- A1: ...`
  - `- A2: ...`
  - `- B3: ...`
  - `- H1, H2: ...`
  - `Verified:`
  - `- Beach Habitats data integrity preserved`
  - `- Round-trip passes`
  - `- p95 latency unchanged on <endpoint>`

## Recommended Phase 3 Execution Discipline

- one migration set at a time
- one production apply at a time
- verification before the next step
- no `upgrade head` across multiple high-stakes Phase 3 transitions

That discipline is stricter than the acceptable Phase 2 `R3`/`R4` combined
apply, because Phase 3 changes are not low-risk and are not independent.

## Effort Estimate

Once design is approved:
- realistic estimate is 2-3 weeks of focused work
- 3-4 weeks is plausible with normal interruptions, production monitoring
  windows, and code-update churn in the highest-risk services

The earlier 1-2 week estimate was optimistic given:
- 6 transition sub-phases
- 15+ touched tables
- production verification gates
- required monitoring windows between code-change cutovers

## Maximum Dual-Write Duration

Dual-write is a transition tool, not a permanent operating mode.

These duration bounds apply to the code-change phases only:
- Phase 3C dual-write
- Phase 3D read cutover
- Phase 3E legacy-write freeze
- Phase 3F irreversible cleanup timing

They do not impose a waiting period between the schema-only setup phases 3A
and 3B.

Per table, the intended maximum cadence is:
- dual-write phase: 3-7 days before reads cut over
- reads on new key with monitoring: 7-14 days before legacy writes stop
- post-write-stop monitoring before legacy column drop: 14-30 days

Expected maximum elapsed time per table:
- roughly 30-60 days from transition start to legacy-key removal

If a table needs materially longer:
- treat that as a warning signal
- investigate the blocking dependency rather than letting dual-write linger

## Phase 3 Complete Acceptance Criteria

Phase 3 should only be declared complete when all of the following are true:

- no `company_id` columns remain in active operational tables
  - verified via `information_schema`
- no active code path references `company_id`
  - verified by repo-wide search, excluding explicitly deprecated compatibility
    surfaces
- every `operator_id` column has one of three outcomes:
  - removed
  - renamed/reworked to explicit actor meaning
  - explicitly retained with documented non-tenant semantics
- round-trip passes from empty DB to the final Phase 3 head
- Beach Habitats operations remain stable for 7 consecutive days after the
  final cutover
- new-operator simulation works end-to-end without touching legacy keys
  - tenant creation
  - property creation
  - inquiry ingestion
  - queue visibility
- all applicable scale criteria are verified satisfied for Phase 3:
  - `A1`
  - `A2`
  - `A3`
  - `A4`
  - `B3`
  - `D1`
  - `D3`
  - `G2`
  - `H1`
  - `H2`
