#!/usr/bin/env python3
"""
seed_beach_habitats_full.py
============================
One-shot seeder that loads ALL Beach Habitats data into Supabase:

  1. Upserts 43 properties into `properties` table
  2. Upserts full guidebook knowledge into `concierge_knowledge` table
     (structured JSON — facts, sections, faq per property)
  3. Upserts text documents into `knowledge_embeddings` table
     (flat text rows used by the vector/RAG search layer)

Run this BEFORE Lanier signs up to pre-load everything under the default tenant.
After she signs up, run with --relink <HER_TENANT_UUID> to move it all to her account.

Usage (run each line separately in terminal):

    export DATABASE_URL="postgresql://postgres.mskazxakxowcggxmkmrp:PASSWORD@aws-1-us-east-1.pooler.supabase.com:5432/postgres"
    pip3 install psycopg2-binary
    python3 scripts/seed_beach_habitats_full.py --dry-run
    python3 scripts/seed_beach_habitats_full.py

After Lanier signs up:
    python3 scripts/seed_beach_habitats_full.py --relink LANIER_TENANT_UUID
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional
from uuid import uuid4

import psycopg2
from psycopg2.extras import Json

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR     = Path(__file__).parent
UNIT_INFO_JSON = SCRIPT_DIR / "output" / "unit_info_import" / "properties_normalized.json"
KNOWLEDGE_JSONL = SCRIPT_DIR / "output" / "concierge_knowledge" / "concierge_knowledge_bulk.jsonl"

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
OPERATOR_NAME     = "Beach Habitats 30A"
OPERATOR_ID       = "op_beach_habitats"

_raw = os.getenv("DATABASE_URL", "")
if not _raw:
    print("ERROR: DATABASE_URL environment variable is not set.")
    print()
    print("Set it first:")
    print("  export DATABASE_URL='postgresql://postgres.mskazxakxowcggxmkmrp:YOUR_PASSWORD@aws-1-us-east-1.pooler.supabase.com:5432/postgres'")
    print()
    print("Get your password from Supabase → Settings → Database → Connection string")
    sys.exit(1)

# Keep pooler port 6543 — direct port 5432 is often blocked by local networks
# Just fix the driver prefix for psycopg2
DB_URL = _raw.replace("postgresql+asyncpg://", "postgresql://")
if "sslmode" not in DB_URL:
    DB_URL += "?sslmode=require"

COMMUNITIES = {
    "watercolor": "watercolor", "water color": "watercolor",
    "rosemary beach": "rosemary_beach", "rosemary": "rosemary_beach",
    "alys beach": "alys_beach", "alys": "alys_beach",
    "seaside": "seaside",
    "grayton beach": "grayton_beach", "grayton": "grayton_beach",
    "blue mountain beach": "blue_mountain", "blue mountain": "blue_mountain",
    "seagrove beach": "seagrove", "seagrove": "seagrove",
    "watersound": "watersound", "water sound": "watersound",
    "seacrest beach": "seacrest", "seacrest": "seacrest",
    "inlet beach": "inlet_beach", "inlet": "inlet_beach",
}


def norm_community(v) -> str:
    return COMMUNITIES.get(str(v or "").lower().strip(), "other")


def safe(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s and s.lower() not in ("nan", "none", "") else None


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Properties table
# ─────────────────────────────────────────────────────────────────────────────

def step1_properties(cur, tenant_id: str, dry_run: bool) -> Dict[str, str]:
    """Upsert all properties. Returns {property_code: db_uuid}."""
    print("\n" + "─" * 50)
    print("STEP 1: Properties table")
    print("─" * 50)

    if not UNIT_INFO_JSON.exists():
        print(f"  ⚠  Not found: {UNIT_INFO_JSON}")
        print("  Skipping property upsert.")
        return {}

    records = json.loads(UNIT_INFO_JSON.read_text("utf-8"))
    print(f"  Found {len(records)} records in properties_normalized.json")

    # Existing properties in DB
    cur.execute("SELECT property_code, id::text FROM properties WHERE tenant_id = %s", (tenant_id,))
    existing = {r[0]: r[1] for r in cur.fetchall()}
    print(f"  {len(existing)} properties already in DB for tenant {tenant_id}")

    inserted = updated = 0
    code_to_id: Dict[str, str] = dict(existing)

    for rec in records:
        code = safe(rec.get("unit_code") or rec.get("property_code"))
        if not code:
            continue

        addr      = safe(rec.get("address") or rec.get("address_street")) or "Unknown"
        community = norm_community(rec.get("community"))
        bedrooms  = int(float(rec.get("bedrooms") or 0))
        bathrooms = float(rec.get("bathrooms") or 0)
        wifi_net  = safe(rec.get("wifi_network") or rec.get("wifi_name"))
        wifi_pw   = safe(rec.get("wifi_password"))
        guide_url = safe(rec.get("guidebook_url") or rec.get("property_guide_url")
                         or rec.get("property_guide"))
        notes     = safe(rec.get("notes") or rec.get("general_notes"))

        tag = "[DRY]" if dry_run else "  ✓ "

        if code in existing:
            if not dry_run:
                cur.execute("""
                    UPDATE properties SET
                        address_street     = %(addr)s,
                        community          = %(com)s,
                        bedrooms           = %(bed)s,
                        bathrooms          = %(bath)s,
                        wifi_network       = %(wn)s,
                        wifi_password      = %(wp)s,
                        property_guide_url = %(gu)s,
                        general_notes      = %(notes)s,
                        operator_name      = %(opname)s,
                        updated_at         = NOW()
                    WHERE tenant_id = %(tid)s AND property_code = %(code)s
                """, dict(addr=addr, com=community, bed=bedrooms, bath=bathrooms,
                          wn=wifi_net, wp=wifi_pw, gu=guide_url, notes=notes,
                          opname=OPERATOR_NAME, tid=tenant_id, code=code))
            updated += 1
            print(f"  {tag} UPDATE  {code:18s} {bedrooms}BR/{bathrooms:.1f}BA  {community}")
        else:
            new_id = str(uuid4())
            if not dry_run:
                cur.execute("""
                    INSERT INTO properties (
                        id, tenant_id, property_code, address_street, community,
                        bedrooms, bathrooms, wifi_network, wifi_password,
                        property_guide_url, general_notes, operator_name,
                        data_source, confidence_score
                    ) VALUES (
                        %(id)s, %(tid)s, %(code)s, %(addr)s, %(com)s,
                        %(bed)s, %(bath)s, %(wn)s, %(wp)s,
                        %(gu)s, %(notes)s, %(opname)s,
                        'import', 0.85
                    )
                """, dict(id=new_id, tid=tenant_id, code=code, addr=addr, com=community,
                          bed=bedrooms, bath=bathrooms, wn=wifi_net, wp=wifi_pw,
                          gu=guide_url, notes=notes, opname=OPERATOR_NAME))
            code_to_id[code] = new_id
            inserted += 1
            print(f"  {tag} INSERT  {code:18s} {bedrooms}BR/{bathrooms:.1f}BA  {community}")

    print()
    print(f"  Result: {inserted} inserted, {updated} updated, {inserted+updated} total")
    return code_to_id


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — concierge_knowledge table (structured JSON per property)
# ─────────────────────────────────────────────────────────────────────────────

def step2_concierge_knowledge(cur, tenant_id: str, code_to_id: Dict[str, str], dry_run: bool):
    """Upsert full guidebook data into concierge_knowledge (one row per property)."""
    print("\n" + "─" * 50)
    print("STEP 2: concierge_knowledge table (guidebook JSON)")
    print("─" * 50)

    if not KNOWLEDGE_JSONL.exists():
        print(f"  ⚠  Not found: {KNOWLEDGE_JSONL}")
        return

    lines = [l.strip() for l in KNOWLEDGE_JSONL.read_text("utf-8").split("\n") if l.strip()]
    print(f"  Found {len(lines)} property records in JSONL")

    # Check existing
    cur.execute("SELECT property_external_id FROM concierge_knowledge WHERE tenant_id = %s",
                (tenant_id,))
    existing_codes = {r[0] for r in cur.fetchall()}
    print(f"  {len(existing_codes)} already in concierge_knowledge for this tenant")

    upserted = skipped = errors = 0

    for line in lines:
        try:
            rec = json.loads(line)
        except Exception as e:
            print(f"  ✗ JSON parse error: {e}")
            errors += 1
            continue

        code      = rec.get("unit_code", "")
        prop_uuid = code_to_id.get(code)
        context   = rec.get("property_context", {})
        facts     = rec.get("facts", {})
        sections  = rec.get("sections", {})
        faq       = rec.get("faq", [])
        guide_url = rec.get("guidebook_url", "") or None
        raw_len   = rec.get("raw_text_length", 0)

        if not code:
            skipped += 1
            continue

        tag = "[DRY]" if dry_run else "  ✓ "
        action = "UPDATE" if code in existing_codes else "INSERT"
        faq_count = len(faq)
        sec_count = len([s for s, v in sections.items() if v])
        print(f"  {tag} {action:6s}  {code:18s}  {faq_count} FAQ  {sec_count} sections")

        if dry_run:
            upserted += 1
            continue

        try:
            cur.execute("""
                INSERT INTO concierge_knowledge
                    (concierge_knowledge_id, tenant_id, property_id,
                     property_external_id, source, guidebook_url,
                     property_context, facts, sections, faq, raw_text_length)
                VALUES
                    (%(kid)s, %(tid)s, %(pid)s,
                     %(ext)s, 'guidebook_import', %(gurl)s,
                     %(ctx)s, %(facts)s, %(secs)s, %(faq)s, %(rlen)s)
                ON CONFLICT (tenant_id, property_external_id)
                DO UPDATE SET
                    property_id      = EXCLUDED.property_id,
                    guidebook_url    = EXCLUDED.guidebook_url,
                    property_context = EXCLUDED.property_context,
                    facts            = EXCLUDED.facts,
                    sections         = EXCLUDED.sections,
                    faq              = EXCLUDED.faq,
                    raw_text_length  = EXCLUDED.raw_text_length,
                    updated_at       = NOW()
            """, dict(
                kid=str(uuid4()),
                tid=tenant_id,
                pid=prop_uuid,
                ext=code,
                gurl=guide_url,
                ctx=Json(context),
                facts=Json(facts),
                secs=Json(sections),
                faq=Json(faq),
                rlen=raw_len,
            ))
            upserted += 1
        except Exception as e:
            print(f"  ✗ {code}: {e}")
            errors += 1

    print()
    print(f"  Result: {upserted} upserted, {skipped} skipped, {errors} errors")


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — knowledge_embeddings table (flat text for RAG/semantic search)
# ─────────────────────────────────────────────────────────────────────────────

def step3_knowledge_embeddings(cur, tenant_id: str, code_to_id: Dict[str, str], dry_run: bool):
    """
    Upsert flat text documents into knowledge_embeddings for RAG retrieval.
    Each property produces several documents: property_info, faq entries, sections.
    The embedding vector itself is generated at query time by the RAG layer —
    we just need the text content in the table.
    """
    print("\n" + "─" * 50)
    print("STEP 3: knowledge_embeddings table (RAG text docs)")
    print("─" * 50)

    if not KNOWLEDGE_JSONL.exists():
        print(f"  ⚠  Not found: {KNOWLEDGE_JSONL}")
        return

    lines = [l.strip() for l in KNOWLEDGE_JSONL.read_text("utf-8").split("\n") if l.strip()]

    # Check table columns to understand schema
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'knowledge_embeddings'
        ORDER BY ordinal_position
    """)
    cols = [r[0] for r in cur.fetchall()]

    if not cols:
        print("  ⚠  knowledge_embeddings table not found — skipping")
        return

    print(f"  Table columns: {', '.join(cols)}")

    # Determine which column names to use
    has_doc_id       = "doc_id" in cols
    has_property_code = "property_code" in cols
    has_doc_type     = "doc_type" in cols
    has_tenant_id    = "tenant_id" in cols
    has_content_type = "content_type" in cols

    if not has_doc_id:
        print("  ⚠  No 'doc_id' column — table may use different schema, skipping")
        return

    # Check existing doc_ids for this operator
    cur.execute("SELECT doc_id FROM knowledge_embeddings WHERE operator_id = %s",
                (OPERATOR_ID,))
    existing_doc_ids = {r[0] for r in cur.fetchall()}
    print(f"  {len(existing_doc_ids)} existing docs for operator '{OPERATOR_ID}'")

    rows_to_upsert = []

    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:
            continue

        code  = rec.get("unit_code", "")
        facts = rec.get("facts", {})
        faq   = rec.get("faq", [])
        sections = rec.get("sections", {})
        context  = rec.get("property_context", {})
        guide_url = rec.get("guidebook_url", "")

        if not code:
            continue

        # ── Property info doc (facts summary) ────────────────────────────
        fact_lines = []
        if facts.get("wifi"):
            fact_lines.append(f"WiFi password: {facts['wifi']}")
        if facts.get("check_in"):
            fact_lines.append(f"Check-in: {str(facts['check_in'])[:300]}")
        if facts.get("check_out"):
            fact_lines.append(f"Check-out: {facts['check_out']}")
        if context.get("address"):
            fact_lines.append(f"Address: {context['address']}")
        if context.get("bedrooms"):
            fact_lines.append(f"Bedrooms: {context['bedrooms']}")

        if fact_lines:
            rows_to_upsert.append({
                "doc_id": f"{OPERATOR_ID}_{code}_property_info",
                "operator_id": OPERATOR_ID,
                "property_code": code,
                "doc_type": "property_info",
                "content": "\n".join(fact_lines),
                "metadata": Json({"unit_code": code, "guidebook_url": guide_url,
                                  "source": "unit_info_import"}),
            })

        # ── FAQ docs ──────────────────────────────────────────────────────
        for i, faq_item in enumerate(faq):
            q = faq_item.get("question", "")
            a = faq_item.get("answer", "")
            if q and a:
                rows_to_upsert.append({
                    "doc_id": f"{OPERATOR_ID}_{code}_faq_{i}",
                    "operator_id": OPERATOR_ID,
                    "property_code": code,
                    "doc_type": "property_faq",
                    "content": f"Q: {q}\nA: {a[:1500]}",
                    "metadata": Json({"unit_code": code, "question": q,
                                      "source": faq_item.get("source", "guidebook")}),
                })

        # ── Section docs ──────────────────────────────────────────────────
        section_labels = {
            "check_in": "Check-in instructions",
            "check_out": "Check-out instructions",
            "wifi": "WiFi information",
            "parking": "Parking",
            "door_lock": "Door codes and access",
            "shipping": "Shipping and packages",
            "bikes": "Bikes",
            "pool": "Pool and amenities",
            "beach": "Beach gear and access",
            "hvac": "AC and heating",
            "appliance": "Appliances",
            "transport": "Transportation",
            "emergency": "Emergency procedures",
        }
        for sec_key, sec_text in sections.items():
            if not sec_text or not sec_text.strip():
                continue
            label = section_labels.get(sec_key, sec_key.replace("_", " ").title())
            rows_to_upsert.append({
                "doc_id": f"{OPERATOR_ID}_{code}_section_{sec_key}",
                "operator_id": OPERATOR_ID,
                "property_code": code,
                "doc_type": "property_info",
                "content": f"{label} at {code}:\n{sec_text[:2500]}",
                "metadata": Json({"unit_code": code, "section": sec_key,
                                  "source": "guidebook_section"}),
            })

    print(f"  Generated {len(rows_to_upsert)} documents across {len(lines)} properties")

    if dry_run:
        # Show sample
        for r in rows_to_upsert[:5]:
            status = "EXISTS" if r["doc_id"] in existing_doc_ids else "NEW   "
            print(f"    [{status}] {r['doc_id'][:70]}")
        print(f"    ... and {max(0, len(rows_to_upsert)-5)} more")
        return

    upserted = errors = 0
    for row in rows_to_upsert:
        try:
            if has_tenant_id:
                cur.execute("""
                    INSERT INTO knowledge_embeddings
                        (doc_id, operator_id, property_code, doc_type, content, metadata, tenant_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (doc_id) DO UPDATE SET
                        content    = EXCLUDED.content,
                        metadata   = EXCLUDED.metadata,
                        updated_at = NOW()
                """, (row["doc_id"], row["operator_id"], row["property_code"],
                      row["doc_type"], row["content"], row["metadata"], tenant_id))
            else:
                cur.execute("""
                    INSERT INTO knowledge_embeddings
                        (doc_id, operator_id, property_code, doc_type, content, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (doc_id) DO UPDATE SET
                        content    = EXCLUDED.content,
                        metadata   = EXCLUDED.metadata,
                        updated_at = NOW()
                """, (row["doc_id"], row["operator_id"], row["property_code"],
                      row["doc_type"], row["content"], row["metadata"]))
            upserted += 1
        except Exception as e:
            print(f"  ✗ {row['doc_id']}: {e}")
            errors += 1

    print(f"  Result: {upserted} upserted, {errors} errors")


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — Re-link to new tenant after signup
# ─────────────────────────────────────────────────────────────────────────────

