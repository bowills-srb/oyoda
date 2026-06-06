# Migration Discipline

## Why this doc exists

We have lived through two distinct shapes of integration failure on Oyvoda's
canonical surfaces, and they each cost real operator-visible quality:

1. **KB schema drift.** Two parallel knowledge-storage paths (the retired
   `concierge_knowledge` JSONB model and the live `concierge_scoped_knowledge`
   model) silently diverged. Code paths kept reading both. Operator-edited
   knowledge ended up on the wrong side of the drift and operator answers
   degraded. The fix was a single canonical surface enforced by a single
   service (`DashboardKnowledgeService`).
2. **Brain pre-booking + guest-session migration seams.** A partial cutover
   left the intake half of the new pathway enabled
   (`messaging_brain_llm_intake = true`) but the lifecycle half disabled
   (`brain_prebooking_lifecycle_primary = false`). Every Beach Habitats
   inbound got the boilerplate fallback draft. Separately, the
   `guest_session_routed` route outcome was recorded by one path without a
   tight contract that the receiving canonical surface
   (`concierge_guest_sessions`) actually had the matching row. 78% of routed
   outcomes had no backing session.

These two are different shapes of the same family of risk. The first is
**parallel-schema drift**. The second is **incomplete-cutover seam**. Both
produce systems that are technically working as written and operationally
confusing.

This document records the disciplines we use to prevent both. The point isn't
that we have to follow rules; the point is that without these rules, work
done at one seam leaks correctness debt across the whole canonical pathway.

## Principle 1 — Single canonical surface

For every concept the system models (knowledge, properties, guest sessions,
pre-booking inquiries, normalizations, message events), there is exactly one
canonical storage surface and exactly one service that writes it.

- Do not introduce a parallel table to "experiment with" a new pathway. If
  the new pathway needs a different shape, change the canonical surface, not
  add a new one alongside it.
- Do not introduce a second write path because the existing service is
  inconvenient. The inconvenience is a design signal, not a permission slip.
- Read paths can be wrapped, decorated, or specialized. Write paths must
  funnel through the canonical service.

Examples in current code that honor this:

- `concierge_scoped_knowledge` writes go through
  `app/services/messaging_brain/knowledge/dashboard_kb_service.py`
- `pre_booking_inquiries` writes go through
  `app/services/messaging_brain/persistence/prebooking_inquiry_store.py`
- `concierge_guest_sessions` writes go through the brain-era session
  adapters (see `app/services/messaging_brain/session_channel_adapter.py`
  and `app/services/concierge/post_booking_routing.py`)

When you find yourself reaching for a second writer, stop. Tighten the
existing one instead.

## Principle 2 — Tighten contracts, do not add bridges

When two code paths disagree about what an outcome means or when persistence
should happen, the fix is to fix the disagreement on the canonical surface,
not to add a third layer that papers over both.

The pattern we're avoiding:

```
old_path  → outcome_x  ↘
                          → bridge_layer → canonical_surface
new_path  → outcome_y  ↗
```

Every bridge layer is a future seam. The bridge inherits both upstream sets
of assumptions, then code reading downstream of the bridge inherits whatever
the bridge decided. Over time the bridge becomes the de facto contract and
the original surfaces drift further apart.

Instead:

```
old_path  ↘
            → canonical_surface (with one enforced contract)
new_path  ↗
```

If the contract is too loose to support both paths, tighten the contract.
That may mean introducing a new explicit outcome state
(e.g. `pending_session_resolution` distinct from `guest_session_routed`) so
that both paths can describe what they actually did honestly. That is a
contract change, not a bridge.

Once the contract is tightened and the older seam is no longer needed,
retire the leftover path. Leaving it in place indefinitely creates the same
kind of future drift pressure as a bridge.

## Principle 3 — Audit before fix on any canonical surface

We have proven this discipline twice this quarter (Properties v0 contract
audit, Spooky Lane gate-block audit). Never write code that touches schema,
routing, or canonical-surface contracts without first writing the audit
that confirms which layer is failing.

The audit is the document, not the SQL. The deliverable is a `docs/scratch/`
markdown file that:

- Names the symptom in plain language
- Lists the layers data flows through
- Provides production-safe queries for each layer
- Defines an interpretation rubric (which result means which root cause)
- Concludes with what specifically would need to change

Once the audit lands, the fix is small, scoped, and the rollback story is
obvious. Without the audit, the fix is a guess.

## Principle 4 — Route outcomes must be queryable truth

If a routing layer records `outcome = X`, a query against the canonical
surface must be able to find the artifact that justifies `X`. If it can't,
either the route is lying or the persistence didn't durably happen.

Concrete rule for pre-booking + guest-session routing:

- `route_outcome = guest_session_routed` means a row exists in
  `concierge_guest_sessions` keyed to the same message
- `route_outcome = pre_booking_new` means a row exists in
  `pre_booking_inquiries` keyed to the same draft
- `route_outcome = confirmed_guest_email_received` means a confirmed-guest
  reservation match was found and persisted
- `route_outcome = pending_session_resolution` is the explicit honest
  outcome when we have routed away from pre-booking but cannot yet confirm
  a session exists

This is enforced by code: the route outcome write should happen *after* the
canonical surface write, not before, and should be wrapped in a check that
the surface write actually committed.

Audit (running this regularly catches drift early):

