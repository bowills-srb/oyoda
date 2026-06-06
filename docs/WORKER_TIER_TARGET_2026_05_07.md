# Worker Tier Target

Date: 2026-05-07

This note records the architectural decision taken on 2026-05-07 for
background execution topology.

## Decision

Option B is selected: restore the Celery worker tier as the
authoritative background execution path.

This decision is based on two findings already established in the
current audit trail:

1. Celery worker infrastructure was foundational in the codebase from
   the beginning, not an aspirational late add-on.
2. A meaningful set of scheduled and delayed tasks now appears
   silently unproven or inactive because production drift left the
   system in a mixed embedded-worker / Celery-tier state.

The purpose of this restoration is not to reintroduce an abandoned
architecture. It is to restore the intended durable execution surface
for background work and remove current ambiguity about what runs where.

## Target Topology

Target production topology:

- `oyvoda`
  - API only
  - serves HTTP
  - no long-term responsibility for durable scheduled, delayed, or
    retryable background work

- `oyvoda-worker`
  - real Celery worker
  - uses [docker/Dockerfile.worker](/Users/dhuntermckenzie/Downloads/oyvoda/docker/Dockerfile.worker:1)
  - consumes queues from Redis

- `oyvoda-beat`
  - real Celery beat scheduler
  - publishes scheduled tasks into Redis for worker consumption

## Broker

Broker decision is already made by current infrastructure:

- Redis at `redis.railway.internal:6379`
- current env wiring already present on `oyvoda` and `oyvoda-worker`
  through:
  - `CELERY_BROKER_URL`
  - `CELERY_RESULT_BACKEND`
  - `REDIS_URL`

No broker provisioning is required for the restoration path.

## Transition Exception

Gmail polling stays embedded in `oyvoda` transitionally.

Reason:

- it is the most production-sensitive background path currently known
  to be working
- it already has service-level guardrails in the API process
- moving it during worker-tier restoration would increase blast radius
  without being necessary to prove Celery end-to-end

This exception is transitional only. Reassess after Session 4 once the
worker tier is stable and the rest of the background surface is no
longer ambiguous.

## Queue Layout

Current Celery queue layout from
[app/workers/celery_app.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/workers/celery_app.py:29):

- `operations`
  - operational snapshot refresh

- `concierge`
  - proactive trigger evaluation
  - PMS session reconciliation
  - escalation SLA checks
  - knowledge gap curation
  - concierge health checks
  - normalization coverage tripwire
  - message retention enforcement

- `ingestion`
  - inbox polling tasks
  - market/event ingestion tasks

These queues remain the starting layout for restoration work. Session 2
and Session 3 should validate execution against the existing queue split
before any queue redesign is considered.

### Session 2 queue-mismatch finding

During Session 2 preparation, the repo surfaced a real topology gap:

- the selected smoke-test task,
  `check_normalization_coverage_tripwire`, is routed to the
  `concierge` queue
- the checked-in worker manifest in
  [railway-worker.toml](/Users/dhuntermckenzie/Downloads/oyvoda/railway-worker.toml:1)
  was subscribed only to `ingestion`

That meant the worker could have booted successfully while still being
unable to consume the chosen smoke-test task.

### Transitional Session 2 decision

Session 2 uses a transitional multi-queue worker shape:

- `ingestion,concierge,operations`

Reason:

- it proves Celery end-to-end with the already-selected monitor-only
  smoke-test task
- it avoids changing the smoke-test task mid-session
- it keeps the session focused on mechanical worker proof rather than
  queue-topology design

This is explicitly transitional, not the final queue-topology target.

## Long-Term Boundary

Long-term rule:

- durable scheduled work belongs on Celery
- delayed work belongs on Celery
- retryable work belongs on Celery

That includes, over time:

- timeout auto-send
- normalization coverage monitoring
- concierge health checks
- escalation SLA checks
- stale draft voiding
- PMS sync
- Escapia polling
- retention enforcement
- cleanup tasks
- market and event intelligence tasks

The only explicit transitional exception at the time of this decision
is Gmail polling.

## Out Of Scope For The Restoration

The following are intentionally out of scope for the initial
restoration path:

- dead-letter handling
- queue TTL policy
- advanced retry strategy
- queue-priority redesign
- moving Gmail polling off the API service

Those can become follow-on hardening work after the worker tier is
functional and verified.

## Carry-Forward Notes

- Migration env SSL handling:
  [db/migrations/env.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/env.py:1)
  currently hardcodes `sslmode=require`, which blocks local Alembic
  runs against non-SSL Postgres instances used for migration
  verification. The current workaround is applying migration SQL
  directly during local checks. Preferred follow-up: respect `sslmode`
  from the resolved connection URL or an explicit env override.

- Event scraper data architecture:
  the `460` null-tenant `30a_fl` rows currently living in legacy
  `concierge_knowledge` are clearly event-scraper data, not operator
  knowledge. Future proactive-engine work should identify their
  current consumers and likely move them to a dedicated events surface
  rather than keeping them co-resident with operator KB.

- Legacy concierge_knowledge duplicate imports:
  production legacy `concierge_knowledge` contains `2784` in-scope
  tenant-owned rows but only `897` unique scoped Q&A entries; the
  remaining `1887` rows are exact duplicates of the same question,
  answer, and property. This appears to come from repeated seed/import
  runs rather than distinct knowledge. No direct cleanup is planned
  because the legacy table is on the deprecation path, but future
  operator onboarding and guidebook import flows should be idempotent
  or use upsert semantics so duplicate rows do not accumulate again.

- PRIORITY carry-forward: Concierge multi-source audit superseded by
  Oyvoda platform intelligence layer framing.
  The original concierge-focused audit was directionally correct, but
  Session C clarified that these fragments are broader than messaging
  concierge work. Components previously grouped under "concierge
  multi-source integration" should now be treated as platform
  intelligence infrastructure and prioritized through the broader
  Oyvoda platform intelligence project below. That includes:
  guidebook-scraping to structured-KB pipeline; curated activity
  providers; dining service with 30A catalog and OpenTable tool
  integration; event planning service on top of `market_events`;
  weather / beach conditions adapters; market-brain bundle; older AI
  concierge/session layer; live operational lookups like the Escapia
  gate-code intercept; and cross-property similarity / scan patterns.
  During Session C retrieval work and later concierge work, touched
  code should still be categorized and documented, but restoration,
  migration, or retirement decisions should be made in the platform
  intelligence roadmap rather than under a narrower concierge-only
  framing.

- PRIORITY carry-forward: Guidebook parsing completeness audit and
  re-extraction.
  Beach Habitats property knowledge originated from Breezeway
  guidebooks via `scripts/fetch_guidebooks_playwright.py`,
  `scripts/build_concierge_knowledge.py`, and
  `scripts/seed_beach_habitats_full.py`. The current parser is
  deterministic and likely captures headers, lists, and structured
  sections more reliably than prose, conditional instructions, and
  complex sentence-level facts. This matters because scoped retrieval
  is only as complete as the extracted knowledge base: property `203WW`
  currently shows `25` migrated entries, while the underlying guidebook
  likely contains materially more operator-useful facts. Incomplete
  extraction creates false-positive gap flags, redundant operator
  answers, and trust erosion when operators believe the answer was
  already documented. Planned audit: sample one guidebook such as
  `203WW`, enumerate all extractable facts manually, compare them to the
  extracted concierge rows, and quantify the completeness gap. Likely
  follow-up implementation is LLM-based structured extraction over the
  source HTML with deduplication against existing entries and operator
  review before bulk import into `concierge_scoped_knowledge`.
  Estimated scope: `2-3 hours` audit, `6-10 hours` re-extraction
  implementation, `1-2 hours` re-import. Schedule after Session C lands
  and before Session E ships the operator-facing gap-fill loop, so
  operators do not immediately encounter avoidable false-positive gap
  holds.

- PRIORITY carry-forward: Oyvoda platform intelligence layer.
  Hunter clarified that the prior infrastructure in this codebase was
  not only for guest messaging, but for a broader operator-intelligence
  platform. The reusable components surfacing during Session C —
  profile similarity scoring, cross-property scan patterns,
  multi-source concierge aggregation, curated provider catalogs,
  event/market adapters, weather/conditions adapters, and the
  guidebook ingestion pipeline — serve at least four different product
  applications: (1) guest messaging support, including cross-property
  FAQ borrowing and multi-source response composition; (2) pricing
  intelligence for operators, helping compare amenities, location, and
  features against nightly-rate performance across a portfolio; (3)
  business-development support for operators, giving them comparable
  property/rate evidence when pitching potential owners; and (4) a
  universal Oyvoda-wide knowledge brain, where cross-operator data can
  become platform intelligence and a long-term moat. Current active
  development is only the first of those. The others appear dormant,
  but they should be treated as strategic product areas rather than
  discarded leftovers. When prioritized, this needs a phased project:
  component evaluation, application-strategy prioritization, and a
  restoration-vs-rebuild roadmap across operator-facing and platform
  surfaces. Estimated scope is substantial: likely `8-15` dedicated
  sessions over multiple months, not a single sprint. Schedule Phase 1
  shortly after Session E ships the gap-fill loop so the current
  messaging foundation is stable first. Do not lose the decision point:
  Oyvoda positioned only as AI guest messaging undersells the broader
  product and the value of this dormant infrastructure.

## Session B Closure

Session B established the unified scoped concierge-knowledge
foundation:

- schema migration `059_concierge_scoped_knowledge` created
  `concierge_scoped_knowledge` and
  `concierge_scoped_knowledge_history`
- unified writer `write_scoped_knowledge(...)` now supports
  `property` and `tenant` scope with versioned history rows
- legacy `concierge_knowledge` backfill completed successfully into
  the new table

Backfill summary:

- legacy rows scanned: `3247`
- migrated scoped entries: `897`
- `topic_id IS NULL` legacy rows migrated: `897`
- topic-classified legacy rows migrated: `0`
- skipped null-tenant event rows: `460`
- skipped unresolvable test rows: `3`
- exact duplicate import rows collapsed by `question_key`: `1887`

Important Session B migration decision:

- legacy rows do not receive `topic_id` during backfill
- `topic_id` is reserved for future canonical scoped answers, such as
  gap-fill writes
- legacy row-per-Q&A content remains retrievable through
  `question_key`, original question text, and metadata

Verification outcome:

- migrated rows preserve original question and answer text
- migrated rows resolve to the expected property `scope_target_id`
- all migrated rows carry `legacy_id`, `legacy_category`,
  `migration_run_id`, and `migrated_at` metadata
- all migrated rows were written at `version=1`
- `concierge_scoped_knowledge_history` contains matching `created`
  audit rows for all `897` migrated entries

Follow-on note for Session C:

- retrieval still reads legacy/property-scoped concierge knowledge
  paths today
- Session C is responsible for switching pre-booking and concierge
  consumers onto unified scoped retrieval
- Session C closure:
  six surfaces were evaluated for migration onto unified scoped
  retrieval. C.3.1 moved
  `retrieve_prebooking_property_evidence(...)` indirectly by making
  `property_canonical_service._load_concierge_knowledge(...)` the
  centralized compatibility seam. C.3.2 verified
  `detect_missing_knowledge(...)` and
  `_find_tagged_concierge_knowledge(...)` against projected scoped data
  and added diagnostics. C.3.3 verified the fallback grounded FAQ path
  against projected scoped data and added diagnostics. C.3.4 documented
  `best_faq_answer_with_transfer(...)` as a dormant platform
  intelligence fragment instead of migrating it. C.3.5 records the seam
  decision explicitly: compatibility projection is centralized in
  `property_canonical_service` rather than localized across each
  consumer.
- Validation period:
  dual-read fallback remains active. The
  `source_provenance["concierge_knowledge_retrieval_source"]`
  diagnostic tracks `unified` vs `legacy_fallback` usage. Trigger
  condition for Session D legacy retirement: roughly one week of Beach
  Habitats traffic with `retrieval_source='legacy_fallback'`
  approaching zero.
- Session C carry-forwards:
  `PRIORITY` Oyvoda platform intelligence layer; `PRIORITY` guidebook
  parsing completeness audit and re-extraction; migration env SSL
  handling; schema drift cleanup (`concierge_knowledge` model vs live
  production); legacy LLM topic classification (ready to schedule,
  roughly `6-10 hours`); and cross-property knowledge borrowing fate
  decisions inside the platform intelligence project.
- Concierge encounter log:
  `app/services/concierge/ai_concierge.py` is currently categorized as
  `INTEGRATED`. It imports `context_builder` and appears wired into the
  broader concierge path, but no cleanup/refactor was taken during
  Session C.1 / C.3.1 because the active goal is scoped retrieval
  unification for pre-booking. Keep this module in the post-Session E
  concierge integration project unless a later retrieval seam requires a
  small, local adjustment.
  `ConciergeKnowledgeService.best_faq_answer_with_transfer(...)` is
  currently categorized as `DORMANT`. Session C.3.4 found no active
  callers in the current messaging flow. Its reusable primitives should
  be treated as platform-intelligence components rather than migrated in
  isolation:
  `_profile_similarity` is a `PLATFORM INTELLIGENCE PRIMITIVE` for
  property-pair similarity scoring; the tenant-wide cross-property scan
  pattern inside `best_faq_answer_with_transfer(...)` is a `PLATFORM
  INTELLIGENCE PRIMITIVE`; `_load_legacy_knowledge(...)` is a
  schema-drift workaround still used by dormant platform-intelligence
  functions; and the older AI concierge stack remains related platform
  intelligence infrastructure for multi-source aggregation, curated
  providers, market brain, and weather/conditions adapters. Fate
  decision deferred to the post-Session E PRIORITY platform
  intelligence project.

