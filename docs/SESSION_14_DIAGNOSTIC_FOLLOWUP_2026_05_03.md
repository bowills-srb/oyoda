# Session 14 Diagnostic Followup -- 2026-05-03

Follow-up snapshot to the 2026-05-02 topology report and the Session 14
Beach Habitats pre-booking brain cutover.

This document captures what was established during the 2026-05-03
diagnostic session investigating why post-cutover Beach Habitats
inquiries were not yet producing clear messaging-brain signal.

This is a diagnostic artifact, not a fix proposal and not a reopening of
Session 14 closure.

## Update: Watch Window Opened

Subsequent production verification after this document's initial draft
confirmed that the Beach Habitats messaging-brain rollout is
operationally live.

First verified post-hotfix brain draft:

- `INQ-559E4CE5`
- `platform='direct'`
- `draft_source='messaging_brain'`
- `route_outcome='pre_booking_new'`
- normalization timestamp: `2026-05-03 01:32:11+00`

This is the honest watch-window start time:

- `2026-05-03 01:32:11 UTC`
- `2026-05-02 8:32:11 PM CDT`

Confirmed brain-draft count from that watch-window start through the end
of the 2026-05-03 evening diagnostic session:

- `1`

## 1. Established Facts

### Poller routing into the pre-booking dispatch path is real

The embedded Gmail poller does route ordinary guest pre-booking traffic
into the brain-gated pre-booking dispatch path.

The relevant code path is:

- `GmailInboxPoller._process_one_message(...)`
- `GmailInboxPoller._route_message(...)`
- `process_routed_email(...)`
- `decide_email_route(...)`
- `dispatch_pre_booking(...)`

Observed code behavior:

- system-generated messages route to `dispatch_system_event(...)`
- messages with an active in-stay session route to `dispatch_in_stay(...)`
- all other guest messages route to `dispatch_pre_booking(...)`

This rules out the earlier fear that the Gmail poller was bypassing the
brain-gated pre-booking dispatch path entirely.

### The brain integration is wired into the live poller path

Inside `dispatch_pre_booking(...)`, the code:

- checks `MESSAGING_BRAIN_RUNTIME`
- checks `MESSAGING_BRAIN_SHADOW_MODE`
- if runtime is enabled, attempts `PreBookingBrainOrchestrator().handle(...)`
- on brain failure, logs and falls back to the legacy pre-booking path

So the runtime flag and brain orchestrator are in the live inbox-poller
path for Beach Habitats.

### At least one post-cutover inquiry reached `dispatch_pre_booking(...)`

The inquiry `INQ-4B9C7425` has a matching `message_normalizations` row
with:

- `route_outcome='pre_booking_new'`
- `draft_source='fallback_no_api'`

That combination is consistent with the final
`update_normalization_outcome(...)` call near the end of
`dispatch_pre_booking(...)`.

This means `INQ-4B9C7425` definitely reached the pre-booking dispatch
path and completed a legacy draft/save flow.

### Two other post-cutover inquiries likely also reached dispatch

The inquiries `INQ-3007C78E` and `INQ-31E35BF4` do not currently show a
matching `message_normalizations` row under the queried identifiers.

However, both carry policy warnings of the form:

- `missing_property_knowledge:beach_access,local_area`
- `missing_property_knowledge:amenities,pool_access`

Those warnings are not produced by a separate save path. They are
consumed by `GmailInboxPoller._maybe_record_pre_booking_gap(...)` after a
saved pre-booking `result` is returned.

That strongly suggests these two inquiries also flowed through the
pre-booking dispatch path and then hit a normalization-write gap.

### `fallback_no_api` is a legacy draft-source outcome

The legacy pre-booking draft generator returns `fallback_no_api` when no
configured model provider key is available for that path.

The code checks for:

- `GROQ_API_KEY`
- `ANTHROPIC_API_KEY`
- `GOOGLE_API_KEY` / `GEMINI_API_KEY`

