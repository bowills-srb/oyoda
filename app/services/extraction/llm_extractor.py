from __future__ import annotations

from dataclasses import dataclass
import asyncio
import json
import logging
import os
import random
import re
import time
from typing import Any, Optional
from uuid import UUID

import httpx

from app.services.messaging_brain.knowledge.topic_registry import TOPIC_REGISTRY, topic_prompt_catalog
from app.services.extraction.canonical_block_service import CanonicalBlock
from app.services.extraction.chunkers import ChunkedContent
from app.services.extraction.deterministic_extractors import ExtractionCandidatePayload
from app.services.observability.llm_usage_tracker import LLMUsageTracker

logger = logging.getLogger(__name__)

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_MODEL = "claude-sonnet-4-20250514"
_DEFAULT_MAX_OUTPUT_TOKENS = 1200
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_RETRY_ATTEMPTS = 5
_DEFAULT_RATE_LIMIT_BASE_DELAY = 2.0
_DEFAULT_RATE_LIMIT_MAX_DELAY = 60.0
_INPUT_COST_PER_MILLION = 3.0
_OUTPUT_COST_PER_MILLION = 15.0

_SYSTEM_PROMPT_TEMPLATE = """You are an extraction tool for short-term rental property knowledge.
You receive an HTML chunk from a guidebook and extract distinct, explicit facts as question-answer pairs.

CRITICAL RULES:

1. Extract only facts that are EXPLICITLY stated in the chunk.
   Do not infer, assume, complete, or fill gaps.

2. Each distinct fact becomes its own Q&A pair.
   If a chunk contains multiple facts, produce multiple pairs.
   If a policy contains multiple explicit time windows, thresholds, or branches,
   output one pair per explicit branch.

3. If content is ambiguous, difficult to atomize, or you are uncertain,
   set "uncertain": true and include the original text in "proposed_answer_text" without splitting.

4. Question text should be natural and complete.

5. Answer text should stay anchored to the source meaning.
   Light normalization is allowed, but do not paraphrase away the source meaning.

6. "evidence_excerpt" must quote the exact source text that supports the extraction.
   It must be a verbatim substring of the input chunk's text content.
   Copy it exactly from the source text. Do not normalize punctuation, spelling, or contractions.

7. Set "confidence" conservatively:
   - 0.98+: exact structured extraction
   - 0.90-0.97: clear prose extraction
   - 0.85-0.89: some interpretation involved
   - below 0.85: uncertain extraction

8. If a fact involves conditions, set "conditional": true.
   Atomize by condition when the condition boundaries are explicit and straightforward.
   Example: if a cancellation policy states different outcomes for 60+ days,
   60-30 days, and under 30 days, output separate conditional facts.

9. "proposed_topic_id" must be one of the allowed topic IDs below or null.
   Never invent a topic ID.

10. Skip decorative content, navigation, branding, and marketing copy.
   Extract only operationally useful guest facts.

DO NOT:
- Do not infer facts not stated
- Do not complete patterns
- Do not fill gaps
- Do not paraphrase the source meaning away from the text
- Do not invent topic_ids outside the provided registry
- Do not produce evidence_excerpts that are not in the source
- Do not merge multiple explicit policy branches into one candidate when they can be separated cleanly

WHEN UNCERTAIN:
- Set uncertain=true
- Include the original text in proposed_answer_text
- Lower confidence
- Better to skip a fact than to fabricate one
- If an exact evidence excerpt is hard to copy, skip the candidate instead of approximating it

Allowed topic IDs:
{topic_catalog}

OUTPUT FORMAT:
Return a JSON array of objects with these fields:
- proposed_question_text
- proposed_answer_text
- proposed_topic_id
- confidence
- evidence_excerpt
- uncertain
- conditional
- source_section

If no extractable facts exist, return [].
Do not include any text outside the JSON array.
The response must be parseable JSON."""


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_question_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _normalized_substring(haystack: str, needle: str) -> bool:
    source = _normalize_text(haystack).lower()
    target = _normalize_text(needle).lower()
    if not source or not target:
        return False
    return target in source


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


@dataclass(frozen=True)
class LLMUsage:
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    latency_ms: float
    attempts: int
    retry_count: int
    retry_wait_time_seconds: float
    failed_after_max_retries: bool


@dataclass(frozen=True)
class LLMExtractionResult:
    chunk_id: str
    candidates: list[ExtractionCandidatePayload]
    usage: Optional[LLMUsage]
    raw_text: str
    error: Optional[str] = None


