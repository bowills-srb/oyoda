"""
InboundMessageGate: first-stage classifier for inbound emails.

Runs at the top of dispatch_pre_booking before any pre-booking-specific
DB-backed processing. The gate decides whether an inbound email is a real
guest message that should proceed into the existing guest pipeline, or
operational/marketing/system noise that should be skipped or reviewed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

import httpx

from app.services.observability.llm_usage_tracker import LLMCallTimer, LLMUsageTracker

logger = logging.getLogger(__name__)

PROCEED_CONFIDENCE_THRESHOLD = 0.7
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class InboundClassification(str, Enum):
    GUEST_MESSAGE = "guest_message"
    OPERATIONAL_NOTIFICATION = "operational_notification"
    MARKETING = "marketing"
    BOUNCE_OR_SYSTEM = "bounce_or_system"
    UNCLEAR = "unclear"


@dataclass(frozen=True)
class GateExtraction:
    guest_text: Optional[str] = None
    guest_name: Optional[str] = None
    property_reference: Optional[str] = None
    reply_path: Optional[str] = None
    thread_id: Optional[str] = None


@dataclass(frozen=True)
class GateDecision:
    decision_id: UUID
    classification: InboundClassification
    confidence: float
    reasoning: str
    extracted: Optional[GateExtraction]
    model: str
    raw_response: Optional[str] = None
    error: Optional[str] = None
    status_code: Optional[int] = None
    retryable: bool = False

    @property
    def should_proceed_as_guest(self) -> bool:
        return (
            self.classification == InboundClassification.GUEST_MESSAGE
            and self.confidence >= PROCEED_CONFIDENCE_THRESHOLD
        )

    @property
    def should_route_to_review(self) -> bool:
        if self.classification == InboundClassification.UNCLEAR:
            return True
        if (
            self.classification == InboundClassification.GUEST_MESSAGE
            and self.confidence < PROCEED_CONFIDENCE_THRESHOLD
        ):
            return True
        return False


GATE_SYSTEM_PROMPT = """You classify inbound emails arriving at a short-term-rental operator's inbox.
The operator uses Oyvoda, an AI concierge that drafts replies to guest inquiries. Your job is
to decide whether each email represents a real guest message that needs a reply, or some other
kind of email that should NOT trigger a guest-reply draft.

You will receive an email's headers (From, Subject, Reply-To, X-Template, X-Category, Return-Path)
and its body content. Return a structured classification.

CLASSIFICATION CATEGORIES:

guest_message: A real message from a guest or prospective guest that needs a reply. The body
contains the guest's actual words. The operator can and should respond to it.

operational_notification: An automated notification from a booking platform that is ABOUT a guest
interaction but is not itself the guest's message. Examples: Airbnb BOOKING_INITIAL_INQUIRY
notifications, RESERVATION_INQUIRIES_REMINDER emails, resolution-team notifications, booking
confirmations, cancellation notices, payout notifications, review reminders.

marketing: Promotional or marketing emails. Newsletters, vendor outreach, host tips, announcements.

bounce_or_system: Mail bounces, delivery failures, autoresponders, postmaster errors, calendar
invites, and other system-generated infrastructure mail.

unclear: You cannot confidently classify the email.

KEY DISCRIMINATORS:

1. Real guest messages contain the guest's voice. If the body is mostly telling the operator what
   to do ("Respond to Keri's inquiry", "You have 24 hours"), classify as operational_notification.

2. Real guest messages on Airbnb often come through express@airbnb.com with a reply.airbnb.com
   reply path. Airbnb automation often comes from automated@airbnb.com or uses templates like
   BOOKING_INITIAL_INQUIRY or RESERVATION_INQUIRIES_REMINDER.

3. The same guest message can arrive twice from Airbnb: once as automated@airbnb.com with no
   reply path (operational_notification) and once as express@airbnb.com with a reply path
   (guest_message). Only the second one is the canonical guest_message.

4. If From contains a guest's name but the address is a platform domain, the display name alone is
   not enough to call it a guest message. Read the body.

5. Real guest messages from Vrbo/HomeAway often come from sender@messages.homeaway.com or similar
   platform-relay addresses, with a Reply-To routed back through messages.homeaway.com or Vrbo's
   relay. The body contains the guest's text in their own voice. Vrbo also sends operational
   notifications such as booking confirmations, payout notices, and reminders; those are
   operational_notification.

EXTRACTION:

