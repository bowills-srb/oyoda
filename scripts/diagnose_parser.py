from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from dataclasses import asdict, is_dataclass
from typing import Any
from uuid import UUID

import psycopg2

from app.services.integrations.email_parser_router import (
    _has_ota_inquiry_signal,
    parse_structured_inbound_email,
)
from app.services.integrations.gmail_inbox_poller import (
    GMAIL_API_BASE,
    GmailInboxPoller,
    GmailTokenManager,
)
from app.services.integrations.inbound_source_router import detect_inbound_source_route
from app.services.integrations.message_source_detection import detect_platform
from app.services.integrations.ota_email_parsers import parse_ota_inquiry


DEFAULT_TENANT_ID = "e07980b2-a990-4b24-91d1-c8cb71ab70e1"
DEFAULT_MESSAGE_ID = "19dedf1dd40d72fa"


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _print_block(title: str, payload: Any) -> None:
    print(f"\n=== {title} ===")
    if isinstance(payload, str):
        print(payload, flush=True)
        return
    print(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, default=str), flush=True)


def _get_refresh_row(tenant_id: str) -> tuple[str, str]:
    db_url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT refresh_token, watched_email
            FROM operator_gmail_creds
            WHERE tenant_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (tenant_id,),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"No operator_gmail_creds row for tenant {tenant_id}")
        return row[0], row[1]
    finally:
        conn.close()


def _summarize_parsed(parsed: Any) -> dict[str, Any]:
    if not parsed:
        return {"parsed": False}
    summary = {
        "parsed": True,
        "type": type(parsed).__name__,
    }
    for field in (
        "platform",
        "parser_source",
        "sender_role",
        "thread_event_type",
        "lifecycle_stage",
        "guest_name",
        "guest_email",
        "reply_channel_address",
        "property_name_hint",
        "platform_listing_id",
        "platform_unit_id",
        "source_interaction_id",
        "source_property_id",
        "latest_guest_turn",
        "latest_operator_turn",
        "message_body",
        "prior_thread_context",
        "asks",
        "extraction_notes",
    ):
        if hasattr(parsed, field):
            value = getattr(parsed, field)
            if isinstance(value, str) and len(value) > 500:
                value = value[:500] + "…"
            summary[field] = value
    if hasattr(parsed, "is_usable"):
        try:
            summary["is_usable"] = parsed.is_usable()
        except Exception as exc:  # noqa: BLE001
            summary["is_usable"] = f"error:{exc}"
    return summary


