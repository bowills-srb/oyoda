# `ON CONFLICT` Divergence Reconciliation — 2026-05-04

Reconciliation note resolving tracker item B7: the `ON CONFLICT`
semantic divergence between Path 1 (`_save_inquiry`) and Path 2
(`_save_draft`) writing to `pre_booking_inquiries`.

This note establishes the actual divergence shape, names the
behavioral implications, recommends a convention, and identifies the
follow-on work needed before convention enforcement.

This note does not change code. The recommended convention is
documented for confirmation in a future implementation session.

## Purpose

The intake path reconciliation audit (`8a425df`) flagged a behavioral
divergence between Path 1 and Path 2's `ON CONFLICT` semantics. The
flag was preliminary — a closer look during B7 reconciliation shows
the divergence is real but its directionality and implications differ
from the earlier framing.

This note characterizes the divergence accurately, surfaces a
specific safety concern in Path 2's current behavior, and recommends
a convention. Implementation is deferred to a separate session.

## Scope

**In scope:**
- Path 1 (`pre_booking_auto_send._save_inquiry`) `ON CONFLICT` clause
- Path 2 (`pre_booking_handler._save_draft`) `ON CONFLICT` clause
- Database constraints relevant to the conflict resolution
- Upstream dedup mechanisms that gate when conflicts can arise
- Behavioral implications of the current divergence

**Out of scope:**
- Code changes (deferred to follow-on implementation session)
- Path 3 (`_save_fallback_pre_booking_inquiry`) — delegates to
  Path 1's writer and inherits its conflict semantics
- The broader question of whether the canonical contract should
  carry conflict-resolution semantics (architecture-level, not B7
  scope)
- Reprocessing model design beyond what's needed to evaluate the
  current divergence

## The actual divergence

### Path 1 — `_save_inquiry` in `pre_booking_auto_send.py`

```sql
INSERT INTO pre_booking_inquiries (
    ...fields...
) VALUES (
    ...values...
) ON CONFLICT (thread_id, message_id) DO NOTHING
```

Path 1's behavior on conflict: leave the existing row unchanged, do
not modify any field, do not change status. The new write effectively
no-ops if the unique constraint is violated.

### Path 2 — `_save_draft` in `pre_booking_handler.py`

```sql
INSERT INTO pre_booking_inquiries (
    ...fields...
) VALUES (
    ...values...
) ON CONFLICT (thread_id, message_id) DO UPDATE SET
    guest_thread_id = COALESCE(EXCLUDED.guest_thread_id, pre_booking_inquiries.guest_thread_id),
    draft_text = EXCLUDED.draft_text,
    status = 'pending_review',
    policy_flags = EXCLUDED.policy_flags
```

Path 2's behavior on conflict: update four fields on the existing
row. Critically, `status` is unconditionally set to `'pending_review'`,
overwriting whatever status the row currently has.

### Database-level constraint

Migration `018_pre_booking_pipeline.py` defines:

```
draft_id   TEXT UNIQUE NOT NULL
thread_id  TEXT NOT NULL
message_id TEXT NOT NULL DEFAULT ''
UNIQUE (thread_id, message_id)
```

The unique constraint on `(thread_id, message_id)` is real and
enforced. Both `ON CONFLICT` clauses reference this constraint
correctly. The constraint exists independently of either writer.

## Upstream dedup landscape

Two dedup layers operate before either writer's `ON CONFLICT` clause
becomes relevant:

### Layer 1: Gmail message dedup

`gmail_inbox_poller._is_already_processed(...)` queries
`gmail_processed_messages` for `(gmail_message_id, operator_id)`. If
a row exists, the poller returns early and never invokes parsing,
routing, or any writer. This catches normal repeat polling of the
same Gmail message.

```python
async def _is_already_processed(self, gmail_message_id: str) -> bool:
    """Check if we've already processed this Gmail message ID."""
    ...
    result = await self.db.execute(
        text("""SELECT 1 FROM gmail_processed_messages
                WHERE gmail_message_id = :mid AND operator_id = :op LIMIT 1"""),
        {"mid": gmail_message_id, "op": self.operator_id},
    )
    return result.fetchone() is not None
```

### Layer 2: Route outcome downgrade

When dispatch reaches a writer and the save reports `saved=False`,
the route outcome becomes `pre_booking_duplicate` instead of
`pre_booking_new`:

```python
# email_dispatch.py
return "pre_booking_new" if result.get("saved") else "pre_booking_duplicate"
```

This downgrade reflects that the writer attempted but did not insert.
It does not prevent the conflict from firing — it observes that one
fired.

### What the dedup landscape implies

For Path 1, the layer-1 dedup typically prevents the writer from
seeing duplicates. When it does see one (e.g., layer-1 missed a row,
or processing was retried before `_mark_processed` landed), Path 1's
DO NOTHING preserves the existing row. The route outcome reflects
the no-op as `pre_booking_duplicate`.

For Path 2, the same upstream dedup may apply (depending on how Path
2 is reached — Celery worker, webhook, or direct invocation). When
upstream dedup misses, Path 2's DO UPDATE actively mutates the
existing row.

