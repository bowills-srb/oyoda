"""Gap 3 backfill: derive property_groups + memberships from properties.community enum.

RECONCILIATION DECISION (documented here per the brief):
  Two representations of "neighborhood" now exist:
  - Legacy: properties.community (community_type ENUM, migration 003) — operator-provided at import
  - Current: property_groups M2M (migration 076) — richer, supports group-scoped knowledge,
    HOA rules, the learning loop's neighborhood tier

  For v1: DERIVE groups from the enum now (this script). Going forward, property_groups is
  canonical (it supports scoped knowledge, required_vendors, gate_code, hoa_rules — the enum
  can hold none of that). New properties/onboarding should populate the group membership and
  optionally keep the enum in sync.

  Drift risk: if community enum and group memberships can both be edited independently, they will
  diverge. This is acceptable for v1 (derive-once). Flag "single canonical neighborhood home" for
  v2 so a future edit path doesn't update one and not the other.

  community='other' or NULL → no group (honest absence — those properties aren't in a managed
  neighborhood group). Not a gap, not a warning.

IDEMPOTENT:
  - Groups: INSERT ... ON CONFLICT DO NOTHING (matched on (tenant_id, name))
  - Memberships: INSERT ... ON CONFLICT DO NOTHING (PK is (property_id, property_group_id))

RUN:
  python scripts/backfill_property_groups_from_community.py --tenant <uuid> [--apply]
  Default is dry-run. Pass --apply to write.

VERIFIED: Beach Habitats (e07980b2-a990-4b24-91d1-c8cb71ab70e1)
  Gate 0 distribution:
    watercolor: 30, seagrove: 6, other: 3, blue_mountain: 2,
    seacrest: 1, rosemary_beach: 1, grayton_beach: 1, watersound: 1
  Applied: 7 groups, 42 memberships.
  Post-apply: Gap 4 surfacer returns 7 groups × 8 missing topics (0% coverage) — correct.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from uuid import UUID

from sqlalchemy import text

# 30A brand-name overrides; others get title-cased underscore→space
COMMUNITY_DISPLAY_NAMES = {
    "watercolor":     "WaterColor",
    "watersound":     "WaterSound",
    "rosemary_beach": "Rosemary Beach",
    "alys_beach":     "Alys Beach",
    "seaside":        "Seaside",
    "grayton_beach":  "Grayton Beach",
    "blue_mountain":  "Blue Mountain Beach",
    "seagrove":       "Seagrove Beach",
    "seacrest":       "Seacrest Beach",
    "inlet_beach":    "Inlet Beach",
}


def _display_name(community: str) -> str:
    return COMMUNITY_DISPLAY_NAMES.get(community, community.replace("_", " ").title())


async def _run(tenant_id: UUID, apply: bool) -> None:
    from app.core.database import get_db_session

    mode = "APPLY" if apply else "DRY RUN"
    print(f"[Gap 3 backfill] {mode} — tenant {tenant_id}")
    print()

    async with get_db_session() as db:
        # Gate 0 — distribution
        dist = (await db.execute(
            text("""
                SELECT community, COUNT(*) AS cnt
                FROM properties
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND COALESCE(is_active, TRUE) = TRUE
                GROUP BY community
                ORDER BY cnt DESC
            """),
            {"tid": str(tenant_id)},
        )).fetchall()

        print("Community distribution:")
        for row in dist:
            tag = " ← no group (community=other/null)" if row[0] in (None, "other") else ""
            print(f"  {row[0]}: {row[1]}{tag}")
        print()

        communities = [
            row[0] for row in dist
            if row[0] and row[0] != "other"
        ]

        if not communities:
            print("ERROR: No non-null, non-'other' community values found.")
            print("Gap 3 cannot derive groups — becomes a data-entry task.")
            sys.exit(1)

        total_groups = 0
        total_memberships = 0

        for comm in communities:
            name = _display_name(comm)
            prop_count = next(r[1] for r in dist if r[0] == comm)
            print(f"  {'CREATE' if apply else 'WOULD CREATE'} group: {name!r} ({prop_count} properties)")
            total_groups += 1
            total_memberships += prop_count

        print()
        print(f"Total: {total_groups} groups, {total_memberships} memberships")
        print(f"  (properties with community=other/null → no group: honest absence)")

        if not apply:
            print()
            print("Pass --apply to write.")
            return

        print()
        groups_created = 0
        memberships_created = 0

        for comm in communities:
            name = _display_name(comm)
            meta = json.dumps({"source": "community_enum_backfill", "community_enum": comm})

            row = (await db.execute(
                text("""
                    INSERT INTO property_groups (tenant_id, name, group_type, is_active, metadata)
                    VALUES (CAST(:tid AS uuid), :name, 'neighborhood', TRUE, CAST(:meta AS jsonb))
                    ON CONFLICT DO NOTHING
                    RETURNING id
                """),
                {"tid": str(tenant_id), "name": name, "meta": meta},
            )).fetchone()

            if row:
                group_id = row[0]
                groups_created += 1
            else:
                group_id = (await db.execute(
                    text("SELECT id FROM property_groups WHERE tenant_id = CAST(:tid AS uuid) AND name = :name LIMIT 1"),
                    {"tid": str(tenant_id), "name": name},
                )).scalar()

            result = await db.execute(
                text("""
                    INSERT INTO property_group_memberships (property_id, property_group_id, tenant_id)
                    SELECT p.id, CAST(:gid AS uuid), CAST(:tid AS uuid)
                    FROM properties p
                    WHERE p.tenant_id = CAST(:tid AS uuid)
                      AND COALESCE(p.is_active, TRUE) = TRUE
                      AND p.community = CAST(:comm AS community_type)
                    ON CONFLICT DO NOTHING
                """),
                {"gid": str(group_id), "tid": str(tenant_id), "comm": comm},
            )
            memberships_created += result.rowcount

        await db.commit()
        print(f"Done: {groups_created} groups created, {memberships_created} memberships created.")

        # Post-apply verification
        verification = (await db.execute(
            text("""
                SELECT g.name, COUNT(m.property_id) AS members
                FROM property_groups g
                LEFT JOIN property_group_memberships m ON m.property_group_id = g.id
                WHERE g.tenant_id = CAST(:tid AS uuid)
                GROUP BY g.id, g.name
                ORDER BY members DESC, g.name
            """),
            {"tid": str(tenant_id)},
        )).fetchall()

        print()
        print("Post-apply verification:")
        for row in verification:
            print(f"  {row[0]}: {row[1]} members")


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive property_groups from properties.community enum")
    parser.add_argument("--tenant", required=True, help="Tenant UUID")
    parser.add_argument("--apply", action="store_true", help="Write to DB (default: dry-run)")
    args = parser.parse_args()
    asyncio.run(_run(UUID(args.tenant), args.apply))


if __name__ == "__main__":
    main()
