from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from collections import defaultdict
from datetime import date
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text

from app.core.db_connect import create_configured_async_engine


TENANT_ID = "e07980b2-a990-4b24-91d1-c8cb71ab70e1"
CORPUS_ROOT = Path("tests/fixtures/inquiry_corpus")
PLATFORM_LIMITS = {
    "direct": 8,
    "airbnb": 6,
    "vrbo": 6,
}


@dataclass
class InquiryRow:
    platform: str
    draft_id: str
    created_at: str
    guest_name: str
    guest_email: str
    parser_source: str
    gmail_message_id: str
    message_text: str
    raw_subject: str
    full_message_text: str
    source_provider: str
    source_thread_id: str
    parser_used: str
    platform_listing_id: str
    platform_unit_id: str
    property_external_id: str
    requested_check_in: Optional[str]
    requested_check_out: Optional[str]
    requested_guests: Optional[int]
    message_body: str
    message_subject: str


def _slug(text_value: str) -> str:
    compact = re.sub(r"[^a-z0-9]+", "_", (text_value or "").strip().lower())
    compact = compact.strip("_")
    return compact[:48] or "fixture"


def _sanitize_phone(text_value: str) -> str:
    return re.sub(r"(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}", "+1-555-0100", text_value)


def _replace_all(text_value: str, replacements: dict[str, str]) -> str:
    result = text_value or ""
    for source, target in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        if source:
            result = result.replace(source, target)
    return _sanitize_phone(result)


def _row_to_replacements(row: InquiryRow, *, index: int) -> dict[str, str]:
    guest_name = f"Guest {index:03d}"
    guest_email = f"guest_{index:03d}@example.test"
    property_token = f"Property_{index:03d}"
    replacements = {
        row.guest_name or "": guest_name,
        row.guest_email or "": guest_email,
        row.property_external_id or "": property_token,
        row.platform_listing_id or "": f"listing_{index:03d}",
        row.platform_unit_id or "": f"unit_{index:03d}",
    }
    if row.platform_listing_id:
        replacements[f"#{row.platform_listing_id}"] = f"#listing_{index:03d}"
    if row.platform == "vrbo":
        external_match = re.search(r"\b\d{4}-\d{5,}\b", row.full_message_text or "")
        if external_match:
            replacements[external_match.group(0)] = f"2403-{index:06d}"
    return replacements


def _build_source_fixture(row: InquiryRow, *, fixture_id: str, index: int) -> dict[str, Any]:
    replacements = _row_to_replacements(row, index=index)
    subject = row.raw_subject or row.message_subject or ""
    body = row.full_message_text or row.message_body or row.message_text or ""
    property_token = replacements.get(row.property_external_id or "", f"Property_{index:03d}")
    guest_alias = replacements.get(row.guest_name or "", f"Guest {index:03d}")
    guest_email_alias = replacements.get(row.guest_email or "", f"guest_{index:03d}@example.test")
    if row.platform == "airbnb":
        from_header = "Airbnb <express@airbnb.com>"
        reply_to = "reply@reply.airbnb.com"
    elif row.platform == "vrbo":
        from_header = f"{guest_alias} <sender@messages.homeaway.com>"
        reply_to = "uuid@messages.homeaway.com"
    else:
        from_header = f"{guest_alias} <{guest_email_alias}>"
        reply_to = guest_email_alias
    llm_payload = {
        "latest_guest_message": _replace_all(row.message_text or body, replacements),
        "property_code_or_name": property_token,
        "sender_name": guest_alias,
        "sender_email": guest_email_alias,
        "requested_guests": row.requested_guests,
        "requested_check_in": row.requested_check_in,
        "requested_check_out": row.requested_check_out,
    }
    return {
        "fixture_id": fixture_id,
        "platform": row.platform,
        "source_channel": "email",
        "source_provider": row.source_provider or row.platform,
        "headers": {
            "From": from_header,
            "Reply-To": reply_to,
            "Message-ID": row.gmail_message_id or f"fixture-{fixture_id}",
            "X-Thread-Id": row.source_thread_id or row.gmail_message_id or f"thread-{fixture_id}",
            "X-Oyvoda-Parser-Used": row.parser_used or "",
        },
        "subject": _replace_all(subject, replacements),
        "plain_text": _replace_all(body, replacements),
        "raw_html": "",
        "llm_extracted_fields": llm_payload,
        "provenance": {
            "tenant_id": TENANT_ID,
            "draft_id": row.draft_id,
            "created_at": row.created_at,
            "gmail_message_id": row.gmail_message_id,
            "parser_source_live": row.parser_source,
            "parser_used_live": row.parser_used,
        },
    }


