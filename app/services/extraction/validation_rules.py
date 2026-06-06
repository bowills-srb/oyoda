from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Protocol
import re

if TYPE_CHECKING:
    from app.services.extraction.deterministic_extractors import ExtractionCandidatePayload


VALIDATION_ACTION_RANK = {
    "auto_promote": 0,
    "stage_for_review": 1,
    "reject": 2,
}


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    concern_type: str | None
    concern_description: str | None
    suggested_action: str


class ValidationRule(Protocol):
    def check(
        self,
        candidate_payload: ExtractionCandidatePayload,
        source_block: dict[str, Any],
    ) -> ValidationResult:
        ...


def _pass_result() -> ValidationResult:
    return ValidationResult(
        passed=True,
        concern_type=None,
        concern_description=None,
        suggested_action="auto_promote",
    )


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _as_int(value: Any) -> Optional[int]:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _basic_email_ok(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))


def _basic_phone_ok(value: str) -> bool:
    compact = re.sub(r"[^\d+]", "", value)
    digit_count = len(re.sub(r"\D", "", compact))
    return digit_count >= 7 and bool(re.fullmatch(r"\+?[\d]+", compact))


class ReservationInfoRule:
    def check(
        self,
        candidate_payload: ExtractionCandidatePayload,
        source_block: dict[str, Any],
    ) -> ValidationResult:
        if source_block.get("render_type") != "widget.reservation_info":
            return _pass_result()

        data = source_block.get("data")
        if not isinstance(data, dict):
            return _pass_result()

        bedrooms = _as_int(data.get("bedroom_count"))
        bathrooms = _as_int(data.get("bathroom_count"))
        bed_count = _as_int(data.get("bed_count"))
        checkin = _normalize_text(data.get("checkin_time"))
        checkout = _normalize_text(data.get("checkout_time"))

        if (
            bedrooms is not None
            and bathrooms is not None
            and bathrooms > bedrooms + 2
        ):
            return ValidationResult(
                passed=False,
                concern_type="implausible",
                concern_description="bathroom_count is more than two above bedroom_count",
                suggested_action="stage_for_review",
            )
        if bedrooms == 0 and bed_count is not None and bed_count > 0:
            return ValidationResult(
                passed=False,
                concern_type="implausible",
                concern_description="bedroom_count is zero while bed_count is non-zero",
                suggested_action="stage_for_review",
            )
        if bedrooms is not None and bedrooms > 20:
            return ValidationResult(
                passed=False,
                concern_type="implausible",
                concern_description="bedroom_count exceeds sanity threshold of 20",
                suggested_action="stage_for_review",
            )
        if bathrooms is not None and bathrooms > 20:
            return ValidationResult(
                passed=False,
                concern_type="implausible",
                concern_description="bathroom_count exceeds sanity threshold of 20",
                suggested_action="stage_for_review",
            )
        if checkin and checkout and checkin == checkout:
            return ValidationResult(
                passed=False,
                concern_type="implausible",
                concern_description="check-in time matches check-out time",
                suggested_action="stage_for_review",
            )
        return _pass_result()


class WifiRule:
    def check(
        self,
        candidate_payload: ExtractionCandidatePayload,
        source_block: dict[str, Any],
    ) -> ValidationResult:
        if source_block.get("render_type") != "widget.wifi":
            return _pass_result()

        data = source_block.get("data")
        if not isinstance(data, dict):
            return _pass_result()

        name = _normalize_text(data.get("wifi_name"))
        password = _normalize_text(data.get("wifi_password"))

        if name and not password:
            return ValidationResult(
                passed=False,
                concern_type="sparse",
                concern_description="wifi_name is present but wifi_password is blank",
                suggested_action="stage_for_review",
            )
        if name and (len(name) > 64 or re.search(r"[\x00-\x1f]", name)):
            return ValidationResult(
                passed=False,
                concern_type="malformed",
                concern_description="wifi_name has control characters or exceeds 64 characters",
                suggested_action="stage_for_review",
            )
        return _pass_result()


class ContactInfoRule:
    def check(
        self,
        candidate_payload: ExtractionCandidatePayload,
        source_block: dict[str, Any],
    ) -> ValidationResult:
        render_type = source_block.get("render_type")
        answer = _normalize_text(candidate_payload.proposed_answer_text)
        if not answer:
            return _pass_result()

        if render_type == "widget.email_address" and not _basic_email_ok(answer):
            return ValidationResult(
                passed=False,
                concern_type="malformed",
                concern_description="email address failed basic format validation",
                suggested_action="stage_for_review",
            )
        if render_type in {"widget.phone_number", "widget.messaging_phone_number"} and not _basic_phone_ok(answer):
            return ValidationResult(
                passed=False,
                concern_type="malformed",
                concern_description="phone number failed basic format validation",
                suggested_action="stage_for_review",
            )
        if render_type == "widget.website" and not answer.lower().startswith(("http://", "https://")):
            return ValidationResult(
                passed=False,
                concern_type="malformed",
                concern_description="website value does not start with http:// or https://",
                suggested_action="stage_for_review",
            )
        return _pass_result()


class DirectionNoteRule:
    def check(
        self,
        candidate_payload: ExtractionCandidatePayload,
        source_block: dict[str, Any],
    ) -> ValidationResult:
        if source_block.get("render_type") != "home.direction_note":
            return _pass_result()

        text_value = _normalize_text(candidate_payload.proposed_answer_text)
        if len(text_value) < 10:
            return ValidationResult(
                passed=False,
                concern_type="sparse",
                concern_description="direction note is shorter than 10 characters",
                suggested_action="stage_for_review",
            )
        return _pass_result()


class CompositeValidator:
    def __init__(self, rules: list[ValidationRule]) -> None:
        self._rules = rules

    def check(
        self,
        candidate_payload: ExtractionCandidatePayload,
        source_block: dict[str, Any],
    ) -> ValidationResult:
        chosen = _pass_result()
        for rule in self._rules:
            result = rule.check(candidate_payload, source_block)
            if VALIDATION_ACTION_RANK[result.suggested_action] > VALIDATION_ACTION_RANK[chosen.suggested_action]:
                chosen = result
            elif (
                not result.passed
                and not chosen.passed
                and VALIDATION_ACTION_RANK[result.suggested_action] == VALIDATION_ACTION_RANK[chosen.suggested_action]
            ):
                chosen = result
        return chosen


DETERMINISTIC_VALIDATOR = CompositeValidator(
    [
        ReservationInfoRule(),
        WifiRule(),
        ContactInfoRule(),
        DirectionNoteRule(),
    ]
)
