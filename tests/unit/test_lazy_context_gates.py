from app.services.messaging_brain.context.lazy_context_gates import (
    needs_local_knowledge,
    needs_nearby_availability,
    needs_property_facts,
)


def test_needs_property_facts_matches_operational_question() -> None:
    assert needs_property_facts("What's the wifi password and door code?")


def test_needs_property_facts_ignores_generic_greeting() -> None:
    assert not needs_property_facts("Hi there, just saying hello.")


def test_needs_nearby_availability_requires_people_and_inventory_signal() -> None:
    assert needs_nearby_availability(
        "Our friends are coming too. Is there another place nearby they can book?"
    )


def test_needs_nearby_availability_rejects_people_without_search_signal() -> None:
    assert not needs_nearby_availability("We are traveling with friends this year.")


def test_needs_local_knowledge_matches_recommendation_question() -> None:
    assert needs_local_knowledge("Any good seafood restaurants nearby?")


def test_needs_local_knowledge_ignores_non_local_question() -> None:
    assert not needs_local_knowledge("Can we check in a little early?")
