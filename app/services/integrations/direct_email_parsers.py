from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from email.utils import parseaddr
from typing import Optional

from app.services.integrations.message_ask_taxonomy import detect_message_asks


@dataclass
class ParsedDirectInquiry:
    platform: str = "direct"
    parser_source: str = "direct_website_form_parser"
    lifecycle_stage: str = "pre_booking"
    sender_role: str = "guest"
    thread_event_type: str = "inquiry"
    guest_name: Optional[str] = None
    guest_email: Optional[str] = None
    reply_channel_address: Optional[str] = None
    property_name_hint: Optional[str] = None
    check_in: Optional[date] = None
    check_out: Optional[date] = None
    guests_adults: Optional[int] = None
    guests_children: Optional[int] = None
    message_body: Optional[str] = None
    latest_guest_turn: Optional[str] = None
    latest_operator_turn: Optional[str] = None
    prior_thread_context: Optional[str] = None
    asks: list[str] = field(default_factory=list)
    raw_subject: Optional[str] = None
    page_path: Optional[str] = None
    extraction_notes: list[str] = field(default_factory=list)

    def is_usable(self) -> bool:
        primary = (
            self.latest_guest_turn
            or self.latest_operator_turn
            or self.message_body
            or ""
        ).strip()
        return len(primary) >= 10


def parse_direct_inquiry(
    headers: dict,
    subject: str = "",
    plain_text: str = "",
    market_id: str = "",
    strict_form_only: bool = False,
) -> Optional[ParsedDirectInquiry]:
    body = plain_text or ""
    looks_like_form = _looks_like_direct_website_form(body, headers)
    looks_like_thread = _looks_like_direct_website_thread(body, subject)
    if strict_form_only:
        if not looks_like_form:
            return None
    elif not (looks_like_form or looks_like_thread):
        return None

    parsed = ParsedDirectInquiry()
    parsed.raw_subject = subject
    parsed.property_name_hint = _extract_property_name(subject, body)
    parsed.page_path = _extract_single_line_value(body, "Page Path")
    parsed.check_in = _parse_date(_extract_single_line_value(body, "Arrival Date"))
    parsed.check_out = _parse_date(_extract_single_line_value(body, "Departure Date"))
    parsed.guests_adults = _parse_int(_extract_single_line_value(body, "Adults"))
    parsed.guests_children = _parse_int(_extract_single_line_value(body, "Children"))

    from_header = headers.get("From") or headers.get("from") or ""
    reply_to_header = headers.get("Reply-To") or headers.get("reply-to") or ""
    to_header = headers.get("To") or headers.get("to") or ""
    from_name, from_email = parseaddr(from_header)
    reply_name, reply_email = parseaddr(reply_to_header)
    to_name, to_email = parseaddr(to_header)

    guest_name = _extract_guest_name(body)

    operator_sender = _looks_like_operator_sender(from_email, from_header)
    operator_turn = _extract_operator_reply_body(body) if operator_sender else None
    if operator_turn:
        parsed.guest_email = (reply_email or to_email or _extract_single_line_value(body, "Email") or "").strip().lower()
        parsed.guest_name = (guest_name or reply_name or to_name or parsed.guest_email or "Guest").strip()
    else:
        parsed.guest_email = (reply_email or _extract_single_line_value(body, "Email") or from_email or "").strip().lower()
        parsed.guest_name = (guest_name or reply_name or from_name or parsed.guest_email or "Guest").strip()
    parsed.reply_channel_address = parsed.guest_email

    guest_turn = _extract_field_value(body, "Comments/Questions", multiline=True)
    if not guest_turn:
        guest_turn = _extract_field_value(body, "Comments", multiline=True)
    if not guest_turn:
        guest_turn = _extract_field_value(body, "Message/Comments", multiline=True)
    if not guest_turn and _looks_like_direct_guest_reply(subject, body):
        guest_turn = _extract_direct_guest_reply_body(body)

    if operator_turn:
        parsed.sender_role = "operator"
        parsed.thread_event_type = "operator_reply"
        parsed.latest_operator_turn = operator_turn
        parsed.latest_guest_turn = (guest_turn or "").strip()
        parsed.message_body = parsed.latest_guest_turn or parsed.latest_operator_turn
        parsed.prior_thread_context = _extract_prior_context(body)
        parsed.extraction_notes.append("operator_reply:text")
    else:
        parsed.sender_role = "guest"
        parsed.thread_event_type = "guest_reply" if _looks_like_direct_guest_reply(subject, body) else "inquiry"
        parsed.latest_guest_turn = (guest_turn or "").strip()
        parsed.message_body = parsed.latest_guest_turn
        parsed.extraction_notes.append(
            "guest_reply:text" if parsed.thread_event_type == "guest_reply" else "guest_inquiry:text"
        )

    parsed.asks = detect_message_asks(parsed.message_body or "", market_id=market_id)
    if parsed.property_name_hint:
        parsed.extraction_notes.append("property:subject_or_form")
    if parsed.guest_email:
        parsed.extraction_notes.append("reply_channel:reply_to")

    return parsed if parsed.is_usable() else None


