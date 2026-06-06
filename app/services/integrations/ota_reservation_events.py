from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from app.services.integrations.message_source_detection import detect_platform


@dataclass
class ParsedOtaReservationEvent:
    platform: str
    parser_source: str
    system_event_type: str
    lifecycle_stage: str = "pre_arrival"
    guest_name: Optional[str] = None
    guest_email: Optional[str] = None
    reply_channel_address: Optional[str] = None
    reservation_id: Optional[str] = None
    source_interaction_id: Optional[str] = None
    platform_listing_id: Optional[str] = None
    property_name_hint: Optional[str] = None
    check_in: Optional[date] = None
    check_out: Optional[date] = None
    guests_adults: Optional[int] = None
    guests_children: Optional[int] = None
    review_rating: Optional[int] = None
    public_review_text: Optional[str] = None
    private_note: Optional[str] = None
    review_response_url: Optional[str] = None
    monetary_amount: Optional[float] = None
    summary_text: Optional[str] = None
    extraction_notes: list[str] = field(default_factory=list)

    def is_usable(self) -> bool:
        return bool(
            self.guest_name
            or self.platform_listing_id
            or self.reservation_id
            or self.source_interaction_id
        )


def parse_ota_reservation_event(
    headers: dict,
    subject: str = "",
    plain_text: str = "",
) -> Optional[ParsedOtaReservationEvent]:
    platform = detect_platform(headers, subject, plain_text=plain_text)
    if platform == "airbnb":
        review_event = _parse_airbnb_review_event(headers, subject, plain_text)
        if review_event is not None:
            return review_event
        money_request_event = _parse_airbnb_money_request_event(headers, subject, plain_text)
        if money_request_event is not None:
            return money_request_event
        return _parse_airbnb_reservation_event(headers, subject, plain_text)
    if platform == "vrbo":
        review_event = _parse_vrbo_review_event(headers, subject, plain_text)
        if review_event is not None:
            return review_event
        return _parse_vrbo_reservation_event(headers, subject, plain_text)
    return None


def _parse_airbnb_review_event(headers: dict, subject: str, body: str) -> Optional[ParsedOtaReservationEvent]:
    lowered_subject = (subject or "").lower()
    lowered_body = (body or "").lower()
    if "left a" not in lowered_subject or "review" not in lowered_subject:
        if "rated their stay" not in lowered_body and "private note" not in lowered_body:
            return None

    parsed = ParsedOtaReservationEvent(
        platform="airbnb",
        parser_source="ota_review_event_airbnb",
        system_event_type="review_received",
        lifecycle_stage="post_stay",
    )

    guest_match = re.search(r"^(.*?)\s+left a\s+(\d)-star review", subject or "", re.I)
    if guest_match:
        parsed.guest_name = _clean_text(guest_match.group(1))
        parsed.review_rating = int(guest_match.group(2))
        parsed.extraction_notes.extend(["guest_name:subject", "review_rating:subject"])

    if parsed.review_rating is None:
        rating_match = re.search(r"OVERALL RATING\s+(\d)", body or "", re.I)
        if rating_match:
            parsed.review_rating = int(rating_match.group(1))
            parsed.extraction_notes.append("review_rating:text")

    property_match = re.search(
        r"FEEDBACK FROM THEIR STAY\s+(.+?)\s+([A-Z][a-z]{2}\s+\d{1,2}\s*[–-]\s*\d{1,2},\s*20\d{2})",
        _clean_text(body or ""),
        re.I,
    )
    if property_match:
        parsed.property_name_hint = _clean_text(property_match.group(1))
        parsed.extraction_notes.append("property_name:feedback_block")

    check_in, check_out = _extract_stay_range(body)
    parsed.check_in = check_in
    parsed.check_out = check_out
    if check_in:
        parsed.extraction_notes.append("check_in:review_range")
    if check_out:
        parsed.extraction_notes.append("check_out:review_range")

    listing_match = re.search(r"airbnb\.com/rooms/(\d+)", body or "", re.I)
    if listing_match:
        parsed.platform_listing_id = listing_match.group(1)
        parsed.extraction_notes.append("listing_id:text")

    public_match = re.search(
        r"OVERALL RATING\s+\d+\s+(.*?)\s+PRIVATE NOTE",
        _clean_text(body or ""),
        re.I,
    )
    if public_match:
        parsed.public_review_text = _clean_text(public_match.group(1))
        parsed.extraction_notes.append("public_review:text")

    private_match = re.search(
        r"PRIVATE NOTE\s+(.*?)\s+(SPECIAL THANKS|KEEP HOSTING|Read full review|Write a response)",
        _clean_text(body or ""),
        re.I,
    )
    if private_match:
        parsed.private_note = _clean_text(private_match.group(1))
        parsed.extraction_notes.append("private_note:text")

    response_match = re.search(r"(https://www\.airbnb\.com/users/reviews\?id=\d+&respond_to=\d+[^]\s]*)", body or "", re.I)
    if response_match:
        parsed.review_response_url = response_match.group(1).strip()
        parsed.extraction_notes.append("review_response_url:text")

    parsed.summary_text = (
        f"{parsed.guest_name or 'Guest'} left a {parsed.review_rating or ''}-star review"
        f"{': ' + parsed.public_review_text if parsed.public_review_text else ''}"
    ).strip(": ")
    return parsed if parsed.is_usable() else None