## Session 1 Closure

Session 1 established the source-document storage foundation for the
broader content-layer and guidebook re-extraction work:

- Cloudflare R2 is now the durable storage backend for source
  documents.
- `DocumentModel` is now a real production table instead of an orphaned
  prototype model. Production now has both `documents` and
  `extracted_fields`.
- the operator document-import flow at
  `/app/api/properties/documents/import` now persists uploaded source
  documents in R2 before normalization/extraction continues.

R2 storage layout:

- `{tenant_id}/{document_group_id}/original/{filename}`
- `{tenant_id}/{document_group_id}/versions/{version_number}/{filename}`
- `{tenant_id}/{document_group_id}/extracted/{artifact_name}`

Document storage semantics:

- `documents.file_path` stores the R2 object key
- `documents.storage_backend` is currently `r2`
- `documents.document_group_id` is the stable logical document folder
- `documents.version_number` tracks row-per-version history
- `documents.content_hash` supports exact-content dedupe and change
  detection
- `documents.upload_method` records ingestion source such as
  `operator_upload`
- `scope_type` supports both property-scoped and portfolio-scoped
  uploads

Operator import flow update:

- uploaded bytes are hashed and persisted to R2 first
- a `documents` row is created for the initial version or a new version
  row is appended to the same `document_group_id`
- identical content reuses the latest row rather than creating a new
  version
- extraction results are cached on the `documents` row and mirrored into
  `extracted_fields`
- live smoke test passed against production using a real authenticated
  upload, then the smoke-test rows and R2 object were removed

Production-state verification outcome:

- deployed API container includes `app/services/storage/r2_client.py`
  and the operator import persistence seam
- live R2 upload/retrieve/delete round-trip succeeded
- production schema now includes `documents` and `extracted_fields`
- production currently has `0` persistent document rows after smoke-test
  cleanup, so there was no preexisting `/tmp` document inventory to
  migrate

Session 1 carry-forwards:

- formalize R2 lifecycle policy for originals, versions, and extracted
  artifacts
- design operator-facing document-version history UX
- decide whether future exact-hash matches should always reuse the
  latest row or optionally create explicit re-upload events
- generic `/documents/upload` endpoint still carries the older `/tmp`
  placeholder path and should be aligned to the R2-backed storage path
  when that surface is brought back into scope
- legacy `/tmp` documents endpoint cleanup:
  `app/api/v1/endpoints/documents.py` is no longer on the live operator
  workflow because `/app/api/properties/documents/import` now handles
  durable R2-backed storage. When prioritized, either remove the older
  endpoint entirely if it is confirmed dead or migrate it onto the R2
  client if a generic upload surface is still wanted. Estimated scope:
  roughly `30-60 minutes`. Low priority.
- asyncpg type handling patterns:
  two real production issues surfaced during Phase 2.2 extraction
  staging verification. First, asyncpg can be ambiguous about text
  parameter types in some update expressions unless the SQL shape is
  explicit. Second, `timestamptz` parameters should be passed as real
  `datetime` objects rather than ISO strings. Future write/update paths
  against production Postgres should prefer explicit typing where
  asyncpg may be ambiguous and should use `datetime.now(timezone.utc)`
  instead of serialized timestamp strings. This is not a bug, just a
  practical implementation pattern that is best caught by production
  smoke tests before consumers depend on the path.
- improved knowledge candidate shaping for deterministic extractors:
  current deterministic document extractors emit mostly raw
  field/value pairs. In Session 2 Phase 2.3 these are translated into
  scoped-knowledge question/answer candidates with default phrasing so
  the staging pipeline can function, but the result is intentionally
  rough rather than polished. Future improvement areas include
  per-field-name question templates, per-extractor topic assignment,
  and field grouping rules that combine related fields into a single
  structured FAQ entry. This is lower priority than the core staging
  and guidebook re-extraction sessions, and is likely to be partially
  superseded once Session 4 LLM extraction lands. Estimated scope:
  roughly `4-6 hours` when prioritized.

## Session 2 Closure

Session 2 established the extraction staging foundation on top of the
Session 1 R2/document-storage base.

What is now active:

- `extraction_candidates` is the unified staging table for extracted
  facts, assets, and document metadata candidates
- `ExtractionStagingService` is the active promotion router
- operator document imports now route through staging instead of
  writing knowledge/assets directly
- high-confidence deterministic facts and assets auto-promote into
  `concierge_scoped_knowledge` and `operator_property_assets`
- lower-confidence candidates remain pending in staging for later
  operator review
- `guest_qa` remains on its legacy import path for now

`extraction_candidates` schema:

- identity and scope:
  `candidate_id`, `tenant_id`, `scope_type`, `scope_target_id`
- source tracking:
  `source_type`, `source_document_id`, `source_url`,
  `extraction_method`
- proposed content:
  `candidate_type`, `proposed_question_text`,
  `proposed_question_key`, `proposed_answer_text`,
  `proposed_topic_id`, `proposed_tags`, `proposed_metadata`
- review and promotion:
  `confidence`, `evidence_excerpt`, `source_section`,
  `review_status`, `reviewed_by_user_id`, `reviewed_at`,
  `review_notes`, `promoted_to_table`, `promoted_to_id`,
  `promoted_at`
- lifecycle:
  `created_at`, `updated_at`

Active staging service operations:

- `create_candidate(...)`
- `get_pending_candidates(...)`
- `approve_candidate(...)`
- `reject_candidate(...)`
- `bulk_approve(...)`
- `auto_promote_eligible(...)`

Active promotion routing:

- `candidate_type='fact'`:
  writes through `ScopedKnowledgeService.write_scoped_knowledge(...)`
- `candidate_type='asset'`:
  writes through `OperatorPropertyAssetService.upsert_asset(...)`
- `candidate_type='document_metadata'`:
  updates document extraction metadata on the `documents` row

Current auto-promotion rules:

- deterministic `fact` or `asset` with `confidence >= 0.95`:
  auto-promote
- `source_type='pms'` with `confidence >= 0.99`:
  auto-promote
- any `llm` extraction:
  stays staged regardless of confidence
- anything below `0.70`:
  stays staged

Confidence mapping used by the operator document import seam:

- `high` -> `0.95`
- `medium` -> `0.80`
- `low` -> `0.60`

Current deterministic fact-candidate translation policy:

- `proposed_question_text` comes from field-name-based default
  phrasing such as `What does the document say about wifi password?`
- `proposed_question_key` comes from normalized field name
- `proposed_answer_text` is the extracted field value
- `evidence_excerpt` comes from extractor `source_text` when present
- `source_section` comes from extractor source type/page context
- this is intentionally rough but functional; phrasing/topic polish is
  deferred until Session 4 LLM extraction

Operator import seam after Session 2:

- source document is persisted in R2 first
- normalization and deterministic extraction run as before
- extracted fields are saved onto the `documents` row and into
  `extracted_fields`
- extracted facts/assets are converted into staging candidates
- immediate `auto_promote_eligible(...)` runs only against the
  candidates created by that import batch
- response shape remains backward-compatible and now also returns:
  `extraction_candidates_created`, `auto_promoted_count`,
  `auto_promoted_candidate_ids`, `auto_promoted_entry_ids`,
  `staged_for_review_count`, `staged_candidate_ids`

Session 2 production verification trail:

- Phase 2.1:
  `extraction_candidates` migration deployed successfully after fixing
  an accidental multiple-head Alembic issue caused by a misplaced test
  shim in `db/migrations/versions/`
- Phase 2.2:
  staging-service smoke test in production caught two real asyncpg
  issues:
  - ambiguous text parameter typing in update SQL
  - `timestamptz` parameters needing real `datetime` objects instead
    of serialized strings
- Phase 2.3:
  first live import attempt exposed a real property-scope seam bug:
  `_load_property_record_for_code(...)` selected `properties.id`
  without aliasing it to `property_id`, which broke property-scoped
  staging imports even though the live table had the UUID available
  - fixed in follow-up commit `0c33008`
  - redeployed and verified successfully

Successful production smoke result for Phase 2.3:

- authenticated scoped-admin upload to Beach Habitats property
  `203WW`
- returned:
  - `fields_extracted=5`
  - `extraction_candidates_created=5`
  - `auto_promoted_count=4`
  - `staged_for_review_count=1`
- production row checks confirmed:
  - R2-backed `documents` row created
  - 5 staging candidates created
  - 4 `concierge_scoped_knowledge` rows auto-promoted
  - 1 candidate left pending review
- cleanup completed and verified for:
  - `documents`
  - `extracted_fields`
  - `extraction_candidates`
  - `concierge_scoped_knowledge`
  - `concierge_scoped_knowledge_history`
  - R2 source object

Session 2 carry-forwards:

- improved knowledge candidate shaping for deterministic extractors:
  post-Session 4 polish item, roughly `4-6 hours`
- operator review API + UI:
  deferred from Phase 2.4 into Session 5 so API and UI can be shaped
  together
- configurable auto-promotion thresholds per operator
- operator-specific category trust rules
- pattern detection across candidates / cross-property similarity:
  likely ties into the broader platform-intelligence project
- guest QA import through staging:
  defer evaluation; current `guest_qa` path remains on legacy import
- legacy `/tmp` documents endpoint cleanup:
  low-priority follow-up from Session 1
- asyncpg type handling patterns:
  preserve the production-smoke discipline for future write paths

Architecture state after Session 2:

- source documents persist durably in R2
- `documents` and `extracted_fields` are active
- `extraction_candidates` is active
- staging service with promotion routing is active
- operator imports route through staging with immediate
  auto-promotion for eligible deterministic candidates
- high-confidence deterministic facts/assets promote into
  `concierge_scoped_knowledge` / `operator_property_assets`
- lower-confidence candidates remain staged for review
- the foundation is now in place for:
  - Session 3:
    guidebook fetcher/source-artifact fixes
  - Session 4:
    LLM-assisted extraction into staging
  - Session 5:
    operator review API + UI surface

## Session Breakdown

### Session 1

Decision and documentation only.

Deliverables:

- this topology target document
- carry-forward updates in the inbound-to-draft audit
- explicit Session 2 acceptance criteria
- explicit smoke-test task selection

### Session 2

Restore one real Celery worker path without touching beat.

Deliverables:

- `oyvoda-worker` uses `docker/Dockerfile.worker`, not
  `docker/Dockerfile.api`
- worker connects to Redis successfully
- one smoke-test task can be enqueued from `oyvoda`
- `oyvoda-worker` consumes that task successfully
- execution is verified with greppable log lines showing task start and
  task completion

Non-goals:

- do not touch `oyvoda-beat`
- do not bulk-restore the full task surface
- do not migrate Gmail polling

### Session 3

Restore beat and validate scheduled tasks in layers.

Deliverables:

- `oyvoda-beat` runs as a real Celery beat scheduler
- low-risk scheduled tasks validated first
- broken tasks repaired task-by-task where needed
- decide target queue topology:
  - single worker subscribed to multiple queues
  - or multiple worker services each subscribed to one queue class

### Session 4

Finalize topology and remove redundancy.

Deliverables:

- rewire tripwire to the verified execution surface
- remove duplicated or ambiguous embedded/Celery overlap where
  appropriate
- confirm Item 2 can resume against a settled worker-tier surface

## Session 2 Acceptance Criteria

Session 2 is successful only if all of the following are true:

1. `oyvoda-worker` is configured to use
   [docker/Dockerfile.worker](/Users/dhuntermckenzie/Downloads/oyvoda/docker/Dockerfile.worker:1),
   not `docker/Dockerfile.api`.
2. One smoke-test task can be enqueued from `oyvoda`.
3. The smoke-test task is consumed by `oyvoda-worker`.
4. Task execution is verified through greppable logs that show both:
   - task start
   - task completion
5. That end-to-end task path works before any other task is considered
   restored.
6. `oyvoda-beat` is not modified in Session 2.

## Session 2 Smoke-Test Task

Selected smoke-test task:

- `check_normalization_coverage_tripwire`

Why this task is the best Session 2 verifier:

- monitor-only
- cannot mutate guest-facing production state
- cannot send messages
- cannot trigger operator-visible workflow changes
- has a single clear purpose
- directly validates the monitoring path added on 2026-05-07

Why it beats `check_concierge_health` as the first smoke test:

- `check_concierge_health` touches a broader health surface and has
  more implicit dependencies
- `check_normalization_coverage_tripwire` is narrower and safer as the
  first end-to-end proof of worker execution

Constraint worth carrying forward:

- although it is low-risk, it still performs DB-backed coverage reads,
  so Session 2 should add or verify explicit log lines for task start
  and completion before using it as the final proof point

