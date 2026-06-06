from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.services.integrations.message_source_detection import detect_platform


@dataclass(frozen=True)
class InboundSourceRoute:
    family: str
    provider: str
    parser_hint: str


def detect_inbound_source_route(
    headers: dict,
    subject: str,
    plain_text: str = "",
    raw_html: str = "",
) -> InboundSourceRoute:
    platform = detect_platform(
        headers,
        subject,
        plain_text=plain_text,
        raw_html=raw_html,
    )
    if platform == "vrbo":
        return InboundSourceRoute(family="ota", provider="vrbo", parser_hint="ota")
    if platform == "airbnb":
        return InboundSourceRoute(family="ota", provider="airbnb", parser_hint="ota")

    if _looks_like_direct_website_form(headers, subject, plain_text, raw_html):
        return InboundSourceRoute(
            family="direct_website_form",
            provider="direct",
            parser_hint="direct_website_form",
        )

    if _looks_like_vendor_ops_email(subject, plain_text):
        return InboundSourceRoute(
            family="vendor_ops_email",
            provider="direct",
            parser_hint="vendor_ops_email",
        )

    return InboundSourceRoute(family="generic_email", provider="direct", parser_hint="generic")


def _looks_like_direct_website_form(
    headers: dict,
    subject: str,
    plain_text: str,
    raw_html: str,
) -> bool:
    header_keys = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    x_mailer = header_keys.get("x-mailer", "")
    content = "\n".join(
        part for part in [subject or "", plain_text or "", raw_html or ""] if part
    )

    if "drupal webform" in x_mailer.lower():
        return True

    markers = (
        "submitted values are:",
        "listing of interest:",
        "page path:",
        "arrival date:",
        "departure date:",
        "comments/questions:",
    )
    score = sum(1 for marker in markers if marker in content.lower())
    return score >= 3


def _looks_like_vendor_ops_email(subject: str, plain_text: str) -> bool:
    text = f"{subject}\n{plain_text}".lower()
    service_markers = (
        "beach chair",
        "chair setup",
        "beach setup",
    )
    coordination_markers = (
        "booking list",
        "service list",
        "attached booking list",
        "please see attached",
        "thank you for sending these over",
        "set up for",
        "setup for",
    )
    return any(marker in text for marker in service_markers) and any(
        marker in text for marker in coordination_markers
    )