async def diagnose(tenant_id: str, message_id: str) -> None:
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("app.services.integrations.ota_email_parsers").setLevel(logging.DEBUG)
    logging.getLogger("app.services.integrations.email_parser_router").setLevel(logging.DEBUG)

    refresh_token, watched_email = _get_refresh_row(tenant_id)
    token_manager = GmailTokenManager(
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        refresh_token=refresh_token,
    )
    poller = GmailInboxPoller(
        operator_id="diagnose",
        company_id=UUID(tenant_id),
        token_manager=token_manager,
        watched_email=watched_email,
        db=None,
    )

    token = await token_manager.get_access_token()
    headers = token_manager.auth_header(token)
    gmail_message = await poller._get_full_message(message_id, headers)
    if not gmail_message:
        raise RuntimeError(f"Gmail message {message_id} not found")

    raw_headers = {
        h["name"]: h["value"]
        for h in gmail_message.get("payload", {}).get("headers", [])
        if h.get("name") and h.get("value") is not None
    }
    subject = raw_headers.get("Subject", raw_headers.get("subject", ""))
    raw_body = poller._parser._decode_gmail_payload(gmail_message.get("payload", {}))
    plain_body = poller._parser.extract_plain_text_body(raw_body) if raw_body else ""
    raw_html = poller._parser.extract_html_body(gmail_message)

    _print_block(
        "INPUTS",
        {
            "watched_email": watched_email,
            "gmail_message_id": message_id,
            "subject": subject,
            "from": raw_headers.get("From", raw_headers.get("from")),
            "x_mediated_message_type": raw_headers.get("X-Mediated-Message-Type"),
            "payload_mime_type": (gmail_message.get("payload") or {}).get("mimeType"),
            "raw_body_length": len(raw_body or ""),
            "plain_body_length": len(plain_body),
            "plain_body_first_500": plain_body[:500],
            "raw_html_length": len(raw_html),
            "raw_html_truthy": bool(raw_html),
        },
    )

    platform = detect_platform(raw_headers, subject, plain_text=plain_body, raw_html=raw_html)
    source_route = detect_inbound_source_route(
        raw_headers,
        subject,
        plain_text=plain_body,
        raw_html=raw_html,
    )
    _print_block(
        "DETECTION",
        {
            "detect_platform": platform,
            "source_route": asdict(source_route),
        },
    )

    ota = parse_ota_inquiry(
        raw_html=raw_html,
        headers=raw_headers,
        subject=subject,
        plain_text=plain_body,
    )
    _print_block("PARSE_OTA_INQUIRY", _summarize_parsed(ota))

    adapted_ota = poller._adapt_ota_inquiry(gmail_message, ota) if ota else None
    _print_block(
        "ADAPT_OTA_INQUIRY",
        {
            "result_type": type(adapted_ota).__name__ if adapted_ota else None,
            "parser_source": getattr(adapted_ota, "parser_source", None) if adapted_ota else None,
            "sender_role": getattr(adapted_ota, "sender_role", None) if adapted_ota else None,
            "platform": getattr(adapted_ota, "platform", None) if adapted_ota else None,
            "body_length": len(getattr(adapted_ota, "body", "") or "") if adapted_ota else 0,
            "body_first_300": (getattr(adapted_ota, "body", "") or "")[:300] if adapted_ota else "",
            "latest_guest_first_300": (getattr(adapted_ota, "latest_guest_message", "") or "")[:300] if adapted_ota else "",
            "latest_operator_first_300": (getattr(adapted_ota, "latest_operator_message", "") or "")[:300] if adapted_ota else "",
            "is_non_guest_email_on_adapted_body": (
                poller._parser.is_non_guest_email(subject, adapted_ota.body) if adapted_ota else None
            ),
            "has_ota_inquiry_signal": _has_ota_inquiry_signal(ota, adapted_ota) if (ota and adapted_ota) else None,
        },
    )

    result = parse_structured_inbound_email(
        subject=subject,
        plain_text=plain_body,
        raw_html=raw_html,
        headers=raw_headers,
        parser=poller._parser,
        adapt_reservation_event=lambda parsed_event: poller._adapt_ota_reservation_event(gmail_message, parsed_event),
        adapt_ota_inquiry=lambda parsed_ota: poller._adapt_ota_inquiry(gmail_message, parsed_ota),
        adapt_direct_inquiry=lambda parsed_direct: poller._adapt_direct_inquiry(gmail_message, parsed_direct),
        adapt_vendor_email=lambda parsed_vendor: poller._adapt_vendor_email(gmail_message, parsed_vendor),
        fallback_parse=lambda: poller._parser.parse(gmail_message),
    )

    _print_block(
        "FINAL_RESULT",
        {
            "type": type(result).__name__ if result else None,
            "parser_source": getattr(result, "parser_source", None),
            "property_name": getattr(result, "property_name", None),
            "platform_listing_id": getattr(result, "platform_listing_id", None),
            "body_length": len(getattr(result, "body", "") or "") if result else 0,
            "latest_guest_message": (getattr(result, "latest_guest_message", "") or "")[:500] if result else "",
            "sender_role": getattr(result, "sender_role", None) if result else None,
            "is_inquiry": getattr(result, "is_inquiry", None) if result else None,
            "latest_operator_message": (getattr(result, "latest_operator_message", "") or "")[:500] if result else "",
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose parser behavior for a specific Gmail message")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--message-id", default=DEFAULT_MESSAGE_ID)
    args = parser.parse_args()
    asyncio.run(diagnose(args.tenant_id, args.message_id))


if __name__ == "__main__":
    main()
