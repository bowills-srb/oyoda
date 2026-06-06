from __future__ import annotations

import re
from typing import Optional


_VRBO_SENDER_PATTERNS = (
    "messages.homeaway.com",
    "messages.vrbo.com",
    "reviews.homeaway.com",
    "@vrbo.com",
    "@homeaway.com",
)

_AIRBNB_SENDER_PATTERNS = (
    "automated.airbnb.com",
    "@airbnb.com",
    "airbnb.com",
)

_VRBO_SUBJECT_PATTERNS = (
    re.compile(r"Vrbo\s*#\s*\d+", re.IGNORECASE),
    re.compile(r"Inquiry from .+? - Vrbo", re.IGNORECASE),
    re.compile(r"New (message|inquiry|booking).*Vrbo", re.IGNORECASE),
    re.compile(r"reviewed their stay .* property #\s*\d+", re.IGNORECASE),
)

_AIRBNB_SUBJECT_PATTERNS = (
    re.compile(r"Reservation request", re.IGNORECASE),
    re.compile(r"inquiry for your (listing|place)", re.IGNORECASE),
    re.compile(r"new (message|booking) from", re.IGNORECASE),
)

_VRBO_BODY_PATTERNS = (
    re.compile(r"has sent an additional inquiry", re.IGNORECASE),
    re.compile(r"respond to this inquiry", re.IGNORECASE),
    re.compile(r"inquiry from\s*:?\s*vrbo", re.IGNORECASE),
    re.compile(r"further info", re.IGNORECASE),
    re.compile(r"traveler name", re.IGNORECASE),
    re.compile(r"property\s*:?\s*external id", re.IGNORECASE),
)

_AIRBNB_BODY_PATTERNS = (
    re.compile(r"respond to .+?'s inquiry", re.IGNORECASE),
    re.compile(r"you can also respond by replying directly to this email", re.IGNORECASE),
    re.compile(r"for your protection and safety, always communicate through airbnb", re.IGNORECASE),
    re.compile(r"pre-approve / decline", re.IGNORECASE),
)


def detect_platform(
    headers: dict,
    subject: str,
    plain_text: str = "",
    raw_html: str = "",
) -> Optional[str]:
    from_header = (headers.get("From") or headers.get("from") or "").lower()
    subject_text = subject or ""
    body_text = " ".join(part for part in (plain_text, raw_html) if part)
    if any(p in from_header for p in _VRBO_SENDER_PATTERNS):
        return "vrbo"
    if any(p in from_header for p in _AIRBNB_SENDER_PATTERNS):
        return "airbnb"
    if any(p.search(subject_text) for p in _VRBO_SUBJECT_PATTERNS):
        return "vrbo"
    if any(p.search(subject_text) for p in _AIRBNB_SUBJECT_PATTERNS):
        return "airbnb"
    if any(p.search(body_text) for p in _VRBO_BODY_PATTERNS):
        return "vrbo"
    if any(p.search(body_text) for p in _AIRBNB_BODY_PATTERNS):
        return "airbnb"
    return None
