from __future__ import annotations

from dataclasses import dataclass, replace
from html import unescape
import json
import re
from typing import Any, Optional, Protocol
from uuid import UUID

from app.services.extraction.canonical_block_service import CanonicalBlock
from app.services.extraction.validation_rules import DETERMINISTIC_VALIDATOR


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_question_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _html_to_text(value: Any) -> str:
    text_value = str(value or "")
    without_tags = re.sub(r"<[^>]+>", " ", text_value)
    return _normalize_text(unescape(without_tags))


def _format_time(value: Any) -> str:
    text_value = _normalize_text(value)
    if not text_value:
        return ""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?", text_value)
    if not match:
        return text_value
    hour = int(match.group(1))
    minute = match.group(2)
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute} {suffix}"


def _as_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stringify_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _normalize_text(value)
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _json_safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


@dataclass(frozen=True)
class ExtractionCandidatePayload:
    scope_type: str
    scope_target_id: str
    source_type: str
    extraction_method: str
    candidate_type: str
    proposed_question_text: str
    proposed_question_key: str
    proposed_answer_text: str
    proposed_topic_id: Optional[str]
    proposed_tags: list[str]
    proposed_metadata: dict[str, Any]
    confidence: float
    evidence_excerpt: str
    source_section: str


class DeterministicExtractor(Protocol):
    render_type: str

    def extract(self, canonical_block: CanonicalBlock) -> list[ExtractionCandidatePayload]:
        ...


def _base_metadata(canonical_block: CanonicalBlock) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "render_type": canonical_block.render_type,
        "canonical_page_id": canonical_block.canonical_page_id,
        "canonical_source_property_id": str(canonical_block.canonical_source_property_id),
        "duplicate_count": canonical_block.duplicate_count,
        "block_hash": canonical_block.block_hash,
    }
    if canonical_block.duplicate_group_metadata:
        metadata["duplicate_group_metadata"] = _json_safe(canonical_block.duplicate_group_metadata)
    return metadata


def _build_payload(
    canonical_block: CanonicalBlock,
    *,
    question_text: str,
    answer_text: str,
    evidence_excerpt: str,
    topic_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
    metadata: Optional[dict[str, Any]] = None,
    source_suffix: Optional[str] = None,
) -> Optional[ExtractionCandidatePayload]:
    normalized_question = _normalize_text(question_text)
    normalized_answer = _normalize_text(answer_text)
    if not normalized_question or not normalized_answer:
        return None
    normalized_evidence = _normalize_text(evidence_excerpt) or normalized_answer
    payload_metadata = _base_metadata(canonical_block)
    if metadata:
        payload_metadata.update(metadata)
    if topic_id and topic_id not in payload_metadata.get("tags", []):
        payload_tags = list(dict.fromkeys([*(tags or []), topic_id]))
    else:
        payload_tags = list(dict.fromkeys(tags or []))
    source_section = canonical_block.render_type
    if source_suffix:
        source_section = f"{source_section} | {source_suffix}"
    return ExtractionCandidatePayload(
        scope_type=canonical_block.scope_type,
        scope_target_id=_scope_target_id(canonical_block),
        source_type="guidebook",
        extraction_method="deterministic",
        candidate_type="fact",
        proposed_question_text=normalized_question,
        proposed_question_key=_normalize_question_key(normalized_question),
        proposed_answer_text=normalized_answer,
        proposed_topic_id=topic_id,
        proposed_tags=payload_tags,
        proposed_metadata=payload_metadata,
        confidence=0.98,
        evidence_excerpt=normalized_evidence,
        source_section=source_section,
    )


def _scope_target_id(canonical_block: CanonicalBlock) -> str:
    if canonical_block.scope_type == "tenant":
        return str(canonical_block.tenant_id)
    return str(canonical_block.canonical_source_property_id)


