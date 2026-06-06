# Exception Handling Audit — Legacy Operator Endpoints

Date: 2026-05-17
Trigger: Phase 4.3-E.1 uncovered three real bugs hidden behind a broad `try/except` in `/operator/operator/market-events`
Scope: `app/api/v1/endpoints/operator.py`

## Summary

The broad-exception pattern is real and concentrated in legacy `operator.py`.
Many operator-facing read endpoints catch `Exception` broadly and return
plausible empty or default payloads instead of surfacing failures. This keeps
the dashboard responsive, but it also masks real runtime bugs:

- broken imports
- missing columns
- wrong tenant/identity fields
- dead joins
- schema drift between ORM, migrations, and production

Phase 4.3-E.1 proved the risk was not theoretical: `/operator/operator/market-events`
was silently swallowing multiple bugs and falling back to `30a_fl`, making the
endpoint appear healthy while returning misleading data.

## Root Pattern

```python
result = {"field_1": default, "field_2": default, ...}
try:
    async with get_async_session() as db:
        # multiple queries, joins, computations
        ...
except Exception as e:
    logger.warning("query failed: %s", e)
return result
```

Two problems recur:

1. Partial-success masking
   One subquery succeeds and another fails; the endpoint returns a partially
   populated payload with no signal that anything broke.

2. Log-only failure attribution
   The only indicator is a warning log. In production, that is easy to miss,
   and clients receive a valid-looking success response.

## Findings By Risk

### High Risk

These endpoints combine tenant-scoped DB reads with broad exception handlers
that return success-shaped fallback data. If tenant scoping, joins, or schema
references break, operators see empty dashboards instead of explicit errors.

- `GET /operator/sessions/{token}/messages`
  File: [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:763)
  On failure returns `[]`.

- `GET /operator/knowledge-gaps`
  File: [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:813)
  On failure returns `[]`.

- `GET /operator/analytics/heatmap`
  File: [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1016)
  On failure returns an empty `cells` array.

- `GET /operator/analytics/properties`
  File: [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1117)
  On failure returns `[]`.

- `GET /operator/analytics/response-times`
  File: [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1216)
  On failure returns zero/empty distribution data.

- `GET /operator/analytics/revenue`
  File: [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1413)
  On failure returns zeroed revenue totals and empty breakdowns.

- `GET /operator/upsell-rates`
  File: [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1620)
  On failure returns platform defaults, which can mask missing operator config
  or broken identity lookups.

- `GET /operator/stats`
  File: [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1828)
  On failure returns zero counts.

### Medium Risk

These do not appear to create cross-tenant data exposure directly, but they can
still hide important feature breakage.

- `POST /operator/sessions`
  Narrow fallbacks exist around property-name lookup, operator branding,
  repeat-guest memory, and journey creation.
  File: [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:158)

- `POST /operator/sessions/{token}/feedback`
  Internal helper tolerates failures in tenant lookup, upsell pull, escalation
  pull, and guest-profile update, allowing feedback submission to succeed while
  downstream profile data may be lost.
  File: [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1486)

- `GET /operator/operator/market-events`
  File: [operator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator.py:1954)
  Phase 4.3-E.1 fixed the hardcoded operator default and multiple hidden bugs,
  but the outer broad `try/except` still means future schema drift could again
  collapse into a misleading fallback response.

### Low Risk

These newer operator-facing surfaces generally fail loudly with explicit
`HTTPException` responses rather than returning empty success payloads.

- `operator_dashboard_api.py`
  Example: [operator_dashboard_api.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator_dashboard_api.py:1500)

- `operator_app.py`
  Example: [operator_app.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator_app.py:2634)

One lower-risk exception remains:

- Admin summary path returns `{"error": ...}` with HTTP 200
  File: [operator_app.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/api/v1/endpoints/operator_app.py:2292)

## Production Verification Snapshot

While auditing the fallback risk, production `operator_policies` was inspected
to understand whether the revenue/upsell endpoints were merely risky or already
wrong.

Observed production facts:

- `operator_policies.operator_id` exists and is `character varying`
- `operator_policies.tenant_id` exists and is `uuid`
- `operator_policies.upsell_rates` exists
- `operator_policies.upsell_rates_configured` exists
- `operator_policies.market_id` does **not** exist in production
- production currently has **0 rows** in `operator_policies`

Implications:

1. The identity drift found in `get_upsell_rates` / `get_revenue_impact`
   remains structurally suspicious because those endpoints query
   `WHERE operator_id = :tenant`, passing a tenant UUID string into a legacy
   string identity column.

2. Because production currently has zero `operator_policies` rows, those
   endpoints are not hiding operator-specific upsell data today; they are
   falling back because no source rows exist.

3. The Phase 4.3-E.1 `market-events` fix now depends on a column
   (`operator_policies.market_id`) that is present in migration history but not
   in production schema, so the endpoint will continue to rely on its fallback
   path until that schema drift is reconciled.

## Recommended Follow-up

Do not do a sweeping rewrite immediately. The better path is targeted cleanup:

1. High-risk legacy `operator.py` hardening brief
   - convert the worst silent fallbacks into explicit 5xx or degraded
     responses with a `_warnings` block
   - prioritize:
     - `/operator/analytics/revenue`
     - `/operator/analytics/properties`
     - `/operator/upsell-rates`
     - `/operator/stats`

2. Identity/schema audit brief
   - reconcile `operator_policies` identity usage (`operator_id` vs `tenant_id`)
   - reconcile `market_id` schema drift between migration history and
     production

3. Phase 4.5 / 4.6 retrofit
   - when legacy concierge endpoints are retired or rewritten against Brain
     tables, tighten exception handling as part of that work rather than as a
     separate broad pass

## Out of Scope

- Internal service-layer broad `except` usage
- Rewriting analytics endpoints against canonical Brain tables
- Operator UI changes
- Multi-file sweep across all endpoint modules beyond the targeted sample above

## Bottom Line

The anti-pattern is real and proven harmful. The highest-value conclusion from
this audit is not “broad except exists”; it is:

> In legacy `operator.py`, broad `except` plus success-shaped fallback payloads
> can hide real production bugs for long periods.

This document should be used as a reference whenever touching surviving legacy
operator endpoints.

## Phase 4.3-M Follow-up

Phase 4.3-M added a new intent-classification escalation path in
[intent_classification_escalator.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/concierge/intent_classification_escalator.py).
That path intentionally does **not** follow the old success-shaped masking
pattern.

Implemented behavior:

- `operator_settings` threshold lookup catches `ProgrammingError` and
  `DBAPIError` explicitly, logs tenant/key context, and falls back to the
  default threshold
- provider request failures catch `httpx.TimeoutException` and
  `httpx.HTTPError`
- provider parse/coercion failures catch `JSONDecodeError`, `KeyError`, and
  `ValueError`
- all escalation failures fall back to the keyword result with explicit
  classifier metadata such as `llm_failed_keyword_default` rather than silently
  pretending the LLM path succeeded

This is the target pattern for future routing-layer exception handling:
preserve user-facing continuity when needed, but make the degraded path
observable in logs and persisted audit metadata.

## Phase 4.3-N Follow-up

Phase 4.3-N adds reservation-aware routing in
[reservation_aware_routing.py](/Users/dhuntermckenzie/Downloads/oyvoda/app/services/integrations/reservation_aware_routing.py).
That intake-time PMS lookup also follows the explicit degraded-path pattern
instead of broad exception masking.

Implemented behavior:

- feature-flag lookup failures log warning context and default to disabled for
  non-Beach-Habitats tenants
- `operator_settings` reads catch `ProgrammingError` and `DBAPIError`
  explicitly and fall back to default reservation windows
- local cached-booking reads catch `ProgrammingError` and `DBAPIError`
  explicitly and degrade to `None`
- live Escapia lookup catches `httpx.TimeoutException`,
  `httpx.HTTPError`, and credential/parse `ValueError`
- repeated failures are cached briefly so duplicate poll cycles do not hammer
  the PMS while it is degraded
- lookup failures fail open to the existing pre-booking route and append
  audit metadata such as `pms_lookup_failed` instead of silently pretending a
  reservation match happened

This is the target pattern for lifecycle-resolution seams: do not fail closed,
but do make every degraded path visible in logs and parser-note metadata.
## Phase 4.3-O Follow-up

- Extracted shared rollback helper to `app/db/session_safety.py`.
- Hardened fail-soft DB handlers so they clear aborted session state before returning defaults:
  - `email_dispatch`
  - `reservation_aware_routing`
  - `escalation_handoff_agent`
  - `pms_sync_agent`
  - `knowledge_curator_agent`
- This phase preserved fallback behavior while removing the swallow-without-rollback pattern from the touched production-error paths.