def _parse_vrbo_review_event(headers: dict, subject: str, body: str) -> Optional[ParsedOtaReservationEvent]:
    lowered_subject = (subject or "").lower()
    lowered_body = (body or "").lower()
    if "review" not in lowered_subject and "review" not in lowered_body:
        return None
    if "respond to this inquiry" in lowered_body:
        return None
    if not any(
        marker in lowered_body
        for marker in ("private feedback", "overall rating", "left a review", "star review", "submitted a review", "write a response")
    ):
        return None

    parsed = ParsedOtaReservationEvent(
        platform="vrbo",
        parser_source="ota_review_event_vrbo",
        system_event_type="review_received",
        lifecycle_stage="post_stay",
    )
    rating_match = re.search(r"(\d)\s*-?\s*star review", subject or "", re.I) or re.search(r"overall rating\s+(\d)", body or "", re.I)
    if rating_match:
        parsed.review_rating = int(rating_match.group(1))
        parsed.extraction_notes.append("review_rating:text")
    else:
        alt_rating_match = re.search(r"\b([1-5])\s+out of\s+5\b", body or "", re.I)
        if alt_rating_match:
            parsed.review_rating = int(alt_rating_match.group(1))
            parsed.extraction_notes.append("review_rating:out_of_5")
    guest_match = re.search(r"review from\s+([^:]+)", subject or "", re.I)
    if guest_match:
        parsed.guest_name = _clean_text(guest_match.group(1))
        parsed.extraction_notes.append("guest_name:subject")
    else:
        alt_guest_match = re.search(r"^(.*?)\s+reviewed their stay\b", subject or "", re.I)
        if alt_guest_match:
            parsed.guest_name = _clean_text(alt_guest_match.group(1))
            parsed.extraction_notes.append("guest_name:subject_alt")

    reservation_match = re.search(r"reservation id\s*#\s*([A-Z0-9-]+)", body or "", re.I)
    if reservation_match:
        parsed.reservation_id = reservation_match.group(1).strip()
        parsed.extraction_notes.append("reservation_id:text")

    listing_match = re.search(r"property\s*#\s*(\d+)", subject or "", re.I)
    if listing_match:
        parsed.platform_listing_id = listing_match.group(1)
        parsed.extraction_notes.append("listing_id:subject")

    response_match = re.search(r"(https?://www\.vrbo\.com/td/reviews/[^\s]+)", body or "", re.I)
    if response_match:
        parsed.review_response_url = response_match.group(1).strip()
        parsed.extraction_notes.append("review_response_url:text")

    property_match = re.search(r"Write a response:\s+\S+\s+(.+?)\s+Reservation ID\s*#", _clean_text(body or ""), re.I)
    if property_match:
        parsed.property_name_hint = _clean_text(property_match.group(1))
        parsed.extraction_notes.append("property_name:text")

    arrival_match = re.search(r"Date of arrival\s*[-:]\s*([A-Za-z]+\s+\d{1,2},\s*20\d{2})", body or "", re.I)
    if arrival_match:
        parsed.check_in = _parse_flexible_date(arrival_match.group(1))
        if parsed.check_in:
            parsed.extraction_notes.append("check_in:text")

    clean_body = _clean_text(body or "")
    public_match = re.search(
        r"(?:public review|review)\s*[:\-]?\s*(.*?)\s*(?:private feedback|private note|date of arrival|need help\?|$)",
        clean_body,
        re.I,
    )
    if public_match:
        parsed.public_review_text = _clean_text(public_match.group(1))
        parsed.extraction_notes.append("public_review:text")
    elif parsed.review_rating is not None:
        alt_public_match = re.search(
            r"\b[1-5]\s+out of\s+5\s+(.*?)\s+Date of arrival",
            clean_body,
            re.I,
        )
        if alt_public_match:
            parsed.public_review_text = _clean_text(alt_public_match.group(1))
            parsed.extraction_notes.append("public_review:out_of_5_block")
    private_match = re.search(r"(?:private feedback|private note)\s*[:\-]?\s*(.*)", _clean_text(body or ""), re.I)
    if private_match:
        parsed.private_note = _clean_text(private_match.group(1))
        parsed.extraction_notes.append("private_note:text")
    parsed.summary_text = (
        f"{parsed.guest_name or 'Guest'} left a review"
        f"{': ' + parsed.public_review_text if parsed.public_review_text else ''}"
    )
    return parsed if parsed.is_usable() else None


