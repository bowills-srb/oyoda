from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from uuid import UUID

import httpx

from app.services.observability.llm_usage_tracker import LLMUsageTracker

logger = logging.getLogger(__name__)


@dataclass
class ConciergeReviewResult:
    verdict: str = "approve"  # approve | revise | human_review | block
    confidence: float = 0.0
    review_source: str = "heuristic"
    flags: list[str] = field(default_factory=list)
    rationale: str = ""
    reviewed_response: str = ""
    scores: Dict[str, float] = field(default_factory=dict)


_NEGOTIATION_PATTERNS = (
    re.compile(r"\brental agreement\b", re.I),
    re.compile(r"\bamend(?:ment)?\b", re.I),
    re.compile(r"\breimburse(?:ment|d)?\b", re.I),
    re.compile(r"\brefund\b", re.I),
    re.compile(r"\bcompromise\b", re.I),
    re.compile(r"\bcredit card\b", re.I),
    re.compile(r"\bcharge\b", re.I),
    re.compile(r"\bfee\b", re.I),
    re.compile(r"\bupdate the rental agreement\b", re.I),
    re.compile(r"\blate checkout\b", re.I),
    re.compile(r"\bcheckout to\b", re.I),
)

_OFF_PLATFORM_BOOKING_PATTERNS = (
    re.compile(r"\bbook directly\b", re.I),
    re.compile(r"\bthrough your company\b", re.I),
    re.compile(r"\bavoid fees\b", re.I),
    re.compile(r"\boff[- ]platform\b", re.I),
)

_OFF_PLATFORM_RESPONSE_PATTERNS = (
    re.compile(r"\bour site\b", re.I),
    re.compile(r"\bbook direct(?:ly)?\b", re.I),
    re.compile(r"\bthrough our website\b", re.I),
    re.compile(r"\bbook elsewhere\b", re.I),
    re.compile(r"\bemail us directly\b", re.I),
    re.compile(r"\bcall us\b", re.I),
    re.compile(r"\btext us\b", re.I),
)

_AMENITY_RISK_PATTERNS = (
    re.compile(r"\bgolf cart\b", re.I),
    re.compile(r"\bwrist ?bands?\b", re.I),
    re.compile(r"\bpool\b", re.I),
    re.compile(r"\bcheck(?:ing)? in\b", re.I),
)

_PROMISE_PATTERNS = (
    re.compile(r"\bdefinitely\b", re.I),
    re.compile(r"\bcertainly\b", re.I),
    re.compile(r"\bguarantee\b", re.I),
    re.compile(r"\bwe can\b", re.I),
    re.compile(r"\bwe will\b", re.I),
)

_POLICY_ALLOWANCE_PATTERNS = (
    re.compile(r"\b(?:is|are)\b.*\ballowed\b", re.I),
    re.compile(r"\bbring (?:our|my|your) own\b", re.I),
    re.compile(r"\bcan (?:we|i)\b.*\bbring\b", re.I),
)

_DECISIVE_POLICY_RESPONSE_PATTERNS = (
    re.compile(r"\byes[, ]", re.I),
    re.compile(r"\bno[, ]", re.I),
    re.compile(r"\byou (?:can|may)\b", re.I),
    re.compile(r"\byou (?:cannot|can’t|can't|may not)\b", re.I),
    re.compile(r"\bthat is allowed\b", re.I),
    re.compile(r"\bthat is not allowed\b", re.I),
    re.compile(r"\bare not allowed\b", re.I),
    re.compile(r"\bis not allowed\b", re.I),
)

_SERVICE_ANIMAL_PATTERNS = (
    re.compile(r"\bservice animal[s]?\b", re.I),
    re.compile(r"\bservice dog[s]?\b", re.I),
    re.compile(r"\bada\b", re.I),
)

_CONCRETE_AMENITY_FACT_PATTERNS = (
    re.compile(r"\bgolf cart\b", re.I),
    re.compile(r"\blsv\b", re.I),
    re.compile(r"\bbikes?\b", re.I),
    re.compile(r"\bwristbands?\b", re.I),
    re.compile(r"\bbeach chairs?\b", re.I),
    re.compile(r"\bumbrellas?\b", re.I),
)

_CONCRETE_FACT_RESPONSE_PATTERNS = (
    re.compile(r"\b\d+\s*(?:seater|bikes?|chairs?|umbrellas?)\b", re.I),
    re.compile(r"\bcomes? with\b", re.I),
    re.compile(r"\bincluded\b", re.I),
    re.compile(r"\badditional fee\b", re.I),
    re.compile(r"\baccess to\b", re.I),
)

