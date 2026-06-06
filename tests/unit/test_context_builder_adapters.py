from types import SimpleNamespace

from app.services.messaging_brain.context.property_facts import (
    assess_prebooking_knowledge_richness,
    retrieve_prebooking_property_evidence,
)
from app.services.messaging_brain.agents.context_builder_adapters import (
    extract_guidebook_knowledge,
    to_legacy_prebooking_property_data,
)


def _stub(facts=None, sections=None, faq=None):
    """Stub matching the duck-typed surface (.facts, .sections, .faq)."""
    return SimpleNamespace(facts=facts, sections=sections, faq=faq)


def test_extract_guidebook_knowledge_full_populated():
    k = _stub(
        facts={"check_in_time": "4pm", "wifi_password": "abc123"},
        sections={"parking": "Two spots in driveway.", "pool": "Heated."},
        faq=[{"question": "Pets?", "answer": "No pets allowed."}],
    )
    result = extract_guidebook_knowledge(k)
    assert result == {
        "facts": {"check_in_time": "4pm", "wifi_password": "abc123"},
        "sections": {"parking": "Two spots in driveway.", "pool": "Heated."},
        "faq": [{"question": "Pets?", "answer": "No pets allowed."}],
    }


def test_extract_guidebook_knowledge_facts_only():
    k = _stub(facts={"check_in_time": "4pm"})
    assert extract_guidebook_knowledge(k) == {"facts": {"check_in_time": "4pm"}}


def test_extract_guidebook_knowledge_sections_only():
    k = _stub(sections={"parking": "Two spots."})
    assert extract_guidebook_knowledge(k) == {"sections": {"parking": "Two spots."}}


def test_extract_guidebook_knowledge_faq_only():
    k = _stub(faq=[{"question": "Pets?", "answer": "No."}])
    assert extract_guidebook_knowledge(k) == {
        "faq": [{"question": "Pets?", "answer": "No."}]
    }


def test_extract_guidebook_knowledge_none_input():
    assert extract_guidebook_knowledge(None) == {}


def test_extract_guidebook_knowledge_empty_object_all_attrs_missing():
    k = SimpleNamespace()
    assert extract_guidebook_knowledge(k) == {}


def test_extract_guidebook_knowledge_empty_object_attrs_present_but_empty():
    k = _stub(facts={}, sections={}, faq=[])
    assert extract_guidebook_knowledge(k) == {}


def test_extract_guidebook_knowledge_malformed_facts_is_string():
    k = _stub(facts="not a dict", sections={"a": "b"}, faq=None)
    assert extract_guidebook_knowledge(k) == {"sections": {"a": "b"}}


def test_extract_guidebook_knowledge_malformed_faq_is_dict():
    k = _stub(faq={"not": "a list"})
    assert extract_guidebook_knowledge(k) == {}


def test_extract_guidebook_knowledge_malformed_sections_is_list():
    k = _stub(sections=["not", "a", "dict"])
    assert extract_guidebook_knowledge(k) == {}


def test_extract_guidebook_knowledge_returns_shallow_copy_facts():
    upstream_facts = {"check_in": "4pm"}
    k = _stub(facts=upstream_facts)
    result = extract_guidebook_knowledge(k)
    result["facts"]["check_in"] = "MUTATED"
    assert upstream_facts == {"check_in": "4pm"}


def test_extract_guidebook_knowledge_returns_shallow_copy_faq():
    upstream_faq = [{"question": "Q", "answer": "A"}]
    k = _stub(faq=upstream_faq)
    result = extract_guidebook_knowledge(k)
    result["faq"].append({"question": "X", "answer": "Y"})
    assert len(upstream_faq) == 1


def test_legacy_adapter_full_passthrough():
    gk = {
        "facts": {"check_in_time": "4pm", "wifi_password": "abc123"},
        "sections": {"parking": "Two spots.", "pool": "Heated."},
        "faq": [{"question": "Pets?", "answer": "No."}],
    }
    result = to_legacy_prebooking_property_data(guidebook_knowledge=gk)
    assert result == {
        "concierge_knowledge": {
            "facts": {"check_in_time": "4pm", "wifi_password": "abc123"},
            "sections": {"parking": "Two spots.", "pool": "Heated."},
            "faq": [{"question": "Pets?", "answer": "No."}],
        }
    }


def test_legacy_adapter_empty_input():
    result = to_legacy_prebooking_property_data(guidebook_knowledge={})
    assert result == {"concierge_knowledge": {}}


def test_legacy_adapter_partial_facts_only():
    gk = {"facts": {"check_in_time": "4pm"}}
    result = to_legacy_prebooking_property_data(guidebook_knowledge=gk)
    assert result == {"concierge_knowledge": {"facts": {"check_in_time": "4pm"}}}


