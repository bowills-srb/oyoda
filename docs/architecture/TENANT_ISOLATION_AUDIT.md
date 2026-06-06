# Tenant Isolation Audit — Phase 4.3 Companion

Date: 2026-05-16
Status: Audit findings + Phase 4.3-D scope definition
Scope: API endpoints accessing tenant-scoped data

## Summary

Most operator-facing endpoints in the system resolve `tenant_id` from authenticated JWT/cookie context correctly. A specific cluster of legacy endpoints in `app/api/v1/endpoints/operator.py` accept `operator_id` as a query parameter and fall back to `DEFAULT_TENANT_ID` (a sentinel UUID `00000000-0000-0000-0000-000000000001`, distinct from any real tenant) when no parameter is provided. These endpoints do not cross-check the auth context against the requested `operator_id`, creating a path-level authorization gap that will become exploitable the moment a second operator onboards.

The router does require authentication (`Depends(require_ops_access)`), so only ops users hit these endpoints. The gap is: authenticated user from operator A can pass `?operator_id=<operator_B_tenant_uuid>` and read operator B's data.

Today, operator B does not exist; cross-tenant queries return empty results. The risk materializes with operator #2 onboarding.

## Surfaces verified safe (tenant from JWT, no fallback)

These resolve tenant from authenticated context. Cannot be coerced via query parameter:

- `/api/v1/operator-policies` GET, PATCH — uses `resolve_request_tenant_id` from `app/api/dependencies/request_tenant.py`
- `/api/v1/operator/properties/reconcile` — uses `_require_tenant` wrapping the same helper
- `/app/api/*` operator dashboard API (`app/api/v1/endpoints/operator_dashboard_api.py`) — uses `_require_context`, docstring asserts "Never trust a tenant_id from the request body"
- All Brain read paths (`CanonicalPropertyService`, `ScopedKnowledgeService`, `ContextBuilderAgent`) — tenant_id is a required UUID parameter from `InboundGuestMessage`; no defaults, no fallbacks
- All Phase 4.0/4.1/4.2/4.3-A/4.3-A.1/4.3-A.2 surfaces — tenant_id resolved from authenticated context or passed as required UUID

## Affected endpoints (operator.py)

All under prefix `/operator`. Router has `dependencies=[Depends(require_ops_access)]` but no tenant-scoping decorator.

### Read endpoints — fall back to sentinel when `operator_id` query param absent

| Endpoint | Tables read | Retirement status |
|---|---|---|
| `GET /operator/knowledge-gaps` | `concierge_knowledge_gaps` | **Retire in 4.6** (legacy concierge) |
| `POST /operator/knowledge-gaps/{gap_id}/resolve` | `concierge_knowledge_gaps` | **Retire in 4.6** |
| `GET /operator/sessions` | `concierge_guest_sessions` | **Retire in 4.6** |
| `GET /operator/analytics` | `concierge_messages`, `concierge_guest_sessions`, `concierge_knowledge_gaps` | **Harden** — analytics is needed post-retirement, refactor against Brain tables |
| `GET /operator/analytics/heatmap` | `concierge_messages` | **Harden** — refactor to read from `message_normalizations` |
| `GET /operator/analytics/properties` | `concierge_guest_sessions`, `concierge_messages`, `concierge_escalations`, `concierge_knowledge_gaps` | **Harden** — refactor to read from canonical Brain tables |
| `GET /operator/analytics/response-times` | `concierge_messages` | **Harden** — refactor to read from `message_normalizations` |
| `GET /operator/analytics/revenue` | `concierge_messages`, `concierge_journey_activities`, `operator_policies` | **Harden** — revenue analytics is a product feature, refactor against Brain tables |
| `GET /operator/guests` | `guest_profiles` | **Harden** — guest profiles is a product feature, not legacy concierge |
| `GET /operator/guests/{profile_id}` | `guest_profiles` | **Harden** |
| `PATCH /operator/guests/{profile_id}/preferences` | `guest_profiles` | **Harden** |
| `GET /operator/stats` | `concierge_guest_sessions`, `concierge_escalations` | **Harden** — stats is a product feature, refactor |
| `GET /operator/upsell-rates` | `operator_policies` | **Harden** — `operator_policies` is canonical Brain data going forward |

### Write endpoints — accept `operator_id` query param without auth-context cross-check

| Endpoint | Tables written | Retirement status |
|---|---|---|
| `POST /operator/upsell-rates` | `operator_policies` | **Harden** — writes to canonical Brain data; must use auth-context tenant |
| `POST /operator/sessions` (`create_session`) | `concierge_guest_sessions`, `concierge_guest_journeys`, etc. | **Retire in 4.6** (legacy guest session creation) |

### Other endpoints in `operator.py` — already auth-context-correct