PLACEHOLDER_RESPONSE_PATTERNS = (
    re.compile(r"\[insert\b", re.I),
    re.compile(r"\[fill[ _-]?in\b", re.I),
    re.compile(r"\[placeholder\b", re.I),
    re.compile(r"\[your\s+\w+\b", re.I),
    re.compile(r"\[specific\s+\w+\b", re.I),
    re.compile(r"\[bracket(?:s|ed)?\b", re.I),
    re.compile(r"\[\.\.\.\]"),
)


def _has_grounded_golf_cart_policy(source_lower: str) -> bool:
    return "grounded_golf_cart_policy:" in source_lower


def _has_grounded_golf_cart_inclusion(source_lower: str) -> bool:
    return "grounded_golf_cart_included:" in source_lower or "grounded_golf_cart_size:" in source_lower


async def review_concierge_response(
    *,
    guest_message: str,
    draft_response: str,
    source_context: str,
    lifecycle_stage: str = "",
    sender_role: str = "guest",
    property_name: str = "",
    tenant_id: UUID | None = None,
) -> ConciergeReviewResult:
    heuristic = _heuristic_review(
        guest_message=guest_message,
        draft_response=draft_response,
        source_context=source_context,
        lifecycle_stage=lifecycle_stage,
        sender_role=sender_role,
    )
    llm_result = await _llm_review(
        guest_message=guest_message,
        draft_response=draft_response,
        source_context=source_context,
        lifecycle_stage=lifecycle_stage,
        property_name=property_name,
        tenant_id=tenant_id,
    )
    if llm_result is None:
        return heuristic
    merged = _merge_reviews(heuristic, llm_result)
    return _apply_placeholder_guard(merged)


def _heuristic_review(
    *,
    guest_message: str,
    draft_response: str,
    source_context: str,
    lifecycle_stage: str,
    sender_role: str,
) -> ConciergeReviewResult:
    flags: list[str] = []
    verdict = "approve"
    confidence = 0.72
    message = guest_message or ""
    response = draft_response or ""
    source = source_context or ""

    if sender_role != "guest":
        flags.append("non_guest_sender")
        verdict = "human_review"

    if any(p.search(message) for p in _NEGOTIATION_PATTERNS):
        flags.append("negotiation_or_contract_change")
        verdict = "human_review"
        confidence = 0.9

    platform_source = source.lower()
    if lifecycle_stage == "pre_booking" and any(p.search(message) for p in _OFF_PLATFORM_BOOKING_PATTERNS):
        if "vrbo" in platform_source or "airbnb" in platform_source:
            flags.append("off_platform_booking_policy_risk")
            verdict = "human_review"
            confidence = max(confidence, 0.94)

    if "$" in message and any(p.search(message) for p in _AMENITY_RISK_PATTERNS):
        flags.append("compensation_with_amenity_risk")
        verdict = "human_review"
        confidence = 0.92

    early_arrival_signal = any(
        phrase in message.lower()
        for phrase in ["come earlier", "arrive early", "early check", "early arrival", "land at", "drop bags"]
    ) or ("check" in message.lower() and "in" in message.lower())
    if lifecycle_stage == "pre_arrival" and early_arrival_signal:
        if "confirm" not in response.lower() and "request" not in response.lower():
            flags.append("early_arrival_or_checkin_without_confirmation_language")
            if verdict == "approve":
                verdict = "revise"

    if any(p.search(response) for p in _PROMISE_PATTERNS) and source and "$" in response and "$" not in source:
        flags.append("promise_or_numeric_commitment_not_grounded")
        verdict = "human_review"

    if any(p.search(message) for p in _OFF_PLATFORM_BOOKING_PATTERNS) and any(
        p.search(response) for p in _OFF_PLATFORM_RESPONSE_PATTERNS
    ):
        flags.append("response_encourages_off_platform_booking")
        verdict = "block"
        confidence = max(confidence, 0.97)

    if not any(p.search(message) for p in _SERVICE_ANIMAL_PATTERNS) and any(
        p.search(response) for p in _SERVICE_ANIMAL_PATTERNS
    ):
        flags.append("response_introduces_service_animal_framing")
        verdict = "human_review"
        confidence = max(confidence, 0.95)

    policy_question = any(p.search(message) for p in _POLICY_ALLOWANCE_PATTERNS) or (
        "golf cart" in message.lower() and "allowed" in message.lower()
    )
    if policy_question and any(
        p.search(response) for p in _DECISIVE_POLICY_RESPONSE_PATTERNS
    ):
        source_lower = source.lower()
        if "golf cart" in message.lower():
            has_grounding = _has_grounded_golf_cart_policy(source_lower)
        else:
            grounding_markers = ("policy_", "allowed", "rule", "beach", "umbrella", "chair", "access", "gear")
            has_grounding = any(marker in source_lower for marker in grounding_markers)
        if not has_grounding:
            flags.append("ungrounded_policy_decision")
            if verdict == "approve":
                verdict = "human_review"
            confidence = max(confidence, 0.9)

    if any(p.search(message) for p in _CONCRETE_AMENITY_FACT_PATTERNS) and any(
        p.search(response) for p in _CONCRETE_FACT_RESPONSE_PATTERNS
    ):
        source_lower = source.lower()
        if "golf cart" in message.lower():
            has_fact_grounding = _has_grounded_golf_cart_inclusion(source_lower)
        else:
            fact_markers = ("bike", "wristband", "chair", "umbrella", "included", "fee", "access")
            has_fact_grounding = any(marker in source_lower for marker in fact_markers)
        if not has_fact_grounding:
            flags.append("ungrounded_amenity_fact")
            if verdict == "approve":
                verdict = "human_review"
            confidence = max(confidence, 0.9)

    key_terms = _extract_salient_terms(message)
    if key_terms:
        covered = sum(1 for term in key_terms if term in response.lower())
        coverage = covered / max(len(key_terms), 1)
        if coverage < 0.2 and len(message.strip()) > 40:
            flags.append("low_intent_coverage")
            if verdict == "approve":
                verdict = "revise"
            confidence = max(confidence, 0.8)
    else:
        coverage = 1.0

    rationale = "heuristic review completed"
    if flags:
        rationale = "; ".join(flags[:3])

    return ConciergeReviewResult(
        verdict=verdict,
        confidence=confidence,
        review_source="heuristic",
        flags=flags,
        rationale=rationale,
        reviewed_response="",
        scores={
            "intent_coverage": round(coverage, 2),
            "promise_risk": 1.0 if "promise_or_numeric_commitment_not_grounded" in flags else 0.0,
            "negotiation_risk": 1.0 if "negotiation_or_contract_change" in flags else 0.0,
            "policy_risk": 1.0 if any(
                flag in flags for flag in {
                    "off_platform_booking_policy_risk",
                    "response_encourages_off_platform_booking",
                    "ungrounded_policy_decision",
                    "response_introduces_service_animal_framing",
                    "ungrounded_amenity_fact",
                }
            ) else 0.0,
        },
    )


