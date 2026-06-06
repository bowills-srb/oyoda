# Pipeline Coordination Observations — 2026-05-03

**Addendum:** See
`docs/PIPELINE_COORDINATION_ADDENDUM_2026_05_04.md` for status
updates, reframed findings, and next-session workstreams that
supersede parts of §§3.2, 5, 6.1, 6.3, 6.4, and 6.6 below.

**Status: Preliminary observations from operator-side inbox review and
code investigation. Not a confirmed audit, not a decision document, no
recommendations. Captured for fresh-eyes follow-up in a subsequent
session.**

This note records observations made during a single session of
operator-side inbox review (Beach Habitats) and code-level
investigation of the regenerate path. The investigation arose
incidentally during a routine inbox check and was scoped narrowly to
capture what was visible before the session ended.

The observations are real and concrete. The interpretations are
preliminary and may not survive fresh-eyes review. The unanswered
questions in §6 are the load-bearing items for the next session.

## 1. Operational context at observation

- **Watch window:** 9 of 50 brain drafts attributed (per the morning
  watch check); mix is varied across direct, Airbnb, and Vrbo
  channels; latest attributed brain draft 2026-05-03 19:55:40 UTC.
- **Operator-quality signal:** None yet. Watch window has produced
  no operator actions on inquiries in-window.
- **Operator interaction during this session:** The operator (Hunter)
  hit "Regenerate" in the pre-booking UI on one in-window inquiry as
  part of this investigation. This is an investigation-driven action,
  not a natural review action; if the watch infrastructure logs
  regenerates as operator actions, that single data point should be
  treated as contaminated rather than as a natural operator-quality
  signal.

## 2. Inbox-side observations (Beach Habitats)

Observed during direct review of the operator's Gmail inbox.

### 2.1 Marketing email tagged as "Oyvoda Processed"

A Petite Plume Mother's Day delivery promotional email
(`Feedback-ID: ...:CAMPAIGN:Attentive`, standard bulk-mail headers,
`info@petite-plume.com` sender) carried the Oyvoda Processed Gmail
label.

The .eml file's headers (preserved as `Last_Chance_for_Mother_s_Day_Delivery.eml`)
show every standard bulk-mail signal: List-Unsubscribe headers,
Feedback-ID with CAMPAIGN classification, Attentive Mobile / SendGrid
infrastructure markers, marketing sender domain. Any reasonable
upstream filter would identify this as non-inquiry traffic.

**Not yet established:** whether this message produced a row in
`pre_booking_inquiries`, or whether the "Oyvoda Processed" label
was applied at the poller layer before classification correctly
dropped it. The .eml alone cannot disambiguate.

### 2.2 Legitimate OTA messages NOT tagged as "Oyvoda Processed"

Messages from Vrbo and Airbnb that appear to be legitimately
Oyvoda-relevant — including content described as "pending
reservations," "reservation requests," and similar — were observed
in the inbox without the "Oyvoda Processed" label.

**Not yet established:** what fraction of these are genuine guest
inquiries vs. OTA operational notifications (reservation reminders,
property promotional content, etc.). The proportion calibrates how
serious any coverage gap might be.

### 2.3 Drafts attributed to a model but containing fallback text

The operator reports observing, over multiple days prior to the
current rollout watch, drafts in the pre-booking review UI that:

- Were stamped as model-generated in the UI
- Contained generic/fallback text rather than apparent model output
- Produced different (more model-like) output when "Regenerate" was
  clicked

The operator developed a habit of regenerating these drafts before
sending. The pattern was not investigated structurally until this
session.

## 3. UI-level observations during this session

Two pre-booking inquiries were examined directly in the operator UI:

### 3.1 Inquiry: 8/2-8/9 availability question

- **Sender:** `sender@messages.homeaway.com` (Vrbo)
- **Property:** "Unknown property"
- **Parser:** `generic_gmail_parser`
- **Latest turn:** "Not confidently isolated"
- **Status banner:** MANUAL REVIEW — "Oyvoda fell back to a safer
  draft path instead of a full model-generated reply"
- **Draft path attribution:** `messaging brain`
- **Policy warnings:** `draft source:messaging brain`
- **Draft text:** "Thanks for reaching out — a teammate will review
  this and follow up shortly."

### 3.2 Inquiry: Jackie Lee, "open and heated" question

Same upstream signal pattern as 3.1 (Unknown property,
generic_gmail_parser, not confidently isolated, Vrbo source). Initial
state identical in shape: MANUAL REVIEW banner, fallback draft text,
attribution `messaging brain`.

After clicking "Regenerate":

- **Property:** Unknown property (unchanged)
- **Parser:** `generic_gmail_parser` (unchanged)
- **Latest turn:** Not confidently isolated (unchanged)
- **Status banner:** DRAFT READY — "95% heuristic / Model-generated
  draft using extracted email context, property data, operator
  guidance, and routing heuristics. This is not a send-permission
  score."
