# Inbound To Draft Audit

Date: 2026-05-07

This is a first-pass audit of the inbound email pipeline from transport ingress to draft persistence. It is scoped to the live code paths that matter for Beach Habitats style pre-booking traffic, not a full system review.

## 0. Related Prior Docs

This document is not intended to replace the earlier audit trail. The closest existing repo artifacts are:

- [docs/INTAKE_PATH_RECONCILIATION_2026_05_04.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/INTAKE_PATH_RECONCILIATION_2026_05_04.md:1)
- [docs/AIRBNB_PARSER_GAP_AUDIT_2026_05_04.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/AIRBNB_PARSER_GAP_AUDIT_2026_05_04.md:1)
- [docs/DOWNSTREAM_UNIFORMITY_AUDIT_2026_05_04.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/DOWNSTREAM_UNIFORMITY_AUDIT_2026_05_04.md:1)
- [docs/CLOSED_WORLD_REASONING_AUDIT_2026_05_04.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/CLOSED_WORLD_REASONING_AUDIT_2026_05_04.md:1)
- [docs/PIPELINE_COORDINATION_OBSERVATIONS_2026_05_03.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/PIPELINE_COORDINATION_OBSERVATIONS_2026_05_03.md:1)

This audit is the focused 2026-05-07 follow-on for the current ingress-to-draft path after the LLM-ingress replacement and save-path incident.

## 1. Entry Points

- Gmail ingress starts in [app/services/integrations/gmail_inbox_poller.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/gmail_inbox_poller.py:1457).
- Microsoft ingress starts in [app/services/integrations/microsoft_inbox_poller.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/microsoft_inbox_poller.py:183).
- Both flow through [app/services/integrations/email_parser_router.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/email_parser_router.py:25).
- Routing after parsing is shared through [app/services/integrations/email_pipeline.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/email_pipeline.py:14) and [app/services/integrations/email_dispatch.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/email_dispatch.py:164).

## 2. Layer Map

### Layer A: Transport decode

- Gmail decodes payload headers, plain text, HTML, links, and raw body in `GmailEmailParser`.
- Microsoft does the same shape adaptation for Graph mail.
- Deterministic logic here:
  - sender-domain platform detection
  - skip patterns for obvious non-guest senders
  - basic thread splitting and quoted-text cleanup

### Layer B: Source-route detection

- [app/services/integrations/inbound_source_router.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/inbound_source_router.py:12) assigns one of:
  - `ota`
  - `direct_website_form`
  - `vendor_ops_email`
  - `generic`
- Deterministic logic here:
  - sender/header/platform regex detection
  - Drupal form markers
  - vendor marker keywords like `beach chair`

### Layer C: Primary parse

- [app/services/integrations/email_parser_router.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/email_parser_router.py:25) now tries `LLMEmailExtractor` first for `ota`, `direct_website_form`, and `generic`.
- [app/services/integrations/llm_email_extractor.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/llm_email_extractor.py:1) extracts:
  - `latest_guest_message`
  - `property_code_or_name`
  - dates
  - guest count
  - sender email
  - sender name
- Hard rule:
  - if `latest_guest_message` is empty or too short, extraction raises `LLMEmailExtractorParseFailure` and the message should not proceed to composer.

### Layer D: Deterministic fallback parse

- If the LLM path fails with timeout, invalid JSON, or schema failure, the router falls back to:
  - [app/services/integrations/ota_email_parsers.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/ota_email_parsers.py:1)
  - [app/services/integrations/direct_email_parsers.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/direct_email_parsers.py:1)
  - provider fallback parse in the poller
- Deterministic logic here is still heavy:
  - regex subject matching
  - substring extraction of guest turn
  - quoted-thread dissection
  - property/date/guest extraction from templated bodies

### Layer E: High-level route selection

- [app/services/integrations/email_pipeline.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/email_pipeline.py:14) chooses:
  - `system_event`
  - `in_stay`
  - `pre_booking`
- Deterministic logic here:
  - active session lookup
  - `system_generated` flags
  - reservation context checks

### Layer F: Inbound gate

- [app/services/messaging_brain/inbound_message_gate.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging_brain/inbound_message_gate.py:1) runs at the top of `dispatch_pre_booking`.
- This is an LLM classifier with deterministic thresholds:
  - `guest_message` with confidence `>= 0.7` proceeds
  - `unclear` or low-confidence guest routes to review
  - operational / marketing / bounce gets skipped
- Override flags:
  - `INBOUND_MESSAGE_GATE_ENABLED`
  - `INBOUND_MESSAGE_GATE_REVIEW_ALL`