def _parse_airbnb_reservation_event(headers: dict, subject: str, body: str) -> Optional[ParsedOtaReservationEvent]:
    lowered_subject = (subject or "").lower()
    lowered_body = (body or "").lower()
    is_reminder = "reservation reminder:" in lowered_subject or "booking_reservation_reminder_to_host" in lowered_body
    is_confirmation = (
        "reservation confirmed" in lowered_subject
        or "new booking confirmed" in lowered_body
        or "another booking confirmed" in lowered_body
        or "booking confirmed" in lowered_body
    )
    is_cancellation = (
        lowered_subject.startswith("canceled:")
        or "reservation canceled" in lowered_body
        or "had to cancel reservation" in lowered_body
    )
    if not is_reminder and not is_confirmation and not is_cancellation:
        return None

    parsed = ParsedOtaReservationEvent(
        platform="airbnb",
        parser_source="ota_reservation_event_airbnb",
        system_event_type=(
            "reservation_canceled"
            if is_cancellation
            else "reservation_confirmed" if is_confirmation and not is_reminder
            else "reservation_reminder"
        ),
    )
    reply_to = headers.get("Reply-To") or headers.get("reply-to") or ""
    if reply_to:
        parsed.reply_channel_address = reply_to.strip()
        parsed.extraction_notes.append("reply_channel:header")

    guest_match = re.search(r"([A-Z][A-Za-z]+)\s+arrives\s+[A-Za-z]+,\s+[A-Za-z]{3}\s+\d{1,2}\.", body or "", re.I)
    if guest_match:
        parsed.guest_name = guest_match.group(1).title()
        parsed.extraction_notes.append("guest_name:arrival_heading")
    elif is_confirmation:
        subject_guest = re.search(r"reservation confirmed\s*-\s*(.+?)\s+arrives\s+[A-Za-z]{3}\s+\d{1,2}", subject or "", re.I)
        if subject_guest:
            parsed.guest_name = _clean_text(subject_guest.group(1))
            parsed.extraction_notes.append("guest_name:subject")
    elif is_cancellation:
        cancel_guest = re.search(r"your guest\s+([A-Z][A-Za-z]+)\s+had to cancel reservation", body or "", re.I)
        if cancel_guest:
            parsed.guest_name = _clean_text(cancel_guest.group(1))
            parsed.extraction_notes.append("guest_name:cancellation_text")

    full_name_match = re.search(
        r"details/[A-Z0-9]+\?[^ ]*\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)+)\s+Identity verified",
        re.sub(r"\s+", " ", body or ""),
        re.I,
    )
    if full_name_match:
        parsed.guest_name = full_name_match.group(1).strip()
        parsed.extraction_notes.append("guest_name:detail_block")

    reservation_match = re.search(r"CONFIRMATION CODE\s+([A-Z0-9]+)", body or "", re.I)
    if not reservation_match and is_cancellation:
        reservation_match = re.search(r"Reservation\s+([A-Z0-9]+)\s+for", subject or "", re.I)
    if reservation_match:
        parsed.reservation_id = reservation_match.group(1).strip()
        parsed.extraction_notes.append("reservation_id:confirmation_code")

    thread_match = re.search(r"airbnb\.com/hosting/thread/(\d+)", body or "", re.I)
    if thread_match:
        parsed.source_interaction_id = thread_match.group(1)
        parsed.extraction_notes.append("thread_id:text")

    listing_match = re.search(r"airbnb\.com/rooms/(\d+)", body or "", re.I)
    if not listing_match and is_cancellation:
        listing_match = re.search(r"Listing\s*#\s*(\d+)", body or "", re.I)
    if listing_match:
        parsed.platform_listing_id = listing_match.group(1)
        parsed.extraction_notes.append("listing_id:text")

    property_match = re.search(r"airbnb\.com/rooms/\d+[^\n]*\n\n([A-Z0-9 |+&'/-]{8,})\n", body or "", re.I)
    if not property_match and is_cancellation:
        property_match = re.search(
            r"details/[A-Z0-9]+\s+(.+?)\s+Listing\s*#",
            _clean_text(body or ""),
            re.I,
        )
    if property_match:
        parsed.property_name_hint = _clean_text(property_match.group(1)).title()
        parsed.extraction_notes.append("property_name:text")

    check_in, check_out = _extract_month_day_dates(body)
    parsed.check_in = check_in
    parsed.check_out = check_out
    if check_in:
        parsed.extraction_notes.append("check_in:text")
    if check_out:
        parsed.extraction_notes.append("check_out:text")

    guests = re.search(r"GUESTS\s+(\d+)\s+adults?(?:,\s*(\d+)\s+children?)?", body or "", re.I | re.S)
    if not guests and is_cancellation:
        guests = re.search(r"Aug \d{1,2}\s*[–-]\s*\d{1,2},\s*(\d+)\s+guests", body or "", re.I)
    if guests:
        parsed.guests_adults = int(guests.group(1))
        parsed.guests_children = int(guests.group(2) or 0) if guests.lastindex and guests.lastindex > 1 else 0
        parsed.extraction_notes.append("guests:text")

    parsed.summary_text = (
        "Reservation canceled event"
        if parsed.system_event_type == "reservation_canceled"
        else "Reservation confirmed event" if parsed.system_event_type == "reservation_confirmed"
        else "Reservation reminder event"
    )
    return parsed if parsed.is_usable() else None