## Open Risks

1. Some Celery-defined tasks may have bit-rotted while not running.
2. Embedded workers in `oyvoda` currently overlap conceptually with
   parts of the Celery surface.
3. The current Railway service manifests are still API-shaped for
   worker-tier services and must be corrected carefully.
4. The checked-in worker manifest was not previously aligned with the
   selected smoke-test task's queue routing, which confirms the worker
   tier was incomplete rather than simply dormant.

## Session 2 Outcome

Session 2 produced a partial but meaningful verification result.

### What was proved

- `oyvoda-worker` is now running as a real Celery worker in production.
- The live deployment is:
  - deployment id: `ddc8307e-49eb-4f82-ab48-4f07609bbb4a`
  - build shape: `docker/Dockerfile.worker`
  - start command:
    `sh -c 'celery -A app.workers.celery_app:celery_app worker --loglevel=INFO --queues=ingestion,concierge,operations --hostname=multiq@%h --concurrency=${CELERY_INGESTION_CONCURRENCY:-6} --prefetch-multiplier=1'`
- Celery booted successfully and logged:
  - `Connected to redis://default:**@redis.railway.internal:6379//`
  - `mingle: all alone`
  - `multiq@77ac4a8824ae ready.`
- Task discovery includes
  `app.workers.tasks.check_normalization_coverage_tripwire`
- The worker is consuming real production Celery traffic today.

### Smoke-test result

Smoke-test task id:

- `4c2bdc7d-fac0-486f-a51e-bcd61eddca50`

Result-backend state queried from inside the live worker container:

- `state = PENDING`
- `result = None`

Interpretation:

- worker-tier mechanics are proven at the infrastructure level
- this specific smoke-test task is not yet verified end-to-end
- Session 3 should determine whether the task is pending because of
  queue-routing mismatch outside the worker, broker/publish mismatch,
  or another task-dispatch issue

### Path used

Session 2 used Path A:

- prepared a temporary deploy root outside git
- copied repo contents into that directory
- replaced the temp root `railway.toml` with
  `railway-worker.toml`
- deployed with:
  `railway up -s oyvoda-worker --path-as-root /tmp/oyvoda-worker-deploy...`

This proved the worker shape can be applied cleanly, but it is not yet
the most durable possible configuration path. A future deploy of
`oyvoda-worker` from the normal repo root would revert to the API-shaped
`railway.toml` unless Railway service settings are made permanent or the
multi-service config approach is formalized.

## Session 3 Starting Scope

### Beat status

- `oyvoda-beat` remains failed/inactive
- Session 3 is still the first session allowed to touch it

### Observed task inventory from the live worker window

Observed over the first production window after worker restoration:

- `app.workers.tasks.poll_connected_inboxes_all_operators`
  - outcome: `SUCCESS`
  - representative result:
    `{'triggered': 1, 'providers': {'google': 1}}`

- `app.workers.tasks.sync_pms_sessions`
  - outcome: `SUCCESS`
  - representative result:
    `{'status': 'success', 'synced': 0, 'changed': 0, 'skipped': 0, 'errors': 0}`

- `app.workers.tasks.check_escalation_slas`
  - outcome: `SUCCESS`, but with repeated internal error logs
  - failure mode observed inside task:
    `asyncpg.exceptions.UndefinedColumnError`
  - one-line message:
    `column "ack_sla_breached" does not exist`
  - implication:
    task logic is running, but references schema that is not present

- `app.workers.tasks.poll_connected_inbox_for_operator`
  - outcome during observed window: `RETRY / not cleanly succeeding`
  - failure mode 1:
    `asyncpg.exceptions.QueryCanceledError`
  - one-line message:
    `canceling statement due to statement timeout`
  - failure mode 2 (logged as non-fatal warning from Gmail poller path):
    `asyncpg.exceptions.PostgresSyntaxError`
  - one-line message:
    `cannot insert multiple commands into a prepared statement`

### Session 3 implication

Session 3 should start from this concrete task-level inventory rather
than from abstract "worker tier may have bit-rotted" language.

## Bottom Line

The architectural decision is locked:

- Redis remains the broker
- Celery becomes the authoritative background execution tier
- Gmail polling stays embedded temporarily
- restoration proceeds in staged sessions, not as a bulk migration

## Session 3 Phase 1-2 Outcome

### Two-service deploy note

Shared Python code in `app/` does not reach both production runtimes
with a single git push.

- `oyvoda` auto-deploys from GitHub
- `oyvoda-worker` stays on its last manually deployed image until it is
  explicitly redeployed

Operational rule going forward:

- land and verify the `oyvoda` API deploy first
- if the change affects worker-executed code, manually redeploy
  `oyvoda-worker`
- only then treat the behavior change as verified on the worker tier

This matters for any shared service/module change, including Celery
tasks and service code under `app/services/`.

### Smoke-test producer diagnosis

The `check_normalization_coverage_tripwire` smoke-test did not stay
`PENDING` because of a routing bug.

Verified facts from the live worker and Redis broker:

- `check_normalization_coverage_tripwire` is routed to the
  `concierge` queue in
  [app/workers/celery_app.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/workers/celery_app.py:43)
- the live worker is subscribed to `ingestion`, `concierge`, and
  `operations`
- both smoke-test task IDs were found sitting in the live Redis
  `concierge` list with the correct task name and routing key

The root cause was queue backlog, not misrouting:

- `concierge` queue depth during diagnosis was ~2.4k messages
- the two smoke-test tasks were the newest messages on the queue
- roughly 2.4k older tasks were ahead of them
- queue composition was dominated by
  `app.workers.tasks.check_escalation_slas`

Producer conclusion:

- static code search still shows beat as the only in-repo scheduler for
  `check_escalation_slas`
- Railway deployment history confirms that `oyvoda-beat` existed as a
  real Celery beat service in late April
- the live queue shrank from `2458` to `2444` over a five-minute watch,
  then to `2438` shortly after
- no new messages were prepended ahead of the smoke-test tasks during
  that watch window

Interpretation:

- the queue appears to be draining a historical backlog rather than
  being filled by an unseen live `.delay()` loop
- Session 2's smoke-test mechanism failed because it was placed at the
  tail of a saturated queue, not because publish/route/consume was
  misconfigured

### SLA flag migration

Phase 2 landed a schema-only fix for `check_escalation_slas`.

Migration:

- [db/migrations/versions/055_concierge_escalation_sla_flags.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/055_concierge_escalation_sla_flags.py:1)

What it adds to `concierge_escalations`:

- `ack_sla_breached BOOLEAN NOT NULL DEFAULT FALSE`
- `resolve_sla_breached BOOLEAN NOT NULL DEFAULT FALSE`

Why boolean was correct:

- `_stamp_breach()` writes `TRUE` into the selected column
- stats/read sites aggregate and count these fields as booleans
- there was no repo evidence that these were intended as timestamps

Risk check:

- `SELECT COUNT(*) FROM concierge_escalations` returned `0`
- this made the single-step `ALTER TABLE ... ADD COLUMN ... DEFAULT FALSE`
  migration safe for the current production table size

Post-migration verification:

### Adoptive migration note

Railway re-runs `alembic upgrade head` during every deploy via the API
service pre-deploy command in
[railway.toml](/Users/dhuntermckenzie/Downloads/oyvoda/railway.toml:1).
That means adoptive migrations must be cheap to re-run even when the
target objects already exist.

Session 3 found that a single multi-statement `op.execute(...)` blob in
`057_canonical_property_runtime_tables_to_alembic` was enough to trip
Railway's deploy-time statement timeout during a pre-deploy Alembic
rerun. The fix was to split the adoptive DDL into separate
`op.execute()` calls per statement.

Rule going forward:

- adoptive migrations should execute one DDL statement at a time
- avoid single monolithic SQL blobs for multiple `CREATE TABLE` /
  `CREATE INDEX` / `CREATE SEQUENCE` operations
- verify that a rerun against an already-upgraded database completes
  cleanly before relying on Railway deploy-time Alembic

### Commit 3-4 worker verification

Commits:

- `a768904` `refactor(canonical-property): make ensure_schema() a no-op now that Alembic owns the schema`
- `7da9666` `refactor(gmail-poller): make run_gmail_migration() a no-op now that Alembic owns the schema`

API deploys:

- `oyvoda` accepted both commits successfully

Worker deploy:

- `oyvoda-worker` required an explicit manual redeploy to pick up the
  shared-code changes
- the first redeploy attempt failed with `413 Payload Too Large` when a
  temporary directory uploaded too much local workspace content
- retrying from a `git archive`-based temp directory succeeded

Verified on fresh `oyvoda-worker` logs after the redeploy:

- `[CanonicalPropertySchemaDeprecated] ensure_schema() called after Alembic ownership; runtime DDL is disabled`
- `[GmailMigrationDeprecated] run_gmail_migration() called after Alembic ownership; runtime DDL is disabled`
- the previous runtime-DDL failure signatures were no longer observed:
  - no `CREATE INDEX IF NOT EXISTS idx_canonical_property_refs_lookup`
    timeout
  - no Gmail multi-statement `cannot insert multiple commands into a
    prepared statement` error

### Commit 5 worker verification

Commit:

- `1492fb0` `fix(workers): remove sync_tenant_sources() from inbox poll hot path`

What changed:

- `_poll_connected_inbox_for_operator_async(...)` no longer calls
  `sync_tenant_sources(...)`
- the heavy tenant catalog sync remains available from explicit API
  entry points, but is no longer coupled to inbox polling

Verified on fresh `oyvoda-worker` logs after the worker redeploy:

- `poll_connected_inbox_for_operator` tasks now complete successfully
  rather than retrying on `QueryCanceledError`
- sample successful task completions:
  - `5fa2b4df-fc26-4e6f-b562-419077d73ab4` in `19.64s`
  - `9d0c9b87-afeb-41b4-8dea-05585795dd33` in `23.58s`
  - `4b47d2c9-88c6-4a23-850c-12506ce8d4a2` in `21.89s`
  - `35d0608a-96ec-4817-8f53-136906666be1` in `16.05s`
  - `f181b0c7-b20c-493b-9950-91088d921849` in `15.58s`
  - `bdddd98b-5f20-4ebf-8656-750907dd4dd0` in `15.80s`
- observed result payloads were real inbox poll completions, typically
  `query_mode=recent_inbox`, `messages_found=25`,
  `messages_processed=0`, `non_guest_skips=25`, `errors=[]`
- no new Gmail multi-statement syntax errors were observed
- no new canonical-property timeout errors were observed
- `[GmailMigrationDeprecated]` warnings continued to fire as expected
- `[CanonicalPropertySchemaDeprecated]` warnings stopped appearing in
  the poll path, which is expected because that path no longer calls
  `sync_tenant_sources(...)`

15-minute ingestion queue observation after the worker became active:

- start depth: `1321`
- `+5m`: `1215`
- `+10m`: `1109`
- `+15m`: `1001`
- net drain: `320` messages in `15` minutes
- effective drain rate: `21.3` messages/minute
- typical task duration: `15-25s`

This closed the last open functional gap from Session 3: the worker
tier is now executing real inbox poll traffic successfully under load.

- live schema now reports both columns as:
  - `boolean`
  - `NOT NULL`
  - default `false`
- fresh `check_escalation_slas` executions at `2026-05-07 21:51 UTC`
  succeeded without any accompanying `UndefinedColumnError`

### Backlog status after fix

The queue is still draining slowly after the schema fix:

- `concierge` depth observed at `2442`, then `2438` shortly after

This confirms the migration removed the missing-column failure, but it
does not by itself clear the historical backlog quickly.

Operational note:

- because `concierge_escalations` currently has `0` rows, the fixed SLA
  checks are executing as clean no-op reads
- no backlog purge was performed in this session
- a future session can make an explicit operational decision between:
  - letting the backlog drain naturally
  - purging stale queued SLA tasks to accelerate recovery

## Phase 3 Closure

Session 3 closed with all five architectural cleanup changes landed and
verified:

1. adoptive Alembic coverage for runtime-created `pre_booking_inquiries`
   columns
2. adoptive Alembic coverage for canonical property tables and indexes
3. runtime canonical-property schema DDL removed from hot paths via
   `ensure_schema()` no-op
4. runtime Gmail schema DDL removed from hot paths via
   `run_gmail_migration()` no-op
5. `sync_tenant_sources(...)` removed from the worker inbox-poll hot
   path

Backlog handling decision:

- Option A selected: let the `ingestion` queue drain naturally
- estimated remaining drain time at the end of the observation window:
  about `47` minutes for the remaining `1001` messages
- no purge action taken
- rationale:
  - the observed drain rate is acceptable
  - the queued work still has operational value
  - natural drain is lower-risk than purging live Redis task queues
  - allowing the worker to chew through a real backlog provided
    production validation under load

Architectural learnings to preserve:

- shared code changes require verifying both services:
  - `oyvoda` API auto-deploys on push
  - `oyvoda-worker` requires an explicit manual redeploy
- adoptive migrations on Railway should split DDL into separate
  `op.execute()` calls rather than one multi-statement blob, to avoid
  deploy-time statement timeouts
