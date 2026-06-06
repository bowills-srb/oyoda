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

Guidebook Knowledge Indexer

Reads all 42 Breezeway guidebook markdown files and indexes them
into the vector store so the Librarian Agent can answer property-
specific questions (TV instructions, bike lock codes, pool hours,
parking, wristband info, etc.)

Usage:
    # Dry run — show what would be indexed without writing to DB
    python scripts/index_guidebooks.py --dry-run

    # Index all properties
    python scripts/index_guidebooks.py

    # Index a single property
    python scripts/index_guidebooks.py --property 134MC

    # Re-index (wipe + rewrite) a property
    python scripts/index_guidebooks.py --property 134MC --force

    # Verbose output
    python scripts/index_guidebooks.py --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Path setup ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

GUIDEBOOK_DIR = REPO_ROOT / "scripts" / "output" / "guidebooks_browser" / "markdown"
SUMMARY_FILE  = REPO_ROOT / "scripts" / "output" / "guidebooks_browser" / "summary.json"

OPERATOR_ID   = "beach_habitats"   # single operator for now

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("index_guidebooks")


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


# ─────────────────────────────────────────────────────────────────────────────
# Section chunking
# ─────────────────────────────────────────────────────────────────────────────

# Patterns that mark the start of a new guidebook section
_SECTION_RE = re.compile(
    r"^#{1,3}\s+.+$",
    re.MULTILINE,
)

# Sections we want to keep vs skip
_SKIP_SECTIONS = {
    "reservation info", # structured data already in DB
    "getting here",     # address, duplicated
    "wifi",             # already in quick-answer templates
    "more...",          # pagination artifact
}

# Nav boilerplate that appears in the Landing section — strip these lines
_NAV_LINES = {"beach habitats 30a", "stay", "guide", "contact", "search", "about property"}

# Classify content into doc_type buckets
_TYPE_KEYWORDS: List[Tuple[str, str]] = [
    ("pool", "property_amenity"),
    ("bike", "property_amenity"),
    ("beach", "property_amenity"),
    ("wristband", "property_amenity"),
    ("parking", "property_info"),
    ("door", "property_info"),
    ("check in", "property_info"),
    ("check out", "property_info"),
    ("shipping", "property_info"),
    ("trash", "property_info"),
    ("recycl", "property_info"),
    ("ac unit", "property_info"),
    ("air condition", "property_info"),
    ("refrigerator", "property_info"),
    ("dishwasher", "property_info"),
    ("oven", "property_info"),
    ("coffee", "property_info"),
    ("washer", "property_info"),
    ("dryer", "property_info"),
    ("speaker", "property_info"),
    ("tv", "property_info"),
    ("television", "property_info"),
    ("cable", "property_info"),
    ("internet", "property_info"),
    ("shuttle", "local_tip"),
    ("trolley", "local_tip"),
    ("restaurant", "dining"),
    ("dining", "dining"),
    ("food", "dining"),
    ("beach chair", "activity"),
    ("beach setup", "activity"),
    ("kayak", "activity"),
    ("paddleboard", "activity"),
    ("golf cart", "activity"),
    ("rule", "property_rules"),
    ("quiet hour", "property_rules"),
    ("pet", "property_rules"),
    ("smoke", "property_rules"),
    ("noise", "property_rules"),
    ("guest", "property_rules"),
]


@dataclass
class Chunk:
    """A single indexable chunk from a guidebook."""
    property_code: str
    property_address: str
    section_title: str
    content: str
    doc_type: str
    char_count: int = 0

    def __post_init__(self):
        self.char_count = len(self.content)

    @property
    def doc_id(self) -> str:
        key = f"{self.property_code}|{self.section_title}|{self.content[:100]}"
        return "gb_" + hashlib.md5(key.encode()).hexdigest()[:14]

    def to_searchable_text(self) -> str:
        """Text actually embedded — include property name for context."""
        return (
            f"Property {self.property_address} ({self.property_code}). "
            f"{self.section_title}: {self.content}"
        )

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "operator_id": OPERATOR_ID,
            "property_code": self.property_code,
            "property_address": self.property_address,
            "doc_type": self.doc_type,
            "section_title": self.section_title,
            "source": "breezeway_guidebook",
            "char_count": self.char_count,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Markdown parser
