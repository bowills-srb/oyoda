"""
operator_dashboard_api.py — Unified API for the operator dashboard sections
that don't have a dedicated endpoint file.

All routes under /app/api/*. Auth: httpOnly JWT cookie (same pattern as
operator_prebooking.py to avoid circular imports with operator_app.py).

Sections covered here:
  • Knowledge Base          GET/POST/PATCH/DELETE /app/api/kb
  • Knowledge Gaps          GET/POST /app/api/kb-gaps
  • Guest Sessions          GET /app/api/sessions, GET /app/api/sessions/{id}
  • Booking Context         GET /app/api/booking-context
  • Escalations             GET/POST /app/api/escalations
  • Vendors                 GET/POST/PATCH/DELETE /app/api/vendors
  • Vendor Categories       GET/POST /app/api/vendor-categories
  • Operator Settings       GET/PATCH /app/api/settings
  • Notifications           GET/POST /app/api/notifications
  • Dashboard Summary       GET /app/api/dashboard-summary  (consolidated counters)

Tenant scoping: every query filters by the JWT-derived `tenant_id`. Never
trust a tenant_id from the request body.
"""

from __future__ import annotations

import base64
import json
import logging
import socket
import time
import uuid
from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.services.feature_flags import FeatureFlag, get_feature_flags
from app.services.messaging_brain.knowledge.dashboard_kb_service import (
    get_dashboard_kb_service,
)
from app.services.operator.dashboard_summary_service import (
    default_dashboard_summary,
    get_dashboard_summary_service,
)
from app.services.operator.escalation_action_agent import get_escalation_action_agent
from app.services.operator.escalation_workflow_service import get_escalation_workflow_service
from app.services.operator.handoff_service import get_operator_handoff_service
from app.services.operator.property_asset_service import get_operator_property_asset_service
from app.services.operator.safety_protocol_service import get_safety_protocol_service
from app.services.operator.scope_service import get_operator_scope_service
from app.services.operator.work_order_service import get_operator_work_order_service
from app.services.operator.stay_action_agent import get_stay_action_agent
from app.services.operator.stay_event_service import get_stay_event_service
from app.services.operator.stay_pms_feed_service import get_stay_pms_feed_service
from app.services.operator.stay_workflow_service import get_stay_workflow_service
from app.services.operator.vendor_intelligence_service import get_vendor_intelligence_service
from app.services.operator.realtime_hub import get_operator_realtime_hub
from app.services.operator.message_retention_service import (
    DEFAULT_RETENTION_POLICY,
    merge_retention_policy,
)
from app.services.messaging.operator_alerts import (
    AlertType,
    ESCALATION_TIMEOUTS,
    get_alert_router,
)
from app.services.messaging.booking_context_adapters import (
    BookingContextBuildError,
    BookingContextAdapterConfig,
    BookingContextLookup,
    build_booking_context_adapter,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/api", tags=["Operator Dashboard"])
scope_service = get_operator_scope_service()
escalation_workflow_service = get_escalation_workflow_service()
escalation_action_agent = get_escalation_action_agent()
handoff_service = get_operator_handoff_service()
work_order_service = get_operator_work_order_service()
property_asset_service = get_operator_property_asset_service()
stay_workflow_service = get_stay_workflow_service()
stay_action_agent = get_stay_action_agent()
stay_event_service = get_stay_event_service()
stay_pms_feed_service = get_stay_pms_feed_service()
vendor_intelligence_service = get_vendor_intelligence_service()
safety_protocol_service = get_safety_protocol_service()


# ─────────────────────────────────────────────────────────────────────────────
# Auth (mirrors operator_prebooking.py to avoid circular import)
# ─────────────────────────────────────────────────────────────────────────────

def _decode_jwt_payload(token: str) -> Optional[dict]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def _get_user(request: Request) -> Optional[dict]:
    token = request.cookies.get("oyvoda_access")
    if not token:
        return None
    payload = _decode_jwt_payload(token)
    if not payload:
        return None
    if payload.get("role") == "super_admin":
        scoped_op = request.cookies.get("oyvoda_scoped_op")
        scoped_tid = request.cookies.get("oyvoda_scoped_tid")
        if scoped_op:
            payload["scoped_op"] = scoped_op
        if scoped_tid:
            payload["tid"] = scoped_tid
            payload["tenant_id"] = scoped_tid
    return payload


def _require_context(request: Request) -> dict:
    """Return {operator_id, tenant_id, role, email} or raise 401/403."""
    user = _get_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    role = user.get("role", "owner")
    if role == "super_admin" and not user.get("scoped_op"):
        raise HTTPException(
            403,
            "Super admin must scope into an operator first (use /app/api/admin/scope)",
        )
    operator_id = user.get("scoped_op") or user.get("sub", "")
    tenant_id = user.get("tid") or operator_id
    if not tenant_id:
        raise HTTPException(403, "No tenant context")
    return {
        "operator_id": operator_id,
        "tenant_id": tenant_id,
        "role": role,
        "email": user.get("email", ""),
    }


def _serialize(row_mapping: dict) -> dict:
    """Convert UUID/datetime/date values in a row to JSON-safe primitives."""
    out = {}
    for k, v in row_mapping.items():
        if isinstance(v, uuid.UUID):
            out[k] = str(v)
        elif isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


async def _table_columns(db: AsyncSession, table_name: str) -> set[str]:
    rows = (await db.execute(
        text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = :table
        """),
        {"table": table_name},
    )).fetchall()
    return {str(r[0]) for r in rows}


async def _rollback_quietly(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except Exception:
        pass


def _existing_column(columns: set[str], *candidates: str) -> Optional[str]:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


async def _module_enabled(
    db: AsyncSession,
    tenant_id: str,
    flag_name: str,
) -> bool:
    return await get_feature_flags(db).is_enabled(flag_name, company_id=tenant_id)


async def _ensure_module_enabled(
    db: AsyncSession,
    tenant_id: str,
    flag_name: str,
) -> None:
    if not await _module_enabled(db, tenant_id, flag_name):
        raise HTTPException(404, "Module not enabled")


def _classify_db_exception(exc: Exception) -> Optional[HTTPException]:
    message = str(exc)
    if isinstance(exc, socket.gaierror) or "nodename nor servname provided" in message:
        return HTTPException(503, "Database host could not be resolved")
    if "InvalidPasswordError" in type(exc).__name__ or "password authentication failed" in message:
        return HTTPException(503, "Database authentication failed")
    if "Connect call failed" in message or "connection refused" in message.lower():
        return HTTPException(503, "Database connection failed")
    return None


async def _property_query_meta(db: AsyncSession, alias: str = "") -> Optional[dict]:
    columns = await _table_columns(db, "properties")
    if not columns:
        return None

    prefix = f"{alias}." if alias else ""
    id_col = _existing_column(columns, "property_id", "id")
    tenant_col = _existing_column(columns, "tenant_id", "company_id")
    name_candidates = [
        col
        for col in ("property_name", "name", "address_street", "address_line1", "property_code", "external_id")
        if col in columns
    ]
    code_candidates = [
        col
        for col in ("property_code", "property_external_id", "external_id", "code", "name", "property_name", "address_street", "address_line1")
        if col in columns
    ]

    predicates = []
    if tenant_col:
        predicates.append(f"{prefix}{tenant_col} = CAST(:tid AS uuid)")
    if "deleted_at" in columns:
        predicates.append(f"{prefix}deleted_at IS NULL")
    if "is_deleted" in columns:
        predicates.append(f"COALESCE({prefix}is_deleted, FALSE) = FALSE")
    if "is_active" in columns:
        predicates.append(f"COALESCE({prefix}is_active, TRUE) = TRUE")

    name_expr = "COALESCE(" + ", ".join(f"{prefix}{col}" for col in name_candidates) + ", 'Property')" if name_candidates else "'Property'"
    code_expr = "COALESCE(" + ", ".join(f"{prefix}{col}" for col in code_candidates) + ", 'Property')" if code_candidates else "'Property'"

    return {
        "columns": columns,
        "id_expr": f"{prefix}{id_col}" if id_col else "NULL::uuid",
        "name_expr": name_expr,
        "code_expr": code_expr,
        "where_sql": " AND ".join(predicates) if predicates else "TRUE",
    }


async def _scope_profile(request: Request, db: AsyncSession, ctx: Optional[dict] = None) -> dict:
    ctx = ctx or _require_context(request)
    user = _get_user(request) or {}
    return await scope_service.get_scope_profile(
        db,
        ctx["tenant_id"],
        user.get("sub", ""),
        ctx.get("role", "owner"),
    )


async def _portfolio_property_codes(
    db: AsyncSession,
    tenant_id: str,
    portfolio_key: str,
) -> list[str]:
    if not portfolio_key:
        return []
    if not await scope_service._table_exists(db, "operator_portfolios") or not await scope_service._table_exists(db, "operator_portfolio_properties"):
        return []
    rows = (
        await db.execute(
            text(
                """
                SELECT pp.property_external_id
                FROM operator_portfolios p
                JOIN operator_portfolio_properties pp
                  ON pp.portfolio_id = p.portfolio_id
                WHERE p.tenant_id = CAST(:tid AS uuid)
                  AND p.portfolio_key = :portfolio_key
                """
            ),
            {"tid": tenant_id, "portfolio_key": portfolio_key},
        )
    ).fetchall()
    return [str(row[0]) for row in rows if row[0]]


async def _resolve_market_id_for_tenant(db: AsyncSession, tenant_id: str) -> str:
    try:
        row = (
            await db.execute(
                text(
                    """
                    SELECT market_id
                    FROM operator_market_links
                    WHERE company_id = CAST(:tid AS uuid)
                    LIMIT 1
                    """
                ),
                {"tid": tenant_id},
            )
        ).fetchone()
        if row and row[0]:
            return str(row[0])
    except Exception:
        await _rollback_quietly(db)
    try:
        row = (
            await db.execute(
                text(
                    """
                    SELECT market_id
                    FROM market_registry
                    WHERE operator_ids @> CAST(:operator_ids AS jsonb)
                    LIMIT 1
                    """
                ),
                {"operator_ids": json.dumps([tenant_id])},
            )
        ).fetchone()
        if row and row[0]:
            return str(row[0])
    except Exception:
        await _rollback_quietly(db)
    return "30a_fl"


async def _enforce_scope_permission(
    request: Request,
    db: AsyncSession,
    permission: str,
    ctx: Optional[dict] = None,
) -> dict:
    ctx = ctx or _require_context(request)
    profile = await _scope_profile(request, db, ctx)
    if permission == "assign" and not profile["can_assign"]:
        raise HTTPException(403, "You do not have permission to assign within this scope")
    if permission == "manage_vendors" and not profile["can_manage_vendors"]:
        raise HTTPException(403, "You do not have permission to manage vendors in this scope")
    if permission == "manage_settings" and not profile["can_manage_settings"]:
        raise HTTPException(403, "You do not have permission to manage settings in this scope")
    return profile


async def _visible_property_id_map(
    db: AsyncSession,
    tenant_id: str,
    visible_property_codes: Optional[set[str]],
) -> Optional[dict[str, str]]:
    if visible_property_codes is None:
        return None
    if not visible_property_codes:
        return {}
    meta = await _property_query_meta(db)
    if not meta:
        return {}
    rows = (
        await db.execute(
            text(
                f"""
                SELECT CAST({meta['id_expr']} AS text) AS property_id,
                       {meta['code_expr']} AS property_code
                FROM properties
                WHERE {meta['where_sql']}
                  AND {meta['code_expr']} = ANY(CAST(:codes AS text[]))
                """
            ),
            {"tid": tenant_id, "codes": sorted(visible_property_codes)},
        )
    ).mappings().all()
    return {
        str(row["property_id"]): str(row["property_code"])
        for row in rows
        if row.get("property_id") and row.get("property_code")
    }


def _normalize_vendor_property_ids(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item)]
        except Exception:
            return []
    return []


async def _first_gmail_credential_row(db: AsyncSession, operator_id: str, tenant_id: str):
    try:
        row = (await db.execute(
            text("""
                SELECT watched_email, connected_at, email_provider,
                       last_polled_at, last_poll_success, last_poll_summary,
                       last_poll_error, last_messages_found, last_new_pending_inquiries,
                       last_query_mode
                FROM operator_gmail_creds
                WHERE operator_id = :oid
                ORDER BY connected_at DESC NULLS LAST
                LIMIT 1
            """),
            {"oid": operator_id},
        )).mappings().first()
        if row:
            return row
    except Exception:
        await _rollback_quietly(db)

    try:
        row = (await db.execute(
            text("""
                SELECT g.watched_email, g.connected_at, g.email_provider,
                       g.last_polled_at, g.last_poll_success, g.last_poll_summary,
                       g.last_poll_error, g.last_messages_found, g.last_new_pending_inquiries,
                       g.last_query_mode
                FROM operator_accounts a
                JOIN operator_gmail_creds g
                  ON g.operator_id = a.id
                WHERE a.tenant_id = CAST(:tid AS uuid)
                ORDER BY g.connected_at DESC NULLS LAST
                LIMIT 1
            """),
            {"tid": tenant_id},
        )).mappings().first()
        if row:
            return row
    except Exception:
        await _rollback_quietly(db)

    try:
        return (await db.execute(
            text("""
                SELECT watched_email, connected_at, email_provider,
                       last_polled_at, last_poll_success, last_poll_summary,
                       last_poll_error, last_messages_found, last_new_pending_inquiries,
                       last_query_mode
                FROM operator_gmail_creds
                WHERE tenant_id = CAST(:tid AS uuid)
                ORDER BY connected_at DESC NULLS LAST
                LIMIT 1
            """),
            {"tid": tenant_id},
        )).mappings().first()
    except Exception:
        await _rollback_quietly(db)
        return None


async def _operator_inbox_account_row(db: AsyncSession, operator_id: str, tenant_id: str):
    try:
        row = (await db.execute(
            text("""
                SELECT messaging_email, email, email_provider
                FROM operator_accounts
                WHERE id = CAST(:oid AS uuid)
                LIMIT 1
            """),
            {"oid": operator_id},
        )).mappings().first()
        if row:
            return row
    except Exception:
        await _rollback_quietly(db)

    try:
        return (await db.execute(
            text("""
                SELECT messaging_email, email, email_provider
                FROM operator_accounts
                WHERE tenant_id = CAST(:tid AS uuid)
                LIMIT 1
            """),
            {"tid": tenant_id},
        )).mappings().first()
    except Exception:
        await _rollback_quietly(db)
        return None


async def _recent_prebooking_activity_row(db: AsyncSession, tenant_id: str):
    try:
        return (await db.execute(
            text("""
                SELECT platform, received_at
                FROM pre_booking_inquiries
                WHERE company_id = CAST(:tid AS uuid)
                  AND received_at >= NOW() - INTERVAL '14 days'
                ORDER BY received_at DESC
                LIMIT 1
            """),
            {"tid": tenant_id},
        )).mappings().first()
    except Exception:
        await _rollback_quietly(db)
        return None


async def _resolved_inbox_status_row(db: AsyncSession, operator_id: str, tenant_id: str):
    inbox_row = await _first_gmail_credential_row(db, operator_id, tenant_id)
    if inbox_row and inbox_row.get("watched_email"):
        return inbox_row

    account_row = await _operator_inbox_account_row(db, operator_id, tenant_id)
    recent_activity = await _recent_prebooking_activity_row(db, tenant_id)
    inbox_email = (account_row or {}).get("messaging_email") or (account_row or {}).get("email")
    if recent_activity and inbox_email:
        platform = (recent_activity.get("platform") or "pms").strip().lower()
        provider = (account_row or {}).get("email_provider") or "pms"
        activity_at = recent_activity.get("received_at")
        platform_label = platform.replace("_", " ") if platform else "pms"
        return {
            "watched_email": inbox_email,
            "connected_at": activity_at,
            "email_provider": provider,
            "last_polled_at": None,
            "last_poll_success": None,
            "last_poll_summary": f"Recent inquiry activity via {platform_label}",
            "last_poll_error": None,
            "last_messages_found": None,
            "last_new_pending_inquiries": None,
            "last_query_mode": "pms_activity",
        }

    return None


async def _notification_recipient_filter_sql(db: AsyncSession) -> str:
    columns = await _table_columns(db, "operator_notifications")
    if "recipient_user_id" in columns:
        return "(recipient_user_id IS NULL OR recipient_user_id = CAST(:oid AS uuid))"
    return "TRUE"


def _default_onboarding_status() -> dict:
    steps = [
        {
            "key": "connect_inbox",
            "title": "Connect your guest messaging inbox",
            "detail": "Connect your Gmail inbox so guest inquiries start flowing in.",
            "done": False,
            "critical": True,
            "cta_label": "Connect now",
            "cta_target": "/app/connect-gmail",
            "provider": None,
        },
        {
            "key": "review_properties",
            "title": "Review your properties",
            "detail": "Review your properties and set AI response mode once they are available.",
            "done": False,
            "critical": False,
            "cta_label": "Review",
            "cta_target": "properties",
            "count": 0,
        },
        {
            "key": "first_inquiry",
            "title": "Receive your first guest inquiry",
            "detail": "Once your inbox is connected and forwarded, inquiries appear in Messages.",
            "done": False,
            "critical": False,
            "cta_label": None,
            "cta_target": None,
        },
    ]
    return {
        "steps": steps,
        "percent_complete": 0,
        "completed": 0,
        "total": len(steps),
        "inbox_connected": False,
        "inbox_status": {
            "email": None,
            "provider": None,
            "last_polled_at": None,
            "last_poll_success": None,
            "last_poll_summary": None,
            "last_poll_error": None,
            "last_messages_found": None,
            "last_new_pending_inquiries": None,
            "last_query_mode": None,
        },
        "critical_incomplete": steps[0],
        "degraded": True,
    }


# ═════════════════════════════════════════════════════════════════════════════
# KNOWLEDGE BASE
# ═════════════════════════════════════════════════════════════════════════════
#
# All KB reads and writes go through `get_dashboard_kb_service()` from
# `app/services/messaging_brain/knowledge/dashboard_kb_service.py`. That
# service stores dashboard KB entries in `concierge_scoped_knowledge`
# (one row per Q&A entry, scoped by tenant/property), not the retired
# guidebook-style `concierge_knowledge` JSONB table.
#
# Property reference resolution accepts:
#   - `properties.property_code`
#   - `properties.external_id`
#   - the property's `scope_target_id` UUID
#   - the literal `"__all_properties__"` for tenant-scope knowledge
#
# Historical note: this endpoint used to fan out JSONB `faq` items from
# `concierge_knowledge` into flat rows. That model is gone; the dashboard
# KB service is now the canonical path.
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/kb")
async def list_kb_entries(
    request: Request,
    property_id: Optional[str] = None,
    group_id: Optional[str] = None,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    knowledge_service = get_dashboard_kb_service()
    try:
        entries = await knowledge_service.list_dashboard_entries(
            session=db,
            tenant_id=uuid.UUID(ctx["tenant_id"]),
            property_ref=property_id,
            group_id=group_id,
        )
        return {"entries": entries, "count": len(entries)}
    except Exception as e:
        await _rollback_quietly(db)
        logger.exception("[KB] list failed")
        classified = _classify_db_exception(e)
        if classified:
            raise classified
        raise HTTPException(500, f"KB list failed: {e}")


@router.post("/kb")
async def create_kb_entry(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    question = (body.get("question") or "").strip()
    answer = (body.get("answer") or "").strip()
    if not question or not answer:
        raise HTTPException(400, "question and answer are required")

    category = (body.get("category") or "General").strip()
    retry_topic = (body.get("retry_topic") or "").strip().lower()
    property_id = body.get("property_id")  # None = all-properties bucket
    property_external_id = body.get("property_external_id")
    property_group_id = body.get("property_group_id")
    knowledge_service = get_dashboard_kb_service()
    entry = await knowledge_service.create_dashboard_entry(
        session=db,
        tenant_id=uuid.UUID(ctx["tenant_id"]),
        question=question,
        answer=answer,
        category=category,
        property_id=property_id,
        property_external_id=property_external_id,
        property_group_id=property_group_id,
    )
    from app.core.database import get_db_session
    from app.services.messaging_brain.kb_retry_handler import kb_post_save_retry_held_inquiries

    retry_result = await kb_post_save_retry_held_inquiries(
        db=db,
        db_factory=get_db_session,
        tenant_id=ctx["tenant_id"],
        operator_id=ctx["operator_id"],
        topic=retry_topic or None,
    )

    return {
        "ok": True,
        "id": entry["id"],
        "entry": entry,
        **retry_result,
    }


@router.patch("/kb/{entry_id}")
async def update_kb_entry(
    entry_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    knowledge_service = get_dashboard_kb_service()
    updated = await knowledge_service.update_dashboard_entry(
        session=db,
        tenant_id=uuid.UUID(ctx["tenant_id"]),
        entry_id=entry_id,
        body=body,
    )
    if not updated:
        raise HTTPException(404, "KB entry not found")
    return {"ok": True, "id": entry_id}


@router.delete("/kb/{entry_id}")
async def delete_kb_entry(
    entry_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    knowledge_service = get_dashboard_kb_service()
    deleted = await knowledge_service.delete_dashboard_entry(
        session=db,
        tenant_id=uuid.UUID(ctx["tenant_id"]),
        entry_id=entry_id,
    )
    if not deleted:
        raise HTTPException(404, "KB entry not found")
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════════════
# KNOWLEDGE GAPS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/kb-gaps")
async def list_kb_gaps(
    request: Request,
    resolved: Optional[bool] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    try:
        gap_columns = await _table_columns(db, "concierge_knowledge_gaps")
        if not gap_columns:
            return {"gaps": [], "count": 0, "total_unresolved": 0}
        where = ["tenant_id = CAST(:tid AS uuid)"]
        params: dict = {"tid": ctx["tenant_id"], "limit": min(limit, 200)}
        if resolved is not None:
            where.append("resolved = :resolved")
            params["resolved"] = resolved

        stage_select = "stage" if "stage" in gap_columns else "NULL::text AS stage"
        channel_select = "channel" if "channel" in gap_columns else "'text' AS channel"
        source_select = "source" if "source" in gap_columns else "'concierge' AS source"
        intent_select = "detected_intent" if "detected_intent" in gap_columns else "NULL::text AS detected_intent"
        confidence_select = "confidence_score" if "confidence_score" in gap_columns else "NULL::float AS confidence_score"
        resolved_select = "resolved" if "resolved" in gap_columns else "FALSE AS resolved"
        resolution_notes_select = "resolution_notes" if "resolution_notes" in gap_columns else "NULL::text AS resolution_notes"
        metadata_select = (
            "metadata" if "metadata" in gap_columns else
            ("metadata_json AS metadata" if "metadata_json" in gap_columns else "'{}'::jsonb AS metadata")
        )
        property_external_id_select = "property_external_id" if "property_external_id" in gap_columns else "NULL::text AS property_external_id"
        created_at_expr = "created_at" if "created_at" in gap_columns else "NOW()"
        created_at_select = f"{created_at_expr} AS created_at"

        rows = (await db.execute(
            text(f"""
                SELECT gap_id, question_text, {stage_select}, {channel_select}, {source_select},
                       {intent_select}, {confidence_select}, {resolved_select},
                       {resolution_notes_select}, {metadata_select}, {property_external_id_select},
                       {created_at_select}
                FROM concierge_knowledge_gaps
                WHERE {' AND '.join(where)}
                ORDER BY {created_at_expr} DESC
                LIMIT :limit
            """),
            params,
        )).mappings().all()

        # Aggregate duplicate questions (same question, different sessions)
        seen: dict = {}
        for r in rows:
            q = (r["question_text"] or "").strip().lower()
            row_created_at = r["created_at"].isoformat() if r["created_at"] else None
            if q in seen:
                seen[q]["ask_count"] += 1
                if row_created_at:
                    prior_last = seen[q].get("last_asked_at")
                    if not prior_last or row_created_at > prior_last:
                        seen[q]["last_asked_at"] = row_created_at
                continue
            meta = r["metadata"] or {}
            if isinstance(meta, str):
                try: meta = json.loads(meta)
                except: meta = {}
            seen[q] = {
                "gap_id":         str(r["gap_id"]),
                "question":       r["question_text"],
                "category":       (r["detected_intent"] or "general").replace("_", " ").title(),
                "category_slug":  r["detected_intent"] or "general",
                "confidence":     float(r["confidence_score"] or 0),
                "ai_answer":      meta.get("ai_response", ""),
                "stage":          r["stage"],
                "channel":        r["channel"],
                "source":         r["source"],
                "resolved":       bool(r["resolved"]),
                "property":       r["property_external_id"] or "All Properties",
                "ask_count":      1,
                "created_at":     row_created_at,
                "last_asked_at":  row_created_at,
                "draft_id":       meta.get("draft_id", ""),
                "reason":         meta.get("reason", ""),
                "intent":         meta.get("intent", ""),
                "threshold_pct":  meta.get("threshold_pct"),
                "actual_pct":     meta.get("actual_pct"),
                "missing_topics": meta.get("missing_topics") or [],
                "parser_source":  meta.get("parser_source", ""),
                "asks":           meta.get("asks") or [],
                "platform_listing_id": meta.get("platform_listing_id", ""),
                "platform_unit_id": meta.get("platform_unit_id", ""),
                "link_context_summary": meta.get("link_context_summary", ""),
                "policy_warnings": meta.get("policy_warnings") or [],
            }
        return {
            "gaps": list(seen.values()),
            "count": len(seen),
            "total_unresolved": sum(1 for g in seen.values() if not g["resolved"]),
        }
    except Exception as e:
        await _rollback_quietly(db)
        logger.exception("[KBGaps] list failed")
        raise HTTPException(500, f"KB gaps list failed: {e}")


@router.post("/kb-gaps/{gap_id}/resolve")
async def resolve_kb_gap(
    gap_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Mark a gap as resolved; optionally promote its answer into the KB."""
    ctx = _require_context(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    add_to_kb = bool(body.get("add_to_kb"))
    answer = (body.get("answer") or "").strip()
    notes = (body.get("notes") or "").strip()
    retry_topic = (body.get("retry_topic") or "").strip().lower()

    # Load gap
    gap = (await db.execute(
        text("""
            SELECT gap_id, question_text, detected_intent, property_external_id
            FROM concierge_knowledge_gaps
            WHERE gap_id = CAST(:gid AS uuid)
              AND tenant_id = CAST(:tid AS uuid)
            LIMIT 1
        """),
        {"gid": gap_id, "tid": ctx["tenant_id"]},
    )).fetchone()
    if not gap:
        raise HTTPException(404, "Gap not found")

    # Optionally add to KB through the scoped dashboard KB service.
    if add_to_kb and answer:
        dashboard_kb = get_dashboard_kb_service()
        await dashboard_kb.create_dashboard_entry(
            session=db,
            tenant_id=uuid.UUID(ctx["tenant_id"]),
            question=gap.question_text,
            answer=answer,
            category=(gap.detected_intent or "general").replace("_", " ").title(),
            property_external_id=gap.property_external_id or "__all_properties__",
            autocommit=False,
        )

    await db.execute(
        text("""
            UPDATE concierge_knowledge_gaps
            SET resolved = TRUE,
                resolution_notes = :notes
            WHERE gap_id = CAST(:gid AS uuid)
              AND tenant_id = CAST(:tid AS uuid)
        """),
        {"gid": gap_id, "tid": ctx["tenant_id"], "notes": notes or "Resolved via dashboard"},
    )
    await db.commit()
    from app.core.database import get_db_session
    from app.services.messaging_brain.kb_retry_handler import kb_post_save_retry_held_inquiries

    retry_result = await kb_post_save_retry_held_inquiries(
        db=db,
        db_factory=get_db_session,
        tenant_id=ctx["tenant_id"],
        operator_id=ctx["operator_id"],
        topic=retry_topic or None,
    )
    hub = get_operator_realtime_hub()
    await hub.publish(
        ctx["tenant_id"],
        "kb.retry_progress",
        {
            "gap_id": gap_id,
            "tenant_id": ctx["tenant_id"],
            "topic": retry_topic or None,
            "result": retry_result,
        },
    )
    await hub.publish(
        ctx["tenant_id"],
        "summary.updated",
        {
            "tenant_id": ctx["tenant_id"],
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "source": "kb_gap_resolve",
        },
    )
    return {"ok": True, "added_to_kb": add_to_kb and bool(answer), **retry_result}


@router.post("/kb-gaps/{gap_id}/dismiss")
async def dismiss_kb_gap(
    gap_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Dismiss (not actionable) — marks as resolved with a dismissal note."""
    ctx = _require_context(request)
    await db.execute(
        text("""
            UPDATE concierge_knowledge_gaps
            SET resolved = TRUE,
                resolution_notes = 'Dismissed by operator'
            WHERE gap_id = CAST(:gid AS uuid)
              AND tenant_id = CAST(:tid AS uuid)
        """),
        {"gid": gap_id, "tid": ctx["tenant_id"]},
    )
    await db.commit()
    return {"ok": True}


@router.get("/kb/learning-proposals")
async def list_learning_proposals(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Return pending extraction candidates created from operator draft edits."""
    ctx = _require_context(request)
    rows = await db.execute(
        text("""
            SELECT
                id,
                proposed_question_text,
                proposed_answer_text,
                scope_type,
                confidence,
                proposed_metadata,
                created_at
            FROM extraction_candidates
            WHERE source_type = 'other'
              AND review_status = 'pending'
              AND proposed_metadata::jsonb->>'source' = 'operator_draft_edit'
              AND tenant_id = CAST(:tid AS uuid)
            ORDER BY created_at DESC
        """),
        {"tid": ctx["tenant_id"]},
    )
    proposals = []
    for row in rows.mappings():
        meta = row["proposed_metadata"]
        if isinstance(meta, str):
            import json as _json
            try:
                meta = _json.loads(meta)
            except Exception:
                meta = {}
        proposals.append({
            "id": str(row["id"]),
            "proposed_question_text": row["proposed_question_text"],
            "proposed_answer_text": row["proposed_answer_text"],
            "scope_type": row["scope_type"],
            "confidence": row["confidence"],
            "draft_id": meta.get("draft_id"),
            "edit_type": meta.get("edit_type"),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        })
    return {"proposals": proposals}


@router.post("/kb/learning-proposals/{candidate_id}/approve")
async def approve_learning_proposal(
    candidate_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Approve a learning proposal and promote it to the KB."""
    ctx = _require_context(request)
    from app.services.extraction.staging_service import ExtractionStagingService
    staging = ExtractionStagingService()
    result = await staging.approve_candidate(
        db,
        candidate_id=candidate_id,
        reviewed_by_user_id=ctx.get("operator_id") or ctx["tenant_id"],
    )
    await db.commit()
    return {
        "ok": True,
        "promoted_to_table": result.promoted_to_table,
        "promoted_to_id": str(result.promoted_to_id) if result.promoted_to_id else None,
    }


@router.post("/kb/learning-proposals/{candidate_id}/reject")
async def reject_learning_proposal(
    candidate_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Reject a learning proposal."""
    ctx = _require_context(request)
    from app.services.extraction.staging_service import ExtractionStagingService
    staging = ExtractionStagingService()
    await staging.reject_candidate(
        db,
        candidate_id=candidate_id,
        reviewed_by_user_id=ctx.get("operator_id") or ctx["tenant_id"],
    )
    await db.commit()
    return {"ok": True}


@router.get("/group-knowledge-gaps")
async def get_group_knowledge_gaps_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Return structural knowledge gaps for all property groups with members.

    A structural gap is an expected-topic hole at neighborhood/HOA scope —
    e.g. "WaterSound has 12 properties but no HOA rules on file." Distinct
    from reactive gaps (unanswered guest questions) in /kb-gaps.

    Response:
        {
          "gaps": [
            {
              "group_id": "...",
              "group_name": "WaterSound",
              "group_type": "neighborhood",
              "member_count": 12,
              "missing_topics": ["hoa_rules", "required_vendors", "gate_code"],
              "present_topics": ["quiet_hours"],
              "coverage_fraction": 0.25
            }
          ],
          "total_groups_checked": 3,
          "groups_with_gaps": 2
        }
    """
    ctx = _require_context(request)
    from app.services.messaging_brain.knowledge.group_gap_surfacer import (
        get_group_knowledge_gaps,
    )
    import uuid as _uuid
    try:
        gaps = await get_group_knowledge_gaps(db, _uuid.UUID(ctx["tenant_id"]))
    except Exception as exc:
        raise HTTPException(500, f"Group gap check failed: {exc}")

    return {
        "gaps": [g.to_dict() for g in gaps],
        "total_groups_checked": len(gaps),  # only groups with gaps are returned
        "groups_with_gaps": len(gaps),
    }


@router.post("/kb/test")
async def test_kb_question(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Test a question against the KB — returns best match + confidence."""
    ctx = _require_context(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    question = (body.get("question") or "").strip().lower()
    if not question:
        raise HTTPException(400, "question is required")
    knowledge_service = get_dashboard_kb_service()
    result = await knowledge_service.test_dashboard_question(
        session=db,
        tenant_id=uuid.UUID(ctx["tenant_id"]),
        question=question,
    )
    best = result["best"]
    best_score = result["score"]

    threshold = 0.40
    if best and best_score >= threshold:
        return {
            "answered": True,
            "confidence": round(best_score, 2),
            "answer": best["answer"],
            "sources": [f"{best['category']} · {best['property_label']}"],
            "match_question": best["question"],
        }
    # Log the gap so it shows up in KB Gaps
    await db.execute(
        text("""
            INSERT INTO concierge_knowledge_gaps
            (gap_id, tenant_id, question_text, channel, source, detected_intent,
             confidence_score, metadata)
            VALUES (gen_random_uuid(), CAST(:tid AS uuid), :q, 'dashboard_test',
                    'operator_test', 'general', :conf,
                    CAST(:meta AS jsonb))
        """),
        {
            "tid": ctx["tenant_id"],
            "q": question,
            "conf": round(best_score, 2),
            "meta": json.dumps({"ai_response": "", "tested_by": ctx["email"]}),
        },
    )
    await db.commit()
    return {
        "answered": False,
        "confidence": round(best_score, 2),
        "answer": f"No confident match found. Added as a knowledge gap — resolve it in KB Gaps to teach your AI.",
        "sources": [],
    }


# ═════════════════════════════════════════════════════════════════════════════
# GUEST SESSIONS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/sessions")
async def list_sessions(
    request: Request,
    status: Optional[str] = None,
    phase: Optional[str] = None,
    assigned_to_me: bool = False,
    portfolio_key: str = "",
    include_archived: bool = False,
    limit: int = 50,
    db: AsyncSession = Depends(get_async_session),
):
    started = time.perf_counter()
    ctx = _require_context(request)
    try:
        scope_profile = await _scope_profile(request, db, ctx)
        session_columns = await _table_columns(db, "concierge_guest_sessions")
        where = ["tenant_id = CAST(:tid AS uuid)"]
        params: dict = {
            "tid": ctx["tenant_id"],
            "limit": min(limit, 200),
            "oid": ctx["operator_id"],
        }
        visible_property_codes = scope_profile["visible_property_codes"]
        portfolio_property_codes: list[str] = []
        if portfolio_key:
            portfolio_property_codes = await _portfolio_property_codes(db, ctx["tenant_id"], portfolio_key)
            if visible_property_codes is not None:
                portfolio_property_codes = [
                    code for code in portfolio_property_codes
                    if code in visible_property_codes
                ]
            where.append("property_code = ANY(CAST(:portfolio_property_codes AS text[]))")
            params["portfolio_property_codes"] = portfolio_property_codes or ["__no_match__"]
        elif visible_property_codes is not None:
            where.append("property_code = ANY(CAST(:visible_property_codes AS text[]))")
            params["visible_property_codes"] = sorted(visible_property_codes)
        if status:
            where.append("status = :status")
            params["status"] = status
        if phase:
            where.append("phase = :phase")
            params["phase"] = phase
        if assigned_to_me and await _table_columns(db, "operator_workflow_handoffs"):
            where.append(
                """
                EXISTS (
                    SELECT 1
                    FROM operator_workflow_handoffs h
                    WHERE h.tenant_id = CAST(:tid AS uuid)
                      AND h.workflow_type = 'stay'
                      AND h.workflow_ref = CAST(session_id AS text)
                      AND h.status IN ('open', 'in_progress', 'blocked')
                      AND h.assignee_user_id = CAST(:oid AS uuid)
                )
                """
            )

        optional_session_cols = {
            "guest_thread_id": "NULL::uuid AS guest_thread_id",
            "proactive_triggered_at": "NULL::timestamptz AS proactive_triggered_at",
            "pms_synced_at": "NULL::timestamptz AS pms_synced_at",
            "reservation_id": "NULL::text AS reservation_id",
        }
        optional_selects = ",\n                       ".join(
            col if col in session_columns else fallback
            for col, fallback in optional_session_cols.items()
        )

        rows = (await db.execute(
            text(f"""
                SELECT session_id, token, guest_name, guest_phone, guest_email,
                       property_id, property_code, property_name,
                       num_guests, check_in, check_out,
                       status, phase, conversation_count, last_message_at,
                       {optional_selects},
                       created_at, updated_at
                FROM concierge_guest_sessions
                WHERE {' AND '.join(where)}
                ORDER BY COALESCE(last_message_at, created_at) DESC
                LIMIT :limit
            """),
            params,
        )).mappings().all()

        # Get escalation count per session
        sess_tokens = [r["token"] for r in rows if r["token"]]
        esc_map = {}
        if sess_tokens:
            esc_rows = (await db.execute(
                text("""
                    SELECT session_token, COUNT(*) AS open_count
                    FROM concierge_escalations
                    WHERE session_token = ANY(:tokens)
                      AND status IN ('pending', 'acknowledged')
                    GROUP BY session_token
                """),
                {"tokens": sess_tokens},
            )).mappings().all()
            esc_map = {r["session_token"]: int(r["open_count"] or 0) for r in esc_rows}

        session_ids = [str(r["session_id"]) for r in rows if r["session_id"]]
        journey_map = {}
        if session_ids and await _table_columns(db, "concierge_guest_journeys"):
            journey_rows = (await db.execute(
                text("""
                    SELECT session_id, welcome_sent, extend_offer_sent,
                           checkin_reminder_sent, checkout_reminder_sent,
                           pool_heat_offered, pool_heat_accepted
                    FROM concierge_guest_journeys
                    WHERE session_id = ANY(CAST(:session_ids AS uuid[]))
                """),
                {"session_ids": session_ids},
            )).mappings().all()
            journey_map = {
                str(r["session_id"]): {
                    "welcome_sent": bool(r["welcome_sent"]),
                    "extend_offer_sent": bool(r["extend_offer_sent"]),
                    "checkin_reminder_sent": bool(r["checkin_reminder_sent"]),
                    "checkout_reminder_sent": bool(r["checkout_reminder_sent"]),
                    "pool_heat_offered": bool(r["pool_heat_offered"]),
                    "pool_heat_accepted": bool(r["pool_heat_accepted"]),
                }
                for r in journey_rows
            }

        notification_count_map = {}
        if session_ids and await _table_columns(db, "concierge_notifications"):
            notification_rows = (await db.execute(
                text("""
                    SELECT session_id, COUNT(*) AS notification_count
                    FROM concierge_notifications
                    WHERE session_id = ANY(CAST(:session_ids AS uuid[]))
                    GROUP BY session_id
                """),
                {"session_ids": session_ids},
            )).mappings().all()
            notification_count_map = {
                str(r["session_id"]): int(r["notification_count"] or 0)
                for r in notification_rows
            }

        assignment_map = {}
        if session_ids and await _table_columns(db, "operator_workflow_handoffs"):
            assignment_rows = (await db.execute(
                text("""
                    SELECT workflow_ref,
                           assignee_user_id::text AS assignee_user_id,
                           assignee_label,
                           COUNT(*) AS open_handoff_count
                    FROM operator_workflow_handoffs
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND workflow_type = 'stay'
                      AND workflow_ref = ANY(CAST(:session_ids AS text[]))
                      AND status IN ('open', 'in_progress', 'blocked')
                    GROUP BY workflow_ref, assignee_user_id, assignee_label
                    ORDER BY workflow_ref, open_handoff_count DESC, assignee_label ASC
                """),
                {"tid": ctx["tenant_id"], "session_ids": session_ids},
            )).mappings().all()
            for row in assignment_rows:
                ref = str(row["workflow_ref"])
                if ref in assignment_map:
                    continue
                assignment_map[ref] = {
                    "assigned_operator_id": row.get("assignee_user_id") or "",
                    "assigned_operator_label": row.get("assignee_label") or "",
                    "open_handoff_count": int(row.get("open_handoff_count") or 0),
                    "assignment_status": "assigned" if row.get("assignee_user_id") or row.get("assignee_label") else "unassigned",
                }

        items = []
        enriched_summary = {
            "with_booking_context": 0,
            "journey_tracked": 0,
            "proactive_evaluated": 0,
            "notifications_sent": 0,
            "archived": 0,
        }
        session_ids = [str(r["session_id"]) for r in rows if r["session_id"]]
        await stay_workflow_service.sync_sessions(db, ctx["tenant_id"], session_ids)
        workflow_map = await stay_workflow_service.workflow_map(db, ctx["tenant_id"], session_ids)
        for r in rows:
            sid = str(r["session_id"])
            journey_state = journey_map.get(sid, {})
            workflow = workflow_map.get(sid, {})
            operational_state = str(workflow.get("operational_state") or "active").lower()
            if operational_state == "archived":
                enriched_summary["archived"] += 1
                if not include_archived:
                    continue
            has_booking_context = bool(r["reservation_id"] or r["pms_synced_at"])
            notification_count = notification_count_map.get(sid, 0)
            assignment = assignment_map.get(sid, {})
            if has_booking_context:
                enriched_summary["with_booking_context"] += 1
            if journey_state:
                enriched_summary["journey_tracked"] += 1
            if r["proactive_triggered_at"]:
                enriched_summary["proactive_evaluated"] += 1
            enriched_summary["notifications_sent"] += notification_count
            items.append({
                "session_id":       sid,
                "token":            r["token"],
                "guest_name":       r["guest_name"],
                "guest_phone":      r["guest_phone"],
                "guest_email":      r["guest_email"],
                "property_code":    r["property_code"],
                "property_name":    r["property_name"],
                "num_guests":       r["num_guests"],
                "check_in":         r["check_in"].isoformat() if r["check_in"] else None,
                "check_out":        r["check_out"].isoformat() if r["check_out"] else None,
                "status":           r["status"],
                "phase":            r["phase"],
                "conversation_count": r["conversation_count"] or 0,
                "last_message_at":  r["last_message_at"].isoformat() if r["last_message_at"] else None,
                "open_escalations": esc_map.get(r["token"], 0),
                "reservation_id":   r["reservation_id"],
                "pms_synced_at":    r["pms_synced_at"].isoformat() if r["pms_synced_at"] else None,
                "proactive_triggered_at": r["proactive_triggered_at"].isoformat() if r["proactive_triggered_at"] else None,
                "has_booking_context": has_booking_context,
                "journey_tracked": bool(journey_state),
                "welcome_sent": journey_state.get("welcome_sent", False),
                "checkin_reminder_sent": journey_state.get("checkin_reminder_sent", False),
                "checkout_reminder_sent": journey_state.get("checkout_reminder_sent", False),
                "extend_offer_sent": journey_state.get("extend_offer_sent", False),
                "pool_heat_offered": journey_state.get("pool_heat_offered", False),
                "pool_heat_accepted": journey_state.get("pool_heat_accepted", False),
                "notifications_sent": notification_count,
                "assigned_operator_id": assignment.get("assigned_operator_id", ""),
                "assigned_operator_label": assignment.get("assigned_operator_label", ""),
                "open_handoff_count": assignment.get("open_handoff_count", 0),
                "assignment_status": assignment.get("assignment_status", "unassigned"),
                "workflow": workflow,
            })

        summary = {"all": 0, "in_stay": 0, "arriving": 0, "post_stay": 0}
        for item in items:
            summary["all"] += 1
            phase_val = item.get("phase") or ""
            if phase_val == "in_stay":
                summary["in_stay"] += 1
            elif phase_val in {"pre_arrival", "arrival_day"}:
                summary["arriving"] += 1
            elif phase_val == "post_stay":
                summary["post_stay"] += 1

        summary.update(enriched_summary)
        payload = {"sessions": items, "count": len(items), "summary": summary}
        logger.info(
            "[Today] sessions tenant=%s limit=%s count=%s include_archived=%s elapsed_ms=%.1f",
            ctx["tenant_id"],
            min(limit, 200),
            len(items),
            include_archived,
            (time.perf_counter() - started) * 1000,
        )
        return payload
    except Exception as e:
        logger.exception("[Sessions] list failed")
        raise HTTPException(500, f"Sessions list failed: {e}")


@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    try:
        scope_profile = await _scope_profile(request, db, ctx)
        has_concierge_messages = bool(await _table_columns(db, "concierge_messages"))
        session_columns = await _table_columns(db, "concierge_guest_sessions")
        optional_session_cols = {
            "proactive_triggered_at": "NULL::timestamptz AS proactive_triggered_at",
            "pms_synced_at": "NULL::timestamptz AS pms_synced_at",
            "reservation_id": "NULL::text AS reservation_id",
        }
        optional_selects = ",\n                       ".join(
            col if col in session_columns else fallback
            for col, fallback in optional_session_cols.items()
        )
        sess = (await db.execute(
            text("""
                SELECT session_id, token, guest_name, guest_phone, guest_email,
                       property_code, property_name, num_guests,
                       check_in, check_out, status, phase,
                       conversation_count, last_message_at, created_at,
                       """ + optional_selects + """
                FROM concierge_guest_sessions
                WHERE session_id = CAST(:sid AS uuid)
                  AND tenant_id = CAST(:tid AS uuid)
                  {"AND property_code = ANY(CAST(:visible_property_codes AS text[]))" if scope_profile["visible_property_codes"] is not None else ""}
                LIMIT 1
            """),
            {
                "sid": session_id,
                "tid": ctx["tenant_id"],
                **({"visible_property_codes": sorted(scope_profile["visible_property_codes"])} if scope_profile["visible_property_codes"] is not None else {}),
            },
        )).mappings().first()
        if not sess:
            raise HTTPException(404, "Session not found")

        msgs = []
        if has_concierge_messages:
            msgs = (await db.execute(
                text("""
                    SELECT message_id, direction, content, content_type,
                           detected_intent, was_quick_answer, response_time_ms,
                           created_at
                    FROM concierge_messages
                    WHERE session_id = CAST(:sid AS uuid)
                    ORDER BY created_at ASC
                    LIMIT 200
                """),
                {"sid": session_id},
            )).mappings().all()

        journey_columns = await _table_columns(db, "concierge_guest_journeys")
        activity_columns = await _table_columns(db, "concierge_journey_activities")
        notification_columns = await _table_columns(db, "concierge_notifications")

        journey = None
        activities = []
        notifications = []

        if journey_columns:
            journey = (await db.execute(
                text("""
                    SELECT journey_id,
                           welcome_sent, welcome_sent_at,
                           extend_offer_sent, extend_offer_sent_at, extend_offer_response,
                           pool_heat_offered, pool_heat_accepted,
                           checkin_reminder_sent, checkin_reminder_sent_at,
                           checkout_reminder_sent, checkout_reminder_sent_at
                    FROM concierge_guest_journeys
                    WHERE session_id = CAST(:sid AS uuid)
                    LIMIT 1
                """),
                {"sid": session_id},
            )).mappings().first()

        if journey and activity_columns:
            activities = (await db.execute(
                text("""
                    SELECT activity_id, activity_type, status, discussed_at, notes
                    FROM concierge_journey_activities
                    WHERE journey_id = CAST(:jid AS uuid)
                    ORDER BY activity_type ASC
                """),
                {"jid": str(journey["journey_id"])},
            )).mappings().all()

        if notification_columns:
            notifications = (await db.execute(
                text("""
                    SELECT notification_id, notification_type, channel, recipient,
                           status, sent_at, delivered_at, external_id, error_message
                    FROM concierge_notifications
                    WHERE session_id = CAST(:sid AS uuid)
                    ORDER BY created_at DESC
                    LIMIT 20
                """),
                {"sid": session_id},
            )).mappings().all()

        open_escalations = (await db.execute(
            text("""
                SELECT ticket_id, reason, priority, status, summary, created_at
                FROM concierge_escalations
                WHERE session_token = :token
                ORDER BY created_at DESC
                LIMIT 20
            """),
            {"token": sess["token"]},
        )).mappings().all()

        # Intent mix
        intent_mix = {}
        for m in msgs:
            intent = (m["detected_intent"] or "").strip()
            if not intent:
                continue
            intent_mix[intent] = intent_mix.get(intent, 0) + 1

        booking_context = {}
        try:
            adapter = build_booking_context_adapter(
                BookingContextAdapterConfig(company_id=uuid.UUID(ctx["tenant_id"]))
            )
            booking_context = await adapter.lookup(
                db,
                BookingContextLookup(session_id=session_id),
            )
        except BookingContextBuildError:
            booking_context = {}
        except Exception:
            logger.exception("[Sessions] booking context lookup failed")
            booking_context = {}

        stay_module_enabled = await _module_enabled(db, ctx["tenant_id"], FeatureFlag.STAY_WORKFLOW_MODULE)
        handoffs_enabled = await _module_enabled(db, ctx["tenant_id"], FeatureFlag.HANDOFFS_MODULE)
        work_orders_enabled = await _module_enabled(db, ctx["tenant_id"], FeatureFlag.WORK_ORDERS_MODULE)

        workflow = {}
        events = []
        pms_feed = {}
        if stay_module_enabled:
            await stay_workflow_service.sync_session(db, ctx["tenant_id"], session_id)
            workflow_map = await stay_workflow_service.workflow_map(db, ctx["tenant_id"], [session_id])
            workflow = workflow_map.get(session_id, {})
            events = await stay_event_service.list_events(db, ctx["tenant_id"], session_id, limit=30)
            pms_feed = await stay_pms_feed_service.load_feed(
                db,
                ctx["tenant_id"],
                reservation_id=sess["reservation_id"],
                property_code=sess["property_code"],
                property_name=sess["property_name"],
                check_in=sess["check_in"],
                check_out=sess["check_out"],
            )

        handoffs = []
        if handoffs_enabled:
            handoffs = (
                await handoff_service.list_handoffs(
                    db,
                    ctx["tenant_id"],
                    workflow_type="stay",
                    workflow_refs=[session_id],
                )
            ).get(session_id, [])

        work_orders = []
        if work_orders_enabled:
            work_orders = (
                await work_order_service.list_work_orders(
                    db,
                    ctx["tenant_id"],
                    workflow_type="stay",
                    workflow_refs=[session_id],
                )
            ).get(session_id, [])

        repeat_guest = {}
        try:
            from app.services.concierge.guest_profile_service import lookup_guest_profile
            profile = await lookup_guest_profile(
                db,
                ctx["tenant_id"],
                phone=sess["guest_phone"],
                email=sess["guest_email"],
            )
            if profile:
                repeat_guest = profile.to_concierge_context()
        except Exception:
            repeat_guest = {}

        feedback_prompt = None
        if sess["phase"] in {"departure_day", "post_stay"} and not sess["feedback_rating"]:
            first_name = (sess["guest_name"] or "there").split()[0]
            feedback_prompt = (
                f"Hi {first_name}, thank you again for staying with us at {sess['property_name']}. "
                "We'd love to hear how your stay went if you have a moment to share feedback."
            )

        return {
            "session": {
                "session_id":    str(sess["session_id"]),
                "guest_thread_id": str(sess["guest_thread_id"]) if sess.get("guest_thread_id") else None,
                "token":         sess["token"],
                "guest_name":    sess["guest_name"],
                "guest_phone":   sess["guest_phone"],
                "guest_email":   sess["guest_email"],
                "property_code": sess["property_code"],
                "property_name": sess["property_name"],
                "num_guests":    sess["num_guests"],
                "check_in":      sess["check_in"].isoformat() if sess["check_in"] else None,
                "check_out":     sess["check_out"].isoformat() if sess["check_out"] else None,
                "status":        sess["status"],
                "phase":         sess["phase"],
                "conversation_count": sess["conversation_count"] or 0,
                "last_message_at":    sess["last_message_at"].isoformat() if sess["last_message_at"] else None,
                "proactive_triggered_at": sess["proactive_triggered_at"].isoformat() if sess["proactive_triggered_at"] else None,
                "pms_synced_at": sess["pms_synced_at"].isoformat() if sess["pms_synced_at"] else None,
                "reservation_id": sess["reservation_id"],
            },
            "repeat_guest_profile": repeat_guest,
            "post_stay_actions": {
                "can_request_feedback": bool(
                    sess["phase"] in {"departure_day", "post_stay"} and not sess["feedback_rating"]
                ),
                "feedback_prompt_suggestion": feedback_prompt,
                "has_repeat_guest_memory": bool(repeat_guest),
            },
            "messages": [
                {
                    "message_id":   str(m["message_id"]),
                    "direction":    m["direction"],
                    "content":      m["content"],
                    "content_type": m["content_type"],
                    "intent":       m["detected_intent"],
                    "was_quick_answer": bool(m["was_quick_answer"]),
                    "response_time_ms": m["response_time_ms"],
                    "created_at":   m["created_at"].isoformat() if m["created_at"] else None,
                }
                for m in msgs
            ],
            "open_escalations": [
                {
                    "ticket_id": e["ticket_id"],
                    "reason":    e["reason"],
                    "priority":  e["priority"],
                    "status":    e["status"],
                    "summary":   e["summary"],
                    "created_at": e["created_at"].isoformat() if e["created_at"] else None,
                }
                for e in open_escalations
            ],
            "intent_mix": intent_mix,
            "booking_context": booking_context,
            "journey": {
                "journey_id": str(journey["journey_id"]) if journey else None,
                "welcome_sent": bool(journey["welcome_sent"]) if journey else False,
                "welcome_sent_at": journey["welcome_sent_at"].isoformat() if journey and journey["welcome_sent_at"] else None,
                "extend_offer_sent": bool(journey["extend_offer_sent"]) if journey else False,
                "extend_offer_sent_at": journey["extend_offer_sent_at"].isoformat() if journey and journey["extend_offer_sent_at"] else None,
                "extend_offer_response": journey["extend_offer_response"] if journey else None,
                "pool_heat_offered": bool(journey["pool_heat_offered"]) if journey else False,
                "pool_heat_accepted": bool(journey["pool_heat_accepted"]) if journey else False,
                "checkin_reminder_sent": bool(journey["checkin_reminder_sent"]) if journey else False,
                "checkin_reminder_sent_at": journey["checkin_reminder_sent_at"].isoformat() if journey and journey["checkin_reminder_sent_at"] else None,
                "checkout_reminder_sent": bool(journey["checkout_reminder_sent"]) if journey else False,
                "checkout_reminder_sent_at": journey["checkout_reminder_sent_at"].isoformat() if journey and journey["checkout_reminder_sent_at"] else None,
                "activities": [
                    {
                        "activity_id": str(a["activity_id"]),
                        "activity_type": a["activity_type"],
                        "status": a["status"],
                        "discussed_at": a["discussed_at"].isoformat() if a["discussed_at"] else None,
                        "notes": a["notes"],
                    }
                    for a in activities
                ],
            },
            "notifications": [
                {
                    "notification_id": str(n["notification_id"]),
                    "notification_type": n["notification_type"],
                    "channel": n["channel"],
                    "recipient": n["recipient"],
                    "status": n["status"],
                    "sent_at": n["sent_at"].isoformat() if n["sent_at"] else None,
                    "delivered_at": n["delivered_at"].isoformat() if n["delivered_at"] else None,
                    "external_id": n["external_id"],
                    "error_message": n["error_message"],
                }
                for n in notifications
            ],
            "handoffs": handoffs,
            "work_orders": work_orders,
            "events": events,
            "pms_feed": pms_feed,
            "workflow": workflow,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Sessions] detail failed")
        raise HTTPException(500, f"Session detail failed: {e}")


@router.get("/threads/{guest_thread_id}")
async def get_guest_thread_timeline(
    guest_thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _scope_profile(request, db, ctx)
    visible_property_codes = scope_profile["visible_property_codes"]

    pre_booking_rows = (
        await db.execute(
            text(
                """
                SELECT
                    'pre_booking' AS item_type,
                    draft_id AS item_id,
                    property_external_id AS property_code,
                    guest_name,
                    message_text AS summary,
                    received_at AS occurred_at,
                    status,
                    thread_id AS thread_ref
                FROM pre_booking_inquiries
                WHERE company_id = CAST(:tid AS uuid)
                  AND guest_thread_id = CAST(:guest_thread_id AS uuid)
                ORDER BY received_at ASC
                """
            ),
            {"tid": ctx["tenant_id"], "guest_thread_id": guest_thread_id},
        )
    ).mappings().all()

    session_rows = (
        await db.execute(
            text(
                """
                SELECT
                    'session' AS item_type,
                    CAST(session_id AS text) AS item_id,
                    property_code,
                    guest_name,
                    CONCAT(property_name, ' · ', phase) AS summary,
                    COALESCE(last_message_at, created_at) AS occurred_at,
                    status,
                    token AS thread_ref
                FROM concierge_guest_sessions
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND guest_thread_id = CAST(:guest_thread_id AS uuid)
                ORDER BY COALESCE(last_message_at, created_at) ASC
                """
            ),
            {"tid": ctx["tenant_id"], "guest_thread_id": guest_thread_id},
        )
    ).mappings().all()

    escalation_rows = (
        await db.execute(
            text(
                """
                SELECT
                    'escalation' AS item_type,
                    ticket_id AS item_id,
                    property_code,
                    guest_name,
                    summary,
                    created_at AS occurred_at,
                    status,
                    session_token AS thread_ref
                FROM concierge_escalations
                WHERE guest_thread_id = CAST(:guest_thread_id AS uuid)
                ORDER BY created_at ASC
                """
            ),
            {"guest_thread_id": guest_thread_id},
        )
    ).mappings().all()

    items = [*pre_booking_rows, *session_rows, *escalation_rows]
    if visible_property_codes is not None:
        items = [item for item in items if (item.get("property_code") or "") in visible_property_codes]
    if not items:
        raise HTTPException(404, "Guest thread not found")

    items.sort(key=lambda item: item.get("occurred_at") or datetime.min)
    primary_guest_name = next((item.get("guest_name") for item in items if item.get("guest_name")), "Guest")
    property_codes = sorted({str(item.get("property_code") or "") for item in items if item.get("property_code")})
    return {
        "guest_thread_id": guest_thread_id,
        "guest_name": primary_guest_name,
        "property_codes": property_codes,
        "timeline": [
            {
                "item_type": item["item_type"],
                "item_id": item["item_id"],
                "property_code": item.get("property_code") or "",
                "guest_name": item.get("guest_name") or primary_guest_name,
                "summary": item.get("summary") or "",
                "status": item.get("status") or "",
                "thread_ref": item.get("thread_ref") or "",
                "occurred_at": item["occurred_at"].isoformat() if item.get("occurred_at") else None,
            }
            for item in items
        ],
    }


@router.get("/booking-context")
async def get_booking_context(
    request: Request,
    session_id: Optional[str] = None,
    reservation_id: Optional[str] = None,
    property_code: Optional[str] = None,
    guest_email: Optional[str] = None,
    guest_phone: Optional[str] = None,
    check_in: Optional[str] = None,
    check_out: Optional[str] = None,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    try:
        adapter = build_booking_context_adapter(
            BookingContextAdapterConfig(company_id=uuid.UUID(ctx["tenant_id"]))
        )
        lookup = BookingContextLookup(
            session_id=session_id,
            reservation_id=reservation_id,
            property_code=property_code,
            guest_email=guest_email,
            guest_phone=guest_phone,
            check_in=date.fromisoformat(check_in) if check_in else None,
            check_out=date.fromisoformat(check_out) if check_out else None,
        )
        return await adapter.lookup(db, lookup)
    except BookingContextBuildError as exc:
        raise HTTPException(400, str(exc))
    except ValueError as exc:
        raise HTTPException(400, f"Invalid booking context parameters: {exc}")
    except Exception as e:
        logger.exception("[BookingContext] lookup failed")
        raise HTTPException(500, f"Booking context lookup failed: {e}")


@router.post("/sessions/{session_id}/send-update")
async def send_session_guest_update(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _scope_profile(request, db, ctx)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    message_text = (body.get("message_text") or "").strip()
    escalation_ticket_id = (body.get("escalation_ticket_id") or "").strip() or None
    if not message_text:
        raise HTTPException(400, "message_text is required")

    sess = (await db.execute(
        text("""
            SELECT session_id, token, guest_phone, guest_name
            FROM concierge_guest_sessions
            WHERE session_id = CAST(:sid AS uuid)
              AND tenant_id = CAST(:tid AS uuid)
              """ + ("AND property_code = ANY(CAST(:visible_property_codes AS text[]))" if scope_profile["visible_property_codes"] is not None else "") + """
            LIMIT 1
        """),
        {
            "sid": session_id,
            "tid": ctx["tenant_id"],
            **({"visible_property_codes": sorted(scope_profile["visible_property_codes"])} if scope_profile["visible_property_codes"] is not None else {}),
        },
    )).mappings().first()
    if not sess:
        raise HTTPException(404, "Session not found")
    if not sess["guest_phone"]:
        raise HTTPException(400, "This session has no guest phone for direct messaging yet")

    try:
        from app.services.messaging.channel_router import get_channel_router, ChannelMessage
        from app.services.concierge.db_session_service import get_db_session_service

        delivery = await get_channel_router().send(
            to=sess["guest_phone"],
            message=ChannelMessage(body=message_text),
            session_id=sess["session_id"],
        )
        if not delivery.success:
            raise HTTPException(502, delivery.error or "Guest message delivery failed")

        tenant_uuid = uuid.UUID(ctx["tenant_id"])
        svc = get_db_session_service(tenant_uuid)
        await svc.add_message(
            db=db,
            session_id=sess["session_id"],
            direction="outbound",
            content=message_text,
            content_type="text",
            detected_intent="operator_guest_update",
        )

        if escalation_ticket_id:
            await db.execute(
                text("""
                    UPDATE concierge_escalations
                    SET guest_update_note = :note,
                        guest_update_status = 'sent_to_guest',
                        guest_updated_at = NOW(),
                        updated_at = NOW()
                    WHERE ticket_id = :ticket_id
                      AND session_token = :token
                """),
                {
                    "ticket_id": escalation_ticket_id,
                    "token": sess["token"],
                    "note": message_text,
                },
            )
            await db.commit()
            await escalation_workflow_service.sync_ticket(db, ctx["tenant_id"], escalation_ticket_id)

        await stay_workflow_service.sync_session(db, ctx["tenant_id"], session_id)

        return {
            "ok": True,
            "channel": str(delivery.channel.value if hasattr(delivery.channel, "value") else delivery.channel),
            "message_sid": delivery.message_sid,
            "sent_at": delivery.sent_at.isoformat() if delivery.sent_at else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[Sessions] send guest update failed")
        raise HTTPException(500, f"Guest update failed: {e}")


@router.get("/sessions/{session_id}/actions")
async def list_session_actions(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    await _ensure_module_enabled(db, ctx["tenant_id"], FeatureFlag.STAY_WORKFLOW_MODULE)
    scope_profile = await _scope_profile(request, db, ctx)
    where = ["s.session_id = CAST(:sid AS uuid)", "s.tenant_id = CAST(:tenant AS uuid)"]
    params = {"sid": session_id, "tenant": ctx["tenant_id"]}
    if scope_profile["visible_property_codes"] is not None:
        where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        params["visible_property_codes"] = sorted(scope_profile["visible_property_codes"])
    owns = (await db.execute(
        text(f"""
            SELECT 1
            FROM concierge_guest_sessions s
            WHERE {' AND '.join(where)}
            LIMIT 1
        """),
        params,
    )).fetchone()
    if not owns:
        raise HTTPException(404, "Session not found")

    await stay_workflow_service.sync_session(db, ctx["tenant_id"], session_id)
    actions = await stay_action_agent.list_actions(db, ctx["tenant_id"], [session_id])
    return {"session_id": session_id, "actions": actions.get(session_id, [])}


@router.post("/sessions/{session_id}/actions/{action_type}/execute")
async def execute_session_action(
    session_id: str,
    action_type: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _scope_profile(request, db, ctx)
    visible_property_codes = scope_profile["visible_property_codes"]
    where = ["s.session_id = CAST(:sid AS uuid)", "s.tenant_id = CAST(:tenant AS uuid)"]
    params = {"sid": session_id, "tenant": ctx["tenant_id"]}
    if visible_property_codes is not None:
        where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        params["visible_property_codes"] = sorted(visible_property_codes)
    owns = (await db.execute(
        text(f"""
            SELECT 1
            FROM concierge_guest_sessions s
            WHERE {' AND '.join(where)}
            LIMIT 1
        """),
        params,
    )).fetchone()
    if not owns:
        raise HTTPException(404, "Session not found")

    normalized_action_type = (action_type or "").strip().lower()
    if normalized_action_type in {"vendor_coordination", "turnover_coordination"}:
        await _enforce_scope_permission(request, db, "manage_vendors", ctx)
    elif normalized_action_type in {"ops_review", "owner_internal_update", "accounting_claim_handoff"}:
        await _enforce_scope_permission(request, db, "assign", ctx)

    try:
        result = await stay_action_agent.execute_action(
            db,
            ctx["tenant_id"],
            session_id,
            normalized_action_type,
            actor_label=ctx.get("email") or ctx.get("operator_id"),
        )
        await db.commit()
        await stay_workflow_service.sync_session(db, ctx["tenant_id"], session_id)
        return {"session_id": session_id, "action_type": normalized_action_type, **result}
    except RuntimeError as exc:
        await _rollback_quietly(db)
        raise HTTPException(400, str(exc))
    except Exception as exc:
        await _rollback_quietly(db)
        logger.exception("[Sessions] execute action failed")
        raise HTTPException(500, f"Session action failed: {exc}")


# ═════════════════════════════════════════════════════════════════════════════
# ESCALATIONS
# ═════════════════════════════════════════════════════════════════════════════
#
# concierge_escalations has no tenant_id column (legacy schema). We scope
# by joining to concierge_guest_sessions on session_token.
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/escalations")
async def list_escalations(
    request: Request,
    status: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_async_session),
):
    started = time.perf_counter()
    ctx = _require_context(request)
    try:
        scope_profile = await _scope_profile(request, db, ctx)
        visible_property_codes = scope_profile["visible_property_codes"]
        columns = await _table_columns(db, "concierge_escalations")
        message_columns = await _table_columns(db, "concierge_messages")
        has_concierge_messages = bool(message_columns)
        watchers_sql = "e.watchers" if "watchers" in columns else "'[]'::jsonb AS watchers"
        watchers_notified_sql = "e.watchers_notified_at" if "watchers_notified_at" in columns else "NULL::timestamptz AS watchers_notified_at"
        vendor_name_sql = "e.vendor_name" if "vendor_name" in columns else "NULL::text AS vendor_name"
        vendor_phone_sql = "e.vendor_phone" if "vendor_phone" in columns else "NULL::text AS vendor_phone"
        vendor_eta_sql = "e.vendor_eta_minutes" if "vendor_eta_minutes" in columns else "NULL::int AS vendor_eta_minutes"
        vendor_status_sql = "e.vendor_status" if "vendor_status" in columns else "NULL::text AS vendor_status"
        guest_updated_sql = "e.guest_updated_at" if "guest_updated_at" in columns else "NULL::timestamptz AS guest_updated_at"
        guest_update_status_sql = "e.guest_update_status" if "guest_update_status" in columns else "NULL::text AS guest_update_status"
        guest_update_due_sql = "e.guest_update_due_at" if "guest_update_due_at" in columns else "NULL::timestamptz AS guest_update_due_at"
        guest_update_note_sql = "e.guest_update_note" if "guest_update_note" in columns else "NULL::text AS guest_update_note"
        latest_outbound_join_sql = """
                LEFT JOIN LATERAL (
                    SELECT m.created_at AS latest_outbound_at,
                           LEFT(COALESCE(m.content, ''), 500) AS latest_outbound_message
                    FROM concierge_messages m
                    WHERE m.session_id = s.session_id
                      AND m.direction = 'outbound'
                    ORDER BY m.created_at DESC
                    LIMIT 1
                ) lm ON TRUE
        """ if has_concierge_messages else """
                LEFT JOIN LATERAL (
                    SELECT NULL::timestamptz AS latest_outbound_at,
                           NULL::text AS latest_outbound_message
                ) lm ON TRUE
        """
        where = ["s.tenant_id = CAST(:tid AS uuid)"]
        params: dict = {"tid": ctx["tenant_id"], "limit": min(limit, 200)}
        if visible_property_codes is not None:
            where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
            params["visible_property_codes"] = sorted(visible_property_codes)
        if status and status != "all":
            where.append("e.status = :status")
            params["status"] = status

        rows = (await db.execute(
            text(f"""
                SELECT e.ticket_id, e.session_token,
                       e.guest_name, e.guest_phone, e.guest_email,
                       e.property_name, e.property_code,
                       e.reason, e.priority, e.status, e.summary, e.last_message,
                       e.assigned_to, e.resolution_notes,
                       e.acknowledged_at, e.resolved_at,
                       {watchers_sql}, {watchers_notified_sql}, {guest_update_note_sql},
                       {vendor_name_sql}, {vendor_phone_sql},
                       {vendor_eta_sql}, {vendor_status_sql}, {guest_updated_sql},
                       {guest_update_status_sql}, {guest_update_due_sql},
                       lm.latest_outbound_at, lm.latest_outbound_message,
                       e.created_at, e.updated_at,
                       s.session_id
                FROM concierge_escalations e
                INNER JOIN concierge_guest_sessions s
                    ON s.token = e.session_token
                {latest_outbound_join_sql}
                WHERE {' AND '.join(where)}
                ORDER BY
                    CASE e.status WHEN 'pending' THEN 0 WHEN 'acknowledged' THEN 1 ELSE 2 END,
                    CASE e.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                    e.created_at DESC
                LIMIT :limit
            """),
            params,
        )).mappings().all()

        items = [{
            "ticket_id":    r["ticket_id"],
            "session_id":   str(r["session_id"]) if r["session_id"] else None,
            "session_token": r["session_token"],
            "guest_name":   r["guest_name"],
            "guest_phone":  r["guest_phone"],
            "guest_email":  r["guest_email"],
            "property_name": r["property_name"],
            "property_code": r["property_code"],
            "reason":       r["reason"],
            "priority":     r["priority"],
            "status":       r["status"],
            "summary":      r["summary"],
            "last_message": r["last_message"],
            "assigned_to":  r["assigned_to"],
            "resolution_notes": r["resolution_notes"],
            "watchers": r["watchers"] or [],
            "watchers_notified_at": r["watchers_notified_at"].isoformat() if r["watchers_notified_at"] else None,
            "guest_update_note": r["guest_update_note"],
            "vendor_name": r["vendor_name"],
            "vendor_phone": r["vendor_phone"],
            "vendor_eta_minutes": int(r["vendor_eta_minutes"]) if r["vendor_eta_minutes"] is not None else None,
            "vendor_status": r["vendor_status"],
            "guest_updated_at": r["guest_updated_at"].isoformat() if r["guest_updated_at"] else None,
            "guest_update_status": r["guest_update_status"],
            "guest_update_due_at": r["guest_update_due_at"].isoformat() if r["guest_update_due_at"] else None,
            "latest_outbound_at": r["latest_outbound_at"].isoformat() if r["latest_outbound_at"] else None,
            "latest_outbound_message": r["latest_outbound_message"],
            "acknowledged_at": r["acknowledged_at"].isoformat() if r["acknowledged_at"] else None,
            "resolved_at":  r["resolved_at"].isoformat() if r["resolved_at"] else None,
            "created_at":   r["created_at"].isoformat() if r["created_at"] else None,
        } for r in rows]
        await escalation_workflow_service.sync_rows(db, ctx["tenant_id"], items)
        workflow_map = await escalation_workflow_service.workflow_map(
            db,
            ctx["tenant_id"],
            [item["ticket_id"] for item in items if item.get("ticket_id")],
        )
        for item in items:
            item["workflow"] = workflow_map.get(item["ticket_id"]) or escalation_workflow_service._build_workflow(item)

        summary_rows = (await db.execute(
            text(f"""
                SELECT e.status, COUNT(*) AS cnt
                FROM concierge_escalations e
                INNER JOIN concierge_guest_sessions s ON s.token = e.session_token
                WHERE s.tenant_id = CAST(:tid AS uuid)
                {"AND s.property_code = ANY(CAST(:visible_property_codes AS text[]))" if visible_property_codes is not None else ""}
                GROUP BY e.status
            """),
            {
                "tid": ctx["tenant_id"],
                **({"visible_property_codes": sorted(visible_property_codes)} if visible_property_codes is not None else {}),
            },
        )).mappings().all()
        summary = {"pending": 0, "acknowledged": 0, "resolved": 0}
        for s in summary_rows:
            key = s["status"] or "pending"
            summary[key] = int(s["cnt"])
        summary["open"] = summary["pending"] + summary["acknowledged"]

        payload = {"escalations": items, "count": len(items), "summary": summary}
        logger.info(
            "[Today] escalations tenant=%s limit=%s status=%s count=%s elapsed_ms=%.1f",
            ctx["tenant_id"],
            min(limit, 200),
            status or "all",
            len(items),
            (time.perf_counter() - started) * 1000,
        )
        return payload
    except Exception as e:
        logger.exception("[Escalations] list failed")
        raise HTTPException(500, f"Escalations list failed: {e}")


@router.post("/escalations/{ticket_id}/assign")
async def assign_escalation(
    ticket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _enforce_scope_permission(request, db, "assign", ctx)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    assigned_to = (body.get("assigned_to") or "").strip()

    # Ownership check (tenant scoping) via session join
    ownership_where = ["e.ticket_id = :tid", "s.tenant_id = CAST(:tenant AS uuid)"]
    ownership_params = {"tid": ticket_id, "tenant": ctx["tenant_id"]}
    visible_property_codes = scope_profile["visible_property_codes"]
    if visible_property_codes is not None:
        ownership_where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        ownership_params["visible_property_codes"] = sorted(visible_property_codes)

    owns = (await db.execute(
        text(f"""
            SELECT 1 FROM concierge_escalations e
            JOIN concierge_guest_sessions s ON s.token = e.session_token
            WHERE {' AND '.join(ownership_where)}
            LIMIT 1
        """),
        ownership_params,
    )).fetchone()
    if not owns:
        raise HTTPException(404, "Escalation not found")

    await db.execute(
        text("""
            UPDATE concierge_escalations
            SET assigned_to = :who, status = 'acknowledged',
                acknowledged_at = COALESCE(acknowledged_at, NOW()),
                updated_at = NOW()
            WHERE ticket_id = :tid
        """),
        {"who": assigned_to, "tid": ticket_id},
    )
    await db.commit()
    await escalation_workflow_service.sync_ticket(db, ctx["tenant_id"], ticket_id)
    return {"ok": True}


@router.post("/escalations/{ticket_id}/coordination")
async def save_escalation_coordination(
    ticket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _scope_profile(request, db, ctx)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    owns_where = ["e.ticket_id = :tid", "s.tenant_id = CAST(:tenant AS uuid)"]
    owns_params = {"tid": ticket_id, "tenant": ctx["tenant_id"]}
    if scope_profile["visible_property_codes"] is not None:
        owns_where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        owns_params["visible_property_codes"] = sorted(scope_profile["visible_property_codes"])
    owns = (await db.execute(
        text(f"""
            SELECT 1 FROM concierge_escalations e
            JOIN concierge_guest_sessions s ON s.token = e.session_token
            WHERE {' AND '.join(owns_where)}
            LIMIT 1
        """),
        owns_params,
    )).fetchone()
    if not owns:
        raise HTTPException(404, "Escalation not found")

    columns = await _table_columns(db, "concierge_escalations")
    required = {
        "watchers",
        "guest_update_note",
        "guest_updated_at",
        "watchers_notified_at",
        "guest_update_status",
        "guest_update_due_at",
    }
    if not required.issubset(columns):
        raise HTTPException(503, "Escalation coordination fields are not available yet")

    raw_watchers = body.get("watchers") or []
    watchers: list[str] = []
    if isinstance(raw_watchers, list):
        watchers = [str(v).strip() for v in raw_watchers if str(v).strip()]
    note = (body.get("guest_update_note") or "").strip()
    mark_updated = bool(body.get("mark_guest_updated"))
    notify_watchers = bool(body.get("notify_watchers"))
    guest_update_status = (body.get("guest_update_status") or "").strip() or None
    guest_update_due_at = (body.get("guest_update_due_at") or "").strip() or None

    await db.execute(
        text("""
            UPDATE concierge_escalations
            SET watchers = CAST(:watchers AS jsonb),
                guest_update_note = :guest_update_note,
                guest_update_status = :guest_update_status,
                guest_update_due_at = CAST(:guest_update_due_at AS timestamptz),
                guest_updated_at = CASE
                    WHEN :mark_guest_updated THEN NOW()
                    ELSE guest_updated_at
                END,
                watchers_notified_at = CASE
                    WHEN :notify_watchers AND :has_watchers THEN NOW()
                    ELSE watchers_notified_at
                END,
                updated_at = NOW()
            WHERE ticket_id = :tid
        """),
        {
            "tid": ticket_id,
            "watchers": json.dumps(watchers),
            "guest_update_note": note or None,
            "guest_update_status": guest_update_status,
            "guest_update_due_at": guest_update_due_at,
            "mark_guest_updated": mark_updated,
            "notify_watchers": notify_watchers if "watchers_notified_at" in columns else False,
            "has_watchers": bool(watchers),
        },
    )
    if notify_watchers and watchers:
        notif_columns = await _table_columns(db, "operator_notifications")
        recipient_enabled = "recipient_user_id" in notif_columns
        recipient_rows = (await db.execute(
            text("""
                SELECT CAST(id AS text) AS user_id, LOWER(email) AS email_key, LOWER(name) AS name_key
                FROM operator_team_members
                WHERE tenant_id = CAST(:tid AS uuid)
                UNION ALL
                SELECT CAST(id AS text) AS user_id, LOWER(email) AS email_key, LOWER(owner_name) AS name_key
                FROM operator_accounts
                WHERE tenant_id = CAST(:tid AS uuid)
            """),
            {"tid": ctx["tenant_id"]},
        )).mappings().all()
        recipient_map: dict[str, str] = {}
        for row in recipient_rows:
            if row["email_key"]:
                recipient_map[str(row["email_key"]).strip()] = row["user_id"]
            if row["name_key"]:
                recipient_map[str(row["name_key"]).strip()] = row["user_id"]

        matched_ids: list[str] = []
        unmatched_labels: list[str] = []
        for watcher in watchers:
            key = watcher.strip().lower()
            recipient_id = recipient_map.get(key)
            if recipient_id and recipient_id not in matched_ids:
                matched_ids.append(recipient_id)
            elif not recipient_id:
                unmatched_labels.append(watcher)

        title = f"Escalation update shared with {', '.join(watchers[:2])}" + ("…" if len(watchers) > 2 else "")
        body_text = f"Ticket {ticket_id} was shared with watchers: {', '.join(watchers)}." + (f" Guest update: {note}" if note else "")

        if recipient_enabled and matched_ids:
            for recipient_id in matched_ids:
                await db.execute(
                    text("""
                        INSERT INTO operator_notifications
                            (tenant_id, recipient_user_id, kind, severity, title, body, link_target, link_label)
                        VALUES
                            (CAST(:tid AS uuid), CAST(:recipient_user_id AS uuid),
                             'escalation_watchers', 'info', :title, :body, 'escalations', 'Open escalation')
                    """),
                    {
                        "tid": ctx["tenant_id"],
                        "recipient_user_id": recipient_id,
                        "title": title,
                        "body": body_text,
                    },
                )
    if (not recipient_enabled) or unmatched_labels or not matched_ids:
            suffix = f" Unmatched watchers: {', '.join(unmatched_labels)}." if unmatched_labels else ""
            await db.execute(
                text("""
                    INSERT INTO operator_notifications
                        (tenant_id, kind, severity, title, body, link_target, link_label)
                    VALUES
                        (CAST(:tid AS uuid), 'escalation_watchers', 'info',
                         :title, :body, 'escalations', 'Open escalation')
                """),
                {
                    "tid": ctx["tenant_id"],
                    "title": title,
                    "body": body_text + suffix,
                },
            )
    await db.commit()
    await escalation_workflow_service.sync_ticket(db, ctx["tenant_id"], ticket_id)
    return {"ok": True}


@router.post("/escalations/{ticket_id}/resolve")
async def resolve_escalation(
    ticket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _scope_profile(request, db, ctx)
    try:
        body = await request.json()
    except Exception:
        body = {}
    notes = (body.get("notes") or "").strip()

    owns_where = ["e.ticket_id = :tid", "s.tenant_id = CAST(:tenant AS uuid)"]
    owns_params = {"tid": ticket_id, "tenant": ctx["tenant_id"]}
    if scope_profile["visible_property_codes"] is not None:
        owns_where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        owns_params["visible_property_codes"] = sorted(scope_profile["visible_property_codes"])
    owns = (await db.execute(
        text(f"""
            SELECT 1 FROM concierge_escalations e
            JOIN concierge_guest_sessions s ON s.token = e.session_token
            WHERE {' AND '.join(owns_where)}
            LIMIT 1
        """),
        owns_params,
    )).fetchone()
    if not owns:
        raise HTTPException(404, "Escalation not found")

    await db.execute(
        text("""
            UPDATE concierge_escalations
            SET status = 'resolved',
                resolution_notes = :notes,
                resolved_at = NOW(),
                updated_at = NOW()
            WHERE ticket_id = :tid
        """),
        {"tid": ticket_id, "notes": notes or "Resolved by operator"},
    )
    await db.commit()
    await escalation_workflow_service.sync_ticket(db, ctx["tenant_id"], ticket_id)
    return {"ok": True}


@router.post("/escalations/{ticket_id}/dispatch-vendor")
async def dispatch_vendor_for_escalation(
    ticket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _enforce_scope_permission(request, db, "manage_vendors", ctx)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    owns_where = ["e.ticket_id = :tid", "s.tenant_id = CAST(:tenant AS uuid)"]
    owns_params = {"tid": ticket_id, "tenant": ctx["tenant_id"]}
    if scope_profile["visible_property_codes"] is not None:
        owns_where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        owns_params["visible_property_codes"] = sorted(scope_profile["visible_property_codes"])
    owns = (await db.execute(
        text(f"""
            SELECT 1 FROM concierge_escalations e
            JOIN concierge_guest_sessions s ON s.token = e.session_token
            WHERE {' AND '.join(owns_where)}
            LIMIT 1
        """),
        owns_params,
    )).fetchone()
    if not owns:
        raise HTTPException(404, "Escalation not found")

    columns = await _table_columns(db, "concierge_escalations")
    required = {"vendor_name", "vendor_phone", "vendor_eta_minutes", "vendor_status", "guest_updated_at"}
    if not required.issubset(columns):
        raise HTTPException(503, "Escalation dispatch fields are not available yet")

    vendor_status = (body.get("vendor_status") or "contacted").strip().lower()
    allowed_statuses = {"recommended", "contacted", "dispatched", "scheduled", "en_route", "on_site", "completed", "failed", "reassigned", "cancelled"}
    if vendor_status not in allowed_statuses:
        raise HTTPException(400, "Invalid vendor_status")

    replace_existing = bool(body.get("replace_existing"))
    existing_vendor = (
        await db.execute(
            text("SELECT vendor_name, vendor_status FROM concierge_escalations WHERE ticket_id = :tid LIMIT 1"),
            {"tid": ticket_id},
        )
    ).mappings().first()
    previous_vendor_name = existing_vendor.get("vendor_name") if existing_vendor else None
    if existing_vendor and existing_vendor.get("vendor_name") and not replace_existing and vendor_status not in {"completed", "failed", "cancelled"}:
        raise HTTPException(409, "A vendor is already assigned. Set replace_existing=true to replace them.")

    await db.execute(
        text("""
            UPDATE concierge_escalations
            SET vendor_name = :vendor_name,
                vendor_phone = :vendor_phone,
                vendor_eta_minutes = :vendor_eta_minutes,
                vendor_status = :vendor_status,
                guest_updated_at = CASE
                    WHEN :guest_updated THEN NOW()
                    ELSE guest_updated_at
                END,
                updated_at = NOW()
            WHERE ticket_id = :tid
        """),
        {
            "tid": ticket_id,
            "vendor_name": (body.get("vendor_name") or "").strip() or None,
            "vendor_phone": (body.get("vendor_phone") or "").strip() or None,
            "vendor_eta_minutes": body.get("vendor_eta_minutes"),
            "vendor_status": vendor_status,
            "guest_updated": bool(body.get("guest_updated")),
        },
    )
    await db.commit()
    await escalation_workflow_service.sync_ticket(db, ctx["tenant_id"], ticket_id)
    await escalation_workflow_service.record_vendor_transition(
        db,
        ctx["tenant_id"],
        ticket_id,
        {
            "changed_at": datetime.utcnow().isoformat(),
            "changed_by": ctx.get("email") or ctx.get("operator_id"),
            "vendor_name": (body.get("vendor_name") or "").strip() or None,
            "vendor_phone": (body.get("vendor_phone") or "").strip() or None,
            "vendor_eta_minutes": body.get("vendor_eta_minutes"),
            "vendor_status": vendor_status,
            "replace_existing": replace_existing,
            "previous_vendor_name": previous_vendor_name if replace_existing else None,
            "note": (body.get("note") or "").strip() or None,
        },
    )
    await db.commit()
    return {"ok": True}


@router.post("/sessions/{session_id}/dispatch-vendor")
async def dispatch_vendor_for_session(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _enforce_scope_permission(request, db, "manage_vendors", ctx)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    where = ["s.session_id = CAST(:sid AS uuid)", "s.tenant_id = CAST(:tenant AS uuid)"]
    params = {"sid": session_id, "tenant": ctx["tenant_id"]}
    if scope_profile["visible_property_codes"] is not None:
        where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        params["visible_property_codes"] = sorted(scope_profile["visible_property_codes"])
    session_row = (
        await db.execute(
            text(
                f"""
                SELECT s.session_id, s.property_code, s.phase
                FROM concierge_guest_sessions s
                WHERE {' AND '.join(where)}
                LIMIT 1
                """
            ),
            params,
        )
    ).mappings().first()
    if not session_row:
        raise HTTPException(404, "Session not found")

    vendor_status = (body.get("vendor_status") or "contacted").strip().lower()
    allowed_statuses = {"recommended", "contacted", "dispatched", "scheduled", "en_route", "on_site", "completed", "failed", "reassigned", "cancelled"}
    if vendor_status not in allowed_statuses:
        raise HTTPException(400, "Invalid vendor_status")

    workflow_map = await stay_workflow_service.workflow_map(db, ctx["tenant_id"], [session_id])
    workflow = workflow_map.get(session_id) or {}
    current_vendor = workflow.get("vendor") if isinstance(workflow.get("vendor"), dict) else {}
    replace_existing = bool(body.get("replace_existing"))
    if current_vendor.get("name") and not replace_existing and vendor_status not in {"completed", "failed", "cancelled"}:
        raise HTTPException(409, "A vendor is already assigned. Set replace_existing=true to replace them.")
    previous_vendor_name = current_vendor.get("name") if replace_existing else None

    vendor_patch = {
        "selected_vendor_id": body.get("vendor_id"),
        "name": (body.get("vendor_name") or "").strip() or None,
        "phone": (body.get("vendor_phone") or "").strip() or None,
        "category_slug": (body.get("category_slug") or "").strip() or None,
        "dispatch_state": vendor_status,
        "eta_minutes": body.get("vendor_eta_minutes"),
        "selected_at": current_vendor.get("selected_at") if current_vendor.get("name") and not replace_existing else datetime.utcnow().isoformat(),
        "last_updated_at": datetime.utcnow().isoformat(),
    }
    if previous_vendor_name:
        vendor_patch["previous_vendor_name"] = previous_vendor_name

    guest_update_patch = None
    if body.get("guest_updated"):
        guest_update_patch = {
            "status": "sent_to_guest",
            "updated_at": datetime.utcnow().isoformat(),
            "note": "Vendor dispatch update acknowledged in operator flow",
        }

    await stay_action_agent.update_dispatch_state(
        db,
        ctx["tenant_id"],
        session_id,
        vendor_patch=vendor_patch,
        guest_update_patch=guest_update_patch,
        vendor_event={
            "changed_at": datetime.utcnow().isoformat(),
            "changed_by": ctx.get("email") or ctx.get("operator_id"),
            "vendor_name": vendor_patch.get("name"),
            "vendor_phone": vendor_patch.get("phone"),
            "vendor_eta_minutes": vendor_patch.get("eta_minutes"),
            "eta_visibility_mode": (body.get("eta_visibility_mode") or "estimated").strip().lower(),
            "tracking_url": (body.get("tracking_url") or "").strip() or None,
            "last_known_distance_text": (body.get("last_known_distance_text") or "").strip() or None,
            "asset_id": body.get("asset_id"),
            "vendor_status": vendor_status,
            "replace_existing": replace_existing,
            "previous_vendor_name": previous_vendor_name,
            "note": (body.get("note") or "").strip() or None,
        },
    )
    category_slug = str(body.get("category_slug") or "").strip().lower()
    is_turnover_vendor = category_slug in {"cleaning", "housekeeping", "linen", "laundry"}
    phase_value = str(session_row.get("phase") or "").strip().lower()
    if is_turnover_vendor and phase_value in {"departure_day", "post_stay"}:
        turnover_patch = {
            "updated_at": datetime.utcnow().isoformat(),
            "updated_by": ctx.get("email") or ctx.get("operator_id") or "operator",
            "assigned_vendor_id": body.get("vendor_id"),
            "assigned_vendor_name": vendor_patch.get("name"),
            "note": (body.get("note") or "").strip() or None,
        }
        if vendor_status in {"recommended", "contacted", "dispatched", "scheduled", "en_route", "on_site"}:
            turnover_patch["status"] = "in_progress"
            turnover_patch["started_at"] = datetime.utcnow().isoformat()
        elif vendor_status == "completed":
            turnover_patch["status"] = "ready"
            turnover_patch["ready_at"] = datetime.utcnow().isoformat()
            turnover_patch["archived_at"] = datetime.utcnow().isoformat()
        elif vendor_status in {"failed", "reassigned", "cancelled"}:
            turnover_patch["status"] = vendor_status
        await stay_action_agent.update_turnover_state(
            db,
            ctx["tenant_id"],
            session_id,
            turnover_patch=turnover_patch,
        )
    await db.commit()
    await stay_workflow_service.sync_session(db, ctx["tenant_id"], session_id)
    return {"ok": True}


@router.post("/sessions/{session_id}/turnover-status")
async def update_session_turnover_status(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _enforce_scope_permission(request, db, "manage_vendors", ctx)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    where = ["s.session_id = CAST(:sid AS uuid)", "s.tenant_id = CAST(:tenant AS uuid)"]
    params = {"sid": session_id, "tenant": ctx["tenant_id"]}
    if scope_profile["visible_property_codes"] is not None:
        where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        params["visible_property_codes"] = sorted(scope_profile["visible_property_codes"])
    session_row = (
        await db.execute(
            text(
                f"""
                SELECT s.session_id, s.property_code
                FROM concierge_guest_sessions s
                WHERE {' AND '.join(where)}
                LIMIT 1
                """
            ),
            params,
        )
    ).mappings().first()
    if not session_row:
        raise HTTPException(404, "Session not found")

    turnover_status = (body.get("status") or "").strip().lower()
    allowed_statuses = {"planned", "pending", "in_progress", "ready", "reassigned", "failed", "cancelled"}
    if turnover_status not in allowed_statuses:
        raise HTTPException(400, "Invalid turnover status")

    now_iso = datetime.utcnow().isoformat()
    turnover_patch = {
        "status": turnover_status,
        "updated_at": now_iso,
        "updated_by": ctx.get("email") or ctx.get("operator_id") or "operator",
        "note": (body.get("note") or "").strip() or None,
    }
    if turnover_status == "in_progress":
        turnover_patch["started_at"] = now_iso
    if turnover_status == "ready":
        turnover_patch["ready_at"] = now_iso
        turnover_patch["archived_at"] = now_iso

    await stay_action_agent.update_turnover_state(
        db,
        ctx["tenant_id"],
        session_id,
        turnover_patch=turnover_patch,
    )
    await db.commit()
    await stay_workflow_service.sync_session(db, ctx["tenant_id"], session_id)
    workflow_map = await stay_workflow_service.workflow_map(db, ctx["tenant_id"], [session_id])
    return {"ok": True, "workflow": workflow_map.get(session_id, {})}


@router.get("/sessions/{session_id}/events")
async def session_events(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _scope_profile(request, db, ctx)
    where = ["s.session_id = CAST(:sid AS uuid)", "s.tenant_id = CAST(:tenant AS uuid)"]
    params = {"sid": session_id, "tenant": ctx["tenant_id"]}
    if scope_profile["visible_property_codes"] is not None:
        where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        params["visible_property_codes"] = sorted(scope_profile["visible_property_codes"])
    exists = (
        await db.execute(
            text(
                f"""
                SELECT 1
                FROM concierge_guest_sessions s
                WHERE {' AND '.join(where)}
                LIMIT 1
                """
            ),
            params,
        )
    ).first()
    if not exists:
        raise HTTPException(404, "Session not found")
    events = await stay_event_service.list_events(db, ctx["tenant_id"], session_id, limit=40)
    return {"events": events, "count": len(events)}


@router.post("/sessions/{session_id}/events")
async def record_session_event(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _enforce_scope_permission(request, db, "manage_vendors", ctx)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    where = ["s.session_id = CAST(:sid AS uuid)", "s.tenant_id = CAST(:tenant AS uuid)"]
    params = {"sid": session_id, "tenant": ctx["tenant_id"]}
    if scope_profile["visible_property_codes"] is not None:
        where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        params["visible_property_codes"] = sorted(scope_profile["visible_property_codes"])
    session_row = (
        await db.execute(
            text(
                f"""
                SELECT CAST(s.session_id AS text) AS session_id,
                       s.token,
                       s.property_code
                FROM concierge_guest_sessions s
                WHERE {' AND '.join(where)}
                LIMIT 1
                """
            ),
            params,
        )
    ).mappings().first()
    if not session_row:
        raise HTTPException(404, "Session not found")

    event_type = (body.get("event_type") or "").strip().lower()
    allowed_event_types = {
        "guest_checked_out",
        "housekeeping_arrived",
        "housekeeping_completed",
        "feedback_requested",
        "linen_pickup_started",
        "linen_returned",
        "property_ready",
        "documentation_started",
        "documentation_completed",
        "walkthrough_started",
        "walkthrough_completed",
        "vendor_arrived",
        "vendor_completed",
    }
    if event_type not in allowed_event_types:
        raise HTTPException(400, "Invalid event type")

    event = await stay_event_service.record_event(
        db,
        ctx["tenant_id"],
        session_id=session_id,
        session_token=session_row.get("token"),
        property_code=session_row.get("property_code"),
        event_type=event_type,
        status=(body.get("status") or "completed"),
        source=(body.get("source") or "operator"),
        note=body.get("note"),
        payload=body.get("payload") if isinstance(body.get("payload"), dict) else {},
        occurred_at=body.get("occurred_at"),
        created_by=ctx.get("email") or ctx.get("operator_id") or "operator",
    )
    await db.commit()
    await stay_workflow_service.sync_session(db, ctx["tenant_id"], session_id)
    workflow_map = await stay_workflow_service.workflow_map(db, ctx["tenant_id"], [session_id])
    events = await stay_event_service.list_events(db, ctx["tenant_id"], session_id, limit=40)
    return {"ok": True, "event": event, "events": events, "workflow": workflow_map.get(session_id, {})}


@router.post("/sessions/{session_id}/request-feedback")
async def request_session_feedback(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _scope_profile(request, db, ctx)
    where = ["s.session_id = CAST(:sid AS uuid)", "s.tenant_id = CAST(:tenant AS uuid)"]
    params = {"sid": session_id, "tenant": ctx["tenant_id"]}
    if scope_profile["visible_property_codes"] is not None:
        where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        params["visible_property_codes"] = sorted(scope_profile["visible_property_codes"])
    session_row = (
        await db.execute(
            text(
                f"""
                SELECT CAST(s.session_id AS text) AS session_id,
                       s.token,
                       s.property_code,
                       s.property_name,
                       s.guest_name,
                       s.phase,
                       s.feedback_rating
                FROM concierge_guest_sessions s
                WHERE {' AND '.join(where)}
                LIMIT 1
                """
            ),
            params,
        )
    ).mappings().first()
    if not session_row:
        raise HTTPException(404, "Session not found")
    if session_row.get("feedback_rating"):
        raise HTTPException(400, "Feedback already recorded")
    if session_row.get("phase") not in {"departure_day", "post_stay"}:
        raise HTTPException(400, "Feedback requests are only available after the stay")

    first_name = (session_row.get("guest_name") or "there").split()[0]
    suggested_message = (
        f"Hi {first_name}, thank you again for staying with us at {session_row.get('property_name')}. "
        "We'd love to hear how your stay went if you have a moment to share feedback."
    )
    event = await stay_event_service.record_event(
        db,
        ctx["tenant_id"],
        session_id=session_id,
        session_token=session_row.get("token"),
        property_code=session_row.get("property_code"),
        event_type="feedback_requested",
        status="completed",
        source="operator",
        note="Operator triggered post-stay feedback request",
        payload={"suggested_message": suggested_message},
        created_by=ctx.get("email") or ctx.get("operator_id") or "operator",
    )
    await db.commit()
    if await _module_enabled(db, ctx["tenant_id"], FeatureFlag.STAY_WORKFLOW_MODULE):
        await stay_workflow_service.sync_session(db, ctx["tenant_id"], session_id)
    return {
        "ok": True,
        "event": event,
        "suggested_message": suggested_message,
    }


@router.get("/sessions/{session_id}/pms-feed")
async def session_pms_feed(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    await _ensure_module_enabled(db, ctx["tenant_id"], FeatureFlag.STAY_WORKFLOW_MODULE)
    scope_profile = await _scope_profile(request, db, ctx)
    where = ["s.session_id = CAST(:sid AS uuid)", "s.tenant_id = CAST(:tenant AS uuid)"]
    params = {"sid": session_id, "tenant": ctx["tenant_id"]}
    if scope_profile["visible_property_codes"] is not None:
        where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        params["visible_property_codes"] = sorted(scope_profile["visible_property_codes"])
    session_row = (
        await db.execute(
            text(
                f"""
                SELECT CAST(s.session_id AS text) AS session_id,
                       s.reservation_id,
                       s.property_code,
                       s.property_name,
                       s.check_in,
                       s.check_out
                FROM concierge_guest_sessions s
                WHERE {' AND '.join(where)}
                LIMIT 1
                """
            ),
            params,
        )
    ).mappings().first()
    if not session_row:
        raise HTTPException(404, "Session not found")
    feed = await stay_pms_feed_service.load_feed(
        db,
        ctx["tenant_id"],
        reservation_id=session_row.get("reservation_id"),
        property_code=session_row.get("property_code"),
        property_name=session_row.get("property_name"),
        check_in=session_row.get("check_in"),
        check_out=session_row.get("check_out"),
    )
    return {"pms_feed": feed}


@router.post("/sessions/{session_id}/events/import-pms")
async def import_session_pms_event(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    await _ensure_module_enabled(db, ctx["tenant_id"], FeatureFlag.STAY_WORKFLOW_MODULE)
    scope_profile = await _enforce_scope_permission(request, db, "manage_vendors", ctx)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    where = ["s.session_id = CAST(:sid AS uuid)", "s.tenant_id = CAST(:tenant AS uuid)"]
    params = {"sid": session_id, "tenant": ctx["tenant_id"]}
    if scope_profile["visible_property_codes"] is not None:
        where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        params["visible_property_codes"] = sorted(scope_profile["visible_property_codes"])
    session_row = (
        await db.execute(
            text(
                f"""
                SELECT CAST(s.session_id AS text) AS session_id,
                       s.token,
                       s.property_code
                FROM concierge_guest_sessions s
                WHERE {' AND '.join(where)}
                LIMIT 1
                """
            ),
            params,
        )
    ).mappings().first()
    if not session_row:
        raise HTTPException(404, "Session not found")

    provider = (body.get("provider") or "").strip().lower() or "unknown"
    provider_event_type = (body.get("event_type") or "").strip().lower()
    if not provider_event_type:
        raise HTTPException(400, "Missing event_type")

    normalized = stay_pms_feed_service.normalize_pms_event(
        provider,
        provider_event_type,
        note=body.get("note"),
        payload=body.get("payload") if isinstance(body.get("payload"), dict) else {},
    )
    event = await stay_event_service.record_event(
        db,
        ctx["tenant_id"],
        session_id=session_id,
        session_token=session_row.get("token"),
        property_code=session_row.get("property_code"),
        event_type=normalized["event_type"],
        status=(body.get("status") or "completed"),
        source=normalized["source"],
        note=normalized.get("note"),
        payload=normalized.get("payload"),
        occurred_at=body.get("occurred_at"),
        created_by=ctx.get("email") or ctx.get("operator_id") or "operator",
    )
    await db.commit()
    await stay_workflow_service.sync_session(db, ctx["tenant_id"], session_id)
    workflow_map = await stay_workflow_service.workflow_map(db, ctx["tenant_id"], [session_id])
    return {"ok": True, "event": event, "workflow": workflow_map.get(session_id, {})}


@router.get("/sessions/{session_id}/handoffs")
async def session_handoffs(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    await _ensure_module_enabled(db, ctx["tenant_id"], FeatureFlag.HANDOFFS_MODULE)
    scope_profile = await _scope_profile(request, db, ctx)
    where = ["s.session_id = CAST(:sid AS uuid)", "s.tenant_id = CAST(:tenant AS uuid)"]
    params = {"sid": session_id, "tenant": ctx["tenant_id"]}
    if scope_profile["visible_property_codes"] is not None:
        where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        params["visible_property_codes"] = sorted(scope_profile["visible_property_codes"])
    exists = (
        await db.execute(
            text(
                f"""
                SELECT 1
                FROM concierge_guest_sessions s
                WHERE {' AND '.join(where)}
                LIMIT 1
                """
            ),
            params,
        )
    ).fetchone()
    if not exists:
        raise HTTPException(404, "Session not found")
    handoffs = (
        await handoff_service.list_handoffs(
            db,
            ctx["tenant_id"],
            workflow_type="stay",
            workflow_refs=[session_id],
        )
    ).get(session_id, [])
    return {"session_id": session_id, "handoffs": handoffs}


@router.get("/sessions/{session_id}/work-orders")
async def session_work_orders(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    await _ensure_module_enabled(db, ctx["tenant_id"], FeatureFlag.WORK_ORDERS_MODULE)
    scope_profile = await _scope_profile(request, db, ctx)
    where = ["s.session_id = CAST(:sid AS uuid)", "s.tenant_id = CAST(:tenant AS uuid)"]
    params = {"sid": session_id, "tenant": ctx["tenant_id"]}
    if scope_profile["visible_property_codes"] is not None:
        where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        params["visible_property_codes"] = sorted(scope_profile["visible_property_codes"])
    exists = (
        await db.execute(
            text(
                f"""
                SELECT 1
                FROM concierge_guest_sessions s
                WHERE {' AND '.join(where)}
                LIMIT 1
                """
            ),
            params,
        )
    ).fetchone()
    if not exists:
        raise HTTPException(404, "Session not found")
    work_orders = (
        await work_order_service.list_work_orders(
            db,
            ctx["tenant_id"],
            workflow_type="stay",
            workflow_refs=[session_id],
        )
    ).get(session_id, [])
    return {"session_id": session_id, "work_orders": work_orders}


@router.get("/escalations/{ticket_id}/handoffs")
async def escalation_handoffs(
    ticket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    await _ensure_module_enabled(db, ctx["tenant_id"], FeatureFlag.HANDOFFS_MODULE)
    scope_profile = await _scope_profile(request, db, ctx)
    where = ["e.ticket_id = :tid", "s.tenant_id = CAST(:tenant AS uuid)"]
    params = {"tid": ticket_id, "tenant": ctx["tenant_id"]}
    if scope_profile["visible_property_codes"] is not None:
        where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        params["visible_property_codes"] = sorted(scope_profile["visible_property_codes"])
    exists = (
        await db.execute(
            text(
                f"""
                SELECT 1
                FROM concierge_escalations e
                JOIN concierge_guest_sessions s ON s.token = e.session_token
                WHERE {' AND '.join(where)}
                LIMIT 1
                """
            ),
            params,
        )
    ).fetchone()
    if not exists:
        raise HTTPException(404, "Escalation not found")
    handoffs = (
        await handoff_service.list_handoffs(
            db,
            ctx["tenant_id"],
            workflow_type="escalation",
            workflow_refs=[ticket_id],
        )
    ).get(ticket_id, [])
    return {"ticket_id": ticket_id, "handoffs": handoffs}


@router.get("/escalations/{ticket_id}/work-orders")
async def escalation_work_orders(
    ticket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    await _ensure_module_enabled(db, ctx["tenant_id"], FeatureFlag.WORK_ORDERS_MODULE)
    scope_profile = await _scope_profile(request, db, ctx)
    where = ["e.ticket_id = :tid", "s.tenant_id = CAST(:tenant AS uuid)"]
    params = {"tid": ticket_id, "tenant": ctx["tenant_id"]}
    if scope_profile["visible_property_codes"] is not None:
        where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        params["visible_property_codes"] = sorted(scope_profile["visible_property_codes"])
    exists = (
        await db.execute(
            text(
                f"""
                SELECT 1
                FROM concierge_escalations e
                JOIN concierge_guest_sessions s ON s.token = e.session_token
                WHERE {' AND '.join(where)}
                LIMIT 1
                """
            ),
            params,
        )
    ).fetchone()
    if not exists:
        raise HTTPException(404, "Escalation not found")
    work_orders = (
        await work_order_service.list_work_orders(
            db,
            ctx["tenant_id"],
            workflow_type="escalation",
            workflow_refs=[ticket_id],
        )
    ).get(ticket_id, [])
    return {"ticket_id": ticket_id, "work_orders": work_orders}


@router.post("/handoffs/{handoff_id}/status")
async def update_workflow_handoff_status(
    handoff_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    await _ensure_module_enabled(db, ctx["tenant_id"], FeatureFlag.HANDOFFS_MODULE)
    await _enforce_scope_permission(request, db, "assign", ctx)
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        handoff = await handoff_service.get_handoff(db, ctx["tenant_id"], handoff_id)
        if not handoff:
            raise HTTPException(404, "Handoff not found")
        await handoff_service.update_handoff(
            db,
            ctx["tenant_id"],
            handoff_id,
            status=body.get("status"),
            assignee_user_id=body.get("assignee_user_id"),
            assignee_label=body.get("assignee_label"),
            resolution={
                "updated_by": ctx.get("email") or ctx.get("operator_id"),
                "note": (body.get("note") or "").strip() or None,
            } if body.get("note") or body.get("status") in {"completed", "cancelled"} else None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await db.commit()
    if handoff.get("workflow_type") == "stay":
        await stay_workflow_service.sync_session(db, ctx["tenant_id"], str(handoff.get("workflow_ref") or ""))
    elif handoff.get("workflow_type") == "escalation":
        await escalation_workflow_service.sync_ticket(db, ctx["tenant_id"], str(handoff.get("workflow_ref") or ""))
    return {"ok": True, "handoff_id": handoff_id}


@router.post("/work-orders/{work_order_id}/status")
async def update_work_order_status(
    work_order_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    await _ensure_module_enabled(db, ctx["tenant_id"], FeatureFlag.WORK_ORDERS_MODULE)
    await _enforce_scope_permission(request, db, "assign", ctx)
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        work_order = await work_order_service.get_work_order(db, ctx["tenant_id"], work_order_id)
        if not work_order:
            raise HTTPException(404, "Work order not found")
        await work_order_service.update_work_order(
            db,
            ctx["tenant_id"],
            work_order_id,
            status=body.get("status"),
            dispatch_state=body.get("dispatch_state"),
            verification_state=body.get("verification_state"),
            invoice_state=body.get("invoice_state"),
            invoice_amount=body.get("invoice_amount"),
            invoice_reference=body.get("invoice_reference"),
            eta_minutes=body.get("eta_minutes"),
            last_actor_label=ctx.get("email") or ctx.get("operator_id"),
            resolution={
                "updated_by": ctx.get("email") or ctx.get("operator_id"),
                "note": (body.get("note") or "").strip() or None,
            } if body.get("note") or body.get("status") or body.get("verification_state") or body.get("invoice_state") else None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await db.commit()
    if work_order.get("workflow_type") == "stay":
        await stay_workflow_service.sync_session(db, ctx["tenant_id"], str(work_order.get("workflow_ref") or ""))
    elif work_order.get("workflow_type") == "escalation":
        await escalation_workflow_service.sync_ticket(db, ctx["tenant_id"], str(work_order.get("workflow_ref") or ""))
    return {"ok": True, "work_order_id": work_order_id}


@router.get("/properties/{property_code}/assets")
async def property_assets(
    property_code: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    await _ensure_module_enabled(db, ctx["tenant_id"], FeatureFlag.PROPERTY_ASSETS_MODULE)
    scope_profile = await _scope_profile(request, db, ctx)
    visible = scope_profile["visible_property_codes"]
    if visible is not None and property_code not in visible:
        raise HTTPException(404, "Property not found")
    items = await property_asset_service.list_assets(db, ctx["tenant_id"], property_code)
    return {"property_code": property_code, "assets": items, "count": len(items)}


@router.post("/properties/{property_code}/assets")
async def upsert_property_asset(
    property_code: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    await _ensure_module_enabled(db, ctx["tenant_id"], FeatureFlag.PROPERTY_ASSETS_MODULE)
    await _enforce_scope_permission(request, db, "manage_vendors", ctx)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    asset = await property_asset_service.upsert_asset(
        db,
        ctx["tenant_id"],
        property_code=property_code,
        asset_id=body.get("asset_id"),
        asset_type=(body.get("asset_type") or "").strip().lower(),
        asset_name=(body.get("asset_name") or "").strip(),
        manufacturer=(body.get("manufacturer") or "").strip() or None,
        model_number=(body.get("model_number") or "").strip() or None,
        serial_number=(body.get("serial_number") or "").strip() or None,
        install_vendor_id=body.get("install_vendor_id"),
        install_vendor_name=(body.get("install_vendor_name") or "").strip() or None,
        install_date=body.get("install_date"),
        warranty_scope=(body.get("warranty_scope") or "none").strip().lower(),
        warranty_provider=(body.get("warranty_provider") or "").strip() or None,
        warranty_start_date=body.get("warranty_start_date"),
        warranty_end_date=body.get("warranty_end_date"),
        parts_warranty_end_date=body.get("parts_warranty_end_date"),
        labor_warranty_end_date=body.get("labor_warranty_end_date"),
        status=(body.get("status") or "active").strip().lower(),
        condition_state=(body.get("condition_state") or "good").strip().lower(),
        useful_life_years=body.get("useful_life_years"),
        last_service_at=body.get("last_service_at"),
        last_work_order_id=body.get("last_work_order_id"),
        notes=(body.get("notes") or "").strip(),
        metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else {},
    )
    await db.commit()
    return {"ok": True, **asset}


@router.get("/escalations/{ticket_id}/actions")
async def escalation_actions(
    ticket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _scope_profile(request, db, ctx)
    where = ["e.ticket_id = :tid", "s.tenant_id = CAST(:tenant AS uuid)"]
    params = {"tid": ticket_id, "tenant": ctx["tenant_id"]}
    if scope_profile["visible_property_codes"] is not None:
        where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        params["visible_property_codes"] = sorted(scope_profile["visible_property_codes"])
    owns = (await db.execute(
        text(f"""
            SELECT 1
            FROM concierge_escalations e
            JOIN concierge_guest_sessions s ON s.token = e.session_token
            WHERE {' AND '.join(where)}
            LIMIT 1
        """),
        params,
    )).fetchone()
    if not owns:
        raise HTTPException(404, "Escalation not found")

    actions = await escalation_action_agent.list_actions(db, ctx["tenant_id"], [ticket_id])
    return {"ticket_id": ticket_id, "actions": actions.get(ticket_id, [])}


@router.post("/escalations/{ticket_id}/actions/{action_type}/execute")
async def execute_escalation_action(
    ticket_id: str,
    action_type: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _scope_profile(request, db, ctx)
    visible_property_codes = scope_profile["visible_property_codes"]
    where = ["e.ticket_id = :tid", "s.tenant_id = CAST(:tenant AS uuid)"]
    params = {"tid": ticket_id, "tenant": ctx["tenant_id"]}
    if visible_property_codes is not None:
        where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        params["visible_property_codes"] = sorted(visible_property_codes)
    owns = (await db.execute(
        text(f"""
            SELECT 1
            FROM concierge_escalations e
            JOIN concierge_guest_sessions s ON s.token = e.session_token
            WHERE {' AND '.join(where)}
            LIMIT 1
        """),
        params,
    )).fetchone()
    if not owns:
        raise HTTPException(404, "Escalation not found")

    normalized_action_type = (action_type or "").strip().lower()
    if normalized_action_type == "vendor_coordination":
        await _enforce_scope_permission(request, db, "manage_vendors", ctx)
    elif normalized_action_type in {"owner_internal_update", "accounting_claim_handoff"}:
        await _enforce_scope_permission(request, db, "assign", ctx)

    try:
        result = await escalation_action_agent.execute_action(
            db,
            ctx["tenant_id"],
            ticket_id,
            normalized_action_type,
            actor_label=ctx.get("email") or ctx.get("operator_id"),
        )
        await db.commit()
        await escalation_workflow_service.sync_ticket(db, ctx["tenant_id"], ticket_id)
        return {"ticket_id": ticket_id, "action_type": normalized_action_type, **result}
    except RuntimeError as exc:
        await _rollback_quietly(db)
        raise HTTPException(400, str(exc))
    except Exception as exc:
        await _rollback_quietly(db)
        logger.exception("[Escalations] execute action failed")
        raise HTTPException(500, f"Escalation action failed: {exc}")


def _alert_type_for_escalation(reason: Optional[str], summary: Optional[str], last_message: Optional[str]) -> AlertType:
    r = (reason or "").strip().lower()
    text_blob = " ".join([reason or "", summary or "", last_message or ""]).lower()
    if r in {"maintenance", "property_issue"}:
        return AlertType.MAINTENANCE
    if r == "safety" or any(token in text_blob for token in ("fire", "flood", "gas leak", "medical", "unsafe", "injured", "911", "locked out")):
        return AlertType.SAFETY
    if r == "billing" or any(token in text_blob for token in ("refund", "charge", "billing", "payment", "money back")):
        return AlertType.BILLING
    return AlertType.ESCALATION


@router.get("/escalations/{ticket_id}/routing-preview")
async def escalation_routing_preview(
    ticket_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _scope_profile(request, db, ctx)
    where = ["e.ticket_id = :tid", "s.tenant_id = CAST(:tenant AS uuid)"]
    params = {"tid": ticket_id, "tenant": ctx["tenant_id"]}
    if scope_profile["visible_property_codes"] is not None:
        where.append("s.property_code = ANY(CAST(:visible_property_codes AS text[]))")
        params["visible_property_codes"] = sorted(scope_profile["visible_property_codes"])
    row = (await db.execute(
        text(f"""
            SELECT e.ticket_id, e.property_code, e.reason, e.summary, e.last_message
            FROM concierge_escalations e
            JOIN concierge_guest_sessions s ON s.token = e.session_token
            WHERE {' AND '.join(where)}
            LIMIT 1
        """),
        params,
    )).mappings().first()
    if not row:
        raise HTTPException(404, "Escalation not found")

    alert_type = _alert_type_for_escalation(row["reason"], row["summary"], row["last_message"])
    router = get_alert_router(db=db)
    available, skipped = await router.get_recipients(
        company_id=ctx["tenant_id"],
        alert_type=alert_type,
        property_code=row["property_code"],
    )
    await escalation_workflow_service.sync_ticket(db, ctx["tenant_id"], ticket_id)
    workflow_map = await escalation_workflow_service.workflow_map(db, ctx["tenant_id"], [ticket_id])

    def _contact_payload(contact) -> dict:
        return {
            "id": contact.id,
            "contact_name": contact.contact_name,
            "contact_phone": contact.contact_phone,
            "contact_email": contact.contact_email,
            "alert_type": contact.alert_type.value,
            "property_code": contact.property_code,
            "is_primary": bool(contact.is_primary),
            "escalation_order": int(contact.escalation_order or 1),
            "escalation_timeout_minutes": int(contact.escalation_timeout_minutes or ESCALATION_TIMEOUTS.get(alert_type, 30)),
            "availability_reason": contact.availability_reason(),
            "redirect_to_id": contact.redirect_to_id,
            "notes": contact.notes,
        }

    return {
        "ticket_id": ticket_id,
        "alert_type": alert_type.value,
        "property_code": row["property_code"],
        "coverage_gap": len(available) == 0,
        "timeout_minutes": int(ESCALATION_TIMEOUTS.get(alert_type, 30)),
        "available_contacts": [_contact_payload(contact) for contact in available],
        "skipped_contacts": [_contact_payload(contact) for contact in skipped],
        "workflow": workflow_map.get(ticket_id) or {},
    }


# ═════════════════════════════════════════════════════════════════════════════
# VENDORS
# ═════════════════════════════════════════════════════════════════════════════

_DEFAULT_VENDOR_CATEGORIES = [
    {"slug": "restaurants",     "display_name": "Restaurants",           "icon": "🍽️", "sort_order": 10},
    {"slug": "watersports",     "display_name": "Watersports",           "icon": "🛶", "sort_order": 20},
    {"slug": "groceries",       "display_name": "Groceries & Delivery",  "icon": "🛒", "sort_order": 30},
    {"slug": "maintenance",     "display_name": "Maintenance",           "icon": "🔧", "sort_order": 40},
    {"slug": "transportation",  "display_name": "Transportation",        "icon": "🚗", "sort_order": 50},
    {"slug": "activities",      "display_name": "Activities & Fitness",  "icon": "🏋️", "sort_order": 60},
    {"slug": "spa_wellness",    "display_name": "Spa & Wellness",        "icon": "💆", "sort_order": 70},
    {"slug": "events",          "display_name": "Events & Entertainment","icon": "🎉", "sort_order": 80},
]

_DISPATCH_VENDOR_SLUGS = {
    "maintenance",
    "transportation",
}

_DISPATCH_VENDOR_KEYWORDS = (
    "maintenance",
    "repair",
    "plumb",
    "electric",
    "hvac",
    "ac",
    "locksmith",
    "cleaning",
    "security",
    "emergency",
    "transport",
)


def _vendor_workflow_group(category_slug: Optional[str]) -> str:
    slug = (category_slug or "").strip().lower()
    if slug in _DISPATCH_VENDOR_SLUGS:
        return "dispatch"
    if any(token in slug for token in _DISPATCH_VENDOR_KEYWORDS):
        return "dispatch"
    return "experience"


async def _ensure_default_categories(db: AsyncSession, tenant_id: str) -> None:
    """Seed the default 8 categories once per tenant if they don't exist."""
    existing = (await db.execute(
        text("SELECT COUNT(*) FROM vendor_categories WHERE tenant_id = CAST(:tid AS uuid)"),
        {"tid": tenant_id},
    )).scalar() or 0
    if existing > 0:
        return
    for cat in _DEFAULT_VENDOR_CATEGORIES:
        await db.execute(
            text("""
                INSERT INTO vendor_categories (tenant_id, slug, display_name, icon, sort_order)
                VALUES (CAST(:tid AS uuid), :slug, :name, :icon, :sort)
                ON CONFLICT (tenant_id, slug) DO NOTHING
            """),
            {
                "tid": tenant_id, "slug": cat["slug"],
                "name": cat["display_name"], "icon": cat["icon"],
                "sort": cat["sort_order"],
            },
        )
    await db.commit()


@router.get("/vendor-categories")
async def list_vendor_categories(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    await _ensure_default_categories(db, ctx["tenant_id"])
    rows = (await db.execute(
        text("""
            SELECT c.category_id, c.slug, c.display_name, c.icon, c.sort_order,
                   COUNT(v.vendor_id) FILTER (WHERE v.active = TRUE) AS vendor_count
            FROM vendor_categories c
            LEFT JOIN vendors v
                ON v.tenant_id = c.tenant_id AND v.category_slug = c.slug
            WHERE c.tenant_id = CAST(:tid AS uuid)
            GROUP BY c.category_id, c.slug, c.display_name, c.icon, c.sort_order
            ORDER BY c.sort_order ASC
        """),
        {"tid": ctx["tenant_id"]},
    )).mappings().all()
    items = []
    for row in rows:
        data = dict(row)
        data["workflow_group"] = _vendor_workflow_group(data.get("slug"))
        items.append(_serialize(data))
    return {"categories": items}


@router.post("/vendor-categories")
async def create_vendor_category(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    slug = (body.get("slug") or "").strip().lower().replace(" ", "_")
    name = (body.get("display_name") or "").strip()
    icon = (body.get("icon") or "📍").strip()
    if not slug or not name:
        raise HTTPException(400, "slug and display_name are required")

    await db.execute(
        text("""
            INSERT INTO vendor_categories (tenant_id, slug, display_name, icon, sort_order)
            VALUES (CAST(:tid AS uuid), :slug, :name, :icon,
                    (SELECT COALESCE(MAX(sort_order), 0) + 10
                       FROM vendor_categories WHERE tenant_id = CAST(:tid AS uuid)))
            ON CONFLICT (tenant_id, slug) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                icon = EXCLUDED.icon,
                updated_at = NOW()
        """),
        {"tid": ctx["tenant_id"], "slug": slug, "name": name, "icon": icon},
    )
    await db.commit()
    return {"ok": True, "slug": slug}


@router.get("/vendors")
async def list_vendors(
    request: Request,
    category_slug: Optional[str] = None,
    workflow: Optional[str] = None,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _scope_profile(request, db, ctx)
    visible_property_ids = await _visible_property_id_map(db, ctx["tenant_id"], scope_profile["visible_property_codes"])
    where = ["tenant_id = CAST(:tid AS uuid)"]
    params: dict = {"tid": ctx["tenant_id"]}
    if category_slug:
        where.append("category_slug = :slug")
        params["slug"] = category_slug

    rows = (await db.execute(
        text(f"""
            SELECT vendor_id, category_slug, name, phone, website,
                   ai_script, internal_notes, priority,
                   apply_scope, property_ids, active,
                   operational_metadata,
                   referral_count, last_referred_at,
                   created_at, updated_at
            FROM vendors
            WHERE {' AND '.join(where)}
            ORDER BY category_slug ASC, priority ASC, created_at ASC
        """),
        params,
    )).mappings().all()
    items = []
    for row in rows:
        data = dict(row)
        data["property_ids"] = _normalize_vendor_property_ids(data.get("property_ids"))
        data["operational_metadata"] = vendor_intelligence_service.normalize_metadata(data.get("operational_metadata"))
        if visible_property_ids is not None:
            apply_scope = str(data.get("apply_scope") or "all").strip().lower()
            vendor_property_ids = set(data["property_ids"])
            if apply_scope != "all" and not (vendor_property_ids & set(visible_property_ids.keys())):
                continue
        data["workflow_group"] = _vendor_workflow_group(data.get("category_slug"))
        items.append(_serialize(data))
    if workflow in {"dispatch", "experience"}:
        items = [item for item in items if item.get("workflow_group") == workflow]
    return {"vendors": items, "count": len(items)}


@router.post("/vendors")
async def create_vendor(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _enforce_scope_permission(request, db, "manage_vendors", ctx)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    name = (body.get("name") or "").strip()
    category_slug = (body.get("category_slug") or "").strip().lower()
    if not name or not category_slug:
        raise HTTPException(400, "name and category_slug are required")
    visible_property_ids = await _visible_property_id_map(db, ctx["tenant_id"], scope_profile["visible_property_codes"])
    apply_scope = (body.get("apply_scope") or "all").strip().lower()
    property_ids = _normalize_vendor_property_ids(body.get("property_ids"))
    if visible_property_ids is not None:
        if apply_scope == "all":
            raise HTTPException(403, "Scoped team members cannot create tenant-wide vendors")
        allowed_ids = set(visible_property_ids.keys())
        if not property_ids or not set(property_ids).issubset(allowed_ids):
            raise HTTPException(403, "Vendor scope must stay within your assigned properties")

    # Ensure category row exists (creates default ones for new tenants)
    await _ensure_default_categories(db, ctx["tenant_id"])
    cat_row = (await db.execute(
        text("""
            SELECT category_id FROM vendor_categories
            WHERE tenant_id = CAST(:tid AS uuid) AND slug = :slug LIMIT 1
        """),
        {"tid": ctx["tenant_id"], "slug": category_slug},
    )).fetchone()
    category_id = str(cat_row[0]) if cat_row else None

    result = await db.execute(
        text("""
            INSERT INTO vendors
                (tenant_id, category_id, category_slug, name, phone, website,
                 ai_script, internal_notes, priority, apply_scope, property_ids, active, operational_metadata)
            VALUES
                (CAST(:tid AS uuid),
                 CASE WHEN :cid = '' THEN NULL ELSE CAST(:cid AS uuid) END,
                 :slug, :name, :phone, :website,
                 :ai_script, :notes, :priority, :scope, CAST(:pids AS jsonb), :active, CAST(:operational_metadata AS jsonb))
            RETURNING vendor_id
        """),
        {
            "tid":     ctx["tenant_id"],
            "cid":     category_id or "",
            "slug":    category_slug,
            "name":    name,
            "phone":   body.get("phone") or "",
            "website": body.get("website") or "",
            "ai_script":  body.get("ai_script") or "",
            "notes":   body.get("internal_notes") or "",
            "priority": int(body.get("priority") or 1),
            "scope":   apply_scope or "all",
            "pids":    json.dumps(property_ids),
            "active":  True if body.get("active") is None else bool(body.get("active")),
            "operational_metadata": json.dumps(vendor_intelligence_service.normalize_metadata(body.get("operational_metadata"))),
        },
    )
    new_id = result.fetchone()[0]
    await db.commit()
    return {"ok": True, "vendor_id": str(new_id)}


@router.patch("/vendors/{vendor_id}")
async def update_vendor(
    vendor_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _enforce_scope_permission(request, db, "manage_vendors", ctx)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    visible_property_ids = await _visible_property_id_map(db, ctx["tenant_id"], scope_profile["visible_property_codes"])
    existing_row = (await db.execute(
        text("""
            SELECT apply_scope, property_ids, operational_metadata
            FROM vendors
            WHERE vendor_id = CAST(:vid AS uuid)
              AND tenant_id = CAST(:tid AS uuid)
            LIMIT 1
        """),
        {"vid": vendor_id, "tid": ctx["tenant_id"]},
    )).mappings().first()
    if not existing_row:
        raise HTTPException(404, "Vendor not found")
    if visible_property_ids is not None:
        existing_scope = str(existing_row["apply_scope"] or "all").strip().lower()
        existing_property_ids = set(_normalize_vendor_property_ids(existing_row["property_ids"]))
        allowed_ids = set(visible_property_ids.keys())
        if existing_scope == "all" or not existing_property_ids.issubset(allowed_ids):
            raise HTTPException(403, "Vendor is outside your assigned properties")

    allowed = {"name", "phone", "website", "ai_script", "internal_notes",
               "priority", "apply_scope", "active", "category_slug"}
    sets = []
    params: dict = {"vid": vendor_id, "tid": ctx["tenant_id"]}
    for k, v in body.items():
        if k in allowed:
            sets.append(f"{k} = :{k}")
            params[k] = v
    if "property_ids" in body:
        next_property_ids = _normalize_vendor_property_ids(body["property_ids"])
        if visible_property_ids is not None and not set(next_property_ids).issubset(set(visible_property_ids.keys())):
            raise HTTPException(403, "Vendor scope must stay within your assigned properties")
        sets.append("property_ids = CAST(:property_ids AS jsonb)")
        params["property_ids"] = json.dumps(next_property_ids)
    if "operational_metadata" in body:
        sets.append("operational_metadata = CAST(:operational_metadata AS jsonb)")
        params["operational_metadata"] = json.dumps(vendor_intelligence_service.normalize_metadata(body.get("operational_metadata")))
    if "apply_scope" in body and visible_property_ids is not None:
        next_scope = str(body.get("apply_scope") or "").strip().lower()
        if next_scope == "all":
            raise HTTPException(403, "Scoped team members cannot create tenant-wide vendors")
    if not sets:
        return {"ok": True, "no_changes": True}
    sets.append("updated_at = NOW()")

    result = await db.execute(
        text(f"""
            UPDATE vendors
            SET {', '.join(sets)}
            WHERE vendor_id = CAST(:vid AS uuid)
              AND tenant_id = CAST(:tid AS uuid)
        """),
        params,
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(404, "Vendor not found")
    return {"ok": True}


@router.delete("/vendors/{vendor_id}")
async def delete_vendor(
    vendor_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _enforce_scope_permission(request, db, "manage_vendors", ctx)
    visible_property_ids = await _visible_property_id_map(db, ctx["tenant_id"], scope_profile["visible_property_codes"])
    if visible_property_ids is not None:
        existing_row = (await db.execute(
            text("""
                SELECT apply_scope, property_ids
                FROM vendors
                WHERE vendor_id = CAST(:vid AS uuid)
                  AND tenant_id = CAST(:tid AS uuid)
                LIMIT 1
            """),
            {"vid": vendor_id, "tid": ctx["tenant_id"]},
        )).mappings().first()
        if not existing_row:
            raise HTTPException(404, "Vendor not found")
        existing_scope = str(existing_row["apply_scope"] or "all").strip().lower()
        existing_property_ids = set(_normalize_vendor_property_ids(existing_row["property_ids"]))
        if existing_scope == "all" or not existing_property_ids.issubset(set(visible_property_ids.keys())):
            raise HTTPException(403, "Vendor is outside your assigned properties")
    result = await db.execute(
        text("""
            DELETE FROM vendors
            WHERE vendor_id = CAST(:vid AS uuid)
              AND tenant_id = CAST(:tid AS uuid)
        """),
        {"vid": vendor_id, "tid": ctx["tenant_id"]},
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(404, "Vendor not found")
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ═════════════════════════════════════════════════════════════════════════════

_DEFAULT_SETTINGS = {
    "prebooking_autosend_threshold": 95,
    "escalation_urgency_threshold": 70,
    "kb_gap_detection_threshold": 40,
    "ai_concierge_name": "Your Concierge",
    "notify_emergency": True,
    "notify_maintenance": True,
    "notify_prebooking": True,
    "notify_kb_gaps": False,
    "notify_weekly_analytics": True,
    "kb_suppressed_categories": [],
    "ai_paused": False,
    "ai_paused_at": None,
    "proactive_policy": {
        "enabled_touch_types": [
            "pre_arrival_welcome",
            "arrival_info",
            "dinner_planning",
            "arrival_day_checkin",
            "in_stay_checkin",
            "checkout_prep",
            "extend_offer",
            "service_update_reassurance",
        ],
        "min_hours_between_proactive_touches": 18,
        "min_hours_between_service_updates": 4,
        "max_notifications_per_stay_window": 6,
        "allow_service_updates_during_escalation": True,
    },
    "escalation_guest_policy": {
        "allow_eta_updates": True,
        "allow_reassurance_without_eta": True,
        "operator_approval_required_for_status_updates": False,
    },
    "safety_policy": {
        "require_human_ack_for_property_damage": True,
        "auto_hold_unit_on_life_safety": True,
        "auto_hold_unit_on_property_damage": True,
        "allow_non_life_safety_guest_reassurance": True,
    },
    "stay_operations_policy": {
        "workflow_profile": "assisted_ops",
        "enable_access_workflows": True,
        "enable_rental_workflows": True,
        "enable_turnover_workflows": True,
        "enable_maintenance_workflows": True,
        "enable_post_checkout_walkthrough": False,
        "walkthrough_required_before_ready": False,
        "auto_archive_when_turnover_ready": True,
    },
    "retention_policy": dict(DEFAULT_RETENTION_POLICY),
    "review_event_policy": {
        "ingest_review_events": True,
        "apply_private_feedback_signals": False,
        "generate_review_response_drafts": False,
    },
}


def _merged_settings_payload(row_data: Optional[dict]) -> dict:
    data = dict(_DEFAULT_SETTINGS)
    if not row_data:
        return data

    raw = dict(row_data)
    kb_sup = raw.get("kb_suppressed_categories") or []
    if isinstance(kb_sup, str):
        try:
            kb_sup = json.loads(kb_sup)
        except Exception:
            kb_sup = []
    raw["kb_suppressed_categories"] = kb_sup

    extra = raw.get("extra") or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    extra = extra if isinstance(extra, dict) else {}

    proactive_policy = dict(_DEFAULT_SETTINGS["proactive_policy"])
    proactive_policy.update(extra.get("proactive_policy") or {})
    escalation_guest_policy = dict(_DEFAULT_SETTINGS["escalation_guest_policy"])
    escalation_guest_policy.update(extra.get("escalation_guest_policy") or {})
    safety_policy = dict(_DEFAULT_SETTINGS["safety_policy"])
    safety_policy.update(extra.get("safety_policy") or {})
    stay_operations_policy = dict(_DEFAULT_SETTINGS["stay_operations_policy"])
    stay_operations_policy.update(extra.get("stay_operations_policy") or {})
    retention_policy = merge_retention_policy(extra)
    review_event_policy = dict(_DEFAULT_SETTINGS["review_event_policy"])
    review_event_policy.update(extra.get("review_event_policy") or {})

    data.update({k: v for k, v in raw.items() if k in data or k in {"updated_at"}})
    data["proactive_policy"] = proactive_policy
    data["escalation_guest_policy"] = escalation_guest_policy
    data["safety_policy"] = safety_policy
    data["stay_operations_policy"] = stay_operations_policy
    data["retention_policy"] = retention_policy
    data["review_event_policy"] = review_event_policy

    if data.get("ai_paused_at") and hasattr(data["ai_paused_at"], "isoformat"):
        data["ai_paused_at"] = data["ai_paused_at"].isoformat()
    if data.get("updated_at") and hasattr(data["updated_at"], "isoformat"):
        data["updated_at"] = data["updated_at"].isoformat()
    return data


@router.get("/settings")
async def get_settings(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _scope_profile(request, db, ctx)
    try:
        settings_cols = await _table_columns(db, "operator_settings")
        account_cols = await _table_columns(db, "operator_accounts")
        row = None
        acct = None

        if settings_cols:
            wanted_settings = [
                "prebooking_autosend_threshold",
                "escalation_urgency_threshold",
                "kb_gap_detection_threshold",
                "ai_concierge_name",
                "notify_emergency",
                "notify_maintenance",
                "notify_prebooking",
                "notify_kb_gaps",
                "notify_weekly_analytics",
                "kb_suppressed_categories",
                "ai_paused",
                "ai_paused_at",
                "extra",
                "updated_at",
            ]
            select_settings = ",\n                   ".join(
                col if col in settings_cols else f"NULL AS {col}"
                for col in wanted_settings
            )
            row = (await db.execute(
                text(f"""
                    SELECT {select_settings}
                    FROM operator_settings
                    WHERE tenant_id = CAST(:tid AS uuid)
                    LIMIT 1
                """),
                {"tid": ctx["tenant_id"]},
            )).mappings().first()

        if account_cols:
            wanted_account = [
                "email",
                "messaging_email",
                "company_name",
                "owner_name",
                "pms",
                "plan",
                "property_count",
                "onboarding_complete",
            ]
            select_account = ",\n                   ".join(
                col if col in account_cols else f"NULL AS {col}"
                for col in wanted_account
            )
            acct = (await db.execute(
                text(f"""
                    SELECT {select_account}
                    FROM operator_accounts
                    WHERE tenant_id = CAST(:tid AS uuid) LIMIT 1
                """),
                {"tid": ctx["tenant_id"]},
            )).mappings().first()
    except Exception as exc:
        await _rollback_quietly(db)
        logger.exception("[Settings] load failed")
        raise HTTPException(500, f"Settings failed: {exc}")

    data = _merged_settings_payload(dict(row) if row else None)

    account = dict(acct) if acct else {}
    return {
        "settings": data,
        "account": account,
        "permissions": {
            "can_manage_settings": bool(scope_profile["can_manage_settings"]),
            "can_manage_vendors": bool(scope_profile["can_manage_vendors"]),
            "can_assign": bool(scope_profile["can_assign"]),
        },
    }


@router.patch("/settings")
async def update_settings(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    await _enforce_scope_permission(request, db, "manage_settings", ctx)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    numeric_keys = {"prebooking_autosend_threshold", "escalation_urgency_threshold",
                    "kb_gap_detection_threshold"}
    bool_keys = {"notify_emergency", "notify_maintenance", "notify_prebooking",
                 "notify_kb_gaps", "notify_weekly_analytics", "ai_paused"}
    str_keys = {"ai_concierge_name"}

    sets = ["updated_at = NOW()"]
    params: dict = {"tid": ctx["tenant_id"], "oid": ctx["operator_id"]}
    extra_patch: dict[str, object] = {}

    for k, v in body.items():
        if k in numeric_keys:
            val = int(v)
            val = max(0, min(100, val))  # clamp 0..100
            sets.append(f"{k} = :{k}")
            params[k] = val
        elif k in bool_keys:
            sets.append(f"{k} = :{k}")
            params[k] = bool(v)
            if k == "ai_paused":
                if bool(v):
                    sets.append("ai_paused_at = NOW()")
                else:
                    sets.append("ai_paused_at = NULL")
        elif k in str_keys:
            sets.append(f"{k} = :{k}")
            params[k] = str(v).strip()[:200]
        elif k == "kb_suppressed_categories":
            sets.append("kb_suppressed_categories = CAST(:kb_sup AS jsonb)")
            params["kb_sup"] = json.dumps(v or [])
        elif k == "proactive_policy":
            incoming = v if isinstance(v, dict) else {}
            allowed = incoming.get("enabled_touch_types")
            extra_patch["proactive_policy"] = {
                "enabled_touch_types": [
                    str(item).strip()
                    for item in (allowed if isinstance(allowed, list) else _DEFAULT_SETTINGS["proactive_policy"]["enabled_touch_types"])
                    if str(item).strip()
                ],
                "min_hours_between_proactive_touches": max(1, min(72, int(incoming.get("min_hours_between_proactive_touches", _DEFAULT_SETTINGS["proactive_policy"]["min_hours_between_proactive_touches"])))),
                "min_hours_between_service_updates": max(1, min(24, int(incoming.get("min_hours_between_service_updates", _DEFAULT_SETTINGS["proactive_policy"]["min_hours_between_service_updates"])))),
                "max_notifications_per_stay_window": max(1, min(20, int(incoming.get("max_notifications_per_stay_window", _DEFAULT_SETTINGS["proactive_policy"]["max_notifications_per_stay_window"])))),
                "allow_service_updates_during_escalation": bool(incoming.get("allow_service_updates_during_escalation", _DEFAULT_SETTINGS["proactive_policy"]["allow_service_updates_during_escalation"])),
            }
        elif k == "escalation_guest_policy":
            incoming = v if isinstance(v, dict) else {}
            extra_patch["escalation_guest_policy"] = {
                "allow_eta_updates": bool(incoming.get("allow_eta_updates", _DEFAULT_SETTINGS["escalation_guest_policy"]["allow_eta_updates"])),
                "allow_reassurance_without_eta": bool(incoming.get("allow_reassurance_without_eta", _DEFAULT_SETTINGS["escalation_guest_policy"]["allow_reassurance_without_eta"])),
                "operator_approval_required_for_status_updates": bool(incoming.get("operator_approval_required_for_status_updates", _DEFAULT_SETTINGS["escalation_guest_policy"]["operator_approval_required_for_status_updates"])),
            }
        elif k == "stay_operations_policy":
            incoming = v if isinstance(v, dict) else {}
            profile = str(incoming.get("workflow_profile", _DEFAULT_SETTINGS["stay_operations_policy"]["workflow_profile"])).strip().lower()
            if profile not in {"messaging_only", "assisted_ops", "full_ops"}:
                profile = _DEFAULT_SETTINGS["stay_operations_policy"]["workflow_profile"]
            extra_patch["stay_operations_policy"] = {
                "workflow_profile": profile,
                "enable_access_workflows": bool(incoming.get("enable_access_workflows", _DEFAULT_SETTINGS["stay_operations_policy"]["enable_access_workflows"])),
                "enable_rental_workflows": bool(incoming.get("enable_rental_workflows", _DEFAULT_SETTINGS["stay_operations_policy"]["enable_rental_workflows"])),
                "enable_turnover_workflows": bool(incoming.get("enable_turnover_workflows", _DEFAULT_SETTINGS["stay_operations_policy"]["enable_turnover_workflows"])),
                "enable_maintenance_workflows": bool(incoming.get("enable_maintenance_workflows", _DEFAULT_SETTINGS["stay_operations_policy"]["enable_maintenance_workflows"])),
                "enable_post_checkout_walkthrough": bool(incoming.get("enable_post_checkout_walkthrough", _DEFAULT_SETTINGS["stay_operations_policy"]["enable_post_checkout_walkthrough"])),
                "walkthrough_required_before_ready": bool(incoming.get("walkthrough_required_before_ready", _DEFAULT_SETTINGS["stay_operations_policy"]["walkthrough_required_before_ready"])),
                "auto_archive_when_turnover_ready": bool(incoming.get("auto_archive_when_turnover_ready", _DEFAULT_SETTINGS["stay_operations_policy"]["auto_archive_when_turnover_ready"])),
            }
        elif k == "retention_policy":
            current_extra = {"retention_policy": v} if isinstance(v, dict) else {}
            extra_patch["retention_policy"] = merge_retention_policy(current_extra)
        elif k == "safety_policy":
            incoming = v if isinstance(v, dict) else {}
            extra_patch["safety_policy"] = {
                "require_human_ack_for_property_damage": bool(incoming.get("require_human_ack_for_property_damage", _DEFAULT_SETTINGS["safety_policy"]["require_human_ack_for_property_damage"])),
                "auto_hold_unit_on_life_safety": bool(incoming.get("auto_hold_unit_on_life_safety", _DEFAULT_SETTINGS["safety_policy"]["auto_hold_unit_on_life_safety"])),
                "auto_hold_unit_on_property_damage": bool(incoming.get("auto_hold_unit_on_property_damage", _DEFAULT_SETTINGS["safety_policy"]["auto_hold_unit_on_property_damage"])),
                "allow_non_life_safety_guest_reassurance": bool(incoming.get("allow_non_life_safety_guest_reassurance", _DEFAULT_SETTINGS["safety_policy"]["allow_non_life_safety_guest_reassurance"])),
            }
        elif k == "review_event_policy":
            incoming = v if isinstance(v, dict) else {}
            extra_patch["review_event_policy"] = {
                "ingest_review_events": bool(incoming.get("ingest_review_events", _DEFAULT_SETTINGS["review_event_policy"]["ingest_review_events"])),
                "apply_private_feedback_signals": bool(incoming.get("apply_private_feedback_signals", _DEFAULT_SETTINGS["review_event_policy"]["apply_private_feedback_signals"])),
                "generate_review_response_drafts": bool(incoming.get("generate_review_response_drafts", _DEFAULT_SETTINGS["review_event_policy"]["generate_review_response_drafts"])),
            }

    # UPSERT pattern — if no row exists for this tenant yet, create one
    existing = (await db.execute(
        text("SELECT 1 FROM operator_settings WHERE tenant_id = CAST(:tid AS uuid)"),
        {"tid": ctx["tenant_id"]},
    )).fetchone()

    if extra_patch:
        existing_row = (await db.execute(
            text("SELECT extra FROM operator_settings WHERE tenant_id = CAST(:tid AS uuid) LIMIT 1"),
            {"tid": ctx["tenant_id"]},
        )).mappings().first()
        current_extra = existing_row.get("extra") if existing_row else {}
        if isinstance(current_extra, str):
            try:
                current_extra = json.loads(current_extra)
            except Exception:
                current_extra = {}
        current_extra = current_extra if isinstance(current_extra, dict) else {}
        current_extra.update(extra_patch)
        sets.append("extra = CAST(:extra_json AS jsonb)")
        params["extra_json"] = json.dumps(current_extra)

    if existing:
        await db.execute(
            text(f"""
                UPDATE operator_settings
                SET {', '.join(sets)}
                WHERE tenant_id = CAST(:tid AS uuid)
            """),
            params,
        )
    else:
        # Insert with defaults for unspecified fields
        base = dict(_DEFAULT_SETTINGS)
        base.pop("ai_paused_at", None)
        base_extra = {
            "proactive_policy": dict(_DEFAULT_SETTINGS["proactive_policy"]),
            "escalation_guest_policy": dict(_DEFAULT_SETTINGS["escalation_guest_policy"]),
            "safety_policy": dict(_DEFAULT_SETTINGS["safety_policy"]),
            "stay_operations_policy": dict(_DEFAULT_SETTINGS["stay_operations_policy"]),
            "retention_policy": dict(_DEFAULT_SETTINGS["retention_policy"]),
            "review_event_policy": dict(_DEFAULT_SETTINGS["review_event_policy"]),
        }
        for k, v in body.items():
            if k in numeric_keys:
                base[k] = max(0, min(100, int(v)))
            elif k in bool_keys:
                base[k] = bool(v)
            elif k in str_keys:
                base[k] = str(v).strip()[:200]
            elif k == "kb_suppressed_categories":
                base[k] = v or []
            elif k == "proactive_policy" and "proactive_policy" in extra_patch:
                base_extra["proactive_policy"] = extra_patch["proactive_policy"]
            elif k == "escalation_guest_policy" and "escalation_guest_policy" in extra_patch:
                base_extra["escalation_guest_policy"] = extra_patch["escalation_guest_policy"]
            elif k == "stay_operations_policy" and "stay_operations_policy" in extra_patch:
                base_extra["stay_operations_policy"] = extra_patch["stay_operations_policy"]
            elif k == "retention_policy" and "retention_policy" in extra_patch:
                base_extra["retention_policy"] = extra_patch["retention_policy"]
            elif k == "safety_policy" and "safety_policy" in extra_patch:
                base_extra["safety_policy"] = extra_patch["safety_policy"]
            elif k == "review_event_policy" and "review_event_policy" in extra_patch:
                base_extra["review_event_policy"] = extra_patch["review_event_policy"]
        await db.execute(
            text("""
                INSERT INTO operator_settings
                    (tenant_id, operator_id,
                     prebooking_autosend_threshold, escalation_urgency_threshold,
                     kb_gap_detection_threshold, ai_concierge_name,
                     notify_emergency, notify_maintenance, notify_prebooking,
                     notify_kb_gaps, notify_weekly_analytics,
                     kb_suppressed_categories, ai_paused, extra)
                VALUES
                    (CAST(:tid AS uuid), CAST(:oid AS uuid),
                     :pre_thr, :esc_thr, :gap_thr, :ai_name,
                     :n_em, :n_mt, :n_pb, :n_kb, :n_wk,
                     CAST(:kb_sup AS jsonb), :paused, CAST(:extra_json AS jsonb))
            """),
            {
                "tid":      ctx["tenant_id"],
                "oid":      ctx["operator_id"],
                "pre_thr":  base["prebooking_autosend_threshold"],
                "esc_thr":  base["escalation_urgency_threshold"],
                "gap_thr":  base["kb_gap_detection_threshold"],
                "ai_name":  base["ai_concierge_name"],
                "n_em":     base["notify_emergency"],
                "n_mt":     base["notify_maintenance"],
                "n_pb":     base["notify_prebooking"],
                "n_kb":     base["notify_kb_gaps"],
                "n_wk":     base["notify_weekly_analytics"],
                "kb_sup":   json.dumps(base["kb_suppressed_categories"]),
                "paused":   base["ai_paused"],
                "extra_json": json.dumps(base_extra),
            },
        )
    await db.commit()
    return {"ok": True}


@router.get("/settings/alert-routing")
async def get_alert_routing_settings(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _scope_profile(request, db, ctx)
    visible_property_codes = scope_profile["visible_property_codes"]
    try:
        contact_columns = await _table_columns(db, "operator_alert_contacts")
        if not contact_columns:
            return {
                "contacts": [],
                "coverage": [],
                "all_covered": False,
                "gap_count": 0,
                "properties": [],
                "alert_types": [a.value for a in AlertType],
                "permissions": {"can_manage_settings": bool(scope_profile["can_manage_settings"])},
            }

        contacts = (await db.execute(
            text(f"""
                SELECT
                    c.id::text,
                    c.contact_name,
                    c.contact_phone,
                    c.contact_email,
                    c.alert_type,
                    c.property_code,
                    c.is_primary,
                    c.escalation_order,
                    c.escalation_timeout_minutes,
                    c.active_hours_start,
                    c.active_hours_end,
                    c.is_available,
                    c.unavailable_until,
                    c.redirect_to_id::text,
                    c.notes,
                    r.contact_name AS redirect_name
                FROM operator_alert_contacts c
                LEFT JOIN operator_alert_contacts r ON r.id = c.redirect_to_id
                WHERE c.company_id = CAST(:tid AS uuid)
                  {"AND (c.property_code IS NULL OR c.property_code = ANY(CAST(:visible_property_codes AS text[])))" if visible_property_codes is not None else ""}
                ORDER BY c.alert_type, c.escalation_order, c.contact_name
            """),
            {
                "tid": ctx["tenant_id"],
                **({"visible_property_codes": sorted(visible_property_codes)} if visible_property_codes is not None else {}),
            },
        )).mappings().all()

        prop_rows = []
        property_meta = await _property_query_meta(db)
        if property_meta:
            prop_rows = (await db.execute(
                text(f"""
                    SELECT
                        {property_meta["id_expr"]} AS property_id,
                        {property_meta["name_expr"]} AS property_name,
                        {property_meta["code_expr"]} AS property_code
                    FROM properties
                    WHERE {property_meta["where_sql"]}
                      {"AND " + property_meta["code_expr"] + " = ANY(CAST(:visible_property_codes AS text[]))" if visible_property_codes is not None else ""}
                    ORDER BY {property_meta["name_expr"]}
                """),
                {
                    "tid": ctx["tenant_id"],
                    **({"visible_property_codes": sorted(visible_property_codes)} if visible_property_codes is not None else {}),
                },
            )).mappings().all()

        router_svc = get_alert_router(db=db)
        coverage = []
        for alert_type in AlertType:
            available, skipped = await router_svc.get_recipients(
                company_id=ctx["tenant_id"],
                alert_type=alert_type,
            )
            coverage.append({
                "alert_type": alert_type.value,
                "has_coverage": len(available) > 0,
                "available_count": len(available),
                "available_contacts": [c.contact_name for c in available],
                "ooo_contacts": [f"{c.contact_name} ({c.availability_reason()})" for c in skipped],
                "escalation_timeout_minutes": ESCALATION_TIMEOUTS.get(alert_type, 30),
                "gap_details": None if available else "No available contacts — alerts will fall back to Oyvoda ops.",
            })

        return {
            "contacts": [
                {
                    **_serialize(row),
                    "active_hours": (
                        f"{row['active_hours_start']}–{row['active_hours_end']}"
                        if row["active_hours_start"] and row["active_hours_end"] else "24/7"
                    ),
                    "status_label": (
                        f"OOO until {row['unavailable_until'].strftime('%b %d, %I:%M %p UTC')}"
                        if (not row["is_available"] and row["unavailable_until"])
                        else ("Unavailable" if not row["is_available"] else (
                            f"Active {row['active_hours_start']}–{row['active_hours_end']}"
                            if row["active_hours_start"] and row["active_hours_end"] else "Available 24/7"
                        ))
                    ),
                }
                for row in contacts
            ],
            "coverage": coverage,
            "all_covered": all(item["has_coverage"] for item in coverage),
            "gap_count": sum(1 for item in coverage if not item["has_coverage"]),
            "properties": [
                {
                    "property_id": str(row["property_id"]) if row["property_id"] else None,
                    "property_name": row["property_name"],
                    "property_code": row["property_code"],
                }
                for row in prop_rows
            ],
            "alert_types": [a.value for a in AlertType],
            "permissions": {
                "can_manage_settings": bool(scope_profile["can_manage_settings"]),
            },
        }
    except Exception as e:
        await _rollback_quietly(db)
        logger.exception("[AlertRouting] load failed")
        raise HTTPException(500, f"Alert routing failed: {e}")


@router.post("/settings/alert-routing")
async def create_alert_routing_contact(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _enforce_scope_permission(request, db, "manage_settings", ctx)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    contact_name = (body.get("contact_name") or "").strip()
    if not contact_name:
        raise HTTPException(400, "contact_name is required")

    alert_type = (body.get("alert_type") or "general").strip().lower()
    if alert_type not in {a.value for a in AlertType}:
        raise HTTPException(400, "Invalid alert_type")

    property_code = (body.get("property_code") or "").strip() or None
    if scope_profile["visible_property_codes"] is not None and property_code and property_code not in scope_profile["visible_property_codes"]:
        raise HTTPException(403, "Alert routing scope must stay within your assigned properties")
    contact_phone = (body.get("contact_phone") or "").strip() or None
    contact_email = (body.get("contact_email") or "").strip() or None
    notes = (body.get("notes") or "").strip() or None
    active_hours_start = (body.get("active_hours_start") or "").strip() or None
    active_hours_end = (body.get("active_hours_end") or "").strip() or None
    escalation_order = max(1, int(body.get("escalation_order") or 1))
    escalation_timeout_minutes = max(1, int(body.get("escalation_timeout_minutes") or ESCALATION_TIMEOUTS.get(AlertType(alert_type), 30)))
    is_primary = bool(body.get("is_primary", escalation_order == 1))

    await db.execute(
        text("""
            INSERT INTO operator_alert_contacts
                (id, company_id, alert_type, property_code, contact_name,
                 contact_phone, contact_email, is_primary, escalation_order,
                 escalation_timeout_minutes, active_hours_start, active_hours_end,
                 is_available, notes, created_at, updated_at)
            VALUES
                (gen_random_uuid(), CAST(:tid AS uuid), :alert_type, :property_code, :contact_name,
                 :contact_phone, :contact_email, :is_primary, :escalation_order,
                 :timeout_minutes, :active_hours_start, :active_hours_end,
                 TRUE, :notes, NOW(), NOW())
        """),
        {
            "tid": ctx["tenant_id"],
            "alert_type": alert_type,
            "property_code": property_code,
            "contact_name": contact_name,
            "contact_phone": contact_phone,
            "contact_email": contact_email,
            "is_primary": is_primary,
            "escalation_order": escalation_order,
            "timeout_minutes": escalation_timeout_minutes,
            "active_hours_start": active_hours_start,
            "active_hours_end": active_hours_end,
            "notes": notes,
        },
    )
    await db.commit()
    return {"ok": True}


@router.patch("/settings/alert-routing/{contact_id}")
async def update_alert_routing_contact(
    contact_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _enforce_scope_permission(request, db, "manage_settings", ctx)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    fields = []
    params: dict = {"contact_id": contact_id, "tid": ctx["tenant_id"]}

    if "contact_name" in body:
        name = (body.get("contact_name") or "").strip()
        if not name:
            raise HTTPException(400, "contact_name cannot be empty")
        fields.append("contact_name = :contact_name")
        params["contact_name"] = name
    if "contact_phone" in body:
        fields.append("contact_phone = :contact_phone")
        params["contact_phone"] = (body.get("contact_phone") or "").strip() or None
    if "contact_email" in body:
        fields.append("contact_email = :contact_email")
        params["contact_email"] = (body.get("contact_email") or "").strip() or None
    if "property_code" in body:
        fields.append("property_code = :property_code")
        params["property_code"] = (body.get("property_code") or "").strip() or None
    if "notes" in body:
        fields.append("notes = :notes")
        params["notes"] = (body.get("notes") or "").strip() or None
    if "active_hours_start" in body:
        fields.append("active_hours_start = :active_hours_start")
        params["active_hours_start"] = (body.get("active_hours_start") or "").strip() or None
    if "active_hours_end" in body:
        fields.append("active_hours_end = :active_hours_end")
        params["active_hours_end"] = (body.get("active_hours_end") or "").strip() or None
    if "is_primary" in body:
        fields.append("is_primary = :is_primary")
        params["is_primary"] = bool(body.get("is_primary"))
    if "escalation_order" in body:
        fields.append("escalation_order = :escalation_order")
        params["escalation_order"] = max(1, int(body.get("escalation_order") or 1))
    if "escalation_timeout_minutes" in body:
        fields.append("escalation_timeout_minutes = :escalation_timeout_minutes")
        params["escalation_timeout_minutes"] = max(1, int(body.get("escalation_timeout_minutes") or 1))
    if "alert_type" in body:
        alert_type = (body.get("alert_type") or "").strip().lower()
        if alert_type not in {a.value for a in AlertType}:
            raise HTTPException(400, "Invalid alert_type")
        fields.append("alert_type = :alert_type")
        params["alert_type"] = alert_type

    if not fields:
        raise HTTPException(400, "No supported fields provided")

    existing = (await db.execute(
        text("""
            SELECT property_code
            FROM operator_alert_contacts
            WHERE id = CAST(:contact_id AS uuid)
              AND company_id = CAST(:tid AS uuid)
            LIMIT 1
        """),
        {"contact_id": contact_id, "tid": ctx["tenant_id"]},
    )).mappings().first()
    if not existing:
        raise HTTPException(404, "Contact not found")
    existing_property_code = existing.get("property_code")
    if scope_profile["visible_property_codes"] is not None:
        if existing_property_code and existing_property_code not in scope_profile["visible_property_codes"]:
            raise HTTPException(403, "Alert routing contact is outside your assigned properties")
        next_property_code = (body.get("property_code") or "").strip() or None if "property_code" in body else existing_property_code
        if next_property_code and next_property_code not in scope_profile["visible_property_codes"]:
            raise HTTPException(403, "Alert routing scope must stay within your assigned properties")

    result = await db.execute(
        text(f"""
            UPDATE operator_alert_contacts
            SET {', '.join(fields)},
                updated_at = NOW()
            WHERE id = CAST(:contact_id AS uuid)
              AND company_id = CAST(:tid AS uuid)
            RETURNING id
        """),
        params,
    )
    if not result.fetchone():
        raise HTTPException(404, "Contact not found")
    await db.commit()
    return {"ok": True}


@router.post("/settings/alert-routing/{contact_id}/ooo")
async def mark_alert_routing_contact_ooo(
    contact_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _enforce_scope_permission(request, db, "manage_settings", ctx)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    unavailable_until = (body.get("unavailable_until") or "").strip()
    redirect_to_id = (body.get("redirect_to_id") or "").strip() or None
    if not unavailable_until:
        raise HTTPException(400, "unavailable_until is required")

    if scope_profile["visible_property_codes"] is not None:
        existing = (await db.execute(
            text("""
                SELECT property_code
                FROM operator_alert_contacts
                WHERE id = CAST(:contact_id AS uuid)
                  AND company_id = CAST(:tid AS uuid)
                LIMIT 1
            """),
            {"contact_id": contact_id, "tid": ctx["tenant_id"]},
        )).mappings().first()
        if not existing:
            raise HTTPException(404, "Contact not found")
        existing_property_code = existing.get("property_code")
        if existing_property_code and existing_property_code not in scope_profile["visible_property_codes"]:
            raise HTTPException(403, "Alert routing contact is outside your assigned properties")

    result = await db.execute(
        text("""
            UPDATE operator_alert_contacts
            SET is_available = FALSE,
                unavailable_until = CAST(:until AS timestamptz),
                redirect_to_id = CAST(:redirect_to_id AS uuid),
                updated_at = NOW()
            WHERE id = CAST(:contact_id AS uuid)
              AND company_id = CAST(:tid AS uuid)
            RETURNING id
        """),
        {
            "contact_id": contact_id,
            "tid": ctx["tenant_id"],
            "until": unavailable_until,
            "redirect_to_id": redirect_to_id,
        },
    )
    if not result.fetchone():
        raise HTTPException(404, "Contact not found")
    await db.commit()
    return {"ok": True}


@router.post("/settings/alert-routing/{contact_id}/available")
async def mark_alert_routing_contact_available(
    contact_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _enforce_scope_permission(request, db, "manage_settings", ctx)
    if scope_profile["visible_property_codes"] is not None:
        existing = (await db.execute(
            text("""
                SELECT property_code
                FROM operator_alert_contacts
                WHERE id = CAST(:contact_id AS uuid)
                  AND company_id = CAST(:tid AS uuid)
                LIMIT 1
            """),
            {"contact_id": contact_id, "tid": ctx["tenant_id"]},
        )).mappings().first()
        if not existing:
            raise HTTPException(404, "Contact not found")
        existing_property_code = existing.get("property_code")
        if existing_property_code and existing_property_code not in scope_profile["visible_property_codes"]:
            raise HTTPException(403, "Alert routing contact is outside your assigned properties")
    result = await db.execute(
        text("""
            UPDATE operator_alert_contacts
            SET is_available = TRUE,
                unavailable_until = NULL,
                redirect_to_id = NULL,
                updated_at = NOW()
            WHERE id = CAST(:contact_id AS uuid)
              AND company_id = CAST(:tid AS uuid)
            RETURNING id
        """),
        {
            "contact_id": contact_id,
            "tid": ctx["tenant_id"],
        },
    )
    if not result.fetchone():
        raise HTTPException(404, "Contact not found")
    await db.commit()
    return {"ok": True}


@router.delete("/settings/alert-routing/{contact_id}")
async def delete_alert_routing_contact(
    contact_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    scope_profile = await _enforce_scope_permission(request, db, "manage_settings", ctx)
    if scope_profile["visible_property_codes"] is not None:
        existing = (await db.execute(
            text("""
                SELECT property_code
                FROM operator_alert_contacts
                WHERE id = CAST(:contact_id AS uuid)
                  AND company_id = CAST(:tid AS uuid)
                LIMIT 1
            """),
            {"contact_id": contact_id, "tid": ctx["tenant_id"]},
        )).mappings().first()
        if not existing:
            raise HTTPException(404, "Contact not found")
        existing_property_code = existing.get("property_code")
        if existing_property_code and existing_property_code not in scope_profile["visible_property_codes"]:
            raise HTTPException(403, "Alert routing contact is outside your assigned properties")
    result = await db.execute(
        text("""
            DELETE FROM operator_alert_contacts
            WHERE id = CAST(:contact_id AS uuid)
              AND company_id = CAST(:tid AS uuid)
            RETURNING id
        """),
        {
            "contact_id": contact_id,
            "tid": ctx["tenant_id"],
        },
    )
    if not result.fetchone():
        raise HTTPException(404, "Contact not found")
    await db.commit()
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════════════
# AI GUIDANCE — "House Rules & AI Guidance" free-form bucket
# ═════════════════════════════════════════════════════════════════════════════
# Lets operators type natural-language policy the AI should follow when
# drafting guest replies ("offer 20% off for 7+ nights direct-booked",
# "no pets", "check-out is strict 11am"). The raw text is injected into
# the system prompt in pre_booking_auto_send.generate_inquiry_draft().
#
# Single row per company (UNIQUE on company_id). 8000-char cap enforced by
# the DB constraint in migration 030. Empty text = "no operator guidance"
# (pipeline falls back to platform defaults).

@router.get("/settings/ai-guidance")
async def get_ai_guidance(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    row = (await db.execute(
        text("""
            SELECT guidance_text, updated_by, updated_at
            FROM operator_ai_guidance
            WHERE company_id = CAST(:tid AS uuid)
            LIMIT 1
        """),
        {"tid": ctx["tenant_id"]},
    )).mappings().first()
    if not row:
        return {
            "guidance_text": "",
            "updated_by": None,
            "updated_at": None,
            "char_limit": 8000,
        }
    return {
        "guidance_text": row["guidance_text"] or "",
        "updated_by":    row["updated_by"],
        "updated_at":    row["updated_at"].isoformat() if row["updated_at"] else None,
        "char_limit":    8000,
    }


@router.put("/settings/ai-guidance")
async def save_ai_guidance(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """Upsert this tenant's AI guidance text. Body: {guidance_text: str}."""
    ctx = _require_context(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    guidance = (body.get("guidance_text") or "").strip()
    if len(guidance) > 8000:
        raise HTTPException(400, "guidance_text exceeds 8000 characters")

    await db.execute(
        text("""
            INSERT INTO operator_ai_guidance (company_id, guidance_text, updated_by)
            VALUES (CAST(:tid AS uuid), :g, :who)
            ON CONFLICT (company_id) DO UPDATE SET
                guidance_text = EXCLUDED.guidance_text,
                updated_by    = EXCLUDED.updated_by,
                updated_at    = NOW()
        """),
        {"tid": ctx["tenant_id"], "g": guidance, "who": ctx.get("email", "")},
    )
    await db.commit()
    return {
        "ok": True,
        "guidance_text": guidance,
        "char_count": len(guidance),
        "char_limit": 8000,
    }


# ═════════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/notifications")
async def list_notifications(
    request: Request,
    limit: int = 20,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    try:
        if not await _table_columns(db, "operator_notifications"):
            return {"notifications": [], "unread_count": 0}
        recipient_filter = await _notification_recipient_filter_sql(db)
        rows = (await db.execute(
            text(f"""
                SELECT notification_id, kind, severity, title, body,
                       link_target, link_label, read_at, created_at
                FROM operator_notifications
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND {recipient_filter}
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {"tid": ctx["tenant_id"], "oid": ctx["operator_id"], "limit": min(limit, 100)},
        )).mappings().all()

        unread = (await db.execute(
            text(f"""
                SELECT COUNT(*) FROM operator_notifications
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND read_at IS NULL
                  AND {recipient_filter}
            """),
            {"tid": ctx["tenant_id"], "oid": ctx["operator_id"]},
        )).scalar() or 0

        return {
            "notifications": [_serialize(dict(r)) for r in rows],
            "unread_count": int(unread),
        }
    except Exception as e:
        await _rollback_quietly(db)
        logger.exception("[Notifications] list failed")
        raise HTTPException(500, f"Notifications failed: {e}")


@router.post("/notifications/read-all")
async def mark_all_notifications_read(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    recipient_filter = await _notification_recipient_filter_sql(db)
    await db.execute(
        text(f"""
            UPDATE operator_notifications
            SET read_at = NOW()
            WHERE tenant_id = CAST(:tid AS uuid)
              AND read_at IS NULL
              AND {recipient_filter}
        """),
        {"tid": ctx["tenant_id"], "oid": ctx["operator_id"]},
    )
    await db.commit()
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════════════
# MESSAGING OBSERVABILITY
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/messaging-observability")
async def messaging_observability(
    request: Request,
    days: int = 7,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    if not await _table_columns(db, "message_normalizations"):
        return {
            "available": False,
            "summary": "Messaging observability not available yet",
            "window_days": max(1, min(days, 30)),
        }

    days = max(1, min(days, 30))
    try:
        counts = (await db.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE COALESCE(draft_source, '') = 'model') AS model_count,
                    COUNT(*) FILTER (WHERE COALESCE(draft_source, '') <> '' AND COALESCE(draft_source, '') <> 'model') AS fallback_count,
                    COUNT(*) FILTER (WHERE COALESCE(route_outcome, '') ILIKE '%fallback%') AS route_fallback_count,
                    COUNT(*) FILTER (WHERE COALESCE(selected_property_code, '') <> '') AS property_bound_count,
                    COUNT(*) FILTER (WHERE latest_turn_extracted IS TRUE) AS latest_turn_count
                FROM message_normalizations
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND sent_at >= NOW() - (:days || ' days')::interval
            """),
            {"tid": ctx["tenant_id"], "days": str(days)},
        )).mappings().first() or {}

        parser_rows = (await db.execute(
            text("""
                SELECT COALESCE(parser_used, 'unknown') AS parser_used, COUNT(*) AS cnt
                FROM message_normalizations
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND sent_at >= NOW() - (:days || ' days')::interval
                GROUP BY COALESCE(parser_used, 'unknown')
                ORDER BY cnt DESC, parser_used ASC
                LIMIT 3
            """),
            {"tid": ctx["tenant_id"], "days": str(days)},
        )).mappings().all()

        route_rows = (await db.execute(
            text("""
                SELECT COALESCE(route_outcome, 'unknown') AS route_outcome, COUNT(*) AS cnt
                FROM message_normalizations
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND sent_at >= NOW() - (:days || ' days')::interval
                GROUP BY COALESCE(route_outcome, 'unknown')
                ORDER BY cnt DESC, route_outcome ASC
                LIMIT 3
            """),
            {"tid": ctx["tenant_id"], "days": str(days)},
        )).mappings().all()

        total = int(counts.get("total") or 0)
        model_count = int(counts.get("model_count") or 0)
        fallback_count = int(counts.get("fallback_count") or 0)
        property_bound_count = int(counts.get("property_bound_count") or 0)
        latest_turn_count = int(counts.get("latest_turn_count") or 0)

        return {
            "available": True,
            "window_days": days,
            "total_messages": total,
            "model_count": model_count,
            "fallback_count": fallback_count,
            "route_fallback_count": int(counts.get("route_fallback_count") or 0),
            "property_bound_count": property_bound_count,
            "latest_turn_count": latest_turn_count,
            "parser_mix": [
                {"parser_used": r["parser_used"], "count": int(r["cnt"] or 0)}
                for r in parser_rows
            ],
            "route_mix": [
                {"route_outcome": r["route_outcome"], "count": int(r["cnt"] or 0)}
                for r in route_rows
            ],
        }
    except Exception as e:
        logger.exception("[MessagingObservability] failed")
        raise HTTPException(500, f"Messaging observability failed: {e}")


@router.get("/messaging-events")
async def messaging_events(
    request: Request,
    limit: int = 12,
    composer_only: bool = False,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    if not await _table_columns(db, "message_normalizations"):
        return {
            "events": [],
            "count": 0,
            "available": False,
            "composer_rows": [],
            "composer_count": 0,
        }

    limit = max(1, min(limit, 50))

    if composer_only:
        try:
            rows = (await db.execute(
                text("""
                    SELECT
                        source_message_id,
                        sender_display_name,
                        sender_address,
                        sent_at,
                        selected_property_code,
                        latest_guest_turn,
                        route_outcome,
                        draft_source,
                        fallback_reason,
                        composer_source,
                        composer_response_text,
                        composer_latency_ms,
                        composer_input_tokens,
                        composer_output_tokens,
                        composer_notes
                    FROM message_normalizations
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND composer_source IS NOT NULL
                    ORDER BY sent_at DESC
                    LIMIT :limit
                """),
                {"tid": ctx["tenant_id"], "limit": limit},
            )).mappings().all()

            composer_rows = []
            for r in rows:
                guest_turn = (r["latest_guest_turn"] or "")
                composer_text = (r["composer_response_text"] or "")
                notes_raw = r["composer_notes"]
                if isinstance(notes_raw, str):
                    try:
                        notes = json.loads(notes_raw)
                    except Exception:
                        notes = []
                elif isinstance(notes_raw, list):
                    notes = notes_raw
                else:
                    notes = []

                composer_rows.append({
                    "source_message_id": r["source_message_id"],
                    "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
                    "guest_name": r["sender_display_name"] or r["sender_address"] or "",
                    "property_code": r["selected_property_code"] or "",
                    "latest_guest_turn": guest_turn[:240],
                    "guest_turn_truncated": len(guest_turn) > 240,
                    "composer_active": True,
                    "composer_source": r["composer_source"] or "",
                    "composer_response_text": composer_text[:400],
                    "composer_text_truncated": len(composer_text) > 400,
                    "composer_latency_ms": int(r["composer_latency_ms"]) if r["composer_latency_ms"] is not None else None,
                    "composer_input_tokens": int(r["composer_input_tokens"]) if r["composer_input_tokens"] is not None else None,
                    "composer_output_tokens": int(r["composer_output_tokens"]) if r["composer_output_tokens"] is not None else None,
                    "composer_notes": notes,
                    "draft_source": r["draft_source"] or "",
                    "route_outcome": r["route_outcome"] or "",
                    "fallback_reason": r["fallback_reason"] or "",
                })

            return {
                "events": [],
                "count": 0,
                "available": True,
                "composer_rows": composer_rows,
                "composer_count": len(composer_rows),
            }
        except Exception as e:
            logger.exception("[MessagingEvents] composer_only path failed")
            raise HTTPException(500, f"Messaging events failed: {e}")

    try:
        rows = (await db.execute(
            text("""
                SELECT
                    source_message_id,
                    sender_display_name,
                    sender_address,
                    sent_at,
                    selected_property_code,
                    selected_property_match_type,
                    parser_used,
                    latest_turn_extracted,
                    latest_turn_confidence,
                    route_outcome,
                    draft_source,
                    fallback_reason
                FROM message_normalizations
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND (
                    COALESCE(draft_source, '') <> 'model'
                    OR COALESCE(route_outcome, '') ILIKE '%fallback%'
                    OR COALESCE(selected_property_code, '') = ''
                    OR latest_turn_extracted IS FALSE
                  )
                ORDER BY sent_at DESC
                LIMIT :limit
            """),
            {"tid": ctx["tenant_id"], "limit": limit},
        )).mappings().all()

        events = []
        for r in rows:
            draft_source = (r["draft_source"] or "").strip()
            route_outcome = (r["route_outcome"] or "").strip()
            property_code = (r["selected_property_code"] or "").strip()
            latest_turn_ok = bool(r["latest_turn_extracted"])
            severity = "info"
            title = "Messaging event"
            body = ""
            if draft_source and draft_source != "model":
                severity = "warning"
                title = f"Draft used {draft_source.replace('_', ' ')}"
                body = r["fallback_reason"] or "A recent inbound message did not stay on the model-generated draft path."
            elif route_outcome and "fallback" in route_outcome.lower():
                severity = "warning"
                title = f"Route outcome {route_outcome.replace('_', ' ')}"
                body = r["fallback_reason"] or "Routing fell back to a safer path."
            elif not property_code:
                severity = "warning"
                title = "Property binding needs review"
                body = "A recent inbound message did not bind to a property code."
            elif not latest_turn_ok:
                severity = "medium"
                title = "Latest guest turn was not cleanly extracted"
                body = "Thread parsing may need review for this message."

            who = r["sender_display_name"] or r["sender_address"] or "Guest"
            details = []
            if who:
                details.append(f"from {who}")
            if property_code:
                details.append(f"property {property_code}")
            if r["parser_used"]:
                details.append(f"parser {r['parser_used']}")
            if r["selected_property_match_type"]:
                details.append(f"match {r['selected_property_match_type']}")
            if r["latest_turn_confidence"] is not None:
                details.append(f"turn {round(float(r['latest_turn_confidence']) * 100)}%")
            if details:
                body = (body + " " + " · ".join(details)).strip()

            events.append({
                "event_id": f"msg::{r['source_message_id']}",
                "severity": severity,
                "title": title,
                "body": body,
                "link_target": "prebooking",
                "link_label": "Open Pre-Booking",
                "created_at": r["sent_at"].isoformat() if r["sent_at"] else None,
            })

        return {
            "events": events,
            "count": len(events),
            "available": True,
            "composer_rows": [],
            "composer_count": 0,
        }
    except Exception as e:
        logger.exception("[MessagingEvents] failed")
        raise HTTPException(500, f"Messaging events failed: {e}")


@router.get("/market-intelligence")
async def operator_market_intelligence(
    request: Request,
    days: int = 30,
    db: AsyncSession = Depends(get_async_session),
):
    ctx = _require_context(request)
    days = max(7, min(int(days or 30), 90))
    try:
        market_id = await _resolve_market_id_for_tenant(db, ctx["tenant_id"])
        today = date.today()
        window_end = today + timedelta(days=days)

        events_result = await db.execute(
            text(
                """
                SELECT
                    event_id, title, category, start_date, end_date,
                    venue_name, venue_address, description,
                    demand_impact_score, is_free, ticket_price_range,
                    ticket_url, is_multi_day, estimated_attendance
                FROM market_events
                WHERE market_id = :mid
                  AND start_date >= :today
                  AND start_date <= :end_date
                  AND is_active = true
                ORDER BY demand_impact_score DESC NULLS LAST, start_date ASC
                LIMIT 25
                """
            ),
            {"mid": market_id, "today": today, "end_date": window_end},
        )
        events = []
        for row in events_result.fetchall():
            impact = row[8] or 0
            impact_label = "High" if impact > 0.7 else ("Medium" if impact > 0.45 else "Low")
            events.append(
                {
                    "id": str(row[0]),
                    "title": row[1],
                    "category": row[2] or "other",
                    "start_date": row[3].isoformat() if row[3] else None,
                    "end_date": row[4].isoformat() if row[4] else None,
                    "venue": row[5],
                    "venue_address": row[6],
                    "description": (row[7] or "")[:200],
                    "demand_impact": round(impact, 2),
                    "demand_impact_label": impact_label,
                    "is_free": row[9],
                    "ticket_price": row[10],
                    "ticket_url": row[11],
                    "is_multi_day": row[12],
                    "estimated_attendance": row[13],
                }
            )

        cat_result = await db.execute(
            text(
                """
                SELECT category, COUNT(*) as cnt,
                       AVG(demand_impact_score) as avg_impact
                FROM market_events
                WHERE market_id = :mid
                  AND start_date >= :today
                  AND start_date <= :end_date
                  AND is_active = true
                GROUP BY category
                ORDER BY cnt DESC
                """
            ),
            {"mid": market_id, "today": today, "end_date": window_end},
        )
        categories = [
            {"category": row[0] or "other", "count": row[1], "avg_impact": round(row[2] or 0, 2)}
            for row in cat_result.fetchall()
        ]

        peak_result = await db.execute(
            text(
                """
                SELECT
                    start_date,
                    COUNT(*) as event_count,
                    SUM(COALESCE(demand_impact_score, 0.3)) as total_impact,
                    string_agg(title, ', ' ORDER BY demand_impact_score DESC NULLS LAST) as event_titles
                FROM market_events
                WHERE market_id = :mid
                  AND start_date >= :today
                  AND start_date <= :end_date
                  AND is_active = true
                GROUP BY start_date
                HAVING COUNT(*) > 1 OR SUM(COALESCE(demand_impact_score, 0.3)) > 0.6
                ORDER BY total_impact DESC
                LIMIT 8
                """
            ),
            {"mid": market_id, "today": today, "end_date": window_end},
        )
        peak_dates = [
            {
                "date": row[0].isoformat(),
                "event_count": row[1],
                "total_impact": round(row[2], 2),
                "events": row[3][:80] + "..." if row[3] and len(row[3]) > 80 else row[3],
            }
            for row in peak_result.fetchall()
        ]

        signals_result = await db.execute(
            text(
                """
                SELECT signal_type, value, confidence,
                       detected_at, metadata, valid_from, valid_until
                FROM signals
                WHERE geo_id = :mid
                  AND signal_type = 'demand_pressure'
                  AND detected_at > NOW() - INTERVAL '30 days'
                ORDER BY detected_at DESC
                LIMIT 10
                """
            ),
            {"mid": market_id},
        )
        signals = []
        for row in signals_result.fetchall():
            meta = row[4] or {}
            signals.append(
                {
                    "type": row[0],
                    "value": round(row[1], 3),
                    "confidence": round(row[2], 2),
                    "detected_at": row[3].isoformat() if row[3] else None,
                    "explanation": meta.get("explanation", "") if isinstance(meta, dict) else "",
                    "valid_from": row[5].isoformat() if row[5] else None,
                    "valid_until": row[6].isoformat() if row[6] else None,
                }
            )

        registry_result = await db.execute(
            text(
                """
                SELECT market_name, state_code, last_scraped_at,
                       last_scrape_event_count, scrape_interval_hours
                FROM market_registry
                WHERE market_id = :mid
                """
            ),
            {"mid": market_id},
        )
        registry_row = registry_result.fetchone()
        market_info = {}
        if registry_row:
            market_info = {
                "name": registry_row[0],
                "state": registry_row[1],
                "last_scraped": registry_row[2].isoformat() if registry_row[2] else None,
                "total_events_on_file": registry_row[3] or 0,
                "scrape_interval_hours": registry_row[4],
            }

        high_impact_count = sum(1 for event in events if event["demand_impact"] > 0.7)
        total_events = len(events)
        avg_impact = sum(event["demand_impact"] for event in events) / total_events if total_events else 0
        demand_level = (
            "High" if avg_impact > 0.6 or high_impact_count >= 3 else
            "Elevated" if avg_impact > 0.4 or high_impact_count >= 1 else
            "Normal"
        )

        return {
            "market_id": market_id,
            "market": market_info,
            "window_days": days,
            "as_of": today.isoformat(),
            "demand_summary": {
                "level": demand_level,
                "total_events": total_events,
                "high_impact_events": high_impact_count,
                "avg_impact_score": round(avg_impact, 2),
                "peak_dates": peak_dates,
            },
            "events": events,
            "categories": categories,
            "signals": signals,
        }
    except Exception as exc:
        logger.warning("[MarketIntelligence] tenant-scoped API failed: %s", exc)
        await _rollback_quietly(db)
        return {
            "market_id": "30a_fl",
            "market": {"name": "Market not configured"},
            "window_days": days,
            "as_of": date.today().isoformat(),
            "demand_summary": {
                "level": "Unknown",
                "total_events": 0,
                "high_impact_events": 0,
                "avg_impact_score": 0,
                "peak_dates": [],
            },
            "events": [],
            "categories": [],
            "signals": [],
            "note": "Market data not yet available for this operator.",
        }


# ═════════════════════════════════════════════════════════════════════════════
# DASHBOARD SUMMARY — one call to populate the sidebar badges + overview cards
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/dashboard-summary")
async def dashboard_summary(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    started = time.perf_counter()
    ctx = _require_context(request)
    tid = ctx["tenant_id"]
    oid = ctx["operator_id"]

    try:
        scope_profile = await _scope_profile(request, db, ctx)
        property_meta = await _property_query_meta(db)
        inbox_row = await _resolved_inbox_status_row(db, oid, tid)
        notif_filter = "TRUE"
        if await _table_columns(db, "operator_notifications"):
            notif_filter = await _notification_recipient_filter_sql(db)
        payload = await get_dashboard_summary_service().build_summary(
            session=db,
            tenant_id=tid,
            operator_id=ctx["operator_id"],
            property_meta=property_meta,
            notification_filter_sql=notif_filter,
            inbox_row=inbox_row,
            visible_property_codes=sorted(scope_profile["visible_property_codes"]) if scope_profile["visible_property_codes"] is not None else None,
        )
        logger.info(
            "[DashboardSummary] tenant=%s operator=%s cache_source=%s elapsed_ms=%.1f",
            tid,
            oid,
            payload.get("cache_source", "unknown"),
            (time.perf_counter() - started) * 1000,
        )
        return payload
    except Exception as e:
        await _rollback_quietly(db)
        logger.exception("[DashboardSummary] failed")
        fallback = default_dashboard_summary()
        classified = _classify_db_exception(e)
        if classified:
            fallback["warning"] = classified.detail
        else:
            fallback["warning"] = "Dashboard summary is temporarily unavailable"
        return fallback


# ════════════════════════════════════════════════════════════════════════════
# ONBOARDING STATUS — drives the Overview checklist + dashboard-wide "Connect
# your inbox" banner. Tells the frontend which setup steps remain so we can
# walk operators through them without making them hunt.
# ════════════════════════════════════════════════════════════════════════════

@router.get("/onboarding-status")
async def onboarding_status(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Return a checklist of onboarding steps the operator still needs to complete.

    Each step has:
      - key: stable identifier for the frontend
      - title: human-readable label
      - done: bool — whether the step is complete
      - cta_label / cta_target: what to show if not done (navigation target or URL)
      - detail: optional status text shown beneath the step

    The frontend uses this to render:
      (1) the Setup Checklist card on the Overview page, and
      (2) a persistent top-of-dashboard banner when critical steps are incomplete
          (Gmail/inbox not connected is currently the only "critical" step).
    """
    ctx = _require_context(request)
    tid = ctx["tenant_id"]
    oid = ctx["operator_id"]

    try:
        # ---- Inbox connection status (critical) ----
        inbox_connected = False
        inbox_email = None
        inbox_provider = None
        gmail_row = await _resolved_inbox_status_row(db, oid, tid)
        account_row = await _operator_inbox_account_row(db, oid, tid)
        if gmail_row and gmail_row["watched_email"]:
            inbox_connected = True
            inbox_email = gmail_row["watched_email"]
            inbox_provider = gmail_row["email_provider"] or "gmail"
        elif account_row and (account_row.get("messaging_email") or account_row.get("email")):
            inbox_email = account_row.get("messaging_email") or account_row.get("email")
            inbox_provider = account_row.get("email_provider") or "gmail"

        # ---- Properties status ----
        property_meta = await _property_query_meta(db)
        try:
            prop_count = (await db.execute(
                text(f"SELECT COUNT(*) FROM properties WHERE {property_meta['where_sql']}" if property_meta else "SELECT 0"),
                {"tid": tid},
            )).scalar() or 0
        except Exception:
            await _rollback_quietly(db)
            prop_count = 0

        try:
            if await _table_columns(db, "property_ai_autonomy"):
                properties_reviewed_count = (await db.execute(
                    text("""
                        SELECT COUNT(*) FROM property_ai_autonomy
                        WHERE tenant_id = CAST(:tid AS uuid)
                    """),
                    {"tid": tid},
                )).scalar() or 0
            else:
                properties_reviewed_count = 0
        except Exception:
            await _rollback_quietly(db)
            properties_reviewed_count = 0

        try:
            first_inquiry_row = (await db.execute(
                text("""
                    SELECT MIN(received_at) AS first_received
                    FROM pre_booking_inquiries
                    WHERE company_id = CAST(:tid AS uuid)
                """),
                {"tid": tid},
            )).fetchone()
            first_inquiry_at = first_inquiry_row[0] if first_inquiry_row else None
        except Exception:
            await _rollback_quietly(db)
            first_inquiry_at = None

        steps = [
            {
                "key": "connect_inbox",
                "title": "Connect your guest messaging inbox",
                "detail": (
                    (
                        f"Connected: {inbox_email}"
                        + (f" · last polled {gmail_row['last_polled_at'].strftime('%b %d %I:%M %p')}" if inbox_connected and gmail_row and gmail_row.get("last_polled_at") else "")
                        + (f" · {gmail_row['last_poll_summary']}" if inbox_connected and gmail_row and gmail_row.get("last_poll_summary") else "")
                    ) if inbox_connected
                    else (
                        f"Configured inbox: {inbox_email}. Connect your inbox provider so guest inquiries start flowing in."
                        if inbox_email
                        else "Connect your inbox provider so guest inquiries start flowing in."
                    )
                ),
                "done": inbox_connected,
                "critical": True,
                "type": "action",
                "visible_when_complete": True,
                "cta_label": "Reconnect inbox" if inbox_connected else "Connect now",
                "cta_target": "/app/connect-gmail",
                "provider": inbox_provider,
            },
            {
                "key": "review_properties",
                "title": "Review your properties",
                "detail": (
                    f"{prop_count} properties loaded. Visit Properties to review them and set AI response mode."
                    if prop_count > 0
                    else "No properties loaded yet. Contact support to import them."
                ),
                "done": properties_reviewed_count > 0,
                "critical": False,
                "type": "action",
                "visible_when_complete": True,
                "cta_label": "Review",
                "cta_target": "properties",
                "count": prop_count,
            },
            {
                "key": "first_inquiry",
                "title": "Receive your first guest inquiry",
                "detail": (
                    f"First inquiry received {first_inquiry_at.strftime('%b %d')}."
                    if first_inquiry_at
                    else "Once your inbox is connected and forwarded, inquiries appear in Messages."
                ),
                "done": first_inquiry_at is not None,
                "critical": False,
                "type": "milestone",
                "visible_when_complete": False,
                "cta_label": "Open messages" if first_inquiry_at else None,
                "cta_target": "prebooking" if first_inquiry_at else None,
            },
        ]

        total = len(steps)
        completed = sum(1 for s in steps if s["done"])
        percent_complete = int(100 * completed / total) if total else 0
        critical_incomplete = next(
            (s for s in steps if s["critical"] and not s["done"]),
            None,
        )

        return {
            "steps": steps,
            "percent_complete": percent_complete,
            "completed": completed,
            "total": total,
            "inbox_connected": inbox_connected,
            "inbox_status": {
                "email": inbox_email,
                "provider": inbox_provider,
                "last_polled_at": gmail_row["last_polled_at"].isoformat() if inbox_connected and gmail_row and gmail_row.get("last_polled_at") else None,
                "last_poll_success": bool(gmail_row["last_poll_success"]) if inbox_connected and gmail_row and gmail_row.get("last_poll_success") is not None else None,
                "last_poll_summary": gmail_row["last_poll_summary"] if inbox_connected and gmail_row else None,
                "last_poll_error": gmail_row["last_poll_error"] if inbox_connected and gmail_row else None,
                "last_messages_found": int(gmail_row["last_messages_found"] or 0) if inbox_connected and gmail_row and gmail_row.get("last_messages_found") is not None else None,
                "last_new_pending_inquiries": int(gmail_row["last_new_pending_inquiries"] or 0) if inbox_connected and gmail_row and gmail_row.get("last_new_pending_inquiries") is not None else None,
                "last_query_mode": gmail_row["last_query_mode"] if inbox_connected and gmail_row else None,
            },
            "critical_incomplete": critical_incomplete,
            "degraded": False,
        }
    except Exception as e:
        await _rollback_quietly(db)
        logger.exception("[OnboardingStatus] failed")
        fallback = _default_onboarding_status()
        classified = _classify_db_exception(e)
        if classified:
            fallback["warning"] = classified.detail
        else:
            fallback["warning"] = "Onboarding data is temporarily unavailable"
        return fallback


# ═════════════════════════════════════════════════════════════════════════════
# PROPERTY AI AUTONOMY — operator toggle for auto-send vs. review per property
# ═════════════════════════════════════════════════════════════════════════════
# MVP: one setting per property (stage='all'). Future: per-stage granularity.
# Backed by migration 027's property_ai_autonomy table.

@router.get("/properties/autonomy")
async def list_properties_with_autonomy(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Return every property for this tenant with its current autonomy setting.
    Used by the Properties page to render toggles on each row.
    """
    ctx = _require_context(request)
    rows = (await db.execute(
        text("""
            SELECT
                p.id,
                p.property_code,
                p.external_id,
                p.address_street,
                p.address_city,
                p.address_state,
                p.address_zip,
                p.community,
                p.bedrooms,
                p.bathrooms,
                p.sleeps,
                p.property_type,
                p.has_pool,
                p.has_hot_tub,
                p.pets_allowed,
                p.data_source,
                p.created_at,
                a.stage,
                COALESCE(a.approval_mode, 'required')          AS approval_mode,
                COALESCE(a.min_confidence_for_auto, 0.95)      AS min_confidence_for_auto,
                a.auto_enabled_at,
                a.auto_enabled_by,
                r.approval_mode                                 AS pre_booking_approval_mode,
                r.approval_mode_set_at                          AS pre_booking_approval_mode_set_at,
                r.approval_mode_set_by                          AS pre_booking_approval_mode_set_by
            FROM properties p
            LEFT JOIN property_ai_autonomy a
                ON a.property_id = p.id
            LEFT JOIN property_rollout_phases r
                ON r.company_id = CAST(:tid AS uuid)
               AND r.property_id = p.property_code
            WHERE p.tenant_id = CAST(:tid AS uuid)
              AND COALESCE(p.is_active, TRUE) = TRUE
            ORDER BY p.address_street ASC NULLS LAST, a.stage ASC NULLS LAST
        """),
        {"tid": ctx["tenant_id"]},
    )).mappings().all()

    def _lane_payload(stage: str, approval_mode: str, min_confidence: float, enabled_at, enabled_by):
        return {
            "stage": stage,
            "approval_mode": approval_mode,
            "min_confidence_for_auto": float(min_confidence),
            "auto_enabled_at": enabled_at.isoformat() if enabled_at else None,
            "auto_enabled_by": enabled_by,
        }

    def _derive_lane(stages: dict, target: str):
        if target == "pre_booking":
            exact = stages.get("pre_booking_rollout")
            if exact:
                return {**exact, "source_stage": "pre_booking"}
            return {
                "stage": "pre_booking",
                "approval_mode": "required",
                "min_confidence_for_auto": 0.95,
                "auto_enabled_at": None,
                "auto_enabled_by": None,
                "source_stage": "default",
            }
        guest_stage_keys = ("booked_pre_arrival", "in_stay", "post_stay")
        guest_exact = [stages.get(key) for key in guest_stage_keys if stages.get(key)]
        if guest_exact:
            modes = {item["approval_mode"] for item in guest_exact}
            if len(modes) == 1:
                mode = guest_exact[0]["approval_mode"]
                min_conf = min(item["min_confidence_for_auto"] for item in guest_exact)
                return {
                    "stage": "guest_sessions",
                    "approval_mode": mode,
                    "min_confidence_for_auto": min_conf,
                    "auto_enabled_at": guest_exact[0]["auto_enabled_at"],
                    "auto_enabled_by": guest_exact[0]["auto_enabled_by"],
                    "source_stage": "guest_sessions_exact",
                }
            return {
                "stage": "guest_sessions",
                "approval_mode": "mixed",
                "min_confidence_for_auto": min(item["min_confidence_for_auto"] for item in guest_exact),
                "auto_enabled_at": None,
                "auto_enabled_by": None,
                "source_stage": "guest_sessions_mixed",
            }
        fallback = stages.get("all")
        return {**fallback, "stage": "guest_sessions", "source_stage": "all"} if fallback else {
            "stage": "guest_sessions",
            "approval_mode": "required",
            "min_confidence_for_auto": 0.95,
            "auto_enabled_at": None,
            "auto_enabled_by": None,
            "source_stage": "default",
        }

    items_by_id: dict[str, dict] = {}
    for r in rows:
        pid = str(r["id"])
        item = items_by_id.get(pid)
        if item is None:
            item = {
                "id":              pid,
                "property_code":   r["property_code"],
                "external_id":     r["external_id"],
                "address_street":  r["address_street"],
                "address_city":    r["address_city"],
                "address_state":   r["address_state"],
                "address_zip":     r["address_zip"],
                "community":       r["community"],
                "bedrooms":        r["bedrooms"],
                "bathrooms":       r["bathrooms"],
                "sleeps":          r["sleeps"],
                "property_type":   r["property_type"],
                "has_pool":        r["has_pool"],
                "has_hot_tub":     r["has_hot_tub"],
                "pets_allowed":    r["pets_allowed"],
                "data_source":     r["data_source"],
                "created_at":      r["created_at"].isoformat() if r["created_at"] else None,
                "autonomy_by_stage": {},
            }
            items_by_id[pid] = item
        stage = (r["stage"] or "all").strip()
        item["autonomy_by_stage"][stage] = _lane_payload(
            stage,
            r["approval_mode"],
            r["min_confidence_for_auto"],
            r["auto_enabled_at"],
            r["auto_enabled_by"],
        )
        if "pre_booking_rollout" not in item["autonomy_by_stage"]:
            item["autonomy_by_stage"]["pre_booking_rollout"] = _lane_payload(
                "pre_booking",
                (r["pre_booking_approval_mode"] or "required"),
                0.95,
                r["pre_booking_approval_mode_set_at"],
                r["pre_booking_approval_mode_set_by"],
            )

    items = []
    for item in items_by_id.values():
        stages = item["autonomy_by_stage"]
        overall = stages.get("all") or {
            "stage": "all",
            "approval_mode": "required",
            "min_confidence_for_auto": 0.95,
            "auto_enabled_at": None,
            "auto_enabled_by": None,
        }
        pre_booking = _derive_lane(stages, "pre_booking")
        guest_sessions = _derive_lane(stages, "guest_sessions")
        items.append({
            **item,
            "approval_mode": overall["approval_mode"],
            "min_confidence_for_auto": float(overall["min_confidence_for_auto"]),
            "auto_enabled_at": overall["auto_enabled_at"],
            "auto_enabled_by": overall["auto_enabled_by"],
            "autonomy": {
                "all": overall,
                "pre_booking": pre_booking,
                "guest_sessions": guest_sessions,
            },
        })

    auto_count = sum(1 for i in items if i["approval_mode"] == "auto")
    pre_booking_auto_count = sum(1 for i in items if i["autonomy"]["pre_booking"]["approval_mode"] == "auto")
    guest_sessions_auto_count = sum(1 for i in items if i["autonomy"]["guest_sessions"]["approval_mode"] == "auto")
    return {
        "properties": items,
        "count": len(items),
        "summary": {
            "total":        len(items),
            "auto":         auto_count,
            "review":       len(items) - auto_count,
            "auto_count":   auto_count,
            "review_count": len(items) - auto_count,
            "pre_booking_auto_count": pre_booking_auto_count,
            "pre_booking_review_count": len(items) - pre_booking_auto_count,
            "guest_sessions_auto_count": guest_sessions_auto_count,
            "guest_sessions_review_count": len(items) - guest_sessions_auto_count,
        },
    }


@router.patch("/properties/{property_id}/autonomy")
async def update_property_autonomy(
    property_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Set the autonomy mode for a single property. Body:
        {
          "approval_mode": "auto" | "required",
          "min_confidence_for_auto": 0.95   (optional, default 0.95)
        }
    """
    ctx = _require_context(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    approval_mode = (body.get("approval_mode") or "").strip().lower()
    if approval_mode not in ("auto", "required"):
        raise HTTPException(400, "approval_mode must be 'auto' or 'required'")
    stage_scope = (body.get("stage_scope") or body.get("stage") or "all").strip().lower()
    if stage_scope not in ("all", "pre_booking", "guest_sessions"):
        raise HTTPException(400, "stage_scope must be 'all', 'pre_booking', or 'guest_sessions'")

    min_conf = body.get("min_confidence_for_auto")
    if min_conf is None:
        min_conf = 0.95
    try:
        min_conf = float(min_conf)
    except (TypeError, ValueError):
        raise HTTPException(400, "min_confidence_for_auto must be a number")
    if not (0 <= min_conf <= 1):
        raise HTTPException(400, "min_confidence_for_auto must be between 0 and 1")

    # Verify the property belongs to this tenant (defense-in-depth)
    owns = (await db.execute(
        text("""
            SELECT 1 FROM properties
            WHERE id = CAST(:pid AS uuid) AND tenant_id = CAST(:tid AS uuid)
            LIMIT 1
        """),
        {"pid": property_id, "tid": ctx["tenant_id"]},
    )).fetchone()
    if not owns:
        raise HTTPException(404, "Property not found")

    property_row = (await db.execute(
        text("""
            SELECT id, property_code
            FROM properties
            WHERE id = CAST(:pid AS uuid) AND tenant_id = CAST(:tid AS uuid)
            LIMIT 1
        """),
        {"pid": property_id, "tid": ctx["tenant_id"]},
    )).mappings().first()
    if not property_row:
        raise HTTPException(404, "Property not found")

    from app.services.messaging.autonomy_gate import set_property_autonomy
    from app.services.staged_rollout import ApprovalMode, get_rollout_service
    import uuid as _uuid

    if stage_scope in ("pre_booking", "all"):
        rollout_service = get_rollout_service(db)
        ok = await rollout_service.set_approval_mode(
            ctx["tenant_id"],
            property_row["property_code"],
            ApprovalMode(approval_mode),
            set_by=ctx.get("email", "") or "operator",
        )
        if not ok:
            raise HTTPException(500, "Failed to update pre-booking approval mode")

    if stage_scope in ("guest_sessions", "all"):
        stages = ["all"] if stage_scope == "all" else ["booked_pre_arrival", "in_stay", "post_stay"]
        for stage in stages:
            await set_property_autonomy(
                db,
                tenant_id=_uuid.UUID(ctx["tenant_id"]),
                property_id=_uuid.UUID(str(property_row["id"])),
                approval_mode=approval_mode,
                stage=stage,
                min_confidence_for_auto=min_conf,
                changed_by=ctx.get("email", ""),
            )

    return {
        "ok": True,
        "property_id": property_id,
        "stage_scope": stage_scope,
        "approval_mode": approval_mode,
        "min_confidence_for_auto": min_conf,
    }


@router.post("/properties/autonomy/bulk")
async def bulk_update_property_autonomy(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Apply the same autonomy mode to many properties at once. Operators with
    50+ properties will want this ("set all to auto-send"). Body:
        {
          "property_ids": ["<uuid>", "<uuid>", ...],  # or [] to mean ALL
          "approval_mode": "auto" | "required",
          "min_confidence_for_auto": 0.95  (optional)
        }
    """
    ctx = _require_context(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    approval_mode = (body.get("approval_mode") or "").strip().lower()
    if approval_mode not in ("auto", "required"):
        raise HTTPException(400, "approval_mode must be 'auto' or 'required'")
    stage_scope = (body.get("stage_scope") or body.get("stage") or "all").strip().lower()
    if stage_scope not in ("all", "pre_booking", "guest_sessions"):
        raise HTTPException(400, "stage_scope must be 'all', 'pre_booking', or 'guest_sessions'")
    min_conf = float(body.get("min_confidence_for_auto") or 0.95)
    if not (0 <= min_conf <= 1):
        raise HTTPException(400, "min_confidence_for_auto must be between 0 and 1")

    ids = body.get("property_ids") or []
    if ids:
        # Validate every id belongs to this tenant
        rows = (await db.execute(
            text("""
                SELECT id FROM properties
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND id = ANY(CAST(:ids AS uuid[]))
            """),
            {"tid": ctx["tenant_id"], "ids": ids},
        )).fetchall()
        valid_ids = [str(r[0]) for r in rows]
        if len(valid_ids) != len(ids):
            raise HTTPException(400, "One or more property_ids are invalid for this tenant")
    else:
        # Apply to ALL properties for this tenant
        rows = (await db.execute(
            text("SELECT id FROM properties WHERE tenant_id = CAST(:tid AS uuid) AND COALESCE(is_active, TRUE) = TRUE"),
            {"tid": ctx["tenant_id"]},
        )).fetchall()
        valid_ids = [str(r[0]) for r in rows]

    property_rows = (await db.execute(
        text("""
            SELECT id, property_code
            FROM properties
            WHERE tenant_id = CAST(:tid AS uuid)
              AND id = ANY(CAST(:ids AS uuid[]))
        """),
        {"tid": ctx["tenant_id"], "ids": valid_ids},
    )).mappings().all()

    from app.services.messaging.autonomy_gate import set_property_autonomy
    from app.services.staged_rollout import ApprovalMode, get_rollout_service
    import uuid as _uuid
    tenant_uuid = _uuid.UUID(ctx["tenant_id"])
    by = ctx.get("email", "")
    rollout_service = get_rollout_service(db)
    count = 0
    guest_stages = ["all"] if stage_scope == "all" else ["booked_pre_arrival", "in_stay", "post_stay"]
    for row in property_rows:
        if stage_scope in ("pre_booking", "all"):
            ok = await rollout_service.set_approval_mode(
                ctx["tenant_id"],
                row["property_code"],
                ApprovalMode(approval_mode),
                set_by=by or "operator",
            )
            if not ok:
                raise HTTPException(500, f"Failed to update pre-booking approval mode for {row['property_code']}")
        if stage_scope in ("guest_sessions", "all"):
            for stage in guest_stages:
                await set_property_autonomy(
                    db,
                    tenant_id=tenant_uuid,
                    property_id=_uuid.UUID(str(row["id"])),
                    approval_mode=approval_mode,
                    stage=stage,
                    min_confidence_for_auto=min_conf,
                    changed_by=by,
                )
        count += 1

    return {"ok": True, "updated": count, "approval_mode": approval_mode, "stage_scope": stage_scope}
