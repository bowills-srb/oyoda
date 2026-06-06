"""
Persistence for InboundMessageGate decisions.

Each gate decision is written to inbound_classifications using an isolated
session so write failures here cannot poison the caller's transaction state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import text

from app.core.database import get_db_session
from app.services.messaging_brain.inbound_message_gate import GateDecision

logger = logging.getLogger(__name__)


async def persist_gate_decision(
    *,
    decision: GateDecision,
    tenant_id: UUID,
    gmail_message_id: Optional[str],
    source_message_id: Optional[str],
    parser_source: Optional[str],
    from_header: Optional[str],
    subject: Optional[str],
    proceeded_as_guest: bool,
    routed_to_review: bool,
) -> bool:
    """Persist one gate decision for observability and rollout review."""
    try:
        async with get_db_session() as db:
            await db.execute(
                text(
                    """
                    INSERT INTO inbound_classifications (
                        decision_id,
                        tenant_id,
                        gmail_message_id,
                        source_message_id,
                        parser_source,
                        from_header,
                        subject,
                        classification,
                        confidence,
                        reasoning,
                        model,
                        extracted_guest_text,
                        extracted_guest_name,
                        extracted_property_reference,
                        extracted_reply_path,
                        extracted_thread_id,
                        proceeded_as_guest,
                        routed_to_review,
                        gate_error,
                        raw_response,
                        created_at
                    ) VALUES (
                        :decision_id,
                        :tenant_id,
                        :gmail_message_id,
                        :source_message_id,
                        :parser_source,
                        :from_header,
                        :subject,
                        :classification,
                        :confidence,
                        :reasoning,
                        :model,
                        :extracted_guest_text,
                        :extracted_guest_name,
                        :extracted_property_reference,
                        :extracted_reply_path,
                        :extracted_thread_id,
                        :proceeded_as_guest,
                        :routed_to_review,
                        :gate_error,
                        :raw_response,
                        :created_at
                    )
                    ON CONFLICT (decision_id) DO NOTHING
                    """
                ),
                {
                    "decision_id": decision.decision_id,
                    "tenant_id": tenant_id,
                    "gmail_message_id": gmail_message_id,
                    "source_message_id": source_message_id,
                    "parser_source": parser_source,
                    "from_header": from_header,
                    "subject": subject,
                    "classification": decision.classification.value,
                    "confidence": decision.confidence,
                    "reasoning": decision.reasoning,
                    "model": decision.model,
                    "extracted_guest_text": (
                        decision.extracted.guest_text if decision.extracted else None
                    ),
                    "extracted_guest_name": (
                        decision.extracted.guest_name if decision.extracted else None
                    ),
                    "extracted_property_reference": (
                        decision.extracted.property_reference if decision.extracted else None
                    ),
                    "extracted_reply_path": (
                        decision.extracted.reply_path if decision.extracted else None
                    ),
                    "extracted_thread_id": (
                        decision.extracted.thread_id if decision.extracted else None
                    ),
                    "proceeded_as_guest": proceeded_as_guest,
                    "routed_to_review": routed_to_review,
                    "gate_error": decision.error,
                    "raw_response": decision.raw_response,
                    "created_at": datetime.now(timezone.utc),
                },
            )
            await db.commit()
        return True
    except Exception as exc:
        logger.error(
            "[InboundGate] persist_failed exception_type=%s message=%s "
            "decision_id=%s tenant_id=%s classification=%s",
            type(exc).__name__,
            str(exc),
            decision.decision_id,
            tenant_id,
            decision.classification.value,
            exc_info=True,
        )
        return False
