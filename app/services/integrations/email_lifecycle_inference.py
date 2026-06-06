from __future__ import annotations

import re
from typing import Iterable

_PRE_ARRIVAL_ASKS = {
    "check_in_process",
    "reservation_ops",
    "agreement_completion",
    "agreement_dispute",
    "payment_status",
    "receipt_request",
}

_IN_STAY_ASKS = {
    "wifi_issue",
    "pest_issue",
    "service_issue",
    "service_recovery",
}

_PRE_ARRIVAL_PATTERNS = (
    re.compile(r"\bi(?:'|’)?m booked\b", re.I),
    re.compile(r"\bi am booked\b", re.I),
    re.compile(r"\bwe(?:'|’)?re booked\b", re.I),
    re.compile(r"\bwe are booked\b", re.I),
    re.compile(r"\bour reservation\b", re.I),
    re.compile(r"\bmy reservation\b", re.I),
    re.compile(r"\bsign (?:a|the) contract\b", re.I),
    re.compile(r"\brental agreement\b", re.I),
    re.compile(r"\bgate code\b", re.I),
    re.compile(r"\bdoor code\b", re.I),
    re.compile(r"\bcheck(?:ing)?[- ]?in\b", re.I),
)

_IN_STAY_PATTERNS = (
    re.compile(r"\bduring our stay\b", re.I),
    re.compile(r"\bpeople who stay at this house\b", re.I),
    re.compile(r"\bwe can(?:not|'t) find\b", re.I),
    re.compile(r"\bnot working\b", re.I),
    re.compile(r"\bbroken\b", re.I),
    re.compile(r"\bgolf cart\b.*\bcharge\b", re.I),
    re.compile(r"\bcharge\b.*\bgolf cart\b", re.I),
    re.compile(r"\boutside wall outlets?\b", re.I),
)


def infer_lifecycle_stage_from_message(
    *,
    current_stage: str = "pre_booking",
    subject: str = "",
    message: str = "",
    asks: Iterable[str] | None = None,
) -> str:
    """Best-effort lifecycle upgrade for direct or generic inbox traffic.

    We only upgrade away from ``pre_booking`` when the message itself strongly
    signals that the guest already has a booking or is actively on stay.
    """
    stage = (current_stage or "pre_booking").strip().lower() or "pre_booking"
    if stage != "pre_booking":
        return stage

    ask_set = {str(item or "").strip().lower() for item in (asks or []) if str(item or "").strip()}
    blob = f"{subject}\n{message}".strip()
    if not blob:
        return stage

    if ask_set & _IN_STAY_ASKS or any(pattern.search(blob) for pattern in _IN_STAY_PATTERNS):
        return "in_stay"

    if ask_set & _PRE_ARRIVAL_ASKS or any(pattern.search(blob) for pattern in _PRE_ARRIVAL_PATTERNS):
        return "pre_arrival"

    return stage