The divergence therefore matters whenever a duplicate write reaches
either writer. That is rare in normal operation but reachable enough
that the semantics matter.

## The safety concern

Path 2's DO UPDATE includes:

```sql
status = 'pending_review'
```

This is unconditional. There is no check on the row's current status.
If the existing row has been operator-actioned — approved, edited,
rejected, or otherwise transitioned — Path 2's DO UPDATE silently
reverts it to pending_review.

Concrete failure mode:

1. Path 2 processes an inquiry, row is inserted with `status = 'pending_review'`
2. Operator reviews, approves, and replies. The row's status transitions to `'replied'` or similar.
3. A reprocessing event reaches Path 2 (upstream dedup miss, retry, or alternate code path)
4. Path 2's DO UPDATE fires. `status` is reset to `'pending_review'`. The operator's action appears undone.
5. The operator may not notice immediately. The inquiry shows up in their queue again as if no action was taken.

Path 1 does not exhibit this behavior. DO NOTHING preserves the
operator's action.

This is not theoretical. The DO UPDATE clause is real production
code; the conditions reaching it are uncommon but reachable; the
resulting state mutation is silent.

## Recommendation

**Both paths should use `DO NOTHING` semantics on conflict.**

Reasoning:

- **Operator state preservation.** DO NOTHING preserves any
  transitions the row has undergone since insertion. DO UPDATE can
  silently revert them. Operator state must not be silently mutated
  by writer-level retry behavior.
- **Idempotency.** Both paths should be idempotent on duplicate
  invocations. DO NOTHING is straightforwardly idempotent. DO UPDATE
  is technically idempotent only if the update payload is identical
  to the existing row, which it is not in Path 2's case.
- **Predictability.** Operators interacting with the queue should
  not need to know which writer produced a row to predict its
  retry behavior.
- **Separation of concerns.** Reprocessing flows that need to update
  an existing inquiry should be explicit reprocessing flows, not
  side effects of a conflict resolution clause. If Path 2 (or any
  future writer) needs to update existing inquiries, that update
  should be a separate code path with explicit operator-state
  awareness.

If Path 2 has a legitimate use case for updating existing inquiries
on retry — e.g., refreshing a draft when the brain produces a
better version — that use case should be served by:

1. An explicit "update inquiry draft" code path that takes a status
   guard, or
2. A new column distinguishing "writer-stamped draft" from "operator-
   approved draft" so DO UPDATE can mutate the former without
   touching the latter

Neither exists today. Until they do, DO NOTHING is the safe convention.

## Forward work

Closing B7 fully requires three pieces of work, in order:

### B7.a: Confirm the recommendation in a follow-on session

This note is the input to the decision, not the decision. A
confirmation session should:

- Verify Path 2 has no legitimate reprocessing requirement that
  would be broken by switching to DO NOTHING
- Confirm whether any production traffic is currently flowing
  through Path 2 (per intake path audit, Path 2 activity is
  unresolved pending worker-tier topology resolution — tracker B4)
- Lock the convention with a committed decision artifact

### B7.b: Implement the convention

A small patch changing Path 2's `ON CONFLICT (thread_id, message_id) DO UPDATE SET ...`
to `ON CONFLICT (thread_id, message_id) DO NOTHING`. Maybe 5 lines of
change. Should ship in its own commit, separate from any other work.

### B7.c: Audit other writers for the same pattern

This audit confirmed Path 1, Path 2, and Path 3 (which delegates to
Path 1). It did not audit other tables or writers in the codebase
that might have similar DO UPDATE clauses with status mutation. A
brief sweep — grep for `DO UPDATE SET.*status` — would catch any
other instances of the pattern.

## Open questions

1. **Does Path 2 have a legitimate reprocessing requirement?** The
   audit cannot determine this from code alone. Path 2 may have been
   built with reprocessing in mind that is not currently exercised
   but is intended to be activated. B7.a should resolve this before
   B7.b proceeds.

2. **Is the worker-tier topology resolution (E1 / B4) a prerequisite
   to B7.b?** Path 2's actual traffic is unknown. Implementing the
   convention before knowing whether Path 2 is live carries low risk
   (the change is a strictly safer behavior, not a riskier one), but
   we'd be patching code that may not be exercised. Worth confirming.

3. **Should the canonical contract carry conflict-resolution
   semantics?** Both writers operate on legacy fragmented argument
   bundles, not `CanonicalInboundMessage`. A canonical-typed writer
   would naturally implement consistent conflict resolution. This is
   architecture-level, larger than B7, and should be considered when
   B1 (Path 1 adaptation) and the broader canonical migration
   proceed.

## Out of scope

This note does not:

- Make code changes to either writer
- Decide the long-term canonical writer's conflict semantics
- Audit non-`pre_booking_inquiries` tables for similar patterns
- Resolve outstanding items from prior audits (Issue 3, worker tier
  topology, etc.)
- Specify the exact diff for B7.b implementation
