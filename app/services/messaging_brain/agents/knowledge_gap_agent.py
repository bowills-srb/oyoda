from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List
from uuid import UUID

from app.services.messaging_brain.knowledge.topic_registry import (
    KnowledgeTopicDefinition,
    expand_legacy_topics,
    get_knowledge_topic,
)
from app.services.messaging_brain.intake.topic_classifier import (
    TopicClassification,
    classify_message_topics,
)
from app.services.orchestration.messaging_brain_contracts import (
    GuestContextBundle,
    MessageClassification,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KnowledgeTopicAssessment:
    topic_id: str
    description: str
    status: str
    answer_source: str = ""
    gap_severity: str = "hold"
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class KnowledgeGapAnalysis:
    topic_classification: TopicClassification
    resolved_topics: List[KnowledgeTopicAssessment] = field(default_factory=list)
    gap_topics: List[KnowledgeTopicAssessment] = field(default_factory=list)
    ambiguity_flags: List[str] = field(default_factory=list)

    @property
    def missing_topic_ids(self) -> List[str]:
        return [topic.topic_id for topic in self.gap_topics if topic.gap_severity == "hold"]


def _nested_lookup(payload: Dict[str, Any], path: str) -> Any:
    current: Any = payload or {}
    for part in (path or "").split("."):
        if not part:
            continue
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def _has_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and value is not None


def _find_tagged_concierge_knowledge(
    *,
    topic: KnowledgeTopicDefinition,
    property_data: Dict[str, Any],
) -> bool:
    knowledge = property_data.get("concierge_knowledge") or {}
    if not isinstance(knowledge, dict):
        return False
    expected_tags = {tag.casefold() for tag in topic.concierge_knowledge_tags}
    if not expected_tags:
        return False
    faq_items = knowledge.get("faq") if isinstance(knowledge.get("faq"), list) else []
    for entry in faq_items:
        if not isinstance(entry, dict):
            continue
        topic_value = str(entry.get("topic") or "").strip().casefold()
        if topic_value and topic_value in expected_tags:
            return True
        tags = entry.get("tags")
        if isinstance(tags, list):
            if expected_tags & {str(tag).strip().casefold() for tag in tags}:
                return True
    return False


def _topic_specific_evidence_hit(
    *,
    topic: KnowledgeTopicDefinition,
    evidence_hits: List[Dict[str, Any]],
) -> bool:
    keywords = {keyword.casefold() for keyword in topic.classifier_keywords}
    for hit in evidence_hits:
        haystack = " ".join(
            str(hit.get(key) or "") for key in ("source", "label", "text")
        ).casefold()
        if any(keyword in haystack for keyword in keywords):
            return True
    return False


def _resolve_structured_topic(
    *,
    topic: KnowledgeTopicDefinition,
    property_data: Dict[str, Any],
    operator_policies: Dict[str, Any],
) -> tuple[bool, str, List[str]]:
    notes: List[str] = []
    if topic.closed_world_rule == "boolean_property":
        value = _nested_lookup(property_data, topic.property_schema_fields[0]) if topic.property_schema_fields else None
        if isinstance(value, bool):
            return True, "property_schema", notes
        return False, "", notes

    if topic.closed_world_rule == "enum_presence":
        value = _nested_lookup(property_data, topic.property_schema_fields[0]) if topic.property_schema_fields else None
        if value is not None and str(value).strip() != "":
            return True, "property_schema", notes
        return False, "", notes

    if topic.closed_world_rule == "text_presence":
        for path in topic.property_schema_fields:
            if _has_text(_nested_lookup(property_data, path)):
                return True, "property_schema", notes
        for path in topic.operator_policy_fields:
            if _has_text(_nested_lookup(operator_policies, path)):
                return True, "operator_policy", notes
        return False, "", notes

    if topic.closed_world_rule == "numeric_property":
        for path in topic.property_schema_fields:
            value = _nested_lookup(property_data, path)
            if _has_number(value):
                return True, "property_schema", notes
        return False, "", notes

    if topic.closed_world_rule == "sleeping_arrangement":
        if _nested_lookup(property_data, "bedrooms") or _nested_lookup(property_data, "max_guests"):
            return True, "property_schema", notes
        return False, "", notes

    if topic.closed_world_rule == "max_occupancy":
        if _nested_lookup(property_data, "max_guests") or _nested_lookup(property_data, "bedrooms"):
            return True, "property_schema", notes
        return False, "", notes

    if topic.closed_world_rule == "pool_heat_capability":
        has_pool = _nested_lookup(property_data, "has_pool")
        pool_heated = _nested_lookup(property_data, "pool_heated")
        policy_available = _nested_lookup(operator_policies, "pool_heat.available")
        if has_pool is False:
            notes.append("no_pool_present")
            return True, "property_schema", notes
        if isinstance(policy_available, bool):
            if not policy_available:
                notes.append("pool_heat_policy_not_available")
            return True, "operator_policy", notes
        if isinstance(pool_heated, bool):
            if not pool_heated:
                notes.append("pool_not_heated")
            return True, "property_schema", notes
        return False, "", notes

    if topic.closed_world_rule in {"pool_heat_cost", "pool_heat_notice"}:
        has_pool = _nested_lookup(property_data, "has_pool")
        pool_heated = _nested_lookup(property_data, "pool_heated")
        policy_available = _nested_lookup(operator_policies, "pool_heat.available")
        available = None
        if has_pool is False:
            notes.append("no_pool_present")
            available = False
        elif isinstance(policy_available, bool):
            available = policy_available
        elif isinstance(pool_heated, bool):
            available = pool_heated
        if available is False:
            notes.append("negative_closure")
            return True, "negative_closure", notes
        field_name = "pool_heat.daily_fee" if topic.topic_id == "pool_heating_cost" else "pool_heat.advance_notice_hours"
        field_value = _nested_lookup(operator_policies, field_name)
        if field_value not in (None, "", []):
            return True, "operator_policy", notes
        return False, "", notes

    if topic.closed_world_rule == "pet_policy":
        pet_friendly = _nested_lookup(property_data, "pet_friendly")
        policy = _nested_lookup(operator_policies, "pet_policy")
        if isinstance(pet_friendly, bool):
            return True, "property_schema", notes
        if _has_text(policy):
            return True, "operator_policy", notes
        return False, "", notes

    if topic.closed_world_rule == "pet_fee":
        pet_friendly = _nested_lookup(property_data, "pet_friendly")
        policy = str(_nested_lookup(operator_policies, "pet_policy") or "").strip().lower()
        if pet_friendly is False or policy in {"not_allowed", "denied", "forbidden"}:
            notes.append("negative_closure")
            return True, "negative_closure", notes
        fee = _nested_lookup(operator_policies, "pet_fee")
        if fee not in (None, "", []):
            return True, "operator_policy", notes
        return False, "", notes

    if topic.closed_world_rule == "check_in_process":
        if _has_text(_nested_lookup(property_data, "check_in_time")) or _has_text(_nested_lookup(operator_policies, "check_in_time")):
            return True, "property_schema", notes
        return False, "", notes

    if topic.closed_world_rule == "early_check_in":
        allowed = _nested_lookup(operator_policies, "early_checkin.allowed")
        earliest = _nested_lookup(operator_policies, "early_checkin.earliest")
        fee = _nested_lookup(operator_policies, "early_checkin_fee")
        if isinstance(allowed, bool):
            return True, "operator_policy", notes
        if earliest not in (None, "", []) or fee not in (None, "", []):
            return True, "operator_policy", notes
        return False, "", notes

    if topic.closed_world_rule == "late_check_out":
        allowed = _nested_lookup(operator_policies, "late_checkout.allowed")
        latest = _nested_lookup(operator_policies, "late_checkout.max_time")
        fee = _nested_lookup(operator_policies, "late_checkout_fee")
        if isinstance(allowed, bool):
            return True, "operator_policy", notes
        if latest not in (None, "", []) or fee not in (None, "", []):
            return True, "operator_policy", notes
        return False, "", notes

    if topic.closed_world_rule == "cancellation_policy":
        for path in topic.operator_policy_fields:
            if _nested_lookup(operator_policies, path) not in (None, "", []):
                return True, "operator_policy", notes
        return False, "", notes

    return False, "", notes


class KnowledgeGapAgent:
    async def analyze(
        self,
        *,
        message: str,
        classification: MessageClassification,
        context: GuestContextBundle,
    ) -> KnowledgeGapAnalysis:
        try:
            company_id: UUID | None = UUID(context.tenant_id)
        except (ValueError, TypeError):
            company_id = None

        classified = await classify_message_topics(message, tenant_id=company_id)
        topic_ids = list(classified.topic_ids)
        if not topic_ids:
            intent = classification.intent_topic or ""
            if intent and intent != "general":
                topic_ids.extend(expand_legacy_topics([intent]))
        topic_ids = list(dict.fromkeys(topic_ids))

        # Build the flat property_data dict the closed-world rules expect,
        # sourced from the typed GuestContextBundle. This replaces the old
        # flat-dict parameter.
        property_data: Dict[str, Any] = {
            **context.property_facts,
            **context.house_rules,
            **context.access_info,
            "concierge_knowledge": context.property_knowledge,
        }
        operator_policies: Dict[str, Any] = dict(context.operator_policies)

        # Use pre-computed evidence from ContextBuilderAgent. The legacy
        # retrieve_prebooking_property_evidence call is retired here; the
        # ContextBuilder now owns evidence retrieval so the gate reads from
        # the bundle rather than re-computing.
        evidence_hits: List[Dict[str, Any]] = list(context.guidebook_evidence)

        resolved: List[KnowledgeTopicAssessment] = []
        missing: List[KnowledgeTopicAssessment] = []
        ambiguities: List[str] = []
        source_provenance = property_data.get("source_provenance") if isinstance(property_data, dict) else {}
        retrieval_source = ""
        if isinstance(source_provenance, dict):
            retrieval_source = str(source_provenance.get("concierge_knowledge_retrieval_source") or "").strip()

        for topic_id in topic_ids:
            topic = get_knowledge_topic(topic_id)
            if topic is None:
                continue
            answered, answer_source, notes = _resolve_structured_topic(
                topic=topic,
                property_data=property_data or {},
                operator_policies=operator_policies or {},
            )
            if answered:
                logger.info(
                    "[KnowledgeGap] topic=%s status=resolved resolved_via=%s retrieval_source=%s",
                    topic.topic_id,
                    answer_source or "structured",
                    retrieval_source or "unknown",
                )
                resolved.append(
                    KnowledgeTopicAssessment(
                        topic_id=topic.topic_id,
                        description=topic.description,
                        status="resolved",
                        answer_source=answer_source,
                        gap_severity=topic.gap_severity,
                        notes=notes,
                    )
                )
                continue

            tagged_match = _find_tagged_concierge_knowledge(topic=topic, property_data=property_data or {})
            evidence_match = _topic_specific_evidence_hit(
                topic=topic,
                evidence_hits=evidence_hits,
            )
            if tagged_match or evidence_match:
                resolved_via = "tagged_faq" if tagged_match else "evidence_hit"
                logger.info(
                    "[KnowledgeGap] topic=%s status=resolved resolved_via=%s retrieval_source=%s",
                    topic.topic_id,
                    resolved_via,
                    retrieval_source or "unknown",
                )
                resolved.append(
                    KnowledgeTopicAssessment(
                        topic_id=topic.topic_id,
                        description=topic.description,
                        status="resolved",
                        answer_source="concierge_knowledge",
                        gap_severity=topic.gap_severity,
                        notes=notes,
                    )
                )
                continue

            logger.info(
                "[KnowledgeGap] topic=%s status=gap retrieval_source=%s",
                topic.topic_id,
                retrieval_source or "unknown",
            )
            missing.append(
                KnowledgeTopicAssessment(
                    topic_id=topic.topic_id,
                    description=topic.description,
                    status="gap",
                    answer_source="",
                    gap_severity=topic.gap_severity,
                    notes=notes,
                )
            )

        return KnowledgeGapAnalysis(
            topic_classification=classified,
            resolved_topics=resolved,
            gap_topics=missing,
            ambiguity_flags=ambiguities,
        )
