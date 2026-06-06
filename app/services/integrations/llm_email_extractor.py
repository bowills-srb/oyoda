from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from email.utils import parseaddr
from typing import Any, Dict, Optional
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.services.observability.llm_usage_tracker import LLMCallTimer, LLMUsageTracker
from app.services.integrations.property_mention_surfaces import (
    build_surface_audit_payload,
    dissect_thread_surfaces,
    extract_property_mention_candidates,
    select_best_candidate,
)


logger = logging.getLogger(__name__)

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _re_search_first(pattern: str, text: str, *, flags: int = re.I) -> str:
    match = re.search(pattern, text or "", flags)
    if not match:
        return ""
    return str(match.group(1) or "").strip()

PROMPT = """You extract structured guest-inquiry data from inbound vacation-rental emails.

You may receive:
- VRBO/HomeAway forwarded inquiry emails with heavy wrapper metadata
- Airbnb forwarded inquiry emails
- Direct guest emails
- Guest replies inside longer quoted threads
- Non-actionable emails like bounces, out-of-office replies, Gmail notifications, review reminders, or messages that contain only header markup

Your job:
1. Identify the latest actual guest-authored message, if one exists.
2. Extract property/date/guest metadata when it is clearly present.
3. Return ONE JSON object only. No markdown, no commentary.

Rules:
- `latest_guest_message` must be the guest's actual words from the newest actionable guest turn, not email headers, thread markup, CSS, boilerplate, or operator text.
- If there is no actionable guest inquiry, or the content is only metadata / markup / automated mail, return `latest_guest_message` as null.
- `property_code_or_name` may be any raw property identifier or property name seen in the email. Do not normalize or validate it.
- For dates, return ISO format `YYYY-MM-DD` only when explicit. Otherwise return null.
- `requested_guests` must be an integer or null.
- `sender_email` should be the best guest email if it is explicit; otherwise null.
- `sender_name` should be the best guest name if it is explicit; otherwise null.

Return exactly this JSON shape:
{
  "latest_guest_message": string | null,
  "property_code_or_name": string | null,
  "platform_listing_id": string | null,
  "platform_unit_id": string | null,
  "external_id": string | null,
  "provider_account_id": string | null,
  "provider_property_id": string | null,
  "requested_check_in": string | null,
  "requested_check_out": string | null,
  "requested_guests": integer | null,
  "sender_email": string | null,
  "sender_name": string | null
}"""


