# Brief — Gap 4: Proactive neighborhood/HOA knowledge-gap surfacing

For Claude Code. Build-ready. Read OYVODA_AUDIT_KNOWLEDGE_INGESTION_LAYER.md, the Gap 1 brief
(group-scope staging, 9916f13 done), and topic_registry.py first. This is the genuinely NEW
capability Hunter asked for: if a property is in a neighborhood and HOA rules / required vendors
/ gate codes apply but aren't on file, SURFACE it proactively — don't wait for a guest to ask.

## Key finding from the registry read (shapes the whole brief)
TOPIC_REGISTRY (app/services/messaging_brain/knowledge/topic_registry.py) has 27 topics, ALL
property-level (pool, pet, parking, check_in, trash, quiet_hours, smoking, local_area, etc.).
There are NO HOA / required-vendor / gate-code / community-access topics. `local_area` (tagged
"neighborhood", gap_severity="review", has community_name schema field) is the only group-ish one.
So the "expected at group scope" vocabulary does NOT exist yet. Gap 4 must DEFINE it first
(Part A), then check coverage against it (Part B).

## Part A — extend the topic registry with group-scope vocabulary
1. Add a field to KnowledgeTopicDefinition marking group-relevance. RECOMMENDATION:
   `expected_at_group_scope: bool = False` (simplest) OR `applicable_scopes: Tuple[str,...] =
   ("property",)`. Prefer the explicit bool for v1 clarity. Single source of truth — do NOT make a
   separate parallel list that can drift from the registry.
2. Add NEW group-relevant topics (the vocabulary that doesn't exist today):
   - `hoa_rules` — HOA policies governing the community (the core one).
   - `required_vendors` — vendors that MUST/should be used (e.g. golf-cart rental approved vendors,
     with phone numbers — the VRBO golf-cart example: not "must be HOA approved" but "here are the
     vendors + numbers"). closed_world_rule kb_only; gap_severity "review".
   - `gate_code` / `community_access` — gate codes, access procedures for the community.
   - `community_amenities` — shared pools, beach access points, community facilities.
   Mark these expected_at_group_scope=True.
3. Mark EXISTING topics that are legitimately group-expectable (optional, conservative): parking,
   quiet_hours, trash_disposal, local_area can be neighborhood/HOA-wide. Mark the ones that clearly
   apply HOA-wide as expected_at_group_scope=True. Be conservative — only mark ones that genuinely
   recur at the community level. (A topic being group-expected does NOT prevent property-scope
   overrides — the inheritance hierarchy already handles override.)
   Note negative_closure/dependent rules already exist on topics — don't disturb them.

## Part B — proactive per-group coverage check (the surfacing)
A new service (e.g. app/services/messaging_brain/knowledge/group_gap_surfacer.py or extend an
existing knowledge-health service):
- For each property_group for the tenant WHERE the group has >=1 member property
  (property_group_memberships) AND group is active:
  - expected = {topics where expected_at_group_scope is True}
  - present = {topic_ids that have a concierge_scoped_knowledge entry at scope_type='property_group',
    scope_target_id=group_id, is_active}
  - missing = expected - present
  - For each missing topic, surface a structural gap: group name, member count, missing topic.
- Output shape: per-group list of missing expected topics, e.g.
  {group: "WaterSound", member_count: 12, missing: ["hoa_rules","required_vendors","gate_code"]}.
- This is PROACTIVE/structural — driven by "group exists + has members + expected topic absent",
  NOT by guest questions (that's the existing reactive concierge_knowledge_gaps path). Keep the two
  distinct: reactive gaps = unanswered guest questions; structural gaps = expected-coverage holes.

## Honesty / scope discipline (same rules as the whole session)
- Absence of a GROUP is not a gap. Only groups that EXIST with members get checked. A property with
  no group membership is not flagged (it's a valid non-grouped property).
- This is expected-TOPIC coverage, NOT open-ended AI guessing about what a neighborhood "should"
  have. Bounded to the registry's expected_at_group_scope set. No hallucinated requirements.
- A surfaced structural gap is a PROMPT to the operator ("WaterSound has no HOA policy on file —
  add one?"), not an error and not auto-filled. Operator fills it once at group scope -> all members
  inherit (Gap 1 made group-scope writable; the read path already inherits).
- Don't double-count: if a topic exists at tenant scope that covers it, decide whether that
  satisfies the group expectation. RECOMMENDATION: group-expected means "should be answerable for
  member properties" — if a tenant-scope entry already answers it, it's arguably covered. For v1,
  check group-scope presence specifically (the point is neighborhood-specific rules), but note this
  decision so it's deliberate.

## Surfacing location
- Expose via an endpoint/service the operator dashboard can read. Most natural home: Property
  Readiness (the trust console) or a Knowledge Health view — per-neighborhood "missing expected
  knowledge" list. Backend service + endpoint in this brick; the frontend surface can be a
  follow-up wire-up (note it, don't necessarily build the UI here unless cheap).
- Connects to onboarding (Gap 3 / signup): the same check run at signup is the "we found 31
  communities, 14 missing HOA rules" experience from the vision.

## Dependencies / sequencing
- Depends on Gap 1 (group-scope staging, DONE) so a surfaced gap is fillable at group scope.
- Beach Habitats group memberships are EMPTY (Gap 3) — so for the live tenant this will surface
  "no groups with members" until Gap 3 populates them. That's correct/honest. Test with seeded
  groups+members; real data lights up after Gap 3.
- Gap 2's confidence/verified columns let the surfacer ALSO flag "group has an HOA entry but it's
  low-confidence / unverified" as a softer gap — OPTIONAL for v1, note it as an extension.

## Verification
- Seed a property_group with 2 member properties, no group-scoped entries -> surfacer reports the
  full expected set as missing for that group.
- Add a group-scoped hoa_rules entry -> surfacer drops hoa_rules from missing for that group.
- A group with no members -> not reported. A property with no group -> not reported.
- Unit tests for the coverage math (expected - present) and the honesty rules (no group => no gap).

## Scope guards
- Registry extension is additive (new field defaults False, new topics appended). Don't break
  existing topic resolution / negative-closure rules.
- No change to the reactive guest-question gap path (concierge_knowledge_gaps).
- Structural surfacing is read-only analysis + an endpoint; it does not auto-write knowledge.
- Frontend UI optional in this brick (backend service + endpoint required; note UI as follow-up).

## Done when
- KnowledgeTopicDefinition has a group-scope marker; hoa_rules/required_vendors/gate_code/
  community_amenities topics added and marked group-expected; conservative existing topics marked.
- A surfacer service computes per-group missing expected topics (expected - present at group scope).
- Endpoint exposes it for the dashboard; honesty rules hold (no group/no members => nothing surfaced).
- Unit tests cover coverage math + honesty rules.
- Commit SHA. Note: this is the proactive "ask for what the neighborhood needs" capability; combined
  with Gap 1 (fillable at group scope) and Gap 3 (memberships), it closes the neighborhood/HOA loop.
