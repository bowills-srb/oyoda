## Phase 4.3-J Intake Identity Audit

Date: 2026-05-17

Scope: Production diagnosis of `INQ-69214887` (Monica Duvall, received `2026-05-17 20:29:28+00`)

Trigger: Operator review of Monica Duvall's parking follow-up showed a weak, unbound pre-booking draft even though the earlier thread had already resolved to property `31GARD` ("3 By The Sea").

### Executive Summary

The initial hypothesis was wrong in one important way: `INQ-69214887` does **not** prove a surviving Phase 4.3-I normalization-invariant bypass.

What production actually shows:

- `INQ-69214887` was saved with canonical `message_id` and `thread_id`.
- It later received a `message_normalizations` row from the Phase 4.3-I historical backfill.
- The tenant-wide canonical invariant currently holds: active rows with `message_id` present and no matching normalization row by `message_id` = `0`.

The real production failure is narrower and different:

- The May 17 follow-up arrived on the same canonical thread as Monica's May 14 parking question.
- The live intake path failed to carry forward or recover the property binding (`31GARD`) on that follow-up.
- Because `parsed.property_code` stayed empty, the guest-thread resolver created a new Monica thread with `property_code = NULL` instead of reusing the existing `31GARD` thread.
- The draft then went through the normal pre-booking pipeline with empty property context and produced a weak knowledge-gap hold.

There is also a secondary observability issue:

- some active rows preserve canonical `message_id/thread_id` but leave the legacy `gmail_message_id/gmail_thread_id` mirror fields blank
- audits that join only on `gmail_message_id` will misclassify those rows as "missing normalization" even when canonical normalization exists

### Production Evidence

#### 1. The problematic inquiry row

```sql
SELECT draft_id, message_id, thread_id, gmail_message_id, gmail_thread_id,
       platform, guest_name, intent, property_external_id, company_id,
       tenant_id, archived_at
FROM pre_booking_inquiries
WHERE draft_id = 'INQ-69214887';
```

Result:

```text
draft_id      INQ-69214887
message_id    19e36fe0ce3b4611
thread_id     19e28332e4d7a1e4
gmail_message_id NULL
gmail_thread_id  NULL
platform      direct
guest_name    MONICA DUVALL
intent        amenities
property_external_id NULL/empty
archived_at   NULL
```

Interpretation:

- canonical message identity is present
- legacy Gmail mirror fields are blank
- property binding is blank

#### 2. There is a normalization row for Monica's follow-up

```sql
SELECT *
FROM message_normalizations
WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'::uuid
  AND source_message_id = '19e36fe0ce3b4611';
```

Result (shortened):

```text
source_channel            email
source_provider           direct
source_thread_id          19e28332e4d7a1e4
source_message_id         19e36fe0ce3b4611
latest_guest_turn         Can someone please let me know about parking before I sign the contract? Thanks
selected_property_code    NULL
parser_used               phase_4_3_i_backfill
route_outcome             historical_unprocessed
draft_source              phase_4_3_i_backfill
fallback_reason           retrospective_normalization_no_draft_generation
created_at                2026-05-17 21:00:35+00
```

Interpretation:

- the row was not normalized live
- it was repaired by the Phase 4.3-I backfill about 31 minutes later
- the backfill did not recover property binding, so the normalization row remains unbound

#### 3. Guest-thread continuity split

```sql
SELECT *
FROM guest_threads
WHERE guest_thread_id IN (
  'ad4f2736-45c0-4eae-9f1d-87fb73591353'::uuid,
  '3ccbbe39-c9bb-4ee9-93ce-362620eefe8d'::uuid
);
```

Result:

```text
ad4f2736-45c0-4eae-9f1d-87fb73591353  property_code=31GARD  guest_name=Monica Duvall  inquiry_thread_id=19e219585cc5a11e
3ccbbe39-c9bb-4ee9-93ce-362620eefe8d  property_code=NULL    guest_name=MONICA DUVALL  inquiry_thread_id=19e28332e4d7a1e4
```

Interpretation:

- Monica already had an existing guest thread bound to `31GARD`
- the May 17 follow-up created a second Monica thread with no property binding

#### 4. Earlier thread history proves property resolution itself works

```sql
SELECT draft_id, message_id, thread_id, gmail_message_id, gmail_thread_id,
       property_external_id, message_text, intent, confidence, received_at
FROM pre_booking_inquiries
WHERE thread_id = '19e28332e4d7a1e4'
ORDER BY received_at;
```

Result:

```text
INQ-7CEDCCB2  message_id=19e28332e4d7a1e4  property_external_id=31GARD
INQ-69214887 message_id=19e36fe0ce3b4611  property_external_id=''
```

The May 14 message on the same thread explicitly said:

> We have booked 3 By The Sea...

and was resolved to `31GARD`.

The May 17 follow-up on that same thread said:

> Can someone please let me know about parking before I sign the contract? Thanks

and lost the property binding on the live pass.

#### 5. Canonical property and parking knowledge exist

`properties` row:

```text
property_code     31GARD
address_street    31 Gardenia - 3 By the Sea
bedrooms          3
bathrooms         3.5
parking_instructions present
```

`concierge_scoped_knowledge` includes a `parking` topic for `31GARD`.

Interpretation:

- this is not a missing-knowledge problem in the canonical store
- it is an identity/property-binding problem before drafting

### Code Trace

#### Live save path

`INQ-69214887` was produced by the normal pre-booking draft path, not a manual row insert and not an unmigrated normalization bypass.

Evidence:

- the saved row contains the standard pre-booking knowledge-gap hold warning
- the draft text and warning shape match `detect_missing_knowledge(...)` inside:
  - [pre_booking_auto_send.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/pre_booking_auto_send.py:2465)
- the save path for normal pre-booking drafts is:
  - `dispatch_pre_booking(...)`
  - `process_pre_booking_inquiry(...)` or `process_pre_booking_inquiry_with_draft(...)`
  - `PreBookingPipelineOrchestrator.persist_and_dispatch(...)`
  - `save_inquiry_from_canonical(...)`
  - `persist_pre_booking_inquiry_with_normalization(...)`
  - `_save_inquiry(...)`

Key code references:

- [email_dispatch.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/email_dispatch.py:607)
- [pre_booking_auto_send.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/pre_booking_auto_send.py:2547)
- [inquiry_persistence.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/inquiry_persistence.py:15)

#### Where the property binding was lost

The live property resolver in the Gmail poller uses only the current parsed property signals:

- `platform_listing_id`
- `platform_unit_id`
- `raw_property_mention`
- `property_name`

Reference:

- [gmail_inbox_poller.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/gmail_inbox_poller.py:2570)

That resolver does **not** use:

- prior normalized rows on the same canonical `thread_id`
- existing `guest_thread` property binding
- conversation-history-derived property context

The generic identity used for both prompt-time thread lookup and persistence is:

- `tenant_id`
- `property_code`
- `guest_name`
- `inquiry_thread_id`

Reference:

- [email_dispatch.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/email_dispatch.py:232)

Because Monica's follow-up reached this step with:

- `thread_id = 19e28332e4d7a1e4`
- `guest_name = MONICA DUVALL`
- `property_code = ''`

the resolver called:

- `GuestThreadService.ensure_inquiry_thread(... property_code='', inquiry_thread_id='19e28332e4d7a1e4')`

Reference:

- [guest_thread_service.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/guest_thread_service.py:26)

`GuestThreadService` checks:

1. `session_token`
2. `inquiry_thread_id`
3. `(property_code, guest_name_norm)` if property exists

The existing Monica `31GARD` thread was anchored on a different original inquiry thread id (`19e219585cc5a11e`), so the follow-up did not match query #2.
Because `property_code` was empty, it could not match query #3 either.
Result: a second Monica thread was inserted with `property_code = NULL`.

### Parser-path finding

The strongest evidence points to the generic inbound-email path rather than a direct-website-form parser:

- platform is `direct`
- canonical `message_id/thread_id` are present
- the email body was reduced to a clean latest guest turn with no preserved quoted context
- the direct website parser requires website-form markers such as `Listing of Interest:` / `Comments/Questions:` / `submitted values are:`
- Monica's observed email shape did not resemble a website form; it was a plain conversational follow-up

Relevant code:

- LLM/generic inbound path:
  - [email_parser_router.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/email_parser_router.py:410)
  - [gmail_inbox_poller.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/gmail_inbox_poller.py:1688)
- direct website-form parser:
  - [direct_email_parsers.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/direct_email_parsers.py:41)

This parser-branch identification is an inference from production row shape plus code, not directly logged production metadata.

### Phase 4.3-I Invariant Status

The original brief assumed Monica's row proved the invariant failed. Production data shows otherwise.

Canonical invariant check:

```sql
SELECT COUNT(*) AS invariant_violations_by_message_id
FROM pre_booking_inquiries pbi
LEFT JOIN message_normalizations mn
  ON mn.tenant_id = pbi.company_id
 AND mn.source_channel = 'email'
 AND mn.source_message_id = pbi.message_id
WHERE pbi.company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'::uuid
  AND pbi.archived_at IS NULL
  AND pbi.message_id IS NOT NULL
  AND pbi.message_id <> ''
  AND mn.source_message_id IS NULL;
```