- schema management belongs in Alembic, not request or task hot paths
- maintenance work like tenant catalog sync should run from explicit
  triggers or separate scheduled jobs, not from inbox poll loops
- embedded and worker execution paths can diverge; restoration work must
  compare both and verify they reach equivalent operational outcomes

Open follow-up items:

- `_record_poll_heartbeat()` in
  `app/services/integrations/gmail_inbox_poller.py` still contains
  runtime DDL and should be cleaned up in a later pass
- `oyvoda-beat` restoration remains pending before scheduled task
  execution can be considered fully restored
- the seven `ensure_schema()` callers and three
  `run_gmail_migration()` callers still invoke no-op compatibility
  functions; that cleanup is optional and non-blocking

## Item 3 Closure

Heartbeat-schema cleanup landed in two steps:

1. `cb7c8ae` `feat(schema): adopt operator_gmail_creds runtime columns into Alembic`
2. `c2250fc` `refactor(gmail-poller): make _record_poll_heartbeat DDL a no-op now that Alembic owns the schema`

What changed:

- Alembic now owns the runtime-created `operator_gmail_creds` heartbeat
  columns:
  - `last_polled_at`
  - `last_poll_success`
  - `last_poll_summary`
  - `last_poll_error`
  - `last_messages_found`
  - `last_new_pending_inquiries`
  - `last_query_mode`
- `_record_poll_heartbeat()` no longer performs runtime
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...`
- the function still performs the real heartbeat `UPDATE`

Verification:

- live Alembic head advanced to
  `058_operator_gmail_creds_runtime_columns`
- live `operator_gmail_creds` column shapes remained unchanged after
  the adoptive migration
- `oyvoda` API deployment for `c2250fc` succeeded
- `oyvoda-worker` was manually redeployed and reached
  `3e399541-b029-458e-bc14-12302484a200` `SUCCESS`
- worker probe task:
  - enqueued `poll_connected_inbox_for_operator` for
    `4d0721d7-3d36-409a-a648-7209ad347a73`
  - task id:
    `cc82d7dc-59a7-4fdb-89d3-f01e4a517e79`
  - observed runtime warnings:
    - `[GmailMigrationDeprecated] run_gmail_migration() called after Alembic ownership; runtime DDL is disabled`
    - `[GmailHeartbeatSchemaDeprecated] _record_poll_heartbeat() called after Alembic ownership; runtime DDL is disabled`
  - observed successful poll result:
    - `[GmailPoller] 4d0721d7-3d36-409a-a648-7209ad347a73 mode=recent_inbox: found=25 processed=0 pre_booking=0 in_stay=0 errors=0`
  - observed Celery success:
    - `Task app.workers.tasks.poll_connected_inbox_for_operator[cc82d7dc-59a7-4fdb-89d3-f01e4a517e79] succeeded in 19.15s`
- live `ingestion` queue depth after the redeploy remained `0`

This closes the heartbeat-specific runtime-DDL cleanup. Remaining
cleanup is now mechanical caller removal and optional deletion of the
compatibility no-op functions.

## Item 4 Commit 1 Verification

Canonical-property caller cleanup landed in:

- `6872878` `refactor(canonical-property): remove ensure_schema callers now that schema is Alembic-managed`

What changed:

- removed the seven internal `ensure_schema()` calls from
  `app/services/property_canonical_write_service.py`
- removed the explicit `writer.ensure_schema()` call from
  `scripts/run_escapia_identity_import_railway.sh`
- removed unit-test monkeypatches that no longer matched production
  behavior

Verification:

- local unit verification:
  - `PYTHONPATH=/Users/dhuntermckenzie/Downloads/oyvoda .venv/bin/pytest -q tests/unit/test_property_canonical_write_service.py`
  - `5 passed`
- `oyvoda` deployed commit `6872878` successfully
- `oyvoda-worker` was manually redeployed to deployment
  `ca6ba33a-8303-43dc-be49-98ede1951d24` and reached `SUCCESS`
- worker probe task:
  - task id:
    `7017d54a-78f7-4137-84c3-87e5a732c15f`
  - observed success:
    - `Task app.workers.tasks.poll_connected_inbox_for_operator[7017d54a-78f7-4137-84c3-87e5a732c15f] succeeded in 21.02s`
  - observed poll result:
    - `[InboxPoll] operator=4d0721d7-3d36-409a-a648-7209ad347a73 provider=google mode=recent_inbox found=25 processed=0 new=0 errors=0`
- `[CanonicalPropertySchemaDeprecated]` warnings stopped appearing in
  the worker poll path during the probe window, confirming the internal
  callers are gone
- `[GmailMigrationDeprecated]` and `[GmailHeartbeatSchemaDeprecated]`
  warnings still appeared as expected, because those callers have not
  been removed yet

Railway transient metadata observation:

- on `2026-05-08`, Railway briefly reported `builder=RAILPACK` with no
  `preDeployCommand` or `startCommand` while deployment
  `9e19f9b5-e535-4ec8-9178-e32013b5b300` was still building
- once the deployment advanced, service metadata normalized back to the
  actual `/railway.toml` + `docker/Dockerfile.api` configuration
- this was a build-time reporting quirk, not configuration drift and
  not actionable

## Item 4 Commit 2 Verification

Gmail migration caller cleanup landed in:

- `4b1e59a` `refactor(gmail-poller): remove run_gmail_migration callers now that schema is Alembic-managed`

What changed:

- removed the worker-path `run_gmail_migration()` call from
  `app/workers/tasks.py`
- removed the two API-path `run_gmail_migration()` calls from:
  - `app/api/v1/endpoints/operator_app.py`
  - `app/api/v1/endpoints/operator_prebooking.py`
- kept the no-op compatibility function itself in place for one more
  deploy cycle

Verification:

- local compile verification:
  - `python3 -m py_compile app/workers/tasks.py app/api/v1/endpoints/operator_app.py app/api/v1/endpoints/operator_prebooking.py`
- caller grep verification:
  - `rg -n "run_gmail_migration\\(" app/workers/tasks.py app/api/v1/endpoints/operator_app.py app/api/v1/endpoints/operator_prebooking.py`
  - no remaining caller matches
- `oyvoda` deployed commit `4b1e59a` successfully
- `oyvoda-worker` was manually redeployed to deployment
  `8c6eca82-0689-494e-9ed9-d0fe35cf378b` and reached `SUCCESS`
- worker probe task:
  - task id:
    `f2c92e6d-060f-47a2-acda-3b454dcf357c`
  - observed success:
    - `Task app.workers.tasks.poll_connected_inbox_for_operator[f2c92e6d-060f-47a2-acda-3b454dcf357c] succeeded in 18.34s`
  - observed poll result:
    - `[InboxPoll] operator=4d0721d7-3d36-409a-a648-7209ad347a73 provider=google mode=recent_inbox found=25 processed=0 new=0 errors=0`
- `[GmailMigrationDeprecated]` warnings stopped appearing during the
  worker probe window, confirming the callers are gone
- `[GmailHeartbeatSchemaDeprecated]` warnings still appeared as
  expected, because `_record_poll_heartbeat()` still contains its
  compatibility no-op block

At this point, the remaining cleanup is optional dead-code removal:
delete the no-op compatibility function bodies and their unused module
constants after this verification window.

## Item 4 Commit 3 Verification

Dead-code cleanup landed in:

- `0da9566` `cleanup: remove no-op'd schema management code after Alembic adoption`

What changed:

- deleted the stale `MIGRATION_STATEMENTS` constant from
  `app/services/property_canonical_write_service.py`
- deleted the remaining Gmail-side compatibility dead code from
  `app/services/integrations/gmail_inbox_poller.py`:
  - `MIGRATION_SQL`
  - `run_gmail_migration()`
  - the first-use heartbeat no-op warning gate
  - `_POLL_HEARTBEAT_COLUMNS_READY`
- preserved the real heartbeat `UPDATE` behavior in
  `_record_poll_heartbeat()`

Verification:

- local compile verification:
  - `python3 -m py_compile app/services/property_canonical_write_service.py app/services/integrations/gmail_inbox_poller.py`
- local focused tests:
  - `PYTHONPATH=/Users/dhuntermckenzie/Downloads/oyvoda .venv/bin/pytest -q tests/unit/test_property_canonical_write_service.py tests/unit/test_inbound_transport.py`
  - `11 passed`
- reference verification:
  - no remaining matches for:
    - `ensure_schema`
    - `run_gmail_migration`
    - `CanonicalPropertySchemaDeprecated`
    - `GmailMigrationDeprecated`
    - `GmailHeartbeatSchemaDeprecated`
    - `MIGRATION_STATEMENTS`
    - Gmail poller `MIGRATION_SQL`
- `oyvoda` deployed commit `0da9566` successfully
- `oyvoda-worker` was manually redeployed to deployment
  `ff629b8c-5878-402d-8d3e-f36c44b7a6e5` and reached `SUCCESS`
- worker probe task:
  - task id:
    `face2016-638c-4156-bd8a-ded8078b3d23`
  - observed success:
    - `Task app.workers.tasks.poll_connected_inbox_for_operator[face2016-638c-4156-bd8a-ded8078b3d23] succeeded in 19.94s`
  - observed poll result:
    - `[InboxPoll] operator=4d0721d7-3d36-409a-a648-7209ad347a73 provider=google mode=recent_inbox found=25 processed=0 new=0 errors=0`
- no `[GmailMigrationDeprecated]` warning appeared
- no `[GmailHeartbeatSchemaDeprecated]` warning appeared

Item 4 is now fully closed:

- runtime DDL compatibility shims were first neutralized, then all
  callers were removed, and finally the dead schema-management code was
  deleted
- the worker and embedded/API paths both continue to process Beach
  Habitats inbox work without regression

## Item 1 Beat Restoration

Beat restoration was completed by redeploying `oyvoda-beat` with the
existing beat-specific manifest instead of the API manifest.

Root cause of the failed beat state:

- the previously failed `oyvoda-beat` deployment
  `a8892dbd-27c5-4cf7-b9f2-86d1a4d2fc30` was running the API shape:
  - `/railway.toml`
  - `docker/Dockerfile.api`
  - API `preDeployCommand` (`alembic upgrade head`)
  - API `uvicorn` start command
- its logs failed before beat startup with:
  - `RuntimeError: No database URL configured for migrations. Set ALEMBIC_DATABASE_URL or DATABASE_URL before running alembic upgrade head.`
- so `oyvoda-beat` was not failing as a Celery beat scheduler; it was
  failing because the service had the wrong deployment shape

Restoration:

- `oyvoda-beat` was redeployed with the beat manifest shape using the
  worker image and Celery beat start command
- successful deployment:
  - `94d91673-a323-4f28-bc0d-2fb4b096739b`
- verified live service metadata after restore:
  - `builder: DOCKERFILE`
  - `dockerfilePath: docker/Dockerfile.worker`
  - `preDeployCommand: null`
  - `startCommand: celery -A app.workers.celery_app:celery_app beat --loglevel=INFO`

Observed beat behavior:

- startup log:
  - `[2026-05-08 15:53:09,459: INFO/MainProcess] beat: Starting...`
- first observed due-task emission at `15:55 UTC`:
  - `check-unacked-alerts`
  - `check-escalation-slas`
  - `poll-escapia-messages`
  - `poll-email-inboxes`

Observed worker behavior after beat restore:

- `check_escalation_slas` was received and succeeded:
  - task id `f6a13268-4ec6-4b6f-8bfd-f45367d9bfc5`
  - succeeded in `1.03s`
  - result: `{'status': 'success', 'breaches': 0}`
- `poll_connected_inboxes_all_operators` was received and succeeded:
  - task id `fb1bcc65-d165-49ee-b284-10164a600071`
  - succeeded in `2.55s`
  - result: `{'triggered': 1, 'providers': {'google': 1}}`
- the resulting fan-out worker task also succeeded:
  - `poll_connected_inbox_for_operator[3d9bd99b-d902-4177-b5bc-6b34cab8e7a7]`
  - the short log sample confirmed receipt; adjacent worker probes and
    the now-stable inbox poll path remained healthy

Residual inventory / item 1.5 follow-up:

- beat definitely emitted:
  - `check_unacked_alerts`
  - `poll_escapia_messages_all_operators`
- in the short post-restore verification window, I did not capture the
  corresponding worker receipt/completion lines for those two tasks
- that is not evidence of failure, but it is the remaining follow-up
  inventory to verify when we do the next scheduled-task sweep

Railway metadata note:

- during an unrelated `oyvoda` API deployment on `2026-05-08`, Railway
  briefly reported `builder=RAILPACK` with missing start/predeploy
  metadata while the deployment was still building
- once the deployment progressed, metadata normalized back to the real
  `/railway.toml` Dockerfile configuration
- this appears to be a transient build-time reporting quirk, not
  configuration drift

Item 1 is now functionally closed:

- `oyvoda-beat` is restored in the correct beat shape
- beat is emitting scheduled tasks from `celery_app.py`
- `oyvoda-worker` is receiving and succeeding at least the first
  observed scheduled tasks
- further scheduled-task verification and any newly surfaced bit-rot
  should be handled as follow-up work rather than as part of the beat
  restore itself

### Item 1.5 Bit-Rot Inventory

