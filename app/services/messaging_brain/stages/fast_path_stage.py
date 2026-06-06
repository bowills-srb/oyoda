from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from typing import Any, Optional
from uuid import UUID

from app.services.concierge.escalation_service import EscalationDetector
from app.services.concierge.escapia_unified import intercept_gate_code_request
from app.services.orchestration.messaging_brain_contracts import (
    InboundGuestMessage,
    MessageClassification,
    RecommendedAction,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FastPathResult:
    response_text: str
    confidence: float
    confidence_source: str
    final_action: RecommendedAction = RecommendedAction.DRAFT_ONLY
    escalation_required: bool = False
    reason_for_escalation: str = ""
    notes: list[str] = field(default_factory=list)


class FastPathStage:
    name = "FastPathStage"

    def __init__(self, *, escalation_detector: Optional[EscalationDetector] = None) -> None:
        self._escalation_detector = escalation_detector or EscalationDetector()

    async def run(
        self,
        *,
        message: InboundGuestMessage,
        classification: MessageClassification,
        db_session: Any,
    ) -> Optional[FastPathResult]:
        escalation = self._maybe_escalate(message)
        if escalation is not None:
            return escalation

        gate_code = await self._maybe_intercept_gate_code(
            message=message,
            db_session=db_session,
        )
        if gate_code is not None:
            return gate_code

        return None

    def _maybe_escalate(self, message: InboundGuestMessage) -> Optional[FastPathResult]:
        detected = self._escalation_detector.detect_escalation(message.text or "", [])
        if not detected or not detected.get("needed"):
            return None

        priority = str(detected.get("priority") or "medium").lower()
        reason = str(detected.get("reason") or "other").lower()
        support_phone = (
            str(message.metadata.get("context_adapter_overlay", {}).get("access_info", {}).get("support_phone") or "")
            if isinstance(message.metadata, dict)
            else ""
        ) or "your host team"
        guest_name = (message.guest_name or "Guest").split()[0]

        return FastPathResult(
            response_text=_escalation_response(
                priority=priority,
                reason_code=reason,
                guest_name=guest_name,
                support_phone=support_phone,
            ),
            confidence=1.0,
            confidence_source="escalation_routed",
            final_action=RecommendedAction.ESCALATE,
            escalation_required=True,
            reason_for_escalation=f"fast_path escalation: {reason}",
            notes=[
                "fast_path: escalation_routed",
                f"esc_reason:{reason}",
                f"fast_path: escalation priority={priority} reason={reason}",
            ],
        )

    async def _maybe_intercept_gate_code(
        self,
        *,
        message: InboundGuestMessage,
        db_session: Any,
    ) -> Optional[FastPathResult]:
        identity = getattr(message, "identity", None)
        identity_state = str(getattr(identity, "state", "") or "").lower()
        if identity_state != "identified":
            return None
        if not message.session_token or not message.property_code:
            return None

        api_key = os.getenv("ESCAPIA_API_KEY", "")
        company_id_raw = os.getenv("FIRST_OPERATOR_COMPANY_ID", "")
        if not api_key or not company_id_raw:
            return None

        try:
            company_id = UUID(company_id_raw)
        except (ValueError, TypeError):
            return None

        overlay = message.metadata.get("context_adapter_overlay", {}) if isinstance(message.metadata, dict) else {}
        reservation_facts = overlay.get("reservation_facts", {}) if isinstance(overlay, dict) else {}
        session_data = {
            "check_in": reservation_facts.get("check_in_date") or message.metadata.get("check_in_date"),
            "check_out": reservation_facts.get("check_out_date") or message.metadata.get("check_out_date"),
            "guest_name": message.guest_name or "Guest",
        }

        try:
            response_text = await intercept_gate_code_request(
                message=message.text or "",
                session_data=session_data,
                property_external_id=message.property_code,
                session_token=message.session_token,
                company_id=company_id,
                api_key=api_key,
                db=db_session,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[FastPathStage] gate-code intercept failed: %s", exc, exc_info=True)
            return None

        if not response_text:
            return None

        return FastPathResult(
            response_text=response_text,
            confidence=1.0,
            confidence_source="gate_code_intercept",
            final_action=RecommendedAction.AUTO_SEND,
            notes=["fast_path: gate_code_intercept"],
        )


def _escalation_response(
    *,
    priority: str,
    reason_code: str,
    guest_name: str,
    support_phone: str,
) -> str:
    if priority == "urgent":
        return (
            f"I'm so sorry you're dealing with this, {guest_name}. "
            f"This needs immediate attention — please call our emergency line right now: **{support_phone}**. "
            "Someone is available 24/7 and will help you right away. 🆘"
        )
    if priority == "high":
        if reason_code == "maintenance":
            return (
                f"I'm so sorry about this issue, {guest_name}! "
                "I'm immediately alerting our property team. "
                f"They'll be in touch very shortly. If it's urgent, please call us directly: **{support_phone}**."
            )
        return (
            f"I completely understand your frustration, {guest_name}. "
            "This deserves more than I can offer through chat — let me connect you with a team member who can make this right. "
            f"Please call us at **{support_phone}** or I can have someone call you."
        )
    return (
        f"Of course, {guest_name}! Let me connect you with a team member right away. "
        f"You can reach us at **{support_phone}**."
    )
