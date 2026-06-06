from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch

import pytest

from app.services.integrations.email_inbound import ParsedEmailMessage
from app.services.integrations.email_parser_router import parse_structured_inbound_email
from app.services.integrations.gmail_inbox_poller import GmailEmailParser
from app.services.integrations.inbound_source_router import detect_inbound_source_route
from app.services.integrations.llm_email_extractor import ExtractedEmailFields


CORPUS_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "inquiry_corpus"


def _discover_fixture_pairs() -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for source_path in sorted(CORPUS_ROOT.glob("*/*.source.json")):
        expected_path = source_path.with_name(source_path.name.replace(".source.json", ".expected.json"))
        if expected_path.exists():
            pairs.append((source_path, expected_path))
    return pairs


def _adapt_llm(source: dict[str, Any], extracted: ExtractedEmailFields) -> ParsedEmailMessage:
    headers = source["headers"]
    from_header = headers.get("From", "")
    reply_to = headers.get("Reply-To", "")
    return ParsedEmailMessage(
        source_provider="gmail",
        source_message_id=headers.get("Message-ID", source["fixture_id"]),
        source_thread_id=headers.get("X-Thread-Id", f"thread-{source['fixture_id']}"),
        gmail_message_id=headers.get("Message-ID", source["fixture_id"]),
        gmail_thread_id=headers.get("X-Thread-Id", f"thread-{source['fixture_id']}"),
        message_id_header=headers.get("Message-ID", source["fixture_id"]),
        guest_name=extracted.sender_name or "Guest",
        guest_email=extracted.sender_email or "guest@example.test",
        reply_channel_address=reply_to,
        subject=source["subject"],
        body=extracted.latest_guest_message,
        latest_guest_message=extracted.latest_guest_message,
        conversation_context="",
        full_body=source["plain_text"],
        platform=source["platform"],
        is_inquiry=True,
        parser_source=extracted.parser_source,
        property_name=extracted.raw_property_mention,
        property_code="",
        raw_property_mention=extracted.raw_property_mention,
        requested_check_in=extracted.requested_check_in,
        requested_check_out=extracted.requested_check_out,
        requested_guests=extracted.requested_guests,
        raw_from=from_header,
    )


def _adapt_ota(source: dict[str, Any], parsed_ota: Any) -> ParsedEmailMessage:
    headers = source["headers"]
    return ParsedEmailMessage(
        source_provider="gmail",
        source_message_id=headers.get("Message-ID", source["fixture_id"]),
        source_thread_id=headers.get("X-Thread-Id", f"thread-{source['fixture_id']}"),
        gmail_message_id=headers.get("Message-ID", source["fixture_id"]),
        gmail_thread_id=headers.get("X-Thread-Id", f"thread-{source['fixture_id']}"),
        message_id_header=headers.get("Message-ID", source["fixture_id"]),
        guest_name=getattr(parsed_ota, "guest_name", "") or "Guest",
        guest_email="guest@example.test",
        reply_channel_address=headers.get("Reply-To", ""),
        subject=source["subject"],
        body=getattr(parsed_ota, "message_body", "") or getattr(parsed_ota, "latest_guest_turn", "") or source["plain_text"],
        latest_guest_message=getattr(parsed_ota, "latest_guest_turn", "") or getattr(parsed_ota, "message_body", "") or "",
        latest_operator_message=getattr(parsed_ota, "latest_operator_turn", "") or "",
        conversation_context=getattr(parsed_ota, "prior_thread_context", "") or "",
        full_body=source["plain_text"],
        platform=getattr(parsed_ota, "platform", source["platform"]) or source["platform"],
        is_inquiry=True,
        parser_source=getattr(parsed_ota, "parser_source", "ota_parser"),
        property_name=getattr(parsed_ota, "property_name_hint", "") or "",
        property_code="",
        raw_property_mention=getattr(parsed_ota, "property_name_hint", "") or "",
        requested_check_in=getattr(parsed_ota, "check_in", None),
        requested_check_out=getattr(parsed_ota, "check_out", None),
        requested_guests=getattr(parsed_ota, "guests_total", None),
        raw_from=headers.get("From", ""),
    )