Observed succeeding during the beat-restore verification window:

- `check_escalation_slas`
- `poll_connected_inboxes_all_operators`

Observed scheduled by beat, but completion not directly verified in
the short window:

- `check_unacked_alerts`
  - needs longer observation
  - may still surface schema drift or other dormant task-path issues
- `poll_escapia_messages_all_operators`
  - infrastructure is now live and the task is being scheduled
  - operationally, Escapia communications access is not currently
    available for any operator
  - expected near-term behavior is likely harmless no-op or access
    failure, not actionable application breakage
  - treat as `behavior-pending`, not as an immediate bug

Other beat-scheduled tasks from `celery_app.py` not yet directly
observed in this session:

- `void_stale_drafts_all_operators`
- `enforce_message_retention_policies`
- `restore_expired_ooo`
- `send_inquiry_on_timeout`
  - note: this is a prerequisite path for autonomous mode per
    `AUTONOMOUS_ESCALATION_POLICY_PLAN`
- `sync_pms_all_operators`
- `curate_knowledge_gaps`
- `rebuild_platform_intelligence_task`
- `refresh_experience_demand`
- `ingest_market_events`
- `check_concierge_health`
- `check_normalization_coverage_tripwire`
  - the original tripwire is now operationally live again

Recommended handling:

- observe these tasks naturally as they fire on their real schedules
- do not proactively chase fixes for dormant tasks that are not
  visibly failing
- when a task does fail, address it as a small targeted repair rather
  than reopening beat restoration itself

PMS integration note:

- future PMS integrations should likely be webhook-first rather than
  polling-first
- Escapia is currently the only clearly polled PMS path, and even that
  path is operationally constrained by missing communications access
- this is a design follow-up, not part of the beat-restore fix

## Item 5 Regenerate Gate Asymmetry

The dashboard regenerate path now mirrors the initial draft pipeline's
knowledge-gap safety gate.

Root cause:

- initial draft generation in
  `app/services/concierge/pre_booking_auto_send.py` constructs a
  `PreBookingDecisionStage`, calls `detect_missing_knowledge(...)`,
  and routes knowledge-gap cases to
  `_generate_knowledge_gap_hold_draft(...)`
- regenerate in
  `app/api/v1/endpoints/operator_prebooking.py` previously skipped
  that decision-stage logic and called `generate_inquiry_draft(...)`
  directly
- this created a safety asymmetry where the same inquiry could first
  produce a hold draft and then produce a confident regenerated draft
  from the same degraded context

Fix:

- commit:
  - `2d3c3d7`
  - `fix(prebooking): apply missing_knowledge_topics gate on regenerate path to match initial draft safety`
- regenerate now:
  - calls `detect_missing_knowledge(...)` with the same core inputs
    used by the initial pipeline:
    - `message`
    - `intent`
    - `structured_asks`
    - `property_data`
    - `operator_policies`
  - mirrors the initial pipeline's exact knowledge-gap flag/warning
    shape:
    - `ℹ️ Knowledge gap detected — hold for operator review before replying`
    - `missing_property_knowledge:...`
  - calls `_generate_knowledge_gap_hold_draft(...)` instead of
    `generate_inquiry_draft(...)` whenever knowledge is missing

Verification:

- `oyvoda` deployment for the fix:
  - `63a8e407-7e9d-4383-a945-13b23819ce60`
  - status `SUCCESS`
- focused unit coverage was added in
  `tests/unit/test_operator_prebooking_regenerate.py` for:
  - missing-knowledge regenerate -> hold draft
  - normal regenerate -> standard draft path
- local execution of those endpoint tests was blocked in this workspace
  because the available Python environment does not currently have
  `fastapi` / `starlette` importable during collection
- code-level verification still passed:
  - `python3 -m py_compile app/api/v1/endpoints/operator_prebooking.py tests/unit/test_operator_prebooking_regenerate.py`

Outcome:

- regenerate no longer acts as a hidden bypass around the
  `missing_knowledge_topics` safety gate
- operators now get consistent draft safety semantics between initial
  draft creation and regenerate

## Carry-forward: Regenerate Redesign (Option C)

Item 5 shipped a safety gate as a deliberate band-aid. The deeper
product and architecture plan is to replace regenerate with two more
targeted features and remove regenerate as a discrete feature.

Planned replacement features:

- `Refresh inputs`
  - re-fetch the source Gmail message
  - re-run the full pipeline:
    - LLM extraction
    - brain/orchestration
    - composer
    - adversarial review
  - same code path as initial draft creation, just with potentially
    fresher upstream data
  - intended use case:
    - "Something seems off about this draft; parsing, property
      resolution, or upstream context may have changed."

- `Edit draft`
  - present the operator with a text editor over the current draft
  - save edits back to the same draft record
  - capture the operator's revision as a learning signal:
    - preferences
    - tone/voice
    - factual corrections
  - intended use case:
    - "The draft is mostly right; I want to adjust or correct it."

Removed feature:

- remove `Regenerate` as a standalone button/flow
- eliminate the slot-machine reroll behavior entirely
- operators should either:
  - deliberately refresh inputs through the full pipeline
  - or edit the current draft directly

Why this redesign:

- regenerate originally existed because initial drafts were often stale
  or wrong
- with current ingestion-time LLM extraction, brain composition,
  adversarial review, and stronger persistence, initial drafts are now
  materially better than they were when regenerate was added
- regenerate is now mostly a band-aid that:
  - fights operator-edit learning by encouraging rerolls instead of
    edits
  - encourages slot-machine behavior ("click until you like one")
  - diverges from the initial-draft code path
  - created the safety asymmetry that item 5 had to patch

Multi-session plan:

- Session 1: design
  - read current regenerate endpoint, edit endpoints, and remaining
    legacy-generator callers
  - design `refresh inputs` and `edit draft` feature boundaries
  - decide telemetry shape for capturing original draft plus final
    operator-edited draft
  - produce spec only; no code

- Session 2: backend
  - add new `refresh inputs` endpoint that invokes the full pipeline
  - update edit endpoint behavior if needed to capture original and
    final draft states
  - store telemetry needed for learning
  - deprecate legacy generator usage where safe after caller audit

- Session 3: frontend
  - remove the regenerate button
  - add a `refresh inputs` button with confirmation, since it triggers
    real pipeline work
  - make draft editing the primary operator action

- Session 4: verification
  - confirm telemetry captures correctly
  - confirm no regressions in draft workflows
  - observe operator behavior if/when active operators are using the
    system

Dependencies and ordering:

- not blocked by the remaining carry-forward items
- can be tackled independently when ready
- item 5's shipped safety gate remains the temporary safety net until
  this redesign lands

## Item 2 Closure: Canonical Inquiry Persistence Seam

Item 2 is functionally closed. The three core commits landed, and the
active inquiry-persistence call sites now go through the canonical
interface instead of passing fragmented writer arguments directly from
multiple entry shapes.

Commits landed:

- Commit 1: `93da86d`
  - `feat(prebooking): add canonical save_inquiry interface`
  - added `InquirySaveContext`
  - added `save_inquiry_from_canonical(...)`
  - preserved `_save_inquiry(...)` as the wrapped legacy
    implementation

- Commit 2: `a794a8a`
  - `refactor(prebooking): migrate persist_and_dispatch to canonical save interface`
  - migrated the main pre-booking pipeline seam
  - brain-handoff flow benefited automatically because it reaches
    persistence through `persist_and_dispatch(...)`
  - verified in production that brain-path adversarial review metadata
    still persisted correctly in `policy_warnings`, including:
    - verdict
    - source
    - flags
    - rationale
    - `orig_hash` / `final_hash`
    - preview snippets

- Commit 3: `1e01b24`
  - `refactor(gmail-poller): migrate fallback writer to canonical save interface`
  - migrated the Gmail fallback inquiry writer
  - primary verification came from focused unit tests, which is
    appropriate because the fallback path rarely fires during normal
    production traffic
  - production verification confirmed that the main path remained
    healthy after the fallback migration

Result:

- the inquiry persistence seam now goes through a canonical interface
- `CanonicalInboundMessage` carries inbound-message semantics
- `InquirySaveContext` carries inquiry-persistence semantics
- active callers no longer shred richer upstream state directly into
  `_save_inquiry(...)`

Verification summary:

- Commit 1 local verification:
  - canonical wrapper translation tests passed
- Commit 2 local verification:
  - focused persistence + brain-path tests passed
- Commit 2 production verification:
  - `persist_and_dispatch(...)` created correct rows
  - real `messaging_brain` rows retained full adversarial-review
    metadata in `policy_warnings`
- Commit 3 local verification:
  - focused Gmail fallback adapter + writer tests passed
- Commit 3 production verification:
  - worker stayed healthy
  - Beach Habitats polling stayed healthy
  - queue depth remained at `0`
  - no new main-path persistence regression was observed

### Deferred Commit 4

Carry forward:

- collapse `_save_inquiry(...)` into the canonical wrapper once the new
  seam has had additional production observation time
- this is cleanup, not active risk reduction
- likely shape:
  - inline the legacy implementation into the wrapper
  - or reduce `_save_inquiry(...)` to a private implementation detail
    with fewer legacy entry assumptions
- recommended as a standalone low-risk follow-up session after a few
  days of stable observation

### Worker Redeploy Hardening

This session exposed a deploy-procedure footgun for `oyvoda-worker`.

What happened:

- the initial manual worker redeploy for item 2 commit 2 accidentally
  came up API-shaped
- root cause was a temp-dir race:
  - archive extraction and manifest copy were done in parallel
  - the repo-root API `railway.toml` overwrote the worker manifest in
    the temp deploy directory

Verified safe procedure:

- create temp dir
- extract repo archive into temp dir
- wait for extraction to complete
- copy `railway-worker.toml` to temp `railway.toml`
- verify the temp manifest before deploy
- then `railway link` and `railway up`

Carry forward:

- this sequential prep procedure works, but it is manual and
  error-prone
- future hardening options:
  - script the procedure as one command with built-in verification
  - investigate Railway service-level configuration that can override
    root `railway.toml` for `oyvoda-worker`
  - adopt a deployment path that does not require manual manifest file
    manipulation in temp workspaces
- until then, every manual `oyvoda-worker` redeploy should use the
  sequential prep procedure with explicit manifest verification

### Carry-forward: LLM Provider Error Noise Investigation

Production worker logs during item 2 verification showed repeated
provider failures:

- Anthropic `400 Bad Request`
- Groq `429 Too Many Requests`
- repeated `[LLMEmailExtractor] fallback ...`
- repeated parser fallback to deterministic extraction

Important context:

- this did not originate with item 2
- it did not block inbox poll completion
- defensive fallback behavior is working
- but it likely:
  - degrades extraction quality on affected messages
  - wastes provider spend on failed requests
  - will worsen with scale if left uninvestigated

Investigation needed:

- determine what request shape is triggering Anthropic `400`s
  - especially whether large raw emails or malformed prompt payloads
    are involved
- determine the actual Groq limit being hit
  - burst
  - per-minute
  - daily
- decide whether certain message shapes should route around known-bad
  provider paths
- quantify the spend on failed calls

Priority:

- medium
- not blocking current traffic
- should be addressed before scaling operators materially beyond Beach
  Habitats

### Pricing-Relevant Cost Note

Working estimates worth preserving:

- Beach Habitats:
  - roughly 15-20 real inquiries / day
  - roughly `$60-80/month` estimated LLM cost
- at `~100` operators of similar scale:
  - projected cost on the order of `$6-10K/month`

These are directional, not audited billing numbers, but they are
useful enough for prioritization decisions around cost optimization and
provider-noise cleanup.

## Carry-forward: Operator Response -> Knowledge Capture Loop Verification

The `missing_knowledge_topics` hold path is now safer, but the learning
loop behind it is still unverified.

Desired product behavior:

- when the system generates a hold draft because knowledge is missing,
  the operator's eventual reply should create reusable knowledge
- that knowledge should reduce or eliminate future holds for materially
  similar inquiries

Current status:

- unverified end to end
- we do not yet know whether operator replies are being converted into
  reusable `concierge_knowledge`
- we do not yet know whether `detect_missing_knowledge(...)` can
  actually see any such captured knowledge if it exists

Investigation needed:

- where does an operator reply, sent either from the dashboard or via
  Gmail, get persisted?
- after persistence, is the reply analyzed for factual content beyond
  its literal sent text?
- does anything currently write to `concierge_knowledge`
  automatically from operator replies, or is knowledge only populated
  manually / through PMS sync / other explicit maintenance flows?
- what does `detect_missing_knowledge(...)` actually check:
  - property schema fields only
  - or property schema plus free-form `concierge_knowledge`
- does the `curate_knowledge_gaps` Celery task do meaningful curation
  work today, or is it effectively inactive / partial / no-op?
- earlier audit work flagged `kb_gap_manager.py` as defined but never
  imported:
  - is that where this loop was supposed to live?
  - if yes, why is it disconnected from runtime?

Likely required fixes:

- operator response capture
  - when an operator answers a hold-drafted inquiry, capture the reply
    content and associate it with the `missing_knowledge_topics` that
    triggered the hold