If none are present, the legacy path emits a deterministic fallback
draft rather than an AI-generated draft.

This is an operator-experience issue independent of whether the brain
path is functioning.

### The normalization layer has a real channel-convention mismatch

Current code does not consistently agree on the normalization
`source_channel` value for inbox-derived pre-booking traffic.

Observed conventions:

- `email_dispatch.py` writes normalization outcomes using
  `source_channel='email'`
- the inbound normalizer currently emits `source_channel='email'`
- `operator/prebooking_queue_service.py` joins queue rows using
  `source_channel='gmail'`
- at least one live Beach Habitats normalization row was observed with
  `source_channel='gmail'`

This mismatch predates any fix decision in this session and makes joins
and rollout queries less trustworthy than they should be.

### The post-cutover watch window has still not opened

This statement was superseded by later verification in the same
diagnostic cycle.

The first confirmed Beach Habitats brain-path success row is now known:

- `draft_source='messaging_brain'`
- `route_outcome='pre_booking_new'`
- inquiry `INQ-559E4CE5`
- normalization timestamp `2026-05-03 01:32:11+00`

So the watch window is open and should be measured from that timestamp,
not from the original flag-write timestamp.

## 2. Ranked Issues

### Issue 1: Legacy draft path has no model provider available

Status: resolved as a rollout blocker; remains only as historical
diagnostic context.

Evidence:

- `INQ-4B9C7425` recorded `draft_source='fallback_no_api'`
- the legacy draft generator emits that source when no model API key is
  available

Operational effect:

- if the brain path does not run, operators are not seeing model-written
  legacy drafts
- they are seeing fallback/template-quality drafts instead

Path D and Path E changed the interpretation:

- the live post-hotfix API service does have `ANTHROPIC_API_KEY` and
  `GROQ_API_KEY` set
- `INQ-4B9C7425` was processed by a pre-hotfix API deployment that was
  replaced later that evening
- the `fallback_no_api` result on that inquiry is therefore not evidence
  that the current fixed process lacks model-provider keys

Urgency:

- no longer a blocker for the brain rollout
- does not require immediate follow-up for Session 15

### Issue 2: Brain branch did not produce a brain draft for at least one inquiry

Status: resolved.

Evidence:

- `INQ-4B9C7425` reached `dispatch_pre_booking(...)`
- it completed with legacy `draft_source='fallback_no_api'`
- `INQ-559E4CE5` later produced a verified post-hotfix
  `messaging_brain` draft

Resolved interpretation:

- `INQ-4B9C7425` was handled by a pre-`a55715e` API deployment
- the resolver bug was still live for that inquiry
- the inquiry's legacy behavior was therefore expected for that earlier
  process
- the later inquiry `INQ-559E4CE5` confirms that the post-hotfix process
  does enter and complete the brain path successfully

This issue no longer blocks Session 15.

### Issue 3: Normalization persistence gap for some Gmail-backed inquiries

Evidence:

- `INQ-3007C78E` and `INQ-31E35BF4` likely flowed through the pre-booking
  dispatch path
- neither currently shows a corresponding normalization row under the
  queried ids
- both still have downstream warning patterns consistent with a saved
  pre-booking result

What this means:

- some part of the normalization persistence/update path is not reliably
  landing
- this weakens all downstream metrics, verification SQL, and audit joins

Urgency:

- medium for rollout verification
- high for long-term metrics integrity

### Issue 4: Channel convention mismatch across normalization readers and writers

Evidence:

- queue/service reads expect `source_channel='gmail'`
- current dispatch/normalizer writers use `source_channel='email'`
- a live row exists using the older/different `gmail` convention

What this means:

- normalization lookups are vulnerable to convention drift
- verification queries can produce false negatives depending on which
  channel literal they assume

Urgency:

- medium
- architectural cleanup rather than immediate rollout blocker

### Issue 5: Brain-path observability is insufficient

