from __future__ import annotations

from app.services.messaging_brain.knowledge.topic_registry import TOPIC_REGISTRY, topic_prompt_catalog
from app.services.messaging_brain.intake.topic_classifier import _heuristic_classify


def test_wifi_access_classifier_matches_typical_content():
    result = _heuristic_classify("What's the wifi password and network name for the internet?")
    assert result.topic_ids
    assert result.topic_ids[0] == "wifi_access"


def test_emergency_contacts_classifier_matches_typical_content():
    result = _heuristic_classify("Who do I call after hours if something breaks? Is there an emergency contact?")
    assert result.topic_ids
    assert result.topic_ids[0] == "emergency_contacts"


def test_trash_disposal_classifier_matches_typical_content():
    result = _heuristic_classify("What day is trash pickup and where is the recycling bin?")
    assert result.topic_ids
    assert result.topic_ids[0] == "trash_disposal"


def test_quiet_hours_classifier_matches_typical_content():
    result = _heuristic_classify("What are the quiet hours? We do not want to violate the noise ordinance.")
    assert result.topic_ids
    assert result.topic_ids[0] == "quiet_hours"


def test_smoking_policy_classifier_matches_typical_content():
    result = _heuristic_classify("Is smoking or vaping allowed on the deck, or is this a non-smoking property?")
    assert result.topic_ids
    assert result.topic_ids[0] == "smoking_policy"


def test_each_new_topic_has_unique_keywords():
    topic_ids = (
        "wifi_access",
        "emergency_contacts",
        "trash_disposal",
        "quiet_hours",
        "smoking_policy",
    )
    seen: dict[str, str] = {}
    for topic_id in topic_ids:
        topic = TOPIC_REGISTRY[topic_id]
        for keyword in topic.keywords:
            normalized = keyword.strip().lower()
            assert seen.get(normalized, topic_id) == topic_id
            seen[normalized] = topic_id


def test_new_topics_appear_in_topic_prompt_catalog():
    catalog = topic_prompt_catalog()
    for topic_id in (
        "wifi_access",
        "emergency_contacts",
        "trash_disposal",
        "quiet_hours",
        "smoking_policy",
    ):
        assert f"- {topic_id}:" in catalog