- **Draft path attribution:** `model`
- **Policy warnings:** `parser source:generic gmail parser`
- **Draft text:** "Hi Jackie, thanks for your interest! Our property
  is typically open year-round, and we usually keep it heated during
  the cooler months. However, I recommend checking our Help Centre
  or contacting us directly for the most up-to-date information on
  our operating hours and heating schedule."

The regenerated draft makes confident factual claims about a
property the system did not identify. The operator's question
("will it be open and heated?") refers to a specific property's
amenities (likely a pool/hot tub) — a question whose real answer
depends on property data the system doesn't have access to in this
case.

### 3.3 Operator report: regenerate sometimes recovers property

The operator reports that on some prior inquiries, "Unknown property"
status resolved to a clear property identification after hitting
Regenerate. This was not reproduced during this session, but is
consistent with the code-level finding in §4.

### 3.4 Operator report: regenerate failure observed

A subsequent Regenerate attempt during this session returned a
"regenerate failed" error. Specific error context was not captured.

## 4. Code-level observations

### 4.1 Initial draft pipeline gate

`app/services/concierge/pre_booking_auto_send.py:2020-2070`,
`generate_draft` method:

```python
if decision_stage.missing_knowledge_topics:
    draft_text, draft_source = await _generate_knowledge_gap_hold_draft(...)
else:
    draft_text, draft_source = await generate_inquiry_draft(...)
    _apply_special_draft_source_policy(...)
```