class LLMEmailExtractorFallback(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class LLMEmailExtractorParseFailure(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _ExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latest_guest_message: Optional[str] = None
    property_code_or_name: Optional[str] = None
    platform_listing_id: Optional[str] = None
    platform_unit_id: Optional[str] = None
    external_id: Optional[str] = None
    provider_account_id: Optional[str] = None
    provider_property_id: Optional[str] = None
    requested_check_in: Optional[str] = None
    requested_check_out: Optional[str] = None
    requested_guests: Optional[int] = None
    sender_email: Optional[str] = None
    sender_name: Optional[str] = None


@dataclass(frozen=True)
class ExtractedEmailFields:
    latest_guest_message: str
    raw_property_mention: str
    platform_listing_id: str = ""
    platform_unit_id: str = ""
    external_id_hint: str = ""
    source_property_id: str = ""
    provider_property_id: str = ""
    provider_account_id: str = ""
    requested_check_in: Optional[date] = None
    requested_check_out: Optional[date] = None
    requested_guests: Optional[int] = None
    sender_email: str = ""
    sender_name: str = ""
    parser_source: str = ""
    parser_notes: list[str] = field(default_factory=list)
    property_mention_surface_audit: dict[str, Any] | None = None


@dataclass(frozen=True)
class _ProviderResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMEmailExtractor:
    def __init__(
        self,
        *,
        anthropic_key: Optional[str] = None,
        groq_key: Optional[str] = None,
        tenant_id: UUID | None = None,
        anthropic_model: str = "claude-haiku-4-5",
        groq_model: str = "meta-llama/llama-4-scout-17b-16e-instruct",
        timeout_seconds: float = 4.0,
        max_input_chars: int = 12000,
    ) -> None:
        self._anthropic_key = (
            anthropic_key if anthropic_key is not None else os.getenv("ANTHROPIC_API_KEY", "").strip()
        )
        self._groq_key = groq_key if groq_key is not None else os.getenv("GROQ_API_KEY", "").strip()
        self._tenant_id = tenant_id
        self._anthropic_model = anthropic_model
        self._groq_model = groq_model
        self._timeout_seconds = timeout_seconds
        self._max_input_chars = max_input_chars

    async def extract(
        self,
        *,
        source_message_id: str,
        detected_shape: str,
        subject: str,
        plain_text: str,
        raw_html: str,
        headers: Dict[str, str],
    ) -> ExtractedEmailFields:
        raw_chars = len((plain_text or "") + (raw_html or ""))
        logger.info(
            "[LLMEmailExtractor] start source_message_id=%s shape=%s raw_chars=%s",
            source_message_id or "unknown",
            detected_shape or "unknown",
            raw_chars,
        )

        if not self._anthropic_key and not self._groq_key:
            logger.warning(
                "[LLMEmailExtractor] fallback source_message_id=%s shape=%s reason=no_keys_configured",
                source_message_id or "unknown",
                detected_shape or "unknown",
            )
            raise LLMEmailExtractorFallback("no_keys_configured")

        prompt = self._build_prompt(
            subject=subject,
            plain_text=plain_text,
            raw_html=raw_html,
            headers=headers,
            detected_shape=detected_shape,
        )

        providers = [
            ("groq", self._groq_key, self._groq_model, self._call_groq),
            ("anthropic", self._anthropic_key, self._anthropic_model, self._call_anthropic),
        ]

        last_fallback_reason = "unknown"
        for fallback_position, (provider_name, key, model_id, fn) in enumerate(providers, start=1):
            if not key:
                continue
            timer = LLMCallTimer()
            try:
                raw_response = await fn(prompt)
                payload = self._parse_payload(raw_response.text)
                extracted = self._to_result(
                    payload,
                    provider_name,
                    subject=subject,
                    plain_text=plain_text,
                )
                await LLMUsageTracker.record(
                    service_name="llm_email_extractor",
                    tenant_id=self._tenant_id,
                    request_type="inbox_parse",
                    provider=provider_name,
                    model_id=model_id,
                    input_tokens=raw_response.input_tokens,
                    output_tokens=raw_response.output_tokens,
                    success=True,
                    latency_ms=timer.elapsed_ms(),
                    fallback_position=fallback_position,
                    metadata={
                        "source_message_id": source_message_id or "",
                        "detected_shape": detected_shape or "",
                    },
                )
                logger.info(
                    "[LLMEmailExtractor] success source_message_id=%s shape=%s provider=%s fallback_fired=false",
                    source_message_id or "unknown",
                    detected_shape or "unknown",
                    provider_name,
                )
                return extracted
            except LLMEmailExtractorParseFailure:
                await LLMUsageTracker.record(
                    service_name="llm_email_extractor",
                    tenant_id=self._tenant_id,
                    request_type="inbox_parse",
                    provider=provider_name,
                    model_id=model_id,
                    input_tokens=0,
                    output_tokens=0,
                    success=False,
                    latency_ms=timer.elapsed_ms(),
                    fallback_position=fallback_position,
                    error_type="parse_failure",
                    metadata={
                        "source_message_id": source_message_id or "",
                        "detected_shape": detected_shape or "",
                    },
                )
                logger.warning(
                    "[LLMEmailExtractor] parse_failure source_message_id=%s shape=%s provider=%s",
                    source_message_id or "unknown",
                    detected_shape or "unknown",
                    provider_name,
                )
                raise
            except LLMEmailExtractorFallback as exc:
                last_fallback_reason = f"{provider_name}:{exc.reason}"
                await LLMUsageTracker.record(
                    service_name="llm_email_extractor",
                    tenant_id=self._tenant_id,
                    request_type="inbox_parse",
                    provider=provider_name,
                    model_id=model_id,
                    input_tokens=0,
                    output_tokens=0,
                    success=False,
                    latency_ms=timer.elapsed_ms(),
                    fallback_position=fallback_position,
                    error_type=exc.reason,
                    metadata={
                        "source_message_id": source_message_id or "",
                        "detected_shape": detected_shape or "",
                    },
                )
                logger.warning(
                    "[LLMEmailExtractor] fallback source_message_id=%s shape=%s provider=%s reason=%s",
                    source_message_id or "unknown",
                    detected_shape or "unknown",
                    provider_name,
                    exc.reason,
                )

        raise LLMEmailExtractorFallback(last_fallback_reason)

    def _build_prompt(
        self,
        *,
        subject: str,
        plain_text: str,
        raw_html: str,
        headers: Dict[str, str],
        detected_shape: str,
    ) -> str:
        header_lines = []
        for key in ("From", "Reply-To", "To", "Subject", "Date", "Message-ID"):
            value = headers.get(key) or headers.get(key.lower()) or ""
            if value:
                header_lines.append(f"{key}: {value}")
        plain_excerpt = (plain_text or "")[: self._max_input_chars]
        html_excerpt = (raw_html or "")[: self._max_input_chars]
        return (
            f"{PROMPT}\n\n"
            f"Detected shape: {detected_shape or 'unknown'}\n\n"
            f"Headers:\n{chr(10).join(header_lines) or '(none)'}\n\n"
            f"Plain text body:\n{plain_excerpt or '(empty)'}\n\n"
            f"HTML excerpt:\n{html_excerpt or '(empty)'}\n"
        )

    def _parse_payload(self, raw_response: str) -> _ExtractionPayload:
        text = (raw_response or "").strip()
        if not text:
            raise LLMEmailExtractorFallback("empty_response")
        try:
            return _ExtractionPayload.model_validate_json(text)
        except ValidationError as exc:
            raise LLMEmailExtractorFallback(f"invalid_schema:{exc.errors()[0].get('type', 'validation_error')}") from exc
        except Exception as exc:
            raise LLMEmailExtractorFallback(f"invalid_json:{type(exc).__name__}") from exc

    def _to_result(
        self,
        payload: _ExtractionPayload,
        provider_name: str,
        *,
        subject: str,
        plain_text: str,
    ) -> ExtractedEmailFields:
        latest_guest_message = (payload.latest_guest_message or "").strip()
        if len(latest_guest_message) < 5:
            raise LLMEmailExtractorParseFailure("empty_latest_guest_message")

        requested_guests = payload.requested_guests
        if requested_guests is not None and requested_guests <= 0:
            requested_guests = None

        sender_email = (payload.sender_email or "").strip().lower()
        if sender_email:
            sender_email = parseaddr(sender_email)[1].lower() or sender_email

        sender_name = (payload.sender_name or "").strip()
        raw_property_mention = (payload.property_code_or_name or "").strip()
        identity_hints = self._extract_identity_hints(subject=subject, plain_text=plain_text)
        platform_listing_id = (
            (payload.platform_listing_id or "").strip()
            or identity_hints["platform_listing_id"]
        )
        platform_unit_id = (
            (payload.platform_unit_id or "").strip()
            or identity_hints["platform_unit_id"]
        )
        external_id_hint = (
            (payload.external_id or "").strip()
            or identity_hints["external_id_hint"]
        )
        provider_account_id = (
            (payload.provider_account_id or "").strip()
            or identity_hints["provider_account_id"]
        )
        provider_property_id = (
            (payload.provider_property_id or "").strip()
            or identity_hints["provider_property_id"]
        )
        source_property_id = identity_hints["source_property_id"] or provider_property_id
        latest_body, quoted_context = dissect_thread_surfaces(plain_text or "")
        candidates = extract_property_mention_candidates(
            subject=subject,
            latest_body=latest_body or plain_text,
            quoted_context=quoted_context,
        )
        best_candidate = select_best_candidate(candidates)
        normalized_extracted = " ".join(raw_property_mention.casefold().split())
        agreement = None
        if raw_property_mention and best_candidate is not None:
            agreement = " ".join(best_candidate.mention.casefold().split()) == normalized_extracted
        surface_audit = build_surface_audit_payload(
            parser_path="llm_primary",
            extracted_mention=raw_property_mention,
            subject=subject,
            latest_body=latest_body or plain_text,
            quoted_context=quoted_context,
            agreement=agreement,
        )

        return ExtractedEmailFields(
            latest_guest_message=latest_guest_message,
            raw_property_mention=raw_property_mention,
            platform_listing_id=platform_listing_id,
            platform_unit_id=platform_unit_id,
            external_id_hint=external_id_hint,
            source_property_id=source_property_id,
            provider_property_id=provider_property_id,
            provider_account_id=provider_account_id,
            requested_check_in=_parse_iso_date(payload.requested_check_in),
            requested_check_out=_parse_iso_date(payload.requested_check_out),
            requested_guests=requested_guests,
            sender_email=sender_email,
            sender_name=sender_name,
            parser_source=f"llm_email_extractor_{provider_name}",
            parser_notes=[
                f"llm_provider:{provider_name}",
                "llm_primary_ingress",
            ],
            property_mention_surface_audit=surface_audit,
        )

    def _extract_identity_hints(self, *, subject: str, plain_text: str) -> dict[str, str]:
        text = plain_text or ""
        listing_match = _re_search_first(
            r"Vrbo\s*#\s*(\d+)",
            subject or "",
            flags=re.I,
        ) or _re_search_first(
            r"External ID\s+[\w-]+\s*#\s*(\d+)",
            text,
            flags=re.I | re.S,
        ) or _re_search_first(
            r"\bvrbo-(\d+)\b",
            text,
            flags=re.I,
        )
        unit_match = _re_search_first(r"\b(unit_[\w-]+)\b", text, flags=re.I)
        external_id = _re_search_first(r"External ID\s+([\w-]+)", text, flags=re.I)
        provider_account_id = ""
        provider_property_id = ""
        source_property_id = ""
        if external_id:
            account_match = re.match(r"(\d+)-(\d+)$", external_id)
            if account_match:
                provider_account_id = account_match.group(1)
                provider_property_id = account_match.group(2)
                source_property_id = account_match.group(2)
        return {
            "platform_listing_id": listing_match,
            "platform_unit_id": unit_match,
            "external_id_hint": f"ExternalID:{external_id}" if external_id else "",
            "provider_account_id": provider_account_id,
            "provider_property_id": provider_property_id,
            "source_property_id": source_property_id,
        }

    async def _call_anthropic(self, prompt: str) -> _ProviderResponse:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                resp = await client.post(
                    _ANTHROPIC_URL,
                    headers={
                        "x-api-key": self._anthropic_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._anthropic_model,
                        "max_tokens": 500,
                        "temperature": 0,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException as exc:
            raise LLMEmailExtractorFallback("timeout") from exc
        except Exception as exc:
            raise LLMEmailExtractorFallback(f"api_error:{type(exc).__name__}") from exc

        parts = data.get("content") or []
        text = "".join(
            str(part.get("text") or "")
            for part in parts
            if isinstance(part, dict)
        ).strip()
        if not text:
            raise LLMEmailExtractorFallback("empty_response")
        usage = data.get("usage") or {}
        return _ProviderResponse(
            text=text,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
        )

    async def _call_groq(self, prompt: str) -> _ProviderResponse:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                resp = await client.post(
                    _GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {self._groq_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._groq_model,
                        "temperature": 0,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": "Return JSON only."},
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException as exc:
            raise LLMEmailExtractorFallback("timeout") from exc
        except Exception as exc:
            raise LLMEmailExtractorFallback(f"api_error:{type(exc).__name__}") from exc

        choices = data.get("choices") or []
        if not choices:
            raise LLMEmailExtractorFallback("empty_response")
        message = choices[0].get("message") or {}
        text = str(message.get("content") or "").strip()
        if not text:
            raise LLMEmailExtractorFallback("empty_response")
        usage = data.get("usage") or {}
        return _ProviderResponse(
            text=text,
            input_tokens=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
        )


def _parse_iso_date(value: Optional[str]) -> Optional[date]:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None
