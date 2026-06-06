# LLM Blind-Spot Instrumentation Plan

Date: 2026-05-27
Tenant under test: all tenants (blind-spot fixes are global)
Status: plan only, no code change yet
Anchor: [docs/scratch/LLM_USAGE_COVERAGE_AUDIT.md](LLM_USAGE_COVERAGE_AUDIT.md) (codex earlier this session)
Discipline: [docs/architecture/MIGRATION_DISCIPLINE.md](../architecture/MIGRATION_DISCIPLINE.md) — Principle 4 (route outcomes must be queryable truth) extended to "all LLM calls must be queryable truth in `llm_usage_events`"

## Purpose

Close the four production LLM call sites that currently make real provider
calls without recording into `llm_usage_events`. After this lands, every
LLM call in the brain pipeline is queryable through the same surface as
the already-instrumented call sites, and the admin LLM cost dashboard
becomes a complete picture rather than a partial one.

This is the smallest of the four phases and the most parallel-safe: it's
a pure additive code change, no behavior changes, no canonical-surface
contracts touched, no flag flips.

## Canonical-path classification

This phase only touches production LLM call sites that are either already
part of the brain-era canonical path or still-live transitional seams
around it. It is not instrumentation work for dead legacy code.

### Brain-era canonical or brain-adjacent

- `app/services/messaging_brain/inbound_message_gate.py`
  - brain-era inbound classification seam
  - already part of the canonical decision surface when enabled
- `app/services/voice/voice_session.py`
  - live guest voice runtime
  - not retired; still part of the active production interaction path

### Transitional but still live

- `app/services/knowledge/voice_pod.py`
  - live production post-booking path
  - still wraps older session-oriented seams while the migration continues
- `app/services/extraction/llm_extractor.py`
  - live document-ingest path
  - transitional because extraction ownership is still being consolidated,
    but it still affects real operator knowledge state today

### Explicit non-goal

Do not use Phase 4 to instrument paths that are effectively dead just
because they still import a model client. If implementation proves a target
is not actually live in production, stop and move it to the retirement list
instead of instrumenting it.

## What's currently tracked

Per the existing coverage audit, 8 LLM call paths already use
`LLMUsageTracker.record(...)`:

1. `llm_email_extractor` — email parser LLM extraction
2. `llm_intake_agent` — Groq/Anthropic intake classifier (reference example)
3. `llm_composer_agent` — brain composer
4. `response_reviewer` — adversarial reviewer
5. `knowledge_gap_hold_agent` — gap-hold draft composer
6. `topic_classifier` — pre-LLM-first deterministic classifier
7. `intent_escalator` — intent re-classification
8. `structured_property_backfill` — property data backfill

Each follows the same pattern, well-established by `llm_intake_agent.py`'s
`_record_usage` helper at lines ~590-620:

```python
await LLMUsageTracker.record(
    service_name="brain_intake_classifier",
    tenant_id=tenant_id,                          # UUID | None
    request_type="brain_intake_classification",
    provider="groq" | "anthropic",
    model_id=self._model_groq,
    input_tokens=input_tokens or 0,
    output_tokens=output_tokens or 0,
    success=success,                              # bool
    latency_ms=int((time.monotonic() - started_at) * 1000),
    fallback_position=1 | 2,                      # primary=1, fallback=2
    error_type=error_type,                        # str | None
    metadata={
        "message_id": message.message_id,
        "property_code": message.property_code or "",
    },
)
```

The tracker handles cost calculation internally via `calculate_cost(model_id, input_tokens, output_tokens)` — callers don't need to compute it.

## What's NOT tracked (the four blind spots)

### 1. `app/services/knowledge/voice_pod.py`

The post-booking voice/chat session pod. Two LLM call sites, both
untracked:

- `_call_groq` (line ~1010): Groq llama-3.1-70b-versatile, primary
- `_call_gemini` (line ~1050): Gemini Flash, fallback

Tenant context is available: `self.context.tenant_id` is a UUID, set
during `VoicePod.from_session(...)`.

Token data is available in the response: Groq returns `data["usage"]["prompt_tokens"]` /
`completion_tokens`; Gemini returns `response.usage_metadata.prompt_token_count`
and `candidates_token_count`. Both are currently discarded — `_call_groq`
returns only `data["choices"][0]["message"]["content"].strip()` and
`_call_gemini` returns only `response.text.strip()`.

### 2. `app/services/extraction/llm_extractor.py`

Document-extraction LLM calls (Anthropic-based). Used during operator
onboarding when ingesting property docs. Tenant context is in the call
signature.