def test_legacy_adapter_partial_sections_only():
    gk = {"sections": {"parking": "Two spots."}}
    result = to_legacy_prebooking_property_data(guidebook_knowledge=gk)
    assert result == {"concierge_knowledge": {"sections": {"parking": "Two spots."}}}


def test_legacy_adapter_partial_faq_only():
    gk = {"faq": [{"question": "Q", "answer": "A"}]}
    result = to_legacy_prebooking_property_data(guidebook_knowledge=gk)
    assert result == {"concierge_knowledge": {"faq": [{"question": "Q", "answer": "A"}]}}


def test_legacy_adapter_filters_unexpected_keys():
    gk = {
        "facts": {"check_in": "4pm"},
        "future_field_we_havent_designed_yet": {"some": "data"},
        "another_unexpected": [1, 2, 3],
    }
    result = to_legacy_prebooking_property_data(guidebook_knowledge=gk)
    assert result == {"concierge_knowledge": {"facts": {"check_in": "4pm"}}}
    assert "future_field_we_havent_designed_yet" not in result["concierge_knowledge"]


def test_legacy_adapter_filters_empty_subkeys():
    gk = {"facts": {}, "sections": {}, "faq": []}
    result = to_legacy_prebooking_property_data(guidebook_knowledge=gk)
    assert result == {"concierge_knowledge": {}}


def test_legacy_adapter_filters_malformed_types():
    gk = {
        "facts": "not a dict",
        "sections": ["not", "a", "dict"],
        "faq": {"not": "a list"},
    }
    result = to_legacy_prebooking_property_data(guidebook_knowledge=gk)
    assert result == {"concierge_knowledge": {}}


def test_legacy_adapter_returns_shallow_copy():
    upstream_facts = {"check_in": "4pm"}
    gk = {"facts": upstream_facts}
    result = to_legacy_prebooking_property_data(guidebook_knowledge=gk)
    result["concierge_knowledge"]["facts"]["check_in"] = "MUTATED"
    assert upstream_facts == {"check_in": "4pm"}


def test_shared_richness_consumes_adapter_output_full():
    gk = {
        "facts": {
            "check_in_time": "4pm",
            "check_out_time": "10am",
            "wifi_password": "abc123",
            "address": "123 Beach Rd",
        },
        "sections": {
            "parking": "Two spots in driveway.",
            "pool": "Heated pool, open year-round.",
            "beach_access": "Private path to the beach, 2 minute walk.",
        },
        "faq": [
            {"question": "Are pets allowed?", "answer": "No pets allowed."},
            {"question": "Is there wifi?", "answer": "Yes, password is abc123."},
        ],
    }
    property_data = to_legacy_prebooking_property_data(guidebook_knowledge=gk)
    result = assess_prebooking_knowledge_richness(property_data=property_data)
    assert result["label"] in ("rich", "medium", "sparse")
    assert result["label"] != "none"
    assert 0.0 < result["score"] <= 1.0
    assert "summary" in result


def test_shared_richness_consumes_adapter_output_empty():
    property_data = to_legacy_prebooking_property_data(guidebook_knowledge={})
    result = assess_prebooking_knowledge_richness(property_data=property_data)
    assert result["label"] == "none"
    assert result["score"] == 0.0


def test_shared_evidence_consumes_adapter_output_with_match():
    gk = {
        "facts": {"wifi_password": "abc123"},
        "sections": {"parking": "Two parking spots in the driveway."},
        "faq": [
            {"question": "Is there wifi?", "answer": "Yes, password is abc123."},
        ],
    }
    property_data = to_legacy_prebooking_property_data(guidebook_knowledge=gk)
    hits = retrieve_prebooking_property_evidence(
        message="What is the wifi password?",
        property_data=property_data,
    )
    assert isinstance(hits, list)
    assert any("wifi" in str(hit).lower() or "abc123" in str(hit).lower() for hit in hits)


def test_shared_evidence_consumes_adapter_output_empty():
    property_data = to_legacy_prebooking_property_data(guidebook_knowledge={})
    hits = retrieve_prebooking_property_evidence(
        message="Anything?",
        property_data=property_data,
    )
    assert hits == []


def test_shared_helpers_no_exception_on_partial_adapter_output():
    for partial_gk in [
        {"facts": {"check_in_time": "4pm"}},
        {"sections": {"parking": "Two spots."}},
        {"faq": [{"question": "Q", "answer": "A"}]},
    ]:
        property_data = to_legacy_prebooking_property_data(
            guidebook_knowledge=partial_gk
        )
        richness = assess_prebooking_knowledge_richness(property_data=property_data)
        assert "label" in richness
        evidence = retrieve_prebooking_property_evidence(
            message="anything", property_data=property_data,
        )
        assert isinstance(evidence, list)
