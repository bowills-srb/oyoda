#!/usr/bin/env python3
"""
Diagnose Breezeway public-guide API payloads for a portfolio.

For each property in the input payload JSON, fetch the same Breezeway public
API endpoint that GuidebookIngestService uses, and report:
  - HTTP status and content type
  - Top-level JSON keys
  - Page / section / block counts
  - Total content character count (after HTML cleanup, same heuristic as the
    ingest service's _html_to_text)
  - Per-section block count and content chars

Also writes the full raw JSON response for any property whose total content
chars fall below the chunker's min_chars threshold (60), so we can manually
inspect whether the payload is empty (operator content gap) or structurally
different from what render_markdown_from_payload expects (parser gap).

Usage:
    python scripts/diagnose_breezeway_payloads.py \\
        --payload tmp/phase3_reconcile/beach_habitats_pass2_with_guidebooks.json \\
        --output  tmp/phase3_reconcile/breezeway_payload_diagnostic.json \\
        --raw-dir tmp/phase3_reconcile/raw_payloads

Reads no DB state, makes no writes outside the output paths, and does not
require any deployment credentials. Just HTTPS GET to the public API.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx


GUIDEBOOK_API_BASE = "https://api.breezeway.io/public/guides"
DEFAULT_USER_AGENT = "Oyvoda/1.0 guidebook-ingestion"
MIN_CHARS_THRESHOLD = 60  # matches parse_guidebook_markdown's default min_chars

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTISPACE_RE = re.compile(r"[ \t]+")
_MULTINEWLINE_RE = re.compile(r"\n{3,}")


def _html_to_text(value: str) -> str:
    """Same heuristic as guidebook_ingest_service._html_to_text."""
    text = unescape(value or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"(?i)</h[1-6]>", "\n", text)
    text = _HTML_TAG_RE.sub("", text)
    text = _MULTISPACE_RE.sub(" ", text)
    text = _MULTINEWLINE_RE.sub("\n\n", text)
    return text.strip()


def _extract_block_text(data: Any) -> str:
    """Same heuristic as guidebook_ingest_service._extract_block_text."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("content"), str):
            return data["content"]
        if isinstance(data.get("html"), str):
            return data["html"]
        return json.dumps(data, ensure_ascii=False)
    if isinstance(data, list):
        return "\n".join(_extract_block_text(item) for item in data if item is not None)
    return str(data)


def extract_guide_token(url: str) -> str:
    match = re.match(r"^https://guide\.breezeway\.io/([^/?#]+)", (url or "").strip())
    if not match:
        raise ValueError(f"Unsupported guidebook URL: {url}")
    return match.group(1)