# ─────────────────────────────────────────────────────────────────────────────

def _infer_doc_type(title: str, body: str) -> str:
    combined = (title + " " + body).lower()
    for keyword, doc_type in _TYPE_KEYWORDS:
        if keyword in combined:
            return doc_type
    return "property_info"


def _clean_text(text: str) -> str:
    """Strip markdown noise, nav boilerplate, collapse whitespace."""
    # Remove nav boilerplate lines (from Landing section)
    lines = []
    for line in text.splitlines():
        if line.strip().lower() not in _NAV_LINES:
            lines.append(line)
    text = "\n".join(lines)
    # Remove markdown links but keep text: [text](url) → text
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Remove bare URLs that are very long (keep short ones like phone numbers)
    text = re.sub(r"https?://\S{60,}", "", text)
    # Collapse excessive newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_guidebook(
    markdown_path: Path,
    property_code: str,
    property_address: str,
    min_chars: int = 60,
    max_chars: int = 1200,
) -> List[Chunk]:
    """
    Parse a Breezeway guidebook markdown file into indexable chunks.

    Strategy:
    - Split on ## / ### headers
    - Skip boilerplate sections (wifi, reservation info, etc.)
    - Merge tiny adjacent paragraphs within the same section
    - Split very long sections at paragraph boundaries
    - Assign doc_type based on content keywords
    """
    raw = markdown_path.read_text(encoding="utf-8", errors="ignore")
    chunks: List[Chunk] = []

    # Split into (section_title, body) pairs
    sections: List[Tuple[str, str]] = []
    parts = _SECTION_RE.split(raw)
    headers = _SECTION_RE.findall(raw)

    # First part before any header — usually just the H1 property title
    if parts and parts[0].strip():
        sections.append(("Introduction", parts[0]))

    for header, body in zip(headers, parts[1:]):
        title = header.lstrip("#").strip()
        sections.append((title, body))

    for title, body in sections:
        # Skip boilerplate
        if title.lower() in _SKIP_SECTIONS:
            continue
        if any(skip in title.lower() for skip in _SKIP_SECTIONS):
            continue

        body_clean = _clean_text(body)
        if len(body_clean) < min_chars:
            continue

        doc_type = _infer_doc_type(title, body_clean)

        # If body is short enough, single chunk
        if len(body_clean) <= max_chars:
            chunks.append(Chunk(
                property_code=property_code,
                property_address=property_address,
                section_title=title,
                content=body_clean,
                doc_type=doc_type,
            ))
        else:
            # Split at paragraph boundaries (double newline)
            paragraphs = [p.strip() for p in re.split(r"\n\n+", body_clean) if p.strip()]
            current: List[str] = []
            current_len = 0

            for para in paragraphs:
                if current_len + len(para) > max_chars and current:
                    chunks.append(Chunk(
                        property_code=property_code,
                        property_address=property_address,
                        section_title=title,
                        content="\n\n".join(current),
                        doc_type=doc_type,
                    ))
                    current = [para]
                    current_len = len(para)
                else:
                    current.append(para)
                    current_len += len(para)

            if current:
                chunks.append(Chunk(
                    property_code=property_code,
                    property_address=property_address,
                    section_title=title,
                    content="\n\n".join(current),
                    doc_type=doc_type,
                ))

    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# Dry-run reporter
# ─────────────────────────────────────────────────────────────────────────────

def report_dry_run(all_chunks: Dict[str, List[Chunk]]) -> None:
    total = sum(len(v) for v in all_chunks.values())
    print(f"\n{'='*60}")
    print(f"DRY RUN — {len(all_chunks)} properties, {total} total chunks")
    print(f"{'='*60}\n")

    type_counts: Dict[str, int] = {}
    for code, chunks in sorted(all_chunks.items()):
        print(f"  {code:12s}  {len(chunks):3d} chunks")
        for c in chunks:
            type_counts[c.doc_type] = type_counts.get(c.doc_type, 0) + 1

    print(f"\nBy doc_type:")
    for dt, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {dt:25s}  {count}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# DB indexing
