# Missing Inbound Audit

Purpose: classify each “this never showed up in Oyvoda” report into one of four concrete buckets:

1. Gmail polled it but parser/quarantine logic stopped it
2. `message_normalizations` row exists but no inquiry/session surfaced
3. Inquiry/session exists but is routed somewhere the operator is not looking
4. Nothing persisted at all

Use this for Beach Habitats or any other tenant with a connected email inbox.

## Inputs to collect first

For each missing inbound example, gather as many of these as possible:

- received timestamp
- sender email
- subject
- first 1-2 lines of the guest message
- Gmail message id or RFC `Message-ID` header if available

Best-case audit key:

- `gmail_message_id`
- or RFC `Message-ID`

Fallback audit key:

- sender + subject + a tight time window

## Live schema reference

Confirmed in production on 2026-05-27:

- `gmail_processed_messages`
  - `gmail_message_id`
  - `rfc_message_id`
  - `operator_id`
  - `processed_at`
  - `processing_status`
  - `failure_count`
  - `last_failure_reason`
  - `first_seen_at`
  - `last_attempted_at`

- `message_normalizations`
  - `source_message_id`
  - `source_provider`
  - `raw_subject`
  - `sender_address`
  - `latest_guest_turn`
  - `selected_property_code`
  - `route_outcome`
  - `draft_source`
  - `fallback_reason`
  - `parser_used`
  - `parser_notes`
  - `composer_*`

- `pre_booking_inquiries`
  - `draft_id`
  - `message_id`
  - `gmail_message_id`
  - `guest_email`
  - `message_text`
  - `property_external_id`
  - `intent`
  - `status`
  - `confidence_source`
  - `review_verdict`

## Section 1: Did Gmail polling see it?

If you have `gmail_message_id`:

```sql
SELECT
    gmail_message_id,
    rfc_message_id,
    processing_status,
    failure_count,
    last_failure_reason,
    first_seen_at,
    last_attempted_at,
    processed_at
FROM gmail_processed_messages
WHERE gmail_message_id = :gmail_message_id;
```

If you have RFC `Message-ID`:

```sql
SELECT
    gmail_message_id,
    rfc_message_id,
    processing_status,
    failure_count,
    last_failure_reason,
    first_seen_at,
    last_attempted_at,
    processed_at
FROM gmail_processed_messages
WHERE lower(trim(both '<>' from COALESCE(rfc_message_id, '')))
      = lower(trim(both '<>' from :rfc_message_id));
```

What it means:

- `processed` or equivalent terminal success state: Gmail saw it, move to section 2
- `quarantined`: parser failed repeatedly; investigate `last_failure_reason`
- `non_guest`: dropped by non-guest heuristics
- no row: poller never persisted it, or you’re using the wrong message identifier

## Section 2: Did normalization happen?

If you have `gmail_message_id`, `message_normalizations.source_message_id` usually matches it for Gmail:

```sql
SELECT
    source_message_id,
    sent_at,
    source_provider,
    sender_address,
    raw_subject,
    LEFT(latest_guest_turn, 300) AS latest_guest_turn,
    selected_property_code,
    selected_property_match_type,
    parser_used,
    route_outcome,
    draft_source,
    fallback_reason,
    parser_notes::text
FROM message_normalizations
WHERE tenant_id = :tenant_id
  AND source_message_id = :gmail_message_id
ORDER BY sent_at DESC
LIMIT 5;
```

Fallback search by sender/subject/time:

```sql
SELECT
    source_message_id,
    sent_at,
    sender_address,
    raw_subject,
    LEFT(latest_guest_turn, 300) AS latest_guest_turn,
    selected_property_code,
    route_outcome,
    draft_source,
    fallback_reason,
    parser_used
FROM message_normalizations
WHERE tenant_id = :tenant_id
  AND sent_at BETWEEN :window_start AND :window_end
  AND sender_address ILIKE :sender_email
  AND raw_subject ILIKE :subject_pattern
ORDER BY sent_at DESC
LIMIT 20;
```

What it means:

- row exists: canonical inbound persistence worked
- no row but `gmail_processed_messages` exists: parser/persist drift; investigate processing code path

## Section 3: Did a pre-booking inquiry get created?

