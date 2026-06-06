"""
context_builder_agent.py — Loads guest context for the messaging brain.

Primary read path is now canonical/scoped knowledge. The legacy
ConciergeKnowledgeService path is retained only as an explicit injected
compatibility seam for tests while the remaining knowledge-surface
retirement is in flight.

Phase 1.3 scope:
  - Loads property_facts (wifi, check_in, check_out, etc.)
  - Surfaces FAQ presence as evidence (property_knowledge.faq_count)
  - Surfaces HVAC-relevant FAQ entries as synthetic facts so the AC slice
    has something citeable
  - Infers lifecycle from intent_type (SYSTEM_EVENT → SYSTEM, else IN_STAY)

Phase 2.1 enhancement:
  - Surfaces the full normalized FAQ list at property_knowledge.faq
    (capped + truncated; see _FAQ_LIST_MAX_ENTRIES / _FAQ_FIELD_MAX_CHARS)
    so downstream specialists (HouseRulesAgent, AccessAgent, etc.) can
    ground answers without needing a second knowledge-service call.
    faq_count is preserved for backward compatibility.

Phase 1.4+:
  - Real reservation-based lifecycle inference (read reservations table)
  - Real maintenance_status from existing concierge_maintenance_events
  - Local guidebook facts via concierge_local_recommendations
  - Prior message history via the messages table
  - Real RAG pass over FAQ instead of keyword scan

Session 5 additive seam:
  - Accepts an optional provider-normalized context overlay at
    message.metadata["context_adapter_overlay"] so the same brain can
    run on split-provider pre-booking flows (email transport + PMS
    context) without hard-coding provider-specific logic here.

Evidence-key contract:
  evidence_keys lists the keys that downstream agents may cite via
  AgentDecision.evidence_used. Anything outside this list cited by an
  agent will be flagged in the audit log. Keep evidence_keys narrow
  and precise — only include keys whose values are actually populated.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.services.messaging_brain.context.property_facts import (
    assess_prebooking_knowledge_richness,
    retrieve_prebooking_property_evidence,
)
from app.services.messaging_brain.context.lazy_context_gates import (
    needs_local_knowledge,
    needs_nearby_availability,
    needs_property_facts,
)
from app.services.messaging_brain.context.operator_guidance import load_operator_guidance
from app.services.concierge.operator_learning import build_preference_context
from app.services.feature_flags import (
    is_messaging_brain_canonical_kb_read_enabled,
    is_messaging_brain_lazy_context_stage_enabled,
    is_messaging_brain_rich_context_enabled,
    is_messaging_brain_rich_context_shadow_enabled,
    is_messaging_brain_vector_fallback_enabled,
    is_messaging_brain_vector_fallback_shadow_enabled,
)
from app.services.messaging_brain.agents.context_builder_adapters import (
    extract_guidebook_knowledge,
    to_legacy_prebooking_property_data,
)
from app.services.messaging_brain.agents.rich_context_shadow_store import (
    ShadowExceptions,
    build_exception_entry,
    record_rich_context_shadow_observation,
)
from app.services.property_canonical_service import get_canonical_property_service
from app.services.orchestration.messaging_brain_contracts import (
    GuestContextBundle,
    InboundGuestMessage,
    IntentType,
    MessageClassification,
    MessagingLifecycle,
    OutboundIntent,
)

logger = logging.getLogger(__name__)

_VECTOR_TOP_K_DEFAULT = int(os.getenv("PHASE_4_2_5_VECTOR_TOP_K", "5"))
_VECTOR_MIN_SCORE_DEFAULT = float(os.getenv("PHASE_4_2_5_VECTOR_MIN_SCORE", "0.25"))


# Keys we look for in the legacy facts dict. The legacy loader populates
# these conditionally based on Q&A questions matching certain patterns.
_KNOWN_FACT_KEYS = ("wifi", "check_in", "check_out")

# Caps on the FAQ list surfaced into GuestContextBundle.property_knowledge.
# These bound bundle size so the audit row and any downstream serialization
# stay reasonable even for operators with very large knowledge bases.
# 50 entries comfortably covers typical operator KBs (commonly 20–60 entries).
# 800 chars per question/answer is well above realistic FAQ lengths;
# anything longer is almost certainly an import artifact.
_FAQ_LIST_MAX_ENTRIES = 50
_FAQ_FIELD_MAX_CHARS = 800
# Optional fields surfaced from each FAQ entry when present and truthy.
# Kept narrow on purpose — anything outside this allowlist is dropped
# so the in-context shape stays predictable for downstream agents.
_FAQ_PASSTHROUGH_FIELDS = ("category", "source")

# HVAC-relevant terms scanned in FAQ entries for synthetic hvac fact
# extraction. This is a Phase 1.3 stopgap — Phase 4 RAG replaces it.
_HVAC_FAQ_TERMS = (
    "thermostat", "ac ", "a/c", "hvac", "air conditioning",
    "heating", "heat pump", "climate", "temperature",
)

_PROPERTY_FACT_INTENTS = {
    "access",
    "house_rules",
    "late_checkout",
    "maintenance",
}

_LOCAL_KNOWLEDGE_INTENTS = {
    "local_recommendation",
}

_NEARBY_AVAILABILITY_INTENTS = {
    "booking_inquiry",
}


def _try_uuid(value: Optional[str]) -> Optional[UUID]:
    if not value:
        return None
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None


def _should_load_lazy_rich_context(intent_topic: str, message_text: str) -> bool:
    topic = str(intent_topic or "").lower()
    return (
        topic in _PROPERTY_FACT_INTENTS
        or topic in _LOCAL_KNOWLEDGE_INTENTS
        or topic in _NEARBY_AVAILABILITY_INTENTS
        or needs_property_facts(message_text)
        or needs_local_knowledge(message_text)
        or needs_nearby_availability(message_text)
    )


def _should_load_lazy_vector_context(intent_topic: str, message_text: str) -> bool:
    topic = str(intent_topic or "").lower()
    return (
        topic in _LOCAL_KNOWLEDGE_INTENTS
        or topic in _NEARBY_AVAILABILITY_INTENTS
        or needs_local_knowledge(message_text)
        or needs_nearby_availability(message_text)
    )


class ContextBuilderAgent:
    """Builds the GuestContextBundle from the brain-owned knowledge path.

    Stateless. Construct once, reuse across requests.
    """

    name = "ContextBuilderAgent"

    def __init__(
        self,
        knowledge_service: Optional[Any] = None,
    ) -> None:
        # Legacy knowledge_service injection is now a compatibility seam
        # for tests only. Production should run without it so the brain
        # cannot tunnel back into concierge_knowledge reads.
        self._knowledge = knowledge_service

    def _use_canonical_runtime_path(self, flag_enabled: bool) -> bool:
        """Prefer canonical/scoped reads unless a test injected legacy seam.

        If a legacy service is explicitly injected, preserve the old
        flag-gated behavior for compatibility tests. Without that seam,
        the runtime must stay on the canonical/scoped path.
        """
        return flag_enabled or self._knowledge is None

    async def _load_rich_context(
        self,
        *,
        tenant_id: str,
        property_code: Optional[str],
        message_text: str,
        intent: str,
        guidebook_knowledge: Dict[str, Any],
        db_session: Any,
        message_id: Optional[str] = None,
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]], str]:
        """Load richness, evidence, and preference block when the flag is on.

        Returns (richness, evidence, preferences_block). Returns
        ({}, [], "") when:
          - db_session is None (flag check requires DB)
          - both flags are off for this tenant/property
          - the rich-context flag check raises (logged at warning)
          - shadow mode is on without rich-context: rich values are
            computed, one observation row is written, and ({}, [], "")
            is returned so production behavior is unchanged

        Single seam for Session 12 shadow rollout.
        """
        if db_session is None:
            return {}, [], ""

        try:
            flag_on = await is_messaging_brain_rich_context_enabled(
                db=db_session,
                tenant_id=tenant_id,
                property_code=property_code,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "rich_context: flag check failed: %s", exc, exc_info=True,
            )
            return {}, [], ""

        shadow_on = False
        if not flag_on and message_id is not None:
            try:
                shadow_on = await is_messaging_brain_rich_context_shadow_enabled(
                    db=db_session,
                    tenant_id=tenant_id,
                    property_code=property_code,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "rich_context: shadow flag check failed: %s",
                    exc,
                    exc_info=True,
                )
                shadow_on = False

        if not flag_on and not shadow_on:
            return {}, [], ""

        legacy_data = to_legacy_prebooking_property_data(
            guidebook_knowledge=guidebook_knowledge,
        )

        richness: Dict[str, Any] = {}
        evidence: List[Dict[str, Any]] = []
        preferences_block = ""
        shadow_exceptions: ShadowExceptions = {}

        try:
            richness = assess_prebooking_knowledge_richness(
                property_data=legacy_data,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "rich_context: richness assessment failed: %s",
                exc,
                exc_info=True,
            )
            richness = {}
            if shadow_on and not flag_on:
                shadow_exceptions["richness"] = build_exception_entry(exc)

        try:
            evidence = retrieve_prebooking_property_evidence(
                message=message_text,
                property_data=legacy_data,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "rich_context: evidence retrieval failed: %s",
                exc,
                exc_info=True,
            )
            evidence = []
            if shadow_on and not flag_on:
                shadow_exceptions["evidence"] = build_exception_entry(exc)

        try:
            preferences_block = await build_preference_context(
                db=db_session,
                company_id=str(tenant_id),
                intent=intent,
                property_external_id=property_code,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("rich_context: preference load skipped: %s", exc)
            preferences_block = ""
            if shadow_on and not flag_on:
                shadow_exceptions["preferences"] = build_exception_entry(exc)

        if shadow_on and not flag_on:
            assert message_id is not None
            await record_rich_context_shadow_observation(
                db_session,
                tenant_id=tenant_id,
                property_code=property_code,
                message_id=message_id,
                intent=intent,
                richness_shadow=richness,
                evidence_shadow=evidence,
                preferences_block_shadow=preferences_block,
                shadow_exceptions=shadow_exceptions,
            )
            return {}, [], ""

        return richness, evidence, preferences_block

    async def _retrieve_vector_chunks(
        self,
        *,
        tenant_id: str,
        property_code: Optional[str],
        query_text: str,
        db_session: Any,
        top_k: int = _VECTOR_TOP_K_DEFAULT,
        min_score: float = _VECTOR_MIN_SCORE_DEFAULT,
    ) -> list[dict[str, Any]]:
        """Retrieve semantically-relevant guidebook chunks for the query."""
        if not query_text or not property_code or db_session is None:
            return []
        try:
            from app.services.knowledge.vector_store import VectorStore

            store = VectorStore(db_session)
            result = await store.similarity_search(
                query=query_text,
                tenant_id=UUID(str(tenant_id)),
                property_code=property_code,
                top_k=top_k,
                min_score=min_score,
            )
            chunks: list[dict[str, Any]] = []
            for doc in result.documents:
                chunks.append(
                    {
                        "type": "vector_chunk",
                        "doc_id": doc.doc_id,
                        "score": float(doc.score or 0.0),
                        "content": (doc.content or "")[:1500],
                        "doc_type": str(doc.metadata.get("doc_type") or ""),
                        "source_type": "vector_guidebook",
                    }
                )
            return chunks
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[ContextBuilderAgent] vector retrieval failed: tenant=%s property=%s error=%s",
                tenant_id,
                property_code,
                exc,
            )
            return []

    # ── Inbound entry ───────────────────────────────────────────────────────

    async def build(
        self,
        message: InboundGuestMessage,
        classification: MessageClassification,
        *,
        db_session: Any,
    ) -> GuestContextBundle:
        """Build the context bundle for an inbound guest message.

        Failure-tolerant: a knowledge load failure produces an empty
        context with `missing_context=["knowledge_load_failed"]` rather
        than raising. Downstream specialists handle empty context by
        emitting cautious drafts and missing_info entries.
        """
        property_facts: dict[str, Any] = {}
        property_knowledge: dict[str, Any] = {}
        guidebook_knowledge: dict[str, Any] = {}
        operator_policies: dict[str, Any] = {}
        reservation_facts: dict[str, Any] = {}
        house_rules: dict[str, Any] = {}
        access_info: dict[str, Any] = {}
        operator_commitments: list[str] = []
        evidence_keys: list[str] = []
        missing_context: list[str] = []
        guidebook_richness: dict[str, Any] = {}
        guidebook_evidence: list[dict[str, Any]] = []
        learned_preferences_block = ""
        operator_guidance = ""

        try:
            tenant_uuid = UUID(message.tenant_id)
        except (ValueError, AttributeError):
            logger.warning(
                "[ContextBuilderAgent] invalid tenant_id %r — empty context",
                message.tenant_id,
            )
            missing_context.append("invalid_tenant_id")
            return self._empty_bundle(
                message, classification, missing_context,
            )

        use_canonical = False
        if db_session is not None:
            try:
                use_canonical = await is_messaging_brain_canonical_kb_read_enabled(
                    db=db_session,
                    tenant_id=message.tenant_id,
                    property_code=message.property_code or None,
                )
            except Exception as exc:  # noqa: BLE001 — fail-open
                logger.warning(
                    "[ContextBuilderAgent] canonical_kb flag check failed: %s",
                    exc,
                    exc_info=True,
                )
                use_canonical = False

        profile = None
        if self._use_canonical_runtime_path(use_canonical) and db_session is not None:
            try:
                profile = await get_canonical_property_service(db_session).build_profile(
                    tenant_id=tenant_uuid,
                    property_code=message.property_code or "",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[ContextBuilderAgent] canonical_profile load failed: %s",
                    exc,
                    exc_info=True,
                )
                missing_context.append(f"canonical_profile_load_failed: {type(exc).__name__}")
                profile = None

        if profile is not None:
            self._merge_canonical_profile(
                profile=profile,
                property_facts=property_facts,
                property_knowledge=property_knowledge,
                guidebook_knowledge=guidebook_knowledge,
                operator_policies_out=operator_policies,
                evidence_keys=evidence_keys,
                missing_context=missing_context,
            )
        else:
            knowledge = None
            if db_session is not None and self._knowledge is not None:
                try:
                    knowledge = await self._knowledge.get_for_property(
                        session=db_session,
                        tenant_id=tenant_uuid,
                        property_id=_try_uuid(message.property_id),
                        property_external_id=message.property_code or None,
                    )
                except Exception as exc:  # noqa: BLE001 — fail-open
                    logger.exception(
                        "[ContextBuilderAgent] knowledge load failed: %s", exc,
                    )
                    missing_context.append(f"knowledge_load_failed: {type(exc).__name__}")

            if knowledge is not None:
                self._extract_facts(
                    knowledge, property_facts, property_knowledge, evidence_keys,
                )
                guidebook_knowledge = extract_guidebook_knowledge(knowledge)
                if guidebook_knowledge:
                    evidence_keys.append("guidebook_knowledge")
            else:
                if "knowledge_load_failed" not in "".join(missing_context):
                    missing_context.append("no_knowledge_for_property")

        self._merge_context_overlay(
            message=message,
            property_facts=property_facts,
            property_knowledge=property_knowledge,
            reservation_facts=reservation_facts,
            house_rules=house_rules,
            access_info=access_info,
            operator_commitments=operator_commitments,
            evidence_keys=evidence_keys,
            missing_context=missing_context,
        )
        identity = getattr(message, "identity", None)
        if identity is not None:
            if getattr(identity, "reservation_id", "") and not reservation_facts.get("reservation_id"):
                reservation_facts["reservation_id"] = str(identity.reservation_id)
                evidence_keys.append("reservation_facts.reservation_id")
            if getattr(identity, "check_in_date", "") and not reservation_facts.get("check_in_date"):
                reservation_facts["check_in_date"] = str(identity.check_in_date)
                evidence_keys.append("reservation_facts.check_in_date")
            if getattr(identity, "check_out_date", "") and not reservation_facts.get("check_out_date"):
                reservation_facts["check_out_date"] = str(identity.check_out_date)
                evidence_keys.append("reservation_facts.check_out_date")

        lazy_context_stage_on = False
        if db_session is not None:
            try:
                lazy_context_stage_on = await is_messaging_brain_lazy_context_stage_enabled(
                    db=db_session,
                    tenant_id=message.tenant_id,
                    property_code=message.property_code or None,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[ContextBuilderAgent] lazy_context_stage flag check failed: %s",
                    exc,
                    exc_info=True,
                )
                lazy_context_stage_on = False

        rich_context_requested = (
            not lazy_context_stage_on
            or _should_load_lazy_rich_context(classification.intent_topic, message.text)
        )
        if rich_context_requested:
            guidebook_richness, guidebook_evidence, learned_preferences_block = (
                await self._load_rich_context(
                    tenant_id=message.tenant_id,
                    property_code=message.property_code or None,
                    message_text=message.text,
                    intent=classification.intent_topic,
                    guidebook_knowledge=guidebook_knowledge,
                    db_session=db_session,
                    message_id=message.message_id,
                )
            )
        if guidebook_richness:
            evidence_keys.append("guidebook_richness")
        if guidebook_evidence:
            evidence_keys.append("guidebook_evidence")
        if learned_preferences_block:
            evidence_keys.append("learned_preferences_block")

        vector_chunks: list[dict[str, Any]] = []
        if db_session is not None:
            vector_runtime_on = False
            vector_shadow_on = False
            try:
                vector_runtime_on = await is_messaging_brain_vector_fallback_enabled(
                    db=db_session,
                    tenant_id=message.tenant_id,
                    property_code=message.property_code or None,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[ContextBuilderAgent] vector_fallback flag check failed: %s",
                    exc,
                    exc_info=True,
                )
            if not vector_runtime_on:
                try:
                    vector_shadow_on = await is_messaging_brain_vector_fallback_shadow_enabled(
                        db=db_session,
                        tenant_id=message.tenant_id,
                        property_code=message.property_code or None,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[ContextBuilderAgent] vector_fallback shadow flag check failed: %s",
                        exc,
                        exc_info=True,
                    )
            vector_context_requested = (
                not lazy_context_stage_on
                or _should_load_lazy_vector_context(classification.intent_topic, message.text)
            )
            if (
                (vector_runtime_on or vector_shadow_on)
                and vector_context_requested
                and (message.property_code or None)
            ):
                retrieved = await self._retrieve_vector_chunks(
                    tenant_id=message.tenant_id,
                    property_code=message.property_code or None,
                    query_text=message.text,
                    db_session=db_session,
                )
                if vector_runtime_on:
                    vector_chunks = retrieved
                elif retrieved:
                    logger.info(
                        "[ContextBuilderAgent] vector_fallback_shadow tenant=%s property=%s chunks=%d top_score=%.3f",
                        message.tenant_id,
                        message.property_code or "",
                        len(retrieved),
                        float(retrieved[0].get("score") or 0.0),
                    )

        if vector_chunks:
            guidebook_evidence.extend(vector_chunks)
            if "guidebook_evidence" not in evidence_keys:
                evidence_keys.append("guidebook_evidence")
            if "vector_retrieval" not in evidence_keys:
                evidence_keys.append("vector_retrieval")
        if db_session is not None:
            try:
                operator_guidance = await load_operator_guidance(
                    tenant_uuid,
                    db_session,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "[ContextBuilderAgent] operator guidance load skipped: %s",
                    exc,
                )
                operator_guidance = ""
        if operator_guidance:
            evidence_keys.append("operator_guidance")

        self._merge_platform_compliance_context(
            property_knowledge=property_knowledge,
            evidence_keys=evidence_keys,
        )

        lifecycle = message.lifecycle or self._lifecycle_from_classification(classification)

        return GuestContextBundle(
            tenant_id=message.tenant_id,
            property_id=message.property_id,
            property_code=message.property_code,
            reservation_id=message.reservation_id,
            guest_id=message.guest_id,
            lifecycle=lifecycle,
            property_facts=property_facts,
            property_knowledge=property_knowledge,
            guidebook_knowledge=guidebook_knowledge,
            guidebook_richness=guidebook_richness,
            guidebook_evidence=guidebook_evidence,
            learned_preferences_block=learned_preferences_block,
            operator_policies=operator_policies,
            operator_guidance=operator_guidance,
            reservation_facts=reservation_facts,  # 1.4+
            house_rules=house_rules,  # 1.4+
            access_info=access_info,  # 1.4+
            maintenance_status={},  # 1.4+
            local_guidebook_facts={},  # 1.4+
            market_signals={},  # 1.4+
            prior_guest_messages=[],  # 1.4+
            operator_commitments=operator_commitments,  # 1.4+
            evidence_keys=evidence_keys,
            missing_context=missing_context,
        )

    # ── Proactive entry ─────────────────────────────────────────────────────

    async def build_for_proactive(
        self,
        intent: OutboundIntent,
        *,
        db_session: Any,
    ) -> GuestContextBundle:
        """Build context for a proactive outbound trigger.

        Same shape as inbound, but built from OutboundIntent.
        Lifecycle is now explicit on the intent when the caller knows it;
        PRE_ARRIVAL remains the safe fallback when it is absent.
        """
        lifecycle = intent.lifecycle or MessagingLifecycle.PRE_ARRIVAL
        property_facts: dict[str, Any] = {}
        property_knowledge: dict[str, Any] = {}
        guidebook_knowledge: dict[str, Any] = {}
        operator_policies: dict[str, Any] = {}
        evidence_keys: list[str] = []
        missing_context: list[str] = []
        guidebook_richness: dict[str, Any] = {}
        guidebook_evidence: list[dict[str, Any]] = []
        learned_preferences_block = ""
        operator_guidance = ""

        try:
            tenant_uuid = UUID(intent.tenant_id)
        except (ValueError, AttributeError):
            return GuestContextBundle(
                tenant_id=intent.tenant_id,
                property_id=intent.property_id,
                property_code=intent.property_code,
                reservation_id=intent.reservation_id,
                guest_id=intent.guest_id,
                lifecycle=lifecycle,
                guidebook_knowledge={},
                guidebook_richness={},
                guidebook_evidence=[],
                learned_preferences_block="",
                operator_policies={},
                evidence_keys=[],
                missing_context=["invalid_tenant_id"],
            )

        use_canonical = False
        if db_session is not None:
            try:
                use_canonical = await is_messaging_brain_canonical_kb_read_enabled(
                    db=db_session,
                    tenant_id=intent.tenant_id,
                    property_code=intent.property_code or None,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[ContextBuilderAgent.proactive] canonical_kb flag check failed: %s",
                    exc,
                    exc_info=True,
                )
                use_canonical = False

        profile = None
        if self._use_canonical_runtime_path(use_canonical) and db_session is not None:
            try:
                profile = await get_canonical_property_service(db_session).build_profile(
                    tenant_id=tenant_uuid,
                    property_code=intent.property_code or "",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[ContextBuilderAgent.proactive] canonical_profile load failed: %s",
                    exc,
                    exc_info=True,
                )
                missing_context.append(f"canonical_profile_load_failed: {type(exc).__name__}")
                profile = None

        if profile is not None:
            self._merge_canonical_profile(
                profile=profile,
                property_facts=property_facts,
                property_knowledge=property_knowledge,
                guidebook_knowledge=guidebook_knowledge,
                operator_policies_out=operator_policies,
                evidence_keys=evidence_keys,
                missing_context=missing_context,
            )
        elif db_session is not None and self._knowledge is not None:
            try:
                knowledge = await self._knowledge.get_for_property(
                    session=db_session,
                    tenant_id=tenant_uuid,
                    property_id=_try_uuid(intent.property_id),
                    property_external_id=intent.property_code or None,
                )
                if knowledge is not None:
                    self._extract_facts(
                        knowledge, property_facts, property_knowledge, evidence_keys,
                    )
                    guidebook_knowledge = extract_guidebook_knowledge(knowledge)
                    if guidebook_knowledge:
                        evidence_keys.append("guidebook_knowledge")
                else:
                    missing_context.append("no_knowledge_for_property")
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "[ContextBuilderAgent.proactive] knowledge load failed: %s", exc,
                )
                missing_context.append(f"knowledge_load_failed: {type(exc).__name__}")

        lazy_context_stage_on = False
        if db_session is not None:
            try:
                lazy_context_stage_on = await is_messaging_brain_lazy_context_stage_enabled(
                    db=db_session,
                    tenant_id=intent.tenant_id,
                    property_code=intent.property_code or None,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[ContextBuilderAgent.proactive] lazy_context_stage flag check failed: %s",
                    exc,
                    exc_info=True,
                )
                lazy_context_stage_on = False

        proactive_query = intent.trigger_type or ""
        rich_context_requested = (
            not lazy_context_stage_on
            or _should_load_lazy_rich_context(intent.trigger_type, proactive_query)
        )
        if rich_context_requested:
            guidebook_richness, guidebook_evidence, learned_preferences_block = (
                await self._load_rich_context(
                    tenant_id=intent.tenant_id,
                    property_code=intent.property_code or None,
                    message_text="",
                    intent=intent.trigger_type,
                    guidebook_knowledge=guidebook_knowledge,
                    db_session=db_session,
                )
            )
        if guidebook_richness:
            evidence_keys.append("guidebook_richness")
        if guidebook_evidence:
            evidence_keys.append("guidebook_evidence")
        if learned_preferences_block:
            evidence_keys.append("learned_preferences_block")

        vector_chunks: list[dict[str, Any]] = []
        if db_session is not None:
            vector_runtime_on = False
            vector_shadow_on = False
            try:
                vector_runtime_on = await is_messaging_brain_vector_fallback_enabled(
                    db=db_session,
                    tenant_id=intent.tenant_id,
                    property_code=intent.property_code or None,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[ContextBuilderAgent.proactive] vector_fallback flag check failed: %s",
                    exc,
                    exc_info=True,
                )
            if not vector_runtime_on:
                try:
                    vector_shadow_on = await is_messaging_brain_vector_fallback_shadow_enabled(
                        db=db_session,
                        tenant_id=intent.tenant_id,
                        property_code=intent.property_code or None,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[ContextBuilderAgent.proactive] vector_fallback shadow flag check failed: %s",
                        exc,
                        exc_info=True,
                    )
            vector_context_requested = (
                not lazy_context_stage_on
                or _should_load_lazy_vector_context(intent.trigger_type, proactive_query)
            )
            if (
                (vector_runtime_on or vector_shadow_on)
                and vector_context_requested
                and (intent.property_code or None)
            ):
                retrieved = await self._retrieve_vector_chunks(
                    tenant_id=intent.tenant_id,
                    property_code=intent.property_code or None,
                    query_text=intent.trigger_type or "",
                    db_session=db_session,
                )
                if vector_runtime_on:
                    vector_chunks = retrieved
                elif retrieved:
                    logger.info(
                        "[ContextBuilderAgent.proactive] vector_fallback_shadow tenant=%s property=%s chunks=%d top_score=%.3f",
                        intent.tenant_id,
                        intent.property_code or "",
                        len(retrieved),
                        float(retrieved[0].get("score") or 0.0),
                    )

        if vector_chunks:
            guidebook_evidence.extend(vector_chunks)
            if "guidebook_evidence" not in evidence_keys:
                evidence_keys.append("guidebook_evidence")
            if "vector_retrieval" not in evidence_keys:
                evidence_keys.append("vector_retrieval")
        if db_session is not None:
            try:
                operator_guidance = await load_operator_guidance(
                    tenant_uuid,
                    db_session,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "[ContextBuilderAgent.proactive] operator guidance load skipped: %s",
                    exc,
                )
                operator_guidance = ""
        if operator_guidance:
            evidence_keys.append("operator_guidance")

        self._merge_platform_compliance_context(
            property_knowledge=property_knowledge,
            evidence_keys=evidence_keys,
        )

        return GuestContextBundle(
            tenant_id=intent.tenant_id,
            property_id=intent.property_id,
            property_code=intent.property_code,
            reservation_id=intent.reservation_id,
            guest_id=intent.guest_id,
            lifecycle=lifecycle,
            property_facts=property_facts,
            property_knowledge=property_knowledge,
            guidebook_knowledge=guidebook_knowledge,
            guidebook_richness=guidebook_richness,
            guidebook_evidence=guidebook_evidence,
            learned_preferences_block=learned_preferences_block,
            operator_policies=operator_policies,
            operator_guidance=operator_guidance,
            evidence_keys=evidence_keys,
            missing_context=missing_context,
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _extract_facts(
        self,
        knowledge: Any,
        property_facts: dict[str, Any],
        property_knowledge: dict[str, Any],
        evidence_keys: list[str],
    ) -> None:
        """Pull facts and FAQ-derived hints out of the knowledge object.

        knowledge can be either:
          - _LegacyKnowledgeCompat (legacy Q&A path; current production)
          - ConciergeKnowledgeModel-shaped row (future JSONB schema)

        Both expose .facts (dict), .faq (list), .sections (dict) — we
        duck-type read them and skip anything missing.
        """
        # 1. Direct facts
        facts = getattr(knowledge, "facts", None) or {}
        if isinstance(facts, dict):
            for key in _KNOWN_FACT_KEYS:
                value = facts.get(key)
                if value:
                    property_facts[key] = value
                    evidence_keys.append(f"property_facts.{key}")

        # 2. FAQ — surface count, full normalized list, and HVAC-relevant
        #    entries as a synthetic fact (Phase 1.3 stopgap; Phase 4 swaps
        #    for RAG). The full list is what downstream specialists
        #    (HouseRulesAgent, AccessAgent) need to ground answers; the
        #    count remains for backward compatibility with consumers that
        #    only used the old summary signal.
        faq = getattr(knowledge, "faq", None) or []
        if isinstance(faq, list) and faq:
            property_knowledge["faq_count"] = len(faq)
            evidence_keys.append("property_knowledge.faq_count")

            normalized_faq = self._normalize_faq_list(faq)
            if normalized_faq:
                property_knowledge["faq"] = normalized_faq
                evidence_keys.append("property_knowledge.faq")

            hvac_hits = self._scan_faq_for_terms(faq, _HVAC_FAQ_TERMS)
            if hvac_hits:
                property_facts["hvac_info"] = hvac_hits[:3]  # cap at 3
                evidence_keys.append("property_facts.hvac_info")

        # 3. Sections (if present in JSONB schema)
        sections = getattr(knowledge, "sections", None) or {}
        if isinstance(sections, dict) and sections:
            property_knowledge["sections_keys"] = sorted(sections.keys())
            evidence_keys.append("property_knowledge.sections_keys")

    def _merge_canonical_profile(
        self,
        *,
        profile: Dict[str, Any],
        property_facts: dict[str, Any],
        property_knowledge: dict[str, Any],
        guidebook_knowledge: dict[str, Any],
        operator_policies_out: dict[str, Any],
        evidence_keys: list[str],
        missing_context: list[str],
    ) -> None:
        """Project a canonical property profile into the bundle surface."""
        fact_fields = (
            ("bedrooms", "bedrooms"),
            ("bathrooms", "bathrooms"),
            ("max_guests", "max_guests"),
            ("beach_access_type", "beach_access_type"),
            ("parking_summary", "parking_summary"),
            ("check_in_time", "check_in_time"),
            ("check_out_time", "check_out_time"),
            ("community_name", "community_name"),
            ("preferred_address", "preferred_address"),
        )
        for source_key, fact_key in fact_fields:
            value = profile.get(source_key)
            if value not in (None, "", False):
                property_facts[fact_key] = value
                if f"property_facts.{fact_key}" not in evidence_keys:
                    evidence_keys.append(f"property_facts.{fact_key}")

        for key in (
            "has_pool",
            "pool_heated",
            "has_hot_tub",
            "has_waterfront",
            "wifi_available",
        ):
            if profile.get(key):
                property_facts[key] = True
                if f"property_facts.{key}" not in evidence_keys:
                    evidence_keys.append(f"property_facts.{key}")

        if profile.get("pet_friendly") is not None:
            property_facts["pet_friendly"] = bool(profile.get("pet_friendly"))
            if "property_facts.pet_friendly" not in evidence_keys:
                evidence_keys.append("property_facts.pet_friendly")

        if profile.get("property_summary"):
            property_knowledge["summary"] = profile["property_summary"]
            if "property_knowledge.summary" not in evidence_keys:
                evidence_keys.append("property_knowledge.summary")
        if profile.get("description"):
            property_knowledge["description"] = profile["description"]
            if "property_knowledge.description" not in evidence_keys:
                evidence_keys.append("property_knowledge.description")

        concierge = profile.get("concierge_knowledge") or {}
        if isinstance(concierge, dict):
            facts = concierge.get("facts") or {}
            sections = concierge.get("sections") or {}
            faq = concierge.get("faq") or []
            property_context = concierge.get("property_context") or {}

            if isinstance(facts, dict) and facts:
                guidebook_knowledge["facts"] = dict(facts)
                for key in ("wifi", "check_in", "check_out", "parking"):
                    if facts.get(key) and key not in property_facts:
                        property_facts[key] = facts[key]
                        if f"property_facts.{key}" not in evidence_keys:
                            evidence_keys.append(f"property_facts.{key}")
            if isinstance(sections, dict) and sections:
                guidebook_knowledge["sections"] = dict(sections)
                property_knowledge["sections_keys"] = sorted(sections.keys())
                property_knowledge["sections"] = dict(sections)
                if "property_knowledge.sections_keys" not in evidence_keys:
                    evidence_keys.append("property_knowledge.sections_keys")
                if "property_knowledge.sections" not in evidence_keys:
                    evidence_keys.append("property_knowledge.sections")
            if isinstance(faq, list) and faq:
                guidebook_knowledge["faq"] = list(faq)
                normalized_faq = self._normalize_faq_list(faq)
                if normalized_faq:
                    property_knowledge["faq"] = normalized_faq
                    property_knowledge["faq_count"] = len(normalized_faq)
                    if "property_knowledge.faq" not in evidence_keys:
                        evidence_keys.append("property_knowledge.faq")
                    if "property_knowledge.faq_count" not in evidence_keys:
                        evidence_keys.append("property_knowledge.faq_count")
            if isinstance(property_context, dict) and property_context:
                property_knowledge["property_context"] = dict(property_context)
                if "property_knowledge.property_context" not in evidence_keys:
                    evidence_keys.append("property_knowledge.property_context")

            if guidebook_knowledge and "guidebook_knowledge" not in evidence_keys:
                evidence_keys.append("guidebook_knowledge")
            if not guidebook_knowledge and "no_canonical_knowledge_for_property" not in missing_context:
                missing_context.append("no_canonical_knowledge_for_property")

        policies = profile.get("operator_policies") or {}
        if isinstance(policies, dict) and policies:
            operator_policies_out.update(policies)
            if not policies.get("_authored", False) and "no_operator_policies_authored" not in missing_context:
                missing_context.append("no_operator_policies_authored")
            for key in policies:
                if key.startswith("_"):
                    continue
                evidence_key = f"operator_policies.{key}"
                if evidence_key not in evidence_keys:
                    evidence_keys.append(evidence_key)

        provenance = profile.get("source_provenance") or {}
        if isinstance(provenance, dict) and provenance:
            property_knowledge["source_provenance"] = dict(provenance)
            if "property_knowledge.source_provenance" not in evidence_keys:
                evidence_keys.append("property_knowledge.source_provenance")

    @staticmethod
    def _merge_platform_compliance_context(
        *,
        property_knowledge: dict[str, Any],
        evidence_keys: list[str],
    ) -> None:
        """Surface platform compliance rules into the evidence contract."""
        property_knowledge["platform_compliance"] = {
            "service_animal": True,
            "esa_case_by_case_review": True,
        }
        for key in (
            "platform_compliance.service_animal",
            "platform_compliance.esa",
        ):
            if key not in evidence_keys:
                evidence_keys.append(key)

    @staticmethod
    def _merge_context_overlay(
        *,
        message: InboundGuestMessage,
        property_facts: dict[str, Any],
        property_knowledge: dict[str, Any],
        reservation_facts: dict[str, Any],
        house_rules: dict[str, Any],
        access_info: dict[str, Any],
        operator_commitments: list[str],
        evidence_keys: list[str],
        missing_context: list[str],
    ) -> None:
        """Merge a provider-supplied context overlay into the bundle.

        The overlay is additive and best-effort. Existing knowledge
        service facts win for overlapping property_facts/property_knowledge
        keys because operator-authored KB remains the canonical source
        for those fields. Newer Phase 2+ surfaces (house_rules,
        access_info, reservation_facts, operator_commitments) are
        merged directly into the output bundle later via metadata.
        """
        overlay = (message.metadata or {}).get("context_adapter_overlay")
        if not isinstance(overlay, dict):
            return

        overlay_property_facts = overlay.get("property_facts") or {}
        if isinstance(overlay_property_facts, dict):
            for key, value in overlay_property_facts.items():
                if key not in property_facts and value not in (None, "", [], {}):
                    property_facts[key] = value

        overlay_property_knowledge = overlay.get("property_knowledge") or {}
        if isinstance(overlay_property_knowledge, dict):
            for key, value in overlay_property_knowledge.items():
                if key not in property_knowledge and value not in (None, "", [], {}):
                    property_knowledge[key] = value

        overlay_reservation_facts = overlay.get("reservation_facts") or {}
        if isinstance(overlay_reservation_facts, dict):
            for key, value in overlay_reservation_facts.items():
                if value not in (None, "", [], {}):
                    reservation_facts[key] = value

        overlay_house_rules = overlay.get("house_rules") or {}
        if isinstance(overlay_house_rules, dict):
            for key, value in overlay_house_rules.items():
                if value not in (None, "", [], {}):
                    house_rules[key] = value

        overlay_access_info = overlay.get("access_info") or {}
        if isinstance(overlay_access_info, dict):
            for key, value in overlay_access_info.items():
                if value not in (None, "", [], {}):
                    access_info[key] = value

        overlay_commitments = overlay.get("operator_commitments") or []
        if isinstance(overlay_commitments, list):
            for item in overlay_commitments:
                if isinstance(item, str) and item and item not in operator_commitments:
                    operator_commitments.append(item)

        overlay_evidence = overlay.get("evidence_keys") or []
        if isinstance(overlay_evidence, list):
            for key in overlay_evidence:
                if isinstance(key, str) and key and key not in evidence_keys:
                    evidence_keys.append(key)

        overlay_missing = overlay.get("missing_context") or []
        if isinstance(overlay_missing, list):
            for item in overlay_missing:
                if isinstance(item, str) and item and item not in missing_context:
                    missing_context.append(item)

    @staticmethod
    def _normalize_faq_list(faq: list) -> list[dict[str, Any]]:
        """Return a sanitized FAQ list suitable for in-context use.

        Each entry is reduced to {question, answer} plus any whitelisted
        passthrough fields (category, source) if present and truthy. Entries
        with empty question or answer are dropped. The list is capped at
        _FAQ_LIST_MAX_ENTRIES and each string is truncated to
        _FAQ_FIELD_MAX_CHARS to bound the size of GuestContextBundle and
        the resulting audit row.

        Order preservation: legacy loader returns FAQ ordered by recency
        (created_at DESC), so the first N entries are the most recent.
        Don't sort or dedupe here — that's the loader's responsibility.
        """
        out: list[dict[str, Any]] = []
        for entry in faq:
            if len(out) >= _FAQ_LIST_MAX_ENTRIES:
                break
            if not isinstance(entry, dict):
                continue
            q_raw = entry.get("question")
            a_raw = entry.get("answer")
            if q_raw is None or a_raw is None:
                continue
            q = str(q_raw).strip()[:_FAQ_FIELD_MAX_CHARS]
            a = str(a_raw).strip()[:_FAQ_FIELD_MAX_CHARS]
            if not q or not a:
                continue
            normalized: dict[str, Any] = {"question": q, "answer": a}
            for field_name in _FAQ_PASSTHROUGH_FIELDS:
                value = entry.get(field_name)
                if value:
                    normalized[field_name] = str(value)[:_FAQ_FIELD_MAX_CHARS]
            out.append(normalized)
        return out

    @staticmethod
    def _scan_faq_for_terms(
        faq: list, terms: tuple[str, ...],
    ) -> list[dict[str, str]]:
        """Return FAQ entries whose question or answer mentions any of `terms`.

        Each returned entry has shape {"question": str, "answer": str}.
        Search is case-insensitive substring.
        """
        out: list[dict[str, str]] = []
        for entry in faq:
            if not isinstance(entry, dict):
                continue
            q = str(entry.get("question") or "")
            a = str(entry.get("answer") or "")
            haystack = f"{q} {a}".lower()
            if any(term in haystack for term in terms):
                out.append({"question": q, "answer": a})
        return out

    @staticmethod
    def _lifecycle_from_classification(
        classification: MessageClassification,
    ) -> MessagingLifecycle:
        """Best-effort lifecycle inference for Phase 1.3.

        SYSTEM_EVENT → SYSTEM. Everything else defaults to IN_STAY since
        guest-initiated messages most commonly come from active stays in
        the AC-slice canary scenarios. Phase 1.4 reads reservation state
        for the real answer.
        """
        if classification.intent_type == IntentType.SYSTEM_EVENT:
            return MessagingLifecycle.SYSTEM
        return MessagingLifecycle.IN_STAY

    @staticmethod
    def _empty_bundle(
        message: InboundGuestMessage,
        classification: MessageClassification,
        missing_context: list[str],
    ) -> GuestContextBundle:
        overlay = (message.metadata or {}).get("context_adapter_overlay")
        reservation_facts = {}
        house_rules = {}
        access_info = {}
        operator_commitments = []
        evidence_keys = []
        if isinstance(overlay, dict):
            reservation_facts = overlay.get("reservation_facts") or {}
            house_rules = overlay.get("house_rules") or {}
            access_info = overlay.get("access_info") or {}
            operator_commitments = overlay.get("operator_commitments") or []
            if isinstance(overlay.get("evidence_keys"), list):
                evidence_keys = [
                    key for key in overlay["evidence_keys"]
                    if isinstance(key, str) and key
                ]
        return GuestContextBundle(
            tenant_id=message.tenant_id,
            property_id=message.property_id,
            property_code=message.property_code,
            reservation_id=message.reservation_id,
            guest_id=message.guest_id,
            lifecycle=message.lifecycle or ContextBuilderAgent._lifecycle_from_classification(classification),
            reservation_facts=reservation_facts,
            house_rules=house_rules,
            access_info=access_info,
            operator_commitments=operator_commitments,
            evidence_keys=evidence_keys,
            missing_context=missing_context,
        )
