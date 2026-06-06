#!/usr/bin/env python3
"""
Bulk importer for UNIT INFO spreadsheets.

Goals:
1. Parse all property rows from a single file.
2. Extract guidebook hyperlinks when present.
3. Output normalized JSON/CSV artifacts for downstream concierge ingestion.

Supported inputs:
- .xlsx (preferred; preserves cell hyperlinks)
- .csv / .tsv

Notes:
- .numbers is not directly supported. Export from Numbers to .xlsx first.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


@dataclass
class ParsedRow:
    row_number: int
    values: Dict[str, Any]
    hyperlinks: Dict[str, str]


def normalize_header(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[\s\-/]+", "_", text)
    text = re.sub(r"[^a-z0-9_]", "", text)
    return text.strip("_")


def maybe_url(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower().startswith(("http://", "https://")):
        return text
    match = URL_RE.search(text)
    return match.group(0) if match else None


def first_non_empty(row: Dict[str, Any], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        raw = row.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return None


def guess_column(headers: List[str], preferred: List[str], contains: List[str]) -> Optional[str]:
    header_set = set(headers)
    for item in preferred:
        if item in header_set:
            return item
    for h in headers:
        if any(token in h for token in contains):
            return h
    return None


def parse_xlsx(path: Path, sheet_name: Optional[str] = None) -> Tuple[str, List[ParsedRow]]:
    try:
        from openpyxl import load_workbook  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "openpyxl is required for .xlsx parsing. Install with: pip install openpyxl"
        ) from exc

    wb = load_workbook(path, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active
    title = ws.title

    rows = ws.iter_rows(min_row=1, values_only=False)
    header_cells = next(rows, None)
    if not header_cells:
        return title, []

    headers = [normalize_header(cell.value) for cell in header_cells]
    parsed: List[ParsedRow] = []

    for row_idx, row_cells in enumerate(rows, start=2):
        row_values: Dict[str, Any] = {}
        row_links: Dict[str, str] = {}
        is_empty = True

        for i, cell in enumerate(row_cells):
            if i >= len(headers):
                continue
            header = headers[i] or f"column_{i+1}"
            value = cell.value
            if value not in (None, ""):
                is_empty = False
            row_values[header] = value
            if cell.hyperlink and cell.hyperlink.target:
                row_links[header] = str(cell.hyperlink.target)

        if is_empty:
            continue
        parsed.append(ParsedRow(row_number=row_idx, values=row_values, hyperlinks=row_links))

    return title, parsed


def parse_delimited(path: Path) -> Tuple[str, List[ParsedRow]]:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    parsed: List[ParsedRow] = []

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        if not reader.fieldnames:
            return path.name, []
        headers = [normalize_header(x) for x in reader.fieldnames]

        for row_idx, raw in enumerate(reader, start=2):
            values = {}
            for k, v in raw.items():
                nk = normalize_header(k)
                values[nk] = v
            if not any(str(v or "").strip() for v in values.values()):
                continue
            parsed.append(ParsedRow(row_number=row_idx, values=values, hyperlinks={}))

    return path.name, parsed


def to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def build_records(rows: List[ParsedRow]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not rows:
        return [], {"skipped_empty_rows": 0}

    headers = sorted({h for row in rows for h in row.values.keys()})

    unit_col = guess_column(
        headers,
        preferred=["unit_code", "property_code", "unit", "code"],
        contains=["unit", "property_code", "unit_code"],
    )
    address_col = guess_column(
        headers,
        preferred=["address", "address_line1", "street_address"],
        contains=["address", "street"],
    )
    community_col = guess_column(
        headers,
        preferred=["community", "market", "submarket"],
        contains=["community", "market"],
    )
    bed_col = guess_column(
        headers,
        preferred=["bedrooms", "beds", "br"],
        contains=["bed", "br"],
    )
    bath_col = guess_column(
        headers,
        preferred=["bathrooms", "baths", "ba"],
        contains=["bath", "ba"],
    )
    guide_col = guess_column(
        headers,
        preferred=["property_guide", "guidebook", "guidebook_url", "guide_url", "property_guidebook"],
        contains=["guide", "manual", "url", "link"],
    )

    records: List[Dict[str, Any]] = []
    skipped = 0

    for parsed in rows:
        row = parsed.values
        guidebook_url: Optional[str] = None

        if guide_col and parsed.hyperlinks.get(guide_col):
            guidebook_url = parsed.hyperlinks[guide_col]
        elif guide_col:
            guidebook_url = maybe_url(row.get(guide_col))
        else:
            for key, value in row.items():
                url = parsed.hyperlinks.get(key) or maybe_url(value)
                if url:
                    guidebook_url = url
                    break

        unit_code = first_non_empty(row, [unit_col] if unit_col else [])
        address = first_non_empty(row, [address_col] if address_col else [])
        community = first_non_empty(row, [community_col] if community_col else [])
        bedrooms = to_float(row.get(bed_col)) if bed_col else None
        bathrooms = to_float(row.get(bath_col)) if bath_col else None

        if not unit_code and not address:
            skipped += 1
            continue

        records.append(
            {
                "source_row": parsed.row_number,
                "unit_code": unit_code,
                "address": address,
                "community": community,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "guidebook_url": guidebook_url,
                "raw": row,
            }
        )

    stats = {
        "detected_columns": {
            "unit_code": unit_col,
            "address": address_col,
            "community": community_col,
            "bedrooms": bed_col,
            "bathrooms": bath_col,
            "guidebook": guide_col,
        },
        "skipped_empty_rows": skipped,
    }
    return records, stats


def write_outputs(
    output_dir: Path,
    source_name: str,
    records: List[Dict[str, Any]],
    stats: Dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "source": source_name,
        "total_records": len(records),
        "records_with_guidebook": sum(1 for r in records if r.get("guidebook_url")),
        "records_missing_guidebook": sum(1 for r in records if not r.get("guidebook_url")),
        "stats": stats,
    }

    normalized_json = output_dir / "properties_normalized.json"
    normalized_csv = output_dir / "properties_normalized.csv"
    links_jsonl = output_dir / "guidebook_index.jsonl"
    concierge_seed = output_dir / "concierge_seed_payloads.jsonl"
    summary_json = output_dir / "import_summary.json"

    normalized_json.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")

    with normalized_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "source_row",
                "unit_code",
                "address",
                "community",
                "bedrooms",
                "bathrooms",
                "guidebook_url",
            ],
        )
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "source_row": record["source_row"],
                    "unit_code": record.get("unit_code"),
                    "address": record.get("address"),
                    "community": record.get("community"),
                    "bedrooms": record.get("bedrooms"),
                    "bathrooms": record.get("bathrooms"),
                    "guidebook_url": record.get("guidebook_url"),
                }
            )

    with links_jsonl.open("w", encoding="utf-8") as f:
        for record in records:
            if not record.get("guidebook_url"):
                continue
            f.write(
                json.dumps(
                    {
                        "unit_code": record.get("unit_code"),
                        "address": record.get("address"),
                        "community": record.get("community"),
                        "guidebook_url": record.get("guidebook_url"),
                    }
                )
                + "\n"
            )

    with concierge_seed.open("w", encoding="utf-8") as f:
        for record in records:
            payload = {
                "property_external_id": record.get("unit_code") or record.get("address"),
                "property_context": {
                    "address": record.get("address"),
                    "community": record.get("community"),
                    "bedrooms": record.get("bedrooms"),
                    "bathrooms": record.get("bathrooms"),
                },
                "guidebook_url": record.get("guidebook_url"),
                "source": "unit_info_importer",
            }
            f.write(json.dumps(payload) + "\n")

    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote {normalized_json}")
    print(f"Wrote {normalized_csv}")
    print(f"Wrote {links_jsonl}")
    print(f"Wrote {concierge_seed}")
    print(f"Wrote {summary_json}")
    print(json.dumps(summary, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import UNIT INFO spreadsheet into normalized artifacts.")
    parser.add_argument(
        "--input",
        required=True,
        help="Path to source file (.xlsx, .csv, .tsv). Export .numbers to .xlsx first.",
    )
    parser.add_argument(
        "--sheet",
        default=None,
        help="Optional sheet name for xlsx files.",
    )
    parser.add_argument(
        "--output-dir",
        default="scripts/output/unit_info_import",
        help="Directory to write output artifacts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()

    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    suffix = input_path.suffix.lower()
    if suffix == ".numbers":
        print(
            "Numbers files are not directly supported. Export to .xlsx first, then rerun.",
            file=sys.stderr,
        )
        return 2

    if suffix == ".xlsx":
        source_name, rows = parse_xlsx(input_path, args.sheet)
    elif suffix in (".csv", ".tsv"):
        source_name, rows = parse_delimited(input_path)
    else:
        print(
            f"Unsupported file type: {suffix}. Use .xlsx, .csv, or .tsv.",
            file=sys.stderr,
        )
        return 3

    records, stats = build_records(rows)
    write_outputs(output_dir=output_dir, source_name=source_name, records=records, stats=stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
