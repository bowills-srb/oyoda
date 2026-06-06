from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Awaitable, Callable, Optional
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.services.observability.llm_usage_tracker import LLMUsageTracker

logger = logging.getLogger(__name__)

DEFAULT_ESCALATION_THRESHOLD = 0.40
DEFAULT_BRAIN_ROUTER_THRESHOLD = 0.30
_PREVIEW_HASH_LEN = 12
_PREBOOKING_INTENTS = (
    "availability",
    "check_in_process",
    "pet_policy",
    "pricing",
    "amenities",
    "local_area",
    "group_size",
    "accessibility",
    "review_response",
    "general",
)

_PROMPT = """You classify pre-booking vacation-rental guest inquiries.

Return one JSON object only:
{
  "intent": "availability" | "check_in_process" | "pet_policy" | "pricing" |
            "amenities" | "local_area" | "group_size" | "accessibility" |
            "review_response" | "general",
  "confidence": <float 0.0 to 1.0>,
  "reason": "<short sentence>"
}

Use these rules:
- Questions about what the property has, what is included, baby gear, beach gear,
  sleeping setup, pool, wifi, parking, or similar should be "amenities".
- Questions about nearby restaurants, activities, directions, distance, or local
  suggestions should be "local_area".
- If the message is ambiguous, choose "general" and lower the confidence.
- Confidence below 0.40 means meaningful ambiguity remains.

Return JSON only. No markdown, no extra text."""


@dataclass(frozen=True)
class PreBookingClassifierMetadata:
    classifier_source: str
    threshold: float
    original_intent: str
    original_confidence: float
    escalated: bool = False
    contradictory_signals: bool = False
    escalation_provider: str | None = None
    escalated_confidence: float | None = None
    escalated_topic: str | None = None
    notes: list[str] = field(default_factory=list)

    def audit_payload(self) -> dict[str, Any]:
        return {
            "type": "intent_classifier_metadata",
            "classifier_source": self.classifier_source,
            "threshold": self.threshold,
            "original_intent": self.original_intent,
            "original_confidence": self.original_confidence,
            "escalated": self.escalated,
            "contradictory_signals": self.contradictory_signals,
            "escalation_provider": self.escalation_provider,
            "escalated_confidence": self.escalated_confidence,
            "escalated_topic": self.escalated_topic,
            "notes": list(self.notes or []),
        }


async def load_prebooking_escalation_threshold(
    *,
    tenant_id: UUID,
    db: Any = None,
    default: float = DEFAULT_ESCALATION_THRESHOLD,
) -> float:
    return await _load_operator_setting_threshold(
        tenant_id=tenant_id,
        db=db,
        key="intent_classifier_escalation_threshold",
        default=default,
    )


async def load_brain_router_threshold(
    *,
    tenant_id: str,
    db: Any = None,
    default: float = DEFAULT_BRAIN_ROUTER_THRESHOLD,
) -> float:
    try:
        tenant_uuid = UUID(str(tenant_id))
    except (TypeError, ValueError):
        return default
    return await _load_operator_setting_threshold(
        tenant_id=tenant_uuid,
        db=db,
        key="brain_router_confidence_threshold",
        default=default,
    )


