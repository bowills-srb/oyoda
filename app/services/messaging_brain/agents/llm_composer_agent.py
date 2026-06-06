"""
llm_composer_agent.py — LLM-based response composer for the messaging brain.

Session 12 (Phase C of docs/IMPLEMENTATION_QUEUE_2026_05_05.md) — see
docs/SESSION_12_COMPOSER_DESIGN.md for the full design.

Replaces the Phase 1.3a string-concatenation behavior in
GuestMessageBrainOrchestrator._compose_response with a real LLM-backed
synthesizer. The orchestrator already produces structured AgentDecisions
from specialists; the composer's job is to merge those decisions into a
single warm, grounded reply.

Provider chain:
    Anthropic Claude Haiku 4.5  (primary)
        ↓ (timeout / failure / no key)
    Groq llama-4-scout           (secondary)
        ↓ (timeout / failure / no key)
    Gemini 2.0 Flash             (tertiary)
        ↓ (timeout / failure / no key)
    Brain concatenation fallback (ultimate fallback — current
                                  _compose_response behavior)

Total budget: 6.0s. Per-provider timeout: 4.0s. The brain concatenation
fallback has no timeout — it's local string operations.

The agent is stateless across calls. Per-call metadata (provider,
latency, tokens, candidate output, notes) is returned via
ComposerMetadata so the orchestrator can attach it to the audit record.
There must be no mutable per-call state on self — the orchestrator may
share one instance across concurrent message handlers.

Default: not used in production. The orchestrator's _compose_response
selects between this composer and the Phase 1.3a concatenation at
message-handling time based on the MESSAGING_BRAIN_LLM_COMPOSER feature
flag, which defaults OFF. Session 12 ships the code; rollout work
(canary, shadow comparison, eventual full enable) lives in subsequent
sessions.

Vocabulary (from docs/SESSION_12_COMPOSER_DESIGN.md):
- "composer candidate output" — the text this agent produces, regardless
  of which provider or fallback produced it. Stored verbatim in
  ComposerMetadata.composer_response_text.
- "brain concatenation fallback" — the Phase 1.3a string-join behavior
  the orchestrator runs when the composer flag is off OR when all LLM
  providers in this agent fail. The composer's _compose_concatenation
  helper produces it.
- "operator-facing draft" — the response_text on the
  GuestResponseDraft returned to the caller. May or may not equal the
  composer candidate output, depending on shadow mode. The composer
  itself is unaware of shadow mode; that decision lives in the
  orchestrator.

The discipline rule embedded in the prompt mirrors the legacy path's
uncertainty-handling: "If the relevant property facts, operator
guidance, or specialist evidence is missing or uncertain, do not
guess." Specialists' templated draft_text is supplied to the prompt
for tone and hedge preservation only — NOT as a fact source. Facts
come from the typed context blocks. See SYSTEM_PROMPT_TEMPLATE below.

Multi-turn conversation history (Gap #1, 2026-05-06):
The composer reads `message.full_thread_text` as a DB-backed transcript
of prior guest turns and operator replies in this conversation. When
present, it's rendered as Block 5 ("Conversation history so far") and
the newest guest turn shifts to Block 6. The history is loaded by
`app.services.messaging_brain.context.conversation_history.load_history_for_prompt`
at email-dispatch time and written into `message.full_thread_text` via
the EmailTransportAdapter's mapping of `payload.conversation_context`.
When `message.full_thread_text` is empty, Block 5 renders "(none)" and
Block 6 contains the guest's message — preserving the original five-block
shape for first-time threads.

Grounding heuristic (notes-only):
A small regex pass runs on every successful LLM output and appends
`composer_grounding_warning:*` notes for suspicious patterns
(numeric values, phone numbers, email addresses). It does NOT
invalidate output. The intent is to surface honest signal in the
audit row about where fabrication risk is concentrated, without
creating false-confidence. The authoritative grounding verdict is
owned by response_reviewer (adversarial review), not the composer.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import httpx

from app.services.observability.llm_usage_tracker import LLMUsageTracker
from app.services.orchestration.messaging_brain_contracts import (
    AgentDecision,
    ComposerMetadata,
    GuestContextBundle,
    InboundGuestMessage,
    RecommendedAction,
)

logger = logging.getLogger(__name__)


def _coerce_tenant_uuid(value: str | None) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# The system prompt
#
# Structure mirrors docs/SESSION_12_COMPOSER_DESIGN.md eight-block layout.
# Blocks 1-2 land in this template; blocks 3-7 are rendered into the user
# message at call time by _build_user_message.
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a guest-messaging composer for a vacation-rental operator. Your job
is to synthesize one warm, grounded reply from the structured specialist
decisions and verified facts the operator's system has already produced.

# Discipline rule (MOST IMPORTANT)

If the relevant property facts, operator guidance, or specialist evidence
is missing or uncertain, do not guess. The specialists in the input below have
already produced verified hold language for cases where they could not
answer cleanly — preserve their tone of "I'm confirming the detail" rather
than overwriting it with a confident-sounding guess. If a specialist
explicitly recommends CLARIFY and provides clarification questions, ask
those questions directly instead of sending a vague hedge.

Before composing your reply, decide whether you have enough context to
answer well. Default to answering directly. Only ask clarifying questions
when the guest can provide missing information that would materially change
your answer.

When a fact is missing, ask yourself: does the guest know it?
- If yes (dates, group size, what they mean by "celebrate", scope of the
  request, number/type of pets), ask one or two specific clarifying
  questions.
- If no (operator policy, an amenity detail, whether something is
  available, a factual property detail), say you'll confirm and follow up.

# Voice and style baseline

- Sound like a capable human host, not a corporate support team.
- Match the guest's energy level: casual guests can get casual warmth,
  formal guests can get a cleaner formal tone.
- Prefer plain, natural phrasing like "I can confirm that" or "two quick
  questions" over bureaucratic phrasing.
- If you need more information from the guest and the missing detail is
  something they can answer, ask for it directly.

# Clarify vs answer examples

- Clarify: "We'd like to host a gathering" → ask how many people and what
  kind of gathering.
- Clarify: "We're thinking summer with our extended family" → ask dates and
  group size if those details would change the answer.
- Clarify: "Can we bring pets?" when the operator policy needs pet details
  to answer cleanly → ask how many pets and what kind.
- Answer directly: "What time is check-in?" when the fact is present.
- Answer directly: "Are there beach chairs?" when the fact is present.
- Answer directly: "What is the wifi password?" when the fact is present.

# How to read the input

You will receive six blocks in the user message:

1. **Specialist decisions** — what each specialist concluded, the
   templated `draft_text` they produced, the `evidence_used` keys they
   cited, the `missing_info` they flagged, and any `risk_flags`. Use
   these for TONE and HEDGE PRESERVATION only. Do NOT derive facts from
   the specialist drafts themselves — facts come from blocks 2-4.

2. **Property facts** — typed property facts, house rules, access info,
   and reservation facts the system has already verified. THIS is your
   primary fact source.

3. **Operator House Rules & Policy** — free-form policy text the
   operator wrote in their dashboard. FOLLOW THESE EXACTLY. Operator
   policy ALWAYS overrides any specialist's draft language that
   conflicts with it.

4. **Learned Preferences** — cross-operator and per-operator preferences
   the system has learned. Apply when relevant.

5. **Conversation history so far** — a transcript of prior turns in
   this conversation, oldest first. Each turn is labeled with `[Guest, ...]`
   or `[Operator, ...]` and a timestamp. Use this for continuity:
   acknowledge what's already been said, do not repeat information you
   (the Operator) have already shared, do not contradict prior commitments.
   If this block says "(none)", treat the message in Block 6 as the first
   turn of a new conversation.

6. **The newest guest message to reply to** — the latest guest turn.
   Reply to this. The conversation history in Block 5 is supporting
   context; Block 6 is what your reply addresses.

# What to do

- Write 2-5 warm sentences, conversational not corporate.
- 2-5 sentences is fine when needed to answer clearly and ask a concise
  follow-up question.
- Ground every factual claim in blocks 2-4. If a fact isn't there, say
  you'll confirm.
- Preserve any specialist's "I'm confirming" hedges — don't replace them
  with confident-sounding guesses.
- If a specialist recommends CLARIFY or supplies clarification questions,
  treat that as a strong signal and prefer a warm clarifying question.
- Even if no specialist recommends CLARIFY, you may still ask a clarifying
  question when the guest can supply missing information and that would
  materially improve your answer.
- Apply operator policy from block 3 strictly. If a specialist's draft
  conflicts with operator policy (e.g. specialist is friendly about pets
  but operator policy is no-pets), the operator policy wins.
- Use Block 5 (conversation history) for continuity. If the operator
  has already answered something earlier in the thread, do not repeat
  it. Pick up where the conversation left off.

# What not to do

- Do NOT negotiate prices.
- Do NOT promise anything not listed in blocks 2-4.
- Do NOT include calls to action like "go ahead and book" or "submit a
  booking request" in pre-booking replies.
- Do NOT use filler phrases like "Great question!" or "I'd be happy
  to..."
- Do NOT say "our concierge team", "our team", or "we will reach out"
  unless block 3 explicitly describes a real team and wants that phrasing.
- Do NOT say "we'd be happy to discuss the possibility of..." when a
  direct answer or clarifying question would be clearer.
- Do NOT add cancellation-policy or terms-and-conditions disclaimers
  unless the guest asked about them.
- Do NOT restate the guest's own praise of the property back to them as
  filler.
- Do NOT invent neighborhood facts, vendor recommendations, or amenities
  not listed in blocks 2-4.
- Do NOT contradict any specialist's missing-info note. If a specialist
  said they're confirming a detail, preserve that hedge.
- Do NOT turn a guest's own phone number or contact detail into "text me"
  or "call us" language.
- Do NOT derive facts from the specialist drafts in block 1 — they
  exist for tone and hedge preservation only.
- Do NOT repeat information the Operator has already shared in Block 5.
  The guest has read those replies; treat them as common ground.
- Do NOT contradict commitments the Operator made in Block 5 (price
  promises, policy exceptions, scheduled details). Honor them.

# Output

Return ONLY the guest-facing reply text. No preamble, no commentary, no
markdown, no JSON wrapping. Plain text."""


