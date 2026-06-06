#!/usr/bin/env python3
"""
Bulk guidebook fetcher and multi-tab extractor.

Reads guidebook URLs from `guidebook_index.jsonl` and attempts to collect:
- Landing page content
- Tab/section content linked from navigation
- In-page tab sections referenced by anchors

Outputs:
- One markdown file per property with all discovered sections
- One JSON metadata file per property
- A run summary JSON
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup


TAB_HINTS = (
    "tab",
    "guide",
    "info",
    "arrival",
    "check",
    "parking",
    "wifi",
    "amenit",
    "house",
    "rule",
    "faq",
    "local",
    "emergency",
)

SKIP_TEXT_PATTERNS = (
    "javascript:void",
    "mailto:",
    "tel:",
)


@dataclass
class PageContent:
    url: str
    title: str
    text: str
    anchor_sections: Dict[str, str]
    discovered_links: List[str]


def sanitize_filename(value: str) -> str:
    text = (value or "").strip()
    if not text:
        text = "unknown"
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", text)
    return text.strip("_")[:120] or "unknown"


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    normalized_query = "&".join(
        f"{k}={v}"
        for k in sorted(query.keys())
        for v in sorted(query[k])
    )
    clean = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        query=normalized_query,
        fragment="",
    )
    return urlunparse(clean)


def load_index(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if not item.get("guidebook_url"):
                continue
            rows.append(item)
    return rows


def is_candidate_tab_url(base_url: str, candidate: str) -> bool:
    if not candidate:
        return False
    lower = candidate.lower()
    if any(p in lower for p in SKIP_TEXT_PATTERNS):
        return False

    base = urlparse(base_url)
    cand = urlparse(candidate)
    if not cand.scheme:
        return True
    if cand.netloc.lower() != base.netloc.lower():
        return False

    blob = f"{cand.path}?{cand.query}".lower()
    if cand.path == base.path and cand.query:
        return True
    if any(h in blob for h in TAB_HINTS):
        return True
    return cand.path.startswith(base.path.rstrip("/") + "/")


def normalize_whitespace(text: str) -> str:
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "iframe", "svg"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    return normalize_whitespace(text)


def extract_anchor_sections(soup: BeautifulSoup) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    for elem in soup.select("[id]"):
        section_id = (elem.get("id") or "").strip()
        if not section_id:
            continue
        text = normalize_whitespace(elem.get_text(separator="\n"))
        if len(text) < 40:
            continue
        sections[section_id] = text
    return sections


def extract_links(base_url: str, soup: BeautifulSoup) -> List[str]:
    links: Set[str] = set()
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if href.startswith("#"):
            links.add(f"{base_url}{href}")
            continue
        if is_candidate_tab_url(base_url, href):
            links.add(urljoin(base_url, href))
    return sorted(links)


def fetch_page(client: httpx.Client, url: str) -> Optional[PageContent]:
    try:
        response = client.get(url, follow_redirects=True)
    except Exception:
        return None
    if response.status_code >= 400:
        return None
    ctype = (response.headers.get("content-type") or "").lower()
    if "html" not in ctype and "text/" not in ctype:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    title = normalize_whitespace((soup.title.get_text() if soup.title else "")) or "Untitled"
    text = extract_text(soup)
    anchors = extract_anchor_sections(soup)
    discovered = extract_links(str(response.url), soup)
    return PageContent(
        url=str(response.url),
        title=title,
        text=text,
        anchor_sections=anchors,
        discovered_links=discovered,
    )


def crawl_guidebook(
    client: httpx.Client,
    start_url: str,
    max_pages: int,
    delay_ms: int,
) -> Tuple[List[PageContent], List[str]]:
    queue: List[str] = [start_url]
    visited: Set[str] = set()
    pages: List[PageContent] = []
    errors: List[str] = []

    while queue and len(pages) < max_pages:
        raw = queue.pop(0)
        if raw.startswith("#"):
            continue

        canonical = canonicalize_url(raw.split("#", 1)[0])
        if canonical in visited:
            continue
        visited.add(canonical)

        page = fetch_page(client, raw)
        if page is None:
            errors.append(f"failed: {raw}")
            continue

        pages.append(page)
        for link in page.discovered_links:
            target = link
            if "#" in target:
                target = target.split("#", 1)[0]
            if not target:
                continue
            c = canonicalize_url(target)
            if c not in visited and c not in [canonicalize_url(x) for x in queue]:
                queue.append(target)

        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)

    return pages, errors


def markdown_for_property(property_id: str, pages: List[PageContent]) -> str:
    lines: List[str] = [f"# Guidebook Extract: {property_id}", ""]
    for idx, page in enumerate(pages, start=1):
        lines.append(f"## Page {idx}: {page.title}")
        lines.append("")
        lines.append(f"Source URL: {page.url}")
        lines.append("")
        lines.append("### Page Text")
        lines.append("")
        lines.append(page.text or "_No text extracted_")
        lines.append("")

        if page.anchor_sections:
            lines.append("### Anchor Sections")
            lines.append("")
            for section_id, section_text in sorted(page.anchor_sections.items()):
                lines.append(f"#### #{section_id}")
                lines.append("")
                lines.append(section_text)
                lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    index_path = Path(args.index).expanduser().resolve()
    out_dir = Path(args.output_dir).expanduser().resolve()
    md_dir = out_dir / "markdown"
    meta_dir = out_dir / "meta"
    md_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    if not index_path.exists():
        print(f"Index not found: {index_path}")
        return 1

    rows = load_index(index_path)
    if args.limit:
        rows = rows[: args.limit]

    summary = {
        "source_index": str(index_path),
        "total_properties": len(rows),
        "processed": 0,
        "failed": 0,
        "with_content": 0,
        "generated_at_epoch": int(time.time()),
        "items": [],
    }

    with httpx.Client(timeout=args.timeout, headers={"User-Agent": args.user_agent}) as client:
        for item in rows:
            unit_code = sanitize_filename(item.get("unit_code") or item.get("address") or "unknown")
            start_url = str(item.get("guidebook_url") or "").strip()
            if not start_url:
                continue

            pages, errors = crawl_guidebook(
                client=client,
                start_url=start_url,
                max_pages=args.max_pages_per_property,
                delay_ms=args.delay_ms,
            )

            md_path = md_dir / f"{unit_code}.md"
            meta_path = meta_dir / f"{unit_code}.json"
            md_path.write_text(markdown_for_property(unit_code, pages), encoding="utf-8")
            meta = {
                "unit_code": item.get("unit_code"),
                "address": item.get("address"),
                "community": item.get("community"),
                "start_url": start_url,
                "pages_fetched": len(pages),
                "urls": [p.url for p in pages],
                "errors": errors,
            }
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

            summary["processed"] += 1
            if errors and not pages:
                summary["failed"] += 1
            if pages:
                summary["with_content"] += 1

            summary["items"].append(
                {
                    "unit_code": item.get("unit_code"),
                    "address": item.get("address"),
                    "pages_fetched": len(pages),
                    "errors": len(errors),
                    "markdown_file": str(md_path),
                    "meta_file": str(meta_path),
                }
            )

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote {summary_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch guidebooks and extract multi-tab content.")
    parser.add_argument(
        "--index",
        default="scripts/output/unit_info_import/guidebook_index.jsonl",
        help="Path to guidebook index jsonl from import_unit_info.py",
    )
    parser.add_argument(
        "--output-dir",
        default="scripts/output/guidebooks",
        help="Output directory for markdown and metadata files.",
    )
    parser.add_argument(
        "--max-pages-per-property",
        type=int,
        default=12,
        help="Max linked pages/tabs to crawl for each property.",
    )
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=250,
        help="Delay between requests in milliseconds.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Request timeout seconds.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional limit for number of properties to process.",
    )
    parser.add_argument(
        "--user-agent",
        default="STR-Guidebook-Importer/1.0",
        help="HTTP User-Agent for fetch requests.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
