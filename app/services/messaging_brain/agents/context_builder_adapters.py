from __future__ import annotations

from typing import Any, Dict


def extract_guidebook_knowledge(knowledge: Any) -> Dict[str, Any]:
    """Retain full facts/sections/faq from upstream knowledge object.

    Duck-types both _LegacyKnowledgeCompat and ConciergeKnowledgeModel
    shapes; both expose .facts (dict), .sections (dict), .faq (list).
    Returns a normalized dict shaped for downstream consumption by
    the legacy-shape adapter, richness scoring, and evidence retrieval.

    Empty dict means "knowledge object was None or had no retainable
    content"; callers treat empty as "nothing to score" rather than
    as an error condition.

    Shallow copies are made at the boundary so downstream mutation
    cannot leak back into upstream service state.

    FAQ entries are retained raw (not normalized). The brain's
    property_knowledge["faq"] slot holds the normalized/trimmed view
    consumed by other agents; this field is the raw retained source
    for the legacy-shaped adapter and the shared concierge helpers,
    which read entry["question"] and entry["answer"] directly.
    """
    if knowledge is None:
        return {}

    result: Dict[str, Any] = {}

    facts = getattr(knowledge, "facts", None)
    if isinstance(facts, dict) and facts:
        result["facts"] = dict(facts)

    sections = getattr(knowledge, "sections", None)
    if isinstance(sections, dict) and sections:
        result["sections"] = dict(sections)

    faq = getattr(knowledge, "faq", None)
    if isinstance(faq, list) and faq:
        result["faq"] = list(faq)

    return result


def to_legacy_prebooking_property_data(
    *,
    guidebook_knowledge: Dict[str, Any],
) -> Dict[str, Any]:
    """Adapt brain's guidebook_knowledge into the shape the shared
    concierge helpers expect.

    Target consumers (do not add other keys without updating both):
      - app.services.messaging_brain.context.property_facts.assess_prebooking_knowledge_richness
      - app.services.messaging_brain.context.property_facts.retrieve_prebooking_property_evidence

    Both read property_data["concierge_knowledge"] and look for
    "facts" (dict), "sections" (dict), "faq" (list). This adapter
    explicitly allowlists those three keys; future fields in
    guidebook_knowledge do not silently become part of the legacy
    contract.

    Empty input produces {"concierge_knowledge": {}}, which the shared
    helpers handle (richness returns label="none", evidence returns []).
    """
    concierge_knowledge: Dict[str, Any] = {}

    facts = guidebook_knowledge.get("facts")
    if isinstance(facts, dict) and facts:
        concierge_knowledge["facts"] = dict(facts)

    sections = guidebook_knowledge.get("sections")
    if isinstance(sections, dict) and sections:
        concierge_knowledge["sections"] = dict(sections)

    faq = guidebook_knowledge.get("faq")
    if isinstance(faq, list) and faq:
        concierge_knowledge["faq"] = list(faq)

    return {"concierge_knowledge": concierge_knowledge}
