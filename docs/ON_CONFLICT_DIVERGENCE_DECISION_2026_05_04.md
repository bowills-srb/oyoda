# `ON CONFLICT` Divergence Decision — 2026-05-04

**Status: Confirmed. Recommendation locked pending the implementation
condition in §7. Supersedes the reconciliation note at
`docs/ON_CONFLICT_DIVERGENCE_RECONCILIATION_2026_05_04.md`
(commit 20b4e6e).**

This document confirms the decision for tracker item B7: the
`ON CONFLICT` semantic divergence between Path 1
(`pre_booking_auto_send._save_inquiry`) and Path 2
(`pre_booking_handler._save_draft`) writing to
`pre_booking_inquiries`.

The decision is informed by a call-site trace conducted during
confirmation (§4), which materially strengthens the case for the
recommendation by resolving the central open question from the prior
reconciliation note.

This document does not change code. The recommended convention is
documented for implementation in a separate session, gated by §7.

## 0. Operational context at confirmation

This confirmation was made on 2026-05-04 against the following
operational state:

- **Watch window:** 9 of 50 brain drafts attributed; mix is varied
  across direct, Airbnb, and Vrbo channels. Brain pipeline is live
  and growing.
- **Brain-rollout context:** Path 2 (`_save_draft`) sits on the brain
  side of the pre-booking handler. Whether the `ON CONFLICT DO UPDATE`
  clause was intentionally designed to support brain-driven draft
  refresh was a load-bearing question for this confirmation. The
  call-site trace in §4 resolves it.
- **Issue 3:** Self-healed but with residual normalization gap (4 of
  13 in-window inquiries). Not directly material to B7 but informs
  the implementation risk posture in §6.
- **B11 (legacy `pre_booking_auto_send` orchestration disposition):**
  Unresolved. Path 1's continued existence is therefore uncertain
  long-term, but its current `ON CONFLICT DO NOTHING` semantics are
  not the source of the safety concern this decision addresses.

## 1. Decision made

The intake path reconciliation audit (`8a425df`) flagged a behavioral
divergence between Path 1 and Path 2's `ON CONFLICT` semantics. The
B7 reconciliation note (`20b4e6e`) characterized the divergence
accurately and surfaced a specific safety concern in Path 2's
behavior. This document confirms the recommended convention.

The decision is: **what `ON CONFLICT` semantics should
`pre_booking_inquiries` writers use?**

**Decision: Both paths use `ON CONFLICT (thread_id, message_id) DO
NOTHING`.**

What this document does *not* decide:

- The exact diff for the implementation patch (B7.b)
- Whether Path 1 or Path 2 will eventually be retired in favor of a
  canonical-typed writer (architecture-level, separate from B7)
- Whether the canonical contract should carry conflict-resolution
  semantics (architecture-level, separate from B7)
- Conflict semantics for any other table or writer in the codebase
  (subject to B7.c sweep)

## 2. The actual divergence

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

```sql
draft_id   TEXT UNIQUE NOT NULL
thread_id  TEXT NOT NULL
message_id TEXT NOT NULL DEFAULT ''
UNIQUE (thread_id, message_id)
```

The unique constraint on `(thread_id, message_id)` is real and
enforced. Both `ON CONFLICT` clauses reference it correctly. The
constraint exists independently of either writer.

### Internal inconsistency in Path 2's `DO UPDATE`

Path 2's `DO UPDATE` clause updates `guest_thread_id`, `draft_text`,
`status`, and `policy_flags` — but does not update `draft_id`. The
caller pipeline generates a fresh `draft_id` via
`uuid.uuid4().hex[:8].upper()` on every invocation. On conflict, the
freshly-generated `draft_id` from the `INSERT` portion is silently
discarded, while the new `draft_text` overwrites the existing one.

The result is a row with the original `draft_id` but mutated
`draft_text`. Any downstream system keyed on `draft_id` would point
at the original draft while the row's `draft_text` reflects a newer
generation. This is not a designed refresh semantics; it is a
clause whose field selection was not considered against the
caller's behavior.

This internal inconsistency reinforces the case for `DO NOTHING`:
the current `DO UPDATE` is not just risky on operator-actioned rows
(§3), it is incoherent on its own terms.

## 3. The safety concern

Path 2's `DO UPDATE` includes:

```sql
status = 'pending_review'
```

This is unconditional. There is no check on the row's current
status. If the existing row has been operator-actioned — approved,
edited, rejected, or otherwise transitioned — Path 2's `DO UPDATE`
silently reverts it to `pending_review`.

Concrete failure mode:

1. Path 2 processes an inquiry; row inserted with
   `status = 'pending_review'`.
2. Operator reviews, approves, replies. The row's status transitions
   to `'replied'` or similar.
3. A reprocessing event reaches Path 2 (upstream dedup miss, retry,
   or alternate code path).
4. Path 2's `DO UPDATE` fires. `status` is reset to
   `'pending_review'`. The operator's action appears undone.
5. The operator may not notice immediately. The inquiry shows up in
   their queue again as if no action had been taken.