def _parse_airbnb_money_request_event(headers: dict, subject: str, body: str) -> Optional[ParsedOtaReservationEvent]:
    lowered_subject = (subject or "").lower()
    lowered_body = (body or "").lower()
    if "requested money from" not in lowered_subject and "you requested $" not in lowered_body:
        return None

    parsed = ParsedOtaReservationEvent(
        platform="airbnb",
        parser_source="ota_resolution_event_airbnb",
        system_event_type="money_request_created",
        lifecycle_stage="post_stay",
    )

    guest_match = re.search(r"you requested money from\s+(.+)$", subject or "", re.I)
    if guest_match:
        parsed.guest_name = _clean_text(guest_match.group(1))
        parsed.extraction_notes.append("guest_name:subject")

    amount_match = re.search(r"YOU REQUESTED\s+\$([\d,]+(?:\.\d{2})?)\s*USD", body or "", re.I)
    if amount_match:
        parsed.monetary_amount = float(amount_match.group(1).replace(",", ""))
        parsed.extraction_notes.append("amount:text")

    claim_match = re.search(r"/resolutions/([A-Z0-9-]+)", body or "", re.I)
    if claim_match:
        parsed.reservation_id = claim_match.group(1).strip()
        parsed.extraction_notes.append("claim_id:text")

    check_in, check_out = _extract_month_day_dates(body)
    parsed.check_in = check_in
    parsed.check_out = check_out
    if check_in:
        parsed.extraction_notes.append("check_in:text")
    if check_out:
        parsed.extraction_notes.append("check_out:text")

    property_match = re.search(r"\b[A-Za-z]{3}\s+\d{1,2}\s*[–-]\s*\d{1,2},\s*20\d{2}\s+(.+?)\s+This is for payment", _clean_text(body or ""), re.I)
    if property_match:
        parsed.property_name_hint = _clean_text(property_match.group(1))
        parsed.extraction_notes.append("property_name:text")

    listing_match = re.search(r"airbnb\.com/rooms/(\d+)", body or "", re.I)
    if listing_match:
        parsed.platform_listing_id = listing_match.group(1)
        parsed.extraction_notes.append("listing_id:text")

    reason_match = re.search(r"This is for\s+(.*?)(?:\.\s|Review request|$)", _clean_text(body or ""), re.I)
    if reason_match:
        parsed.summary_text = _clean_text(reason_match.group(1))
        parsed.extraction_notes.append("reason:text")

    if parsed.summary_text is None and parsed.monetary_amount is not None:
        parsed.summary_text = f"Money request created for ${parsed.monetary_amount:,.2f}"

    return parsed if parsed.is_usable() else None