### 3. `app/services/messaging_brain/inbound_message_gate.py`

The inbound classification gate (`InboundMessageGate.classify(...)`).
Used for guest-vs-non-guest discrimination on every inbound when the
gate is enabled. Anthropic-based. Tenant context comes from the dispatch
caller — `tenant_id` is passed through to `persist_gate_decision(...)`
already, so the same value is available at the LLM call site.

### 4. `app/services/voice/voice_session.py`

Live phone voice session — Deepgram STT → LLM → ElevenLabs TTS. The
LLM call is Anthropic-based. Tenant context is set per session.

## Tracker signature reference

From [app/services/observability/llm_usage_tracker.py](../../app/services/observability/llm_usage_tracker.py):

```python
@staticmethod
async def record(
    *,
    service_name: str,           # short identifier per file: "voice_pod_chat", "doc_extractor", etc.
    tenant_id: UUID | None,
    request_type: str,           # purpose tag: "voice_response", "doc_field_extract", etc.
    provider: str,               # "groq" | "anthropic" | "gemini" | etc.
    model_id: str,               # exact model id: "claude-haiku-4-5", "llama-3.1-70b-versatile", etc.
    input_tokens: int,           # 0 if unknown
    output_tokens: int,          # 0 if unknown
    success: bool,
    latency_ms: int,
    fallback_position: int = 1,  # 1 = primary, 2 = fallback, etc.
    error_type: str | None = None,
    metadata: dict[str, Any] | None = None,  # free-form, indexed JSONB
) -> None:
```

The tracker is fire-and-forget — internal exceptions are swallowed and
logged but never propagate to the caller. That's the right default for
instrumentation code.

## Retirement rule for this phase

Instrumentation is not the end state. The end state is:

- every live production LLM path writes to `llm_usage_events`
- every non-live leftover path is deleted or explicitly tracked as
  retirement debt

So Phase 4 should be implemented with a paired cleanup mindset:

1. Instrument the live path now.
2. Identify any adjacent fallback/helper path that is no longer reachable
   after the implementation.
3. Retire that path in the same workstream when safe, or log it explicitly
   as retirement debt before closing the phase.

This is how we avoid drifting back into older pathways after the new one is
working correctly.

## Per-file change shape

Each file gets one `_record_usage` helper and `record` calls at every LLM
call boundary. The pattern matches `llm_intake_agent.py:_record_usage`
exactly — same signature, same shape, only `service_name`, `request_type`,
and `metadata` keys differ per file.

### File 1: `voice_pod.py`

**Service identifier:** `voice_pod_chat`
**Request type:** `voice_pod_response`
**Metadata to capture:** session_id (truncated), operator_id, property_code

**Changes:**

```python
# Add to imports near the top of voice_pod.py
from app.services.observability.llm_usage_tracker import LLMUsageTracker

# Add a helper method on VoicePod class, mirroring _record_usage in
# llm_intake_agent.py. Place it near the LLM call methods.

async def _record_llm_usage(
    self,
    *,
    provider: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    success: bool,
    started_at: float,
    fallback_position: int,
    error_type: str | None = None,
) -> None:
    await LLMUsageTracker.record(
        service_name="voice_pod_chat",
        tenant_id=self.context.tenant_id,
        request_type="voice_pod_response",
        provider=provider,
        model_id=model_id,
        input_tokens=input_tokens or 0,
        output_tokens=output_tokens or 0,
        success=success,
        latency_ms=int((time.monotonic() - started_at) * 1000),
        fallback_position=fallback_position,
        error_type=error_type,
        metadata={
            "session_id": self._session_id[:60],
            "operator_id": self.context.operator_id,
            "property_code": self.context.property_code,
        },
    )
```

**Modify `_call_groq`** (currently throws away `data["usage"]`):

```python
async def _call_groq(self, messages: List[Dict[str, str]], settings) -> str:
    import httpx
    started_at = time.monotonic()
    model = getattr(settings, "groq_model", "llama-3.1-70b-versatile")
    groq_messages = [...]  # existing message conversion unchanged

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={...},
                json={...},
            )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        await self._record_llm_usage(
            provider="groq",
            model_id=model,
            input_tokens=0,
            output_tokens=0,
            success=False,
            started_at=started_at,
            fallback_position=1,
            error_type=type(exc).__name__,
        )
        raise

    usage = data.get("usage") or {}
    await self._record_llm_usage(
        provider="groq",
        model_id=model,
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        success=True,
        started_at=started_at,
        fallback_position=1,
    )
    return data["choices"][0]["message"]["content"].strip()
```

