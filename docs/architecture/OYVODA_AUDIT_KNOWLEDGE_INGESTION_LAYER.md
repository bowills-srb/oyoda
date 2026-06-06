# Audit — Operator Knowledge / Ingestion Layer (findings + implementation plan)

Status as of this session. Grounded in actual code reads, not the vision doc. Purpose:
answer "is the knowledge/data layer robust and WIRED to outgoing guest messages, and where
are the gaps." Short answer: the spine is built and wired; there are 4 specific, bounded
gaps. This doc records the architecture-as-it-actually-connects and the implementation plan.

## THE ARCHITECTURE AS IT ACTUALLY CONNECTS (verified)

```
SOURCES (documents: guidebook_api, PDFs, etc.)
  -> extraction/extractor_orchestrator.py
       deterministic_extractors (fast path) -> LLM extractor (fallback only if no deterministic)
  -> extraction/staging_service.py  (extraction_candidates table)
       confidence-scored candidates; auto_promote_eligible() OR stage-for-review
  -> on approve/auto-promote: writes via scoped_knowledge_service.write_scoped_knowledge()
  -> concierge_scoped_knowledge  (versioned + history + sourced + scoped)
  -> READ by messaging_brain/knowledge/scoped_knowledge_service.get_effective_knowledge_for_property()
       resolves tenant -> property_group -> property, MOST-SPECIFIC-WINS (override hierarchy)
  -> feeds guest answers
```

This is ONE connected path. The fear "a layer that isn't wired to outgoing messages" is NOT
the reality: the brain's scoped_knowledge_service reads the same store extraction writes.

## WHAT'S BUILT AND WIRED (a lot)

- **Scoped knowledge store** (concierge_scoped_knowledge, migration 059): scope_type is TEXT
  (no enum migration needed for new scopes), versioned (`version` + full
  concierge_scoped_knowledge_history table on every create/update), sourced (`source` required +
  created_by_user_id), override-capable (uniqueness keyed on scope, so portfolio/group/property
  hold different answers to the same question_key). Advisory-locked writes (race-safe).
- **Entity hierarchy**: properties + property_groups (group_type 'condo_complex'/'HOA zone' = the
  community/neighborhood tier) + property_group_memberships (M2M; absence-of-membership is a valid
  non-gap state). canonical_property_refs for ID resolution.
- **Read-side inheritance — ALREADY BUILT**: scoped_knowledge_service.get_effective_knowledge_for_property
  loads tenant entries, looks up the property's groups, loads each group's entries, loads property
  entries, merges most-specific-wins. The neighborhood/HOA inheritance + override hierarchy the
  vision describes is IMPLEMENTED. _ALLOWED_SCOPE_TYPES = {property, tenant, property_group}.
- **Extraction pipeline**: deterministic-first then LLM, staging with confidence, auto-promote
  (deterministic + conf>=0.95, or pms + conf>=0.99) vs stage-for-review. Per-document and
  per-portfolio (extract_for_portfolio). Promotes facts -> scoped knowledge, assets -> property
  assets, doc metadata -> documents.

## THE 4 REAL GAPS (bounded; this is the implementation plan)

### GAP 1 — staging_service can't stage at property_group scope (THE wiring seam)
`ExtractionStagingService._ALLOWED_SCOPE_TYPES = {"property", "tenant"}` — MISSING
"property_group". The write service and read service BOTH support property_group, but the
STAGING layer in between rejects it. So extraction cannot propose a neighborhood/HOA-scoped fact
even though the rest of the chain handles it. This is the exact "built but not wired through"
seam. FIX: add "property_group" to staging's allowed scope types; ensure _promote_candidate and
_resolve_property_code paths handle group-scoped candidates (a group-scoped fact promotes to
scoped knowledge with scope_type='property_group', scope_target_id=group_id — the write service
already accepts this). Small, high-leverage.

### GAP 2 — confidence / verified-date are not queryable columns
confidence flows through extraction as a real field and lands in concierge_scoped_knowledge
`metadata` JSONB, not as columns. For provenance UI ("click to see source/confidence/verified")
and querying ("show me low-confidence facts to review"), promote to first-class columns on
concierge_scoped_knowledge: `confidence NUMERIC`, `last_verified_at TIMESTAMPTZ`,
`verified_by_user_id UUID`. Reversible migration; backfill confidence from metadata; update
write_scoped_knowledge + promotion to set them. (source already exists as a column.)

### GAP 3 — group memberships are EMPTY for the live tenant
property_group_memberships count = 0 for Beach Habitats. The inheritance machine is built and
idle for lack of data. Populate group memberships (which properties are in WaterSound / WaterColor
/ Seaside). This is onboarding/data-entry, not code — and ties to GAP 4 (gap surfacing) and to the
signup flow ("which properties belong to this neighborhood?").

### GAP 4 — NEIGHBORHOOD/HOA GAP SURFACING (Hunter's explicit ask)
The system must SURFACE missing neighborhood knowledge: if a property is part of a neighborhood
and HOA rules / required vendors / gate codes / etc. apply but aren't present, flag it. Today,
gap detection (concierge_knowledge_gaps) is driven by guest questions that go unanswered (reactive).
What's needed is PROACTIVE structural gap detection at the group level:
- For each property_group: does it have HOA-policy knowledge? required-vendor knowledge? access/
  gate knowledge? If a group has member properties but no group-scoped entries for expected
  topics, that's a surfaced gap: "WaterSound has 12 properties but no HOA policy on file."
- Drive it off the TOPIC_REGISTRY (the canonical topic list) x expected-at-group-scope: certain
  topics (HOA rules, gate codes, community amenities, required vendors) are EXPECTED to exist at
  group scope when a group exists. Missing => surfaced gap.
- Surface in Property Readiness / a knowledge-gap view: per-group "expected but missing" topics,
  so the operator can fill them once and all member properties inherit.
This is the "ask for what it thinks it needs" behavior from the vision, scoped to the achievable:
group-level expected-topic coverage check, not open-ended AI guessing.

## IMPLEMENTATION SEQUENCE
1. GAP 1 (staging property_group scope) — smallest, unblocks neighborhood facts end-to-end.
2. GAP 2 (confidence/verified columns) — migration + write-path + backfill.
3. GAP 4 (proactive group-gap surfacing) — the operator-facing "what's missing per neighborhood".
4. GAP 3 (populate memberships) — data/onboarding; can run in parallel; without it 1/3/4 have
   nothing to act on for Beach Habitats.
Then: the LEARNING LOOP sits on top as another writer into write_scoped_knowledge via the SAME
staging/review pipeline — operator edit -> decompose -> propose scoped candidate (one-off /
property / property_group / tenant) -> staging review queue (already built). The learning loop is
a new SOURCE feeding the existing ingestion pipeline, not a new system.

## VERIFICATION (the wiring must hold end-to-end)
- A property_group-scoped fact can be: extracted -> staged -> promoted -> read back via
  get_effective_knowledge_for_property for a member property (proves GAP 1 + inheritance).
- A guest question answerable only by a group-scoped HOA rule gets the right answer for a member
  property (proves the store actually supports outgoing messages at group scope).
- Confidence/verified queryable as columns (GAP 2).
- A group with members but missing expected topics shows as a surfaced gap (GAP 4).

## SCOPE GUARD (don't boil the ocean)
The vision doc's full platform (multi-PMS connectors, website scraping, MCP crawlers, markets/
buildings tiers, entity-resolution-at-scale) is REAL future work but NOT a prerequisite for any of
the above. The spine is built; this plan completes the seams + adds proactive group-gap surfacing.
Do these 4 gaps; defer the platform.
