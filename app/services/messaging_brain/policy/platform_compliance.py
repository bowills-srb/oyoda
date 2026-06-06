"""Platform-level compliance rules. These override operator policies."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Pattern, Sequence

_SERVICE_ANIMAL_PATTERNS: tuple[Pattern[str], ...] = (
    re.compile(r"\bservice animals?\b", re.IGNORECASE),
    re.compile(r"\bservice dogs?\b", re.IGNORECASE),
    re.compile(r"\bguide dogs?\b", re.IGNORECASE),
    re.compile(r"\b(seeing[- ]eye|hearing) dogs?\b", re.IGNORECASE),
    re.compile(r"\bada (registered|trained|certified)\b", re.IGNORECASE),
)

_ESA_PATTERNS: tuple[Pattern[str], ...] = (
    re.compile(r"\bemotional support (animal|dog|cat|pet)s?\b", re.IGNORECASE),
    re.compile(r"\bESA\b", re.IGNORECASE),
    re.compile(r"\bcomfort (animal|dog|pet)s?\b", re.IGNORECASE),
)

SERVICE_ANIMAL_ACCOMMODATION_RESPONSE = (
    "Service animals are welcome regardless of property pet policy. "
    "We accommodate service animals in accordance with the ADA. "
    "Please share your arrival details and any specific accessibility "
    "needs so we can prepare for your stay."
)


@dataclass(frozen=True)
class PreBookingPolicyOutcome:
    """Deterministic policy bridge result for legacy pre-booking parity."""

    decision: str
    flags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    block_send: bool = False


def _verification_focus_line(intent: str, message: str) -> str:
    lowered = (message or "").lower()
    if "golf cart" in lowered:
        return "whether the property includes a golf cart"
    if "washer" in lowered or "dryer" in lowered or "laundry" in lowered:
        return "the laundry setup"
    if intent == "amenities":
        return "the exact amenity details"
    if intent == "local_area":
        return "the exact area and access details"
    if intent == "group_size":
        return "the exact occupancy details"
    if intent == "check_in_process":
        return "the arrival details"
    return "the exact details"


def evaluate_pre_booking_policy(
    *,
    message: str,
    intent: str,
    confidence: float,
    requested_nights: int | None,
    requested_guests: int | None,
    property_data: dict[str, Any],
    operator_policies: dict[str, Any],
    auto_send_threshold: float,
    flag_pricing_inquiries: bool,
    flag_pet_inquiries: bool,
    approval_mode: str,
    missing_knowledge_topics: Sequence[str],
) -> PreBookingPolicyOutcome:
    """Mirror legacy pre-booking policy checks in a brain-owned helper."""
    flags: list[str] = []
    warnings: list[str] = []
    block_send = False

    if requested_nights is not None:
        min_nights = operator_policies.get("min_nights", 3)
        if requested_nights < min_nights:
            warnings.append(
                f"⚠️ Guest requesting {requested_nights} nights, minimum is {min_nights}"
            )

    if requested_guests:
        max_guests = property_data.get("max_guests")
        if max_guests and requested_guests > max_guests:
            warnings.append(
                f"⚠️ Guest requesting {requested_guests} guests, max is {max_guests}"
            )

    if intent == "pricing" and flag_pricing_inquiries:
        flags.append("ℹ️ Pricing inquiry — review draft before sending")
        block_send = True

    if intent == "pet_policy":
        pet_ok = operator_policies.get("pet_policy") == "allowed"
        flags.append(
            f"ℹ️ Pet inquiry — policy: {'allowed with fee' if pet_ok else 'NOT allowed'}"
        )
        if flag_pet_inquiries:
            block_send = True

    if intent == "check_in_process":
        flags.append(
            "ℹ️ Arrival timing request — confirm early check-in only if property operations allow it"
        )

    if missing_knowledge_topics:
        unique_topics = ",".join(sorted(set(missing_knowledge_topics)))
        flags.append("ℹ️ Knowledge gap detected — hold for operator review before replying")
        warnings.append(f"missing_property_knowledge:{unique_topics}")
        return PreBookingPolicyOutcome(
            decision="hold",
            flags=flags,
            warnings=warnings,
            block_send=block_send,
        )

    if approval_mode == "required":
        return PreBookingPolicyOutcome(
            decision="hold",
            flags=flags,
            warnings=warnings,
            block_send=block_send,
        )

    if block_send:
        decision = "review"
    elif confidence >= auto_send_threshold and not warnings:
        decision = "send_now"
    elif confidence >= 0.5:
        decision = "review"
    else:
        decision = "hold"

    return PreBookingPolicyOutcome(
        decision=decision,
        flags=flags,
        warnings=warnings,
        block_send=block_send,
    )


def apply_pre_booking_draft_source_policy(
    *,
    outcome: PreBookingPolicyOutcome,
    draft_source: str,
    intent: str,
    message: str,
) -> PreBookingPolicyOutcome:
    """Mirror legacy draft-source hold policy in a brain-owned helper."""
    if not draft_source or draft_source == "model":
        return outcome
    if draft_source == "portfolio_matches_grounded":
        return outcome

    flags = list(outcome.flags)
    warnings = list(outcome.warnings)
    warnings.append(f"draft_source:{draft_source}")

    if draft_source == "verification_required":
        detail_line = _verification_focus_line(intent, message)
        flags.append(
            f"ℹ️ Verification follow-up required — confirm {detail_line} before sending or promising specifics"
        )
        warnings.append(f"verification_required:{intent}")
        return PreBookingPolicyOutcome(
            decision="hold",
            flags=flags,
            warnings=warnings,
            block_send=outcome.block_send,
        )

    if draft_source in {"portfolio_matches_partial", "portfolio_follow_up_required"}:
        flags.append(
            "ℹ️ Portfolio recommendation inquiry — operator should review property fit before sending"
        )
        warnings.append(f"portfolio_review_required:{intent}")
        return PreBookingPolicyOutcome(
            decision="hold",
            flags=flags,
            warnings=warnings,
            block_send=outcome.block_send,
        )

    return PreBookingPolicyOutcome(
        decision=outcome.decision,
        flags=flags,
        warnings=warnings,
        block_send=outcome.block_send,
    )


def is_service_animal_request(text: str) -> bool:
    """Return True when the message indicates a service-animal request."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _SERVICE_ANIMAL_PATTERNS)


def is_esa_request(text: str) -> bool:
    """Return True when the message references an emotional support animal."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _ESA_PATTERNS)


__all__ = [
    "SERVICE_ANIMAL_ACCOMMODATION_RESPONSE",
    "PreBookingPolicyOutcome",
    "apply_pre_booking_draft_source_policy",
    "evaluate_pre_booking_policy",
    "is_esa_request",
    "is_service_animal_request",
]
