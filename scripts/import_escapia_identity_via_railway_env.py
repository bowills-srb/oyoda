from __future__ import annotations

import csv
import json
import os
import re
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import Json


TENANT_ID = sys.argv[1] if len(sys.argv) > 1 else "e07980b2-a990-4b24-91d1-c8cb71ab70e1"
CSV_PATH = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/Users/dhuntermckenzie/Downloads/Escapia Property ID List.csv")


def normalize_code(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", (value or "").upper())


def norm_space(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def upsert_profile(cur, canonical: str, display_name: str, marketing_name: str, preferred_address: str, source: str, metadata: dict) -> None:
    cur.execute(
        """
        INSERT INTO canonical_property_profiles (
            tenant_id, canonical_property_code, display_name, marketing_name,
            preferred_address, source, metadata
        )
        VALUES (%s, %s, NULLIF(%s, ''), NULLIF(%s, ''), NULLIF(%s, ''), %s, %s::jsonb)
        ON CONFLICT (tenant_id, canonical_property_code)
        DO UPDATE SET
            display_name = COALESCE(NULLIF(EXCLUDED.display_name, ''), canonical_property_profiles.display_name),
            marketing_name = COALESCE(NULLIF(EXCLUDED.marketing_name, ''), canonical_property_profiles.marketing_name),
            preferred_address = COALESCE(NULLIF(EXCLUDED.preferred_address, ''), canonical_property_profiles.preferred_address),
            source = EXCLUDED.source,
            metadata = canonical_property_profiles.metadata || EXCLUDED.metadata,
            updated_at = NOW()
        """,
        (TENANT_ID, canonical, display_name.strip(), marketing_name.strip(), preferred_address.strip(), source, Json(metadata)),
    )


def upsert_ref(cur, canonical: str, provider: str, ref_kind: str, ref_value: str, source: str, confidence: float, metadata: dict) -> None:
    ref_value = (ref_value or "").strip()
    if not ref_value:
        return
    normalized = ref_value.casefold().strip()
    cur.execute(
        """
        INSERT INTO canonical_property_refs (
            tenant_id, canonical_property_code, provider, ref_kind,
            ref_value, normalized_ref_value, source, confidence, metadata
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (tenant_id, provider, ref_kind, normalized_ref_value)
        DO UPDATE SET
            canonical_property_code = EXCLUDED.canonical_property_code,
            ref_value = EXCLUDED.ref_value,
            source = EXCLUDED.source,
            confidence = GREATEST(canonical_property_refs.confidence, EXCLUDED.confidence),
            metadata = canonical_property_refs.metadata || EXCLUDED.metadata,
            updated_at = NOW()
        """,
        (TENANT_ID, canonical, provider, ref_kind, ref_value, normalized, source, confidence, Json(metadata)),
    )


def main() -> None:
    if not CSV_PATH.exists():
        raise SystemExit(f"CSV not found: {CSV_PATH}")

    url = (os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL") or "").replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
    if not url:
        raise SystemExit("DATABASE_URL/ALEMBIC_DATABASE_URL not set")

    conn = psycopg2.connect(url)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS canonical_property_profiles (
            canonical_profile_id BIGSERIAL PRIMARY KEY,
            tenant_id UUID NOT NULL,
            canonical_property_code TEXT NOT NULL,
            display_name TEXT,
            marketing_name TEXT,
            preferred_address TEXT,
            source TEXT NOT NULL DEFAULT 'system',
            metadata JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, canonical_property_code)
        );
        CREATE INDEX IF NOT EXISTS idx_canonical_property_profiles_code
            ON canonical_property_profiles (tenant_id, canonical_property_code);
        CREATE TABLE IF NOT EXISTS canonical_property_link_reviews (
            review_id BIGSERIAL PRIMARY KEY,
            tenant_id UUID NOT NULL,
            canonical_property_code TEXT,
            provider TEXT NOT NULL DEFAULT 'internal',
            ref_kind TEXT NOT NULL DEFAULT 'alias',
            ref_value TEXT NOT NULL,
            normalized_ref_value TEXT NOT NULL,
            platform_listing_id TEXT,
            platform_unit_id TEXT,
            property_name TEXT,
            display_name TEXT,
            confidence NUMERIC(5,4) DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'pending',
            source TEXT NOT NULL DEFAULT 'system',
            candidate_payload JSONB DEFAULT '[]'::jsonb,
            metadata JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, provider, ref_kind, normalized_ref_value, status)
        );
        CREATE INDEX IF NOT EXISTS idx_canonical_property_link_reviews_status
            ON canonical_property_link_reviews (tenant_id, status, created_at DESC);
        """
    )

    cur.execute(
        """
        SELECT property_code, external_id, address_street, community
        FROM properties
        WHERE tenant_id = %s
        ORDER BY property_code
        """,
        (TENANT_ID,),
    )
    db_rows = [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]

    report = {
        "matched": 0,
        "normalized_matches": 0,
        "address_matches": 0,
        "unmatched": [],
    }

    with CSV_PATH.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            unit_code = str(raw.get("Unit_Code") or "").strip()
            property_id = str(raw.get("Property_ID") or "").strip()
            name = str(raw.get("Name") or "").strip()
            address1 = str(raw.get("Address1") or "").strip()
            address2 = str(raw.get("Address2") or "").strip()
            preferred_address = (address1 + (f" {address2}" if address2 else "")).strip()

            match = next((row for row in db_rows if str(row.get("property_code") or "") == unit_code), None)
            match_type = "exact_unit_code"
            if not match:
                norm = normalize_code(unit_code)
                match = next(
                    (row for row in db_rows if normalize_code(str(row.get("property_code") or "")) == norm),
                    None,
                )
                if match:
                    match_type = "normalized_unit_code"
            if not match and address1:
                candidates = [
                    row
                    for row in db_rows
                    if norm_space(str(row.get("address_street") or "")) == norm_space(address1)
                    or norm_space(str(row.get("address_street") or "")).startswith(norm_space(address1))
                ]
                if len(candidates) == 1:
                    match = candidates[0]
                    match_type = "address_match"
            if not match:
                report["unmatched"].append(
                    {
                        "unit_code": unit_code,
                        "property_id": property_id,
                        "name": name,
                    }
                )
                continue

            property_code = str(match.get("property_code") or "")
            if match_type == "normalized_unit_code":
                report["normalized_matches"] += 1
            elif match_type == "address_match":
                report["address_matches"] += 1
            report["matched"] += 1

            upsert_profile(
                cur,
                property_code,
                name or property_code,
                name or "",
                preferred_address or address1 or str(match.get("address_street") or ""),
                "escapia_csv_import_psycopg2",
                {"escapia_property_id": property_id, "unit_code": unit_code},
            )
            upsert_ref(cur, property_code, "pms", "property_id", property_id, "escapia_csv_import_psycopg2", 0.99, {"source": "escapia_csv_import_psycopg2"})
            upsert_ref(cur, property_code, "pms", "unit_code", unit_code, "escapia_csv_import_psycopg2", 0.99, {"source": "escapia_csv_import_psycopg2"})
            upsert_ref(cur, property_code, "internal", "alias", name, "escapia_csv_import_psycopg2", 0.86, {"source": "escapia_csv_import_psycopg2"})
            upsert_ref(cur, property_code, "internal", "address_street", address1, "escapia_csv_import_psycopg2", 0.82, {"source": "escapia_csv_import_psycopg2"})

    cur.execute(
        """
        SELECT canonical_property_code, display_name, marketing_name, preferred_address
        FROM canonical_property_profiles
        WHERE tenant_id = %s
          AND canonical_property_code IN (%s, %s, %s, %s)
        ORDER BY canonical_property_code
        """,
        (TENANT_ID, "31Hickor", "1151SG", "119VW", "134SC"),
    )
    sample = [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]
    conn.commit()
    print(json.dumps({"report": report, "profile_samples": sample}, indent=2))

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
