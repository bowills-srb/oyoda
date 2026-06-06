#!/usr/bin/env bash
set -euo pipefail

CSV_PATH="${1:-/Users/dhuntermckenzie/Downloads/Escapia Property ID List.csv}"
TENANT_ID="${2:-e07980b2-a990-4b24-91d1-c8cb71ab70e1}"
SERVICE="${SERVICE:-oyvoda-beat}"

if [[ ! -f "$CSV_PATH" ]]; then
  echo "CSV not found: $CSV_PATH" >&2
  exit 1
fi

B64="$(base64 < "$CSV_PATH" | tr -d '\n')"

railway ssh -s "$SERVICE" /bin/sh -lc "cd /app && python - <<'PY'
import asyncio
import base64
import csv
import io
import json
import re
from uuid import UUID

from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.property_canonical_write_service import get_canonical_property_write_service

TENANT_ID = UUID('$TENANT_ID')
CSV_TEXT = base64.b64decode(\"$B64\").decode('utf-8-sig')


def normalize_code(value: str) -> str:
    return re.sub(r'[^A-Za-z0-9]', '', (value or '').upper())


def norm_space(value: str) -> str:
    return re.sub(r'\\s+', ' ', (value or '').strip()).casefold()


async def main() -> None:
    async with SessionLocal() as session:
        writer = get_canonical_property_write_service(session)
        await writer.sync_tenant_sources(TENANT_ID)
        rows = (
            await session.execute(
                text(
                    \"\"\"
                    SELECT property_code, external_id, address_street, community
                    FROM properties
                    WHERE tenant_id = CAST(:tid AS uuid)
                    ORDER BY property_code
                    \"\"\"
                ),
                {'tid': str(TENANT_ID)},
            )
        ).mappings().all()
        db_rows = [dict(r) for r in rows]
        reader = csv.DictReader(io.StringIO(CSV_TEXT))
        report = {
            'matched': 0,
            'normalized_matches': 0,
            'address_matches': 0,
            'unmatched': [],
        }

        for raw in reader:
            unit_code = str(raw.get('Unit_Code') or '').strip()
            property_id = str(raw.get('Property_ID') or '').strip()
            name = str(raw.get('Name') or '').strip()
            address1 = str(raw.get('Address1') or '').strip()
            address2 = str(raw.get('Address2') or '').strip()
            preferred_address = (address1 + (f' {address2}' if address2 else '')).strip()

            match = next((row for row in db_rows if str(row.get('property_code') or '') == unit_code), None)
            match_type = 'exact_unit_code'
            if not match:
                norm = normalize_code(unit_code)
                match = next(
                    (row for row in db_rows if normalize_code(str(row.get('property_code') or '')) == norm),
                    None,
                )
                if match:
                    match_type = 'normalized_unit_code'
            if not match and address1:
                candidates = [
                    row
                    for row in db_rows
                    if norm_space(str(row.get('address_street') or '')) == norm_space(address1)
                    or norm_space(str(row.get('address_street') or '')).startswith(norm_space(address1))
                ]
                if len(candidates) == 1:
                    match = candidates[0]
                    match_type = 'address_match'
            if not match:
                report['unmatched'].append(
                    {
                        'unit_code': unit_code,
                        'property_id': property_id,
                        'name': name,
                    }
                )
                continue

            property_code = str(match.get('property_code') or '')
            if match_type == 'normalized_unit_code':
                report['normalized_matches'] += 1
            elif match_type == 'address_match':
                report['address_matches'] += 1
            report['matched'] += 1

            await writer.upsert_property_profile(
                TENANT_ID,
                canonical_property_code=property_code,
                display_name=name or property_code,
                marketing_name=name or '',
                preferred_address=preferred_address or address1 or str(match.get('address_street') or ''),
                source='escapia_csv_import_remote',
                metadata={'escapia_property_id': property_id, 'unit_code': unit_code},
            )
            await writer.register_property_record(
                TENANT_ID,
                canonical_property_code=property_code,
                display_name=name or property_code,
                property_name=name or '',
                address_line1=preferred_address or address1 or str(match.get('address_street') or ''),
                aliases=[unit_code, name, address1, preferred_address],
                ref_pairs=[
                    {
                        'provider': 'pms',
                        'ref_kind': 'property_id',
                        'ref_value': property_id,
                        'confidence': 0.99,
                        'metadata': {'source': 'escapia_csv_import_remote'},
                    },
                    {
                        'provider': 'pms',
                        'ref_kind': 'unit_code',
                        'ref_value': unit_code,
                        'confidence': 0.99,
                        'metadata': {'source': 'escapia_csv_import_remote'},
                    },
                ],
                source='escapia_csv_import_remote',
            )

        await session.commit()
        sample = (
            await session.execute(
                text(
                    \"\"\"
                    SELECT canonical_property_code, display_name, marketing_name, preferred_address
                    FROM canonical_property_profiles
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND canonical_property_code IN ('31Hickor','1151SG','119VW','134SC')
                    ORDER BY canonical_property_code
                    \"\"\"
                ),
                {'tid': str(TENANT_ID)},
            )
        ).mappings().all()
        print(json.dumps({'report': report, 'profile_samples': [dict(r) for r in sample]}, indent=2))


asyncio.run(main())
PY"