def _build_expected_fixture(
    row: InquiryRow,
    *,
    fixture_id: str,
    index: int,
    source_fixture: dict[str, Any],
) -> dict[str, Any]:
    property_token = source_fixture["llm_extracted_fields"]["property_code_or_name"]
    plain_text = source_fixture["plain_text"]
    is_vrbo_reply = row.platform == "vrbo" and "has replied to your message" in plain_text.lower()
    expected_check_in = None if is_vrbo_reply else row.requested_check_in
    expected_check_out = None if is_vrbo_reply else row.requested_check_out
    expected_guests = None if row.platform == "vrbo" else row.requested_guests
    expected_property_token = property_token
    if row.platform == "vrbo" and not is_vrbo_reply and "external id" in plain_text.lower():
        expected_property_token = f"ExternalID:2403-{index:06d}"
    if is_vrbo_reply:
        expected_property_token = ""
    route_contains = {
        "airbnb": "airbnb",
        "vrbo": "vrbo",
        "direct": "direct",
    }.get(row.platform, row.platform)
    return {
        "fixture_id": fixture_id,
        "description": f"{row.platform} inquiry captured from live Beach Habitats inbound traffic",
        "expected_route_contains": route_contains,
        "expected_pipeline_output": {
            "platform": row.platform,
            "parser_source_contains": "",
            "guest_name": source_fixture["llm_extracted_fields"]["sender_name"],
            "latest_guest_message_contains": [
                source_fixture["llm_extracted_fields"]["latest_guest_message"][:80]
            ],
            "requested_check_in": expected_check_in,
            "requested_check_out": expected_check_out,
            "requested_guests": expected_guests,
            "platform_listing_id": f"listing_{index:03d}" if row.platform_listing_id else "",
            "platform_unit_id": f"unit_{index:03d}" if row.platform_unit_id else "",
            "property_reference_token": expected_property_token,
        },
    }