def _looks_like_direct_website_form(body: str, headers: dict) -> bool:
    x_mailer = (headers.get("X-Mailer") or headers.get("x-mailer") or "").lower()
    if "drupal webform" in x_mailer:
        return True
    lowered = (body or "").lower()
    markers = (
        "submitted values are:",
        "listing of interest:",
        "comments/questions:",
        "message/comments:",
        "arrival date:",
        "departure date:",
    )
    return sum(1 for marker in markers if marker in lowered) >= 3


def _looks_like_direct_website_thread(body: str, subject: str = "") -> bool:
    lowered = (body or "").lower()
    subj = (subject or "").strip()
    if not re.match(r"^\s*re:\s*", subj, re.I):
        return False
    markers = (
        "submitted values are:",
        "listing of interest:",
        "comments/questions:",
        "message/comments:",
        "submitted on ",
        "page path:",
    )
    return sum(1 for marker in markers if marker in lowered) >= 2


def _extract_property_name(subject: str, body: str) -> str:
    listing_label = (_extract_single_line_value(body, "Listing of Interest") or "").strip()
    if listing_label:
        return listing_label

    clean_subject = (subject or "").strip()
    clean_subject = re.sub(r"^\s*Re:\s*", "", clean_subject, flags=re.I)
    if clean_subject:
        match = re.match(r"(.+?)\s*\(", clean_subject)
        if match:
            return match.group(1).strip()
        if len(clean_subject) <= 120 and not _looks_like_bare_name_subject(clean_subject):
            return clean_subject
    return ""


def _extract_guest_name(body: str) -> str:
    first = (_extract_single_line_value(body, "First Name") or _extract_single_line_value(body, "FIrst Name") or "").strip()
    last = (_extract_single_line_value(body, "Last Name") or "").strip()
    combined = " ".join(part for part in [first, last] if part).strip()
    return combined


def _extract_single_line_value(body: str, label: str) -> str:
    return _extract_field_value(body, label, multiline=False)


def _extract_field_value(body: str, label: str, multiline: bool = False) -> str:
    value_pattern = r"(.*?)[ \t]*$" if multiline else r"(.+?)[ \t]*$"
    pattern = re.compile(rf"(?im)^[ \t]*>?[ \t]*{re.escape(label)}:[ \t]*{value_pattern}")
    text = body or ""
    match = pattern.search(text)
    if not match:
        return ""
    value = match.group(1).strip()
    if not multiline:
        return value

    remainder = text[match.end() :]
    trailing_lines: list[str] = []
    for raw_line in remainder.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if trailing_lines:
                break
            continue
        if re.match(r"^[ \t]*>?[ \t]*[A-Za-z][A-Za-z0-9 /()_-]{1,40}:[ \t]*", line):
            break
        trailing_lines.append(stripped.lstrip("> ").strip())
    if trailing_lines:
        value = " ".join([value, *trailing_lines]).strip()
    return value


def _extract_operator_reply_body(body: str) -> Optional[str]:
    match = re.search(r"^(?P<body>.*?)(?:\nOn .+? wrote:|\n>\s*Submitted on)", body or "", re.I | re.S)
    if not match:
        return None
    candidate = re.sub(r"\s+", " ", match.group("body")).strip()
    if len(candidate) < 10 or "submitted values are:" in candidate.lower():
        return None
    return candidate


def _extract_direct_guest_reply_body(body: str) -> Optional[str]:
    match = re.search(r"^(?P<body>.*?)(?:\nOn .+? wrote:|\n>\s*Submitted on)", body or "", re.I | re.S)
    if not match:
        return None
    candidate = re.sub(r"\s+", " ", match.group("body")).strip()
    if len(candidate) < 10:
        return None
    return candidate


def _extract_prior_context(body: str) -> Optional[str]:
    match = re.search(r"(\nOn .+? wrote:.*)$", body or "", re.I | re.S)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _looks_like_direct_guest_reply(subject: str, body: str) -> bool:
    subj = (subject or "").strip()
    text = body or ""
    if not re.match(r"^\s*Re:\s*", subj, re.I):
        return False
    return bool(
        re.search(r"\nOn .+? wrote:", text, re.I | re.S)
        or re.search(r"\n>\s*Submitted on", text, re.I)
        or re.search(r"\n>\s*On .+? wrote:", text, re.I)
    )


def _looks_like_operator_sender(from_email: str, from_header: str = "") -> bool:
    email = (from_email or "").strip().lower()
    header = (from_header or "").lower()
    return (
        email.endswith("@beachhabitats30a.com")
        or "info@beachhabitats30a.com" in header
        or (
            "beachhabitats30a.com" in header
            and "via beach habitats 30a" not in header
        )
    )


def _looks_like_bare_name_subject(value: str) -> bool:
    clean = re.sub(r"[^A-Za-z\s'-]", " ", value or "").strip()
    if not clean:
        return False
    parts = [part for part in clean.split() if part]
    if len(parts) > 3:
        return False
    return all(re.fullmatch(r"[A-Z][a-z'-]*", part) for part in parts)


def _parse_date(value: str) -> Optional[date]:
    text = (value or "").strip()
    if not text:
        return None
    text = re.sub(r"^[A-Za-z]{3},\s*", "", text)
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_int(value: str) -> Optional[int]:
    match = re.search(r"\d+", value or "")
    return int(match.group(0)) if match else None
