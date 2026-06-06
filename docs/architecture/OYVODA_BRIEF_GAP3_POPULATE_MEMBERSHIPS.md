# Brief — Gap 3: Populate property_group memberships (derive from existing community data)

For Claude Code. Build-ready. Read OYVODA_AUDIT_KNOWLEDGE_INGESTION_LAYER.md and the Gap 1/2/4
briefs first. This is the LAST knowledge-layer gap. It is NOT mechanical row-insertion and NOT
(mostly) operator data-entry — it's a DERIVATION + RECONCILIATION of two neighborhood
representations that already exist. Get the reconciliation decision right.

## Key finding (verified in migration 003)
`properties` ALREADY has a `community` column — a `community_type` ENUM with the exact 30A
neighborhoods: watercolor, rosemary_beach, alys_beach, seaside, grayton_beach, blue_mountain,
seagrove, watersound, seacrest, inlet_beach, other. Indexed (ix_properties_community). So
neighborhood ground truth is ALREADY in the property schema — the operator told us at
creation/import. Meanwhile property_groups + property_group_memberships (migration 076) are the
NEWER representation that Gap 1/Gap 4 and the learning loop depend on — and they're EMPTY.

So there are TWO representations of "neighborhood": the legacy `community` enum (likely populated)
and the `property_groups` M2M (empty). Gap 3 reconciles them.

## GATE 0 — confirm the community column is actually populated (one query, do FIRST)
`SELECT community, COUNT(*) FROM properties WHERE tenant_id='e07980b2-a990-4b24-91d1-c8cb71ab70e1'
 AND COALESCE(is_active,TRUE)=TRUE GROUP BY community ORDER BY 2 DESC;`
- If populated (most properties have a non-null community): proceed with DERIVATION (below).
- If mostly NULL: the column exists but was never filled. STOP and report — Gap 3 then becomes a
  data-entry/onboarding task (operator assigns neighborhoods), not a derivation. Don't guess
  neighborhoods from addresses.
- Report the distribution either way (it tells us the real neighborhood structure of Beach Habitats).

## The derivation (if community is populated)
For the tenant, for each DISTINCT non-null, non-'other' community value among active properties:
1. Create a `property_groups` row: tenant_id, name = the community (human-readable, e.g.
   "WaterSound"), group_type = 'neighborhood' (or 'hoa_zone' — pick one, document it; 'neighborhood'
   is most accurate for a 30A community), is_active=true. Idempotent: don't duplicate if a group
   with that name already exists for the tenant.
2. For each property with that community value, insert a `property_group_memberships` row
   (property_id, property_group_id, tenant_id). Idempotent (the PK is (property_id,
   property_group_id), so ON CONFLICT DO NOTHING).
3. `community = 'other'` or NULL → NO group, NO membership. Honest: those properties simply aren't
   in a managed neighborhood group. Absence is valid (not a gap).
Run as a one-time backfill script (app/services/... or a management command), tenant-scoped,
dry-run first (report what it WOULD create), then --no-dry-run. DB target must be confirmed
production before write (same discipline as the gap cleanup).

## RECONCILIATION DECISION (the real substance — document it)
Two representations now exist. Decide the canonical home going forward:
- RECOMMENDATION for v1: `community` enum is the EXISTING operator-provided truth; DERIVE
  property_groups from it (this brick). Going forward, property_groups becomes the canonical
  neighborhood model (it's richer — supports group-scoped knowledge, HOA rules, the learning loop's
  neighborhood tier; the enum can't hold any of that). New properties / onboarding should populate
  the group membership (and optionally keep the enum in sync for legacy reads).
- Note the drift risk: if `community` enum and group memberships can both be edited independently,
  they'll diverge. For v1, derive-once is fine; flag "single canonical neighborhood home" as a
  follow-up so a future edit path doesn't update one and not the other.
- Do NOT delete or deprecate the `community` enum in this brick — other code may read it. Additive only.

## After derivation — the loop closes
Once memberships exist:
- Gap 4's `get_group_knowledge_gaps()` returns REAL gaps for WaterSound et al. ("12 properties, no
  HOA policy on file").
- Operator fills a group-scoped fact (Gap 1 path) -> all member properties inherit (read path).
- The golf-cart question for a WaterSound property can return required_vendors + numbers.
Verify this end-to-end with the real (now-populated) data:
- Run Gap 4's endpoint/surfacer for the tenant -> confirm it returns per-neighborhood missing topics.
- Stage a group-scoped hoa_rules entry for one group -> confirm a member property inherits it via
  get_effective_knowledge_for_property.

## Onboarding connection (note for later, don't build here)
The `community` enum IS the current "assign a neighborhood" mechanism (set at property creation/
import). The signup-time "present neighborhoods to every operator" experience Hunter wants is:
ensure new properties get a community/group assignment, and run the Gap 4 surfacer to ask for
missing HOA/vendor knowledge. That's a follow-up onboarding brick, not this one.

## Scope guards
- GATE 0 first; if community is unpopulated, STOP and report (don't guess neighborhoods).
- Idempotent derivation (groups by name, memberships by PK). Dry-run before write. Confirm prod DB.
- community='other'/NULL -> no group (honest absence).
- Additive only: don't touch the community enum or existing reads.
- Document the reconciliation decision (groups canonical going forward; derive-once now).

## Done when
- GATE 0 distribution reported; community confirmed populated (or task re-scoped if not).
- property_groups created per distinct community; memberships populated; idempotent; prod-confirmed.
- Gap 4 surfacer returns real per-neighborhood gaps for Beach Habitats.
- End-to-end verified: group-scoped fact inherited by a member property with real data.
- Reconciliation decision documented (canonical neighborhood home going forward).
- Commit SHA. Note: closes the neighborhood/HOA loop — Gaps 1+2+4+3 complete; learning loop's
  neighborhood tier now has real data to write against.