class ReservationInfoExtractor:
    render_type = "widget.reservation_info"

    def extract(self, canonical_block: CanonicalBlock) -> list[ExtractionCandidatePayload]:
        data = canonical_block.block_content.get("data")
        if not isinstance(data, dict):
            return []

        payloads: list[ExtractionCandidatePayload] = []
        common_meta = {"field_source": "widget.reservation_info"}

        checkin = _format_time(data.get("checkin_time"))
        payload = _build_payload(
            canonical_block,
            question_text="What time is check-in?",
            answer_text=checkin,
            evidence_excerpt=_stringify_value(data.get("checkin_time")),
            topic_id="check_in_process",
            tags=["check_in"],
            metadata={**common_meta, "field_name": "checkin_time"},
            source_suffix="Reservation Info",
        )
        if payload:
            payloads.append(_replace_scope_target(payload, canonical_block))

        checkout = _format_time(data.get("checkout_time"))
        payload = _build_payload(
            canonical_block,
            question_text="What time is check-out?",
            answer_text=checkout,
            evidence_excerpt=_stringify_value(data.get("checkout_time")),
            topic_id=None,
            tags=["check_out"],
            metadata={**common_meta, "field_name": "checkout_time"},
            source_suffix="Reservation Info",
        )
        if payload:
            payloads.append(_replace_scope_target(payload, canonical_block))

        bedrooms = _as_int(data.get("bedroom_count"))
        payload = _build_payload(
            canonical_block,
            question_text="How many bedrooms does the property have?",
            answer_text=str(bedrooms) if bedrooms is not None else "",
            evidence_excerpt=_stringify_value(data.get("bedroom_count")),
            topic_id="sleeping_arrangement",
            tags=["bedrooms"],
            metadata={**common_meta, "field_name": "bedroom_count"},
            source_suffix="Reservation Info",
        )
        if payload:
            payloads.append(_replace_scope_target(payload, canonical_block))

        bathrooms = _as_int(data.get("bathroom_count"))
        payload = _build_payload(
            canonical_block,
            question_text="How many bathrooms does the property have?",
            answer_text=str(bathrooms) if bathrooms is not None else "",
            evidence_excerpt=_stringify_value(data.get("bathroom_count")),
            topic_id=None,
            tags=["bathrooms"],
            metadata={**common_meta, "field_name": "bathroom_count"},
            source_suffix="Reservation Info",
        )
        if payload:
            payloads.append(_replace_scope_target(payload, canonical_block))

        occupancy = _as_int(data.get("guest_count"))
        payload = _build_payload(
            canonical_block,
            question_text="What's the maximum occupancy?",
            answer_text=str(occupancy) if occupancy is not None else "",
            evidence_excerpt=_stringify_value(data.get("guest_count")),
            topic_id="max_occupancy",
            tags=["occupancy"],
            metadata={**common_meta, "field_name": "guest_count"},
            source_suffix="Reservation Info",
        )
        if payload:
            payloads.append(_replace_scope_target(payload, canonical_block))

        return payloads


class WifiExtractor:
    render_type = "widget.wifi"

    def extract(self, canonical_block: CanonicalBlock) -> list[ExtractionCandidatePayload]:
        data = canonical_block.block_content.get("data")
        if not isinstance(data, dict):
            return []
        payloads: list[ExtractionCandidatePayload] = []
        wifi_name = _stringify_value(data.get("wifi_name"))
        payload = _build_payload(
            canonical_block,
            question_text="What's the WiFi network name?",
            answer_text=wifi_name,
            evidence_excerpt=_stringify_value(data.get("wifi_name")),
            topic_id=None,
            tags=["wifi"],
            metadata={"field_source": "widget.wifi", "field_name": "wifi_name"},
            source_suffix="Wifi",
        )
        if payload:
            payloads.append(_replace_scope_target(payload, canonical_block))

        password = _stringify_value(data.get("wifi_password"))
        payload = _build_payload(
            canonical_block,
            question_text="What's the WiFi password?",
            answer_text=password,
            evidence_excerpt=_stringify_value(data.get("wifi_password")),
            topic_id=None,
            tags=["wifi"],
            metadata={"field_source": "widget.wifi", "field_name": "wifi_password"},
            source_suffix="Wifi",
        )
        if payload:
            payloads.append(_replace_scope_target(payload, canonical_block))
        return payloads


class ContactInfoExtractor:
    _QUESTION_MAP = {
        "widget.messaging_phone_number": "What's the messaging contact phone number?",
        "widget.phone_number": "What's the operator's phone number?",
        "widget.email_address": "What's the operator's email address?",
        "widget.website": "What's the operator's website?",
    }

    def __init__(self, render_type: str) -> None:
        self.render_type = render_type

    def extract(self, canonical_block: CanonicalBlock) -> list[ExtractionCandidatePayload]:
        answer = _stringify_value(canonical_block.block_content.get("data"))
        payload = _build_payload(
            canonical_block,
            question_text=self._QUESTION_MAP[self.render_type],
            answer_text=answer,
            evidence_excerpt=answer,
            topic_id=None,
            tags=["contact_info"],
            metadata={"field_source": self.render_type, "field_name": self.render_type},
            source_suffix=canonical_block.block_content.get("title") or self.render_type,
        )
        if not payload:
            return []
        return [_replace_scope_target(payload, canonical_block, tenant_scope=True)]