async def _fetch_rows(days: int) -> list[InquiryRow]:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    engine = create_configured_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT
                            pbi.platform,
                            pbi.draft_id,
                            pbi.created_at::text AS created_at,
                            COALESCE(NULLIF(pbi.guest_name, ''), mn.sender_display_name, 'Guest') AS guest_name,
                            COALESCE(NULLIF(pbi.guest_email, ''), mn.sender_address, '') AS guest_email,
                            COALESCE(NULLIF(pbi.parser_source, ''), mn.parser_used, '') AS parser_source,
                            COALESCE(pbi.gmail_message_id, '') AS gmail_message_id,
                            COALESCE(pbi.message_text, '') AS message_text,
                            COALESCE(mn.raw_subject, m.subject, '') AS raw_subject,
                            COALESCE(NULLIF(mn.full_message_text, ''), m.body, pbi.message_text, '') AS full_message_text,
                            COALESCE(NULLIF(mn.source_provider, ''), 'gmail') AS source_provider,
                            COALESCE(NULLIF(mn.source_thread_id, ''), pbi.gmail_thread_id, pbi.gmail_message_id, '') AS source_thread_id,
                            COALESCE(NULLIF(mn.parser_used, ''), '') AS parser_used,
                            COALESCE(pbi.platform_listing_id, '') AS platform_listing_id,
                            COALESCE(pbi.platform_unit_id, '') AS platform_unit_id,
                            COALESCE(pbi.property_external_id, '') AS property_external_id,
                            pbi.requested_check_in::text AS requested_check_in,
                            pbi.requested_check_out::text AS requested_check_out,
                            pbi.requested_guests,
                            COALESCE(m.body, '') AS message_body,
                            COALESCE(m.subject, '') AS message_subject
                        FROM pre_booking_inquiries pbi
                        LEFT JOIN message_normalizations mn
                          ON mn.tenant_id = pbi.tenant_id
                         AND mn.source_channel = 'email'
                         AND mn.source_message_id = pbi.gmail_message_id
                        LEFT JOIN messages m
                          ON m.message_id = mn.message_id
                        WHERE pbi.tenant_id = :tenant_id
                          AND pbi.created_at >= NOW() - (:window || ' days')::interval
                          AND pbi.platform IN ('direct', 'airbnb', 'vrbo')
                          AND COALESCE(NULLIF(mn.full_message_text, ''), m.body, pbi.message_text, '') <> ''
                        ORDER BY pbi.created_at DESC
                        """
                    ),
                    {"tenant_id": TENANT_ID, "window": str(days)},
                )
            ).mappings().all()
    finally:
        await engine.dispose()
    return [InquiryRow(**dict(row)) for row in rows]


def _select_rows(rows: list[InquiryRow]) -> list[InquiryRow]:
    selected: list[InquiryRow] = []
    per_platform: dict[str, int] = defaultdict(int)
    seen_shapes: set[tuple[str, str, str]] = set()
    for row in rows:
        limit = PLATFORM_LIMITS.get(row.platform, 0)
        if per_platform[row.platform] >= limit:
            continue
        shape = (
            row.platform,
            row.parser_source or row.parser_used or "",
            _slug((row.raw_subject or row.message_subject or row.message_text)[:80]),
        )
        if shape in seen_shapes:
            continue
        seen_shapes.add(shape)
        selected.append(row)
        per_platform[row.platform] += 1
        if all(per_platform[p] >= PLATFORM_LIMITS[p] for p in PLATFORM_LIMITS):
            break
    return selected


def _write_fixture_set(rows: list[InquiryRow]) -> int:
    CORPUS_ROOT.mkdir(parents=True, exist_ok=True)
    for platform in PLATFORM_LIMITS:
        platform_dir = CORPUS_ROOT / platform
        platform_dir.mkdir(parents=True, exist_ok=True)
        for old_file in platform_dir.glob("*.source.json"):
            old_file.unlink()
        for old_file in platform_dir.glob("*.expected.json"):
            old_file.unlink()
    written = 0
    platform_counts: dict[str, int] = defaultdict(int)
    for index, row in enumerate(rows, start=1):
        platform_dir = CORPUS_ROOT / row.platform
        platform_counts[row.platform] += 1
        local_index = platform_counts[row.platform]
        stem = f"{local_index:03d}_{_slug(row.guest_name or row.message_text or row.draft_id)}"
        fixture_id = f"{row.platform}/{stem}"
        source_fixture = _build_source_fixture(row, fixture_id=fixture_id, index=index)
        expected_fixture = _build_expected_fixture(row, fixture_id=fixture_id, index=index, source_fixture=source_fixture)
        (platform_dir / f"{stem}.source.json").write_text(json.dumps(source_fixture, indent=2, ensure_ascii=False) + "\n")
        (platform_dir / f"{stem}.expected.json").write_text(json.dumps(expected_fixture, indent=2, ensure_ascii=False) + "\n")
        written += 1
    return written


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the real Beach Habitats inquiry regression corpus.")
    parser.add_argument("--days", type=int, default=60, help="Lookback window in days (default: 60).")
    return parser


async def _main_async(days: int) -> int:
    rows = await _fetch_rows(days)
    selected = _select_rows(rows)
    written = _write_fixture_set(selected)
    print(json.dumps({"fetched": len(rows), "selected": len(selected), "written": written}, indent=2))
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return asyncio.run(_main_async(args.days))


if __name__ == "__main__":
    raise SystemExit(main())