```sql
SELECT
    draft_id,
    received_at,
    guest_email,
    guest_name,
    property_external_id,
    property_external_id_source,
    intent,
    status,
    confidence,
    confidence_source,
    parser_source,
    review_verdict,
    LEFT(message_text, 300) AS message_preview,
    LEFT(draft_text, 300) AS draft_preview
FROM pre_booking_inquiries
WHERE company_id = :tenant_id
  AND (
    gmail_message_id = :gmail_message_id
    OR message_id = :gmail_message_id
    OR (
      guest_email ILIKE :sender_email
      AND received_at BETWEEN :window_start AND :window_end
      AND message_text ILIKE :body_snippet
    )
  )
ORDER BY received_at DESC
LIMIT 20;
```

What it means:

- row exists: it entered pre-booking
- no row but normalization exists: it may have been routed to a guest session, dropped as non-pre-booking, or failed between normalization and inquiry persistence

## Section 4: Was it actually routed somewhere else?

For “missing from pre-booking” cases, check whether the normalization outcome says it was intentionally routed away:

Common `route_outcome` values to look for:

- `guest_session_routed`
- `confirmed_guest_email_received`
- `in_stay`
- `in_stay_pending_review`
- `pre_booking_saved`
- `pre_booking_fallback`
- `pre_booking_gate_review`
- `vendor_ops_email`

If `route_outcome = guest_session_routed` or `in_stay*`, inspect guest-session context:

```sql
SELECT
    token,
    session_id,
    guest_name,
    guest_email,
    property_code,
    status,
    phase,
    created_at,
    last_message_at,
    last_message_preview
FROM concierge_guest_sessions
WHERE tenant_id = :tenant_id
  AND guest_email ILIKE :sender_email
ORDER BY COALESCE(last_message_at, created_at) DESC
LIMIT 20;
```

What it means:

- session row exists and timing matches: the message was not lost; it was routed into guest-session handling
- no session row: routing outcome may be misleading or a downstream persistence step failed

## Section 5: Did it create a gap instead of an answer?

```sql
SELECT
    gap_id,
    created_at,
    property_external_id,
    stage,
    channel,
    source,
    detected_intent,
    confidence_score,
    resolved,
    LEFT(question_text, 300) AS question_preview,
    metadata::text
FROM concierge_knowledge_gaps
WHERE tenant_id = :tenant_id
  AND created_at BETWEEN :window_start AND :window_end
  AND (
    question_text ILIKE :body_snippet
    OR property_external_id = :property_code
  )
ORDER BY created_at DESC
LIMIT 20;
```

What it means:

- gap row with matching question: the system saw the message but failed downstream
- no gap row: it may have been dropped before brain/gap handling

## Interpretation rubric

### Bucket A: Poller saw it, parser stopped it

Evidence:

- `gmail_processed_messages` row exists
- `processing_status` is `quarantined` or `non_guest`
- no `message_normalizations` row

Likely causes:

- false-positive non-guest heuristic
- repeated parse failure / quarantine
- too-short body / malformed email

### Bucket B: Normalized, but no inquiry/session surfaced

Evidence:

- `message_normalizations` row exists
- no matching `pre_booking_inquiries`
- no matching `concierge_guest_sessions`

Likely causes:

- persistence failure after normalization
- gate/retry branch swallowed the message
- downstream route bookkeeping drift

### Bucket C: It surfaced, but not where the operator expected

Evidence:

- `route_outcome` is guest-session or confirmed-guest related
- matching `concierge_guest_sessions` row exists

Likely causes:

- operator checked the pre-booking queue, but the message was classified as in-stay / confirmed guest

### Bucket D: True missing inbound

Evidence:

- no `gmail_processed_messages`
- no `message_normalizations`
- no `pre_booking_inquiries`
- no `concierge_guest_sessions`

Likely causes:

- poller didn’t fetch the message
- wrong operator credential / watched inbox
- identifier mismatch in the audit inputs

## First examples to run

Run this audit first on:

- one “I see it in Gmail but nowhere in Oyvoda” example
- one “it showed up as a weird fallback / gap” example
- one “I think this was actually in-stay but I expected pre-booking” example

That three-example set is usually enough to tell whether you have one root cause or multiple.