def analyze_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Walk pages/sections/blocks and compute structural stats."""
    pages = payload.get("pages") or []
    page_count = len(pages)
    section_count = 0
    block_count = 0
    total_content_chars = 0
    sections_detail: List[Dict[str, Any]] = []

    for page in pages:
        if not isinstance(page, dict):
            continue
        page_title = str(page.get("title") or "").strip() or "Guide"
        for section in page.get("sections") or []:
            if not isinstance(section, dict):
                continue
            section_count += 1
            section_title = str(section.get("title") or "").strip() or "(untitled)"
            blocks = section.get("blocks") or []
            section_block_count = 0
            section_content_chars = 0
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                section_block_count += 1
                raw_text = _extract_block_text(block.get("data"))
                clean = _html_to_text(raw_text)
                section_content_chars += len(clean)
            block_count += section_block_count
            total_content_chars += section_content_chars
            sections_detail.append({
                "page_title": page_title,
                "section_title": section_title,
                "block_count": section_block_count,
                "content_chars": section_content_chars,
            })

    return {
        "top_level_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
        "page_count": page_count,
        "section_count": section_count,
        "block_count": block_count,
        "total_content_chars": total_content_chars,
        "below_chunk_threshold": total_content_chars < MIN_CHARS_THRESHOLD,
        "sections": sections_detail,
    }


async def fetch_one(
    client: httpx.AsyncClient,
    property_code: str,
    guide_token: str,
) -> Dict[str, Any]:
    url = f"{GUIDEBOOK_API_BASE}/{guide_token}"
    try:
        resp = await client.get(url)
    except httpx.HTTPError as exc:
        return {
            "property_code": property_code,
            "guide_token": guide_token,
            "url": url,
            "fetch_error": f"{type(exc).__name__}: {exc}",
        }

    result: Dict[str, Any] = {
        "property_code": property_code,
        "guide_token": guide_token,
        "url": url,
        "http_status": resp.status_code,
        "content_type": resp.headers.get("Content-Type", ""),
        "body_bytes": len(resp.content),
    }

    if "json" not in (result["content_type"] or "").lower():
        result["error"] = "non-JSON response"
        result["body_preview"] = resp.content[:500].decode("utf-8", errors="replace")
        return result

    try:
        payload = json.loads(resp.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        result["error"] = f"json_decode_error: {exc}"
        result["body_preview"] = resp.content[:500].decode("utf-8", errors="replace")
        return result

    if not isinstance(payload, dict):
        result["error"] = "payload is not a JSON object"
        result["body_preview"] = json.dumps(payload)[:500]
        return result

    result["raw_payload"] = payload  # held in memory; written to disk only for below-threshold properties
    result.update(analyze_payload(payload))
    return result


async def run(
    payload_path: Path,
    output_path: Path,
    raw_dir: Optional[Path],
    concurrency: int,
) -> int:
    payload_data = json.loads(payload_path.read_text())
    properties = payload_data.get("properties") or []
    if not properties:
        print(f"ERROR: no properties in {payload_path}", file=sys.stderr)
        return 1

    if raw_dir is not None:
        raw_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json",
    }
    semaphore = asyncio.Semaphore(concurrency)
    results: List[Dict[str, Any]] = []

    async def bounded_fetch(client: httpx.AsyncClient, prop: Dict[str, Any]) -> None:
        async with semaphore:
            code = str(prop.get("property_code", "")).strip()
            url = str(prop.get("guidebook_url") or "").strip()
            if not url:
                results.append({
                    "property_code": code,
                    "skipped": "no guidebook_url in input payload",
                })
                return
            try:
                token = extract_guide_token(url)
            except ValueError as exc:
                results.append({
                    "property_code": code,
                    "error": str(exc),
                })
                return
            result = await fetch_one(client, code, token)
            results.append(result)

    async with httpx.AsyncClient(timeout=30.0, headers=headers, follow_redirects=True) as client:
        await asyncio.gather(*(bounded_fetch(client, p) for p in properties))

    # Sort for deterministic output
    results.sort(key=lambda r: r.get("property_code", ""))

    # Separate raw payloads from summary; only persist raw for below-threshold properties
    summary_results: List[Dict[str, Any]] = []
    below_threshold: List[str] = []
    for r in results:
        raw = r.pop("raw_payload", None)
        if raw is not None and r.get("below_chunk_threshold"):
            below_threshold.append(r["property_code"])
            if raw_dir is not None:
                code_safe = re.sub(r"[^A-Za-z0-9_.-]", "_", r["property_code"])
                (raw_dir / f"{code_safe}.json").write_text(
                    json.dumps(raw, ensure_ascii=False, indent=2)
                )
        summary_results.append(r)

    output = {
        "input_payload": str(payload_path),
        "min_chars_threshold": MIN_CHARS_THRESHOLD,
        "total_properties": len(properties),
        "fetched": sum(1 for r in summary_results if "http_status" in r),
        "below_chunk_threshold_count": len(below_threshold),
        "below_chunk_threshold_codes": sorted(below_threshold),
        "results": summary_results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))

    # Console summary
    print(f"Wrote summary to {output_path}")
    print(f"Total properties: {output['total_properties']}")
    print(f"Successfully fetched: {output['fetched']}")
    print(f"Below {MIN_CHARS_THRESHOLD}-char chunk threshold: {len(below_threshold)}")
    if below_threshold:
        print("  Codes:", ", ".join(below_threshold))
        if raw_dir:
            print(f"  Raw payloads written to: {raw_dir}/")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", required=True, type=Path,
                        help="Path to the reconcile payload JSON (with property_code + guidebook_url)")
    parser.add_argument("--output", required=True, type=Path,
                        help="Path to write the diagnostic summary JSON")
    parser.add_argument("--raw-dir", type=Path, default=None,
                        help="If set, raw JSON payloads for below-threshold properties go here")
    parser.add_argument("--concurrency", type=int, default=6,
                        help="Max concurrent API requests (default 6)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    sys.exit(asyncio.run(run(args.payload, args.output, args.raw_dir, args.concurrency)))