# ─────────────────────────────────────────────────────────────────────────────

async def index_chunks(
    chunks: List[Chunk],
    session,
    force: bool = False,
    verbose: bool = False,
) -> Tuple[int, int]:
    """
    Write chunks to the vector store via VectorStore.add_documents().
    Returns (inserted, updated).
    """
    from app.services.knowledge.vector_store import Document, VectorStore

    store = VectorStore(session)

    documents = []
    for c in chunks:
        documents.append(Document(
            doc_id=c.doc_id,
            content=c.to_searchable_text(),
            metadata=c.to_metadata(),
        ))

    if force and chunks:
        property_code = chunks[0].property_code
        deleted = await store.delete_by_property(OPERATOR_ID, property_code)
        if verbose:
            logger.info("  Deleted %d existing docs for %s", deleted, property_code)

    result = await store.add_documents(documents)
    return result["inserted"], result["updated"]


async def run(
    target_property: Optional[str],
    dry_run: bool,
    force: bool,
    verbose: bool,
) -> None:
    # Load summary to get property→address mapping
    summary = json.loads(SUMMARY_FILE.read_text())
    items = {item["unit_code"]: item for item in summary["items"]}

    if target_property:
        if target_property not in items:
            print(f"❌ Property '{target_property}' not found in summary.json")
            print(f"   Available: {', '.join(sorted(items.keys()))}")
            sys.exit(1)
        selected = {target_property: items[target_property]}
    else:
        selected = items

    # Parse all guidebooks
    all_chunks: Dict[str, List[Chunk]] = {}
    skipped = []

    for code, item in selected.items():
        md_path = Path(item["markdown_file"])
        if not md_path.exists():
            skipped.append(code)
            continue

        address = item["address"]
        chunks = parse_guidebook(md_path, code, address)

        if chunks:
            all_chunks[code] = chunks
        else:
            skipped.append(code)
            if verbose:
                logger.warning("No chunks extracted for %s", code)

    if skipped:
        logger.warning("Skipped %d properties (no content): %s", len(skipped), skipped)

    if dry_run:
        report_dry_run(all_chunks)
        return

    # Connect to DB and index
    print(f"\n{'='*60}")
    print(f"INDEXING {len(all_chunks)} properties into vector store")
    print(f"{'='*60}\n")

    from app.core.database import get_db_session

    total_inserted = 0
    total_updated = 0
    errors = []

    async with get_db_session() as session:
        for code, chunks in sorted(all_chunks.items()):
            try:
                inserted, updated = await index_chunks(
                    chunks, session, force=force, verbose=verbose
                )
                total_inserted += inserted
                total_updated += updated
                status = f"+{inserted} new" if inserted else ""
                if updated:
                    status += f"  ~{updated} updated"
                print(f"  ✓ {code:12s}  {len(chunks):3d} chunks  {status}")
            except Exception as exc:
                errors.append((code, str(exc)))
                print(f"  ✗ {code:12s}  ERROR: {exc}")
                logger.exception("Failed indexing %s", code)

    print(f"\n{'─'*60}")
    print(f"Done.  Inserted: {total_inserted}  Updated: {total_updated}")
    if errors:
        print(f"Errors ({len(errors)}):")
        for code, err in errors:
            print(f"  {code}: {err}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Index Breezeway guidebooks into vector store")
    parser.add_argument(
        "--property", "-p",
        metavar="CODE",
        help="Index only this property code (e.g. 134MC). Omit to index all.",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Parse and show chunk counts without writing to DB.",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Delete existing chunks for each property before re-indexing.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show per-chunk detail.",
    )
    args = parser.parse_args()

    asyncio.run(run(
        target_property=args.property,
        dry_run=args.dry_run,
        force=args.force,
        verbose=args.verbose,
    ))


if __name__ == "__main__":
    _print_deprecation_banner()
    main()
