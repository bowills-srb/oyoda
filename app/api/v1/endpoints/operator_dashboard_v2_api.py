from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.db.session import get_async_session
from app.services.feature_flags import (
    FeatureFlag,
    get_feature_flags,
    is_dashboard_v2_primary_enabled,
    is_ship_i_kb_retry_primary_enabled,
)
from app.services.operator.realtime_hub import get_operator_realtime_hub

from app.api.v1.endpoints.operator_dashboard_api import (
    _DEFAULT_SETTINGS,
    _merged_settings_payload,
    _require_context,
)
from app.api.v1.endpoints.operator_prebooking import list_inquiries


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/api/v2", tags=["Operator Dashboard V2"])


def _json_from_response(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    body = getattr(response, "body", b"{}")
    if isinstance(body, bytes):
        return json.loads(body.decode("utf-8") or "{}")
    if isinstance(body, str):
        return json.loads(body or "{}")
    return {}


def _is_uuid_like(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except Exception:
        return False


async def _load_operator_account(db: AsyncSession, tenant_id: str) -> dict[str, Any]:
    try:
        row = (
            await db.execute(
                text(
                    """
                    SELECT tenant_id, company_name, owner_name, email, messaging_email
                    FROM operator_accounts
                    WHERE tenant_id = CAST(:tid AS uuid)
                    LIMIT 1
                    """
                ),
                {"tid": tenant_id},
            )
        ).mappings().first()
        return dict(row) if row else {}
    except Exception:
        return {}


async def _load_autonomy_state(
    db: AsyncSession,
    *,
    tenant_id: str,
    operator_id: str,
) -> dict[str, Any]:
    row = None
    try:
        row = (
            await db.execute(
                text(
                    """
                    SELECT prebooking_autosend_threshold, ai_paused, ai_paused_at, updated_at
                    FROM operator_settings
                    WHERE tenant_id = CAST(:tid AS uuid)
                    LIMIT 1
                    """
                ),
                {"tid": tenant_id},
            )
        ).mappings().first()
    except Exception:
        row = None

    payload = _merged_settings_payload(dict(row) if row else None)
    threshold = float(payload.get("prebooking_autosend_threshold", _DEFAULT_SETTINGS["prebooking_autosend_threshold"])) / 100.0
    auto_enabled = not bool(payload.get("ai_paused", False))
    changed_at = payload.get("updated_at") or payload.get("ai_paused_at")

    return {
        "tenant": {
            "auto_enabled": auto_enabled,
            "confidence_threshold": round(threshold, 4),
            "last_changed_at": changed_at,
            "last_changed_by": operator_id,
        },
        "per_property": None,
        "lifecycle_overrides": None,
    }


async def _load_operator_account_scoped(tenant_id: str) -> dict[str, Any]:
    async with get_db_session() as db:
        return await _load_operator_account(db, tenant_id)


async def _load_prebooking_messages_scoped(request: Request, *, limit: int) -> dict[str, Any]:
    async with get_db_session() as db:
        return _json_from_response(
            await list_inquiries(
                request=request,
                status="all",
                limit=limit,
                db=db,
            )
        )


async def _load_autonomy_state_scoped(*, tenant_id: str, operator_id: str) -> dict[str, Any]:
    async with get_db_session() as db:
        return await _load_autonomy_state(
            db,
            tenant_id=tenant_id,
            operator_id=operator_id,
        )


async def _load_flag_state_scoped(tenant_id: str) -> dict[str, Any]:
    async with get_db_session() as db:
        flags = get_feature_flags(db)
        dashboard_v2_primary, ship_i_kb_retry_primary, lifecycle_primary = await asyncio.gather(
            is_dashboard_v2_primary_enabled(db=db, tenant_id=tenant_id),
            is_ship_i_kb_retry_primary_enabled(db=db, tenant_id=tenant_id),
            flags.is_enabled(
                FeatureFlag.BRAIN_PREBOOKING_LIFECYCLE_PRIMARY,
                company_id=tenant_id,
            ),
        )
        return {
            "dashboard_v2_primary": dashboard_v2_primary,
            "ship_i_kb_retry_primary": ship_i_kb_retry_primary,
            FeatureFlag.BRAIN_PREBOOKING_LIFECYCLE_PRIMARY: lifecycle_primary,
        }


@router.get("/prebooking/bootstrap")
async def prebooking_bootstrap(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    started = time.perf_counter()
    ctx = _require_context(request)
    _ = db  # request-scoped dependency retained for auth/session lifecycle
    account, messages, autonomy, flags = await asyncio.gather(
        _load_operator_account_scoped(ctx["tenant_id"]),
        _load_prebooking_messages_scoped(request, limit=25),
        _load_autonomy_state_scoped(
            tenant_id=ctx["tenant_id"],
            operator_id=ctx["operator_id"],
        ),
        _load_flag_state_scoped(ctx["tenant_id"]),
    )
    payload = {
        "operator": {
            "id": ctx["operator_id"],
            "name": account.get("owner_name") or account.get("company_name") or "Operator",
            "email": account.get("email") or account.get("messaging_email") or "",
        },
        "tenant": {
            "id": ctx["tenant_id"],
            "name": account.get("company_name") or "Oyvoda tenant",
        },
        "inquiries": messages.get("items", []),
        "autonomy": autonomy,
        "flags": flags,
    }
    logger.info(
        "[DashboardV2] prebooking bootstrap tenant=%s operator=%s inquiries=%s elapsed_ms=%.1f",
        ctx["tenant_id"],
        ctx["operator_id"],
        len(payload["inquiries"]),
        (time.perf_counter() - started) * 1000,
    )
    return payload


@router.get("/autonomy")
async def get_autonomy_state(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    return await _load_autonomy_state(
        db,
        tenant_id=ctx["tenant_id"],
        operator_id=ctx["operator_id"],
    )


@router.put("/autonomy")
async def update_autonomy_state(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    if not _is_uuid_like(ctx["tenant_id"]):
        raise HTTPException(
            409,
            "Autonomy settings require a tenant-backed operator account; demo fallback accounts are read-only.",
        )
    body = await request.json()
    tenant = body.get("tenant") if isinstance(body.get("tenant"), dict) else body

    auto_enabled = bool(tenant.get("auto_enabled", True))
    threshold = float(tenant.get("confidence_threshold", 0.95))
    threshold = max(0.0, min(1.0, threshold))

    settings_payload = {
        "ai_paused": not auto_enabled,
        "prebooking_autosend_threshold": round(threshold * 100),
    }
    from app.api.v1.endpoints.operator_dashboard_api import update_settings

    class _RequestProxy:
        def __init__(self, source: Request, payload: dict[str, Any]) -> None:
            self._source = source
            self._payload = payload
            self.cookies = source.cookies
            self.headers = source.headers
            self.method = source.method
            self.scope = source.scope

        async def json(self) -> dict[str, Any]:
            return self._payload

    await update_settings(_RequestProxy(request, settings_payload), db)
    payload = await _load_autonomy_state(
        db,
        tenant_id=ctx["tenant_id"],
        operator_id=ctx["operator_id"],
    )
    hub = get_operator_realtime_hub()
    await hub.publish(
        ctx["tenant_id"],
        "autonomy.changed",
        {
          "tenant_id": ctx["tenant_id"],
          "autonomy": payload,
        },
    )
    return payload


@router.get("/realtime")
async def realtime_stream(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    hub = get_operator_realtime_hub()
    last_event_id = request.headers.get("last-event-id")
    queue, missed = await hub.subscribe(ctx["tenant_id"], last_event_id=last_event_id)

    async def event_generator():
        try:
            yield _format_sse(
                event="summary.updated",
                event_id="0",
                data={
                    "tenant_id": ctx["tenant_id"],
                    "connected_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            for event in missed:
                yield _format_sse(event=event.event, event_id=event.id, data=event.data)
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield _format_sse(event=item.event, event_id=item.id, data=item.data)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            await hub.unsubscribe(ctx["tenant_id"], queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _format_sse(*, event: str, event_id: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, separators=(",", ":"), default=str)
    return f"id: {event_id}\nevent: {event}\ndata: {payload}\n\n"


@router.get("/portfolio-autonomy")
async def get_portfolio_autonomy(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Return the latest portfolio-level autonomy score and per-property rollup
    for the authenticated tenant.

    Reads from the most-recent stored snapshot (written nightly by the
    snapshot_autonomy_all_operators task). Falls back to a live compute if
    no snapshot exists yet — e.g. first day before the nightly run.

    Response shape:
        {
          "portfolio_score": 0.8063,
          "domain_bands": {
              "inquiry": {"score": 0.8355, "band": "Autonomous"},
              "guest_ops": "Developing",
              "maintenance": "Emerging",
              "turnover": "Emerging"
          },
          "rollup": {
              "included_properties": 32,
              "excluded_properties": 13,
              "total_managed": 45
          },
          "as_of": "2026-06-02",
          "source": "snapshot"  // or "live"
        }
    """
    ctx = _require_context(request)
    tid = ctx["tenant_id"]

    # -- Try reading from stored snapshot first -----------------------------------
    try:
        row = (await db.execute(
            text("""
                SELECT
                    portfolio_score,
                    domain_bands,
                    components,
                    snapshot_date
                FROM operator_autonomy_snapshots
                WHERE tenant_id = CAST(:tid AS uuid)
                ORDER BY snapshot_date DESC
                LIMIT 1
            """),
            {"tid": tid},
        )).mappings().first()
    except Exception:
        row = None

    if row:
        try:
            db_components = row["components"] or {}
            rollup_raw = db_components.get("per_property_rollup") or {}
            included = int(rollup_raw.get("included_properties", 0))
            excluded = int(rollup_raw.get("excluded_properties", 0))

            # Count total managed properties for context
            total_managed = (await db.scalar(
                text(
                    "SELECT COUNT(*) FROM properties "
                    "WHERE tenant_id = CAST(:tid AS uuid) "
                    "AND COALESCE(is_active, TRUE) = TRUE"
                ),
                {"tid": tid},
            )) or 0

            return {
                "portfolio_score": float(row["portfolio_score"]),
                "domain_bands": row["domain_bands"],
                "rollup": {
                    "included_properties": included,
                    "excluded_properties": excluded,
                    "total_managed": int(total_managed),
                },
                "as_of": row["snapshot_date"].isoformat() if row["snapshot_date"] else None,
                "source": "snapshot",
            }
        except Exception:
            pass  # fall through to live compute

    # -- Fallback: live compute (first day before nightly run) --------------------
    try:
        from app.services.operator.autonomy_score_service import compute_autonomy_snapshot_bundle
        bundle = await compute_autonomy_snapshot_bundle(db, tid)
        portfolio = bundle["portfolio"]
        rollup = bundle["rollup"]
        total_managed = (await db.scalar(
            text(
                "SELECT COUNT(*) FROM properties "
                "WHERE tenant_id = CAST(:tid AS uuid) "
                "AND COALESCE(is_active, TRUE) = TRUE"
            ),
            {"tid": tid},
        )) or 0
        return {
            "portfolio_score": float(portfolio["portfolio_score"]),
            "domain_bands": portfolio["domain_bands"],
            "rollup": {
                "included_properties": rollup["included_properties"],
                "excluded_properties": rollup["excluded_properties"],
                "total_managed": int(total_managed),
            },
            "as_of": None,
            "source": "live",
        }
    except Exception as exc:
        raise HTTPException(500, f"Portfolio autonomy compute failed: {exc}")