# ─────────────────────────────────────────────────────────────────────────────
# Output validity checks
# ─────────────────────────────────────────────────────────────────────────────

# Length floor mirrors legacy _is_usable_draft (pre_booking_auto_send.py).
_MIN_OUTPUT_CHARS = 30

# Length cap from the design doc Q3 resolution: 2-3 sentences fit in ~700
# characters; anything longer suggests model rambling and we'd rather
# fall through to the next provider.
_MAX_OUTPUT_CHARS = 700

# Placeholder/refusal phrases the legacy path already catches. If the
# model returns text containing any of these, treat as invalid output
# and fall through.
_PLACEHOLDER_PHRASES: tuple[str, ...] = (
    "could not generate",
    "we captured this guest email",
    "i don't have enough information to",
    "unable to generate a response",
    "i cannot generate",
    "as an ai language model",
)


# ─────────────────────────────────────────────────────────────────────────────
# Notes-only grounding heuristic
#
# Narrow on purpose: this catches numbers, phone numbers, and email
# addresses that appeared in composer output. These are the categories
# where fabrication is concrete enough to flag without false-positive
# risk. Named entities, place names, amenity names, and other semantic
# fabrication categories are deliberately excluded — a regex on those
# would either miss real fabrication or false-positive constantly,
# either of which is worse than an honest "we don't check that yet."
#
# Output of _collect_grounding_warnings is appended to composer_notes
# but never invalidates the output. The orchestrator's audit row will
# carry the warnings so engineers can see where to focus the future
# real-grounding-pass work.
# ─────────────────────────────────────────────────────────────────────────────