- knowledge storage
  - write the captured answer into `concierge_knowledge`
  - decide scope carefully:
    - property-specific
    - operator-wide
    - possibly user-confirmed scope via UI affordance
- retrieval integration
  - ensure `detect_missing_knowledge(...)` consults relevant
    `concierge_knowledge` entries, not just structured property schema
    fields
- loop verification
  - add an end-to-end test showing that an operator answering a
    question like "is the pool heated for 178 Spartina Cir" prevents
    future holds on the same question for that property

Why this matters:

- without this loop, the safety gate creates operator work without
  creating learning
- every similar inquiry can produce the same sequence:
  - hold draft
  - operator response
  - zero accumulated knowledge
- that is a poor trade unless the system actually improves from
  operator effort
- this is tightly related to the regenerate redesign's plan to capture
  operator edits as a learning signal; both are parts of the same
  operator-feedback learning surface

Priority and scope:

- estimated investigation scope: roughly 2-4 hours
- implementation scope depends on what parts of the loop are currently
  missing vs merely disconnected
- priority: should be addressed before item 7's autonomous escalation
  policy goes live
- rationale:
  - without this loop, operators bear the full cost of unresolved
    knowledge gaps
  - autonomous mode would amplify the harm of stale or permanently
    unlearned gaps

## Carry-forward: Verify Pipeline Order for Non-Guest Cost Optimization

Worth pinning:

- Beach Habitats traffic appears to be heavily skewed toward non-guest
  inbox traffic:
  - marketing mail
  - platform notifications
  - auto-replies
  - other operational noise
- if LLM extraction runs before non-guest filtering, a meaningful share
  of spend may be landing on messages the system later discards

Estimated traffic shape:

- roughly 15-20 real inquiries / day
- likely total inbox volume around 60-100 messages / day
- if ~75% of inbox traffic is non-guest, then roughly 25-40% of LLM
  extraction cost may be spent on ultimately discarded messages

Investigation:

- read the polling pipeline order carefully:
  - does Gmail polling run LLM extraction on every inbox message
    before classifying non-guest vs guest?
  - or is there already a cheap classifier/gate that filters most
    non-guest traffic before LLM extraction?
- if extraction-first is still the live order:
  - estimate the non-guest cost share more concretely
  - determine whether the cost is material enough to change the order
- evaluate cheap front-door classification options:
  - header-based filtering
    - sender domain
    - reply-to
    - subject patterns
    - known platform automation signatures
  - small-model classification
    - e.g. low-cost Groq / similar lightweight pass
  - layered approach
    - deterministic rules first
    - small model only for ambiguous cases

Potential value:

- estimated savings if the current order is extraction-first:
  - roughly 25-40% lower LLM bill per operator
- at Beach Habitats scale this is not urgent
- at larger scale it becomes real money
  - rough back-of-envelope at ~100 operators:
    - on the order of $2-3K / month

Priority:

- investigate when scaling beyond Beach Habitats
- at current single-operator scale, the cost is small enough that this
  is optimization work rather than an active incident

## Carry-forward: Multi-Operator Scoping Audit and Tightening

Trigger:

- do this when an operator with multiple humans on the team asks for
  specific behavior around:
  - assignment
  - permissions
  - role-based access
  - per-employee dashboards

Current posture:

- Lanier does not currently need this
- her team can answer anything without meaningful conflict
- the current urgency is therefore low
- a larger incoming operator is much more likely to surface the real
  constraints

Investigation scope:

- audit current per-tenant vs per-user scoping across the codebase
- identify places where data is being captured at the wrong granularity
- identify places where permission concepts exist but are not actually
  enforced
- identify gaps in assignment and portfolio logic
- produce a prioritized tightening plan with separate sub-sessions by
  area

Expected output:

- clear inventory of:
  - tenant-scoped behavior that should stay tenant-scoped
  - user-scoped behavior that is currently too broad
  - permission boundaries that are implicit rather than enforced
  - assignment / workload-routing gaps
- implementation plan broken into follow-up sessions

Estimated scope:

- investigation: roughly 3-5 hours
- implementation: likely multiple sessions depending on findings

Priority:

- address when the first operator with real multi-human coordination
  needs arrives
- not urgent for Beach Habitats today

## Session 3 Closure: Breezeway API Source Layer

Session 3 pivoted Beach Habitats guidebook ingestion from the older
Playwright route to an API-first architecture built on Breezeway's
anonymous public guide endpoint:

- `scripts/fetch_guidebooks_api.py`
- `GET https://api.breezeway.io/public/guides/{guide_token}`

This was the correct pivot because the Breezeway UI is a routed SPA:
the old browser fetcher landed on `/home/page/...`, while the real
guide tabs lived under `/guide/page/...`. Session 3 confirmed that the
public API returns the same structured page/section/block model the UI
renders, including the rich HTML needed for Session 4 extraction.

### Session 3 outcome

- Raw guidebook JSON is now persisted as `guidebook_api` source
  documents through `DocumentModel` + R2.
- Per-page extracted artifacts are stored in R2:
  - `guide_manifest.json`
  - `page_{page_id}.html`
  - `page_{page_id}.metadata.json`
- Guidebook documents now carry API-ingestion markers in
  `extracted_fields`:
  - `ingestion_source = "breezeway_public_api"`
  - `fully_ingested_via_api = true`
- The old `scripts/fetch_guidebooks_playwright.py` path is now
  deprecated and retained only as fallback/reference.

### Beach Habitats backfill result

Backfill scope: `42` indexed Beach Habitats guide URLs.

- `36` fetched as new documents
- `3` reused as unchanged
- `3` skipped because Breezeway reported
  `"Home Guide is not available"`
- `0` other per-property errors
- `0` auth/rate-limit/global-stop failures after the targeted 422 fix

Known skipped properties:

- `102-1785` / `6YRphTYrDO8`
- `236SC` / `vSk97BbwmfM`
- `75ECRAB` / `0bXkta5rVyc`

Operator-facing implication:

- Beach Habitats appears to have `3` properties without public
  Breezeway Home Guides configured.

### Source completeness and taxonomy

Manual source-completeness sampling on `203WW` and `100SL2C` confirmed
that the API/source-artifact layer preserves the nuanced content we
care about for downstream extraction:

- multi-branch cancellation policy text
- processing-fee wording
- hurricane refund policy
- conditional early/late check-in language
- full FAQ prose
- quiet-hours and golf-cart rules
- WiFi credentials
- links, bold emphasis, and list structure

Across all `39` public-guide documents stored in production, the page
taxonomy is fully consistent:

- page titles:
  - `Welcome`
  - `Contact Info`
  - `Arrival`
  - `Access`
  - `Company Info`
  - `Services`
  - `General`
  - `FAQs`
- page paths:
  - `guide` × `195`
  - `contact` × `78`
  - `home` × `39`
- page render types:
  - `static` × `234`
  - `static_contact_info` × `39`
  - `dynamic_arrival` × `39`

Block render-type taxonomy across the full Beach Habitats backfill:

- common across essentially every public guide:
  - `guide_content.welcome_message`
  - `home.about_note`
  - `widget.reservation_info`
  - `guide_content.travel_tips`
  - `guide_content.faqs`
  - `widget.recommendations`
  - `widget.getting_here`
  - `guide_content.departure_instructions`
  - `widget.messaging_phone_number`
  - `widget.phone_number`
  - `widget.email_address`
  - `widget.website`
  - `widget.wifi`
  - `widget.upsells`
  - `guide_content.about_us`
  - `guide_content.rules`
  - `guide_content.safety_info`
- common but not universal:
  - `home.trash_info_note`
  - `home.wifi_note`
- rarer:
  - `home.direction_note`

This taxonomy gives Session 4 a strong starting point for
section-aware LLM extraction and for deciding which block types may be
safe to treat deterministically.

### Post-backfill verification

Session 3 also ran a random whole-guide artifact spot-check across six
stored Beach Habitats documents. The sampled guides all retained:

- cancellation-policy text
- processing-fee text
- quiet-hours rules
- WiFi content

That makes the source layer good enough to proceed into Session 4
without another fetcher round.

### Carry-forward

- Per-PMS/guidebook-source adapter pattern:
  Beach Habitats on Breezeway is now cleanly API-backed, but future
  operators on other PMS/content stacks will need adapter-specific
  fetchers rather than one monolithic scraper.
- Playwright fallback retained:
  `scripts/fetch_guidebooks_playwright.py` stays in the repo as
  deprecated fallback/reference.
- R2 artifact read helper:
  `upload_artifact(...)` exists, but a symmetric read/list helper
  should land early in Session 4 so extractors and audit tooling can
  read extracted artifacts directly.
- Periodic re-fetch with hash comparison:
  low-priority follow-up after Session 4/5. The content-hash seam is
  now in place.
- Breezeway scaling/TOS evaluation:
  Session 3 stayed within Beach Habitats-owned guide tokens, used a
  plain identifying User-Agent, and rate-limited requests. If this
  pattern expands beyond the current operator, reevaluate operating
  boundaries deliberately.

- Property-group scope evaluation:
  Session 4 source analysis surfaced content that appears to vary by
  property cluster rather than cleanly at the tenant or single-property
  level. Current examples include `home.about_note`,
  `home.trash_info_note`, and some `home.wifi_note` variants. The
  current scoped-knowledge model only supports `property` and `tenant`
  scope types, so these cluster-patterns should remain property-scoped
  for now. When operator-defined property groups become a real feature
  — likely during later dashboard work or the broader platform
  intelligence project — evaluate adding `property_group` as a first
  class `scope_type` so one reviewed knowledge entry can apply across a
  defined group such as golf-cart properties, beachfront homes, or
  other operator-managed clusters. Priority is below Session 4-5 core
  extraction/review work, but above pure nice-to-have cleanup because
  it affects long-term knowledge modeling.

## Session 4 Progress: Canonical Block Manifest

Session 4.B.0 and 4.B.1 established the pre-extraction dedupe layer
that sits between the Breezeway API source corpus and the later
deterministic / LLM extraction passes.

### Storage seam update

The R2 client now supports symmetric extracted-artifact reads:

- `get_artifact(...)`
- `list_artifacts(...)`
- `get_extracted_content(...)`

The existing Session 3 artifact layout remains unchanged:

- `{tenant_id}/{document_group_id}/extracted/{artifact_name}`

Session 4 also adds optional version-aware extracted-artifact paths for
future reruns:

- `{tenant_id}/{document_group_id}/versions/{version_number}/extracted/{artifact_name}`

This closes the Session 3 carry-forward where extracted guidebook HTML
could be written but not read through the storage wrapper.

### Canonical block manifest concept

`CanonicalBlockService` is now the active portfolio dedupe layer for
guidebook extraction. It builds an in-memory
`CanonicalBlockManifest` per tenant/portfolio by:

1. loading the latest completed `guidebook_api` document for each
   property
2. selecting one canonical page occurrence per render type within each
   property
3. filtering empty-content instances before dedupe
4. hashing exact block content by render type
5. classifying each render type into tenant-wide, property-unique,
   clustered-property, or skipped behavior

The manifest stays in-memory per extraction run for v1. No database
table was added for dedupe decisions because the hashing pass is cheap
enough to regenerate and the current need is correctness, not durable
audit history.

### Refined dedupe classification

Empirical Beach Habitats corpus verification corrected and refined the
Phase 4.A assumptions.

Tenant-scope exact duplicates:

- `guide_content.faqs`
- `guide_content.travel_tips`
- `guide_content.departure_instructions`
- `guide_content.rules`
- `widget.messaging_phone_number`
- `widget.phone_number`
- `widget.email_address`
- `widget.website`

These render types have one exact-content hash across all `39`
completed public-guide documents, so the manifest chooses a single
canonical block and marks it tenant-scoped.

Tenant-scope but skipped in Session 4:

- `widget.recommendations`

This is portfolio-wide duplicate provider/recommendation data, but it
is intentionally deferred to the broader platform-intelligence work
instead of entering scoped guest-answer extraction.

Property-scope, fully unique:

- `home.about_note`
- `widget.wifi`
- `widget.getting_here`
- `home.direction_note`

These stay property-scoped because exact-text hashes are unique per
property (or in the case of `home.direction_note`, unique across the
small set of properties where the block appears).

Property-scope with duplicate-group metadata:

- `widget.reservation_info`
- `home.trash_info_note`
- `home.wifi_note`

These render types have meaningful duplicate clusters, but the current
knowledge model still scopes them per property. Session 4 therefore
preserves per-property extraction while attaching deterministic
duplicate-group metadata for future grouped review and potential
`property_group` scope.

### Empty-content filtering

Manifest construction now filters empty-content block instances before
dedupe analysis and records them separately as
`empty_content_property_ids`.

Current Beach Habitats finding:

- `home.wifi_note` has `5` properties where the block is present but
  blank

These are treated as “field present but blank,” not as meaningful
content clusters.

### Canonical page mapping

Canonical page selection now avoids re-extracting the same block
multiple times within a property:

- `home.about_note` -> `Welcome`
- `guide_content.faqs` -> `FAQs`
- `guide_content.departure_instructions` -> `General`
- `widget.wifi` -> `Arrival`
- `widget.reservation_info` -> `Arrival`
- `widget.getting_here` -> `Arrival`
- `home.trash_info_note` -> `General`
- `home.wifi_note` -> `Arrival`
- all other render types -> first occurrence