async def classify_with_escalation(
    *,
    message: str,
    conversation_context: str,
    tenant_id: UUID,
    keyword_result: dict[str, Any],
    db: Any = None,
    threshold: float | None = None,
) -> tuple[str, float, PreBookingClassifierMetadata]:
    configured_threshold = (
        threshold
        if threshold is not None
        else await load_prebooking_escalation_threshold(tenant_id=tenant_id, db=db)
    )

    original_intent = str(keyword_result.get("intent") or "general")
    original_confidence = float(keyword_result.get("confidence") or 0.0)
    contradictory_signals = bool(keyword_result.get("contradictory_signals"))
    competing_intents = list(keyword_result.get("competing_intents") or [])

    if (
        original_confidence >= configured_threshold
        and not contradictory_signals
    ):
        return (
            original_intent,
            original_confidence,
            PreBookingClassifierMetadata(
                classifier_source="keyword",
                threshold=configured_threshold,
                original_intent=original_intent,
                original_confidence=original_confidence,
                contradictory_signals=contradictory_signals,
                notes=[f"competing_intents:{competing_intents}"] if competing_intents else [],
            ),
        )

    preview_hash = _message_preview_hash(message)
    llm_result = await _run_llm_escalation(
        message=message,
        conversation_context=conversation_context,
        tenant_id=tenant_id,
        original_intent=original_intent,
        original_confidence=original_confidence,
        preview_hash=preview_hash,
    )
    if llm_result is None:
        return (
            original_intent,
            original_confidence,
            PreBookingClassifierMetadata(
                classifier_source="llm_failed_keyword_default",
                threshold=configured_threshold,
                original_intent=original_intent,
                original_confidence=original_confidence,
                escalated=True,
                contradictory_signals=contradictory_signals,
                notes=[f"competing_intents:{competing_intents}"] if competing_intents else [],
            ),
        )

    escalated_intent = str(llm_result["intent"])
    escalated_confidence = float(llm_result["confidence"])
    if escalated_confidence < configured_threshold:
        return (
            original_intent,
            original_confidence,
            PreBookingClassifierMetadata(
                classifier_source="keyword_low_confidence_fallback",
                threshold=configured_threshold,
                original_intent=original_intent,
                original_confidence=original_confidence,
                escalated=True,
                contradictory_signals=contradictory_signals,
                escalation_provider=str(llm_result["provider"]),
                escalated_confidence=escalated_confidence,
                escalated_topic=escalated_intent,
                notes=[f"competing_intents:{competing_intents}"] if competing_intents else [],
            ),
        )

    return (
        escalated_intent,
        escalated_confidence,
        PreBookingClassifierMetadata(
            classifier_source=f"llm_escalated_{llm_result['provider']}",
            threshold=configured_threshold,
            original_intent=original_intent,
            original_confidence=original_confidence,
            escalated=True,
            contradictory_signals=contradictory_signals,
            escalation_provider=str(llm_result["provider"]),
            escalated_confidence=escalated_confidence,
            escalated_topic=escalated_intent,
            notes=[f"competing_intents:{competing_intents}"] if competing_intents else [],
        ),
    )


async def _load_operator_setting_threshold(
    *,
    tenant_id: UUID,
    db: Any = None,
    key: str,
    default: float,
) -> float:
    if db is None:
        return default
    try:
        row = (
            await db.execute(
                text(
                    """
                    SELECT extra
                    FROM operator_settings
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                    LIMIT 1
                    """
                ),
                {"tenant_id": str(tenant_id)},
            )
        ).scalar_one_or_none()
    except ProgrammingError:
        logger.error(
            "[IntentEscalator] operator_settings read failed due to schema issue "
            "tenant_id=%s key=%s",
            tenant_id,
            key,
            exc_info=True,
        )
        return default
    except DBAPIError:
        logger.warning(
            "[IntentEscalator] operator_settings read failed tenant_id=%s key=%s",
            tenant_id,
            key,
            exc_info=True,
        )
        return default

    payload = _coerce_json_object(row)
    raw_value = payload.get(key)
    if raw_value is None:
        return default
    try:
        numeric = float(raw_value)
    except (TypeError, ValueError):
        return default
    return min(max(numeric, 0.0), 1.0)


