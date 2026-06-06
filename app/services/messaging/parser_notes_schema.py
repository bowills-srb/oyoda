from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter


class IntentClassifierMetadataPayload(BaseModel):
    type: Literal["intent_classifier_metadata"]
    classifier_source: str
    threshold: float
    original_intent: str
    original_confidence: float
    escalated: bool = False
    contradictory_signals: bool = False
    escalation_provider: str | None = None
    escalated_confidence: float | None = None
    escalated_topic: str | None = None
    notes: list[str] = Field(default_factory=list)


class BrainClassifierMetadataPayload(BaseModel):
    type: Literal["brain_classifier_metadata"]
    classifier_source: str
    provider_used: str | None = None
    fallback_stage: str | None = None
    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    coercion_notes: list[str] = Field(default_factory=list)
    threshold: float | None = None
    original_intent: str | None = None
    original_confidence: float | None = None
    escalated: bool = False
    contradictory_signals: bool = False
    escalation_provider: str | None = None
    escalated_confidence: float | None = None
    escalated_topic: str | None = None
    legacy_intent: str | None = None
    confidence: float | None = None
    intent_topic: str | None = None
    matched_terms: list[str] = Field(default_factory=list)
    matched_override_keywords: list[str] = Field(default_factory=list)
    resolved_via_override: bool = False
    deterministic_gate_decision: str | None = None
    deterministic_handoff_reason: str | None = None


class ReservationRoutingMetadataPayload(BaseModel):
    type: Literal["reservation_routing_metadata"]
    lifecycle_routing_source: Literal[
        "concierge_session",
        "pms_reservation_matched",
        "no_match_pre_booking",
        "pms_lookup_disabled",
        "pms_lookup_failed",
    ]
    pms_match_method: Literal["reservation_id", "email", "name_dates"] | None = None
    reservation_id: str | None = None
    reservation_check_in: str | None = None
    reservation_check_out: str | None = None
    lifecycle_resolved: Literal["pre_booking", "pre_arrival", "in_stay", "post_stay"]
    property_code: str | None = None
    provider: str | None = None
    failure_reason: str | None = None


class PropertyMentionSurfaceAuditPayload(BaseModel):
    type: Literal["property_mention_surface_audit"]
    parser_path: Literal["llm_primary", "deterministic_fallback"]
    selected_surface: Literal["subject", "latest_body", "quoted_context", "unknown"]
    selected_mention: str | None = None
    selected_confidence: float | None = None
    available_surfaces: list[Literal["subject", "latest_body", "quoted_context"]] = Field(default_factory=list)
    candidate_surfaces: list[Literal["subject", "latest_body", "quoted_context"]] = Field(default_factory=list)
    matched_surfaces: list[Literal["subject", "latest_body", "quoted_context"]] = Field(default_factory=list)
    agreement: bool | None = None


class HealerProposalRecordedPayload(BaseModel):
    type: Literal["healer_proposal_recorded"]
    proposal_id: str
    proposal_kind: str
    signal_source: str
    recorded_at: str


ParserNotePayload = Annotated[
    IntentClassifierMetadataPayload
    | BrainClassifierMetadataPayload
    | ReservationRoutingMetadataPayload
    | PropertyMentionSurfaceAuditPayload
    | HealerProposalRecordedPayload,
    Field(discriminator="type"),
]

PARSER_NOTE_MODELS: dict[str, type[BaseModel]] = {
    "intent_classifier_metadata": IntentClassifierMetadataPayload,
    "brain_classifier_metadata": BrainClassifierMetadataPayload,
    "reservation_routing_metadata": ReservationRoutingMetadataPayload,
    "property_mention_surface_audit": PropertyMentionSurfaceAuditPayload,
    "healer_proposal_recorded": HealerProposalRecordedPayload,
}

_PARSER_NOTE_ADAPTER = TypeAdapter(ParserNotePayload)


def supported_parser_note_types() -> tuple[str, ...]:
    return tuple(PARSER_NOTE_MODELS.keys())


def validate_parser_note_payload(payload: dict[str, Any]) -> ParserNotePayload:
    return _PARSER_NOTE_ADAPTER.validate_python(payload)


def validate_parser_note_payloads(payloads: list[dict[str, Any]]) -> list[ParserNotePayload]:
    return [validate_parser_note_payload(payload) for payload in payloads]