@dataclass(frozen=True)
class LLMBatchExtractionResult:
    results_by_chunk: dict[str, list[ExtractionCandidatePayload]]
    detailed_results: dict[str, LLMExtractionResult]
    total_input_tokens: int
    total_output_tokens: int
    total_estimated_cost_usd: float
    total_retry_count: int
    total_retry_wait_time_seconds: float
    failed_after_max_retries: int
    failed_chunks: list[str]


class LLMExtractor:
    def __init__(
        self,
        *,
        anthropic_api_key: Optional[str] = None,
        model: str = _DEFAULT_MODEL,
        timeout: float = _DEFAULT_TIMEOUT,
        max_output_tokens: int = _DEFAULT_MAX_OUTPUT_TOKENS,
        retry_attempts: int = _DEFAULT_RETRY_ATTEMPTS,
        concurrency: int = 2,
    ) -> None:
        self._api_key = (anthropic_api_key if anthropic_api_key is not None else os.getenv("ANTHROPIC_API_KEY", "")).strip()
        self._model = model
        self._timeout = timeout
        self._max_output_tokens = max_output_tokens
        self._retry_attempts = max(1, retry_attempts)
        self._concurrency = max(1, concurrency)
        self._system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(topic_catalog=topic_prompt_catalog())

    async def extract_from_chunk(
        self,
        chunk: ChunkedContent,
        canonical_block: CanonicalBlock,
    ) -> list[ExtractionCandidatePayload]:
        result = await self.extract_from_chunk_detailed(chunk, canonical_block)
        return result.candidates

    async def extract_from_chunk_detailed(
        self,
        chunk: ChunkedContent,
        canonical_block: CanonicalBlock,
    ) -> LLMExtractionResult:
        if not self._api_key:
            raise ValueError("ANTHROPIC_API_KEY missing")

        user_prompt = self._build_user_prompt(chunk, canonical_block)
        started = time.perf_counter()
        raw_text = ""
        usage_payload: dict[str, Any] = {}
        attempts = 0
        retry_count = 0
        retry_wait_time = 0.0
        failed_after_max_retries = False

        for attempt in range(1, self._retry_attempts + 1):
            attempts = attempt
            try:
                raw_text, usage_payload = await self._call_anthropic(
                    system_prompt=self._system_prompt,
                    user_prompt=user_prompt,
                )
                break
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                error_type = self._response_error_type(exc.response)
                if self._should_retry_http(status=status, error_type=error_type, attempt=attempt):
                    delay = self._retry_delay_for_http(exc.response, attempt=attempt, status=status)
                    retry_count += 1
                    retry_wait_time += delay
                    logger.info(
                        "[LLMExtractor] retrying_http_error status=%s error_type=%s chunk_id=%s attempt=%s delay=%.2fs",
                        status,
                        error_type,
                        chunk.chunk_id,
                        attempt,
                        delay,
                    )
                    await self._sleep(delay)
                    continue
                failed_after_max_retries = status == 429 and attempt >= self._retry_attempts
                logger.warning("[LLMExtractor] anthropic_http_error status=%s chunk_id=%s", status, chunk.chunk_id)
                usage = self._usage_from_payload(
                    usage_payload,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    attempts=attempts,
                    retry_count=retry_count,
                    retry_wait_time_seconds=retry_wait_time,
                    failed_after_max_retries=failed_after_max_retries,
                )
                await self._record_usage(
                    canonical_block=canonical_block,
                    chunk=chunk,
                    usage=usage,
                    success=False,
                    error_type=f"http_{status}",
                )
                return LLMExtractionResult(
                    chunk_id=chunk.chunk_id,
                    candidates=[],
                    usage=usage,
                    raw_text="",
                    error=f"http_{status}",
                )
            except httpx.RequestError as exc:
                if attempt < self._retry_attempts:
                    delay = 0.5 * attempt
                    retry_count += 1
                    retry_wait_time += delay
                    logger.info(
                        "[LLMExtractor] retrying_request_error chunk_id=%s attempt=%s delay=%.2fs error=%s",
                        chunk.chunk_id,
                        attempt,
                        delay,
                        exc,
                    )
                    await self._sleep(delay)
                    continue
                failed_after_max_retries = True
                logger.warning("[LLMExtractor] anthropic_request_error chunk_id=%s error=%s", chunk.chunk_id, exc)
                usage = self._usage_from_payload(
                    usage_payload,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    attempts=attempts,
                    retry_count=retry_count,
                    retry_wait_time_seconds=retry_wait_time,
                    failed_after_max_retries=failed_after_max_retries,
                )
                await self._record_usage(
                    canonical_block=canonical_block,
                    chunk=chunk,
                    usage=usage,
                    success=False,
                    error_type="request_error",
                )
                return LLMExtractionResult(
                    chunk_id=chunk.chunk_id,
                    candidates=[],
                    usage=usage,
                    raw_text="",
                    error="request_error",
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("[LLMExtractor] unexpected_error chunk_id=%s error=%s", chunk.chunk_id, exc)
                usage = self._usage_from_payload(
                    usage_payload,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    attempts=attempts,
                    retry_count=retry_count,
                    retry_wait_time_seconds=retry_wait_time,
                    failed_after_max_retries=False,
                )
                await self._record_usage(
                    canonical_block=canonical_block,
                    chunk=chunk,
                    usage=usage,
                    success=False,
                    error_type="unexpected_error",
                )
                return LLMExtractionResult(
                    chunk_id=chunk.chunk_id,
                    candidates=[],
                    usage=usage,
                    raw_text="",
                    error="unexpected_error",
                )

        latency_ms = (time.perf_counter() - started) * 1000.0
        usage = self._usage_from_payload(
            usage_payload,
            latency_ms=latency_ms,
            attempts=attempts,
            retry_count=retry_count,
            retry_wait_time_seconds=retry_wait_time,
            failed_after_max_retries=failed_after_max_retries,
        )
        candidates = self._parse_and_validate_candidates(raw_text, chunk, canonical_block)
        await self._record_usage(
            canonical_block=canonical_block,
            chunk=chunk,
            usage=usage,
            success=True,
            error_type=None,
        )
        return LLMExtractionResult(
            chunk_id=chunk.chunk_id,
            candidates=candidates,
            usage=usage,
            raw_text=raw_text,
            error=None,
        )

    async def extract_from_chunks_batch(
        self,
        chunks: list[ChunkedContent],
        canonical_blocks: dict[str, CanonicalBlock],
        concurrency: int = 5,
    ) -> LLMBatchExtractionResult:
        semaphore = asyncio.Semaphore(max(1, concurrency or self._concurrency))

        async def _run(chunk: ChunkedContent) -> LLMExtractionResult:
            canonical_block = canonical_blocks[chunk.source_block_hash]
            async with semaphore:
                return await self.extract_from_chunk_detailed(chunk, canonical_block)

        results = await asyncio.gather(*[_run(chunk) for chunk in chunks])
        detailed = {result.chunk_id: result for result in results}
        results_by_chunk = {result.chunk_id: result.candidates for result in results}
        total_input = sum((result.usage.input_tokens if result.usage else 0) for result in results)
        total_output = sum((result.usage.output_tokens if result.usage else 0) for result in results)
        total_cost = sum((result.usage.estimated_cost_usd if result.usage else 0.0) for result in results)
        total_retries = sum((result.usage.retry_count if result.usage else 0) for result in results)
        total_retry_wait = sum((result.usage.retry_wait_time_seconds if result.usage else 0.0) for result in results)
        failed_after_max_retries = sum(
            1
            for result in results
            if result.usage is not None and result.usage.failed_after_max_retries
        )
        failed = [result.chunk_id for result in results if result.error]
        return LLMBatchExtractionResult(
            results_by_chunk=results_by_chunk,
            detailed_results=detailed,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_estimated_cost_usd=total_cost,
            total_retry_count=total_retries,
            total_retry_wait_time_seconds=total_retry_wait,
            failed_after_max_retries=failed_after_max_retries,
            failed_chunks=failed,
        )

    def _build_user_prompt(self, chunk: ChunkedContent, canonical_block: CanonicalBlock) -> str:
        page_context = canonical_block.block_content.get("page_title") or canonical_block.canonical_page_id
        return (
            "Chunk metadata:\n"
            f"- Block render_type: {canonical_block.render_type}\n"
            f"- Section title: {chunk.section_title or 'null'}\n"
            f"- Page context: {page_context}\n"
            f"- Property scope: {canonical_block.scope_type}\n\n"
            "HTML content:\n"
            f"{chunk.content_html}"
        )

    async def _call_anthropic(self, *, system_prompt: str, user_prompt: str) -> tuple[str, dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                _ANTHROPIC_URL,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": _ANTHROPIC_VERSION,
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": self._max_output_tokens,
                    "temperature": 0.0,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            )
            response.raise_for_status()
            data = response.json()
        text = ""
        try:
            text = data["content"][0]["text"].strip()
        except (KeyError, IndexError, TypeError, AttributeError):
            text = ""
        return text, data.get("usage") or {}

    def _usage_from_payload(
        self,
        usage_payload: dict[str, Any],
        *,
        latency_ms: float,
        attempts: int,
        retry_count: int,
        retry_wait_time_seconds: float,
        failed_after_max_retries: bool,
    ) -> LLMUsage:
        input_tokens = int(usage_payload.get("input_tokens") or 0)
        output_tokens = int(usage_payload.get("output_tokens") or 0)
        estimated_cost = (
            (input_tokens / 1_000_000.0) * _INPUT_COST_PER_MILLION
            + (output_tokens / 1_000_000.0) * _OUTPUT_COST_PER_MILLION
        )
        return LLMUsage(
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost,
            latency_ms=latency_ms,
            attempts=attempts,
            retry_count=retry_count,
            retry_wait_time_seconds=retry_wait_time_seconds,
            failed_after_max_retries=failed_after_max_retries,
        )

    async def _record_usage(
        self,
        *,
        canonical_block: CanonicalBlock,
        chunk: ChunkedContent,
        usage: LLMUsage,
        success: bool,
        error_type: Optional[str],
    ) -> None:
        await LLMUsageTracker.record(
            service_name="llm_extractor",
            tenant_id=canonical_block.tenant_id,
            request_type="knowledge_extraction",
            provider="anthropic",
            model_id=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            success=success,
            latency_ms=int(usage.latency_ms),
            fallback_position=1,
            error_type=error_type,
            metadata={
                "chunk_id": chunk.chunk_id,
                "scope_type": canonical_block.scope_type,
                "canonical_page_id": canonical_block.canonical_page_id,
                "attempts": usage.attempts,
                "retry_count": usage.retry_count,
                "retry_wait_time_seconds": usage.retry_wait_time_seconds,
                "failed_after_max_retries": usage.failed_after_max_retries,
            },
        )

    def _response_error_type(self, response: httpx.Response) -> Optional[str]:
        try:
            payload = response.json()
        except Exception:
            return None
        error = payload.get("error")
        if isinstance(error, dict):
            value = error.get("type")
            return str(value).strip() if value else None
        return None

    def _should_retry_http(self, *, status: int, error_type: Optional[str], attempt: int) -> bool:
        if attempt >= self._retry_attempts:
            return False
        if status == 429:
            return True
        if 500 <= status < 600:
            return True
        return error_type in {"rate_limit_error", "overloaded_error", "api_error"}

    def _retry_delay_for_http(self, response: httpx.Response, *, attempt: int, status: int) -> float:
        if status == 429:
            retry_after = self._retry_after_seconds(response)
            if retry_after is not None:
                return retry_after
            base_delay = min(_DEFAULT_RATE_LIMIT_BASE_DELAY * (2 ** max(0, attempt - 1)), _DEFAULT_RATE_LIMIT_MAX_DELAY)
            return min(base_delay + self._jitter_seconds(), _DEFAULT_RATE_LIMIT_MAX_DELAY)
        return 0.5 * attempt

    def _retry_after_seconds(self, response: httpx.Response) -> Optional[float]:
        raw_value = response.headers.get("retry-after")
        if not raw_value:
            return None
        try:
            value = float(raw_value.strip())
        except (TypeError, ValueError):
            return None
        return max(0.0, value)

    def _jitter_seconds(self) -> float:
        return random.uniform(0.0, 1.0)

    async def _sleep(self, delay: float) -> None:
        await asyncio.sleep(delay)

    def _parse_and_validate_candidates(
        self,
        raw_text: str,
        chunk: ChunkedContent,
        canonical_block: CanonicalBlock,
    ) -> list[ExtractionCandidatePayload]:
        payload = self._extract_json_array(raw_text)
        if payload is None:
            logger.warning("[LLMExtractor] parse_failed chunk_id=%s", chunk.chunk_id)
            return []

        candidates: list[ExtractionCandidatePayload] = []
        for index, item in enumerate(payload):
            candidate = self._coerce_candidate(item, chunk, canonical_block, index=index)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def _extract_json_array(self, raw_text: str) -> Optional[list[Any]]:
        text_value = (raw_text or "").strip()
        if not text_value:
            return []
        try:
            parsed = json.loads(text_value)
            return parsed if isinstance(parsed, list) else None
        except json.JSONDecodeError:
            start = text_value.find("[")
            end = text_value.rfind("]")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                parsed = json.loads(text_value[start : end + 1])
                return parsed if isinstance(parsed, list) else None
            except json.JSONDecodeError:
                return None

    def _coerce_candidate(
        self,
        item: Any,
        chunk: ChunkedContent,
        canonical_block: CanonicalBlock,
        *,
        index: int,
    ) -> Optional[ExtractionCandidatePayload]:
        if not isinstance(item, dict):
            logger.warning("[LLMExtractor] invalid_item chunk_id=%s index=%s", chunk.chunk_id, index)
            return None

        question = _normalize_text(item.get("proposed_question_text"))
        answer = _normalize_text(item.get("proposed_answer_text"))
        evidence = _normalize_text(item.get("evidence_excerpt"))
        source_section = _normalize_text(item.get("source_section") or chunk.section_title or canonical_block.render_type)
        topic_id = item.get("proposed_topic_id")
        topic_id = _normalize_text(topic_id) or None
        uncertain = _coerce_bool(item.get("uncertain"))
        conditional = _coerce_bool(item.get("conditional"))
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            logger.warning("[LLMExtractor] invalid_confidence chunk_id=%s index=%s", chunk.chunk_id, index)
            return None

        if not question or not answer or not evidence:
            logger.warning("[LLMExtractor] missing_required_fields chunk_id=%s index=%s", chunk.chunk_id, index)
            return None
        if confidence < 0.0 or confidence > 1.0:
            logger.warning("[LLMExtractor] out_of_range_confidence chunk_id=%s index=%s", chunk.chunk_id, index)
            return None
        if topic_id is not None and topic_id not in TOPIC_REGISTRY:
            logger.warning("[LLMExtractor] unknown_topic chunk_id=%s topic_id=%s", chunk.chunk_id, topic_id)
            return None
        if not _normalized_substring(chunk.content_text, evidence):
            logger.warning("[LLMExtractor] evidence_not_in_source chunk_id=%s index=%s", chunk.chunk_id, index)
            return None

        metadata = {
            "render_type": canonical_block.render_type,
            "canonical_page_id": canonical_block.canonical_page_id,
            "canonical_source_property_id": str(canonical_block.canonical_source_property_id),
            "duplicate_count": canonical_block.duplicate_count,
            "block_hash": canonical_block.block_hash,
            "chunk_id": chunk.chunk_id,
            "chunk_section_title": chunk.section_title,
            "chunk_order_within_block": chunk.order_within_block,
            "chunk_metadata": _json_safe(chunk.metadata),
            "uncertain": uncertain,
            "conditional": conditional,
            "llm_model": self._model,
            "llm_source": "anthropic",
        }
        if canonical_block.duplicate_group_metadata:
            metadata["duplicate_group_metadata"] = _json_safe(canonical_block.duplicate_group_metadata)
        if canonical_block.scope_type == "tenant":
            metadata["tenant_scope_applies_to_count"] = len(canonical_block.applicable_property_ids)
        metadata["applicable_property_ids"] = [str(value) for value in canonical_block.applicable_property_ids]

        tags = ["llm_extracted"]
        if uncertain:
            tags.append("uncertain")
        if conditional:
            tags.append("conditional")
        if topic_id:
            tags.append(topic_id)

        return ExtractionCandidatePayload(
            scope_type=canonical_block.scope_type,
            scope_target_id=(
                str(canonical_block.tenant_id)
                if canonical_block.scope_type == "tenant"
                else str(canonical_block.canonical_source_property_id)
            ),
            source_type="guidebook",
            extraction_method="llm",
            candidate_type="fact",
            proposed_question_text=question,
            proposed_question_key=_normalize_question_key(question),
            proposed_answer_text=answer,
            proposed_topic_id=topic_id,
            proposed_tags=list(dict.fromkeys(tags)),
            proposed_metadata=metadata,
            confidence=confidence,
            evidence_excerpt=evidence,
            source_section=source_section,
        )