When and only when classification is guest_message, extract:
- guest_text
- guest_name
- property_reference
- reply_path
- thread_id

For all other classifications, extracted should be null.

OUTPUT FORMAT:

Respond with a single JSON object, no markdown fences, no commentary:
{
  "classification": "<one of the five categories>",
  "confidence": <float between 0.0 and 1.0>,
  "reasoning": "<one or two sentence explanation>",
  "extracted": {
    "guest_text": "...",
    "guest_name": "...",
    "property_reference": "...",
    "reply_path": "...",
    "thread_id": "..."
  } | null
}

Be honest about confidence. If you are not sure, prefer unclear.
"""


class InboundMessageGate:
    """Classify an inbound email without raising exceptions to callers."""

    def __init__(
        self,
        *,
        anthropic_api_key: Optional[str] = None,
        model: str = "claude-haiku-4-5",
        timeout_s: float = 5.0,
        max_tokens: int = 768,
    ) -> None:
        self._api_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY", "").strip()
        self._model = model
        self._timeout_s = timeout_s
        self._max_tokens = max_tokens

    async def classify(
        self,
        *,
        tenant_id: UUID | None = None,
        from_header: str,
        subject: str,
        reply_to: Optional[str],
        x_template: Optional[str],
        x_category: Optional[str],
        return_path: Optional[str],
        body_text: str,
    ) -> GateDecision:
        decision_id = uuid4()
        if not self._api_key:
            return GateDecision(
                decision_id=decision_id,
                classification=InboundClassification.UNCLEAR,
                confidence=0.0,
                reasoning="gate API key missing",
                extracted=None,
                model=self._model,
                raw_response=None,
                error="ANTHROPIC_API_KEY missing",
            )

        user_content = self._build_user_message(
            from_header=from_header,
            subject=subject,
            reply_to=reply_to,
            x_template=x_template,
            x_category=x_category,
            return_path=return_path,
            body_text=(body_text or "")[:8000],
        )
        timer = LLMCallTimer()
        metadata = {
            "body_chars": len(body_text or ""),
            "has_reply_to": bool(reply_to),
            "x_template": x_template or "",
            "x_category": x_category or "",
        }

        try:
            raw_text, input_tokens, output_tokens = await self._call_anthropic(user_content)
        except Exception as exc:
            status_code = self._extract_status_code(str(exc))
            retryable = self._extract_retryable(str(exc))
            detail = str(exc).strip() or type(exc).__name__
            await self._record_usage(
                tenant_id=tenant_id,
                input_tokens=0,
                output_tokens=0,
                success=False,
                latency_ms=timer.elapsed_ms(),
                error_type=type(exc).__name__,
                metadata=metadata,
            )
            logger.error(
                "[InboundGate] anthropic_call_failed exception_type=%s message=%s",
                type(exc).__name__,
                detail,
                exc_info=True,
            )
            return GateDecision(
                decision_id=decision_id,
                classification=InboundClassification.UNCLEAR,
                confidence=0.0,
                reasoning=f"gate API call failed: {detail}",
                extracted=None,
                model=self._model,
                raw_response=None,
                error=detail,
                status_code=status_code,
                retryable=retryable,
            )
        await self._record_usage(
            tenant_id=tenant_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            success=True,
            latency_ms=timer.elapsed_ms(),
            error_type=None,
            metadata=metadata,
        )

        try:
            parsed = self._parse_classification(raw_text)
        except ValueError as exc:
            logger.error(
                "[InboundGate] response_parse_failed error=%s raw=%r",
                exc,
                raw_text[:500],
            )
            return GateDecision(
                decision_id=decision_id,
                classification=InboundClassification.UNCLEAR,
                confidence=0.0,
                reasoning=f"could not parse gate response: {exc}",
                extracted=None,
                model=self._model,
                raw_response=raw_text,
                error=str(exc),
            )

        return GateDecision(
            decision_id=decision_id,
            classification=parsed["classification"],
            confidence=parsed["confidence"],
            reasoning=parsed["reasoning"],
            extracted=parsed["extracted"],
            model=self._model,
            raw_response=raw_text,
            error=None,
        )

    async def _record_usage(
        self,
        *,
        tenant_id: UUID | None,
        input_tokens: int,
        output_tokens: int,
        success: bool,
        latency_ms: int,
        error_type: Optional[str],
        metadata: dict[str, Any],
    ) -> None:
        await LLMUsageTracker.record(
            service_name="inbound_message_gate",
            tenant_id=tenant_id,
            request_type="inbound_gate_classification",
            provider="anthropic",
            model_id=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            success=success,
            latency_ms=latency_ms,
            error_type=error_type,
            metadata=metadata,
        )

    async def _call_anthropic(self, user_content: str) -> tuple[str, int, int]:
        payload = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": GATE_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_content}],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        attempts = 3
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            for attempt in range(1, attempts + 1):
                try:
                    response = await client.post(_ANTHROPIC_URL, headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    usage = data.get("usage") or {}
                    return (
                        self._extract_text(data),
                        int(usage.get("input_tokens") or 0),
                        int(usage.get("output_tokens") or 0),
                    )
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    retryable = status_code in _RETRYABLE_STATUS_CODES
                    if retryable and attempt < attempts:
                        await asyncio.sleep(0.25 * attempt)
                        continue
                    raise RuntimeError(
                        self._format_http_error(exc, retryable=retryable)
                    ) from exc
                except httpx.TimeoutException as exc:
                    if attempt < attempts:
                        await asyncio.sleep(0.25 * attempt)
                        continue
                    raise RuntimeError("timeout retryable=true") from exc

    @staticmethod
    def _format_http_error(exc: httpx.HTTPStatusError, *, retryable: bool) -> str:
        status_code = exc.response.status_code
        body_preview = ""
        try:
            body_preview = (exc.response.text or "").strip().replace("\n", " ")[:200]
        except Exception:
            body_preview = ""
        detail = f"status={status_code} retryable={str(retryable).lower()}"
        if body_preview:
            detail = f"{detail} body={body_preview}"
        return detail

    @staticmethod
    def _build_user_message(
        *,
        from_header: str,
        subject: str,
        reply_to: Optional[str],
        x_template: Optional[str],
        x_category: Optional[str],
        return_path: Optional[str],
        body_text: str,
    ) -> str:
        return "\n".join(
            [
                "Classify the following inbound email.",
                "",
                "HEADERS:",
                f"From: {from_header or '(none)'}",
                f"Subject: {subject or '(none)'}",
                f"Reply-To: {reply_to or '(none)'}",
                f"X-Template: {x_template or '(none)'}",
                f"X-Category: {x_category or '(none)'}",
                f"Return-Path: {return_path or '(none)'}",
                "",
                "BODY:",
                body_text or "(empty)",
            ]
        )

    @staticmethod
    def _extract_text(response: Any) -> str:
        try:
            for block in response.get("content", []):
                if block.get("type") == "text":
                    return str(block.get("text") or "")
        except Exception:
            pass
        return ""

    @staticmethod
    def _extract_status_code(detail: str) -> Optional[int]:
        match = None
        try:
            import re

            match = re.search(r"status=(\d{3})", detail or "")
        except Exception:
            return None
        if not match:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_retryable(detail: str) -> bool:
        return "retryable=true" in (detail or "").lower()

    @staticmethod
    def _parse_classification(raw: str) -> dict[str, Any]:
        if not raw:
            raise ValueError("empty response")

        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError("response is not an object")

        cls_value = data.get("classification")
        if cls_value not in {c.value for c in InboundClassification}:
            raise ValueError(f"invalid classification: {cls_value!r}")
        classification = InboundClassification(cls_value)

        confidence = data.get("confidence")
        if not isinstance(confidence, (int, float)):
            raise ValueError(f"confidence is not a number: {confidence!r}")
        confidence = float(confidence)
        if confidence < 0.0 or confidence > 1.0:
            raise ValueError(f"confidence out of range: {confidence}")

        reasoning = data.get("reasoning") or ""
        if not isinstance(reasoning, str):
            reasoning = str(reasoning)

        extracted: Optional[GateExtraction] = None
        extracted_raw = data.get("extracted")
        if classification == InboundClassification.GUEST_MESSAGE and isinstance(extracted_raw, dict):
            extracted = GateExtraction(
                guest_text=extracted_raw.get("guest_text") or None,
                guest_name=extracted_raw.get("guest_name") or None,
                property_reference=extracted_raw.get("property_reference") or None,
                reply_path=extracted_raw.get("reply_path") or None,
                thread_id=extracted_raw.get("thread_id") or None,
            )

        return {
            "classification": classification,
            "confidence": confidence,
            "reasoning": reasoning,
            "extracted": extracted,
        }
