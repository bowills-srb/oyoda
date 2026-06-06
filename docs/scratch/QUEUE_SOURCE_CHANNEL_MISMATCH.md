# Queue Service `source_channel` Mismatch — Audit

**Status:** audit only, no code change yet
**Discipline:** `docs/architecture/MIGRATION_DISCIPLINE.md` — Principles 1 (single canonical surface) and 4 (route outcomes must be queryable truth)
**Surfaced:** Session 16, during the pre-Workstream-1 prerequisite review for `PROPERTIES_KB_WORKSTREAM.md`. Originally flagged as a "verify and reconcile later" item in the Known Debt section of `docs/MESSAGING_BRAIN_PREBOOKING_BEACH_HABITATS_ROLLOUT.md`.
**Why it matters now:** this mismatch silently degrades the operator dashboard's view of the exact traffic the Phase 1 brain cutover just enabled, and it directly threatens the correctness of the post-cutover prerequisite check if that check is run through the queue service rather than against the tables.
**Decision (Session 16):** Path B — fix this queue mismatch next, before Properties v0.1.1 polish. Re-ranked deliberately, not parked. See Recommended sequencing below.

---

## The channel model (clarified by Hunter, Session 16)

Oyvoda's ingest model for OTA inbound is:

- Some PMS systems don't expose an API into their guest communications.
- Those PMSes forward inbound OTA messages into the operator's **business email inbox**.
- That inbox can be hosted anywhere — Gmail, Outlook, Fastmail, etc.
- Oyvoda's objective is: the operator connects their email, and that's it.

Therefore the **canonical channel** for this traffic is `email` — the
operator's connected inbox — regardless of the underlying mail host.

The mail host (Gmail vs Outlook) is an **ingest/transport implementation
detail**, not a channel identity. Beach Habitats' business email happens
to be hosted on Gmail, so Oyvoda polls it via the Gmail API. That is *how*
the message is fetched, not *what channel it is*.

These two concepts must not be conflated:

| Concept | Example value | Where it belongs |
|---------|---------------|------------------|
| Canonical channel | `email` | `message_normalizations.source_channel`, any channel-level routing/query logic |
| Ingest/transport mechanism | Gmail API poll | internal poller detail; may appear in `gmail_message_id`, provider fields, parser notes — never as a channel identity in a join predicate |

## Confirmed facts (from code, Session 16)

### Write side — correct

`app/services/integrations/email_dispatch.py`:

```python
def _normalization_source_channel() -> str:
    return "email"
```

Dispatch writes (and later updates) `message_normalizations` rows with
`source_channel = "email"`. Both the initial persist and
`update_normalization_outcome(...)` use this same value, so the dispatch
path is internally consistent — the `message_normalizations` table holds
correct, complete rows under `source_channel = 'email'`, including
`draft_source`, `route_outcome`, `fallback_reason`, `selected_property_code`,
and the structured-ask columns.

`update_normalization_outcome` even logs a warning when its UPDATE matches
0 rows. That warning would NOT fire from a self-mismatch, because dispatch
agrees with itself. (Worth checking production logs for this line anyway —
its presence would indicate a *different* problem upstream.)

### Read side — stale

`app/services/operator/prebooking_queue_service.py`, `_compute_live_rows`,
`primary_sql`:

```sql
LEFT JOIN message_normalizations mn
    ON mn.tenant_id = CAST(:tid AS uuid)
   AND mn.source_channel = 'gmail'          -- <-- stale transport literal
   AND mn.source_message_id = pbi.gmail_message_id
```

The join hardcodes `source_channel = 'gmail'`. Under the channel model
above, this is the transport/channel conflation: it keys off how Beach
Habitats happens to be ingested rather than the canonical channel the
writer recorded. Nothing in the dispatch path writes `'gmail'`, so this
predicate matches none of the brain-dispatched rows.

## Impact

### Today (Beach Habitats, Gmail-hosted)

- The join is a `LEFT JOIN`, so `pre_booking_inquiries` rows still appear
  in the queue — the queue is NOT empty.
- But every `mn.*` column comes back NULL for brain-dispatched rows:
  `normalization_draft_source`, `route_outcome`, `fallback_reason`,
  `selected_property_code`, `selected_property_match_type`,
  `latest_guest_turn`, `prior_thread_context`, `normalized_asks`,
  `prior_operator_commitments`, `latest_turn_confidence`,
  `latest_turn_extracted`, `source_provider`.
- Net effect: the operator dashboard shows the inquiry but loses all the
  brain's enrichment and attribution for it — for the exact traffic the
  Phase 1 cutover just routed through the brain.

### The moment a second operator connects a non-Gmail inbox

This is the structural problem, not just a Beach Habitats quirk. If an
operator connects an Outlook-hosted inbox, dispatch will still write
`source_channel = 'email'` (correct). The queue join will still look for
`'gmail'`. So the join would be **structurally incapable** of ever matching
that operator's rows — there is no code path that would ever write `'gmail'`
for them. The bug doesn't widen gracefully; it fails completely for the
next operator.

## Direct threat to the prerequisite check

