from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from db.migrations.url_config import resolve_migration_url
from app.services.property_canonical_write_service import get_canonical_property_write_service


def _normalize_code(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", (value or "").upper())


def _norm_space(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def _normalize_async_db_url(url: str) -> str:
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    url = url.replace("sslmode=require", "ssl=require")
    return url


@dataclass
class EscapiaRow:
    property_id: str
    unit_code: str
    name: str
    address1: str
    address2: str
    city: str
    province: str


def _load_csv(path: Path) -> List[EscapiaRow]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = []
        for row in csv.DictReader(f):
            rows.append(
                EscapiaRow(
                    property_id=str(row.get("Property_ID") or "").strip(),
                    unit_code=str(row.get("Unit_Code") or "").strip(),
                    name=str(row.get("Name") or "").strip(),
                    address1=str(row.get("Address1") or "").strip(),
                    address2=str(row.get("Address2") or "").strip(),
                    city=str(row.get("City") or "").strip(),
                    province=str(row.get("Province") or "").strip(),
                )
            )
    return rows


async def _load_properties(session, tenant_id: UUID) -> List[dict]:
    rows = (
        await session.execute(
            text(
                """
                SELECT property_code, external_id, address_street, community
                FROM properties
                WHERE tenant_id = CAST(:tid AS uuid)
                ORDER BY property_code
                """
            ),
            {"tid": str(tenant_id)},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def _match_row(esc_row: EscapiaRow, db_rows: List[dict]) -> dict:
    exact_code = next((row for row in db_rows if str(row.get("property_code") or "") == esc_row.unit_code), None)
    if exact_code:
        return {"match_type": "exact_unit_code", "property_code": exact_code["property_code"], "db_row": exact_code}

    norm_code = _normalize_code(esc_row.unit_code)
    normalized_code = next(
        (row for row in db_rows if _normalize_code(str(row.get("property_code") or "")) == norm_code),
        None,
    )
    if normalized_code:
        return {"match_type": "normalized_unit_code", "property_code": normalized_code["property_code"], "db_row": normalized_code}

    address_candidates = [
        row
        for row in db_rows
        if _norm_space(esc_row.address1) and (
            _norm_space(str(row.get("address_street") or "")) == _norm_space(esc_row.address1)
            or _norm_space(str(row.get("address_street") or "")).startswith(_norm_space(esc_row.address1))
        )
    ]
    if len(address_candidates) == 1:
        return {"match_type": "address_match", "property_code": address_candidates[0]["property_code"], "db_row": address_candidates[0]}
    if len(address_candidates) > 1:
        return {
            "match_type": "ambiguous_address",
            "property_code": "",
            "db_row": None,
            "candidates": [row["property_code"] for row in address_candidates],
        }
    return {"match_type": "unmatched", "property_code": "", "db_row": None}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Import Escapia Property_ID / Unit_Code / Name into canonical identity tables.")
    parser.add_argument("--csv", required=True, help="Path to Escapia Property ID CSV")
    parser.add_argument("--tenant-id", required=True, help="Tenant/company UUID")
    parser.add_argument("--apply", action="store_true", help="Persist canonical identity updates")
    args = parser.parse_args()

    tenant_id = UUID(args.tenant_id)
    csv_rows = _load_csv(Path(args.csv))
    db_url, _ = resolve_migration_url(os.environ)
    db_url = _normalize_async_db_url(db_url)

    engine = create_async_engine(
        db_url,
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
        },
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        db_rows = await _load_properties(session, tenant_id)
        writer = get_canonical_property_write_service(session)
        report = {
            "total_csv_rows": len(csv_rows),
            "db_rows": len(db_rows),
            "matched": 0,
            "normalized_matches": 0,
            "address_matches": 0,
            "unmatched": [],
            "ambiguous": [],
        }

        for esc_row in csv_rows:
            match = _match_row(esc_row, db_rows)
            match_type = match["match_type"]
            if match_type in {"exact_unit_code", "normalized_unit_code", "address_match"}:
                report["matched"] += 1
                if match_type == "normalized_unit_code":
                    report["normalized_matches"] += 1
                if match_type == "address_match":
                    report["address_matches"] += 1
                if args.apply:
                    property_code = str(match["property_code"])
                    preferred_address = esc_row.address1 + (f" {esc_row.address2}".strip() if esc_row.address2 else "")
                    await writer.upsert_property_profile(
                        tenant_id,
                        canonical_property_code=property_code,
                        display_name=esc_row.name or property_code,
                        marketing_name=esc_row.name or "",
                        preferred_address=preferred_address.strip() or esc_row.address1 or "",
                        source="escapia_csv_import",
                        metadata={"escapia_property_id": esc_row.property_id, "unit_code": esc_row.unit_code},
                    )
                    await writer.register_property_record(
                        tenant_id,
                        canonical_property_code=property_code,
                        display_name=esc_row.name or property_code,
                        property_name=esc_row.name or "",
                        address_line1=preferred_address.strip() or esc_row.address1 or "",
                        aliases=[esc_row.unit_code, esc_row.name, esc_row.address1, preferred_address.strip()],
                        ref_pairs=[
                            {"provider": "pms", "ref_kind": "property_id", "ref_value": esc_row.property_id, "confidence": 0.99, "metadata": {"source": "escapia_csv_import"}},
                            {"provider": "pms", "ref_kind": "unit_code", "ref_value": esc_row.unit_code, "confidence": 0.99, "metadata": {"source": "escapia_csv_import"}},
                        ],
                        source="escapia_csv_import",
                    )
            elif match_type == "ambiguous_address":
                report["ambiguous"].append(
                    {"unit_code": esc_row.unit_code, "property_id": esc_row.property_id, "name": esc_row.name, "candidates": match["candidates"]}
                )
            else:
                report["unmatched"].append(
                    {
                        "unit_code": esc_row.unit_code,
                        "property_id": esc_row.property_id,
                        "name": esc_row.name,
                        "address1": esc_row.address1,
                        "address2": esc_row.address2,
                    }
                )

        print(json.dumps(report, indent=2))

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
