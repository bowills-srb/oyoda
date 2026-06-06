from __future__ import annotations

import re
from typing import Any, Dict


def _extract_golf_cart_grounding_markers(
    property_data: Dict[str, Any],
    operator_policies: Dict[str, Any],
) -> Dict[str, str]:
    markers: Dict[str, str] = {}
    knowledge = property_data.get("concierge_knowledge") or {}
    facts = knowledge.get("facts") if isinstance(knowledge, dict) else {}
    faq = knowledge.get("faq") if isinstance(knowledge, dict) else []
    blob_parts = [
        str(property_data.get("property_summary") or ""),
        str(property_data.get("description") or ""),
        str(property_data.get("parking_summary") or ""),
        str(operator_policies.get("golf_cart_policy") or ""),
        str(facts.get("golf_cart") or "") if isinstance(facts, dict) else "",
        str(facts.get("transportation") or "") if isinstance(facts, dict) else "",
    ]
    if isinstance(faq, list):
        for item in faq[:12]:
            if isinstance(item, dict):
                blob_parts.append(str(item.get("question") or ""))
                blob_parts.append(str(item.get("answer") or ""))
    blob = "\n".join(part for part in blob_parts if part).lower()

    if re.search(r"\bgolf cart\b", blob):
        if re.search(r"\b(?:includes?|included|comes with)\b.*\bgolf cart\b|\bgolf cart\b.*\b(?:includes?|included|comes with)\b", blob):
            markers["grounded_golf_cart_included"] = "included"
        elif re.search(r"\b(?:no|not|doesn['']?t|does not)\b.*\bgolf cart\b|\bgolf cart\b.*\b(?:not included|not available)\b", blob):
            markers["grounded_golf_cart_included"] = "not_included"

        if re.search(r"\b(?:golf carts?|golf cart usage)\b.*\b(?:not allowed|prohibited|forbidden)\b|\bno golf carts? allowed\b", blob):
            markers["grounded_golf_cart_policy"] = "not_allowed"
        elif re.search(r"\b(?:golf carts?|golf cart usage)\b.*\ballowed\b|\bbring your own golf cart\b", blob):
            markers["grounded_golf_cart_policy"] = "allowed"

        size_match = re.search(r"\b([46]|four|six)\s*[- ]?(?:seater|seat)\b", blob)
        if size_match:
            markers["grounded_golf_cart_size"] = size_match.group(1)

    return markers


def _build_prebooking_grounding_context(
    *,
    guest_name: str,
    platform: str,
    message: str,
    intent: str,
    property_data: Dict[str, Any],
    operator_policies: Dict[str, Any],
) -> str:
    from app.services.messaging_brain.context.property_facts import (
        assess_prebooking_knowledge_richness,
    )

    parts = [
        f"guest_name: {guest_name}",
        f"platform: {platform}",
        f"message: {message}",
        f"intent: {intent}",
    ]
    for key, value in property_data.items():
        if value in (None, "", [], {}):
            continue
        parts.append(f"{key}: {value}")
    for key, value in operator_policies.items():
        if value in (None, "", [], {}):
            continue
        parts.append(f"policy_{key}: {value}")
    for key, value in _extract_golf_cart_grounding_markers(
        property_data,
        operator_policies,
    ).items():
        if value:
            parts.append(f"{key}: {value}")
    richness = assess_prebooking_knowledge_richness(property_data=property_data)
    if richness["label"] != "none":
        parts.append(f"guidebook_richness_label: {richness['label']}")
        parts.append(f"guidebook_richness_score: {richness['score']}")
        parts.append(f"guidebook_richness_summary: {richness['summary']}")
    if platform == "direct":
        parts.append("grounded_direct_booking_channel: true")
    return "\n".join(parts)