The initial pipeline gates draft generation on
`decision_stage.missing_knowledge_topics`. If non-empty, the system
produces a hold draft (matching the "fall back to a safer draft
path" UI banner). Otherwise it produces a full draft via
`generate_inquiry_draft`, with a policy-application step afterward.

### 4.2 Regenerate endpoint behavior

`app/api/v1/endpoints/operator_prebooking.py:1322-1460`,
`@router.post("/inquiries/{draft_id}/regenerate")`:

The regenerate endpoint:

1. Loads the stored inquiry row from `pre_booking_inquiries`
2. Refetches the source Gmail message via the operator's poller
3. Re-runs `_parse_with_ota_fallback(raw)` on the refetched content
4. Re-resolves property code via `_resolve_property_code(parsed)`
5. Re-enriches with link context via `_enrich_with_link_context`
6. Falls back to stored row state if any of the above fails
7. Runs `InquiryIntentClassifier` on the message text
8. Calls `check_inquiry_policy(...)` (a different policy layer than
   the initial pipeline's `_apply_special_draft_source_policy`)
9. Calls `generate_inquiry_draft(...)` directly
10. Appends warnings to `policy_result` if `draft_source != "model"`
    or if `parser_source` is set or if `asks` is non-empty

The regenerate endpoint never constructs `decision_stage` and never
checks `missing_knowledge_topics`. There is no equivalent hold-draft
gate.

### 4.3 The two structural differences

Regenerate diverges from the initial pipeline in two independent
ways:

1. **Input freshness.** Regenerate refetches and re-parses the
   source Gmail message. The initial pipeline uses parse results
   from intake time. On flaky parses, regenerate may have
   legitimately better inputs than the initial pipeline did.

2. **Gate presence.** The initial pipeline's
   `missing_knowledge_topics` hold-draft gate is absent from the
   regenerate path entirely.

These are independent. Either can produce different output between
initial and regenerate runs, for different reasons. Together they
explain why the operator-observed pattern (fallback initial draft,
better-looking regenerated draft) can occur both legitimately
(better inputs on refetch) and concerningly (gate bypass under
identical poor inputs). The Jackie Lee case in §3.2 is the
concerning version: upstream signals identical between initial and
regenerate, but the gate's absence allowed a confident draft to be
produced from the same impoverished context that triggered the
fallback initially.

### 4.4 The `draft_source` column carries heterogeneous values

`grep` results show `draft_source` is written with at least the
following distinct values across the codebase:

- `"model"` — apparently the default "no special source override"
  marker
- `"messaging_brain"` — written by intake and audit paths
- `"fallback_saved"`, `"voice_pod"`, `"gmail_fallback_saved"`
- `"kb_gap_required"`, `"verification_required"`
- `"portfolio_matches_grounded"`, `"portfolio_matches_partial"`,
  `"portfolio_follow_up_required"`
- `"fallback_grounded_guidebook_*"`, `"fallback_grounded_property_data"`,
  `"fallback_grounded_faq"`
- `parsed.parser_source` (passed through from parser identifiers in
  multiple places in `email_dispatch.py`)

The UI's display logic in `operator_prebooking.py:669-738` is a
cascade of string matches that collapses these values into a smaller
set of operator-facing categories. `_is_review_ready_draft_source`
treats both `"model"` and `"messaging_brain"` as review-ready.

The UI's "Draft path: messaging brain" vs. "Draft path: model"
distinction we observed therefore does not correspond to two cleanly
separated draft generators. It corresponds to a heterogeneous
`draft_source` column being mapped through a string cascade into
display labels.

## 5. Interpretive frame

The cumulative shape of the observations does not localize cleanly
to a single component. Each piece — the initial pipeline gating, the
regenerate endpoint refetching, the parser fallback, the property
resolution, the heterogeneous `draft_source` column, the UI display
cascade — is doing something locally reasonable in isolation. The
observed operational behavior emerges from the *coordination*
between these pieces, not from any single piece being broken.

The operator's diagnostic framing during this session was a
"cross-eyed child looking straight ahead but with eyes pointing
different directions" — components that individually want to do the
right thing but are not aligned with each other. This framing is
consistent with the architectural reconciliation work already
underway (see `docs/MESSAGING_ARCHITECTURE.md`,
`docs/ARCHITECTURE_RECONCILIATION_TRACKER.md`); these observations
extend the same pattern from the backend coordination layer to the
operator-facing layer.

It is possible that the regenerate-path asymmetry described in §4.3
is intentional under an "operator is the gate" design — i.e., the
regenerate button is meant to be the operator's escape hatch from
over-cautious initial gating, with the operator providing the
judgment the system itself declined to provide. Under that
interpretation, the missing gate is a feature, not a bug. However,
the UI we observed (DRAFT READY banner with a 95% heuristic
indicator, parser-source warning as a single small line) does not
appear to surface enough degraded-input context for the operator to
fulfill that role effectively. Whether the design intent is
"operator is the gate" and the UI under-supports it, or whether the
gate is genuinely missing without intent, is not established by this
investigation.

## 6. Unanswered questions for the next session

In rough priority order:

**6.1 Is `decision_stage.missing_knowledge_topics` population
legitimate or reactive to upstream brittleness?** This is the
load-bearing question for whether the regenerate-path asymmetry is a
real safety concern. If `missing_knowledge_topics` correctly
identifies real knowledge gaps, then the regenerate path is
producing drafts under conditions where the system itself flagged
"we don't know enough." If `missing_knowledge_topics` is flagging
gaps caused by parser or property-resolution failures rather than
genuine knowledge absence, then regenerate's fresh refetch is
recovering from upstream brittleness rather than bypassing safety.
Reading the population logic resolves this. This is the highest-
priority next read.

**6.2 What does §2.1's marketing email actually look like in
`pre_booking_inquiries`?** Querying `pre_booking_inquiries` for the
Petite Plume message ID disambiguates whether the "Oyvoda Processed"
label means "poller saw this" (benign, system filtered correctly)
or "pipeline produced an inquiry row for this" (real classification
gap). Cheap query, definitive answer.

**6.3 Why does the Vrbo-specific parser fall back to
`generic_gmail_parser` for `messages.homeaway.com` messages?** Both
in-session UI examples were Vrbo-sourced messages where the generic
parser fired instead of a Vrbo-specific one. Either the Vrbo parser
doesn't recognize the trigger, or it tried and failed and fell
back, or selection logic is broken. Sample size is two; pattern
should be verified before action.

**6.4 What's the design intent on regenerate's gate absence?**
Whether the missing `missing_knowledge_topics` check on regenerate
is intentional (operator-as-gate design) or accidental matters for
how this gets addressed. May be answerable by git history on the
regenerate endpoint, by talking with whoever last touched it, or by
inspection of related commits and PR descriptions.

**6.5 What is the `draft_source` column actually supposed to
represent?** Given the heterogeneity in §4.4, the column appears to
be carrying multiple distinct concerns (which generator produced
the draft, what fallback was used, what parser fired, what policy
state was triggered). Whether this is technical debt that should be
normalized, or a deliberate single-column-many-meanings design, is
unclear. Affects how UI display logic should be structured.

## 7. Out of scope

This note does not:

- Recommend any code changes
- Recommend tracker changes
- Decide whether the regenerate-path asymmetry is a safety concern
- Decide whether any UI changes are warranted
- Audit other writers, parsers, or paths beyond what was observed
- Quantify the frequency of any observed pattern in production

These are appropriate next-session work, downstream of resolving §6.

## 8. Carry-forward for next session

A coordination-layer audit covering the seam between the brain
pipeline, the regenerate path, and the operator UI is the natural
follow-on shape. Such an audit would have the same structure as the
Phase 1b audits already on the tracker (closed-world reasoning,
downstream uniformity, intake paths) but scoped to coordination
between the message-processing layers and the operator-facing
layers.

Recommended first read for the next session: the population logic
for `decision_stage.missing_knowledge_topics`, per §6.1. Once that
is understood, the audit scope tightens substantially.
