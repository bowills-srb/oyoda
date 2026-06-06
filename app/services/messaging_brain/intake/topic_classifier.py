from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List
from uuid import UUID

import httpx

from app.services.messaging_brain.knowledge.topic_registry import (
    TOPIC_REGISTRY,
    get_knowledge_topic,
    topic_prompt_catalog,
)
from app.services.observability.llm_usage_tracker import LLMUsageTracker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TopicClassificationMatch:
    topic_id: str
    confidence: float
    rationale: str = ""


@dataclass(frozen=True)
class TopicClassification:
    matches: List[TopicClassificationMatch] = field(default_factory=list)
    provider: str = "none"
    cache_hit: bool = False

    @property
    def topic_ids(self) -> List[str]:
        return [match.topic_id for match in self.matches]


_CLASSIFICATION_CACHE: Dict[str, TopicClassification] = {}


def _normalize_message(message: str) -> str:
    return re.sub(r"\s+", " ", (message or "").strip().lower())


def _extract_json_object(payload: str) -> Dict[str, object]:
    text = (payload or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _coerce_classification(payload: Dict[str, object], provider: str) -> TopicClassification:
    rows = payload.get("topics")
    if not isinstance(rows, list):
        return TopicClassification(provider=provider)
    matches: List[TopicClassificationMatch] = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        topic_id = str(row.get("topic_id") or "").strip()
        if not topic_id or topic_id in seen or get_knowledge_topic(topic_id) is None:
            continue
        seen.add(topic_id)
        try:
            confidence = float(row.get("confidence") or 0.0)
        except Exception:
            confidence = 0.0
        matches.append(
            TopicClassificationMatch(
                topic_id=topic_id,
                confidence=max(0.0, min(1.0, confidence)),
                rationale=str(row.get("rationale") or "").strip(),
            )
        )
    return TopicClassification(matches=matches, provider=provider)


async def _call_groq(*, api_key: str, system_prompt: str, user_prompt: str) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 240,
            },
        )
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        return {
            "text": data["choices"][0]["message"]["content"].strip(),
            "input_tokens": int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
        }


async def _call_claude(*, api_key: str, system_prompt: str, user_prompt: str) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5",
                "max_tokens": 240,
                "temperature": 0.1,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        return {
            "text": data["content"][0]["text"].strip(),
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
        }


def _heuristic_classify(message: str) -> TopicClassification:
    lowered = _normalize_message(message)
    if not lowered:
        return TopicClassification(provider="heuristic")
    ranked: List[TopicClassificationMatch] = []
    for topic in TOPIC_REGISTRY.values():
        score = 0
        for token in topic.classifier_keywords:
            normalized = _normalize_message(token)
            if normalized and normalized in lowered:
                score = max(score, min(3, len(normalized.split())))
        if score <= 0:
            continue
        ranked.append(
            TopicClassificationMatch(
                topic_id=topic.topic_id,
                confidence=min(0.92, 0.4 + (0.12 * score)),
                rationale="keyword_match",
            )
        )
    ranked.sort(key=lambda match: (-match.confidence, match.topic_id))
    return TopicClassification(matches=ranked[:4], provider="heuristic")


async def classify_message_topics(message: str, *, tenant_id: UUID | None = None) -> TopicClassification:
    normalized = _normalize_message(message)
    if not normalized:
        return TopicClassification(provider="none")
    cached = _CLASSIFICATION_CACHE.get(normalized)
    if cached is not None:
        return TopicClassification(matches=cached.matches, provider=cached.provider, cache_hit=True)

    system_prompt = (
        "You classify guest pre-booking questions into concise knowledge topics. "
        "Return only JSON with shape "
        '{"topics":[{"topic_id":"...", "confidence":0.0, "rationale":"..."}]}. '
        "Choose zero or more topics from the allowed catalog. "
        "Do not invent new topic IDs. "
        "Use an empty list if the message does not ask for property knowledge."
    )
    user_prompt = (
        "Allowed topics:\n"
        f"{topic_prompt_catalog()}\n\n"
        "Guest message:\n"
        f"{message.strip()}\n\n"
        "Return only JSON."
    )

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    calls = []
    if groq_key:
        calls.append(("groq", "meta-llama/llama-4-scout-17b-16e-instruct", groq_key, _call_groq))
    if anthropic_key:
        calls.append(("anthropic", "claude-haiku-4-5", anthropic_key, _call_claude))

    for fallback_position, (provider, model_id, api_key, call) in enumerate(calls, start=1):
        started = time.monotonic()
        try:
            response = await call(api_key=api_key, system_prompt=system_prompt, user_prompt=user_prompt)
            payload = _extract_json_object(str(response.get("text") or ""))
            result = _coerce_classification(payload, provider)
            await LLMUsageTracker.record(
                service_name="topic_classifier",
                tenant_id=tenant_id,
                request_type="topic_classification",
                provider=provider,
                model_id=model_id,
                input_tokens=int(response.get("input_tokens") or 0),
                output_tokens=int(response.get("output_tokens") or 0),
                success=True,
                latency_ms=int((time.monotonic() - started) * 1000),
                fallback_position=fallback_position,
                metadata={"message_chars": len(message or "")},
            )
            if result.matches or payload.get("topics") == []:
                _CLASSIFICATION_CACHE[normalized] = result
                return result
        except Exception as exc:
            await LLMUsageTracker.record(
                service_name="topic_classifier",
                tenant_id=tenant_id,
                request_type="topic_classification",
                provider=provider,
                model_id=model_id,
                input_tokens=0,
                output_tokens=0,
                success=False,
                latency_ms=int((time.monotonic() - started) * 1000),
                fallback_position=fallback_position,
                error_type=type(exc).__name__,
                metadata={"message_chars": len(message or "")},
            )
            logger.debug("[TopicClassifier] provider=%s failed: %s", provider, exc)

    fallback = _heuristic_classify(message)
    _CLASSIFICATION_CACHE[normalized] = fallback
    return fallback
