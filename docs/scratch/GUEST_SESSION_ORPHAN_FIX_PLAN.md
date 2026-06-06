# Guest-Session Orphan Fix Plan

Date: 2026-05-27
Tenant under test: Beach Habitats (`e07980b2-a990-4b24-91d1-c8cb71ab70e1`)
Status: partially executed; targeted reroute fix shipped, broader contract tightening parked pending production observation
Anchor: [docs/scratch/GUEST_SESSION_ORPHAN_TRACE.md](GUEST_SESSION_ORPHAN_TRACE.md)
Discipline: [docs/architecture/MIGRATION_DISCIPLINE.md](../architecture/MIGRATION_DISCIPLINE.md) — Principles 1 (single canonical surface), 2 (tighten contracts, don't add bridges), and 4 (route outcomes must be queryable truth)

## Purpose

Close the contract gap between `dispatch_pre_booking` routing and
`concierge_guest_sessions` persistence, on the canonical brain-era surface,
without introducing a parallel pathway. The current symptom is a 78% orphan
rate: 7 of 9 `route_outcome = guest_session_routed` rows in the last 14
days have no discoverable matching `concierge_guest_sessions` row.

## Partial execution shipped on 2026-05-27

One targeted part of this plan has already landed:

- Commit `63e8040` (`routing: fix guest-session reroute fallback handling`)
  fixed the reroute exception path in
  [app/services/integrations/email_dispatch.py](../../app/services/integrations/email_dispatch.py)
  by correcting the `safe_rollback(...)` call in the guest-session reroute
  branch.
- The same commit updated
  [tests/unit/test_email_dispatch_prebooking_brain.py](../../tests/unit/test_email_dispatch_prebooking_brain.py)
  so the mocked `persist_inbound_from_inquiry(...)` returns the real
  route-result shape the production code depends on.

That means this workstream is no longer "plan only." The immediate error-path
bug is fixed. What remains open is whether the larger contract-tightening
change below is still necessary once production traffic has run through:

- the Beach Habitats pre-booking brain-primary cutover, and
- the reroute fallback fix above

The next decision is empirical:

- if the orphan rate for `guest_session_routed` drops to near zero on new
  traffic, the broader route-outcome expansion may be unnecessary
- if orphans persist, the broader contract-tightening change below becomes the
  next implementation step

Until that observation window completes, the plan below remains the bounded
next-step shape rather than committed code.

## Root cause — sharpened from the original trace

Codex's trace doc named three possible causes; reading the actual code
narrows it to one. The relevant call sites in
[app/services/integrations/email_dispatch.py](../../app/services/integrations/email_dispatch.py)
are at the two `guest_session_routed` emitters (one for `parsed_lifecycle_stage in {pre_arrival, in_stay, post_stay}`, one for `is_non_pre_booking_intent(inferred_intent)`).

Both look like this:

```python
if services.db:
    await persist_inbound_from_inquiry(
        services.db,
        tenant_id=services.company_id,
        property_code=parsed.property_code or "",
        # ... more kwargs ...
        source_label="email_dispatch_non_prebooking",
        reservation_id=getattr(parsed, "reservation_id", "") or "",
    )
    await services.db.commit()
await update_normalization_outcome(
    services.db,
    services.company_id,
    _normalization_source_channel(),
    _message_id(parsed),
    selected_property_code=parsed.property_code or "",
    selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
    route_outcome="guest_session_routed",
    draft_source="guest_session_router",
    fallback_reason=f"non_pre_booking_intent:{inferred_intent}:{inferred_confidence}",
    parser_notes_append=_reservation_routing_parser_notes(parsed),
)
return "guest_session_routed"
```

The bug is visible in three structural facts:

1. **The return value of `persist_inbound_from_inquiry` is discarded.**
   Look at [app/services/concierge/post_booking_routing.py:113](../../app/services/concierge/post_booking_routing.py)
   — the function returns `GuestSessionRouteResult(created, session_id,
   guest_thread_id, status)`. The dispatch never captures it.

2. **The outcome write happens unconditionally** after the persistence
   call, regardless of whether the persistence actually created a row,
   found an existing one (`status="already_exists"`), or raised silently.

3. **The orphan condition is therefore guaranteed** any time persistence
   returns `created=False` for a reason other than a true duplicate. The
   trace's tela case (`19e6a47a94f3b34a`, truncated guest turn) almost
   certainly hit one of these paths:
   - `inquiry_thread_id` divergence between this message and the original
     tela inbound — `_find_existing_session` keys on `migration_source.source_message_id`
     and `migration_source.draft_id`, not on RFC `Message-ID`
   - guest_thread_id resolution by `(tenant_id, property_code, guest_name_norm)`
     returning a different thread than expected
   - silent commit failure not re-raised

In all three cases, `persist_inbound_from_inquiry` returns without
creating a discoverable session row, and dispatch still writes
`guest_session_routed`. This is exactly the contract violation
Principle 4 names.

## Fix shape: contract-tightening on the single canonical path

Per Principle 2, the fix is to tighten the contract on the existing
canonical path, not to introduce a bridge or a parallel surface. The
shape is:

1. **Dispatch captures the persistence return value.**
2. **Dispatch writes the route outcome based on the return value:**
   - `created=True` → `route_outcome="guest_session_routed"` (the
     outcome name keeps its current meaning: a session row was created)
   - `status="already_exists"` → `route_outcome="guest_session_existing"`
     (new outcome — honestly says "this message was deduped against a
     prior session")
   - persistence raised → `route_outcome="guest_session_route_failed"`
     (new outcome — honestly says "we tried to route to a session and
     the persistence failed")
3. **A new outcome `pending_session_resolution` is introduced** for the
   case where dispatch routes away from pre-booking but cannot yet
   resolve a session at all (e.g. unbound property + no reservation
   match). This is the contract-completeness piece — it gives
   dispatch a way to honestly say "I made a routing decision but the
   downstream resolution is incomplete."

After the fix, the audit query from MIGRATION_DISCIPLINE.md Principle 4
should return zero orphans for `guest_session_routed`. The other new
outcomes are also queryable truth: each names what actually happened.

## What this fix is NOT

Explicitly **not** doing any of the following:

- **Not adding a bridge.** No "guest_session_router" layer between
  dispatch and `persist_inbound_from_inquiry`. The contract change is on
  the existing call site.
- **Not introducing a parallel surface.** `concierge_guest_sessions`
  remains the single canonical guest-session store. The new
  `route_outcome` values are written into the same
  `message_normalizations` table.
- **Not touching `persist_inbound_from_inquiry`'s internal logic
  unnecessarily.** The function already returns a useful result object;
  the fix is making dispatch respect it. If trace findings reveal a
  separate bug inside the function (e.g. `_find_existing_session` has
  the wrong lookup keys), that's a separate, additive fix.
- **Not papering over silent persistence failures.** If the function
  raises, dispatch will catch it and write `guest_session_route_failed`
  rather than swallowing it.

## Pre-fix verification: end-to-end trace of one orphan

Before any code change, codex traces one specific orphan end-to-end. This
is the Principle 3 audit step.

### Target orphan

The tela near-duplicate identified in the trace doc:

- `source_message_id = 19e6a47a94f3b34a`
- subject: `Inquiry from tela hurt: Aug 23 - Aug 28, 2026 - Vrbo #2435514`
- `route_outcome = guest_session_routed`
- `draft_source = guest_session_router`
- `fallback_reason = non_pre_booking_intent:general:0.55`
- No `concierge_guest_sessions` row found by:
  - `guest_name ILIKE '%tela%hurt%'`
  - `guest_thread_id` direct match
  - `property_context -> migration_source -> source_message_id = '19e6a47a94f3b34a'`

### What to capture

1. **The full `message_normalizations` row** for this `source_message_id`,
   including `parser_notes` and any embedded metadata.
2. **What `_find_existing_session` would have returned** when called with
   this message's `source_message_id` and the `draft_id` (which is empty
   for this dispatch path — `dispatch_pre_booking` doesn't pass one).
3. **What `guest_thread_id` would have been resolved** by
   `ensure_inquiry_thread` using
   `(tenant_id, property_code='', guest_name='tela hurt', inquiry_thread_id='')`.
   Empty `property_code` and empty `inquiry_thread_id` is the suspicious
   case — does `ensure_inquiry_thread` return a usable id or empty?
4. **Whether a real session row exists under a different lookup** —
   try `guest_thread_id` (if step 3 returns one), try property_code
   lookups, try `(tenant_id, guest_name, recent received_at window)`.
5. **The full transaction trace if reproducible** — does the
   `db.add(session)` actually persist, does `commit()` succeed, does
   the row appear in subsequent reads?

### Output

Codex appends a "Trace results" section to this doc with the above
findings populated for the tela case. Once that lands, the fix shape
above either holds as-is or gets one targeted adjustment for whatever
the trace reveals.

## Code change shape (after trace lands)

Below is the contract-tightening change. **Do not write this code until
the trace results are in.** This is the shape the fix is expected to
take, included here so the diff is bounded and reviewable.

### Change 1 — `app/services/integrations/email_dispatch.py`

Both `guest_session_routed` emitters become:

```python
if services.db:
    try:
        route_result = await persist_inbound_from_inquiry(
            services.db,
            tenant_id=services.company_id,
            # ... existing kwargs unchanged ...
            source_label="email_dispatch_non_prebooking",
            reservation_id=getattr(parsed, "reservation_id", "") or "",
        )
        await services.db.commit()
    except Exception as exc:
        await safe_rollback(services.db)
        logger.error(
            "[EmailDispatch] guest-session persistence failed tenant=%s source_message_id=%s exc=%s",
            services.company_id,
            _message_id(parsed),
            exc,
        )
        await update_normalization_outcome(
            services.db,
            services.company_id,
            _normalization_source_channel(),
            _message_id(parsed),
            selected_property_code=parsed.property_code or "",
            selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
            route_outcome="guest_session_route_failed",
            draft_source="guest_session_router",
            fallback_reason=f"persistence_failed:{type(exc).__name__}:{str(exc)[:200]}",
            parser_notes_append=_reservation_routing_parser_notes(parsed),
        )
        return "guest_session_route_failed"
else:
    route_result = None

# Decide outcome based on what persistence actually did.
if route_result is None:
    # No DB session — degenerate path, treat as routing intent only.
    outcome = "pending_session_resolution"
    fallback_detail = "no_db_session"
elif route_result.created:
    outcome = "guest_session_routed"
    fallback_detail = f"session_id={route_result.session_id}"
elif route_result.status == "already_exists":
    outcome = "guest_session_existing"
    fallback_detail = f"existing_session_id={route_result.session_id}"
else:
    outcome = "pending_session_resolution"
    fallback_detail = f"status={route_result.status}"

await update_normalization_outcome(
    services.db,
    services.company_id,
    _normalization_source_channel(),
    _message_id(parsed),
    selected_property_code=parsed.property_code or "",
    selected_property_match_type=services.infer_property_match_type(parsed, parsed.property_code or ""),
    route_outcome=outcome,
    draft_source="guest_session_router",
    fallback_reason=f"non_pre_booking_intent:{inferred_intent}:{inferred_confidence}|{fallback_detail}",
    parser_notes_append=_reservation_routing_parser_notes(parsed),
)
return outcome
```

The same shape applies to the `parsed_lifecycle_stage in {pre_arrival, in_stay, post_stay}` emitter, with its
own `fallback_reason` prefix (`lifecycle_stage:<value>` instead of
`non_pre_booking_intent:...`).

### Change 2 — `app/services/messaging/message_event_store.py` (only if needed)

If `update_normalization_outcome` validates `route_outcome` against an
enum or constants list, add the three new values:

- `guest_session_existing`
- `guest_session_route_failed`
- `pending_session_resolution`

If `route_outcome` is a free-text column (TEXT), no change needed; the
new values just appear in audit queries.

Codex checks this before writing code.

### Change 3 — UI awareness (Principle 6: hybrid states must be honest)

The v2 Pre-Booking surface and any operator-facing inbox view that filters
or counts route outcomes needs to know about the new values. Specifically:

- `guest_session_existing` should be counted as "routed and handled" —
  not as a separate operator action item, just a transparent dedup signal
- `guest_session_route_failed` should surface to operator review (it's a
  legitimate failure they may want to investigate)
- `pending_session_resolution` should surface to operator review with
  clearer copy than the current generic boilerplate

The frontend changes here are small — likely one or two lines in the
`getQueueBucket` and `wasHeldForReview` functions in
`app/static/dashboard-v2/src/routes/PreBooking/PreBookingRoute.tsx`.

Codex confirms scope before touching frontend; this might be deferred to
a follow-up if backend change is enough on its own.

## Verification criteria

After the fix lands, the following must all be true:

### Production data shape

1. The 14-day audit query for `route_outcome = guest_session_routed`
   shows zero orphans (every recorded `guest_session_routed` has a
   matching `concierge_guest_sessions` row found by either
   `migration_source.source_message_id` or `guest_thread_id`).
2. Some new rows appear under `guest_session_existing` (legitimate
   dedup cases) and/or `pending_session_resolution` (cases that
   previously orphaned).
3. `guest_session_route_failed` is rare (single digits per week)
   and each row has a meaningful `fallback_reason` for investigation.

### Replay verification (on the tela orphan)

4. Replaying the tela `19e6a47a94f3b34a` case through the new dispatch
   either produces a real session row (if the persistence logic itself
   works on this case) or honestly records
   `pending_session_resolution` / `guest_session_route_failed` with a
   diagnosable `fallback_reason`.
5. No silent orphan possible — every code path through dispatch
   produces a `route_outcome` that matches what actually happened.

### Regression on the working cases

6. The 2 matched `guest_session_routed` cases from the original trace
   still produce `guest_session_routed` after the fix (i.e. the fix
   doesn't accidentally demote real successes to
   `pending_session_resolution`).
7. No spike in error logs after the fix is deployed.
8. No unrelated route outcomes change rate (sanity check on dispatch
   regression).

### Discipline alignment

9. The change touches one canonical surface (`message_normalizations`)
   and one canonical service (`persist_inbound_from_inquiry`). No
   parallel pathway. (Principle 1)
10. The change tightens the existing contract — does not add a bridge.
    (Principle 2)
11. Every `route_outcome` after the fix is queryable truth. (Principle 4)

### Post-`63e8040` observation query

Before shipping the broader route-outcome expansion, re-run the orphan audit on
traffic created after the Beach Habitats cutover and reroute fix:

```sql
SELECT
    route_outcome,
    COUNT(*) AS routed,
    COUNT(*) FILTER (WHERE backing_row_exists) AS matched,
    COUNT(*) FILTER (WHERE NOT backing_row_exists) AS orphaned
FROM (
    /* join message_normalizations to concierge_guest_sessions using the
       MIGRATION_DISCIPLINE Principle 4 audit shape */
) AS audit
WHERE created_at > '2026-05-27 23:26:23+00'
GROUP BY route_outcome;
```

Decision rule:

- if `guest_session_routed` orphan count on new traffic is zero or near zero,
  keep the current narrower fix and close the broader expansion as unnecessary
- if `guest_session_routed` orphans persist at a meaningful rate, proceed with
  the broader contract-tightening change below

## Rollout sequence

Three sequential commits, each independently understandable:

### Commit 1 — trace results

Codex appends the tela orphan trace results to this doc. No code change.

### Commit 2 — backend contract fix

`app/services/integrations/email_dispatch.py` — both `guest_session_routed`
emitters capture the persistence return value and emit the appropriate
outcome. Verified by `python3 -m py_compile` plus a unit test if a
relevant test surface exists.

If `update_normalization_outcome` needs the enum/constants update,
that's the same commit.

### Commit 3 — frontend awareness (optional, deferred if backend is enough)

`app/static/dashboard-v2/src/routes/PreBooking/PreBookingRoute.tsx`
updated to handle the new outcomes correctly in queue bucketing and
"Next step" guidance. Verified by `npx tsc --noEmit`.

### Production verification window

After Commit 2 deploys:

- Watch `message_normalizations` for new rows for 24-48 hours
- Re-run the orphan audit query daily
- Confirm orphan count drops to zero on the new outcomes

If the orphan count is still nonzero after 48 hours, the fix is
incomplete and we trace the new orphans.

## Rollback procedure

If the fix produces any of:

- A spike in `guest_session_route_failed` (more than ~1% of pre-booking
  inbounds)
- New error logs in pre-booking dispatch
- Operator-visible regression in the v2 Pre-Booking surface

Rollback is a code revert of the affected commit(s), not a flag flip.
This is intentional: the contract tightening is a code-level fix, not
a runtime gate. If it breaks, we revert the code.

The revert procedure:

1. `git revert <commit-sha>` for Commit 2 (and Commit 3 if shipped).
2. Deploy.
3. Confirm `route_outcome = guest_session_routed` resumes (with the
   original orphan rate, which is the known-bad pre-fix state).
4. Trace whatever caused the failure and re-do Commit 2.

The revert restores the pre-fix orphan rate, which is bad but known.
It does not lose any data.

## Open questions for Hunter

1. **Does the optional frontend awareness change land in Commit 2 or
   Commit 3?** Backend correctness is the foundational fix; the frontend
   update is the Principle 6 honesty piece. They can ship together or
   separately. I'd lean separately for cleaner diff isolation.
2. **What's the threshold for `guest_session_route_failed` rate that
   triggers investigation?** The plan suggests "more than ~1% of
   pre-booking inbounds." Confirm or adjust.
3. **Trace first or fix first?** The current ordering assumes we trace
   tela's orphan before writing the fix. An alternative is "write the
   fix shape, capture-rate-check, then trace if needed." I'd recommend
   trace-first per Principle 3, but it's your call.

## Status

This doc is **partially executed and now effectively closed**.

Shipped:

- Commit `63e8040` fixed the guest-session reroute exception-path bug and made
  the reroute tests honest about the current persistence contract.
- Post-cutover production verification on `2026-05-28` showed no new
  `guest_session_routed` orphan class on fresh traffic. The only observed
  post-cutover row was `route_outcome = guest_session_existing`, and direct
  tracing confirmed it corresponded to real existing guest-session records;
  the earlier audit query had simply been too narrow in how it looked for
  the backing session.

Not needed after verification:

- the broader route-outcome expansion (`guest_session_existing`,
  `guest_session_route_failed`, `pending_session_resolution`)
- the corresponding dispatch branching on the full
  `persist_inbound_from_inquiry(...)` return value
- any optional frontend awareness for those new outcomes

The next concrete step is not another code change on this seam. Keep the
Principle 4 audit query as a periodic regression check. If a new orphan class
appears later, resume from the contract-tightening section above with a fresh
trace.

The audit query from MIGRATION_DISCIPLINE.md Principle 4 should become a
weekly check after this lands — early detection of new contract gaps is
cheaper than tracing individual orphan cases later.