**Modify `_call_gemini`** (currently throws away usage_metadata):

```python
async def _call_gemini(self, messages: List[Dict[str, str]], settings=None) -> str:
    import google.generativeai as genai

    started_at = time.monotonic()
    if settings is None:
        settings = get_settings()
    if not settings.gemini_api_key:
        raise ValueError("Gemini API key not configured")

    genai.configure(api_key=settings.gemini_api_key)
    model_name = self.config.model if "gemini" in self.config.model else "gemini-2.0-flash-exp"
    model = genai.GenerativeModel(model_name)

    prompt_parts = [...]  # existing prompt build unchanged

    try:
        response = await model.generate_content_async(
            "\n".join(prompt_parts),
            generation_config={...},
        )
    except Exception as exc:
        await self._record_llm_usage(
            provider="gemini",
            model_id=model_name,
            input_tokens=0,
            output_tokens=0,
            success=False,
            started_at=started_at,
            fallback_position=2,
            error_type=type(exc).__name__,
        )
        raise

    usage = getattr(response, "usage_metadata", None)
    await self._record_llm_usage(
        provider="gemini",
        model_id=model_name,
        input_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
        output_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
        success=True,
        started_at=started_at,
        fallback_position=2,
    )
    return response.text.strip()
```

### File 2: `llm_extractor.py`

**Service identifier:** `doc_extractor`
**Request type:** Field-specific (e.g. `doc_field_extract`, `doc_section_extract`)
**Metadata to capture:** document_id, field_name (or extraction type), document_type

Codex reads `llm_extractor.py` and applies the same helper pattern around
each Anthropic call. Tenant id is in the call signature (most extraction
calls take a `tenant_id: UUID` parameter); pass it through.

The Anthropic response `data["usage"]` has `input_tokens` and `output_tokens`
directly (no rename needed).

### File 3: `inbound_message_gate.py`

**Service identifier:** `inbound_message_gate`
**Request type:** `gate_classification`
**Metadata to capture:** source_message_id (truncated), parser_source, from_header_domain

The gate `classify(...)` method takes the message components but not a
tenant_id directly — `tenant_id` flows in from
`email_dispatch.dispatch_pre_booking` via `persist_gate_decision(...)`.

The cleanest fix: add an optional `tenant_id: UUID | None = None` parameter
to `InboundMessageGate.classify(...)` (it has plenty of other kwargs already)
and pass it from the dispatch call site. The signature change is backward
compatible because it's keyword-only with a default.

Existing dispatch call site (already passes tenant_id elsewhere):

```python
# Before
decision = await gate.classify(
    from_header=parsed.raw_from or "",
    subject=parsed.subject or "",
    reply_to=parsed.reply_channel_address or None,
    x_template=None,
    x_category=None,
    return_path=None,
    body_text=parsed.full_body or parsed.body or "",
)

# After (one new kwarg)
decision = await gate.classify(
    from_header=parsed.raw_from or "",
    subject=parsed.subject or "",
    reply_to=parsed.reply_channel_address or None,
    x_template=None,
    x_category=None,
    return_path=None,
    body_text=parsed.full_body or parsed.body or "",
    tenant_id=services.company_id,
)
```

### File 4: `voice_session.py`

**Service identifier:** `voice_phone_session`
**Request type:** `voice_phone_response`
**Metadata to capture:** session_id (truncated), call_sid (Twilio), property_code

Same helper pattern. Tenant id is in the session object already.

## Verification criteria

After all four files land:

### Smoke verification (single-run)

1. Each file's helper method exists and matches the
   `llm_intake_agent.py:_record_usage` pattern.
2. `python3 -m py_compile` succeeds on each modified file.
3. A single test run that triggers each of the four code paths produces
   one new `llm_usage_events` row per call. Query:

   ```sql
   SELECT
       service_name,
       provider,
       success,
       fallback_position,
       COUNT(*) AS calls
   FROM llm_usage_events
   WHERE created_at > NOW() - INTERVAL '1 hour'
   GROUP BY 1, 2, 3, 4
   ORDER BY service_name, provider;
   ```

   After the test runs, you should see rows for `voice_pod_chat`,
   `doc_extractor`, `inbound_message_gate`, and `voice_phone_session`.

### Production verification (1-2 hour window)