### Layer G: Brain drafting path

- In [app/services/integrations/email_dispatch.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/email_dispatch.py:327), if `MESSAGING_BRAIN_RUNTIME` is enabled:
  - property context is loaded
  - guest thread identity is resolved
  - `PreBookingBrainOrchestrator` drafts a response
  - `process_pre_booking_inquiry_with_draft(...)` persists and holds/sends it
- If that path raises, it falls back to `process_pre_booking_inquiry(...)`.

### Layer H: Persistence and operator visibility

- `_save_inquiry(...)` in [app/services/concierge/pre_booking_auto_send.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/pre_booking_auto_send.py:2729) writes `pre_booking_inquiries`.
- Operator read models are updated through queue sync afterward.
- Normalization outcome is stored through [app/services/messaging/message_event_store.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/messaging/message_event_store.py:199).

## 3. Important Overrides And Fallbacks

- LLM extraction primary, deterministic parsing fallback
- gate enabled or disabled by feature flag
- gate can force review-all even on strong guest messages
- messaging brain runtime can be disabled, which drops to legacy draft generation
- draft persistence can succeed, duplicate, or save-fail
- queue sync is best-effort after inquiry save

## 4. Deterministic Decision Points Still In The System

- source-route classification by sender/subject/body markers
- platform detection by domain and regex
- non-guest detection in the generic parser
- active-session routing into `in_stay`
- feature-flag gating of major behaviors
- property-code resolution in the poller
- duplicate detection by `(thread_id, message_id)` on insert

## 5. Today’s Verified Failure

- The phantom `pre_booking_duplicate` problem was not true dedup.
- Production logs showed `ForeignKeyViolationError` on `pre_booking_inquiries.guest_thread_id` pointing at a missing parent row in `guest_threads`.
- That was being collapsed into `saved=False`, which `email_dispatch` labeled `pre_booking_duplicate`.
- The save path now distinguishes:
  - `saved`
  - `duplicate`
  - `save_failed`

## 6. Current Architectural Read

- The front door is now meaningfully more agentic than it was this morning because guest-turn extraction is LLM-primary.
- The system is still mixed-architecture overall.
- The most fragile deterministic-natural-language zones that remain are:
  - source-route detection
  - deterministic parser fallback
  - generic non-guest detection
  - property resolution from extracted mentions

## 7. Best Next Inspection Targets

- Worker-tier topology resolution
  - Now in progress as a dedicated staged restoration workstream. The architectural decision is locked to Option B: restore Celery worker tier as the authoritative background execution path, with Gmail polling remaining embedded transitionally. See [docs/WORKER_TIER_TARGET_2026_05_07.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/WORKER_TIER_TARGET_2026_05_07.md:1).
- How often the LLM extractor falls back in production, by email shape
- Whether generic non-guest detection is suppressing any real guest traffic
- Property resolution quality after raw-property extraction moved upstream
- Whether any downstream operator surfaces still assume `pre_booking_duplicate` means true duplicate

## 8. Likely Dead Or Superseded Paths

- `app/static/prebooking-wire.js`
  - This appears to be a legacy dashboard-era pre-booking script. It is already deleted in the current worktree, which is a strong sign that it is being retired. Before restoring or reusing it, confirm whether any live HTML still references it.
- Deterministic parser stack in `ota_email_parsers.py` and `direct_email_parsers.py`
  - Not dead today, but now fallback-only for shared ingress. These are candidates for removal once production telemetry shows the LLM path is reliable enough.
- Generic fallback parser in `GmailEmailParser.parse`
  - Also not dead today, but no longer the intended primary path for guest extraction. This is a cleanup candidate after fallback frequency is measured.

## 9. New Blocking Infrastructure Finding

- Worker-tier restoration is now the active top-priority infrastructure workstream ahead of Item 2 (canonical save-wrapper adaptation) and Item 3 (regenerate-path gate asymmetry).
- Item 2 remains paused until Session 4 of worker-tier restoration completes and the production background execution surface is settled.
- Item 3 remains paused behind the same prerequisite because the current periodic/background execution surface is still being normalized.
- The attempted normalization coverage tripwire wiring used Celery beat/task infrastructure, but it is still not operationally live until the worker-tier restoration path reaches verified execution.
- Current status:
  - tripwire code exists in repo
  - tripwire commit `f9965b7` is on `oyvoda`
  - tripwire is not yet verified operationally live
  - tripwire is expected to become the Session 2 smoke-test task for end-to-end Celery verification
- Carry-forward implication:
  - do not resume Item 2 canonical save-wrapper work until the staged worker-tier restoration reaches its Session 4 topology-settled state.