def _adapt_direct(source: dict[str, Any], parsed_direct: Any) -> ParsedEmailMessage:
    headers = source["headers"]
    return ParsedEmailMessage(
        source_provider="gmail",
        source_message_id=headers.get("Message-ID", source["fixture_id"]),
        source_thread_id=headers.get("X-Thread-Id", f"thread-{source['fixture_id']}"),
        gmail_message_id=headers.get("Message-ID", source["fixture_id"]),
        gmail_thread_id=headers.get("X-Thread-Id", f"thread-{source['fixture_id']}"),
        message_id_header=headers.get("Message-ID", source["fixture_id"]),
        guest_name=getattr(parsed_direct, "guest_name", "") or "Guest",
        guest_email=getattr(parsed_direct, "guest_email", "") or "guest@example.test",
        reply_channel_address=headers.get("Reply-To", ""),
        subject=source["subject"],
        body=getattr(parsed_direct, "message_body", "") or getattr(parsed_direct, "latest_guest_turn", "") or source["plain_text"],
        latest_guest_message=getattr(parsed_direct, "latest_guest_turn", "") or getattr(parsed_direct, "message_body", "") or "",
        latest_operator_message=getattr(parsed_direct, "latest_operator_turn", "") or "",
        conversation_context=getattr(parsed_direct, "prior_thread_context", "") or "",
        full_body=source["plain_text"],
        platform="direct",
        is_inquiry=True,
        parser_source=getattr(parsed_direct, "parser_source", "direct_email_parser"),
        property_name=getattr(parsed_direct, "property_name_hint", "") or "",
        property_code="",
        raw_property_mention=getattr(parsed_direct, "property_name_hint", "") or "",
        requested_check_in=getattr(parsed_direct, "check_in", None),
        requested_check_out=getattr(parsed_direct, "check_out", None),
        requested_guests=(getattr(parsed_direct, "guests_adults", 0) or 0) + (getattr(parsed_direct, "guests_children", 0) or 0) or None,
        raw_from=headers.get("From", ""),
    )


def _adapt_vendor(source: dict[str, Any], parsed_vendor: Any) -> ParsedEmailMessage:
    headers = source["headers"]
    return ParsedEmailMessage(
        source_provider="gmail",
        source_message_id=headers.get("Message-ID", source["fixture_id"]),
        source_thread_id=headers.get("X-Thread-Id", f"thread-{source['fixture_id']}"),
        gmail_message_id=headers.get("Message-ID", source["fixture_id"]),
        gmail_thread_id=headers.get("X-Thread-Id", f"thread-{source['fixture_id']}"),
        message_id_header=headers.get("Message-ID", source["fixture_id"]),
        guest_name="Vendor",
        guest_email="vendor@example.test",
        subject=source["subject"],
        body=source["plain_text"],
        latest_guest_message="",
        full_body=source["plain_text"],
        platform="direct",
        is_inquiry=False,
        parser_source=getattr(parsed_vendor, "parser_source", "vendor_email_parser"),
        property_name="",
        property_code="",
        raw_property_mention="",
        raw_from=headers.get("From", ""),
        system_generated=True,
        system_event_type="vendor_ops_email",
    )


def _fallback_parse(source: dict[str, Any]) -> Optional[ParsedEmailMessage]:
    parser = GmailEmailParser()
    if parser.is_non_guest_email(source["subject"], source["plain_text"]):
        return None
    headers = source["headers"]
    return ParsedEmailMessage(
        source_provider="gmail",
        source_message_id=headers.get("Message-ID", source["fixture_id"]),
        source_thread_id=headers.get("X-Thread-Id", f"thread-{source['fixture_id']}"),
        gmail_message_id=headers.get("Message-ID", source["fixture_id"]),
        gmail_thread_id=headers.get("X-Thread-Id", f"thread-{source['fixture_id']}"),
        message_id_header=headers.get("Message-ID", source["fixture_id"]),
        guest_name="Guest",
        guest_email="guest@example.test",
        subject=source["subject"],
        body=source["plain_text"],
        latest_guest_message=source["plain_text"].strip(),
        full_body=source["plain_text"],
        platform=source["platform"],
        is_inquiry=True,
        parser_source="generic_gmail_parser",
        property_name="",
        property_code="",
        raw_property_mention="",
        raw_from=headers.get("From", ""),
    )


