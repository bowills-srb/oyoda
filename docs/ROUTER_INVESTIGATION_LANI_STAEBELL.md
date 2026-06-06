# Router investigation: lani staebell inquiry trace

**Date:** 2026-05-26
**Status:** investigation complete; fix pending operator-environment verification
**Sibling docs:** `ROUTER_PATCH_A_VRBO_LAYER1.md` (the layer-1 patch already
applied, not yet committed)

## Why this exists

A Vrbo inquiry from "lani staebell" with `X-Mediated-Message-Type: INQUIRY`
never reached the pre-booking surface and instead sat in the operator inbox.
This document captures the full code trace through the email pipeline for
that specific message, identifies the three remaining silent-drop candidates
that can't be resolved by reading code alone, and proposes the next step:
runtime instrumentation, not more speculative code.

## The message (relevant headers + content shape)

```
X-Mediated-Site: vrbo
X-Mediated-Message-Type: INQUIRY
X-Mediated-Conversation-ID: /conversations/0030/5b454283-…
X-Inquiry-Listing: vrbo-5089865
X-Inquiry-PropertyExtId: 2403-280970
X-Inquiry-Arrival: 2026-06-28
X-Inquiry-Departure: 2026-07-05
X-Inquiry-Adults: 4
X-Inquiry-Name: lani staebell
From: "lani staebell" <sender@messages.homeaway.com>
Reply-To: lani staebell <54dabbf7-…@messages.homeaway.com>
Subject: Inquiry from lani staebell: Jun 28 - Jul 5, 2026 - Vrbo #5089865
```

Body: a ~700-character guest message asking about pet-policy flexibility
for an elderly Shih Tzu. The HTML contains `<div id="messageBody">` with
the full text. The plain-text section uses Vrbo's canonical labeled-fields
layout (Property / Unit / Dates / Guests / Traveler Name / Inquiry from)
followed by `Further info` and the guest message.

## End-to-end trace (annotated)

Pipeline order:

