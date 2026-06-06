from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.messaging_brain.knowledge.scoped_knowledge_service import (
    get_scoped_knowledge_service,
    project_to_legacy_concierge_knowledge_shape,
)
from app.services.messaging_brain.knowledge.faq_answering import score_faq_match
from app.services.messaging_brain.knowledge.global_faq import list_global_faq


@dataclass(frozen=True)
class PropertyKnowledgeBundle:
    property_profile: Dict[str, Any]
    concierge_knowledge: Dict[str, Any]
    property_context: Dict[str, Any]
    sections: Dict[str, Any]


def _default_property_profile() -> Dict[str, Any]:
    return {
        "operational_constraints": {
            "check_in_time": "4:00 PM",
            "check_out_time": "11:00 AM",
            "late_checkout_available": True,
        },
        "access": {
            "wifi_network": "PropertyWiFi",
            "wifi_password": "welcome123",
        },
        "concierge_knowledge": {},
    }


def _build_property_profile(concierge_knowledge: Dict[str, Any]) -> Dict[str, Any]:
    profile = _default_property_profile()
    facts = concierge_knowledge.get("facts") if isinstance(concierge_knowledge, dict) else {}
    facts = facts if isinstance(facts, dict) else {}
    sections = concierge_knowledge.get("sections") if isinstance(concierge_knowledge, dict) else {}
    sections = sections if isinstance(sections, dict) else {}
    faq = concierge_knowledge.get("faq") if isinstance(concierge_knowledge, dict) else []
    faq = faq if isinstance(faq, list) else []

    if facts.get("check_in"):
        profile["operational_constraints"]["check_in_time"] = str(facts["check_in"])
    if facts.get("check_out"):
        profile["operational_constraints"]["check_out_time"] = str(facts["check_out"])
    if facts.get("wifi"):
        profile["access"]["wifi_password"] = str(facts["wifi"])

    profile["concierge_knowledge"] = {
        "facts": facts,
        "sections": sections,
        "faq": faq,
    }
    return profile


async def load_property_knowledge_bundle(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    property_id: UUID,
) -> PropertyKnowledgeBundle:
    service = get_scoped_knowledge_service()
    effective = await service.get_effective_knowledge_for_property(
        session=session,
        tenant_id=tenant_id,
        property_id=property_id,
    )
    concierge_knowledge = project_to_legacy_concierge_knowledge_shape(effective)
    return PropertyKnowledgeBundle(
        property_profile=_build_property_profile(concierge_knowledge),
        concierge_knowledge=concierge_knowledge,
        property_context={},
        sections={},
    )


async def resolve_property_id_by_code(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    property_code: str,
) -> Optional[UUID]:
    code = str(property_code or "").strip()
    if not code:
        return None
    row = (
        await session.execute(
            text(
                """
                SELECT id::text AS property_id
                FROM properties
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND (
                        property_code = :code
                     OR external_id = :code
                  )
                ORDER BY updated_at DESC NULLS LAST, id
                LIMIT 1
                """
            ),
            {"tenant_id": str(tenant_id), "code": code},
        )
    ).mappings().first()
    if not row or not row.get("property_id"):
        return None
    return UUID(str(row["property_id"]))


async def best_faq_answer_with_global(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    message_text: str,
    concierge_knowledge: Dict[str, Any],
) -> Dict[str, Any]:
    faq = concierge_knowledge.get("faq") if isinstance(concierge_knowledge, dict) else []
    faq = faq if isinstance(faq, list) else []
    local_match, local_score = score_faq_match(message_text, faq)
    if local_match:
        return {
            "answer": local_match["answer"],
            "match_type": "property_faq",
            "score": local_score,
            "source_property_external_id": None,
            "question": local_match["question"],
        }

    global_faq = await list_global_faq(session=session, tenant_id=tenant_id, limit=300)
    global_match, global_score = score_faq_match(
        message_text,
        [
            {
                "question": item["question_text"],
                "answer": item["answer_text"],
                "source": item.get("source", "global_faq"),
            }
            for item in global_faq
        ],
    )
    if global_match and global_score >= 0.52:
        return {
            "answer": global_match["answer"],
            "match_type": "global_faq",
            "score": global_score,
            "source_property_external_id": None,
            "question": global_match["question"],
        }

    return {
        "answer": None,
        "match_type": None,
        "score": 0.0,
        "source_property_external_id": None,
        "question": None,
    }