Evidence:

- the intended failure log path did not produce a quick, message-specific
  answer for `INQ-4B9C7425`
- log search did not disambiguate "brain attempted and raised" from
  "brain never entered"

Important nuance:

- this should be treated as an observability gap, not a proven absence of
  logging
- the log search may have missed the right correlation key
- the logger may have emitted lines that were not easy to retrieve
- or the brain path may not have been entered at all

Operational effect:

- Issue 2 cannot be diagnosed quickly in production
- this slows every subsequent rollout check

Urgency:

- high, because it blocks fast diagnosis of the actual brain-path
  behavior

## 3. Recommended Sequencing

### Session A: Issue 5

Reason:

- highest leverage
- cheapest likely fixes
- improves both operator experience and production diagnosability

Desired stopping criteria:

- next brain-path failure or success is observable from production with a
  clear correlation key

### Session B: Issue 3 plus Issue 4

Reason:

- both live in the normalization/metrics layer
- both are important
- neither should block Session 15 watch-window monitoring once Issue 5 is
  done

Desired stopping criteria:

- normalization rows land consistently for inbox-derived inquiries
- reader/writer channel conventions are aligned and verification joins
  are reliable

## 4. What This Means For The Brain Rollout

The rollout is operationally live.

What was established by the end of the 2026-05-03 evening diagnostic:

- the inbox poller can reach the pre-booking dispatch path
- the brain integration is wired into that path
- the resolver hotfix was necessary and remains valid
- the first verified post-hotfix brain draft was
  `INQ-559E4CE5` at `2026-05-03 01:32:11+00`

So the rollout is no longer blocked. The remaining follow-up issues are
supporting concerns around observability and normalization consistency:

- better observability around brain-path entry/failure
- normalization consistency

Beach Habitats remains operationally fine in the meantime:

- inquiries are still being captured
- drafts are still being created
- operator review remains available

The watch window should be measured from the first verified brain-success
timestamp:

- `2026-05-03 01:32:11+00`

## 5. Out Of Scope For This Document

This document does not:

- propose implementation details for any fix
- decide parser-vs-agent architecture
- decide whether to broaden scope to other PMS/API ingestion lanes
- resolve the larger worker/Celery topology questions from the 2026-05-02
  topology snapshot
- redefine Session 14 closure status

Session 14 remains correctly closed as a seven-SHA rollout artifact set.
This document records follow-up diagnostic findings discovered during
post-cutover verification.

## Appendix: Path D-F Findings

These findings materially changed the interpretation of earlier
diagnostic work conducted on 2026-05-03.

### Path D: provider-key preflight

The legacy draft path checks:

- `GROQ_API_KEY`
- `ANTHROPIC_API_KEY`
- `GOOGLE_API_KEY`
- `GEMINI_API_KEY`

The live post-hotfix `oyvoda` API service was confirmed to have:

- `ANTHROPIC_API_KEY`
- `GROQ_API_KEY`

So the simple theory "current API service has no provider keys" was
disproven.

### Path E: deployment provenance for `INQ-4B9C7425`

Subsequent deployment-history inspection showed:

- current active deployment `8ce6b0aa` went live at
  `2026-05-02 6:05 PM CDT`
- `INQ-4B9C7425` was created at `2026-05-02 5:22 PM CDT`

Therefore `INQ-4B9C7425` was processed by a pre-hotfix API process, not
the current post-hotfix one.

That re-framed the inquiry:

- it was not evidence of a post-hotfix brain failure
- it was evidence of expected pre-hotfix legacy behavior

### Path F: post-hotfix inquiry verification

A production query scoped to inquiries received after the `6:05 PM CDT`
deployment found:

- `INQ-31E35BF4` with a normalization gap still unresolved
- `INQ-559E4CE5` with a confirmed `messaging_brain` normalization row

That query closed the rollout question by proving the post-hotfix
process is producing real brain drafts in production.
