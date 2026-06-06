from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def _tokenize_context_text(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", (value or "").lower())
        if token not in {"with", "that", "this", "from", "have", "your", "about"}
    }


def assess_prebooking_knowledge_richness(
    *,
    property_data: Dict[str, Any],
) -> Dict[str, Any]:
    knowledge = property_data.get("concierge_knowledge") or {}
    if not isinstance(knowledge, dict):
        return {"score": 0.0, "label": "none", "summary": "No structured guidebook knowledge available."}

    facts = knowledge.get("facts") if isinstance(knowledge.get("facts"), dict) else {}
    sections = knowledge.get("sections") if isinstance(knowledge.get("sections"), dict) else {}
    faq = knowledge.get("faq") if isinstance(knowledge.get("faq"), list) else []

    fact_count = sum(1 for value in facts.values() if str(value or "").strip())
    section_count = sum(1 for value in sections.values() if str(value or "").strip())
    faq_count = sum(
        1
        for entry in faq
        if isinstance(entry, dict)
        and str(entry.get("question") or "").strip()
        and str(entry.get("answer") or "").strip()
    )
    text_volume = sum(len(str(value or "").strip()) for value in facts.values())
    text_volume += sum(len(str(value or "").strip()) for value in sections.values())

    score = min(
        1.0,
        (fact_count * 0.08)
        + (section_count * 0.1)
        + (faq_count * 0.03)
        + min(text_volume / 4000.0, 0.35),
    )
    if score >= 0.75:
        label = "rich"
    elif score >= 0.4:
        label = "medium"
    elif score > 0:
        label = "sparse"
    else:
        label = "none"

    summary = (
        f"Guidebook richness: {label} "
        f"(facts={fact_count}, sections={section_count}, faq={faq_count}, text={text_volume})"
    )
    return {
        "score": round(score, 2),
        "label": label,
        "summary": summary,
    }


def _select_relevant_faq_items(
    *,
    message: str,
    faq_items: list[dict[str, Any]],
    limit: int = 2,
) -> list[dict[str, Any]]:
    message_tokens = _tokenize_context_text(message)
    if not message_tokens or not faq_items:
        return []

    ranked: list[tuple[int, dict[str, Any]]] = []
    for item in faq_items:
        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if not question or not answer:
            continue
        overlap = len(message_tokens & _tokenize_context_text(question))
        if overlap <= 0:
            continue
        ranked.append((overlap, item))

    ranked.sort(key=lambda pair: (-pair[0], str(pair[1].get("question") or "")))
    return [item for _, item in ranked[: max(1, limit)]]


def retrieve_prebooking_property_evidence(
    *,
    message: str,
    property_data: Dict[str, Any],
    limit: int = 8,
) -> list[dict[str, Any]]:
    message_tokens = _tokenize_context_text(message)
    if not message_tokens:
        return []

    candidates: list[tuple[int, dict[str, Any]]] = []

    ignored_top_level = {
        "source_provenance",
        "operator_policies",
    }
    ignored_leaf_keys = {
        "source",
        "guidebook_url",
        "raw_text_length",
        "score",
        "confidence",
    }

    def add_candidate(source: str, label: str, text: str) -> None:
        cleaned = str(text or "").strip()
        if not cleaned:
            return
        overlap = len(message_tokens & _tokenize_context_text(f"{label} {cleaned}"))
        if overlap <= 0:
            return
        candidates.append(
            (
                overlap,
                {
                    "source": source,
                    "label": label,
                    "text": cleaned,
                    "score": overlap,
                },
            )
        )

    def walk(value: Any, *, source: str, path: str = "") -> None:
        if value in (None, "", [], {}):
            return
        if isinstance(value, dict):
            for raw_key, raw_child in value.items():
                key = str(raw_key or "").strip()
                if not key or key in ignored_leaf_keys:
                    continue
                child_path = f"{path}.{key}" if path else key
                walk(raw_child, source=source, path=child_path)
            return
        if isinstance(value, (list, tuple)):
            for idx, item in enumerate(value):
                walk(item, source=source, path=f"{path}[{idx}]")
            return
        add_candidate(source, path or "value", str(value))

    for key in (
        "property_summary",
        "description",
        "community_name",
        "beach_access_type",
        "parking_summary",
        "check_in_time",
        "check_out_time",
        "preferred_address",
    ):
        value = property_data.get(key)
        if value not in (None, "", [], {}):
            add_candidate("property_data", key, str(value))

    knowledge = property_data.get("concierge_knowledge") or {}
    if isinstance(knowledge, dict):
        facts = knowledge.get("facts") if isinstance(knowledge.get("facts"), dict) else {}
        sections = knowledge.get("sections") if isinstance(knowledge.get("sections"), dict) else {}
        faq_items = knowledge.get("faq") if isinstance(knowledge.get("faq"), list) else []

        for key, value in facts.items():
            add_candidate("guidebook_fact", str(key), str(value))
        for key, value in sections.items():
            add_candidate("guidebook_section", str(key), str(value))
        for entry in faq_items:
            if not isinstance(entry, dict):
                continue
            question = str(entry.get("question") or "").strip()
            answer = str(entry.get("answer") or "").strip()
            if question and answer:
                add_candidate("faq", question, answer)

    for top_key, top_value in property_data.items():
        if top_key in ignored_top_level or top_key == "concierge_knowledge":
            continue
        walk(top_value, source="property_profile", path=str(top_key))

    candidates.sort(key=lambda item: (-item[0], item[1]["label"]))
    deduped: list[dict[str, Any]] = []
    seen = set()
    for _, item in candidates:
        fingerprint = (item["source"], item["label"].casefold(), item["text"].casefold())
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(item)
        if len(deduped) >= max(1, limit):
            break
    return deduped