| # | Stage | Function | Lani's outcome | Drop risk |
|---|-------|----------|---------------|-----------|
| 1 | Gmail poll fetches | `_get_full_message` | success | none for this case |
| 2 | Body decoding | `_decode_gmail_payload` + `extract_plain_text_body` | success | none |
| 3 | Layer 1 deterministic | `_classify_layer1` (Vrbo branch) | **pre-patch: `unclear`**<br>**post-Patch A: `admit`** | pre-patch falls through to LLM; post-patch admits positively |
| 4 | Non-guest registry | `NON_GUEST_REGISTRY.classify` | no match | low — content is clearly guest |
| 5 | Source-route detection | `detect_inbound_source_route` → `detect_platform` | `parser_hint="ota"`, `provider="vrbo"` via subject regex `\binquiry from .+ - vrbo\b` | none for this case |
| 6 | Email type classification | `EMAIL_TYPE_CLASSIFIER.classify` | `VRBO_GUEST_INQUIRY` (`_INQUIRY_HEADER_TYPES` set doesn't contain `INQUIRY` but `_looks_like_vrbo_inquiry` subject regex matches) | drops `INQUIRY` from the header-types set is the **same schema-drift root cause** as Patch A — see "Mirror bug" below |
| 7 | OTA parser | `parse_ota_inquiry` → `_parse_vrbo` | full extraction success: guest_name, platform_listing_id=5089865, platform_unit_id=unit_5664027, property_name_hint=ExternalID:2403-280970, check_in/out, guests_adults, message_body via `soup.find(id="messageBody")` | none — the parser is correct for this email shape |
| 8 | Usability gate | `parsed.is_usable()` | True (700+ chars of `latest_guest_turn`) | none |
| 9 | Adapter | `_adapt_ota_inquiry` in gmail_inbox_poller | returns populated `ParsedGmailMessage`. **`guest_email=""`** because Reply-To is `@messages.homeaway.com` (a Vrbo relay) and `_is_platform_automation_email` nulls it | not a drop, but causes downstream identity-resolution to have no email to work with |
| 10 | Identity enrichment | `_prepare_parsed_message` | `_resolve_property_code` likely returns `""` (different seam — property-binding audit). `inherit_property_from_thread_context` likely also returns nothing. `_maybe_record_unmatched_platform_identifier` fires and records a binding gap. | not a drop here, but blocks downstream property-grounded responses |
| 11 | Email-pipeline router | `decide_email_route` | no active session, no reservation match, `intake_layer1_decision in {"unclear","admit"}` → `route_kind="pre_booking"` ✅ | safe path through |
| 12 | Pre-booking dispatch | `dispatch_pre_booking` | enters; **silent-drop candidates A/B/C live here — see below** | **THIS IS WHERE THE TRACE GOES DARK** |

## Silent-drop candidates inside `dispatch_pre_booking`

The trace reaches `dispatch_pre_booking` cleanly. Three branches inside it
can result in lani never appearing in pre-booking. Each depends on runtime
state (feature flags or DB success) that can't be resolved from code alone.

### Candidate A — brain-runtime gate

```python
if not runtime_enabled or not brain_lifecycle_primary:
    return await _persist_fallback("brain_runtime_not_primary")
```

`runtime_enabled` comes from feature flag `MESSAGING_BRAIN_RUNTIME`.
`brain_lifecycle_primary` comes from `is_brain_prebooking_lifecycle_primary_enabled`.
Per Phase 1 close: **all three feature-flag gates are default-off** for
new tenants. So Beach Habitats almost certainly hits this branch.

`_persist_fallback` calls `services.save_fallback_pre_booking_inquiry`.
If that returns `True`, lani is saved with `route_outcome="pre_booking_fallback"`
and SHOULD appear in pre-booking. If it returns `False`, `_persist_fallback`
raises `RuntimeError`, which the outer `except Exception` catches and calls
`_persist_fallback(str(exc))` AGAIN. If that second call also fails, the
exception escapes `dispatch_pre_booking`, is caught by `_process_one_message`'s
outer try/except, and recorded as `_PROCESSING_STATUS_FAILED_RETRYABLE`.
After `_MAX_PARSE_FAILURE_ATTEMPTS=3` retries, the message is quarantined.

**Verification needed:** check the Beach Habitats DB for lani's entry in
`gmail_processed_messages`. The `processing_status` and `last_failure_reason`
columns will tell us whether (a) the fallback save succeeded and there's a
visibility bug in the pre-booking queue, (b) the fallback save failed and
the message was quarantined, or (c) the message reached an entirely different
branch.

### Candidate B — InboundMessageGate skipped path

```python
should_run_gate = layer1_decision == "unclear"
if should_run_gate and gate_enabled:
    # ... gate.classify ...
    elif not decision.should_proceed_as_guest:
        if routed_to_review:
            # save fallback with route_outcome="pre_booking_gate_review"
            return "pre_booking_gate_review"
        # save normalization outcome only — NO row saved
        return "pre_booking_gate_skipped"
```

This is the original silent-drop class. If `INBOUND_MESSAGE_GATE_ENABLED=True`
for Beach Habitats and the gate decides `should_proceed_as_guest=False` and
`INBOUND_MESSAGE_GATE_REVIEW_ALL=False`, the return is `pre_booking_gate_skipped`.
The message is marked processed in Gmail (D1 fix preserves UNREAD but the
dedup record is still written) but **nothing is saved to pre-booking**.

Per the Phase 1 default-off policy this is less likely than Candidate A,
but if a different operator with the gate enabled hits this, the same
silent loss occurs.

**Post-Patch A**, lani's `layer1_decision = "admit"`, so `should_run_gate = False`
and the gate is skipped entirely. Patch A by itself eliminates this
candidate for lani going forward.

### Candidate C — DeterministicIntakePreFilter misclassification

```python
classification, classifier_metadata = await DeterministicIntakePreFilter().classify_with_metadata(gate_message, db_session=services.db)
inferred_intent = classifier_metadata.legacy_intent or legacy_intent_from_classification(classification, ...)
if is_non_pre_booking_intent(inferred_intent):
    # persist_inbound_from_inquiry — returns "guest_session_routed"
```

For lani's message text, I scored the prefilter manually:

- `availability`: matches "june", "july", "week" → 2 hits
- `pet_policy`: matches "pet" → 1 hit
- `local_area`: matches "beach" → 1 hit
- everything else: 0 hits

Best: `availability` (2/4 = 0.5 confidence). NOT in
`NON_PRE_BOOKING_INTENTS = {"general", "general_inquiry", "review_response"}`.
So this branch does NOT fire for lani.

**Ruled out for lani specifically.** Remains a risk for messages like
Amber Barry's where "I'm booked" language might tip the scoring toward
`general` or `review_response`.

## Mirror bug: `EMAIL_TYPE_CLASSIFIER._INQUIRY_HEADER_TYPES`

Same root cause as Patch A's layer-1 fix. In `email_type_classifier.py`:

```python
_INQUIRY_HEADER_TYPES = {
    "NEW_INQUIRY",
    "NEW_BOOKING_REQUEST",
}
```

Lani's `X-Mediated-Message-Type: INQUIRY` doesn't match this set either.
The classifier falls through to `_looks_like_vrbo_inquiry`, which uses a
subject regex that happens to match — so the result is correct, but by
luck of subject format, not by header-type recognition.

**This is a latent bug.** A future Vrbo INQUIRY message with a subject that
doesn't match `\binquiry from .+ - vrbo\b` would fail to classify as
`VRBO_GUEST_INQUIRY` and route via the generic OTA fallback path with less
positive-signal metadata.

**Recommended follow-up:** add `INQUIRY` to `_INQUIRY_HEADER_TYPES` in
`email_type_classifier.py`. Trivial, symmetric to Patch A. Belongs in the
same commit as Patch A or in an immediate follow-up.

## What we ruled in vs out

| Stage | Could cause lani's silent loss? |
|---|---|
| Layer 1 dropping the message | NO — `unclear` (pre-patch) continues; `admit` (post-patch) continues |
| Source-route detection | NO — correctly identifies Vrbo |
| Email type classification | NO — subject regex saves us; but mirror bug exists |
| OTA HTML parser | NO — `<div id="messageBody">` extraction succeeds |
| OTA plain-text parser | NO — `Further info` pattern matches |
| Usability gate | NO — 700 chars passes the 10-char minimum |
| `_adapt_ota_inquiry` body-length check | NO — body is well over 10 chars |
| `is_non_guest_email` final check | NO — guest text doesn't match any non-guest pattern |
| `decide_email_route` | NO — routes to pre_booking on unclear/admit |
| `DeterministicIntakePreFilter` non-pre-booking classification | NO — lani classifies as "availability", which is pre-booking |
| **Brain-runtime gate → fallback save failure** | **YES (Candidate A)** |
| **InboundMessageGate skipped path** | **YES (Candidate B)** — eliminated post-Patch A for lani's INQUIRY header type |
| Property binding | NO for this question — binding failure produces "unbound" not "missing" |

## What we cannot resolve from code

We need to see runtime data for lani's specific message to know which
candidate fired. Concretely, query `gmail_processed_messages` for her
Gmail message ID:

```sql
SELECT processing_status, failure_count, last_failure_reason, last_attempted_at
FROM gmail_processed_messages
WHERE operator_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'  -- Beach Habitats
  AND processed_at >= '2026-05-26 16:30:00+00'
  AND processed_at <= '2026-05-26 17:00:00+00'
ORDER BY processed_at DESC;
```

`processing_status` will be one of:
- `processed` + no fallback row in pre-booking → **visibility bug in the queue UI**
- `processed` + fallback row exists in pre-booking → **the data is there, the operator just didn't see it (UI scope issue)**
- `failed_retryable` (count < 3) → **Candidate A active, save failing**
- `quarantined` (count >= 3) → **Candidate A active, save failing repeatedly**
- `non_guest` → **something earlier returned None — needs deeper trace**

If `processing_status='processed'` and there's no pre-booking row, also check:

```sql
SELECT route_outcome, draft_source, fallback_reason
FROM canonical_inbound_normalization_outcomes  -- table name may differ
WHERE source_message_id = '<lani's source_message_id>';
```

The `route_outcome` value (`pre_booking_fallback`, `pre_booking_gate_skipped`,
`pre_booking_gate_review`, `pre_booking_save_failed`, etc.) will pinpoint
the branch.

## Production verification performed on 2026-05-26

After the static code trace above, I verified the live Beach Habitats
environment against production DB state.

### Confirmed

- The live Beach Habitats operator account is:
  - `operator_id = 4d0721d7-3d36-409a-a648-7209ad347a73`
  - `tenant_id = e07980b2-a990-4b24-91d1-c8cb71ab70e1`
- `operator_gmail_creds` is wired to the expected inbox:
  - `watched_email = info@beachhabitats30a.com`
- The Gmail poller is active:
  - `last_polled_at = 2026-05-26 22:30:01+00`
  - `last_poll_success = true`
  - `last_poll_summary = found=1, new=0, dupes=0, save_failed=0, processed=0`
- Production is still running the **old** Vrbo REPLIED behavior:
  - recent `gmail_processed_messages` rows include
    `processing_status='non_guest'`
    with `last_failure_reason='ota_message_type:REPLIED (guest_session)'`
  - therefore Patch A in `email_parser_router.py` is not deployed yet

### Not found

Using lani's exact identifiers from the `.eml`:

- RFC `Message-ID`
- `X-Mediated-Message-ID`
- `X-Mediated-Conversation-ID`
- subject containing `lani staebell`

I found **no matching rows** in:

- `gmail_processed_messages`
- `message_normalizations`
- `pre_booking_inquiries`
- `inbound_classifications`

### What this changes

The absence of any persisted row means lani did **not** make it far enough
to be recorded in any of the normal intake stores. That weakens Candidate A
for this specific message, because a fallback-save failure would still
normally leave a `gmail_processed_messages` retry/quarantine record behind.

The strongest current runtime hypothesis is now:

1. the mailbox is correct and actively polled
2. the message existed in Gmail (per the operator report and poll activity)
3. but it was skipped before normal processing-state persistence, or never
   selected into a processable Gmail-message-id path we can correlate from
   DB alone

The two most plausible next runtime checks are:

- inspect the Gmail API directly for the message and its Gmail `id`
- trace the exact skip path around `_list_message_ids(...)`,
  `_is_already_processed(...)`, and `_intake_message(...)`

### Operational takeaway

We now know this is **not** just a queue-visibility bug, and **not** a
simple "fallback save failed after dispatch" case. There is a pre-persistence
gap somewhere between Gmail listing/fetch and the first durable intake row.

## Architectural finding: parser-layer silent limbo

The router patch (Patch A) fixed silent limbo at the **layer-1 deterministic**
boundary. But the same anti-pattern lives at **two other boundaries** in
the email pipeline:

**Boundary 2 — InboundMessageGate skipped path.** When `should_proceed_as_guest=False`
and `routed_to_review=False`, the message returns `pre_booking_gate_skipped`.
Nothing is saved anywhere actionable. The Gmail message is recorded as
processed in dedup. The operator never sees it. This is the **same shape**
as the pre-patch `REPLIED` drop — a deterministic-layer "we think this
isn't a guest message" decision that terminates the pipeline with no
recovery path.

**Boundary 3 — fallback-save failure cascade.** When `save_fallback_pre_booking_inquiry`
returns False (any exception inside it), `_persist_fallback` raises
`RuntimeError`. The outer except in `dispatch_pre_booking` catches it and
calls `_persist_fallback(str(exc))` AGAIN. If that fails, the exception
escapes `dispatch_pre_booking`. `_process_one_message` catches it, records
`failed_retryable`, and after 3 attempts quarantines the message. **The
operator never sees the message** — it's stuck in `gmail_processed_messages`
with `processing_status='quarantined'`, never surfaced in any UI.

These boundaries deserve the same architectural treatment as the router
patch. See `ROUTER_CONTRACT_SPEC.md` (TODO) for the unified rule set.

## Next steps

In priority order:

1. **Query Beach Habitats DB** for lani's `gmail_processed_messages` row.
   This tells us which candidate fired. No code changes needed.

2. **Apply the mirror-bug fix** in `email_type_classifier.py`: add `INQUIRY`
   to `_INQUIRY_HEADER_TYPES`. Single-line change. Belongs alongside the
   Patch A commit or in an immediate follow-up commit titled e.g. `classifier:
   recognize Vrbo INQUIRY header type alongside NEW_INQUIRY`.

3. **Commit Patch A + the mirror fix together** as `router: stop silent-dropping
   Vrbo OTA messages at layer 1 and the type classifier`.

4. **Write `ROUTER_CONTRACT_SPEC.md`** documenting the strict-positive-gate
   contract and explicitly listing all three silent-limbo boundaries
   identified so far (layer-1, gate-skipped, fallback-save-failure).

5. **Audit the InboundMessageGate skipped path** as a separate fix.
   Either: (a) make it default to admit on uncertainty when content has
   strong guest-message signal (the strict-positive-gate principle applied
   here), or (b) ensure `routed_to_review` is the default rather than the
   exception.

6. **Audit the fallback-save failure cascade** as a separate fix. Either:
   (a) make `save_fallback_pre_booking_inquiry` more robust to whatever
   is failing, or (b) write the message to a "quarantine inbox" UI so the
   operator can see and act on quarantined messages instead of them
   silently rotting in `gmail_processed_messages`.

7. **Investigate property binding** (Casa blanco class) as a separate seam
   — irrelevant to lani's failure mode but relevant to the broader
   operator-reported failure set.

8. **Investigate lifecycle misclassification** (Amber Barry / Natalie Horton)
   as a separate seam — Candidate C may be involved there even though it
   wasn't for lani.

## Glossary of file paths referenced

- `app/services/integrations/email_parser_router.py` — layer-1 deterministic gate, Patch A applied
- `app/services/integrations/email_type_classifier.py` — message-type classifier (mirror bug here)
- `app/services/integrations/ota_email_parsers.py` — Vrbo HTML/plain-text parser
- `app/services/integrations/email_routing.py` — `decide_email_route`
- `app/services/integrations/email_dispatch.py` — `dispatch_pre_booking` (Candidates A, B live here)
- `app/services/integrations/email_pipeline.py` — `process_routed_email` orchestrator
- `app/services/integrations/gmail_inbox_poller.py` — Gmail poller, adapters, `_save_fallback_pre_booking_inquiry`
- `app/services/messaging_brain/agents/deterministic_intake_prefilter.py` — intent classifier (Candidate C)
- `app/services/concierge/post_booking_routing.py` — `is_non_pre_booking_intent`, `NON_PRE_BOOKING_INTENTS`
- `app/services/messaging_brain/inbound_message_gate.py` — AI gate (Candidate B)