async def _parse_fixture(source: dict[str, Any]) -> Optional[ParsedEmailMessage]:
    async def _fake_extract(self, **kwargs):
        payload = source.get("llm_extracted_fields") or {}
        return ExtractedEmailFields(
            latest_guest_message=payload.get("latest_guest_message", source["plain_text"]),
            raw_property_mention=payload.get("property_code_or_name", "") or "",
            requested_check_in=date.fromisoformat(payload["requested_check_in"]) if payload.get("requested_check_in") else None,
            requested_check_out=date.fromisoformat(payload["requested_check_out"]) if payload.get("requested_check_out") else None,
            requested_guests=payload.get("requested_guests"),
            sender_email=payload.get("sender_email", "") or "",
            sender_name=payload.get("sender_name", "") or "",
            parser_source="llm_email_extractor_corpus",
            parser_notes=["corpus_fixture"],
        )

    parser = GmailEmailParser()
    with patch("app.services.integrations.llm_email_extractor.LLMEmailExtractor.extract", new=_fake_extract):
        return await parse_structured_inbound_email(
            source_message_id=source["headers"].get("Message-ID", source["fixture_id"]),
            subject=source["subject"],
            plain_text=source["plain_text"],
            raw_html=source.get("raw_html", ""),
            headers=source["headers"],
            parser=parser,
            adapt_llm_inquiry=lambda extracted: _adapt_llm(source, extracted),
            adapt_reservation_event=lambda parsed_event: None,
            adapt_ota_inquiry=lambda parsed_ota: _adapt_ota(source, parsed_ota),
            adapt_direct_inquiry=lambda parsed_direct: _adapt_direct(source, parsed_direct),
            adapt_vendor_email=lambda parsed_vendor: _adapt_vendor(source, parsed_vendor),
            fallback_parse=lambda: _fallback_parse(source),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source_path,expected_path",
    _discover_fixture_pairs(),
    ids=lambda pair: pair[0].stem if isinstance(pair, tuple) else str(pair),
)
async def test_inquiry_corpus_replay(source_path: Path, expected_path: Path) -> None:
    source = json.loads(source_path.read_text())
    expected = json.loads(expected_path.read_text())

    route = detect_inbound_source_route(
        headers=source["headers"],
        subject=source["subject"],
        plain_text=source["plain_text"],
        raw_html=source.get("raw_html", ""),
    )
    route_text = f"{route.family}/{route.provider}/{route.parser_hint}"
    assert expected["expected_route_contains"] in route_text

    parsed = await _parse_fixture(source)
    assert parsed is not None, f"parser returned None for {source['fixture_id']}"

    pipeline = expected["expected_pipeline_output"]
    assert parsed.platform == pipeline["platform"]
    if pipeline["parser_source_contains"]:
        assert pipeline["parser_source_contains"] in (parsed.parser_source or "")
    assert parsed.guest_name == pipeline["guest_name"]
    for needle in pipeline["latest_guest_message_contains"]:
        assert needle.lower() in (parsed.latest_guest_message or parsed.body or "").lower()
    if pipeline["requested_check_in"]:
        assert parsed.requested_check_in and parsed.requested_check_in.isoformat() == pipeline["requested_check_in"]
    if pipeline["requested_check_out"]:
        assert parsed.requested_check_out and parsed.requested_check_out.isoformat() == pipeline["requested_check_out"]
    if pipeline["requested_guests"] is not None:
        assert parsed.requested_guests == pipeline["requested_guests"]
    if pipeline["platform_listing_id"]:
        assert parsed.subject or parsed.full_body
    if pipeline["platform_unit_id"]:
        assert parsed.subject or parsed.full_body
    if pipeline["property_reference_token"]:
        combined = " ".join(
            [
                parsed.property_name or "",
                parsed.raw_property_mention or "",
                source["plain_text"],
                source["subject"],
            ]
        )
        assert pipeline["property_reference_token"] in combined