def _parse_vrbo_reservation_event(headers: dict, subject: str, body: str) -> Optional[ParsedOtaReservationEvent]:
    lowered_subject = (subject or "").lower()
    lowered_body = (body or "").lower()
    if not (
        "reservation reminder" in lowered_subject
        or "arrives" in lowered_subject
        or ("confirmation code" in lowered_body and "respond to this inquiry" not in lowered_body)
    ):
        return None

    parsed = ParsedOtaReservationEvent(
        platform="vrbo",
        parser_source="ota_reservation_event_vrbo",
        system_event_type="reservation_reminder",
    )
    reply_to = headers.get("Reply-To") or headers.get("reply-to") or ""
    if reply_to:
        parsed.reply_channel_address = reply_to.strip()
        parsed.extraction_notes.append("reply_channel:header")

    subj_name = re.search(r"reservation (?:reminder:)?\s*([^:]+?)\s+(?:is coming soon|arrives|from)", subject or "", re.I)
    if subj_name:
        parsed.guest_name = subj_name.group(1).strip()
        parsed.extraction_notes.append("guest_name:subject")

    conf_match = re.search(r"(?:confirmation code|reservation id)\s*[:\s]+([A-Z0-9-]+)", body or "", re.I)
    if conf_match:
        parsed.reservation_id = conf_match.group(1).strip()
        parsed.extraction_notes.append("reservation_id:text")

    interaction_match = re.search(r"interactionId=([a-f0-9-]+)", body or "", re.I)
    if interaction_match:
        parsed.source_interaction_id = interaction_match.group(1)
        parsed.extraction_notes.append("thread_id:text")

    listing_match = re.search(r"Vrbo\s*#\s*(\d+)", subject or "", re.I)
    if listing_match:
        parsed.platform_listing_id = listing_match.group(1)
        parsed.extraction_notes.append("listing_id:subject")

    prop_match = re.search(r"Property\s+External ID\s+([\w-]+).*?#\s*(\d+)", body or "", re.I | re.S)
    if prop_match and not parsed.platform_listing_id:
        parsed.platform_listing_id = prop_match.group(2)
        parsed.extraction_notes.append("listing_id:text")

    check_in, check_out = _extract_month_day_dates(body)
    parsed.check_in = check_in
    parsed.check_out = check_out
    guests = re.search(r"(\d+)\s+adults?(?:,\s*(\d+)\s+children?)?", body or "", re.I)
    if guests:
        parsed.guests_adults = int(guests.group(1))
        parsed.guests_children = int(guests.group(2) or 0)
        parsed.extraction_notes.append("guests:text")

    parsed.summary_text = "Reservation reminder event"
    return parsed if parsed.is_usable() else None


def _extract_month_day_dates(text: str) -> tuple[Optional[date], Optional[date]]:
    matches = re.findall(r"([A-Za-z]{3,9},?\s+[A-Za-z]{3}\s+\d{1,2}|[A-Za-z]{3,9}\s+\d{1,2},\s+20\d{2})", text or "")
    parsed_dates = []
    for match in matches:
        parsed = _parse_flexible_date(match)
        if parsed:
            parsed_dates.append(parsed)
        if len(parsed_dates) >= 2:
            break
    if len(parsed_dates) >= 2:
        return parsed_dates[0], parsed_dates[1]
    if len(parsed_dates) == 1:
        return parsed_dates[0], None
    return None, None


def _extract_stay_range(text: str) -> tuple[Optional[date], Optional[date]]:
    clean = _clean_text(text)
    match = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2})\s*[–-]\s*(\d{1,2}),\s*(20\d{2})", clean)
    if match:
        month = match.group(1)
        start_day = match.group(2)
        end_day = match.group(3)
        year = match.group(4)
        start = _parse_flexible_date(f"{month} {start_day}, {year}")
        end = _parse_flexible_date(f"{month} {end_day}, {year}")
        if start and end:
            return start, end
    return _extract_month_day_dates(text)


def _parse_flexible_date(value: str) -> Optional[date]:
    text = _clean_text(value)
    current_year = datetime.now().year
    for fmt in ("%A, %b %d", "%a, %b %d", "%B %d, %Y", "%b %d, %Y"):
        try:
            parse_text = text
            effective_fmt = fmt
            if "%Y" not in fmt:
                parse_text = f"{text}, {current_year}"
                effective_fmt = f"{fmt}, %Y"
            parsed = datetime.strptime(parse_text, effective_fmt)
            return parsed.date()
        except ValueError:
            continue
    return None


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()