async def _run_llm_escalation(
    *,
    message: str,
    conversation_context: str,
    tenant_id: UUID,
    original_intent: str,
    original_confidence: float,
    preview_hash: str,
) -> Optional[dict[str, Any]]:
    user_prompt = _build_user_prompt(
        message=message,
        conversation_context=conversation_context,
        original_intent=original_intent,
        original_confidence=original_confidence,
    )
    providers = _provider_chain()
    for fallback_position, provider in enumerate(providers, start=1):
        started = time.monotonic()
        try:
            payload = await provider["call"](
                api_key=provider["api_key"],
                user_prompt=user_prompt,
            )
            content = str(payload["text"]).strip()
            parsed = _parse_llm_payload(content)
            await _record_usage(
                tenant_id=tenant_id,
                provider=provider["name"],
                model_id=provider["model_id"],
                success=True,
                latency_ms=int((time.monotonic() - started) * 1000),
                fallback_position=fallback_position,
                input_tokens=int(payload.get("input_tokens") or 0),
                output_tokens=int(payload.get("output_tokens") or 0),
                metadata={
                    "preview_hash": preview_hash,
                    "original_intent": original_intent,
                    "original_confidence": original_confidence,
                    "escalated_intent": parsed["intent"],
                    "escalated_confidence": parsed["confidence"],
                },
            )
            return {
                "provider": provider["name"],
                "intent": parsed["intent"],
                "confidence": parsed["confidence"],
                "reason": parsed.get("reason", ""),
            }
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            await _record_provider_failure(
                tenant_id=tenant_id,
                provider=provider["name"],
                model_id=provider["model_id"],
                fallback_position=fallback_position,
                preview_hash=preview_hash,
                original_intent=original_intent,
                original_confidence=original_confidence,
                error=exc,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            logger.warning(
                "[IntentEscalator] provider request failed tenant_id=%s provider=%s preview_hash=%s error=%s",
                tenant_id,
                provider["name"],
                preview_hash,
                type(exc).__name__,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            await _record_provider_failure(
                tenant_id=tenant_id,
                provider=provider["name"],
                model_id=provider["model_id"],
                fallback_position=fallback_position,
                preview_hash=preview_hash,
                original_intent=original_intent,
                original_confidence=original_confidence,
                error=exc,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            logger.warning(
                "[IntentEscalator] provider response invalid tenant_id=%s provider=%s preview_hash=%s error=%s",
                tenant_id,
                provider["name"],
                preview_hash,
                type(exc).__name__,
            )
    return None


def _provider_chain() -> list[dict[str, Any]]:
    providers: list[dict[str, Any]] = []
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")
    if anthropic_key:
        providers.append(
            {
                "name": "anthropic",
                "model_id": "claude-haiku-4-5",
                "api_key": anthropic_key,
                "call": _call_anthropic,
            }
        )
    if groq_key:
        providers.append(
            {
                "name": "groq",
                "model_id": "meta-llama/llama-4-scout-17b-16e-instruct",
                "api_key": groq_key,
                "call": _call_groq,
            }
        )
    return providers


async def _call_anthropic(
    *,
    api_key: str,
    user_prompt: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=8.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5",
                "max_tokens": 220,
                "temperature": 0.1,
                "system": _PROMPT,
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


async def _call_groq(
    *,
    api_key: str,
    user_prompt: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=8.0) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                "messages": [
                    {"role": "system", "content": _PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 220,
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


def _build_user_prompt(
    *,
    message: str,
    conversation_context: str,
    original_intent: str,
    original_confidence: float,
) -> str:
    return (
        f"Guest message:\n{message.strip()}\n\n"
        f"Conversation context:\n{(conversation_context or '').strip()[:2500]}\n\n"
        f"Keyword classifier guess: intent={original_intent} confidence={original_confidence:.2f}\n\n"
        "Reclassify using only the allowed intent vocabulary."
    )


def _parse_llm_payload(content: str) -> dict[str, Any]:
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in LLM response")
    payload = json.loads(content[start : end + 1])
    intent = str(payload["intent"]).strip()
    if intent not in _PREBOOKING_INTENTS:
        raise ValueError(f"Unsupported intent: {intent}")
    confidence = float(payload["confidence"])
    confidence = min(max(confidence, 0.0), 1.0)
    reason = str(payload.get("reason") or "").strip()
    return {
        "intent": intent,
        "confidence": round(confidence, 2),
        "reason": reason,
    }


async def _record_usage(
    *,
    tenant_id: UUID,
    provider: str,
    model_id: str,
    success: bool,
    latency_ms: int,
    fallback_position: int,
    input_tokens: int = 0,
    output_tokens: int = 0,
    error_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    await LLMUsageTracker.record(
        service_name="intent_classification_escalator",
        tenant_id=tenant_id,
        request_type="intent_reclassification",
        provider=provider,
        model_id=model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        success=success,
        latency_ms=latency_ms,
        fallback_position=fallback_position,
        error_type=error_type,
        metadata=metadata,
    )


async def _record_provider_failure(
    *,
    tenant_id: UUID,
    provider: str,
    model_id: str,
    fallback_position: int,
    preview_hash: str,
    original_intent: str,
    original_confidence: float,
    error: BaseException,
    latency_ms: int,
) -> None:
    await _record_usage(
        tenant_id=tenant_id,
        provider=provider,
        model_id=model_id,
        success=False,
        latency_ms=latency_ms,
        fallback_position=fallback_position,
        error_type=type(error).__name__,
        metadata={
            "preview_hash": preview_hash,
            "original_intent": original_intent,
            "original_confidence": original_confidence,
        },
    )


def _coerce_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _message_preview_hash(message: str) -> str:
    normalized = re.sub(r"\s+", " ", (message or "").strip())
    return sha256(normalized.encode("utf-8")).hexdigest()[:_PREVIEW_HASH_LEN]
