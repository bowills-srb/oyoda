#!/usr/bin/env python3
"""
[DEPRECATED — Phase 3]

This script is superseded by POST /api/v1/operator/properties/reconcile.

The reconcile endpoint:
- Authenticates the operator (this script bypasses auth).
- Resolves canonical tenant_id from the auth context (this script hardcodes operator strings).
- Runs the same guidebook ingest path via GuidebookIngestService (3G).
- Reconciles property additions, deactivations, and embedding deletes atomically.

Running this script after Phase 3 will succeed mechanically but:
- Writes happen without operator authentication.
- Tenant scoping relies on the script's hardcoded constants, not the JWT.
- Property table state is NOT reconciled — only embeddings are touched.

To ingest a portfolio, call the reconcile endpoint with an operator JWT instead.

Transform extracted guidebook markdown into structured concierge knowledge.

Input:
- markdown files from fetch_guidebooks_playwright.py

Output:
- Per-property JSON knowledge files
- Combined bulk payload for ingestion
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _print_deprecation_banner() -> None:
    banner = (
        "\n"
        "===================================================================\n"
        " DEPRECATED — Phase 3\n"
        "===================================================================\n"
        " This script is superseded by:\n"
        "   POST /api/v1/operator/properties/reconcile\n"
        "\n"
        " The reconcile endpoint authenticates the operator, resolves\n"
        " canonical tenant_id, runs the same guidebook ingest, and\n"
        " reconciles property additions/deactivations atomically.\n"
        "\n"
        " To proceed with this script anyway, set:\n"
        "   OYVODA_ALLOW_LEGACY_INGEST=1\n"
        "===================================================================\n"
    )
    print(banner, file=sys.stderr)
    if os.environ.get("OYVODA_ALLOW_LEGACY_INGEST") != "1":
        print(
            "Refusing to run. Set OYVODA_ALLOW_LEGACY_INGEST=1 to override.",
            file=sys.stderr,
        )
        sys.exit(1)


SECTION_HINTS = {
    "check_in": ["check in", "check-in", "arrival"],
    "check_out": ["check out", "check-out", "checkout", "departure"],
    "wifi": ["wifi", "wi-fi", "internet", "password"],
    "parking": ["parking", "park", "garage"],
    "door_lock": ["door lock", "lock", "keypad", "code"],
    "shipping": ["shipping", "package", "ups"],
    "bikes": ["bike", "bikes", "bike lock"],
    "pool": ["pool", "beach club", "wristband", "amenity wristband"],
    "beach": ["beach", "beach setup", "beach gear", "chairs"],
    "hvac": ["ac unit", "air conditioning", "thermostat"],
    "appliance": ["refrigerator", "coffee maker"],
    "transport": ["shuttle", "trolley"],
    "emergency": ["emergency", "urgent", "911"],
}


FAQ_PATTERNS: List[Tuple[str, str, str]] = [
    ("wifi", r"wifi password[:\s]+([^\n]+)", "Wifi password is {value}."),
    ("check_in", r"check in[:\s]+([^\n]+)", "Check-in is {value}."),
    ("check_out", r"checkout[:\s]+([^\n]+)|check out[:\s]+([^\n]+)", "Checkout is {value}."),
]


def normalize_text(text: str) -> str:
    text = re.sub(r"\r\n?", "\n", text or "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_property_map(path: Path) -> Dict[str, Dict[str, Any]]:
    mapping: Dict[str, Dict[str, Any]] = {}
    if not path.exists():
        return mapping
    records = json.loads(path.read_text(encoding="utf-8"))
    for r in records:
        key = str(r.get("unit_code") or "").strip()
        if key:
            mapping[key] = r
    return mapping


def extract_sections(text: str) -> Dict[str, str]:
    lines = [ln.strip() for ln in text.splitlines()]
    sections: Dict[str, List[str]] = {k: [] for k in SECTION_HINTS.keys()}

    current_key: Optional[str] = None
    for line in lines:
        lower = line.lower()

        matched = None
        for key, hints in SECTION_HINTS.items():
            if any(h in lower for h in hints):
                matched = key
                break

        if matched:
            current_key = matched
            sections[current_key].append(line)
            continue

        if current_key and line:
            sections[current_key].append(line)
        elif not line:
            current_key = None

    cleaned: Dict[str, str] = {}
    for key, chunk in sections.items():
        body = normalize_text("\n".join(chunk))
        if body:
            cleaned[key] = body
    return cleaned


def extract_facts(text: str) -> Dict[str, str]:
    facts: Dict[str, str] = {}
    normalized = text.lower()

    for fact_key, pattern, _ in FAQ_PATTERNS:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        value = next((g for g in match.groups() if g), None)
        if value:
            facts[fact_key] = value.strip()
    return facts


def build_faq(sections: Dict[str, str], facts: Dict[str, str]) -> List[Dict[str, str]]:
    faq: List[Dict[str, str]] = []

    fact_templates = {k: tpl for k, _, tpl in FAQ_PATTERNS}
    for key, value in facts.items():
        faq.append(
            {
                "question": key.replace("_", " ").title(),
                "answer": fact_templates[key].format(value=value),
                "source": "fact_extraction",
            }
        )

    for key, body in sections.items():
        if len(body) < 80:
            continue
        question = {
            "parking": "Where should we park?",
            "door_lock": "How do we lock and unlock the door?",
            "bikes": "Do we have bikes and where are they?",
            "pool": "What are the pool and wristband rules?",
            "beach": "What beach setup and gear info should we know?",
            "shipping": "Can we ship packages to the property?",
            "transport": "Is there a shuttle or trolley?",
            "hvac": "Any AC or thermostat guidance?",
            "appliance": "Any appliance instructions?",
        }.get(key)
        if not question:
            continue
        faq.append(
            {
                "question": question,
                "answer": body,
                "source": f"section:{key}",
            }
        )
    return faq


def parse_markdown(md_text: str) -> str:
    # Remove top-level generated headers to keep only meaningful content.
    lines = md_text.splitlines()
    keep: List[str] = []
    for ln in lines:
        if ln.startswith("# Guidebook Extract:"):
            continue
        if ln.startswith("Source URL:"):
            continue
        if ln.strip() == "## Landing":
            continue
        keep.append(ln)
    return normalize_text("\n".join(keep))


def build_record(
    unit_code: str,
    markdown_path: Path,
    property_map: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    raw_md = markdown_path.read_text(encoding="utf-8")
    content = parse_markdown(raw_md)
    sections = extract_sections(content)
    facts = extract_facts(content)
    faq = build_faq(sections, facts)
    prop = property_map.get(unit_code, {})

    return {
        "unit_code": unit_code,
        "property_context": {
            "address": prop.get("address"),
            "community": prop.get("community"),
            "bedrooms": prop.get("bedrooms"),
            "bathrooms": prop.get("bathrooms"),
        },
        "guidebook_url": prop.get("guidebook_url"),
        "facts": facts,
        "sections": sections,
        "faq": faq,
        "raw_text_length": len(content),
    }


def run(args: argparse.Namespace) -> int:
    markdown_dir = Path(args.markdown_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    properties_json = Path(args.properties_json).expanduser().resolve()

    if not markdown_dir.exists():
        print(f"Markdown dir not found: {markdown_dir}")
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    per_property_dir = output_dir / "per_property"
    per_property_dir.mkdir(parents=True, exist_ok=True)

    property_map = load_property_map(properties_json)

    rows: List[Dict[str, Any]] = []
    for md_file in sorted(markdown_dir.glob("*.md")):
        unit_code = md_file.stem
        record = build_record(unit_code, md_file, property_map)
        rows.append(record)
        (per_property_dir / f"{unit_code}.json").write_text(
            json.dumps(record, indent=2),
            encoding="utf-8",
        )

    bulk_path = output_dir / "concierge_knowledge_bulk.json"
    bulk_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    jsonl_path = output_dir / "concierge_knowledge_bulk.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    summary = {
        "total_properties": len(rows),
        "with_faq": sum(1 for r in rows if r["faq"]),
        "with_facts": sum(1 for r in rows if r["facts"]),
        "avg_faq_per_property": (
            round(sum(len(r["faq"]) for r in rows) / len(rows), 2) if rows else 0.0
        ),
        "output_dir": str(output_dir),
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"Wrote {bulk_path}")
    print(f"Wrote {jsonl_path}")
    print(f"Wrote {summary_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build concierge knowledge from extracted guidebooks.")
    parser.add_argument(
        "--markdown-dir",
        default="scripts/output/guidebooks_browser/markdown",
        help="Directory containing extracted markdown files.",
    )
    parser.add_argument(
        "--properties-json",
        default="scripts/output/unit_info_import/properties_normalized.json",
        help="Normalized property records JSON from import_unit_info.py",
    )
    parser.add_argument(
        "--output-dir",
        default="scripts/output/concierge_knowledge",
        help="Output directory for concierge knowledge artifacts.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    _print_deprecation_banner()
    raise SystemExit(run(parse_args()))
