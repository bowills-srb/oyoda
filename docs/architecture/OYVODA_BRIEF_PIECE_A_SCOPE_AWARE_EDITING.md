# Brief — Piece A: Scope-aware operator knowledge editing (incl. property_group)

For Claude Code. Build-ready. Read OYVODA_AUDIT_KNOWLEDGE_INGESTION_LAYER.md and the Gap 1-4
briefs first. This makes operators able to VIEW, CREATE, EDIT, and DELETE knowledge entries at
ALL scopes — including the property_group (neighborhood) scope that Gap 4 surfaces gaps for but
the dashboard currently can't write. This is "fix it if something's wrong, at any scope," AND it
is the front half of the learning loop (same scope-aware operator write path).

## The gap (verified in dashboard_kb_service.py)
The backend (write_scoped_knowledge, read inheritance) fully supports property_group scope. The
OPERATOR-FACING dashboard service does NOT:
- `_resolve_scope` only ever returns scope_type 'property' (if property given) or 'tenant'
  (fallthrough). No property_group branch — an operator CANNOT create a neighborhood entry.
- `list_dashboard_entries` filters `scope_type IN ('tenant','property')` — group entries are
  INVISIBLE in the operator's KB list (an HOA rule staged at WaterSound scope can't be seen/edited).
- `count_dashboard_entries` same `IN ('tenant','property')` — group entries uncounted.
So Gap 4 surfaces "WaterSound needs an HOA policy," but the operator has no dashboard path to
write it at group scope, and can't see/edit it if it was staged. This brick closes that.

## The fix — extend dashboard_kb_service to be scope-aware (all four tiers)

### 1. _resolve_scope — add property_group resolution
Accept an optional `property_group_id` (and/or a group name/community). Resolution precedence:
property_id -> property scope; property_group_id -> property_group scope (validate the group
exists for the tenant, return scope_type='property_group', scope_target_id=group_id, a
group_label = the group name); else tenant. Keep existing property/tenant behavior unchanged.
NOTE: "one-off" is NOT a stored scope — it's the learning-loop "don't write" choice (Piece B).
Piece A handles the three WRITABLE scopes: property, property_group, tenant.

### 2. list_dashboard_entries — include property_group, label them, allow filtering by group
- Change `scope_type IN ('tenant','property')` to include 'property_group'.
- LEFT JOIN property_groups so a group entry gets a readable property_label (the group name, e.g.
  "WaterSound") and is visibly distinguished as a neighborhood entry (add a field like
  scope_label / scope_kind in the returned dict: 'All Properties' | property_code | group name).
- Allow an optional group filter (list entries for a given group) parallel to the property_ref filter.
- Ordering: keep tenant first, then groups, then properties (or a sensible grouping) so the operator
  sees portfolio -> neighborhood -> property, mirroring the inheritance hierarchy.

### 3. count_dashboard_entries — include property_group
Change the IN clause to include 'property_group'. (Note: this count feeds dashboards; including
group entries is correct — they're real operator knowledge.)

### 4. create/update/delete — already write through; just ensure scope flows
- create_dashboard_entry: accept property_group_id, pass to _resolve_scope. The INSERT already
  writes scope_type/scope_target_id from the resolved scope — so group scope flows once _resolve_scope
  returns it. Verify the verified_at/by (Gap 2) honesty holds: operator-authored group entry =
  human-written = verified_at set, confidence NULL. Same as property/tenant.
- update_dashboard_entry / delete_dashboard_entry: keyed on knowledge_entry_id + tenant_id, so they
  already work for group entries REGARDLESS of scope — once those entries are VISIBLE (fix #2), the
  operator can edit/delete them. Verify no scope-type assumption blocks a group entry update.

### 5. Endpoint / API surface
Wherever the dashboard KB endpoints live (operator_dashboard_*_api.py), thread the
property_group_id param through create/list so the frontend can target a group. Backend + endpoint
in this brick; the frontend UI (a scope picker: All Properties / Neighborhood / specific Property)
is a follow-up wire-up — note it, build only if cheap.

## Why this is the front half of the learning loop
Piece B (learning loop) is: operator edits a DRAFT -> decompose -> choose scope (one-off / property
/ neighborhood / portfolio) -> write. That "choose scope -> write at that scope" machinery is
EXACTLY what Piece A builds for direct entry editing. Piece B adds the draft-decomposition and the
proposal/staging-review front end; the scope-aware write path underneath is shared. Build A first;
B reuses it.

## Honesty / correctness (same discipline)
- Operator edits/creates = human-authored = verified_at set, confidence NULL (Gap 2 semantics). Holds
  for group scope too.
- Editing a group entry corrects it for ALL member properties at once (the inheritance read path) —
  that's the power and the responsibility; the UI (follow-up) should make the scope clear so an
  operator knows "this changes the answer for all 12 WaterSound properties."
- Override hierarchy intact: a property-scope entry still overrides a group entry for that property.
  Editing the group entry doesn't touch property-level overrides. (Most-specific-wins already handles this.)
- Delete is soft (is_active=FALSE) — reversible, keeps history. Unchanged.

## Verification
- Create a group-scoped entry via the dashboard service for a real Beach Habitats group (e.g.
  WaterSound) -> it lands scope_type='property_group', verified_at set.
- list_dashboard_entries returns it, labeled with the group name, distinguishable from property/tenant.
- get_effective_knowledge_for_property for a WaterSound member returns it (inheritance).
- Edit it -> answer changes for all members. Delete it -> soft-deleted, drops from member inheritance.
- Confirm Gap 4 surfacer now shows that topic as COVERED for the group (closes Gap4 -> fill -> covered loop).
- Property-scope and tenant-scope editing still work unchanged (regression).

## Scope guards
- Additive: don't break existing property/tenant create/list/edit/delete.
- No 'one-off' scope here (that's Piece B's non-write choice).
- Frontend scope-picker UI optional in this brick (backend + endpoint required; note UI follow-up).
- Don't change write_scoped_knowledge or read inheritance (already correct) — only the dashboard
  service's scope handling + list/count filters.

## Done when
- dashboard_kb_service resolves, lists, counts, creates, updates, deletes at property_group scope
  (plus existing property/tenant). Group entries visible + labeled in the KB list.
- Operator can fill a Gap-4-surfaced neighborhood gap directly via the dashboard path; members inherit;
  Gap 4 then shows it covered.
- Gap 2 verified_at/confidence semantics hold for group entries.
- Endpoint threads property_group_id. Unit tests cover group create/list/edit/delete + inheritance +
  the Gap4 cover-the-gap loop + property/tenant regression.
- Commit SHA. Note: this answers "can an operator correct any entry at any scope" (YES, now incl.
  neighborhood) AND is the shared scope-aware write path the learning loop (Piece B) builds on.