4. After deploy, real production traffic produces `llm_usage_events` rows
   for each of the four new service identifiers within 1-2 hours
   (some less frequently than others — `doc_extractor` only runs during
   ingestion, `voice_phone_session` only during live calls).
5. Failed calls produce rows with `success=false` and a populated
   `error_type`.
6. Token counts are non-zero for successful calls (the previous behavior
   threw token data away; now it's captured).

### Cost completeness check

7. Sum of `estimated_cost_usd` across all `service_name` values matches
   expectations from external billing dashboards (Groq, Anthropic, Gemini)
   within ~10%. Before this phase, the dashboard sum was missing voice
   pod, voice session, doc extractor, and gate costs; after, it should
   account for them.

## Rollout sequence

Two viable options. Codex picks based on whether independent verification
is needed per file.

### Option A — Single commit, all four files

One commit titled "observability: instrument LLM blind spots in voice pod,
doc extractor, gate, and voice session." Verified by smoke test running
each path once. Simpler diff to review and rollback.

### Option B — Four separate commits, one per file

Each commit titled "observability: instrument LLM usage in `<filename>`"
and verified independently before the next lands. Slower but isolates
any regression to a single file.

I lean Option A unless the verification harness for each file looks
materially different — for pure additive instrumentation with the same
shape per file, one commit is easier to reason about and the risk is
minimal.

## Rollback procedure

If any of the four instrumentation changes produces:

- Latency regression in the underlying LLM call (the `_record_usage` call
  is `await`ed; if it blocks for any reason, it adds to call latency)
- New error patterns in production logs related to LLM usage tracker
  exceptions
- DB write pressure on `llm_usage_events` that affects unrelated queries

Rollback is `git revert <commit-sha>`. The instrumentation is purely
additive — the underlying LLM behavior is unchanged. Reverting restores
the pre-instrumentation state, which is the current (blind) state.

Important: the tracker swallows its own exceptions internally, so an LLM
usage write failure cannot fail the underlying LLM call. Latency is the
only realistic regression vector, and it's bounded by the DB session
acquisition time (typically <5ms).

## What this enables (downstream work)

Once Phase 4 lands and produces 24-48 hours of production data, the
admin LLM cost dashboard becomes a real product surface rather than a
partial one. Specifically:

- Operator-facing cost summary per tenant (already supported by the
  existing `admin_llm_usage.py` endpoints)
- Per-service cost attribution: how much does voice pod cost per
  session, how much does the gate cost per inbound, etc.
- Failure rate per provider per service: identifies which provider chain
  is degrading without paging on it
- Token efficiency check: are we paying for retries or oversized prompts
  in any of the new call sites

The dashboard rebuild work (porting `app/static/dashboard/js/sections/llm-usage.js`
into the v2 surface) is the natural follow-up but is out of scope for
this phase.

## Lower-priority candidates (deferred)

The earlier audit listed `mobile.py` and `landing.py` as also containing
LLM calls but at lower priority. They're deferred from this phase because:

- `mobile.py` — surface for guest-facing mobile prototypes; not yet a
  production code path for Beach Habitats
- `landing.py` — operator landing surface, lighter LLM usage

If after Phase 4 lands the cost dashboard reveals meaningful spend on
either of these, instrument them in a separate follow-up commit. Don't
bundle them with the current four — that's exactly the kind of "while
I'm in here" creep this discipline avoids.

## Open questions for Hunter

1. **Option A vs Option B (commit granularity).** I lean A (single
   commit) for pure additive instrumentation with the same shape per
   file. Confirm or override.
2. **`InboundMessageGate.classify(...)` signature change.** Adding an
   optional `tenant_id` kwarg is the cleanest path. The alternative is
   passing tenant_id via class init, but `InboundMessageGate()` is
   stateless across calls today. Confirm the signature-change approach
   is acceptable.
3. **`mobile.py` / `landing.py` inclusion.** Confirm they stay deferred
   (my recommendation) or get added to the same phase.
4. **Retire leftover paths when proven dead?** Recommendation: yes.
   If a fix makes an older path provably unused, retire it in the same
   workstream when safe. If not safe in the same commit, record it
   explicitly as retirement debt with the concrete module name before
   calling the phase complete.

## Status

This doc is **plan only**. No code change has been made. The next concrete
step is codex applying the four changes per the per-file shape above,
verifying each via `python3 -m py_compile`, then running the smoke
verification query post-deploy.

This is the smallest of the four phases and the most parallel-safe
because it doesn't touch canonical surfaces, runtime gates, or routing
contracts. It can ship at any time without dependency on Phases 1, 2, or 3.
