"""
audit.py — Audit writer for the messaging brain.

Two responsibilities, exposed as two methods on MessageEventStoreAuditWriter:

  1. persist_inbound(message) — called BEFORE the orchestrator pipeline.
     Adapts brain InboundGuestMessage → existing CanonicalInboundMessage,
     calls message_event_store.persist_canonical_inbound_message, and
     returns the internal messages.message_id UUID.

     This UUID is REQUIRED by autonomy_gate.evaluate(triggered_by_message_id=...)
     so the orchestrator's policy step can detect blocking escalations.
     See docs/PHASE_1_3_SEAM_MAP.md "Rule 1" — this ordering is non-negotiable.

  2. write(record, original_message) — called in the orchestrator's finally
     block AFTER the pipeline completes. Calls
     message_event_store.update_normalization_outcome to populate
     route_outcome, draft_source, fallback_reason, selected_property_code
     on the row written by persist_inbound. When the record carries
     composer_metadata (Session 12), additionally calls
     update_normalization_composer_metadata to persist the composer
     fields. Always logs the full AgentAuditRecord at INFO so we have
     a trace even if the DB write fails.

Phase 1 status: in-memory record + shadow-write to existing tables.
Phase 5 will add a dedicated agent_audit_logs table for per-AgentDecision
rows. The contract for `write()` will not change at that point — only the
implementation.
"""

from __future__ import annotations

from dataclasses import asdict
import logging
from types import SimpleNamespace
from typing import Any, Optional
from uuid import UUID

from app.services.messaging.inbound_normalizer import (
    CanonicalInboundMessage,
    InboundMessageNormalizer,
)
from app.services.messaging.message_event_store import (
    persist_canonical_inbound_message,
    update_normalization_composer_metadata,
    update_normalization_outcome,
)
from app.services.orchestration.messaging_brain_contracts import (
    AgentAuditRecord,
    InboundGuestMessage,
)

logger = logging.getLogger(__name__)
_NORMALIZER = InboundMessageNormalizer()


# Truncation limits for free-form audit fields persisted to the DB. The
# message_normalizations columns are TEXT (no hard limit), but very long
# notes payloads bloat the table without benefit. Keep concatenated note
# strings under 500 chars.
_MAX_FALLBACK_REASON_LEN = 500