Path 1 does not exhibit this behavior. `DO NOTHING` preserves the
operator's action.

This is not theoretical. The `DO UPDATE` clause is real production
code; the conditions reaching it are uncommon but reachable; the
resulting state mutation is silent.

## 4. Call-site trace findings

A call-site trace was conducted during confirmation to resolve the
load-bearing open question from the reconciliation note: whether
Path 2 has a legitimate refresh/reprocessing caller that `DO NOTHING`
would break.

### Trace methodology

```bash
rg -n "_save_draft\\(" app/services/ --glob "*.py"
rg -n "_save_draft\\(" app/ --glob "*.py"
```

Plus targeted reading of `_save_draft`'s definition and surrounding
caller context in `app/services/concierge/pre_booking_handler.py`.

### Findings

**1. Single call site, repo-wide.** `_save_draft` is invoked from
exactly one location: line 713 of
`app/services/concierge/pre_booking_handler.py`, inside
`process_inquiry`. No other production code, no test fixtures, no
scripts invoke it.

**2. The single caller is a straight-line initial-save pipeline.**
`process_inquiry` runs the following sequence: classify intent →
generate AI draft → policy check → build draft object → persist via
`_save_draft` → alert operator. Each step produces fresh values for
the row.

**3. No refresh-intent signals in the caller path.**

- No retry loop around the `_save_draft` call.
- No regenerate/update-existing branch.
- No pre-check for an existing inquiry row.
- No comment or control flow suggesting "replace prior draft with
  newer draft."
- No brain-specific refresh-this-existing-inquiry logic upstream.

**4. The pipeline generates fresh identifiers each invocation.**
`draft_id` is produced via `uuid.uuid4().hex[:8].upper()` inside the
build step. A refresh path would look up the existing row's
`draft_id`; this pipeline does not. The pipeline does not know about
prior rows.

**5. Brain-rollout integration is single-shot.** Despite Path 2
sitting on the brain side of the handler, the brain's draft
generation is not designed to refresh an existing inquiry. If
brain-driven refresh becomes a real feature, the trace shows it
would need an explicit code path; it is not served today by this
`ON CONFLICT` clause.

### Implication

The reconciliation note's framing was: "we recommend `DO NOTHING`
and assume nothing legitimately needs `DO UPDATE`." The trace
permits the stronger statement: **we verified through call-site
tracing that no current code path in the repository invokes
`_save_draft` with refresh intent, and we recommend `DO NOTHING` on
that basis.**

The "legitimate reprocessing requirement" question, listed as open
in the reconciliation note, is closed by the trace findings.

## 5. Residual runtime-retry caveat

Code-level absence of refresh intent does not fully rule out
runtime conditions where Path 2 fires twice for the same
`(thread_id, message_id)`. Possible runtime causes:

- Gmail poller retries after a partial failure where
  `_mark_processed` did not land.
- Celery task redelivery from worker-tier instability.
- Manual re-invocation during incident recovery.
- Webhook redelivery from Airbnb or Vrbo channels with at-least-once
  semantics.

The trace shows nothing in code is *designed* to invoke `_save_draft`
twice for the same inquiry. The trace does not show it cannot
*happen* at runtime.

This caveat supports `DO NOTHING`, not against it. If the only way
Path 2 sees a duplicate is unintentional retry, then `DO NOTHING` is
exactly the behavior the system wants: preserve the existing row,
do not silently mutate operator-actioned state. The current
`DO UPDATE` is not serving an intentional retry use case; it is
silently reverting state on unintentional retries.

The caveat is named here for completeness, not as a complication.

## 6. Recommendation

**Both paths use `ON CONFLICT (thread_id, message_id) DO NOTHING`.**

### Reasoning

**1. Operator state preservation.** `DO NOTHING` preserves any
transitions the row has undergone since insertion. `DO UPDATE` can
silently revert them. Operator state must not be silently mutated
by writer-level retry behavior.

**2. Idempotency.** Both paths should be idempotent on duplicate
invocations. `DO NOTHING` is straightforwardly idempotent.
`DO UPDATE` is technically idempotent only if the update payload is
identical to the existing row, which it is not in Path 2's case.

**3. Predictability.** Operators interacting with the queue should
not need to know which writer produced a row to predict its retry
behavior.

**4. Separation of concerns.** Reprocessing flows that need to
update an existing inquiry should be explicit reprocessing flows,
not side effects of a conflict resolution clause. If Path 2 (or any
future writer) needs to update existing inquiries, that update
should be a separate code path with explicit operator-state
awareness.

**5. Internal consistency.** Path 2's current `DO UPDATE` field
selection is incoherent (§2). `DO NOTHING` removes the
inconsistency cleanly; an alternative would be patching the field
selection, but that path has no caller asking for it (§4).

**6. Empirical caller absence.** The call-site trace found no caller
that would need `DO UPDATE` semantics. The change is therefore not
removing functionality the system depends on; it is removing a
clause that no caller intentionally invokes.

