# Brief — Gap 1: Stage knowledge at property_group (neighborhood/HOA) scope

For Claude Code. Build-ready. Read OYVODA_AUDIT_KNOWLEDGE_INGESTION_LAYER.md first. This is
the wiring-seam fix: the write service and read service both support property_group scope, but
the STAGING service in the middle rejects it, so neighborhood/HOA facts can't flow end-to-end.
Small, no migration, high-leverage.

## The gap (verified in code)
- `extraction_candidates.scope_type` is `TEXT NOT NULL` with NO db CHECK constraint
  (migration 061). The DB already accepts 'property_group'.
- `concierge_scoped_knowledge` scope_type is also free TEXT; scoped_knowledge_service
  `_ALLOWED_SCOPE_TYPES = {"property", "tenant", "property_group"}` ALREADY allows it on write.
- The brain's read path (get_effective_knowledge_for_property) ALREADY resolves
  tenant -> property_group -> property with most-specific-wins.
- THE ONLY BLOCKER: `ExtractionStagingService._ALLOWED_SCOPE_TYPES = {"property", "tenant"}`
  in app/services/extraction/staging_service.py — missing "property_group". So a group-scoped
  candidate is rejected at create_candidate(). This is the seam.

## The fix (pure code, no migration)

### 1. staging_service.py — allow property_group
- Add "property_group" to `ExtractionStagingService._ALLOWED_SCOPE_TYPES`.
- In `_promote_candidate`, the `candidate_type == "fact"` path calls
  write_scoped_knowledge(scope_type=candidate.scope_type, scope_target_id=candidate.scope_target_id, ...).
  That already passes scope_type through and the write service accepts 'property_group' +
  a group_id as scope_target_id. VERIFY this path needs no change for facts (it shouldn't).
- The `candidate_type == "asset"` path calls `_resolve_property_code(scope_target_id=...)` which
  queries `properties WHERE property_id = scope_target_id`. For a property_group-scoped ASSET this
  would FAIL (the id is a group, not a property). DECISION: assets are property-specific by nature;
  group-scoped ASSET candidates are likely invalid. Guard it: if candidate_type=='asset' and
  scope_type=='property_group', reject with a clear error (assets don't have a group scope) rather
  than mis-resolving. Facts and document_metadata are the group-scoped types that make sense.
- `_resolve_property_code` also uses `properties.property_id` — NOTE: elsewhere this session the
  live column was confirmed to be `properties.id`, not `properties.property_id`. VERIFY which is
  correct in the live schema before relying on this path; if it's `id`, this is a latent bug to fix
  while here (but only fix if confirmed — don't guess).

### 2. Confirm the extractors can EMIT group scope
- deterministic_extractors.py / llm_extractor.py produce ExtractionCandidatePayload with
  scope_type/scope_target_id. Check whether anything can currently produce scope_type='property_group'.
  Likely they only emit 'property'/'tenant' today. For THIS brick, it's enough that the staging
  layer ACCEPTS group scope (so the learning loop and manual/operator paths can stage group facts);
  having the document extractors auto-detect "this is an HOA-level fact" is a LATER enhancement
  (relates to Gap 4 proactive surfacing). Do NOT build extractor auto-grouping here — just unblock
  the staging+promotion+read path so a group-scoped candidate created by ANY source flows through.

### 3. Verify the canonical block scope path
extractor_orchestrator `_blocks_for_document` and CanonicalBlock have a `scope_type`. Confirm that
if a block were group-scoped, nothing downstream hard-assumes property/tenant only. Likely fine
(scope_type is passed through as a string), but check the promotion + asset paths per #1.

## Verification (prove the seam is closed end-to-end)
Write a focused test (tests/) that:
1. Creates a property_group + a property_group_membership for a test property (or uses Beach
   Habitats once memberships exist).
2. Stages a `fact` candidate with scope_type='property_group', scope_target_id=<group_id>.
3. Approves/promotes it -> confirms it lands in concierge_scoped_knowledge with
   scope_type='property_group'.
4. Calls get_effective_knowledge_for_property(member_property) -> confirms the group-scoped fact
   appears in the effective knowledge (proves inheritance reads it).
5. (If feasible) a guest-answer path test: a question answerable only by that group fact resolves
   correctly for the member property.
This is the end-to-end proof that neighborhood/HOA knowledge flows: stage -> promote -> store ->
inherit -> available to outgoing messages.

## Scope guards
- No migration (scope_type is free TEXT). If you find a hidden CHECK constraint, STOP and report.
- Do NOT build document-extractor auto-grouping (Gap 4 territory).
- Do NOT touch the read-side inheritance (already correct) except to verify it.
- Asset candidates at group scope: reject cleanly, don't mis-resolve.
- Fix _resolve_property_code's column (property_id vs id) ONLY if confirmed wrong in live schema.

## Done when
- staging_service accepts and promotes property_group-scoped fact candidates.
- A group-scoped fact, staged + promoted, is readable via get_effective_knowledge_for_property for
  a member property (test proves it).
- Asset@group-scope rejected with a clear error; facts/document_metadata@group-scope work.
- tsc N/A (backend); unit test added and passing.
- Commit SHA. Note: this unblocks neighborhood/HOA knowledge end-to-end and is the prerequisite for
  Gap 4 (proactive group-gap surfacing) and the learning loop's neighborhood tier.