class MessageEventStoreAuditWriter:
    """Audit writer that wraps existing message_event_store functions.

    Stateless apart from a memory of the last record (for tests). Construct
    once and reuse — the orchestrator does this by default.

    DESIGN NOTE: Shadow mode does NOT skip audit writes. Audit writes are
    how operators validate the brain works before flipping the live switch,
    so they happen regardless of shadow_mode. What shadow mode skips is
    *module side effects* (work order creation, etc.), at the module
    execution boundary — not here. See seam-map Rule 5.
    """

    def __init__(self) -> None:
        # Last record kept for test inspection; never read in production.
        self.last_record: Optional[AgentAuditRecord] = None

    # ── persist_inbound ─────────────────────────────────────────────────────

    async def persist_inbound(
        self,
        db_session: Any,
        message: InboundGuestMessage,
    ) -> Optional[UUID]:
        """Shadow-write the inbound message to the DB and return the
        internal messages.message_id UUID for downstream policy use.

        Returns None if the underlying tables aren't present or the write
        fails (the existing function is fail-open). Callers must handle
        None — autonomy_gate.evaluate accepts triggered_by_message_id=None
        and simply skips the escalation-block lookup.
        """
        try:
            tenant_uuid = UUID(message.tenant_id)
        except (ValueError, AttributeError):
            logger.warning(
                "[MessagingBrain.audit] invalid tenant_id %r; skipping persist_inbound",
                message.tenant_id,
            )
            return None

        canonical = self._adapt_inbound_to_canonical(message)

        try:
            result = await persist_canonical_inbound_message(
                db_session, tenant_uuid, canonical,
            )
        except Exception as exc:  # noqa: BLE001 — fail-open; pipeline continues
            logger.exception(
                "[MessagingBrain.audit] persist_canonical_inbound_message raised: %s",
                exc,
            )
            return None

        msg_uuid_str = (result or {}).get("message_id")
        if not msg_uuid_str:
            return None
        try:
            return UUID(msg_uuid_str)
        except (ValueError, TypeError):
            logger.warning(
                "[MessagingBrain.audit] persist returned non-UUID message_id %r",
                msg_uuid_str,
            )
            return None

    # ── write ───────────────────────────────────────────────────────────────

    async def write(
        self,
        record: AgentAuditRecord,
        *,
        db_session: Any = None,
        original_message: Optional[InboundGuestMessage] = None,
    ) -> None:
        """Persist the per-message outcome to message_normalizations and
        log the full AgentAuditRecord at INFO.

        Failure-tolerant: if the DB write fails, we still log the record.
        The orchestrator wraps this in its own try/except so a write
        failure never crashes the pipeline.
        """
        self.last_record = record

        # 1. DB shadow-write (only if we have an original message; without
        #    it we can't address the right normalization row).
        if original_message is not None and db_session is not None:
            await self._write_outcome(record, original_message, db_session)

        # 2. INFO log — always emitted, even when DB is unavailable.
        self._log_record(record)

    async def _write_outcome(
        self,
        record: AgentAuditRecord,
        original_message: InboundGuestMessage,
        db_session: Any,
    ) -> None:
        try:
            tenant_uuid = UUID(record.tenant_id)
        except (ValueError, AttributeError):
            return

        route_outcome = (
            record.classification.intent_topic
            if record.classification else ""
        )
        draft_source = "messaging_brain"
        fallback_reason = self._compose_fallback_reason(record)
        selected_property_code = original_message.property_code or ""
        parser_notes_append: list[dict[str, Any]] = []
        if record.classifier_metadata is not None:
            parser_notes_append.append(
                {
                    "type": "brain_classifier_metadata",
                    "classifier_source": record.classifier_metadata.classifier_source,
                    "provider_used": record.classifier_metadata.provider_used,
                    "fallback_stage": record.classifier_metadata.fallback_stage,
                    "latency_ms": record.classifier_metadata.latency_ms,
                    "input_tokens": record.classifier_metadata.input_tokens,
                    "output_tokens": record.classifier_metadata.output_tokens,
                    "coercion_notes": list(record.classifier_metadata.coercion_notes or []),
                    "threshold": record.classifier_metadata.threshold,
                    "original_intent": record.classifier_metadata.original_intent,
                    "original_confidence": record.classifier_metadata.original_confidence,
                    "escalated": record.classifier_metadata.escalated,
                    "contradictory_signals": record.classifier_metadata.contradictory_signals,
                    "escalation_provider": record.classifier_metadata.escalation_provider,
                    "escalated_confidence": record.classifier_metadata.escalated_confidence,
                    "escalated_topic": record.classifier_metadata.escalated_topic,
                    "legacy_intent": record.classifier_metadata.legacy_intent,
                    "matched_terms": list(record.classifier_metadata.matched_terms or []),
                    "matched_override_keywords": list(record.classifier_metadata.matched_override_keywords or []),
                    "resolved_via_override": bool(record.classifier_metadata.resolved_via_override),
                    "deterministic_gate_decision": record.classifier_metadata.deterministic_gate_decision,
                    "deterministic_handoff_reason": record.classifier_metadata.deterministic_handoff_reason,
                    "confidence": (
                        record.classification.confidence if record.classification else None
                    ),
                    "intent_topic": (
                        record.classification.intent_topic if record.classification else None
                    ),
                }
            )

        try:
            await update_normalization_outcome(
                db_session,
                tenant_id=tenant_uuid,
                source_channel=original_message.channel,
                source_message_id=original_message.message_id,
                route_outcome=route_outcome,
                draft_source=draft_source,
                selected_property_code=selected_property_code,
                fallback_reason=fallback_reason,
                parser_notes_append=parser_notes_append,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "[MessagingBrain.audit] update_normalization_outcome failed for "
                "message_id=%s",
                original_message.message_id,
            )

        # Session 12 — persist composer metadata when the orchestrator
        # attached one. None means the composer didn't run (flag off);
        # we leave the composer columns at their nulls/defaults.
        # Non-None means the composer was attempted (even if it fell
        # back internally), so the audit row records that fact.
        if record.composer_metadata is not None:
            cm = record.composer_metadata
            try:
                await update_normalization_composer_metadata(
                    db_session,
                    tenant_id=tenant_uuid,
                    source_channel=original_message.channel,
                    source_message_id=original_message.message_id,
                    composer_source=cm.composer_source,
                    composer_response_text=cm.composer_response_text,
                    composer_latency_ms=cm.composer_latency_ms,
                    composer_input_tokens=cm.composer_input_tokens,
                    composer_output_tokens=cm.composer_output_tokens,
                    composer_notes=list(cm.composer_notes or []),
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[MessagingBrain.audit] update_normalization_composer_metadata "
                    "failed for message_id=%s",
                    original_message.message_id,
                )

    def _compose_fallback_reason(self, record: AgentAuditRecord) -> str:
        """Concatenate the most useful audit notes into a bounded string.

        Anything that explains why a draft went to DRAFT_ONLY or ESCALATE
        belongs here. Pipeline errors and module failures are surfaced
        first since they're the most actionable signals for operators.
        """
        if not record.notes:
            return ""
        # Prioritize errors and violations so they're not truncated away.
        priority: list[str] = []
        normal: list[str] = []
        for note in record.notes:
            if any(
                tag in note
                for tag in ("pipeline-error", "module-crash", "module-failed",
                            "evidence-violation")
            ):
                priority.append(note)
            else:
                normal.append(note)
        joined = "; ".join(priority + normal)
        if len(joined) <= _MAX_FALLBACK_REASON_LEN:
            return joined
        return joined[: _MAX_FALLBACK_REASON_LEN - 3] + "..."

    def _log_record(self, record: AgentAuditRecord) -> None:
        evidence_count = sum(len(d.evidence_used) for d in record.decisions)
        logger.info(
            "[MessagingBrain.audit] record_id=%s message_id=%s tenant=%s "
            "channel=%s intent_type=%s intent_topic=%s confidence=%.2f "
            "final_action=%s agent_path=%s evidence_count=%d "
            "module_events=%d module_responses=%d notes=%d",
            record.record_id,
            record.message_id,
            record.tenant_id,
            record.channel,
            record.classification.intent_type.value if record.classification else "?",
            record.classification.intent_topic if record.classification else "?",
            record.classification.confidence if record.classification else 0.0,
            record.policy.final_action.value if record.policy else "?",
            record.agent_path,
            evidence_count,
            len(record.module_events),
            len(record.module_responses),
            len(record.notes),
        )

    # ── Adapter ─────────────────────────────────────────────────────────────

    @staticmethod
    def _adapt_inbound_to_canonical(
        message: InboundGuestMessage,
    ) -> CanonicalInboundMessage:
        """Adapter: brain Pydantic model → existing dataclass.

        The brain shape is a strict superset of CanonicalInboundMessage's
        fields, so this is a pure widening transform with sensible
        defaults for fields the brain doesn't track.
        """
        sender_address = message.guest_email or message.guest_phone or ""
        full_text = message.full_thread_text or message.text
        property_binding_candidates = [
            asdict(candidate)
            for candidate in _NORMALIZER._build_property_candidates(  # noqa: SLF001
                MessageEventStoreAuditWriter._message_property_view(message)
            )
        ]

        return CanonicalInboundMessage(
            source_channel=message.channel,
            source_provider=message.source_provider or "",
            source_thread_id=message.thread_id or "",
            source_message_id=message.message_id,
            sender_role="guest",
            sender_display_name=message.guest_name or "Guest",
            sender_address=sender_address,
            sent_at=message.received_at,
            raw_subject=message.raw_subject or "",
            latest_guest_turn=message.text,
            prior_thread_context=message.full_thread_text or "",
            full_message_text=full_text,
            structured_asks=list(message.structured_asks or []),
            prior_operator_commitments=[],
            property_binding_candidates=property_binding_candidates,
            channel_constraints={},
            parser_used=message.parser_used or "messaging_brain",
            parser_version="v1",
            parser_notes=[],
            latest_turn_confidence=message.parser_confidence,
            latest_turn_extracted=False,
            guest_name=message.guest_name or "Guest",
            guest_email=message.guest_email or "",
        )

    @staticmethod
    def _message_property_view(message: InboundGuestMessage) -> Any:
        metadata = message.metadata or {}
        return SimpleNamespace(
            platform_listing_id=str(metadata.get("platform_listing_id") or ""),
            platform_unit_id=str(metadata.get("platform_unit_id") or ""),
            property_code=message.property_code or "",
            property_name=str(metadata.get("property_name") or ""),
            raw_property_mention=str(
                metadata.get("raw_property_mention")
                or metadata.get("property_name")
                or message.property_code
                or ""
            ),
        )
