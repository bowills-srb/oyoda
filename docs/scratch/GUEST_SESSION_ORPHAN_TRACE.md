# Guest Session Orphan Trace

Date: 2026-05-27
Tenant: Beach Habitats (`e07980b2-a990-4b24-91d1-c8cb71ab70e1`)
Status: investigation complete enough to confirm contract gap; root cause still needs a follow-up trace at the persistence seam

## Question

Why can `route_outcome = guest_session_routed` appear without a discoverable backing `concierge_guest_sessions` row?

## Example traced

Message normalization row:

- `source_message_id = 19e6a47a94f3b34a`
- subject: `Inquiry from tela hurt: Aug 23 - Aug 28, 2026 - Vrbo #2435514`
- parser: `ota_parser_vrbo`
- `latest_guest_turn = "Hi!!! I am s"` (truncated/poor parse)
- `route_outcome = guest_session_routed`
- `draft_source = guest_session_router`
- `fallback_reason = non_pre_booking_intent:general:0.55`

This is the near-duplicate row adjacent to the real pre-booking tela inquiry.

## Branch taken

In [dispatch_pre_booking](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/email_dispatch.py:818),
the branch is:

1. deterministic intake prefilter returns `inferred_intent`
2. `is_non_pre_booking_intent(inferred_intent)` returns `true`
3. `persist_inbound_from_inquiry(...)` is called
4. DB commit is attempted
5. normalization outcome is written as `guest_session_routed`

The important detail is in [app/services/concierge/post_booking_routing.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/post_booking_routing.py:31):

```python
NON_PRE_BOOKING_INTENTS = frozenset({
    "general",
    "general_inquiry",
    "review_response",
})
```

So `general` is enough to push the message out of pre-booking.

## What the persistence seam claims to do

[persist_inbound_from_inquiry](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/post_booking_routing.py:123)
is supposed to:

- dedupe by `property_context.migration_source.source_message_id` / `draft_id`
- ensure a guest thread
- create a `concierge_guest_sessions` row
- create related journey/message rows
- return `created=True` or `status="already_exists"`

## What I could verify in production

### Exact orphan count

After excluding generic Vrbo relay addresses like `sender@messages.homeaway.com` from false-positive matching:

- `guest_session_routed` outcomes in last 14 days: `9`
- discoverable matching sessions: `2`
- orphaned outcomes: `7`

So this is systemic, not a one-off.

### Tela-specific result

I could not find a `concierge_guest_sessions` row for this tela duplicate by:

- `guest_name ILIKE '%tela%hurt%'`
- `guest_thread_id`
- `property_context -> migration_source -> source_message_id = '19e6a47a94f3b34a'`

That means the recorded route outcome is not backed by a discoverable session row for the same source message.

## Important false-positive detail

A naive orphan audit that matches on `guest_email = sender@messages.homeaway.com` is wrong.

Beach Habitats already has many unrelated guest sessions stored with the generic HomeAway relay address, so matching by sender alone produces false positives and undercounts the orphan rate.

The corrected audit must ignore generic relay addresses and prefer:

- exact `guest_thread_id`
- exact `migration_source.source_message_id`
- non-generic guest email only

## Contract finding

The system currently allows:

- normalization to say `guest_session_routed`
- without a discoverable canonical guest-session row tied to the same message

That is a contract violation on a live canonical surface, not dead legacy drift.

## Most likely interpretations

At least one of these is true:

1. `persist_inbound_from_inquiry(...)` can return/commit in a way that does not yield a durable discoverable session row for the originating message.
2. The route outcome is written too early for what it claims semantically.
3. The join keys used to discover the created session are not the same keys the routing path records.

## Recommendation

Do not paper over this with another bridge.

Next trace should instrument one orphaned route end-to-end and capture:

- result status returned by `persist_inbound_from_inquiry(...)`
- created `session_id` if any
- created `guest_thread_id` if any
- whether commit succeeded
- the exact session row lookup keys written into `property_context`

That will tell us whether the fix is:

- a stricter route outcome (`pending_session_resolution`)
- a persistence bug fix
- or both