| Endpoint | Notes |
|---|---|
| `POST /operator/sessions/{token}/send-link` | Token-bound, not tenant-coerced |
| `GET /operator/sessions/{token}` | Token-bound |
| `GET /operator/sessions/{token}/messages` | Token-bound |
| `POST /operator/sessions/{token}/sync-pms` | Token-bound |
| `GET /operator/escalations` | Reads from in-memory `EscalationService`, no SQL tenant param |
| `POST /operator/escalations/{ticket_id}/{acknowledge,resolve}` | Ticket-bound |
| `GET /operator/escalations/sla-stats` | Cross-tenant by design (admin dashboard stat) |
| `GET /operator/sessions/{token}/journey/*` | Token-bound |
| `POST /operator/sessions/{token}/feedback` | Token-bound + tenant resolution from token |
| `POST /operator/knowledge-gap-drafts/*` | Token-bound + service-internal tenant resolution |
| `GET /operator/operator/market-events` | ~~Has a different issue: hardcoded `operator_id=op_beach_habitats` default~~ — **Resolved Phase 4.3-E.1 commit `a02031d`**: endpoint now uses `_require_tenant(request)` from JWT/cookie, hardcoded default removed. |

## Phase 4.3-D scope (proposed)

**Goal**: Eliminate the `operator_id` query parameter + `DEFAULT_TENANT_ID` fallback pattern from every endpoint in `operator.py` slated for hardening. Retire the rest as part of Phase 4.5/4.6 legacy concierge teardown.

### Hardening pattern

Every endpoint in the "Harden" list above adopts the same pattern:

```python
from app.api.dependencies.request_tenant import resolve_request_tenant_id
from app.api.dependencies.ops_auth import require_ops_access
from fastapi import HTTPException, Request, status

def _require_tenant(request: Request) -> UUID:
    tenant_id = resolve_request_tenant_id(request)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: no tenant in token or cookie.",
        )
    return tenant_id

@router.get("/analytics")
async def get_analytics(days: int = 30, request: Request = ...):
    tenant_id = _require_tenant(request)
    # ... all queries use tenant_id instead of DEFAULT_TENANT_ID or operator_id query param
```

The `operator_id` query parameter is removed entirely from the signature. Tenant comes from JWT only. No fallback to sentinel. No client-side override.

### Retirement pattern (Phase 4.5/4.6)

Endpoints marked "Retire in 4.6" are deleted entirely when the legacy concierge tables drop. Their data sources (`concierge_knowledge_gaps`, `concierge_guest_sessions`, etc.) are part of the Phase 4.6 deprecation set.

### Super admin scope-switching

The `_require_context` pattern in `operator_dashboard_api.py` supports super-admin scope-switching via `oyvoda_scoped_op` / `oyvoda_scoped_tid` cookies. Hardening should adopt that pattern: super admins can scope into any tenant via cookie-set, regular ops users see only their own tenant. **This preserves admin workflow without leaving the `operator_id` query parameter as a back door.**

### Out of scope of Phase 4.3-D

- Refactoring the actual analytics queries to read from canonical Brain tables (`message_normalizations` etc.) instead of legacy `concierge_messages` — that's Phase 4.5 work (audit legacy KS callers) and Phase 4.6 (drop tables). 4.3-D only hardens tenant resolution; it does not migrate the underlying queries.
- ~~Hardcoded `operator_id=op_beach_habitats` default on `/operator/operator/market-events`~~ — **Resolved Phase 4.3-E.1 commit `a02031d`**: endpoint now resolves tenant from authenticated context and no longer accepts an `operator_id` override.
- Endpoints that already auth-context-resolve correctly
- UI work in any operator dashboard

## Sequencing recommendation

Phase 4.3-D should ship **before operator #2 onboarding**. The cross-tenant read gap is benign today (operator #2 doesn't exist) but exploitable the moment it does. Three viable orderings:

**Option A: Now, parallel to 4.3-A.2.** Different files (`operator.py` vs `scoped_knowledge_service.py`), no merge conflict. Codex can run both briefs in parallel if you have capacity.

**Option B: Immediately after 4.3-A.2 ships and verifies.** Sequential. Reduces parallel-PR coordination overhead.

**Option C: Defer until before operator #2 onboarding ramp.** Acceptable since the gap is dormant today. Risk is forgetting and onboarding operator #2 before hardening lands.

**Recommendation: B.** Ship 4.3-A.2 first (it's already committed), then immediately ship 4.3-D before any UI work (4.3-B, 4.3-C). The UI work *uses* these endpoints; better the endpoints be hardened before UI code is written against them.

## Acknowledgment for memory

This audit was done specifically to answer the question: "is everything we're doing scoped to each new tenant — can one tenant's data cross to another?"

**Answer: not today, but the architectural gap exists in `operator.py` and will become exploitable with operator #2.** Phase 4.3-D closes it. Documented here so the gap is not rediscovered or forgotten across future sessions.
