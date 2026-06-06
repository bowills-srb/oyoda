from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.services.messaging_brain.intake.intent_escalator import (
    PreBookingClassifierMetadata,
)


# ── Pipeline-stage types ─────────────────────────────────────────────────────
# These were previously in prebooking_runtime.py. They live here because
# prebooking_inquiry_types.py is the canonical domain-types home for the
# pre-booking pipeline.

@dataclass
class AutoSendPolicy:
    auto_send_threshold: float = 0.75
    auto_send_on_timeout: bool = True
    review_window_hours: int = 2
    flag_pet_inquiries: bool = False
    flag_pricing_inquiries: bool = True
    flag_custom_dates: bool = False


class SendDecision(str, Enum):
    SEND_NOW = "send_now"
    REVIEW = "review"
    HOLD = "hold"


@dataclass
class PolicyCheckResult:
    flags: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    block_send: bool = False

    @property
    def has_issues(self) -> bool:
        return bool(self.warnings) or self.block_send


@dataclass
class PreBookingClassificationStage:
    intent: str
    confidence: float
    metadata: Optional[PreBookingClassifierMetadata] = None
    shadow_parser_notes: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class PreBookingDecisionStage:
    approval_mode: str
    auto_send_policy: AutoSendPolicy
    policy_result: PolicyCheckResult
    missing_knowledge_topics: List[str]
    knowledge_gap_analysis: Any = None
    decision: SendDecision = SendDecision.HOLD


@dataclass
class PreBookingInquiryInput:
    thread_id: str
    platform: str
    guest_name: str
    message: str
    property_external_id: str
    company_id: UUID
    api_key: str
    property_data: Dict[str, Any]
    operator_policies: Dict[str, Any]
    structured_asks: List[str] = field(default_factory=list)
    conversation_context: str = ""
    requested_check_in: Optional[date] = None
    requested_check_out: Optional[date] = None
    requested_guests: Optional[int] = None
    message_id: str = ""
    force_approval_mode: Optional[str] = None
    db: Any = None
    guest_thread_id: Optional[str] = None
    brain_draft_confidence: Optional[float] = None
    review_verdict: Optional[str] = None
    confidence_source_override: Optional[str] = None


@dataclass
class PreBookingDraftStage:
    draft_text: str
    draft_source: str


@dataclass
class SaveInquiryResult:
    inserted: bool
    status: str
    guest_thread_id: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    def __bool__(self) -> bool:
        return self.inserted


@dataclass(frozen=True)
class InquirySaveContext:
    draft_id: str
    company_id: UUID
    intent: str
    confidence: float
    draft_text: str
    decision: str
    selected_property_code: str = ""
    requested_check_in: Optional[date] = None
    requested_check_out: Optional[date] = None
    requested_guests: Optional[int] = None
    draft_source: str = ""
    policy_flags: List[str] = field(default_factory=list)
    policy_warnings: List[str] = field(default_factory=list)
    guest_thread_id: Optional[str] = None
    blocked_by_gap_topics: List[str] = field(default_factory=list)
    triggered_by: Optional[str] = None
    intent_confidence: Optional[float] = None
    draft_confidence: Optional[float] = None
    confidence_source: str = "intent_only"
    review_verdict: Optional[str] = None
    autonomy_decision: str = "routed_to_action_auto_off"


def _pg_text_array_literal(values: Optional[List[str]]) -> List[str]:
    return [
        str(value or "").strip()
        for value in (values or [])
        if str(value or "").strip()
    ]