def _extract_salient_terms(message: str) -> list[str]:
    lowered = message.lower()
    tracked = [
        "golf cart", "wristband", "wristbands", "pool", "check in", "checking in",
        "early", "late checkout", "checkout", "credit card", "charge", "fee",
        "reimburse", "refund", "rental agreement", "discount", "booked",
    ]
    return [term for term in tracked if term in lowered]


async def _llm_review(
    *,
    guest_message: str,
    draft_response: str,
    source_context: str,
    lifecycle_stage: str,
    property_name: str,
    tenant_id: UUID | None = None,
) -> Optional[ConciergeReviewResult]:
    groq_key = os.getenv("GROQ_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not groq_key and not anthropic_key:
        return None

    system_prompt = (
        "You are an adversarial reviewer for a hospitality concierge engine.\n"
        "Your job is to challenge the draft response against the source context and guest message.\n"
        "Return strict JSON only with keys: verdict, confidence, flags, rationale, reviewed_response, scores.\n"
        "Verdict must be one of: approve, revise, human_review, block.\n"
        "Use human_review for compensation, contract changes, billing disputes, legal/promise risk, or missing context.\n"
        "If revise, provide a safer reviewed_response. If approve, reviewed_response may be empty.\n"
        "Never invent facts not supported by context."
    )
    user_prompt = (
        f"Lifecycle stage: {lifecycle_stage}\n"
        f"Property: {property_name}\n\n"
        f"Guest message:\n{guest_message}\n\n"
        f"Draft response:\n{draft_response}\n\n"
        f"Available source context:\n{source_context[:4000]}"
    )

    try:
        if groq_key:
            started = time.monotonic()
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 350,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                usage = data.get("usage") or {}
                await LLMUsageTracker.record(
                    service_name="response_reviewer",
                    tenant_id=tenant_id,
                    request_type="review",
                    provider="groq",
                    model_id="meta-llama/llama-4-scout-17b-16e-instruct",
                    input_tokens=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
                    output_tokens=int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
                    success=True,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    fallback_position=1,
                    metadata={"lifecycle_stage": lifecycle_stage, "property_name": property_name},
                )
                content = data["choices"][0]["message"]["content"]
                parsed = _parse_review_json(content)
                if parsed:
                    parsed.review_source = "groq_adversarial"
                    return parsed
        if anthropic_key:
            started = time.monotonic()
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": anthropic_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5",
                        "max_tokens": 350,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": user_prompt}],
                        "temperature": 0.1,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                usage = data.get("usage") or {}
                await LLMUsageTracker.record(
                    service_name="response_reviewer",
                    tenant_id=tenant_id,
                    request_type="review",
                    provider="anthropic",
                    model_id="claude-haiku-4-5",
                    input_tokens=int(usage.get("input_tokens") or 0),
                    output_tokens=int(usage.get("output_tokens") or 0),
                    success=True,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    fallback_position=2,
                    metadata={"lifecycle_stage": lifecycle_stage, "property_name": property_name},
                )
                content = data["content"][0]["text"]
                parsed = _parse_review_json(content)
                if parsed:
                    parsed.review_source = "anthropic_adversarial"
                    return parsed
    except Exception as exc:  # noqa: BLE001
        provider = "anthropic" if groq_key and anthropic_key else ("groq" if groq_key else "anthropic")
        model_id = "claude-haiku-4-5" if provider == "anthropic" else "meta-llama/llama-4-scout-17b-16e-instruct"
        fallback_position = 2 if provider == "anthropic" else 1
        await LLMUsageTracker.record(
            service_name="response_reviewer",
            tenant_id=tenant_id,
            request_type="review",
            provider=provider,
            model_id=model_id,
            input_tokens=0,
            output_tokens=0,
            success=False,
            latency_ms=0,
            fallback_position=fallback_position,
            error_type=type(exc).__name__,
            metadata={"lifecycle_stage": lifecycle_stage, "property_name": property_name},
        )
        logger.warning("[ConciergeReview] LLM review failed: %s", exc)
    return None


def _parse_review_json(content: str) -> Optional[ConciergeReviewResult]:
    text = (content or "").strip()
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        payload = json.loads(text[start:end + 1])
    except Exception:
        return None
    verdict = str(payload.get("verdict") or "approve").strip().lower()
    if verdict not in {"approve", "revise", "human_review", "block"}:
        verdict = "approve"
    return ConciergeReviewResult(
        verdict=verdict,
        confidence=float(payload.get("confidence") or 0.0),
        review_source="llm",
        flags=[str(x) for x in (payload.get("flags") or [])][:8],
        rationale=str(payload.get("rationale") or ""),
        reviewed_response=str(payload.get("reviewed_response") or ""),
        scores=payload.get("scores") or {},
    )


def match_placeholder_pattern(text: str) -> Optional[str]:
    """Return the matching pattern source for `text`, or None.

    Public surface for cross-module placeholder detection. Used by
    both `_apply_placeholder_guard` (primary guard inside the
    reviewer pipeline) and email_dispatch's defensive boundary guard.
    Keeping the regex set and the matcher in one module is what
    prevents the two consumers from drifting.
    """
    candidate = (text or "").strip()
    if not candidate:
        return None
    for pattern in PLACEHOLDER_RESPONSE_PATTERNS:
        if pattern.search(candidate):
            return pattern.pattern
    return None


def _apply_placeholder_guard(result: ConciergeReviewResult) -> ConciergeReviewResult:
    reviewed_response = result.reviewed_response or ""
    matched_pattern = match_placeholder_pattern(reviewed_response)
    if not matched_pattern:
        return result

    flags = list(dict.fromkeys([*result.flags, "placeholder_text_detected"]))
    rationale_note = (
        f"placeholder_text_detected via pattern {matched_pattern!r}"
    )
    rationale = (
        f"{result.rationale}; {rationale_note}"
        if result.rationale
        else rationale_note
    )
    return ConciergeReviewResult(
        verdict="human_review",
        confidence=result.confidence,
        review_source=result.review_source,
        flags=flags,
        rationale=rationale,
        reviewed_response="",
        scores=result.scores,
    )


def _match_placeholder_pattern(text: str) -> Optional[str]:
    return match_placeholder_pattern(text)


def _merge_reviews(
    heuristic: ConciergeReviewResult,
    llm_result: ConciergeReviewResult,
) -> ConciergeReviewResult:
    order = {"approve": 0, "revise": 1, "human_review": 2, "block": 3}
    verdict = heuristic.verdict
    if order.get(llm_result.verdict, 0) >= order.get(heuristic.verdict, 0):
        verdict = llm_result.verdict
    reviewed_response = llm_result.reviewed_response or heuristic.reviewed_response
    flags = list(dict.fromkeys([*heuristic.flags, *llm_result.flags]))
    scores = {**heuristic.scores, **llm_result.scores}
    rationale = llm_result.rationale or heuristic.rationale
    confidence = max(heuristic.confidence, llm_result.confidence)
    return ConciergeReviewResult(
        verdict=verdict,
        confidence=confidence,
        review_source=f"{heuristic.review_source}+{llm_result.review_source}",
        flags=flags,
        rationale=rationale,
        reviewed_response=reviewed_response,
        scores=scores,
    )