```sql
-- For any route outcome that claims a canonical artifact, the artifact
-- should be queryable. The mismatch rate is the canonical-contract debt.
SELECT
    route_outcome,
    COUNT(*) AS routed,
    COUNT(*) FILTER (WHERE backing_row_exists) AS matched,
    COUNT(*) FILTER (WHERE NOT backing_row_exists) AS orphaned
FROM (
    /* join message_normalizations to the claimed canonical surface */
) AS audit
GROUP BY route_outcome;
```

A non-zero orphan count on a "the artifact exists" outcome is a contract
violation, not noise.

## Principle 5 — Cutover completeness is documented per tenant

A "cutover" that's enabled for one tenant and disabled for another is a
known hybrid state, not an accident. But it has to be explicitly documented
or it becomes ambient confusion.

Every runtime gate that can be partially flipped (per-tenant, per-property,
per-environment) has:

- A rollout doc that names the gate, the tenants, the verification artifact
  that gated each flip, and the rollback procedure
- A canonical place to read current state (the `operator_feature_flags`
  table or equivalent), not just "what someone remembers setting"
- A defined "fully cut over" target state so we know when the cutover is
  done

Examples in current code:

- `messaging_brain_runtime` — runtime enable for the brain
- `messaging_brain_llm_intake` — Groq/Anthropic-first intake classifier
- `brain_intake_primary` — brain owns the intake decision
- `brain_prebooking_lifecycle_primary` — brain owns the pre-booking lifecycle
- `post_booking_ai` — guest-session auto-send (defaults off, operator-flipped)

Each of these can be true or false independently per tenant. The system
will behave correctly under any combination, but operator experience will
differ depending on which combination is live. The rollout doc per tenant
is how we keep that legible.

Cutover completeness also includes retirement:

- when a tenant or pathway is fully cut over, name which prior seam is now
  dead
- remove the dead seam in the same workstream when safe
- otherwise log it explicitly as retirement debt with a named module/path
  and owner

## Principle 6 — Hybrid states need explicit user-facing language

When a tenant is in a hybrid state (e.g. LLM-first intake on but brain
lifecycle off, so every inbound gets a fallback boilerplate draft), the
UI should not pretend everything is fine. The operator should be able to
tell from the surface what state they're in.

This is operator-experience-first design applied to migration seams. The
stale-bootstrap fix to the v2 pre-booking page is an example of this: when
the page is showing cached data while live refresh is in flight, the badge
says so; when the live refresh has failed, the badge says so.

The same principle applies to draft sources. A draft from
`gmail_fallback_saved` is not the same artifact as a draft from
`messaging_brain`, and the v2 UI surfaces that distinction explicitly via
the held queue, the "Next step" guidance copy, and the row state language.

## How this connects to the work in flight

The two open workstreams that came out of the 2026-05-27 audit pass are
direct applications of these principles:

- **Brain pre-booking lifecycle cutover (Principle 5).** The flag exists,
  the code path is implemented, and the current Beach Habitats state is a
  documented partial cutover. The next step is a targeted replay/regression
  pass before flipping `brain_prebooking_lifecycle_primary = true`, per
  the safety doc at
  [docs/scratch/BRAIN_PREBOOKING_PRIMARY_SAFETY.md](../scratch/BRAIN_PREBOOKING_PRIMARY_SAFETY.md).
- **Guest-session routing contract gap (Principles 2 and 4).** Routing
  records `guest_session_routed` without a tight contract that
  `concierge_guest_sessions` has the matching row. 7 of 9 outcomes in the
  last 14 days are orphans. The fix is to tighten the contract on the
  single canonical surface, not to add a bridge. The trace at
  [docs/scratch/GUEST_SESSION_ORPHAN_TRACE.md](../scratch/GUEST_SESSION_ORPHAN_TRACE.md)
  is the audit; the fix follows after one orphan is traced end-to-end
  through `persist_inbound_from_inquiry`.

Each of these is a separate fix with a separate verification path and a
separate rollback story. They share a discipline, not an implementation.

## Reviewing changes against this doc

When reviewing any change that touches a canonical surface, routing
outcome, or feature-flag gate, the reviewer asks:

1. Does this introduce a second writer for an existing canonical surface?
   (Principle 1)
2. Does this paper over a contract disagreement with a bridge?
   (Principle 2)
3. Was there an audit doc before the code change? (Principle 3)
4. After this change, does every route outcome remain queryable truth?
   (Principle 4)
5. If this is a gate flip, is the rollout doc updated and is the
   verification artifact attached? (Principle 5)
6. If this introduces a new hybrid state, is the user-facing surface
   honest about it? (Principle 6)
7. If this change makes an older path unnecessary, is that path retired
   now or explicitly logged as retirement debt? (Principles 2 and 5)

If any answer is no, the change isn't ready yet.

## Related documents

- [docs/architecture/LEGACY_RETIREMENT_PLAN.md](LEGACY_RETIREMENT_PLAN.md) — the canonical statement that the brain is the only runtime pipeline; this doc is the discipline that prevents new seams from forming during that retirement
- [docs/architecture/SCHEMA_DRIFT_AUDIT.md](SCHEMA_DRIFT_AUDIT.md) — the concrete production audit that motivated Principle 1
- [docs/architecture/CANONICAL_OPERATOR_KNOWLEDGE_MODEL.md](CANONICAL_OPERATOR_KNOWLEDGE_MODEL.md) — the canonical-surface model for operator knowledge
- [docs/architecture/RESERVATION_AWARE_ROUTING.md](RESERVATION_AWARE_ROUTING.md) — how booked-guest routing is supposed to work; relevant to Principle 4
