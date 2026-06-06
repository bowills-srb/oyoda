from __future__ import annotations

import asyncio

from app.services.concierge import topic_classifier


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"topics":['
                                '{"topic_id":"pool_heating_capability","confidence":0.95,"rationale":"asks if pool is heated"},'
                                '{"topic_id":"pool_heating_cost","confidence":0.9,"rationale":"asks about heating cost"}'
                                ']}'
                            )
                        }
                    }
                ]
            }
        )


def test_classify_message_topics_uses_llm_json_response(monkeypatch):
    topic_classifier._CLASSIFICATION_CACHE.clear()
    monkeypatch.setenv("GROQ_API_KEY", "groq-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(topic_classifier.httpx, "AsyncClient", _FakeClient)

    result = asyncio.run(
        topic_classifier.classify_message_topics("Is the pool heated, and how much does pool heating cost?")
    )

    assert result.provider == "groq"
    assert result.topic_ids == ["pool_heating_capability", "pool_heating_cost"]


def test_classify_message_topics_falls_back_to_heuristics_without_keys(monkeypatch):
    topic_classifier._CLASSIFICATION_CACHE.clear()
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = asyncio.run(
        topic_classifier.classify_message_topics("Do you allow dogs and what is the pet fee?")
    )

    assert "pet_policy" in result.topic_ids
    assert "pet_fee" in result.topic_ids


def test_classify_message_topics_caches_identical_messages(monkeypatch):
    topic_classifier._CLASSIFICATION_CACHE.clear()
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    first = asyncio.run(topic_classifier.classify_message_topics("Thanks so much!"))
    second = asyncio.run(topic_classifier.classify_message_topics("Thanks so much!"))

    assert first.cache_hit is False
    assert second.cache_hit is True