Result:

```text
0
```

So:

- the canonical invariant currently holds
- Monica's row was repaired by the historical backfill
- the earlier diagnosis was thrown off by looking at `gmail_message_id` instead of canonical `message_id`

### Test-scope finding

The current "invariant" tests in:

- [test_pre_booking_normalization_invariant.py](/Users/dhuntermckenzie/Downloads/oyvoda/tests/unit/test_pre_booking_normalization_invariant.py:1)

do **not** implement a tenant-wide row invariant query.

They only test the helper seam:

- base normalization row must exist before save
- outcome update happens after save

That means the tests would never catch:

- rows normalized only after a backfill
- rows whose canonical normalization exists but legacy mirror fields are blank
- property-binding/thread-continuity failures like Monica's

This is not a "wrong filter" problem in the current test; it is a narrower-than-brief implementation of the invariant.

### Quantification

#### A. Canonical normalization invariant

```text
active rows with message_id present and no matching normalization row: 0
```

#### B. Active rows with blank Gmail mirror fields but canonical message identity present

```sql
SELECT COUNT(*)
FROM pre_booking_inquiries
WHERE company_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'::uuid
  AND archived_at IS NULL
  AND message_id IS NOT NULL
  AND message_id <> ''
  AND (gmail_message_id IS NULL OR gmail_message_id = '');
```

Result:

```text
31
```

Breakdown of matching normalization rows for those 31 active rows:

```text
phase_4_3_i_backfill / historical_unprocessed / phase_4_3_i_backfill : 30
llm_email_extractor_groq / pre_booking_gate_skipped / inbound_gate   : 1
```

Recent sample:

```text
INQ-69214887  19e36fe0ce3b4611  19e28332e4d7a1e4  2026-05-17 20:29:28+00
INQ-C1D0068D  19e368d19c174deb  19e368d19c174deb  2026-05-17 18:07:16+00
INQ-D0DE3857  19dc5a30cdc6ea30  19dc5a30cdc6ea30  2026-04-25 17:15:06+00
INQ-2AF79032  19dc57baed7b1169  19dc57baed7b1169  2026-04-25 16:33:57+00
INQ-CF0289C6  19dc56f54118486f  19dc56f54118486f  2026-04-25 16:18:54+00
```

Interpretation:

- Monica is not an isolated row with blank Gmail mirror fields
- but she is the highest-signal example because the same conversation already had a good property binding on the prior thread turn

#### C. Missing-property-binding rows remain broad

Active rows with canonical `message_id` present but empty `property_external_id`:

```text
229
```

This is the same unbound population surfaced in earlier queue audits and confirms the broader property-binding problem still exists beyond Monica.

### Diagnosis

`INQ-69214887` is best understood as:

1. a normal direct-email pre-booking intake
2. on a known canonical thread
3. that failed live property binding on the follow-up turn
4. which caused guest-thread fragmentation
5. which produced a weak knowledge-gap draft
6. and which was later backfilled for normalization only

It is **not**:

- a surviving unmigrated writer path that bypassed `persist_pre_booking_inquiry_with_normalization(...)`
- a current post-4.3-I canonical normalization invariant violation
- a proof that canonical property knowledge for `31GARD` is missing

### Recommended Fix Shape

Do not write the next brief as a normalization-gap fix.

The targeted follow-up should be a property-binding/thread-continuity brief:

1. teach follow-up direct-email intake to reuse prior thread property binding when canonical `thread_id` already has normalized history with `selected_property_code`
2. expand thread identity resolution so follow-up turns on the same canonical `thread_id` can inherit existing guest-thread/property context before drafting
3. preserve or backfill `gmail_message_id/gmail_thread_id` mirror fields consistently, or stop using them in audits that are really about canonical email identity
4. add a regression test for:
   - follow-up email on an existing canonical thread
   - empty current-message property mention
   - prior turn already bound to a property
   - expected outcome: same `guest_thread_id`, same `property_external_id`
5. add a tenant-wide integration test for "no active row with `message_id` present should be missing normalization", because the current helper tests do not assert that contract at dataset level

### Conclusion

Monica's case surfaced a real production defect, but the defect is more precise than the initial brief assumed:

- the system preserved canonical email identity
- the system later repaired normalization
- the system failed to preserve property identity across a follow-up direct-email turn

That is the layer that should be fixed next.