This page mapping is now code-backed rather than only an analysis note.

### Session 4 skip rules

Skipped render types in the current extraction phase:

- `widget.upsells`
- `guide_content.welcome_message`
- `guide_content.about_us`
- `widget.recommendations`
- `guide_content.safety_info`

Reasoning:

- `widget.upsells` is effectively empty
- `guide_content.welcome_message` and `guide_content.about_us` are low
  knowledge-value greeting/branding content
- `widget.recommendations` is deferred to future recommendation /
  platform-intelligence work
- `guide_content.safety_info` is tenant-wide boilerplate and not yet
  needed for the current operator KB extraction surface

### Beach Habitats manifest result

Production smoke test against Beach Habitats tenant
`e07980b2-a990-4b24-91d1-c8cb71ab70e1`:

- completed guidebook documents analyzed: `39`
- raw blocks across portfolio: `1136`
- canonical blocks after dedupe and skip rules: `220`
- reduction ratio: `80.6338%`

Per-render-type result summary:

- tenant-scope canonicals:
  - `guide_content.departure_instructions` `1`
  - `guide_content.faqs` `1`
  - `guide_content.rules` `1`
  - `guide_content.travel_tips` `1`
  - `widget.email_address` `1`
  - `widget.messaging_phone_number` `1`
  - `widget.phone_number` `1`
  - `widget.website` `1`
- property-scope canonicals:
  - `home.about_note` `39`
  - `home.direction_note` `3`
  - `home.trash_info_note` `36`
  - `home.wifi_note` `17`
  - `widget.getting_here` `39`
  - `widget.reservation_info` `39`
  - `widget.wifi` `39`
- skipped canonical count:
  - `0` materialized for skipped render types because they are excluded
    from the manifest

### Duplicate-group patterns observed

The strongest exact-content cluster patterns now recorded in
`duplicate_group_metadata` are:

- `widget.reservation_info`
  - top groups: `5`, `5`, `4`, `3`, `3`, then several `2`s
- `home.trash_info_note`
  - top groups: `10`, `4`, `4`, `2`, `2`
- `home.wifi_note`
  - top meaningful group: `13`
  - plus `5` empty-content properties filtered out separately

This is the first code-backed evidence that natural property-group-like
patterns exist in Beach Habitats even though the current knowledge model
has only `tenant` and `property` scope.

### Production verification

Production-state verification for 4.B.1 passed:

- Railway deploy `e4f99ecf-a733-4926-bf27-fcc4f711be17` reached
  `SUCCESS`
- `CanonicalBlockService` imported and ran inside the live `oyvoda`
  container
- Beach Habitats manifest build completed successfully against the
  stored production corpus

Representative sample verification:

- tenant FAQ canonical:
  - canonical page id `24793`
  - applies to all `39` properties
  - exact content verified against the `FAQs` page in every property
- property-unique `home.about_note` sample:
  - canonical page id `3362` (`Welcome`)
  - sampled content hash appeared exactly once across the portfolio
- clustered `home.trash_info_note` sample:
  - canonical page id `3364` (`General`)
  - sampled duplicate-group metadata expected `10` members and matched
    `10` real properties in production

### Carry-forward

- Property-group scope evaluation:
  empirical Session 4 manifest data now shows concrete cluster
  candidates in `widget.reservation_info`, `home.trash_info_note`, and
  `home.wifi_note`. When `property_group` becomes a real feature, the
  current deterministic `duplicate_group_metadata` should become one
  input for defining operator-visible groups rather than starting that
  clustering effort from scratch.

### Deterministic typed-block extractors

Session 4.B.2 adds the first non-LLM extraction layer on top of the
canonical manifest:

- `widget.reservation_info`
- `widget.wifi`
- `widget.messaging_phone_number`
- `widget.phone_number`
- `widget.email_address`
- `widget.website`
- `home.direction_note`

These extractors emit deterministic `fact` candidates with:

- `source_type='guidebook'`
- `extraction_method='deterministic'`
- `candidate_type='fact'`
- `confidence=0.98`

Current deterministic field coverage:

- `widget.reservation_info`
  - check-in time
  - check-out time
  - bedroom count
  - bathroom count
  - max occupancy when `guest_count` is present
- `widget.wifi`
  - WiFi network name
  - WiFi password
- contact blocks
  - messaging phone number
  - main phone number
  - email address
  - website
- `home.direction_note`
  - special arrival directions as plain text with HTML stripped

Current topic mapping is intentionally conservative:

- mapped:
  - check-in time -> `check_in_process`
  - bedroom count -> `sleeping_arrangement`
  - max occupancy -> `max_occupancy`
- left `null` for now:
  - check-out time
  - bathroom count
  - WiFi network / password
  - operator contact info
  - direction notes

Reason:

- the current topic registry does not yet have clean topic ids for
  WiFi credentials, operator contact details, bathroom count, or
  direction-note content
- forcing weak topic mappings here would create bad scope/topic
  semantics before the LLM extractor and review surface are in place

Production verification for 4.B.2 used real Beach Habitats canonical
blocks with smoke-test-suffixed question texts to avoid mutating active
operator knowledge semantics while still proving the write path.

Observed production smoke result:

- created deterministic candidates: `8`
- auto-promoted: `8`
- verified scoped outputs:
  - property-scoped check-in time: `4:00 PM`
  - property-scoped check-out time: `9:00 AM`
  - property-scoped bedrooms: `1`
  - property-scoped bathrooms: `5`
  - property-scoped WiFi network:
    `68 Royal Fern or 68 Royal Fern 5G`
  - property-scoped WiFi password: `royaldestinations`
  - tenant-scoped operator email:
    `info@beachhabitats30a.com`
  - property-scoped arrival directions for a direction-note property
- cleanup verification after smoke test:
  - knowledge rows remaining: `0`
  - candidate rows remaining: `0`
  - history rows remaining: `0`

Additional implementation note:

- the first live smoke test surfaced a real production seam:
  `duplicate_group_metadata` still contained raw UUID values and had to
  be normalized to JSON-safe strings before candidate creation. The
  extractor layer now performs that normalization explicitly.

Additional carry-forward:

- topic registry expansion:
  Session 4.B.2 confirmed real near-term topic gaps for WiFi
  credentials, operator contact details, bathroom count, and arrival
  directions. Do not invent topic ids ad hoc in extraction code; add
  them deliberately later if the review/UI experience benefits from
  stronger topic semantics.

### Deterministic rich-content chunkers

Session 4.B.3 adds the pre-LLM chunking layer for Breezeway HTML
blocks. The chunkers operate on canonical blocks and emit stable
`ChunkedContent` records with:

- deterministic `chunk_id`
- `source_block_hash`
- `section_title`
- `order_within_block`
- `content_html`
- `content_text`
- per-chunker metadata

Chunker strategy by render type:

- `guide_content.faqs`
  - split on question markers derived from heading-like `<p>` blocks
    with nested bold/strong text
  - each question + following answer content becomes one chunk
  - orphan question headings are preserved as empty-answer chunks
- `home.about_note`
  - split on heading boundaries
  - supports pseudo-headings where Breezeway uses `<p><b><strong>...`
    rather than semantic `<h*>` tags
  - fallback is single chunk if no headings are detected
- `guide_content.rules`
  - split one chunk per `<li>`
  - fallback to paragraph chunks if the list structure is absent
- `guide_content.departure_instructions`
  - same list-item strategy as `guide_content.rules`
- `guide_content.travel_tips`
  - heading-aware when headings exist
  - otherwise one chunk per non-empty paragraph
- `home.trash_info_note`
  - single chunk by default
  - paragraph fallback only if the note grows unusually large

Implementation note:

- the chunkers use `BeautifulSoup(..., \"html.parser\")` rather than a
  hard dependency on the `lxml` parser backend so they work cleanly in
  local test environments and in production containers
- a follow-up fix in Session 4.B.3 corrected nested `<b><strong>` rich
  text detection, which was necessary for both FAQ question splitting
  and about-note heading detection

Production verification for 4.B.3 ran directly against the live Beach
Habitats canonical corpus after deployment.

Observed chunking metrics:

- `guide_content.faqs`
  - canonical blocks: `1`
  - total chunks: `43`
  - average chunk tokens: `82.14`
  - max chunk tokens: `759`
- `home.about_note`
  - canonical blocks: `39`
  - total chunks: `753`
  - average chunks per canonical block: `19.31`
  - max chunks in one about-note block: `34`
  - average chunk tokens: `74.69`
  - max chunk tokens: `396`
- `guide_content.rules`
  - canonical blocks: `1`
  - total chunks: `8`
  - average chunk tokens: `11.38`
- `guide_content.departure_instructions`
  - canonical blocks: `1`
  - total chunks: `6`
  - average chunk tokens: `14.33`
- `guide_content.travel_tips`
  - canonical blocks: `1`
  - total chunks: `18`
  - average chunk tokens: `11.61`
  - max chunk tokens: `53`
- `home.trash_info_note`
  - canonical blocks: `36`
  - total chunks: `36`
  - average chunks per canonical block: `1`
  - average chunk tokens: `47.14`
  - max chunk tokens: `192`

Representative structural verification:

- FAQ chunk titles now line up with real question text such as:
  - `What is your Cancelation Policy?`
  - `What is your Hurricane Refund Policy?`
  - `Check in details?`
- `home.about_note` now splits into semantically useful sections like:
  - `Watercolor Rental Guest Website:`
  - `Check in:`
  - `Shipping items to the house:`
  - `Parking:`
  - `Door locks:`
  - `Coffee Maker:`
- list-based blocks preserve short atomic items for rules and
  departure tasks

Chunking implication for Session 4.B.4:

- FAQ chunking is now in a healthy range for one-question-per-call LLM
  extraction
- list-based chunkers are already producing atomic low-token chunks
- `home.about_note` is much more granular than the initial estimate,
  which is probably good for extraction accuracy but may create a high
  candidate volume. Review that tradeoff during the first LLM sample
  run rather than changing chunking preemptively.

Additional carry-forward:

- chunker iteration after first LLM pass:
  if Session 4.B.4 shows that `home.about_note` produces too many
  low-value micro-chunks or that some FAQ answers should stay grouped,
  refine chunking after observing real extraction quality rather than
  speculating now.

### Deterministic validation gates

Session 4.B.3.5 adds a conservative validation layer in front of
deterministic auto-promotion so obviously implausible source data does
not land in `concierge_scoped_knowledge` at `0.98` confidence.

Implementation:

- [app/services/extraction/validation_rules.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/extraction/validation_rules.py)
  defines:
  - `ValidationResult`
  - `CompositeValidator`
  - deterministic rules for reservation info, WiFi, contact info, and
    direction notes
- [app/services/extraction/deterministic_extractors.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/extraction/deterministic_extractors.py)
  now applies validation after deterministic extraction and before
  staging

Current deterministic validation rules:

- reservation info:
  - `bathroom_count > bedroom_count + 2` -> `implausible`
  - `bedroom_count == 0 and bed_count > 0` -> `implausible`
  - `bedroom_count > 20` -> `implausible`
  - `bathroom_count > 20` -> `implausible`
  - identical check-in and check-out times -> `implausible`
- WiFi:
  - network present but password blank -> `sparse`
  - network name with control characters or extreme length -> `malformed`
- contact info:
  - bad email format -> `malformed`
  - bad phone format -> `malformed`
  - website missing `http://` or `https://` -> `malformed`
- direction notes:
  - text shorter than `10` characters -> `sparse`

Explicit non-rules for Beach Habitats:

- `guest_count = null` is not a validation signal
- `bed_count = 0` is not a validation signal

Reason:

- Beach Habitats source data currently has `guest_count = null` on
  `39 / 39` public guides
- `bed_count = 0` appears on `30 / 39` guides, so it is too sparse to
  use as a reliable blocker

Validation behavior:

- passed candidates keep deterministic confidence `0.98`
- flagged candidates are annotated with
  `proposed_metadata.validation_concern`
- flagged candidates are tagged `validation_review`
- flagged candidates are downgraded to confidence `0.70`, which keeps
  the existing staging-service auto-promotion logic intact and routes
  them to review instead of auto-promotion

Verification:

- local test suite covering deterministic extractors, validation, and
  staging auto-promotion rules:
  - `40 passed`
- focused Beach Habitats reservation-info re-audit against the live
  Breezeway public guide endpoints found:
  - `68RF` flagged with
    `bathroom_count is more than two above bedroom_count`
  - `38` other properties remained auto-promote-eligible under the
    current conservative rule set

Operator-actionable implication:

- the `68RF` reservation-info candidates will now stage for review with
  a clear validation concern rather than auto-promoting directly
- this gives Beach Habitats an actionable data-quality signal to check
  the upstream Breezeway record for `68 E Royal Fern`

Validation finding `68RF`:

- Breezeway source data surfaced through the public guide API as
  `1BR / 5BA`
- follow-up operator verification identified the actual property as
  `4BR / 4BA`
- the new validation gate triggered correctly and prevented silent
  auto-promotion
