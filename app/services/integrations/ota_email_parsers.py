"""
OTA (Online Travel Agency) inquiry email parsers.

This module adds a platform-aware HTML parser for OTA inquiry emails so we can
extract the guest-authored message and stronger property identifiers before
falling back to the generic Gmail parser.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup, Tag
from app.services.integrations.message_ask_taxonomy import detect_message_asks
from app.services.integrations.message_source_detection import detect_platform

logger = logging.getLogger(__name__)


@dataclass
class ParsedOtaInquiry:
    platform: str
    parser_source: str
    lifecycle_stage: str = "pre_booking"
    sender_role: str = "guest"
    thread_event_type: str = "inquiry"
    guest_name: Optional[str] = None
    guest_email: Optional[str] = None
    reply_channel_address: Optional[str] = None
    platform_listing_id: Optional[str] = None
    platform_unit_id: Optional[str] = None
    source_interaction_id: Optional[str] = None
    source_property_id: Optional[str] = None
    source_account_id: Optional[str] = None
    provider_property_id: Optional[str] = None
    provider_account_id: Optional[str] = None
    property_name_hint: Optional[str] = None
    check_in: Optional[date] = None
    check_out: Optional[date] = None
    guests_adults: Optional[int] = None
    guests_children: Optional[int] = None
    nights: Optional[int] = None
    message_body: Optional[str] = None
    latest_guest_turn: Optional[str] = None
    latest_operator_turn: Optional[str] = None
    prior_thread_context: Optional[str] = None
    asks: list[str] = field(default_factory=list)
    raw_subject: Optional[str] = None
    extraction_notes: list[str] = field(default_factory=list)

    def is_usable(self) -> bool:
        primary_text = (
            self.latest_guest_turn
            or self.latest_operator_turn
            or self.message_body
            or ""
        ).strip()
        return len(primary_text) >= 10

    def summary_for_log(self) -> dict:
        return {
            "platform": self.platform,
            "parser_source": self.parser_source,
            "lifecycle_stage": self.lifecycle_stage,
            "listing_id": self.platform_listing_id,
            "unit_id": self.platform_unit_id,
            "guest_name": self.guest_name,
            "guest_email": self.guest_email,
            "sender_role": self.sender_role,
            "thread_event_type": self.thread_event_type,
            "interaction_id": self.source_interaction_id,
            "message_chars": len(self.message_body) if self.message_body else 0,
            "asks": self.asks,
            "has_dates": self.check_in is not None and self.check_out is not None,
            "has_guests": self.guests_adults is not None,
            "usable": self.is_usable(),
            "notes": self.extraction_notes,
        }


def parse_ota_inquiry(
    raw_html: str,
    headers: dict,
    subject: str = "",
    plain_text: str = "",
    market_id: str = "",
) -> Optional[ParsedOtaInquiry]:
    if not raw_html and not plain_text:
        return None

    platform = detect_platform(
        headers,
        subject,
        plain_text=plain_text,
        raw_html=raw_html,
    )
    if platform is None:
        return None

    parsed: Optional[ParsedOtaInquiry] = None

    if raw_html:
        try:
            soup = BeautifulSoup(raw_html, "html.parser")
        except Exception as exc:  # noqa: BLE001
            logger.warning("ota_parser: BeautifulSoup init failed platform=%s err=%s", platform, exc)
            soup = None
        if soup is not None:
            try:
                if platform == "vrbo":
                    parsed = _parse_vrbo(soup, subject, headers)
                elif platform == "airbnb":
                    parsed = _parse_airbnb(soup, subject, headers)
            except Exception as exc:  # noqa: BLE001
                logger.exception("ota_parser: parse crashed platform=%s err=%s", platform, exc)
                parsed = None

    if (parsed is None or not parsed.is_usable()) and plain_text:
        try:
            if platform == "vrbo":
                parsed = _parse_vrbo_plain_text(plain_text, subject, headers)
            elif platform == "airbnb":
                parsed = _parse_airbnb_plain_text(plain_text, subject, headers)
        except Exception as exc:  # noqa: BLE001
            logger.exception("ota_parser: plain_text_parse crashed platform=%s err=%s", platform, exc)
            parsed = parsed if parsed and parsed.is_usable() else None
    elif parsed is not None and platform in {"vrbo", "airbnb"} and plain_text:
        try:
            plain_parsed = _parse_vrbo_plain_text(plain_text, subject, headers) if platform == "vrbo" else _parse_airbnb_plain_text(plain_text, subject, headers)
        except Exception as exc:  # noqa: BLE001
            logger.exception("ota_parser: plain_text_enrichment crashed platform=%s err=%s", platform, exc)
            plain_parsed = None
        if plain_parsed is not None:
            if platform == "vrbo":
                _merge_vrbo_plain_text_enrichment(parsed, plain_parsed)
            else:
                _merge_airbnb_plain_text_enrichment(parsed, plain_parsed)

    if parsed is None:
        logger.info("ota_parser: parse returned None platform=%s subject=%r", platform, subject[:100])
        return None

    _populate_vrbo_payload_metadata(parsed, raw_html=raw_html, plain_text=plain_text)
    parsed.raw_subject = subject
    if not parsed.is_usable():
        logger.info("ota_parser: parse_unusable falling_back_to_generic summary=%s", parsed.summary_for_log())
        return None

    parsed.asks = detect_message_asks(parsed.message_body or "", market_id=market_id)
    logger.info("ota_parser: parse_success summary=%s", parsed.summary_for_log())
    return parsed


def _parse_vrbo(soup: BeautifulSoup, subject: str, headers: dict) -> Optional[ParsedOtaInquiry]:
    parsed = ParsedOtaInquiry(platform="vrbo", parser_source="ota_parser_vrbo")
    notes = parsed.extraction_notes
    parsed.lifecycle_stage = _infer_vrbo_lifecycle_stage(subject)
    _populate_vrbo_header_metadata(parsed, headers)

    subj_listing = re.search(r"Vrbo\s*#\s*(\d+)", subject or "", re.IGNORECASE)
    if subj_listing:
        parsed.platform_listing_id = subj_listing.group(1)
        notes.append("listing_id:subject")

    subj_name = re.search(r"Inquiry from\s+([^:]+?)\s*:", subject or "", re.IGNORECASE)
    if subj_name:
        parsed.guest_name = subj_name.group(1).strip()
        notes.append("guest_name:subject")

    if not parsed.guest_name:
        heading = soup.find(string=re.compile(r"is interested in your property", re.I))
        if heading:
            match = re.search(r"Hello,\s+(.+?)\s+is interested", str(heading), re.I)
            if match:
                parsed.guest_name = match.group(1).strip()
                notes.append("guest_name:heading")

    labels = _extract_labeled_fields(
        soup,
        wanted={"Property", "Unit", "Dates", "Guests", "Traveler Name", "Traveler Phone", "Inquiry from"},
    )

    if "Property" in labels:
        prop_text = labels["Property"]
        listing_match = re.search(r"#\s*(\d+)", prop_text)
        if listing_match:
            parsed.platform_listing_id = listing_match.group(1)
            notes.append("listing_id:body")
        ext_match = re.search(r"External ID\s+([\w-]+)", prop_text, re.I)
        if ext_match:
            external_value = ext_match.group(1)
            parsed.property_name_hint = f"ExternalID:{external_value}"
            account_match = re.match(r"(\d+)-(\d+)$", external_value)
            if account_match:
                parsed.source_account_id = account_match.group(1)
                parsed.source_property_id = parsed.source_property_id or account_match.group(2)
                parsed.provider_account_id = parsed.provider_account_id or account_match.group(1)
                parsed.provider_property_id = parsed.provider_property_id or account_match.group(2)
                notes.append("account_id:body")

    if "Unit" in labels:
        unit_text = labels["Unit"].strip()
        unit_match = re.search(r"(unit_[\w-]+)", unit_text, re.I)
        if unit_match:
            parsed.platform_unit_id = unit_match.group(1)
            notes.append("unit_id:body")
        elif unit_text:
            parsed.platform_unit_id = unit_text
            notes.append("unit_id:body_raw")

    if "Dates" in labels:
        check_in, check_out, nights = _parse_vrbo_dates(labels["Dates"])
        if check_in:
            parsed.check_in = check_in
            notes.append("check_in:body")
        if check_out:
            parsed.check_out = check_out
            notes.append("check_out:body")
        if nights:
            parsed.nights = nights

    if "Guests" in labels:
        adults, children = _parse_guest_counts(labels["Guests"])
        parsed.guests_adults = adults
        parsed.guests_children = children
        if adults is not None:
            notes.append("guests:body")

    if not parsed.guest_name and "Traveler Name" in labels:
        name = labels["Traveler Name"].strip()
        if name:
            parsed.guest_name = name
            notes.append("guest_name:traveler_row")

    parsed.message_body = _extract_vrbo_message_body(soup, parsed.guest_name)
    if parsed.message_body:
        parsed.latest_guest_turn = parsed.message_body
        notes.append("message_body:extracted")
    else:
        notes.append("message_body:MISSING")

    return parsed


def _parse_vrbo_plain_text(text: str, subject: str, headers: dict) -> Optional[ParsedOtaInquiry]:
    parsed = ParsedOtaInquiry(platform="vrbo", parser_source="ota_parser_vrbo_plain")
    notes = parsed.extraction_notes
    parsed.lifecycle_stage = _infer_vrbo_lifecycle_stage(subject)
    body = text or ""
    _populate_vrbo_header_metadata(parsed, headers)

    inner_from = re.search(r"\nFrom:\s*([^<\n]+?)\s*<([^>\n]+)>", body, re.I)
    if inner_from:
        parsed.guest_name = (inner_from.group(1) or "").strip()
        notes.append("guest_name:forwarded_from")
        email = (inner_from.group(2) or "").strip().lower()
        if "@messages.homeaway.com" in email or "@messages.vrbo.com" in email:
            parsed.guest_email = email
            notes.append("guest_email:forwarded_from")

    subj_listing = re.search(r"Vrbo\s*#\s*(\d+)", subject or "", re.IGNORECASE)
    if subj_listing:
        parsed.platform_listing_id = subj_listing.group(1)
        notes.append("listing_id:subject")

    subj_name = re.search(r"Inquiry from\s+([^:]+?)\s*:", subject or "", re.IGNORECASE)
    if subj_name and not parsed.guest_name:
        parsed.guest_name = subj_name.group(1).strip()
        notes.append("guest_name:subject")

    plain_labels = _extract_plain_text_labels(
        body,
        wanted={"Property", "Unit", "Dates", "Guests", "Traveler Name", "Traveler Phone", "Inquiry from"},
    )

    prop_text = plain_labels.get("Property", "")
    prop_match = re.search(r"External ID\s+([\w-]+).*?#\s*(\d+)", prop_text, re.I | re.S)
    if prop_match:
        external_value = prop_match.group(1)
        parsed.property_name_hint = f"ExternalID:{external_value}"
        parsed.platform_listing_id = parsed.platform_listing_id or prop_match.group(2)
        notes.append("listing_id:text")
        account_match = re.match(r"(\d+)-(\d+)$", external_value)
        if account_match:
            parsed.source_account_id = account_match.group(1)
            parsed.source_property_id = parsed.source_property_id or account_match.group(2)
            parsed.provider_account_id = parsed.provider_account_id or account_match.group(1)
            parsed.provider_property_id = parsed.provider_property_id or account_match.group(2)
            notes.append("account_id:text")

    unit_text = plain_labels.get("Unit", "")
    unit_match = re.search(r"(unit_[\w-]+)", unit_text, re.I)
    if unit_match:
        parsed.platform_unit_id = unit_match.group(1)
        notes.append("unit_id:text")

    dates_text = plain_labels.get("Dates", "")
    dates_match = re.search(
        r"([A-Za-z]{3,9}\s+\d{1,2}\s*-\s*[A-Za-z]{3,9}\s+\d{1,2},\s*20\d{2}).*?(\d+)\s*nights?",
        dates_text,
        re.I | re.S,
    )
    if dates_match:
        check_in, check_out, nights = _parse_vrbo_dates(f"{dates_match.group(1)}, {dates_match.group(2)} nights")
        parsed.check_in = check_in
        parsed.check_out = check_out
        parsed.nights = nights
        if check_in:
            notes.append("check_in:text")
        if check_out:
            notes.append("check_out:text")

    guests_match = re.search(r"(\d+)\s+adults?(?:,\s*(\d+)\s+(?:children|child|kids?))?", plain_labels.get("Guests", ""), re.I)
    if guests_match:
        parsed.guests_adults = int(guests_match.group(1))
        parsed.guests_children = int(guests_match.group(2) or 0)
        notes.append("guests:text")

    if not parsed.guest_name and plain_labels.get("Traveler Name"):
        traveler_name = _clean_text(plain_labels["Traveler Name"])
        if traveler_name:
            parsed.guest_name = traveler_name
            notes.append("guest_name:traveler_row")

    operator_reply = _extract_vrbo_operator_reply_body(body)
    if operator_reply:
        parsed.latest_operator_turn = operator_reply
        parsed.sender_role = "operator"
        parsed.thread_event_type = "operator_reply"
        notes.append("operator_reply:text")

    if not parsed.guest_name:
        guest_reply_name = _extract_vrbo_reply_notification_name(body)
        if guest_reply_name:
            parsed.guest_name = guest_reply_name
            notes.append("guest_name:reply_notification")

    parsed.message_body = _extract_vrbo_plain_text_message_body(body, parsed.guest_name)
    if parsed.message_body:
        parsed.latest_guest_turn = parsed.message_body
        notes.append("message_body:text")
        if _is_vrbo_guest_reply_notification(body):
            parsed.thread_event_type = "guest_reply"
            notes.append("guest_reply_notification:text")
    else:
        notes.append("message_body:MISSING")

    parsed.prior_thread_context = _extract_vrbo_prior_thread_context(body)
    _upgrade_lifecycle_from_guest_turn(parsed)

    return parsed


_VRBO_MESSAGE_HEADING = re.compile(r"(Message from|Further info)\s+", re.I)
_MESSAGE_END_MARKERS = (
    re.compile(r"Respond to this Inquiry", re.I),
    re.compile(r"Respond to (this )?message", re.I),
    re.compile(r"View .*(inquiry|booking|message)", re.I),
    re.compile(r"^Unsubscribe", re.I),
    re.compile(r"Traveler Phone", re.I),
    re.compile(r"GREAT NEWS", re.I),
    re.compile(r"This (booking|message) is protected", re.I),
    re.compile(r"Privacy Policy", re.I),
)
_STRUCTURAL_LABELS = {
    "Property",
    "Unit",
    "Dates",
    "Guests",
    "Traveler Name",
    "Traveler Phone",
    "Inquiry from",
    "Vrbo",
}


def _extract_vrbo_message_body(soup: BeautifulSoup, guest_name: Optional[str]) -> Optional[str]:
    # Modern Vrbo reply notifications place the guest text directly in a
    # semantic message container instead of using a "Message from" heading.
    message_body_div = soup.find(id="messageBody")
    if isinstance(message_body_div, Tag):
        finalized = _finalize_message_body(
            message_body_div.get_text(" ", strip=True),
            guest_name,
        )
        if finalized:
            return finalized

    heading_node = soup.find(string=_VRBO_MESSAGE_HEADING)
    if heading_node is None:
        for tag in soup.find_all(["h1", "h2", "h3", "h4", "strong", "b", "p", "div"]):
            if re.match(r"^\s*Message from", tag.get_text(" ", strip=True), re.I):
                heading_node = tag
                break

    if heading_node is None:
        return None

    start_el = heading_node if isinstance(heading_node, Tag) else heading_node.parent
    if start_el is None:
        return None

    parts: list[str] = []
    for text_node in start_el.find_all_next(string=True):
        text = _clean_text(str(text_node))
        if not text:
            continue
        if any(p.search(text) for p in _MESSAGE_END_MARKERS):
            break
        if _VRBO_MESSAGE_HEADING.search(text) and not parts:
            continue
        if text in _STRUCTURAL_LABELS:
            continue
        parts.append(text)

    if not parts:
        return None

    return _finalize_message_body(" ".join(parts).strip(), guest_name)


def _extract_vrbo_plain_text_message_body(text: str, guest_name: Optional[str]) -> Optional[str]:
    patterns = [
        re.compile(
            r"Message from\s+.*?\n(?P<body>.*?)(?:\n\s*Respond to this Inquiry|\n\s*On .+? wrote:|\n\s*>\s*Respond to this Inquiry|$)",
            re.I | re.S,
        ),
        re.compile(
            r"Further info\s*\n(?P<body>.*?)(?:\n\s*Respond to this Inquiry|\n\s*On .+? wrote:|\n\s*>\s*Respond to this Inquiry|$)",
            re.I | re.S,
        ),
        re.compile(
            r"Vrbo:\s+.+?\s+has replied to your message\s*\n(?P<body>.*?)(?:\n\s*-------We're here to help|\n\s*©\s*20\d{2}\s+Vrbo|$)",
            re.I | re.S,
        ),
    ]
    for idx, pattern in enumerate(patterns):
        match = pattern.search(text)
        if not match:
            continue
        raw = match.group("body")
        cleaned_lines = []
        for line in raw.splitlines():
            line = re.sub(r"^\s*>\s?", "", line).strip()
            if not line:
                continue
            if re.match(r"^(Property|Unit|Dates|Guests|Traveler Name|Traveler Phone|Inquiry from)\b", line, re.I):
                continue
            cleaned_lines.append(line)
        candidate = " ".join(cleaned_lines).strip()
        finalized = _finalize_message_body(candidate, guest_name)
        if finalized:
            logger.debug("vrbo_plain_text: matched pattern_%d", idx)
            return finalized

    fallback = _extract_vrbo_plain_text_by_footer(text, guest_name)
    if fallback:
        logger.debug("vrbo_plain_text: matched footer_fallback")
        return fallback

    logger.info("vrbo_plain_text: no pattern matched preview=%r", (text or "")[:200])
    return None


def _extract_vrbo_plain_text_by_footer(text: str, guest_name: Optional[str]) -> Optional[str]:
    footer_match = re.search(
        r"\n\s*-------We're here to help|\n\s*[©�]\s*20\d{2}\s+Vrbo",
        text or "",
        re.I,
    )
    if not footer_match:
        return None

    candidate = (text or "")[:footer_match.start()].strip()
    if not candidate:
        return None

    cleaned_lines: list[str] = []
    for line in candidate.splitlines():
        line = re.sub(r"^\s*>\s?", "", line).strip()
        if not line:
            continue
        if re.match(
            r"^(Property|Unit|Dates|Guests|Traveler Name|Traveler Phone|Inquiry from|Vrbo:)\b",
            line,
            re.I,
        ):
            continue
        cleaned_lines.append(line)

    if not cleaned_lines:
        return None

    return _finalize_message_body(" ".join(cleaned_lines).strip(), guest_name)


def _extract_vrbo_operator_reply_body(text: str) -> Optional[str]:
    match = re.search(r"^(?P<body>.*?)(?:\n>\s*On .+? wrote:|\nOn .+? wrote:)", text or "", re.I | re.S)
    if not match:
        return None
    candidate_lines: list[str] = []
    for line in match.group("body").splitlines():
        cleaned = _clean_text(line)
        if not cleaned or cleaned.startswith("SUBJECT:"):
            continue
        candidate_lines.append(cleaned)
    candidate = " ".join(candidate_lines).strip()
    if len(candidate) < 10:
        return None
    return candidate


def _extract_vrbo_reply_notification_name(text: str) -> Optional[str]:
    match = re.search(r"Vrbo:\s+(.+?)\s+has replied to your message", text or "", re.I)
    if match:
        return match.group(1).strip()
    return None


def _is_vrbo_guest_reply_notification(text: str) -> bool:
    return bool(re.search(r"Vrbo:\s+.+?\s+has replied to your message", text or "", re.I))


def _extract_vrbo_prior_thread_context(text: str) -> Optional[str]:
    match = re.search(r"(\n>\s*On .+? wrote:.*)$", text or "", re.I | re.S)
    if not match:
        return None
    lines = []
    for line in match.group(1).splitlines():
        cleaned = re.sub(r"^\s*>\s?", "", line).strip()
        if cleaned:
            lines.append(cleaned)
    context = " ".join(lines).strip()
    return context or None


def _populate_vrbo_header_metadata(parsed: ParsedOtaInquiry, headers: dict) -> None:
    notes = parsed.extraction_notes
    from_header = headers.get("From") or headers.get("from") or ""
    to_header = headers.get("To") or headers.get("to") or ""
    reply_header = headers.get("Reply-To") or headers.get("reply-to") or ""

    from_email = _extract_first_email(from_header)
    to_email = _extract_first_email(to_header)
    reply_email = _extract_first_email(reply_header)
    relay_email = next(
        (email for email in (reply_email, to_email, from_email) if email and _is_vrbo_relay_address(email)),
        None,
    )

    if relay_email:
        parsed.guest_email = relay_email
        notes.append(
            "guest_email:reply_to"
            if relay_email == reply_email
            else "guest_email:to_header"
            if relay_email == to_email
            else "guest_email:from_header"
        )
    elif from_email:
        parsed.guest_email = from_email
        notes.append("guest_email:from_header")

    if reply_email and _is_vrbo_relay_address(reply_email):
        parsed.reply_channel_address = reply_email
        notes.append("reply_channel:reply_to")
    elif to_email:
        parsed.reply_channel_address = to_email
        notes.append("reply_channel:to_header")

    if from_email and _is_vrbo_relay_address(from_email):
        parsed.sender_role = "guest"
    elif to_email and _is_vrbo_relay_address(to_email):
        parsed.sender_role = "operator"


def _infer_vrbo_lifecycle_stage(subject: str) -> str:
    subject_text = (subject or "").strip().lower()
    if subject_text.startswith("reservation from"):
        return "pre_arrival"
    if subject_text.startswith("inquiry from"):
        return "pre_booking"
    return "unknown"

def _extract_first_email(value: str) -> Optional[str]:
    match = re.search(r"<([^>]+@[^>]+)>", value or "")
    if match:
        return match.group(1).strip().lower()
    match = re.search(r"([\w.+-]+@[\w.-]+)", value or "")
    if match:
        return match.group(1).strip().lower()
    return None


def _is_vrbo_relay_address(value: str) -> bool:
    email = (value or "").lower()
    return "@messages.homeaway.com" in email or "@messages.vrbo.com" in email


def _populate_vrbo_payload_metadata(
    parsed: ParsedOtaInquiry,
    *,
    raw_html: str,
    plain_text: str,
) -> None:
    text = " ".join(part for part in [raw_html or "", plain_text or ""] if part)
    if not text:
        return
    notes = parsed.extraction_notes
    if not parsed.source_interaction_id:
        interaction_match = re.search(r"interactionId=([a-f0-9-]+)", text, re.I)
        if interaction_match:
            parsed.source_interaction_id = interaction_match.group(1)
            notes.append("interaction_id:payload")
    if not parsed.source_property_id:
        property_match = re.search(r"propertyId=(\d+)", text, re.I)
        if property_match:
            parsed.source_property_id = property_match.group(1)
            notes.append("property_id:payload")


def _merge_vrbo_plain_text_enrichment(
    parsed: ParsedOtaInquiry,
    plain_parsed: ParsedOtaInquiry,
) -> None:
    if plain_parsed.sender_role == "operator":
        parsed.sender_role = "operator"
    if plain_parsed.thread_event_type != "inquiry":
        parsed.thread_event_type = plain_parsed.thread_event_type
    if plain_parsed.reply_channel_address and not parsed.reply_channel_address:
        parsed.reply_channel_address = plain_parsed.reply_channel_address
    if plain_parsed.source_interaction_id and not parsed.source_interaction_id:
        parsed.source_interaction_id = plain_parsed.source_interaction_id
    if plain_parsed.source_property_id and not parsed.source_property_id:
        parsed.source_property_id = plain_parsed.source_property_id
    if plain_parsed.latest_operator_turn:
        parsed.latest_operator_turn = plain_parsed.latest_operator_turn
    if plain_parsed.latest_guest_turn and not parsed.latest_guest_turn:
        parsed.latest_guest_turn = plain_parsed.latest_guest_turn
    if plain_parsed.prior_thread_context and not parsed.prior_thread_context:
        parsed.prior_thread_context = plain_parsed.prior_thread_context


def _extract_plain_text_labels(text: str, wanted: set[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    lines = [re.sub(r"^\s*>\s?", "", line.rstrip()) for line in (text or "").splitlines()]
    wanted_map = {item.lower(): item for item in wanted}
    idx = 0
    while idx < len(lines):
        label_raw = _clean_text(lines[idx]).rstrip(":").strip()
        canonical = wanted_map.get(label_raw.lower())
        if not canonical:
            idx += 1
            continue
        values: list[str] = []
        idx += 1
        while idx < len(lines):
            current = _clean_text(lines[idx])
            current_label = wanted_map.get(current.rstrip(":").strip().lower())
            if current_label:
                break
            if current:
                values.append(current)
            idx += 1
        if values and canonical not in result:
            result[canonical] = " ".join(values).strip()
    return result


def _parse_vrbo_dates(text: str) -> tuple[Optional[date], Optional[date], Optional[int]]:
    import calendar

    month_map = {
        **{m.lower(): i for i, m in enumerate(calendar.month_abbr) if m},
        **{m.lower(): i for i, m in enumerate(calendar.month_name) if m},
    }
    year_match = re.search(r"\b(20\d{2})\b", text)
    year = int(year_match.group(1)) if year_match else None
    nights_match = re.search(r"(\d+)\s*nights?", text, re.I)
    nights = int(nights_match.group(1)) if nights_match else None
    dates_found = re.compile(r"([A-Za-z]{3,9})\s+(\d{1,2})", re.I).findall(text)
    if len(dates_found) < 2 or year is None:
        return None, None, nights

    try:
        m1, d1 = dates_found[0]
        m2, d2 = dates_found[1]
        mn1 = month_map.get(m1.lower())
        mn2 = month_map.get(m2.lower())
        if not mn1 or not mn2:
            return None, None, nights
        check_in = date(year, mn1, int(d1))
        check_out_year = year if mn2 >= mn1 else year + 1
        check_out = date(check_out_year, mn2, int(d2))
        return check_in, check_out, nights
    except (TypeError, ValueError):
        return None, None, nights


def _parse_guest_counts(text: str) -> tuple[Optional[int], Optional[int]]:
    adults_match = re.search(r"(\d+)\s*adults?", text, re.I)
    children_match = re.search(r"(\d+)\s*(?:children|child|kids?)", text, re.I)
    return (
        int(adults_match.group(1)) if adults_match else None,
        int(children_match.group(1)) if children_match else None,
    )


def _parse_airbnb(soup: BeautifulSoup, subject: str, headers: dict) -> Optional[ParsedOtaInquiry]:
    parsed = ParsedOtaInquiry(platform="airbnb", parser_source="ota_parser_airbnb")
    notes = parsed.extraction_notes
    parsed.lifecycle_stage = _infer_airbnb_lifecycle_stage(subject)
    _populate_airbnb_header_metadata(parsed, headers)

    subj_patterns = (
        re.compile(r"^(.+?)\s+sent (?:you )?(?:a )?(?:reservation request|message|inquiry)", re.I),
        re.compile(r"^(?:New\s+)?(?:inquiry|message|reservation request) from\s+(.+?)(?:\s+for|\s*$)", re.I),
        re.compile(r"^(.+?)\s+wants to book", re.I),
    )
    for pattern in subj_patterns:
        match = pattern.search(subject or "")
        if match:
            parsed.guest_name = match.group(1).strip()
            notes.append("guest_name:subject")
            break

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        match = re.search(r"airbnb\.com/(?:rooms|h)/(\d+)", href)
        if match:
            parsed.platform_listing_id = match.group(1)
            notes.append("listing_id:href")
            break

    if not parsed.guest_name:
        for pattern in (
            re.compile(r"^(.+?)\s+sent you a message", re.I),
            re.compile(r"^New inquiry from\s+(.+?)$", re.I),
            re.compile(r"^Message from\s+(.+?)$", re.I),
        ):
            node = soup.find(string=pattern)
            if not node:
                continue
            match = pattern.search(str(node))
            if match:
                parsed.guest_name = match.group(1).strip()
                notes.append("guest_name:body")
                break

    details = _extract_labeled_fields(soup, wanted={"Check-in", "Check-out", "Guests", "Listing"})
    if "Check-in" in details:
        check_in = _parse_airbnb_single_date(details["Check-in"])
        if check_in:
            parsed.check_in = check_in
            notes.append("check_in:body")
    if "Check-out" in details:
        check_out = _parse_airbnb_single_date(details["Check-out"])
        if check_out:
            parsed.check_out = check_out
            notes.append("check_out:body")
    if "Guests" in details:
        adults, children = _parse_guest_counts(details["Guests"])
        if adults is None:
            total_match = re.search(r"(\d+)", details["Guests"])
            if total_match:
                parsed.guests_adults = int(total_match.group(1))
                notes.append("guests:body_total")
        else:
            parsed.guests_adults = adults
            parsed.guests_children = children
            notes.append("guests:body")
    if "Listing" in details and not parsed.property_name_hint:
        parsed.property_name_hint = details["Listing"].strip()

    parsed.message_body = _extract_airbnb_message_body(soup, parsed.guest_name)
    if parsed.message_body:
        parsed.latest_guest_turn = parsed.message_body
        notes.append("message_body:extracted")
    else:
        notes.append("message_body:MISSING")

    return parsed


def _parse_airbnb_plain_text(text: str, subject: str, headers: dict) -> Optional[ParsedOtaInquiry]:
    parsed = ParsedOtaInquiry(platform="airbnb", parser_source="ota_parser_airbnb_plain")
    notes = parsed.extraction_notes
    parsed.lifecycle_stage = _infer_airbnb_lifecycle_stage(subject)
    body = text or ""
    _populate_airbnb_header_metadata(parsed, headers)

    listing_match = re.search(r"airbnb\.com/(?:rooms|h)/(\d+)", body, re.I)
    if listing_match:
        parsed.platform_listing_id = listing_match.group(1)
        notes.append("listing_id:text")

    thread_match = re.search(r"airbnb\.com/hosting/thread/(\d+)", body, re.I)
    if thread_match:
        parsed.source_interaction_id = thread_match.group(1)
        notes.append("thread_id:text")

    property_match = re.search(
        r"RESERVATION FOR\s+(.+?)(?:\n{2,}|Condo\s+-|House\s+-|Apartment\s+-)",
        body,
        re.I | re.S,
    )
    if property_match:
        parsed.property_name_hint = _clean_text(property_match.group(1))
        notes.append("property_name:text")
    elif subject:
        subject_property_match = re.search(r"^Inquiry for\s+(.+?)\s+for\s+[A-Za-z]{3}\s+\d{1,2}", subject, re.I)
        if subject_property_match:
            parsed.property_name_hint = _clean_text(subject_property_match.group(1)).rstrip("| ").strip()
            notes.append("property_name:subject")

    guest_name = _extract_airbnb_guest_name_from_plain_text(body)
    if guest_name:
        parsed.guest_name = guest_name
        notes.append("guest_name:text")

    check_in, check_out = _extract_airbnb_dates_from_plain_text(body)
    if check_in:
        parsed.check_in = check_in
        notes.append("check_in:text")
    if check_out:
        parsed.check_out = check_out
        notes.append("check_out:text")

    guests = re.search(r"GUESTS\s+(\d+)\s+adults?(?:,\s*(\d+)\s+children?)?", body, re.I | re.S)
    if guests:
        parsed.guests_adults = int(guests.group(1))
        parsed.guests_children = int(guests.group(2) or 0)
        notes.append("guests:text")

    operator_reply = _extract_airbnb_operator_reply_body(body)
    if operator_reply:
        parsed.sender_role = "operator"
        parsed.thread_event_type = "operator_reply"
        parsed.latest_operator_turn = operator_reply
        notes.append("operator_reply:text")

    guest_turn = _extract_airbnb_plain_text_message_body(body)
    if guest_turn:
        parsed.message_body = guest_turn
        parsed.latest_guest_turn = guest_turn
        notes.append("message_body:text")
        if parsed.sender_role != "operator" and _looks_like_airbnb_follow_up(subject, body):
            parsed.thread_event_type = "guest_reply"
    else:
        notes.append("message_body:MISSING")

    _upgrade_lifecycle_from_guest_turn(parsed)

    return parsed


def _extract_airbnb_message_body(soup: BeautifulSoup, guest_name: Optional[str]) -> Optional[str]:
    for blockquote in soup.find_all("blockquote"):
        text = _clean_text(blockquote.get_text(" ", strip=True))
        if len(text) >= 10:
            return _finalize_message_body(text, guest_name)

    heading = soup.find(string=re.compile(r"^\s*(Message|Guest message|What .+? said)", re.I))
    if heading:
        start = heading.parent if isinstance(heading, Tag) else heading.parent
        if start is not None:
            for el in start.find_all_next(["p", "div", "blockquote"]):
                text = _clean_text(el.get_text(" ", strip=True))
                if len(text) >= 20 and not re.search(r"(Respond|View|Reply|Unsubscribe|Airbnb)", text, re.I):
                    return _finalize_message_body(text, guest_name)

    italics = soup.find_all(["em", "i"])
    longest = max((_clean_text(el.get_text(" ", strip=True)) for el in italics), key=len, default="")
    if len(longest) >= 30:
        return _finalize_message_body(longest, guest_name)

    return None


def _extract_airbnb_plain_text_message_body(text: str) -> Optional[str]:
    patterns = [
        re.compile(
            r"(?:BOOKER|GUEST)\s+(.+?)\s+Reply",
            re.I | re.S,
        ),
        re.compile(
            r"(?:BOOKER|GUEST)\s+(.+?)\s+You can also respond by replying directly to this email",
            re.I | re.S,
        ),
        re.compile(
            r"RESPOND TO .+?[’']S INQUIRY\s+.+?\s+(?:Identity verified.*?\s+)?(?:.+?,\s*[A-Z]{2}\s+)?(?P<body>.+?)\s+Pre-approve\s*/\s*Decline",
            re.I | re.S,
        ),
    ]
    for pattern in patterns:
        match = pattern.search(text or "")
        if not match:
            continue
        candidate = _clean_text(match.groupdict().get("body") or match.group(1))
        if len(candidate) >= 8:
            return candidate
    return None


def _extract_airbnb_guest_name_from_plain_text(text: str) -> Optional[str]:
    block_match = re.search(
        r"(?:FOR YOUR PROTECTION AND SAFETY.*?\n)(.+?)\n\s*(.+?)\n\s*(?:Hi|Hello|Can|Do|Is|We|I)\b",
        text or "",
        re.I | re.S,
    )
    if block_match:
        first = _clean_text(block_match.group(1)).title()
        last = _clean_text(block_match.group(2)).title()
        candidate = " ".join(part for part in [first, last] if part).strip()
        if candidate and not re.search(r"(booker|guest)$", candidate, re.I):
            return candidate
    inquiry_match = re.search(r"RESPOND TO\s+([A-Z][A-Z]+)[’']S INQUIRY", text or "", re.I)
    if inquiry_match:
        return inquiry_match.group(1).strip().title()
    return None


def _extract_airbnb_dates_from_plain_text(text: str) -> tuple[Optional[date], Optional[date]]:
    matches = re.findall(r"([A-Za-z]+ \d{1,2}, 20\d{2})", text or "")
    dates = [_parse_airbnb_single_date(match) for match in matches[:2]]
    if len(dates) >= 2:
        return dates[0], dates[1]
    if len(dates) == 1:
        return dates[0], None
    compact_match = re.search(
        r"Check-in\s+Checkout\s+([A-Za-z]{3}),?\s+([A-Za-z]{3})\s+(\d{1,2})\s+([A-Za-z]{3}),?\s+([A-Za-z]{3})\s+(\d{1,2})",
        text or "",
        re.I | re.S,
    )
    if compact_match:
        current_year = date.today().year
        check_in = _parse_airbnb_single_date(f"{compact_match.group(2)} {compact_match.group(3)}, {current_year}")
        check_out = _parse_airbnb_single_date(f"{compact_match.group(5)} {compact_match.group(6)}, {current_year}")
        if check_in and check_out and check_out < check_in:
            check_out = date(check_out.year + 1, check_out.month, check_out.day)
        return check_in, check_out
    return None, None


def _extract_airbnb_operator_reply_body(text: str) -> Optional[str]:
    match = re.search(r"^(?P<body>.*?)(?:\nOn .+? wrote:|\n>\s*On .+? wrote:)", text or "", re.I | re.S)
    if not match:
        return None
    candidate = _clean_text(match.group("body"))
    if len(candidate) < 10:
        return None
    return candidate


def _looks_like_airbnb_follow_up(subject: str, text: str) -> bool:
    lowered_subject = (subject or "").lower().strip()
    lowered_text = (text or "").lower()
    return (
        lowered_subject.startswith("re:")
        or "reservation for" in lowered_subject
        or "you can also respond by replying directly to this email" in lowered_text
    )


def _parse_airbnb_single_date(text: str) -> Optional[date]:
    import calendar

    month_map = {
        **{m.lower(): i for i, m in enumerate(calendar.month_abbr) if m},
        **{m.lower(): i for i, m in enumerate(calendar.month_name) if m},
    }
    match = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(20\d{2})", text)
    if match:
        month_num = month_map.get(match.group(1).lower())
        if month_num:
            try:
                return date(int(match.group(3)), month_num, int(match.group(2)))
            except ValueError:
                pass

    match = re.search(r"(\d{1,2})/(\d{1,2})/(20\d{2})", text)
    if match:
        try:
            return date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
        except ValueError:
            pass
    return None


def _infer_airbnb_lifecycle_stage(subject: str) -> str:
    lowered = (subject or "").lower()
    if "reservation for" in lowered or "reservation request" in lowered:
        return "pre_arrival"
    if "inquiry" in lowered:
        return "pre_booking"
    return "unknown"


def _populate_airbnb_header_metadata(parsed: ParsedOtaInquiry, headers: dict) -> None:
    notes = parsed.extraction_notes
    from_header = headers.get("From") or headers.get("from") or ""
    reply_header = headers.get("Reply-To") or headers.get("reply-to") or ""

    from_email = _extract_first_email(from_header)
    reply_email = _extract_first_email(reply_header)
    if reply_email:
        parsed.reply_channel_address = reply_email
        notes.append("reply_channel:reply_to")
    if from_email:
        parsed.guest_email = reply_email or from_email
        notes.append("guest_email:header")


def _merge_airbnb_plain_text_enrichment(parsed: ParsedOtaInquiry, plain_parsed: ParsedOtaInquiry) -> None:
    if plain_parsed.platform_listing_id and not parsed.platform_listing_id:
        parsed.platform_listing_id = plain_parsed.platform_listing_id
    if plain_parsed.source_interaction_id and not parsed.source_interaction_id:
        parsed.source_interaction_id = plain_parsed.source_interaction_id
    if plain_parsed.property_name_hint and not parsed.property_name_hint:
        parsed.property_name_hint = plain_parsed.property_name_hint
    if plain_parsed.guest_name and not parsed.guest_name:
        parsed.guest_name = plain_parsed.guest_name
    if plain_parsed.reply_channel_address and not parsed.reply_channel_address:
        parsed.reply_channel_address = plain_parsed.reply_channel_address
    if plain_parsed.latest_guest_turn and not parsed.latest_guest_turn:
        parsed.latest_guest_turn = plain_parsed.latest_guest_turn
        parsed.message_body = parsed.message_body or plain_parsed.latest_guest_turn
    if plain_parsed.latest_operator_turn and not parsed.latest_operator_turn:
        parsed.latest_operator_turn = plain_parsed.latest_operator_turn
    if plain_parsed.check_in and not parsed.check_in:
        parsed.check_in = plain_parsed.check_in
    if plain_parsed.check_out and not parsed.check_out:
        parsed.check_out = plain_parsed.check_out
    if plain_parsed.guests_adults is not None and parsed.guests_adults is None:
        parsed.guests_adults = plain_parsed.guests_adults
        parsed.guests_children = plain_parsed.guests_children
    _upgrade_lifecycle_from_guest_turn(parsed)


def _upgrade_lifecycle_from_guest_turn(parsed: ParsedOtaInquiry) -> None:
    latest = (parsed.latest_guest_turn or parsed.message_body or "").lower()
    if not latest:
        return
    if parsed.lifecycle_stage == "pre_booking" and any(
        phrase in latest for phrase in ("just booked", "we booked", "i booked", "our stay", "my stay")
    ):
        parsed.lifecycle_stage = "pre_arrival"
        parsed.extraction_notes.append("lifecycle:guest_declared_booked")


def _extract_labeled_fields(soup: BeautifulSoup, wanted: set[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"], recursive=False)
        if len(cells) < 2:
            cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        label = _clean_text(cells[0].get_text(" ", strip=True)).rstrip(":").strip()
        if label in wanted and label not in result:
            value = _clean_text(cells[-1].get_text(" ", strip=True))
            if value:
                result[label] = value

    if result:
        return result

    label_regex = re.compile(r"^\s*(" + "|".join(re.escape(w) for w in wanted) + r")\s*:?\s*$", re.I)
    for node in soup.find_all(string=label_regex):
        parent = node.parent
        if not isinstance(parent, Tag):
            continue
        sibling = parent.find_next_sibling()
        if not sibling:
            continue
        label = _clean_text(str(node)).rstrip(":").strip()
        canonical = next((w for w in wanted if w.lower() == label.lower()), None)
        if not canonical:
            continue
        value = _clean_text(sibling.get_text(" ", strip=True))
        if value and canonical not in result:
            result[canonical] = value

    return result


def _clean_text(text: str) -> str:
    if not text:
        return ""
    cleaned = text.replace("\u200c", "").replace("\u200b", "").replace("\xa0", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _finalize_message_body(body: str, guest_name: Optional[str]) -> Optional[str]:
    cleaned = _clean_text(body)
    if guest_name:
        name_pattern = re.escape(guest_name).replace(r"\ ", r"\s*")
        cleaned = re.sub(rf"\s*{name_pattern}\s*$", "", cleaned, flags=re.I).strip()
    if len(cleaned) < 10:
        return None
    if len(cleaned) > 3000:
        cleaned = cleaned[:3000].rsplit(" ", 1)[0] + "…"
    return cleaned