def _select_relevant_mapping_items(
    *,
    message: str,
    mapping: dict[str, Any],
    limit: int = 3,
) -> list[tuple[str, str]]:
    message_tokens = _tokenize_context_text(message)
    if not message_tokens or not mapping:
        return []

    ranked: list[tuple[int, str, str]] = []
    for raw_key, raw_value in mapping.items():
        key = str(raw_key or "").strip()
        value = str(raw_value or "").strip()
        if not key or not value:
            continue
        candidate_tokens = _tokenize_context_text(f"{key} {value}")
        overlap = len(message_tokens & candidate_tokens)
        if overlap <= 0:
            continue
        ranked.append((overlap, key, value))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [(key, value) for _, key, value in ranked[: max(1, limit)]]


def build_prebooking_knowledge_lines(
    *,
    message: str,
    intent: str,
    property_data: Dict[str, Any],
) -> list[str]:
    """Render the most relevant property/KB snippets for pre-booking prompts."""
    knowledge = property_data.get("concierge_knowledge") or {}
    if not isinstance(knowledge, dict):
        return []

    facts = knowledge.get("facts") if isinstance(knowledge.get("facts"), dict) else {}
    sections = knowledge.get("sections") if isinstance(knowledge.get("sections"), dict) else {}
    property_context = (
        knowledge.get("property_context")
        if isinstance(knowledge.get("property_context"), dict)
        else {}
    )
    faq_items = knowledge.get("faq") if isinstance(knowledge.get("faq"), list) else []
    richness = assess_prebooking_knowledge_richness(property_data=property_data)

    lines: list[str] = []
    headline = str(property_context.get("headline") or "").strip()
    overview = str(sections.get("overview") or "").strip()
    location = str(sections.get("location") or sections.get("area") or "").strip()

    if headline:
        lines.append(f"Property headline: {headline[:180]}")
    if not property_data.get("property_summary") and overview:
        lines.append(f"Overview: {overview[:220]}")
    elif overview and intent in {"local_area", "amenities", "group_size", "general"}:
        lines.append(f"Overview: {overview[:220]}")
    if location and intent in {"local_area", "beach_access", "amenities"}:
        lines.append(f"Area notes: {location[:180]}")

    intent_fact_keys = {
        "amenities": ("wifi", "parking", "pool", "hot_tub", "beach_access"),
        "local_area": ("beach_access", "walkability", "location", "distance_to_beach", "nearby"),
        "group_size": ("occupancy", "bedrooms", "sleeping_arrangements"),
        "check_in_process": ("check_in", "check_out", "arrival"),
        "pet_policy": ("pets", "pet_policy"),
    }
    for key in intent_fact_keys.get(intent, ()):
        value = str(facts.get(key) or "").strip()
        if value:
            lines.append(f"{key.replace('_', ' ').title()}: {value[:180]}")

    for hit in retrieve_prebooking_property_evidence(
        message=message,
        property_data=property_data,
        limit=6,
    ):
        source = hit["source"]
        label = str(hit["label"]).replace("_", " ").title()
        text = str(hit["text"])
        if source == "faq":
            lines.append(f"FAQ match — {label}: {text[:220]}")
        elif source == "guidebook_fact":
            lines.append(f"Guidebook fact — {label}: {text[:220]}")
        elif source == "guidebook_section":
            lines.append(f"Guidebook section — {label}: {text[:220]}")
        else:
            lines.append(f"Property detail — {label}: {text[:220]}")
    if richness["label"] != "none":
        lines.append(richness["summary"])

    deduped: list[str] = []
    seen = set()
    for line in lines:
        normalized = line.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(line)
    return deduped[:8]


def build_property_facts_lines(property_facts: Dict[str, Any]) -> List[str]:
    """Render compact property facts for concierge prompts."""
    if not property_facts:
        return []

    facts_lines: List[str] = []
    if property_facts.get("wifi_network"):
        facts_lines.append(
            f"WiFi: {property_facts['wifi_network']} / {property_facts.get('wifi_password', '')}".rstrip(" /")
        )
    if property_facts.get("check_in_time"):
        facts_lines.append(
            f"Check-in: {property_facts['check_in_time']} | Check-out: {property_facts.get('check_out_time', 'see guide')}"
        )
    if property_facts.get("has_pool"):
        facts_lines.append(
            f"Pool: yes {'(heated)' if property_facts.get('pool_heated') else '(unheated)'}"
        )
    if property_facts.get("has_bikes") and property_facts.get("bike_count", 0) > 0:
        facts_lines.append(f"Bikes: {property_facts['bike_count']} available")
    return facts_lines


def build_grounding_context(
    property_facts: Dict[str, Any],
    retrieved_context: str,
    *,
    extras: Optional[Dict[str, Any]] = None,
) -> str:
    """Flatten facts, retrieved KB, and optional extras into one grounding context."""
    parts: List[str] = []
    if property_facts:
        for key, value in property_facts.items():
            if value in (None, "", [], {}):
                continue
            if isinstance(value, (list, tuple)):
                value = ", ".join(str(item) for item in value if item not in (None, ""))
            parts.append(f"{key}: {value}")
    if retrieved_context:
        parts.append(retrieved_context)
    if extras:
        for key, value in extras.items():
            if value in (None, "", [], {}):
                continue
            parts.append(f"{key}: {value}")
    return "\n".join(parts)