If a legitimate use case for updating existing inquiries on retry
emerges in the future — e.g., refreshing a brain draft when a better
version is generated — that use case should be served by:

- An explicit "update inquiry draft" code path that takes a status
  guard, or
- A new column distinguishing "writer-stamped draft" from
  "operator-approved draft" so a future `DO UPDATE` can mutate the
  former without touching the latter.

Neither exists today. Until they do, `DO NOTHING` is the convention.

## 7. Implementation condition

The recommendation is confirmed but conditional. Before the
implementation patch (B7.b) ships, the following must be true:

**7.1 Re-run the call-site trace.**

```bash
rg -n "_save_draft\\(" app/ --glob "*.py"
```

The trace finding of "single call site, no refresh-intent signals"
is what licenses `DO NOTHING` as the convention without further
investigation. If new callers have appeared between this
confirmation and B7.b implementation — particularly any caller that
looks like a refresh path — the recommendation needs re-evaluation
before the patch ships.

This is a paranoid check. It is also cheap. It should run as a
mandatory pre-step to B7.b regardless of how soon implementation
follows confirmation.

If the re-run reveals new callers with refresh intent, B7.b should
not proceed; the decision should be re-opened with the new caller
context as input.

## 8. Forward work

Closing B7 fully requires two pieces of remaining work:

**B7.b: Implement the convention.** A small patch changing Path 2's
`ON CONFLICT (thread_id, message_id) DO UPDATE SET ...` to
`ON CONFLICT (thread_id, message_id) DO NOTHING`. Approximately 5
lines of change. Should ship in its own commit, separate from any
other work. Gated by §7.1.

**B7.c: Audit other writers for the same pattern.** This decision
addressed Path 1, Path 2, and Path 3 (which delegates to Path 1's
writer and inherits its conflict semantics). It did not audit other
tables or writers in the codebase that might have similar
`DO UPDATE` clauses with status mutation. A brief sweep — `rg`
across the codebase for `DO UPDATE SET.*status` and similar
patterns — would catch any other instances. Independent of B7.b
and can run in parallel.

## 9. Open risks

The risks worth naming explicitly:

- **Runtime retry conditions are unknown.** §5 names possible
  runtime causes for duplicate Path 2 invocation. The trace cannot
  measure how often these fire in production. Whatever the rate,
  `DO NOTHING` is the correct behavior; but the rate at which
  duplicate writes are reaching Path 2 today is not measured.
  Operationally this means we do not know how much silent state
  reversion has already happened. If this is a concern, the route
  outcome `pre_booking_duplicate` log volume on Path 2 specifically
  is the metric worth pulling — separate work, not in B7's scope.

- **Future canonical writer should inherit `DO NOTHING` by
  default.** The canonical migration (B-workstream) will eventually
  produce a canonical-typed writer for `pre_booking_inquiries`.
  That writer should adopt `DO NOTHING` semantics by default; any
  deviation should require explicit justification per §6.4. Worth
  noting now so the convention survives the migration.

- **The decision artifact itself ages.** This artifact reflects
  state as of 2026-05-04. If B7.b implementation does not happen
  promptly, §7.1 catches caller drift, but other context (Path 2's
  traffic levels, brain-rollout state, B11 disposition) may have
  shifted in ways worth re-checking before patching.

## 10. What confirmation unblocks

With this decision confirmed:

- **B7.b implementation** is unblocked, gated by §7.1's pre-step
  re-trace.
- **B7.c codebase sweep** is unblocked and can run independently of
  B7.b.
- **Future canonical writer design** has a stated default for
  conflict semantics (per §9, second risk).

## 11. Trace appendix

For auditability, the exact commands and findings from the §4
call-site trace are recorded here.

### Commands

```bash
sed -n '700,790p' app/services/concierge/pre_booking_handler.py
rg -n "_save_draft\\(" app/services/ --glob "*.py"
rg -n "_save_draft\\(" app/ --glob "*.py"
```

### Repo-wide call sites

```text
./app/services/concierge/pre_booking_handler.py:713:
await self._save_draft(draft, db)
./app/services/concierge/pre_booking_handler.py:720:
async def _save_draft(self, draft: InquiryDraft, db) -> None:
```

(Line 720 is the function definition, not a call.)

### Caller context summary

`process_inquiry(...)` in `pre_booking_handler.py`:

1. Classify intent
2. Generate AI draft
3. Policy check
4. Build draft object (fresh `draft_id` via UUID)
5. Persist to DB via `_save_draft` (single call)
6. Alert operator with draft for review

No retry loop, no regenerate branch, no existence pre-check, no
refresh-intent comments. Single-shot initial-save pipeline.
```If you want, I can now turn this into [docs/ON_CONFLICT_DIVERGENCE_DECISION_2026_05_04.md](/Users/dhuntermckenzie/Downloads/oyvoda/docs/ON_CONFLICT_DIVERGENCE_DECISION_2026_05_04.md) and commit it as its own scoped pass. Then we can decide whether to do the tracker update today or stop there.```</analysis to=functions.apply_patch code>