def step4_relink(cur, new_tenant_id: str, dry_run: bool):
    """Move all Beach Habitats rows from default tenant to Lanier's real tenant."""
    print("\n" + "─" * 50)
    print(f"STEP 4: Re-link to new tenant {new_tenant_id}")
    print("─" * 50)

    # Count what we'd move
    cur.execute("SELECT COUNT(*) FROM properties WHERE operator_name=%s AND tenant_id=%s",
                (OPERATOR_NAME, DEFAULT_TENANT_ID))
    prop_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM concierge_knowledge WHERE tenant_id=%s",
                (DEFAULT_TENANT_ID,))
    ck_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM knowledge_embeddings WHERE operator_id=%s",
                (OPERATOR_ID,))
    ke_count = cur.fetchone()[0]

    print(f"  Will re-link:")
    print(f"    {prop_count} properties")
    print(f"    {ck_count} concierge_knowledge rows")
    print(f"    {ke_count} knowledge_embeddings rows")

    if dry_run:
        print("  [DRY RUN] — no changes made")
        return

    cur.execute("""
        UPDATE properties SET tenant_id=%s, updated_at=NOW()
        WHERE operator_name=%s AND tenant_id=%s
    """, (new_tenant_id, OPERATOR_NAME, DEFAULT_TENANT_ID))
    print(f"  ✓ Re-linked {cur.rowcount} properties")

    cur.execute("""
        UPDATE concierge_knowledge SET tenant_id=%s, updated_at=NOW()
        WHERE tenant_id=%s
    """, (new_tenant_id, DEFAULT_TENANT_ID))
    print(f"  ✓ Re-linked {cur.rowcount} concierge_knowledge rows")

    # knowledge_embeddings uses operator_id not tenant_id — no change needed
    # but update tenant_id column if it exists
    try:
        cur.execute("""
            UPDATE knowledge_embeddings SET tenant_id=%s
            WHERE operator_id=%s AND (tenant_id=%s OR tenant_id IS NULL)
        """, (new_tenant_id, OPERATOR_ID, DEFAULT_TENANT_ID))
        print(f"  ✓ Re-linked {cur.rowcount} knowledge_embeddings rows (tenant_id)")
    except Exception:
        pass  # tenant_id column may not exist on this table


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Seed all Beach Habitats property + knowledge data into Supabase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run first (no DB writes):
  python3 scripts/seed_beach_habitats_full.py --dry-run

  # Full seed:
  python3 scripts/seed_beach_habitats_full.py

  # After Lanier signs up, re-link to her account:
  python3 scripts/seed_beach_habitats_full.py --relink <LANIER_TENANT_UUID>
        """
    )
    ap.add_argument("--tenant", "-t", default=DEFAULT_TENANT_ID,
                    help=f"Tenant UUID (default: {DEFAULT_TENANT_ID})")
    ap.add_argument("--dry-run", "-n", action="store_true",
                    help="Show what would happen without writing to DB")
    ap.add_argument("--relink", "-r", metavar="NEW_TENANT_UUID",
                    help="Re-link all rows to a new tenant UUID after operator signs up")
    args = ap.parse_args()

    print()
    print("=" * 60)
    print("Beach Habitats Full DB Seeder")
    print("=" * 60)
    print(f"Tenant:   {args.tenant}")
    print(f"Dry run:  {args.dry_run}")
    print(f"DB:       {DB_URL[:55]}...")
    print()

    try:
        conn = psycopg2.connect(DB_URL)
    except Exception as e:
        print(f"❌ Could not connect to database: {e}")
        print()
        print("Make sure DATABASE_URL is set correctly.")
        print("The pooler URL (port 6543) works fine from local machines.")
        sys.exit(1)

    cur = conn.cursor()

    try:
        if args.relink:
            step4_relink(cur, args.relink, args.dry_run)
            if not args.dry_run:
                conn.commit()
                print("\n✅ Re-link complete.")
        else:
            # Full seed
            code_to_id = step1_properties(cur, args.tenant, args.dry_run)
            if not args.dry_run:
                conn.commit()

            step2_concierge_knowledge(cur, args.tenant, code_to_id, args.dry_run)
            if not args.dry_run:
                conn.commit()

            step3_knowledge_embeddings(cur, args.tenant, code_to_id, args.dry_run)
            if not args.dry_run:
                conn.commit()

            print()
            print("=" * 60)
            if args.dry_run:
                print("✅ Dry run complete — no data was written.")
            else:
                print("✅ Seed complete.")
            print("=" * 60)
            print()
            if not args.dry_run:
                print("Next step: After Lanier signs up at oyvoda.com/signup,")
                print("get her tenant_id from the super admin dashboard, then run:")
                print()
                print(f"  python3 scripts/seed_beach_habitats_full.py --relink <LANIER_TENANT_UUID>")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Error: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
