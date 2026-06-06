from __future__ import annotations

import re
from dataclasses import dataclass, field
from email.utils import parseaddr
from typing import Optional


@dataclass
class ParsedVendorEmail:
    parser_source: str = "vendor_ops_email_parser"
    system_event_type: str = "vendor_ops_email"
    sender_role: str = "vendor"
    vendor_name: Optional[str] = None
    vendor_email: Optional[str] = None
    property_name_hint: Optional[str] = None
    service_type: Optional[str] = None
    service_period_hint: Optional[str] = None
    latest_vendor_turn: Optional[str] = None
    latest_operator_turn: Optional[str] = None
    extraction_notes: list[str] = field(default_factory=list)

    def is_usable(self) -> bool:
        return bool(
            self.vendor_email
            or self.property_name_hint
            or self.service_type
            or self.latest_vendor_turn
            or self.latest_operator_turn
        )


def parse_vendor_coordination_email(headers: dict, subject: str = "", plain_text: str = "") -> Optional[ParsedVendorEmail]:
    if not _looks_like_vendor_coordination(subject, plain_text):
        return None

    parsed = ParsedVendorEmail()
    from_name, from_email = parseaddr(headers.get("From") or headers.get("from") or "")
    to_name, to_email = parseaddr(headers.get("To") or headers.get("to") or "")

    parsed.vendor_name = from_name or ""
    parsed.vendor_email = from_email.lower() if from_email else ""
    parsed.service_type = _infer_service_type(subject, plain_text)
    parsed.service_period_hint = _infer_service_period(subject, plain_text)
    parsed.property_name_hint = _infer_property_name(subject, plain_text)

    operator_reply = _extract_operator_reply_body(plain_text)
    vendor_reply = _extract_vendor_reply_body(plain_text)

    if operator_reply and (to_email or "").strip():
        parsed.sender_role = "operator"
        parsed.latest_operator_turn = operator_reply
        parsed.vendor_email = (to_email or parsed.vendor_email or "").lower()
        parsed.extraction_notes.append("operator_reply:text")
    elif vendor_reply:
        parsed.sender_role = "vendor"
        parsed.latest_vendor_turn = vendor_reply
        parsed.extraction_notes.append("vendor_reply:text")

    if parsed.service_type:
        parsed.extraction_notes.append(f"service:{parsed.service_type}")
    if parsed.property_name_hint:
        parsed.extraction_notes.append("property:subject")
    return parsed if parsed.is_usable() else None


def _looks_like_vendor_coordination(subject: str, body: str) -> bool:
    text = f"{subject}\n{body}".lower()
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


def _infer_service_type(subject: str, body: str) -> str:
    text = f"{subject}\n{body}".lower()
    if "beach chair" in text or "chair setup" in text:
        return "beach_chair_setup"
    return "vendor_coordination"


def _infer_service_period(subject: str, body: str) -> str:
    match = re.search(r"\b(?:for|of)\s+([A-Z][a-z]+\s+20\d{2})\b", f"{subject}\n{body}")
    return match.group(1).strip() if match else ""


def _infer_property_name(subject: str, body: str) -> str:
    clean_subject = re.sub(r"^\s*Re:\s*", "", subject or "", flags=re.I).strip()
    match = re.search(r"-\s*(.+?)\s*$", clean_subject)
    if match:
        return match.group(1).strip()
    body_match = re.search(r"\bfor\s+(.+?)\.\s*$", body or "", re.I | re.M)
    return body_match.group(1).strip() if body_match else ""


def _extract_operator_reply_body(body: str) -> Optional[str]:
    match = re.search(r"^(?P<body>.*?)(?:\nOn .+? wrote:|$)", body or "", re.I | re.S)
    if not match:
        return None
    text = re.sub(r"\s+", " ", match.group("body")).strip()
    if len(text) < 10:
        return None
    if text.lower().startswith("thank you for sending"):
        return None
    return text


def _extract_vendor_reply_body(body: str) -> Optional[str]:
    match = re.search(r"^(?P<body>.*?)(?:\nOn .+? wrote:|$)", body or "", re.I | re.S)
    if not match:
        return None
    text = re.sub(r"\s+", " ", match.group("body")).strip()
    if len(text) < 10:
        return None
    return text
