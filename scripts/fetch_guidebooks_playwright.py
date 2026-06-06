#!/usr/bin/env python3
"""
Browser-rendered guidebook extractor for Breezeway links.

DEPRECATED (Session 3, 2026-05).

Beach Habitats guidebook ingestion now uses
`scripts/fetch_guidebooks_api.py`, which calls Breezeway's anonymous
public guide API and preserves the structured source content more
reliably than routed SPA scraping. This Playwright path is retained as
fallback/reference only and should not be treated as the primary
Beach Habitats ingestion route unless the public API becomes
unavailable or incomplete.

Why this exists:
- Static HTTP fetch only captures the shell page.
- Breezeway guidebooks render content via client-side JS/tabs.

This script uses Playwright with a persistent browser profile so you can:
1. Log in once manually (including Cloudflare check if prompted).
2. Reuse that session to extract all property guidebook tabs.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

from playwright.sync_api import BrowserContext, Page, sync_playwright


TAB_SELECTORS = [
    "button[role='tab']",
    "[role='tab']",
    ".tabs button",
    ".tab button",
    ".tab-item",
    "[data-testid*='tab']",
    "a[href*='tab']",
]

CONTENT_SELECTORS = [
    "main",
    "[role='main']",
    ".guidebook-content",
    ".content",
    "article",
    "body",
]


def sanitize_filename(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", text)
    return text.strip("_")[:120] or "unknown"


def normalize_text(text: str) -> str:
    text = re.sub(r"\r\n?", "\n", text or "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_index(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if item.get("guidebook_url"):
                rows.append(item)
    return rows


def best_content_text(page: Page) -> str:
    for sel in CONTENT_SELECTORS:
        locator = page.locator(sel)
        if locator.count() > 0:
            txt = normalize_text(locator.first.inner_text(timeout=3000))
            if txt and len(txt) > 40:
                return txt
    return normalize_text(page.inner_text("body"))


def warm_page(page: Page) -> None:
    """Give client-side apps time to hydrate and lazy-load content."""
    try:
        page.wait_for_timeout(1500)
        page.mouse.wheel(0, 1600)
        page.wait_for_timeout(700)
        page.mouse.wheel(0, -1400)
        page.wait_for_timeout(500)
    except Exception:
        return


def collect_tab_names(page: Page) -> List[str]:
    names: List[str] = []
    seen: Set[str] = set()
    for sel in TAB_SELECTORS:
        locator = page.locator(sel)
        count = locator.count()
        for i in range(count):
            try:
                label = normalize_text(locator.nth(i).inner_text(timeout=1500))
            except Exception:
                continue
            if not label or len(label) < 2:
                continue
            if label.lower() in ("breezeway", "menu"):
                continue
            if label in seen:
                continue
            seen.add(label)
            names.append(label)
    return names


def click_tab_by_name(page: Page, tab_name: str) -> bool:
    for sel in TAB_SELECTORS:
        locator = page.locator(sel).filter(has_text=tab_name)
        if locator.count() == 0:
            continue
        try:
            locator.first.click(timeout=3000)
            page.wait_for_timeout(1000)
            return True
        except Exception:
            continue
    return False


def extract_guidebook(page: Page, url: str, max_tabs: int) -> Dict[str, object]:
    result: Dict[str, object] = {
        "url": url,
        "title": "",
        "landing_text": "",
        "tabs": [],
        "errors": [],
    }

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        result["title"] = page.title()
    except Exception as exc:
        result["errors"].append(f"navigation_failed_domcontentloaded: {exc}")
        try:
            page.goto(url, wait_until="load", timeout=20000)
            page.wait_for_timeout(1000)
            result["title"] = page.title()
        except Exception as exc2:
            result["errors"].append(f"navigation_failed_load: {exc2}")
            return result

    warm_page(page)
    landing_text = best_content_text(page)
    if len(landing_text) < 40:
        # Retry once for slow-render guides.
        page.wait_for_timeout(2500)
        warm_page(page)
        landing_text = best_content_text(page)
    result["landing_text"] = landing_text

    tab_names = collect_tab_names(page)[:max_tabs]
    tab_results: List[Dict[str, str]] = []
    for tab in tab_names:
        ok = click_tab_by_name(page, tab)
        if not ok:
            tab_results.append({"name": tab, "text": "", "status": "click_failed"})
            continue
        txt = best_content_text(page)
        tab_results.append({"name": tab, "text": txt, "status": "ok"})

    result["tabs"] = tab_results
    return result


def write_markdown(unit_code: str, item: Dict[str, object], path: Path) -> None:
    lines: List[str] = [f"# Guidebook Extract: {unit_code}", ""]
    lines.append(f"Source URL: {item.get('url')}")
    lines.append("")
    lines.append("## Landing")
    lines.append("")
    lines.append((item.get("landing_text") or "_No content_"))
    lines.append("")

    for tab in item.get("tabs", []):
        name = tab.get("name") or "Unknown Tab"
        status = tab.get("status")
        lines.append(f"## Tab: {name}")
        lines.append("")
        if status != "ok":
            lines.append(f"_Status: {status}_")
            lines.append("")
            continue
        lines.append(tab.get("text") or "_No content_")
        lines.append("")

    if item.get("errors"):
        lines.append("## Errors")
        lines.append("")
        for err in item["errors"]:
            lines.append(f"- {err}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render and extract Breezeway guidebooks via Playwright.")
    parser.add_argument(
        "--index",
        default="scripts/output/unit_info_import/guidebook_index.jsonl",
        help="Guidebook index jsonl generated by import_unit_info.py",
    )
    parser.add_argument(
        "--output-dir",
        default="scripts/output/guidebooks_browser",
        help="Output directory",
    )
    parser.add_argument(
        "--profile-dir",
        default="scripts/output/playwright_profile",
        help="Persistent browser profile directory for saved login session",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional number of properties to process",
    )
    parser.add_argument(
        "--max-tabs",
        type=int,
        default=20,
        help="Maximum tabs to click per guidebook",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browser in headed mode (recommended for first login / Cloudflare)",
    )
    return parser.parse_args()


def run() -> int:
    args = parse_args()
    index_path = Path(args.index).expanduser().resolve()
    out_dir = Path(args.output_dir).expanduser().resolve()
    md_dir = out_dir / "markdown"
    meta_dir = out_dir / "meta"
    md_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    rows = load_index(index_path)
    if args.limit:
        rows = rows[: args.limit]

    summary = {
        "source_index": str(index_path),
        "total_properties": len(rows),
        "processed": 0,
        "with_landing_content": 0,
        "with_tabs": 0,
        "items": [],
        "generated_at_epoch": int(time.time()),
    }

    with sync_playwright() as p:
        context: BrowserContext = p.chromium.launch_persistent_context(
            user_data_dir=str(Path(args.profile_dir).expanduser().resolve()),
            headless=not args.headed,
            viewport={"width": 1440, "height": 920},
        )
        page = context.new_page()

        for row in rows:
            unit_code = sanitize_filename(row.get("unit_code") or row.get("address") or "unknown")
            url = row.get("guidebook_url") or ""
            print(f"[guidebook] {unit_code} -> {url}")

            extracted = extract_guidebook(page, url, max_tabs=args.max_tabs)
            tab_count = len([t for t in extracted.get("tabs", []) if t.get("status") == "ok"])

            md_path = md_dir / f"{unit_code}.md"
            meta_path = meta_dir / f"{unit_code}.json"
            write_markdown(unit_code, extracted, md_path)
            meta_path.write_text(json.dumps(extracted, indent=2), encoding="utf-8")

            summary["processed"] += 1
            if len((extracted.get("landing_text") or "").strip()) > 40:
                summary["with_landing_content"] += 1
            if tab_count > 0:
                summary["with_tabs"] += 1

            summary["items"].append(
                {
                    "unit_code": row.get("unit_code"),
                    "address": row.get("address"),
                    "url": url,
                    "tabs_extracted": tab_count,
                    "errors": extracted.get("errors", []),
                    "markdown_file": str(md_path),
                    "meta_file": str(meta_path),
                }
            )

        context.close()

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