The rollout doc's verification step says to confirm the corresponding
`message_normalizations` row has `draft_source = 'messaging_brain'`. There
are two ways to run that check and they currently give OPPOSITE answers
(this is the post-cutover prerequisite check from `PROPERTIES_KB_WORKSTREAM.md`):

- **Direct table query** (query `message_normalizations` directly, or join
  on `source_channel = 'email'`): shows correct
  `draft_source = 'messaging_brain'`. Cutover looks healthy. ✓
- **Through the queue service / operator dashboard**: shows NULL
  `normalization_draft_source` for every row. Cutover looks broken. ✗

**Instruction for the prerequisite check: run the verification queries
DIRECTLY against `pre_booking_inquiries` and `message_normalizations`,
NOT through the queue service, until this mismatch is fixed.** Otherwise
a healthy cutover could be misread as a failure and rolled back.

## Open questions (require a production query — codex/Hunter, not resolvable from code)

1. **Is `(tenant_id, source_message_id)` unique in `message_normalizations`
   across all channels?** This determines the safe fix. If unique, the join
   can drop the channel predicate entirely and match on
   `tenant_id + source_message_id`. If not unique (some other surface writes
   a non-`email` channel with colliding message ids), the join should pin to
   `source_channel = 'email'` explicitly.

   ```sql
   SELECT source_message_id, COUNT(*) AS rows,
          COUNT(DISTINCT source_channel) AS distinct_channels
   FROM message_normalizations
   WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
   GROUP BY source_message_id
   HAVING COUNT(*) > 1
   ORDER BY rows DESC
   LIMIT 50;
   ```

2. **What distinct `source_channel` values actually exist in production?**
   Confirms `'email'` is the live umbrella value and reveals whether any
   legacy `'gmail'` rows exist that a fix would need to account for.

   ```sql
   SELECT source_channel, COUNT(*) AS rows,
          MIN(created_at) AS earliest, MAX(created_at) AS latest
   FROM message_normalizations
   WHERE tenant_id = 'e07980b2-a990-4b24-91d1-c8cb71ab70e1'
   GROUP BY source_channel
   ORDER BY rows DESC;
   ```

3. **Does `mn.source_message_id = pbi.gmail_message_id` hold for non-Gmail
   ingest?** Even after fixing the channel literal, the join also requires
   the id match. For a Gmail-hosted inbox `pbi.gmail_message_id` is
   populated; for an Outlook-hosted inbox it may be empty or named
   differently. The durable fix may need a channel-neutral message-id
   column on `pre_booking_inquiries`, not `gmail_message_id` specifically.
   This is a larger correctness question than the channel literal alone and
   may warrant its own follow-up.

## Candidate fixes (do not implement until open questions are answered)

Ordered from most-contained to most-durable:

1. **Pin to canonical channel.** Change `mn.source_channel = 'gmail'` to
   `mn.source_channel = 'email'`. Smallest change. Fixes Beach Habitats and
   any future email-connected operator. Does NOT address the
   `gmail_message_id` id-match question (open question 3).

2. **Drop the channel predicate.** Match on
   `mn.tenant_id = :tid AND mn.source_message_id = pbi.gmail_message_id`
   only. Correct ONLY if open question 1 confirms
   `(tenant_id, source_message_id)` uniqueness. Removes the
   transport/channel conflation entirely (best aligned with Principle 1).

3. **Channel-neutral id + canonical channel.** Address open question 3 by
   joining on a channel-neutral message-id column and pinning
   `source_channel = 'email'`. Most durable for multi-provider operators,
   largest change, likely its own commit.

The same `'gmail'`-flavored assumption appears elsewhere in the queue
service and should be audited as part of any fix, not just the one join:

- `_persist_rows` writes `source_message_id` from
  `row.get("gmail_message_id") or row.get("message_id")`
- `_load_cached_rows` aliases `source_message_id AS gmail_message_id` and
  `thread_id AS gmail_thread_id`
- the read-model column is named `gmail_message_id` in places

A clean fix names the concept `message_id` / `source_message_id`
consistently and treats Gmail as one ingest path, not the identity.

## Recommended sequencing

This is a reader/queue correctness fix, adjacent to but distinct from the
Properties/KB workstream. Per `MIGRATION_DISCIPLINE.md` ("if a change to one
of those areas seems required mid-workstream, stop and write a fresh anchor
doc; don't drift"), it is captured here rather than folded into a Properties
commit.

Decided order (Path B, Session 16):

1. **The prerequisite check runs against the tables directly** (per the
   instruction above), unaffected by this bug.
2. **Run the three open-question queries** to determine the safe fix shape.
3. **Fix the queue mismatch next**, before Properties v0.1.1 polish. Chosen
   over the prior plan because it degrades the operator's view of every
   brain-sourced row right now and blocks the next non-Gmail operator
   entirely — higher leverage and more contained than the polish work.
4. **Then return to** `docs/scratch/PROPERTIES_KB_WORKSTREAM.md`.

## Status

Audit only. No code change yet. Path B chosen: this fix precedes Properties
v0.1.1 polish. Next concrete step: run the prerequisite check against the
tables directly, then run the three open-question queries (production), then
pick a candidate fix and write the fix commit against the answer. Until
fixed, all post-cutover verification runs against `pre_booking_inquiries`
and `message_normalizations` directly, never through the queue service.