_GROUNDING_WARNING_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    # Dollar amounts. $50, $1,200, $3.50.
    (
        "dollar_amount",
        re.compile(r"\$\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?\b"),
    ),
    # Bare percentage values. 15%, 7.5%.
    (
        "percentage",
        re.compile(r"\b\d{1,3}(?:\.\d+)?%"),
    ),
    # Time-of-day. 3pm, 11:30am, 4:00 PM.
    (
        "time_of_day",
        re.compile(r"\b\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?\b", re.IGNORECASE),
    ),
    # Phone-number-shaped. (555) 123-4567, 555-123-4567, 555.123.4567.
    (
        "phone_number",
        re.compile(
            r"\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b"
        ),
    ),
    # Email-address-shaped. someone@example.com.
    (
        "email_address",
        re.compile(
            r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
        ),
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# Public agent
# ─────────────────────────────────────────────────────────────────────────────


class LLMComposerAgent:
    """LLM-based response composer. Returns a ComposerMetadata payload
    containing the candidate output text plus provider/latency/token
    metadata. The orchestrator decides whether the candidate output
    becomes the operator-facing draft (depends on shadow mode); the
    composer itself is shadow-mode agnostic.

    Stateless across calls. Per-message state lives in local variables
    inside compose(); no mutable per-call state on self.
    """

    name = "LLMComposerAgent"

    def __init__(
        self,
        *,
        anthropic_key: Optional[str] = None,
        groq_key: Optional[str] = None,
        gemini_key: Optional[str] = None,
        per_provider_timeout_seconds: float = 4.0,
        total_budget_seconds: float = 6.0,
        model_anthropic: str = "claude-haiku-4-5",
        model_groq: str = "meta-llama/llama-4-scout-17b-16e-instruct",
        model_gemini: str = "gemini-2.0-flash",
        max_output_tokens: int = 500,
    ) -> None:
        self._anthropic_key = (
            anthropic_key
            if anthropic_key is not None
            else os.getenv("ANTHROPIC_API_KEY", "")
        )
        self._groq_key = (
            groq_key
            if groq_key is not None
            else os.getenv("GROQ_API_KEY", "")
        )
        self._gemini_key = (
            gemini_key
            if gemini_key is not None
            else (
                os.getenv("GEMINI_API_KEY", "")
                or os.getenv("GOOGLE_API_KEY", "")
            )
        )
        self._per_provider_timeout = per_provider_timeout_seconds
        self._total_budget = total_budget_seconds
        self._model_anthropic = model_anthropic
        self._model_groq = model_groq
        self._model_gemini = model_gemini
        self._max_output_tokens = max_output_tokens

    async def compose(
        self,
        *,
        message: InboundGuestMessage,
        decisions: List[AgentDecision],
        context: GuestContextBundle,
        include_learned_preferences: bool = False,
        missing_topic_ids: Optional[List[str]] = None,
    ) -> ComposerMetadata:
        """Produce a ComposerMetadata describing how the response was
        composed. composer_response_text is always populated — either
        with the LLM's output, the brain concatenation fallback, or the
        empty-decisions fallback line.

        The returned metadata is what the orchestrator attaches to the
        AgentAuditRecord. It also tells the orchestrator which text to
        use as the operator-facing draft (when shadow mode is off) or
        which text to record alongside the operator-facing draft (when
        shadow mode is on).
        """
        start = time.monotonic()
        notes: List[str] = []

        # Empty decisions → existing fallback line. No LLM call attempted.
        if not decisions:
            text = (
                "Thanks for the message — I'll get back to you shortly."
            )
            return ComposerMetadata(
                composer_source="fallback_empty",
                composer_response_text=text,
                composer_latency_ms=int((time.monotonic() - start) * 1000),
                composer_input_tokens=None,
                composer_output_tokens=None,
                composer_notes=list(notes),
                clarification_chosen=self._looks_like_clarification(text),
            )

        user_message = self._build_user_message(
            message=message,
            decisions=decisions,
            context=context,
            include_learned_preferences=include_learned_preferences,
            missing_topic_ids=list(missing_topic_ids or []),
        )

        # Provider chain: Anthropic → Groq → Gemini → concatenation.
        provider_chain = [
            ("llm_anthropic", "anthropic", self._anthropic_key, self._call_anthropic),
            ("llm_groq", "groq", self._groq_key, self._call_groq),
            ("llm_gemini", "gemini", self._gemini_key, self._call_gemini),
        ]

        for source_label, provider_name, key, fn in provider_chain:
            if not key:
                notes.append(f"composer_no_key:{provider_name}")
                continue

            elapsed = time.monotonic() - start
            if elapsed >= self._total_budget:
                notes.append(
                    f"composer_budget_exhausted_before:{provider_name}"
                )
                break

            remaining = min(
                self._total_budget - elapsed,
                self._per_provider_timeout,
            )
            if remaining <= 0:
                notes.append(
                    f"composer_budget_exhausted_before:{provider_name}"
                )
                break

            provider_started = time.monotonic()
            fallback_position = len(
                [k for _, _, k, _ in provider_chain[: provider_chain.index((source_label, provider_name, key, fn)) + 1] if k]
            )
            response, provider_notes, input_tokens, output_tokens, error_type = (
                await self._try_provider(
                    provider=provider_name,
                    fn=fn,
                    user_message=user_message,
                    timeout_override=remaining,
                )
            )
            notes.extend(provider_notes)
            if response is None:
                await LLMUsageTracker.record(
                    service_name="brain_composer",
                    tenant_id=_coerce_tenant_uuid(message.tenant_id),
                    request_type="brain_draft_generation",
                    provider=provider_name,
                    model_id=self._provider_model_id(provider_name),
                    input_tokens=input_tokens or 0,
                    output_tokens=output_tokens or 0,
                    success=False,
                    latency_ms=int((time.monotonic() - provider_started) * 1000),
                    fallback_position=fallback_position,
                    error_type=error_type or "provider_failure",
                    metadata={
                        "message_id": message.message_id,
                        "property_code": message.property_code or "",
                        "composer_source": source_label,
                    },
                )
                continue

            text = (response.get("text") or "").strip()
            invalid_reason = self._validate_output(text)
            if invalid_reason:
                await LLMUsageTracker.record(
                    service_name="brain_composer",
                    tenant_id=_coerce_tenant_uuid(message.tenant_id),
                    request_type="brain_draft_generation",
                    provider=provider_name,
                    model_id=self._provider_model_id(provider_name),
                    input_tokens=input_tokens or 0,
                    output_tokens=output_tokens or 0,
                    success=False,
                    latency_ms=int((time.monotonic() - provider_started) * 1000),
                    fallback_position=fallback_position,
                    error_type="invalid_output",
                    metadata={
                        "message_id": message.message_id,
                        "property_code": message.property_code or "",
                        "composer_source": source_label,
                        "invalid_reason": invalid_reason,
                    },
                )
                notes.append(
                    f"composer_invalid_output:{provider_name}:{invalid_reason}"
                )
                continue

            # Notes-only grounding heuristic. Never invalidates output.
            grounding_warnings = self._collect_grounding_warnings(text)
            notes.extend(grounding_warnings)
            await LLMUsageTracker.record(
                service_name="brain_composer",
                tenant_id=_coerce_tenant_uuid(message.tenant_id),
                request_type="brain_draft_generation",
                provider=provider_name,
                model_id=self._provider_model_id(provider_name),
                input_tokens=input_tokens or 0,
                output_tokens=output_tokens or 0,
                success=True,
                latency_ms=int((time.monotonic() - provider_started) * 1000),
                fallback_position=fallback_position,
                metadata={
                    "message_id": message.message_id,
                    "property_code": message.property_code or "",
                    "composer_source": source_label,
                },
            )

            return ComposerMetadata(
                composer_source=source_label,
                composer_response_text=text,
                composer_latency_ms=int((time.monotonic() - start) * 1000),
                composer_input_tokens=input_tokens,
                composer_output_tokens=output_tokens,
                composer_notes=list(notes),
                clarification_chosen=self._looks_like_clarification(text),
            )

        # All LLM providers exhausted. Fall through to brain concatenation.
        if not (self._anthropic_key or self._groq_key or self._gemini_key):
            notes.append("composer_no_keys_configured")
        else:
            notes.append("composer_all_providers_failed")

        concatenated = self._compose_concatenation(decisions)
        return ComposerMetadata(
            composer_source="fallback_concatenation",
            composer_response_text=concatenated,
            composer_latency_ms=int((time.monotonic() - start) * 1000),
            composer_input_tokens=None,
            composer_output_tokens=None,
            composer_notes=list(notes),
            clarification_chosen=self._looks_like_clarification(concatenated),
        )

    # ── Provider call wrapper ───────────────────────────────────────────────

    async def _try_provider(
        self,
        *,
        provider: str,
        fn: Any,
        user_message: str,
        timeout_override: Optional[float] = None,
    ) -> Tuple[Optional[Dict[str, Any]], List[str], Optional[int], Optional[int], Optional[str]]:
        """Wrap one provider call in timeout + exception handling.

        Returns (response_dict_or_None, notes, input_tokens, output_tokens).
        Mirrors LLMIntakeAgent._try_provider's contract including the
        backward-compat (text, usage_dict) tuple shape so test mocks can
        stay simple.
        """
        notes: List[str] = []
        timeout = (
            timeout_override
            if timeout_override is not None
            else self._per_provider_timeout
        )

        try:
            response = await asyncio.wait_for(fn(user_message), timeout=timeout)
        except asyncio.TimeoutError:
            notes.append(f"composer_timeout:{provider}")
            return None, notes, None, None, "timeout"
        except Exception as exc:  # noqa: BLE001
            notes.append(
                f"composer_exception:{provider}:{type(exc).__name__}"
            )
            logger.warning(
                "[LLMComposerAgent] %s provider failed: %s", provider, exc,
            )
            return None, notes, None, None, type(exc).__name__

        if response is None:
            notes.append(f"composer_empty_response:{provider}")
            return None, notes, None, None, "empty_response"

        # Backward-compat test seam — accept (text, usage_dict) tuples.
        if isinstance(response, tuple) and len(response) == 2:
            text, usage = response
            usage = usage or {}
            response = {
                "text": text,
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            }

        text = response.get("text", "")
        input_tokens = response.get("input_tokens")
        output_tokens = response.get("output_tokens")
        if not text or not str(text).strip():
            notes.append(f"composer_empty_response:{provider}")
            return None, notes, input_tokens, output_tokens, "empty_response"

        return response, notes, input_tokens, output_tokens, None

    def _provider_model_id(self, provider: str) -> str:
        if provider == "anthropic":
            return self._model_anthropic
        if provider == "groq":
            return self._model_groq
        if provider == "gemini":
            return self._model_gemini
        return "unknown"

    # ── Provider implementations ────────────────────────────────────────────

    async def _call_anthropic(
        self,
        user_message: str,
    ) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self._per_provider_timeout) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model_anthropic,
                    "max_tokens": self._max_output_tokens,
                    "system": SYSTEM_PROMPT,
                    "messages": [
                        {"role": "user", "content": user_message},
                    ],
                    "temperature": 0.5,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        try:
            text = data["content"][0]["text"]
        except (KeyError, IndexError, TypeError):
            return None

        usage = data.get("usage") or {}
        return {
            "text": text,
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        }

    async def _call_groq(
        self,
        user_message: str,
    ) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self._per_provider_timeout) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._groq_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model_groq,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    "max_tokens": self._max_output_tokens,
                    "temperature": 0.5,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None

        usage = data.get("usage") or {}
        return {
            "text": text,
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
        }

    async def _call_gemini(
        self,
        user_message: str,
    ) -> Optional[Dict[str, Any]]:
        # Gemini's REST endpoint accepts the API key as a query param
        # and uses a different request shape than Anthropic/Groq.
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model_gemini}:generateContent?key={self._gemini_key}"
        )
        async with httpx.AsyncClient(timeout=self._per_provider_timeout) as client:
            resp = await client.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "system_instruction": {
                        "parts": [{"text": SYSTEM_PROMPT}],
                    },
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": user_message}],
                        },
                    ],
                    "generationConfig": {
                        "temperature": 0.5,
                        "maxOutputTokens": self._max_output_tokens,
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()

        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            return None

        usage = data.get("usageMetadata") or {}
        return {
            "text": text,
            "input_tokens": usage.get("promptTokenCount"),
            "output_tokens": usage.get("candidatesTokenCount"),
        }

    # ── Output validation ───────────────────────────────────────────────────

    @staticmethod
    def _validate_output(text: str) -> Optional[str]:
        """Return None if the text passes validity checks; otherwise
        return a short reason string for the audit notes."""
        if not text:
            return "empty"
        stripped = text.strip()
        if len(stripped) < _MIN_OUTPUT_CHARS:
            return f"too_short:{len(stripped)}"
        if len(stripped) > _MAX_OUTPUT_CHARS:
            return f"too_long:{len(stripped)}"
        lowered = stripped.lower()
        for phrase in _PLACEHOLDER_PHRASES:
            if phrase in lowered:
                return f"placeholder_phrase:{phrase}"
        return None

    @staticmethod
    def _collect_grounding_warnings(text: str) -> List[str]:
        """Notes-only grounding heuristic.

        Returns a list of `composer_grounding_warning:*` strings for each
        suspicious pattern matched in the composer output. Never raises,
        never invalidates output.

        Patterns checked: dollar amounts, percentages, time-of-day,
        phone numbers, email addresses. These are concrete fabrication
        categories worth flagging because they're often invented when
        the property facts don't carry them. Semantic fabrication
        (named entities, place names, amenity claims) is deliberately
        excluded — a regex on those would mislead more than help.

        The orchestrator persists these notes alongside the rest of
        composer_notes in the audit row. Engineers reviewing flagged
        rows should treat these as "look at this output more carefully,"
        not as "this output is wrong."
        """
        if not text:
            return []
        warnings: List[str] = []
        for label, pattern in _GROUNDING_WARNING_PATTERNS:
            for match in pattern.findall(text):
                # Truncate the match in the note to keep it small.
                snippet = match if len(match) <= 40 else match[:37] + "..."
                warnings.append(
                    f"composer_grounding_warning:{label}:{snippet}"
                )
        return warnings

    @staticmethod
    def _looks_like_clarification(text: str) -> bool:
        stripped = (text or "").strip().lower()
        if not stripped or "?" not in stripped:
            return False
        clarify_markers = (
            "could you",
            "can you",
            "what dates",
            "which dates",
            "how many",
            "what kind",
            "are you picturing",
            "would you mind sharing",
        )
        return any(marker in stripped for marker in clarify_markers)

    # ── Brain concatenation fallback ────────────────────────────────────────

    @staticmethod
    def _compose_concatenation(decisions: List[AgentDecision]) -> str:
        """Phase 1.3a's behavior — concatenate non-empty draft_text with
        a blank line between. The orchestrator's _compose_response uses
        the same logic; we duplicate it here so the composer can return
        a meaningful `composer_response_text` even when all LLM
        providers fail (the audit row records what the operator saw).

        Kept byte-identical to the orchestrator's fallback path so a
        future cleanup can extract this into a single shared helper.
        """
        parts = [d.draft_text.strip() for d in decisions if d.draft_text.strip()]
        if not parts:
            return "Thanks for the message — I'll get back to you shortly."
        return "\n\n".join(parts)

    # ── User-message construction ───────────────────────────────────────────

    @staticmethod
    def _build_user_message(
        *,
        message: InboundGuestMessage,
        decisions: List[AgentDecision],
        context: GuestContextBundle,
        include_learned_preferences: bool,
        missing_topic_ids: List[str],
    ) -> str:
        """Render the six input blocks the prompt expects (specialist
        decisions, property facts, operator guidance, learned preferences,
        conversation history, newest guest message) into a single
        user-message string.

        Block order matches the SYSTEM_PROMPT's "How to read the input"
        section. Empty blocks render with a "(none)" sentinel rather
        than being omitted, so the model sees consistent structure.

        Block 5 (Conversation history so far) is sourced from
        message.full_thread_text, which the email transport adapter
        populates from payload.conversation_context. When the email
        dispatcher has injected DB-backed history, that's the formatted
        transcript from
        `app.services.messaging_brain.context.conversation_history.format_turns_for_prompt`.
        When no DB history was available, this falls through to whatever
        the parser extracted from the email body's quoted history (which
        may be empty for first-time threads — Block 5 then renders
        "(none)").
        """
        sections: List[str] = []

        # Block 1 — specialist decisions
        sections.append("## 1. Specialist decisions")
        if not decisions:
            sections.append("(none)")
        else:
            for idx, d in enumerate(decisions, 1):
                lines = [
                    f"### Decision {idx}: {d.agent_name}",
                    f"- intent_topic: {d.intent_topic}",
                    f"- confidence: {d.confidence:.2f}",
                    f"- recommended_action: {d.recommended_action.value}",
                ]
                if d.evidence_used:
                    lines.append(
                        f"- evidence_used: {', '.join(d.evidence_used)}"
                    )
                if d.missing_info:
                    lines.append(
                        f"- missing_info: {', '.join(d.missing_info)}"
                    )
                if d.clarification_questions:
                    lines.append(
                        "- clarification_questions: "
                        + " | ".join(d.clarification_questions)
                    )
                if d.risk_flags:
                    lines.append(
                        f"- risk_flags: {', '.join(d.risk_flags)}"
                    )
                if d.draft_text:
                    lines.append(
                        f"- draft_text (TONE/HEDGE REFERENCE ONLY, "
                        f"not a fact source):\n  {d.draft_text}"
                    )
                if d.answer_summary:
                    lines.append(f"- answer_summary: {d.answer_summary}")
                sections.append("\n".join(lines))

        # Block 2 — property facts
        sections.append("## 2. Property facts")
        fact_blocks: List[str] = []
        if context.property_facts:
            fact_blocks.append("### property_facts")
            for k, v in context.property_facts.items():
                fact_blocks.append(f"- {k}: {v}")
        if context.house_rules:
            fact_blocks.append("### house_rules")
            for k, v in context.house_rules.items():
                fact_blocks.append(f"- {k}: {v}")
        if context.access_info:
            fact_blocks.append("### access_info")
            for k, v in context.access_info.items():
                fact_blocks.append(f"- {k}: {v}")
        if context.reservation_facts:
            fact_blocks.append("### reservation_facts")
            for k, v in context.reservation_facts.items():
                fact_blocks.append(f"- {k}: {v}")
        if context.property_knowledge:
            fact_blocks.append("### property_knowledge")
            # Keep this compact — full FAQ can be long.
            for k, v in list(context.property_knowledge.items())[:10]:
                fact_blocks.append(f"- {k}: {v}")
        if not fact_blocks:
            fact_blocks.append("(none)")
        sections.append("\n".join(fact_blocks))

        # Block 3 — operator House Rules & Policy (B1's payload)
        sections.append("## 3. Operator House Rules & Policy (FOLLOW THESE EXACTLY)")
        if context.operator_guidance:
            sections.append(context.operator_guidance)
        else:
            sections.append("(none)")

        # Block 4 — learned preferences
        sections.append("## 4. Learned Preferences")
        if include_learned_preferences and context.learned_preferences_block:
            sections.append(context.learned_preferences_block)
        else:
            sections.append("(none)")

        # Block 5 — conversation history so far
        # Sourced from message.full_thread_text. When the email dispatcher
        # injected DB-backed prior turns, this is a structured transcript
        # (see conversation_history_service.format_turns_for_prompt). When
        # not, this falls back to whatever quoted history the parser
        # extracted from the email body. Both paths land in the same
        # field; the model just sees a transcript-shaped input.
        sections.append("## 5. Conversation history so far")
        thread_history = (message.full_thread_text or "").strip()
        if thread_history:
            sections.append(thread_history)
        else:
            sections.append("(none)")

        # Block 6 — the newest guest message
        sections.append("## 6. Newest guest message to reply to")
        sections.append(message.text or "(empty)")

        # Block 7 — hold-mode binding constraint (gate-identified gaps).
        # Only rendered when the answerability gate found missing facts.
        # This is a hard instruction: the LLM must hedge these topics
        # explicitly rather than inventing answers.
        if missing_topic_ids:
            sections.append("## 7. Missing information — hold-mode constraint")
            topic_list = "\n".join(f"- {tid}" for tid in missing_topic_ids)
            sections.append(
                f"{topic_list}\n\n"
                "**Instruction:** For each topic listed above, acknowledge the "
                "guest's question but do NOT invent an answer. Instead, tell them "
                "you will confirm and follow up. You may answer topics NOT listed "
                "here using the grounded facts in blocks 2–3."
            )

        return "\n\n".join(sections)
