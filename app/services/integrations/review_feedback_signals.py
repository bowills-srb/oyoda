from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ReviewFeedbackSignal:
    family: str
    theme: str
    severity: str
    evidence: str
    validation_status: str
    matched_property_fact: str = ""
    kb_gap_candidate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_review_feedback_signals(
    private_note: str,
    *,
    property_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    text = _clean(private_note)
    if not text:
        return []

    property_data = property_data or {}
    signals: list[ReviewFeedbackSignal] = []

    if _contains_any(text, ("pack n play", "pack-and-play", "crib", "playpen")):
        advertised = _property_mentions(property_data, ("pack n play", "pack-and-play", "crib", "playpen"))
        signals.append(
            ReviewFeedbackSignal(
                family="amenity_expectation",
                theme="pack_n_play",
                severity="medium",
                evidence=_extract_sentence(text, ("pack n play", "pack-and-play", "crib", "playpen")),
                validation_status="possible_listing_mismatch" if advertised else "expectation_only",
                matched_property_fact="listing_mentions_pack_n_play" if advertised else "",
                kb_gap_candidate=bool(advertised),
            )
        )

    if _contains_any(text, ("beach towel", "beach towels", "towel", "towels")):
        advertised = _property_mentions(property_data, ("beach towel", "beach towels", "towel package", "beach gear"))
        signals.append(
            ReviewFeedbackSignal(
                family="amenity_expectation",
                theme="beach_towels",
                severity="low",
                evidence=_extract_sentence(text, ("beach towel", "beach towels", "towel", "towels")),
                validation_status="possible_listing_mismatch" if advertised else "expectation_only",
                matched_property_fact="listing_mentions_beach_towels" if advertised else "",
                kb_gap_candidate=bool(advertised),
            )
        )

    if _contains_any(text, ("wifi", "wi-fi", "internet")):
        wifi_available = bool(property_data.get("wifi_available"))
        signals.append(
            ReviewFeedbackSignal(
                family="connectivity",
                theme="wifi_reliability",
                severity="medium",
                evidence=_extract_sentence(text, ("wifi", "wi-fi", "internet")),
                validation_status="observed_issue" if wifi_available else "expectation_only",
                matched_property_fact="wifi_available=true" if wifi_available else "",
                kb_gap_candidate=False,
            )
        )

    if _contains_any(text, ("freezer", "fridge", "refrigerator", "ice maker")):
        advertised = _property_mentions(property_data, ("freezer", "fridge", "refrigerator", "full kitchen", "kitchen"))
        signals.append(
            ReviewFeedbackSignal(
                family="device_issue",
                theme="cold_storage_appliance",
                severity="medium",
                evidence=_extract_sentence(text, ("freezer", "fridge", "refrigerator", "ice maker")),
                validation_status="observed_issue" if advertised else "needs_operator_review",
                matched_property_fact="listing_mentions_kitchen_appliance" if advertised else "",
                kb_gap_candidate=False,
            )
        )

    if _contains_any(text, ("tv", "television", "televisions")):
        advertised = _property_mentions(property_data, ("tv", "television", "streaming"))
        signals.append(
            ReviewFeedbackSignal(
                family="device_issue",
                theme="tv_functionality",
                severity="medium",
                evidence=_extract_sentence(text, ("tv", "television", "televisions")),
                validation_status="observed_issue" if advertised else "needs_operator_review",
                matched_property_fact="listing_mentions_tv" if advertised else "",
                kb_gap_candidate=False,
            )
        )

    if _contains_any(text, ("toilet paper", "trash bag", "trash bags", "paper towel", "paper towels")):
        signals.append(
            ReviewFeedbackSignal(
                family="supplies",
                theme="starter_supplies",
                severity="low",
                evidence=_extract_sentence(text, ("toilet paper", "trash bag", "trash bags", "paper towel", "paper towels")),
                validation_status="observed_issue",
                matched_property_fact="",
                kb_gap_candidate=False,
            )
        )

    if _contains_any(text, ("house guide", "guidebook", "guide")):
        signals.append(
            ReviewFeedbackSignal(
                family="guide_gap",
                theme="house_guide_discoverability",
                severity="low",
                evidence=_extract_sentence(text, ("house guide", "guidebook", "guide")),
                validation_status="needs_operator_review",
                matched_property_fact="",
                kb_gap_candidate=False,
            )
        )

    return [signal.to_dict() for signal in signals]


def summarize_feedback_signal_outcome(signals: list[dict[str, Any]]) -> dict[str, Any]:
    if not signals:
        return {"count": 0, "kb_gap_candidates": 0, "families": []}
    families = sorted({str(item.get("family") or "") for item in signals if item.get("family")})
    kb_gap_candidates = sum(1 for item in signals if bool(item.get("kb_gap_candidate")))
    return {
        "count": len(signals),
        "kb_gap_candidates": kb_gap_candidates,
        "families": families,
    }


def _property_mentions(property_data: dict[str, Any], terms: tuple[str, ...]) -> bool:
    haystacks = [
        str(property_data.get("property_summary") or ""),
        str(property_data.get("description") or ""),
    ]
    return any(_contains_any(_clean(haystack), terms) for haystack in haystacks if haystack)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _extract_sentence(text: str, terms: tuple[str, ...]) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    for sentence in re.split(r"(?<=[.!?])\s+", normalized):
        if _contains_any(sentence, terms):
            return sentence.strip()
    return normalized[:240]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()