class DirectionNoteExtractor:
    render_type = "home.direction_note"

    def extract(self, canonical_block: CanonicalBlock) -> list[ExtractionCandidatePayload]:
        raw_value = canonical_block.block_content.get("data")
        text_value = _html_to_text(raw_value)
        payload = _build_payload(
            canonical_block,
            question_text="Are there special arrival directions?",
            answer_text=text_value,
            evidence_excerpt=text_value,
            topic_id=None,
            tags=["directions"],
            metadata={"field_source": "home.direction_note", "field_name": "direction_note"},
            source_suffix=canonical_block.block_content.get("title") or "Directions",
        )
        if not payload:
            return []
        return [_replace_scope_target(payload, canonical_block)]


def _replace_scope_target(
    payload: ExtractionCandidatePayload,
    canonical_block: CanonicalBlock,
    *,
    tenant_scope: bool = False,
) -> ExtractionCandidatePayload:
    scope_type = "tenant" if tenant_scope or canonical_block.scope_type == "tenant" else "property"
    if scope_type == "tenant":
        scope_target_id = str(canonical_block.tenant_id)
    else:
        scope_target_id = str(canonical_block.canonical_source_property_id)
    metadata = dict(payload.proposed_metadata)
    metadata["applicable_property_ids"] = [str(value) for value in canonical_block.applicable_property_ids]
    if scope_type == "tenant":
        metadata["tenant_scope_applies_to_count"] = len(canonical_block.applicable_property_ids)
    return ExtractionCandidatePayload(
        scope_type=scope_type,
        scope_target_id=scope_target_id,
        source_type=payload.source_type,
        extraction_method=payload.extraction_method,
        candidate_type=payload.candidate_type,
        proposed_question_text=payload.proposed_question_text,
        proposed_question_key=payload.proposed_question_key,
        proposed_answer_text=payload.proposed_answer_text,
        proposed_topic_id=payload.proposed_topic_id,
        proposed_tags=payload.proposed_tags,
        proposed_metadata=metadata,
        confidence=payload.confidence,
        evidence_excerpt=payload.evidence_excerpt,
        source_section=payload.source_section,
    )


def _apply_validation(
    payload: ExtractionCandidatePayload,
    canonical_block: CanonicalBlock,
) -> ExtractionCandidatePayload:
    result = DETERMINISTIC_VALIDATOR.check(payload, canonical_block.block_content)
    if result.passed:
        return payload

    metadata = dict(payload.proposed_metadata)
    metadata["validation_concern"] = {
        "concern_type": result.concern_type,
        "concern_description": result.concern_description,
        "suggested_action": result.suggested_action,
    }
    tags = list(dict.fromkeys([*payload.proposed_tags, "validation_review"]))
    return replace(
        payload,
        proposed_tags=tags,
        proposed_metadata=metadata,
        confidence=0.70,
    )


CONTACT_RENDER_TYPES = {
    "widget.messaging_phone_number",
    "widget.phone_number",
    "widget.email_address",
    "widget.website",
}


EXTRACTOR_REGISTRY: dict[str, DeterministicExtractor] = {
    ReservationInfoExtractor.render_type: ReservationInfoExtractor(),
    WifiExtractor.render_type: WifiExtractor(),
    DirectionNoteExtractor.render_type: DirectionNoteExtractor(),
    **{render_type: ContactInfoExtractor(render_type) for render_type in CONTACT_RENDER_TYPES},
}


def get_deterministic_extractor(render_type: str) -> Optional[DeterministicExtractor]:
    return EXTRACTOR_REGISTRY.get(str(render_type or ""))


def extract_deterministic_candidates(canonical_block: CanonicalBlock) -> list[ExtractionCandidatePayload]:
    extractor = get_deterministic_extractor(canonical_block.render_type)
    if extractor is None:
        return []
    return [_apply_validation(payload, canonical_block) for payload in extractor.extract(canonical_block)]