- operator action is still needed: correct the upstream Breezeway data
  or edit the staged candidate during review

Regression value:

- when the Session 5 operator review surface lands, `68RF` should
  appear as a validation-flagged staged candidate with enough metadata
  for the operator to understand why it was held and how to correct it

Additional carry-forward:

- validation rules for LLM-extracted candidates:
  deterministic validations work on typed/source-structured fields.
  LLM candidates have a different shape and will need separate
  post-extraction sanity checks once Session 4.B.4 and 4.B.5 are live.

- operator data-quality report:
  Session 5 review surfaces should make validation concerns legible and
  should eventually support a simple operator-facing queue of source
  records worth correcting in Breezeway.

- shared Anthropic client utilities:
  multiple services now call Anthropic directly over `httpx` with
  partially duplicated retry handling, error handling, and accounting
  behavior, including:
  [app/services/messaging_brain/agents/llm_composer_agent.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/llm_composer_agent.py),
  [app/services/messaging_brain/agents/llm_intake_agent.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/agents/llm_intake_agent.py),
  [app/services/concierge/topic_classifier.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/topic_classifier.py),
  [app/services/integrations/llm_email_extractor.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/llm_email_extractor.py),
  the Session 4 extractor path, and
  [app/services/voice/voice_session.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/voice/voice_session.py)
  as an SDK exception. Once the current extraction and review work is
  stable, a shared Anthropic utility should centralize retry rules,
  rate-limit handling, token/cost accounting, and logging.

### LLM extractor for rich-content chunks

Session 4.B.4 adds the Claude Sonnet 4 extraction layer in
[app/services/extraction/llm_extractor.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/extraction/llm_extractor.py).

Design choices:

- direct Anthropic Messages API calls over `httpx.AsyncClient`
- model: `claude-sonnet-4-20250514`
- key source: `ANTHROPIC_API_KEY`
- extractor-local retry loop:
  - retry transient network failures and `5xx`
  - do not retry `4xx`
- topic-registry injection from
  [app/services/concierge/knowledge_topic_registry.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/knowledge_topic_registry.py)
- strict JSON-array parsing with permissive code-fence stripping
- candidate-level validation:
  - `proposed_topic_id` must be in `TOPIC_REGISTRY` or `null`
  - `confidence` must be between `0.0` and `1.0`
  - required fields must be present
  - `evidence_excerpt` must appear in the source chunk text

Prompt strategy:

- repeated "explicit only" framing
- explicit `DO NOT` section to fight helpfulness drift
- explicit `WHEN UNCERTAIN` section
- repeated instruction to copy `evidence_excerpt` exactly from the
  source text
- repeated instruction to split multi-branch policy content into one
  candidate per explicit branch

Real sample verification on `203WW`:

- cancellation-policy FAQ chunk:
  - `3` candidates
  - all `conditional=true`
  - all `topic_id=cancellation_policy`
  - all evidence excerpts passed substring verification
  - sample cost: `$0.009978`
  - latency: `5213 ms`
- `Check in:` about-note chunk:
  - `4` candidates
  - extracted:
    - check-in time
    - early code delivery when the property is ready
    - early check-in not guaranteed
    - housekeeping departure does not mean the property is ready
  - all evidence excerpts passed substring verification
  - sample cost: `$0.012708`
  - latency: `6434 ms`
- quiet-hours rules chunk:
  - `1` candidate
  - `topic_id=null`
  - evidence excerpt passed substring verification
  - sample cost: `$0.006081`
  - latency: `3162 ms`

Prompt tuning outcome:

- the first live pass collapsed the cancellation policy into one broad
  candidate and produced one near-miss evidence excerpt on an
  early-check-in fact
- after strengthening the prompt around exact-copy evidence and
  explicit policy-branch atomization, the cancellation chunk cleanly
  split into `3` conditional candidates and the dropped early-check-in
  candidate was recovered with valid evidence

Additional cross-property spot checks:

- `100SL2C` `home.trash_info_note`
  - `1` grounded candidate
  - cost: `$0.005553`
- `103CPW` `home.about_note` parking section
  - `2` grounded parking candidates
  - both mapped to `parking`
  - cost: `$0.007482`
- `111VW` departure-instructions chunk
  - `1` grounded departure candidate
  - cost: `$0.005433`

Aggregate sample cost:

- first three chunks: `$0.028767`
- additional three chunks: `$0.018468`
- total verification spend: `$0.047235`

Observed quality:

- cancellation-policy extraction now lands in the expected `3-5` fact
  range for the sampled chunk
- topic mapping is conservative and valid:
  - known fits like `cancellation_policy`, `check_in_process`,
    `early_check_in`, and `parking` were used correctly
  - unmatched facts stayed `null`
- confidence calibration looks reasonable:
  - `0.95` for explicit policy/list facts
  - `0.92-0.94` for prose extraction with light normalization

Carry-forward:

- LLM-specific validation:
  the current guardrail is strong on evidence and topic validity, but
  future review work may still want second-pass checks for overly broad
  paraphrases or low-value micro-facts.

- prompt iteration from operator review:
  the prompt is good enough to proceed into orchestrator work, but
  operator review patterns in Session 5 should feed future prompt and
  routing refinements.

- prompt iteration log discipline:
  Session 4.B.4 already required one prompt revision:
  - v1 collapsed the cancellation-policy chunk into one broad
    candidate
  - v2 added explicit branch-by-branch policy splitting and stricter
    exact-copy evidence guidance, which produced `3` atomized
    conditional facts
Future prompt tuning should keep the same discipline:
  1. record the extraction-quality failure
  2. record the prompt change made
  3. re-run the affected sample set
  4. preserve the lesson for similar content types

### Orchestrator wiring

Session 4.B.5 adds
[app/services/extraction/extractor_orchestrator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/extraction/extractor_orchestrator.py)
as the composition layer for the extraction stack.

The orchestrator ties together:

- [app/services/extraction/canonical_block_service.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/extraction/canonical_block_service.py)
- [app/services/extraction/deterministic_extractors.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/extraction/deterministic_extractors.py)
- [app/services/extraction/chunkers.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/extraction/chunkers.py)
- [app/services/extraction/llm_extractor.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/extraction/llm_extractor.py)
- [app/services/extraction/staging_service.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/extraction/staging_service.py)

Per-document behavior:

- loads the target `guidebook_api` document
- finds canonical blocks that apply to that document's property
- runs deterministic extraction where typed extractors exist
- runs chunking + Claude extraction where rich-content chunkers exist
- creates extraction candidates through the staging service
- runs the existing auto-promotion path on the newly created
  candidates
- returns a run summary with:
  - candidates created
  - auto-promoted vs. staged counts
  - deterministic vs. LLM counts
  - failed block and failed chunk counts
  - token, cost, and latency totals

Per-portfolio behavior:

- builds the canonical manifest once per tenant
- processes documents with bounded concurrency
- avoids duplicate tenant-scope extraction by only processing
  tenant-scope canonical blocks on the canonical source property
  during portfolio runs
- aggregates document metrics into a portfolio-level run summary

Unit verification:

- focused orchestrator suite added in
  [tests/unit/test_extractor_orchestrator.py](/Users/dhuntermckenzie/Downloads/oyvoda/tests/unit/test_extractor_orchestrator.py)
- covered:
  - mixed deterministic + LLM routing
  - correct tenant vs. property scope handling
  - tenant-scope extraction happening once per portfolio run
  - block-failure isolation so one bad rich-content block does not
    fail the whole document

Phase boundary:

- Session 4.B.5 stops at orchestrator implementation and smoke-test
  readiness
- the full Beach Habitats extraction run remains Phase 4.B.7

## Phase X.2: Inbox Poller Bleeding Stop

Root cause confirmed on May 12, 2026:

- background inbox polling was repeatedly sending the same dead-end
  Gmail messages through
  [app/services/integrations/llm_email_extractor.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/llm_email_extractor.py)
  every 5 minutes
- the hot path was dominated by:
  - `invalid_schema:json_invalid`
  - OTA parser fallbacks with `message_body:MISSING`
  - generic non-actionable messages that never reached successful
    routing
- these failure paths did not durably mark the message as seen, so
  `recent_inbox` polling kept re-fetching them
- the API web service was also still capable of starting an embedded
  Gmail polling worker, while Celery beat was already scheduling the
  authoritative inbox poll every 5 minutes

Immediate fix landed in commit `594d8e8`
`fix(inbox): stop repeated LLM parsing of failed messages`.

Code changes:

- [app/services/integrations/gmail_inbox_poller.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/gmail_inbox_poller.py)
  now tracks message-processing status beyond simple success:
  - `processed`
  - `non_guest`
  - `failed_retryable`
  - `quarantined`
- retryable parse failures now increment a durable `failure_count`
  keyed by `gmail_message_id`
- after `3` failures, the message is quarantined, labeled, and
  excluded from future `recent_inbox` replay
- non-guest / non-actionable messages are now recorded as terminal
  seen-state immediately instead of being retried forever
- poller result metrics now distinguish ordinary
  `already_processed_skips` from `quarantined_skips`

Schema support:

- new Alembic migration:
  [db/migrations/versions/062_gmail_processed_message_statuses.py](/Users/dhuntermckenzie/Downloads/oyvoda/db/migrations/versions/062_gmail_processed_message_statuses.py)
- `gmail_processed_messages` now carries:
  - `processing_status`
  - `failure_count`
  - `last_failure_reason`
  - `first_seen_at`
  - `last_attempted_at`
- the poller also performs a defensive runtime schema-ensure so the
  hotfix remains safe during rollout windows

Single-poller decision:

- [app/core/config.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/core/config.py)
  now defaults `run_gmail_polling_worker` to `False`
- Celery beat remains the authoritative scheduler for inbox polling
- the web/API process no longer starts the embedded Gmail poller by
  default

Live parse-failure audit before rollout:

- sampled failures were overwhelmingly safe to quarantine:
  - `ota:airbnb` and `ota:vrbo` messages with
    `message_body:MISSING`
  - `generic_email:direct` threads repeatedly returning
    `invalid_schema:json_invalid`
  - direct website-form traffic failing with
    `empty_latest_guest_message`
- repeated `source_message_id` values were visible across multiple
  5-minute polls, confirming the replay loop was real

Production verification:

- deploy statuses after push:
  - `oyvoda`: `e7e1c04c-b8ed-4306-918b-7c1e88c507a6` `SUCCESS`
  - `oyvoda-worker`: `920f6c58-2609-46fd-8676-c1346c2ebac4`
    `SUCCESS`
  - `oyvoda-beat`: `94d91673-a323-4f28-bc0d-2fb4b096739b`
    `SUCCESS`
- API startup logs now show:
  - `Gmail polling worker disabled for this web process`
- worker behavior after rollout improved materially:
  - pre-fix at `18:10`:
    - `mode=recent_inbox found=25 processed=0`
    - dozens of `LLMEmailExtractor` starts
    - repeated Anthropic / Groq fallback churn
  - post-fix at `18:20` and `18:25`:
    - `mode=unread found=1 processed=0`
    - `already_processed_skips=1`
    - no new `LLMEmailExtractor` starts in the sampled post-fix log
      window

Observed effect:

- the wasteful replay loop appears to be stopped
- the remaining unread message is being skipped as already-seen
  instead of being re-sent through Anthropic every poll cycle
- this should cut the dominant background Anthropic waste from the
  earlier X.1 audit down to near-zero except for genuinely new inbox
  traffic

Estimated savings:

- earlier audit measured roughly `199` Anthropic POST attempts/hour
  from the inbox path during the churn window
- the exact dollar savings will depend on real new-message volume, but
  this hotfix removes the clearly non-business-value portion of that
  spend

Carry-forward:

- deterministic-first inbox parsing:
  move
  [app/services/integrations/llm_email_extractor.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/llm_email_extractor.py)
  toward optional / last-resort usage instead of first-line parsing

- LLMEmailExtractor contract quality:
  the `invalid_schema` rate is still too high and needs a separate
  parser-contract improvement pass

- quarantined-message quality audit:
  after `7-14` days of post-fix data accumulation, review the next
  `30-50` quarantined messages and estimate the false-quarantine rate
  across:
  - website-form variations
  - HTML-heavy direct emails
  - edge-case guest inquiry structures
  If the false-quarantine rate is above roughly `5%`, prioritize a
  parser redesign with:
  - deterministic-first parsing for headers and known form formats
  - LLM reserved for content interpretation instead of basic message
    parsing
  - better failure modes that preserve the original message for manual
    operator review
  - fallback parsers for recurring known formats
  Estimated scope:
  - `2-3 hours` for the audit
  - `4-6 hours` for redesign work if needed
  Priority should be treated as high if false quarantines are shown to
  affect the operator value proposition.

- background-service waste audit:
  review all pollers and scheduled jobs for similar replay / retry
  patterns before more operators are onboarded

- operator-app metrics:
  `gmail_processed_messages` now contains terminal non-success states,
  so any dashboards that interpret that table as "successfully
  processed mail only" should be revisited in a later polish pass

- per-operator cost attribution:
  add durable spend telemetry so issues like this surface before they
  burn multiple days of LLM credits
