# Ship O — Target B extraction audit (`VoicePod`)

**Status:** Audit written May 20, 2026. This is a prerequisite audit for Ship O, not a deletion commit.

## Purpose

Target B is not “delete `voice_pod.py`.” It is:

`retire VoicePod as a live guest-message runtime owner`

To do that safely, we need to separate:

- runtime ownership logic that should go away
- helper logic that may still need extraction or preservation

This audit maps that split.

---

## What has already changed

Ship M moved the live session-channel decision path onto:

- `app/services/messaging_brain/session_channel_adapter.py`

And the old channel seams now call that adapter:

- `app/api/v1/endpoints/mobile_v2.py`
- `app/api/v1/endpoints/sms.py`
- `app/api/v1/endpoints/phone.py`
- `app/services/messaging/channel_router.py`

So the important distinction now is:

- names like `_run_voice_pod(...)` still exist in some places
- but they are no longer proof that `VoicePod.respond(...)` is still the runtime

---

## Direct `VoicePod.respond(...)` references found

Repo audit found direct `respond(...)` usage in:

1. `app/services/observability/watch_layer.py`
2. `app/api/v1/endpoints/knowledge.py` voice-pod test endpoint

These are the first concrete places to audit if the runtime ownership is to be retired.

---

## What appears to be runtime-only logic inside `voice_pod.py`

High-likelihood runtime-ownership code:

- `VoicePod.from_session(...)`
- `VoicePod.respond(...)`
- routing / escalation gate wiring
- in-method quick-answer decision path
- in-method PMS context lookup for response generation
- in-method LLM response generation
- in-method dining reservation conversational flow
- in-method Librarian retrieval-to-reply pipeline

This is the legacy alternate runtime shape and is the main retirement target.

---

## What may be extraction-worthy helper logic

Potentially reusable logic that should be evaluated before any file-level deletion:

1. keyword escalation compatibility helpers
   - `_check_keyword_escalation(...)`
   - `_build_escalation_response_text(...)`

2. dining-intent parsing helpers
   - `_is_dining_intent(...)`
   - `_extract_dining_slots(...)`

3. response formatting helpers
   - `_format_quick_answer(...)`
   - `_build_escalation_response(...)`

4. structural data types, if still referenced
   - `VoicePodConfig`
   - `VoicePodContext`
   - `VoicePodResponse`

These should not be assumed reusable. They may still be too entangled with the old runtime. But they are the first candidates to inspect if something in `voice_pod.py` is worth preserving.

---

## Recommended extraction rule

Before any deletion commit:

1. audit whether anything outside `voice_pod.py` still legitimately depends on:
   - `VoicePodResponse`
   - helper-formatting behavior
   - dining slot parsing
   - escalation text helpers
2. if yes, extract that logic into a smaller shared helper/module first
3. only then delete `VoicePod` runtime entrypoints

If no legitimate dependencies remain, delete the runtime code directly once the verification window has elapsed.

---

## Current recommendation

Do **not** attempt a wholesale `voice_pod.py` deletion yet.

The next concrete move should be:

- a focused extraction audit around `VoicePodResponse` and any helper-formatting functions

Then, after the Ship M verification window has elapsed:

- remove direct `respond(...)` callers
- collapse or delete the remaining runtime shell

---

## Bottom line

Target B is a two-step problem:

1. extraction audit
2. runtime deletion

Today we are still in step 1.
