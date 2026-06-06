"""
audit.py — Operator Audit Export API

GET /api/v1/audit/export   — Export full audit trail as JSON or CSV
GET /api/v1/audit/summary  — Summary counts for dashboard widget
"""

import csv
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.database import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/audit", tags=["Audit"])


def _tenant_from_request(request: Optional[Request]) -> Optional[str]:
    """Resolve the authenticated operator's tenant_id from the JWT cookie.

    Returns None if the request isn't authenticated, in which case callers
    should fall back to DEFAULT_TENANT_ID (keeps public endpoints working).
    """
    if request is None:
        return None
    try:
        import base64 as _b64, time as _time
        token = request.cookies.get("oyvoda_access")
        if not token:
            return None
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = json.loads(_b64.urlsafe_b64decode(parts[1] + "=="))
        if payload.get("exp", 0) < _time.time():
            return None
        # Explicit tenant claim first; falls back to sub for legacy tokens.
        return payload.get("tid") or payload.get("sub")
    except Exception:
        return None


def _looks_like_uuid(s: str) -> bool:
    """Cheap UUID shape check so we don't pass non-UUID strings to Postgres."""
    if not s or not isinstance(s, str):
        return False
    if len(s) != 36:
        return False
    # 8-4-4-4-12 hex layout
    parts = s.split("-")
    if len(parts) != 5:
        return False
    return [len(p) for p in parts] == [8, 4, 4, 4, 12] and all(
        all(c in "0123456789abcdefABCDEF" for c in p) for p in parts
    )


def _ts(dt) -> str:
    if not dt:
        return ""
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(dt)


async def _get_operator_id(request=None) -> str:
    """Extract operator/company_id from request. Defaults to demo tenant."""
    from app.services.concierge.db_session_service import DEFAULT_TENANT_ID
    return DEFAULT_TENANT_ID


async def _safe_count(
    db,
    *,
    label: str,
    sql: str,
    params: dict,
) -> tuple[int, Optional[str]]:
    """Run a single COUNT inside a SAVEPOINT so a failure here cannot
    poison the outer session for subsequent queries.

    Returns ``(count, error_summary)``. On success, ``error_summary`` is
    ``None``. On failure the SAVEPOINT is rolled back, a warning is
    logged with the table label, and we return ``(0, "<ErrorType>: <msg>")``
    so the response can surface which specific count failed instead of
    pretending everything succeeded with zero.

    Previously this endpoint wrapped each count in a bare ``try/except``
    that swallowed the exception without rolling back — once Postgres
    aborted the transaction (e.g. a missing-column error against a
    renamed table), every subsequent query in the same request hit
    ``InFailedSQLTransactionError``. Using ``begin_nested()`` scopes the
    failure so the outer transaction stays usable.
    """
    from sqlalchemy import text as _sa_text
    try:
        async with db.begin_nested():
            result = await db.execute(_sa_text(sql), params)
            value = result.scalar()
            return int(value or 0), None
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[Audit] count %s failed: %s: %s",
            label,
            type(exc).__name__,
            str(exc)[:200],
        )
        return 0, f"{type(exc).__name__}: {str(exc)[:200]}"


@router.get("/summary")
async def audit_summary(
    request: Request,
    days: int = Query(default=30, ge=1, le=365, description="Lookback window in days"),
):
    """Quick summary counts for the dashboard widget, scoped to the
    currently authenticated operator's tenant.

    Falls back to DEFAULT_TENANT_ID only if there is no JWT cookie (keeps
    unauthenticated / legacy callers working without leaking cross-tenant data).

    Each count runs inside its own SAVEPOINT via ``_safe_count`` so that
    a failure in one query (e.g. table renamed, column missing) cannot
    leave the session in aborted state and cascade-fail every subsequent
    count with ``InFailedSQLTransactionError``. Per-count failures are
    logged and reported back in the ``_count_errors`` field so dashboard
    consumers can distinguish "zero rows" from "this count is broken."
    """
    # Diagnostic marker - prove this version is deployed.
    _VERSION = "audit-v5-kb-from-scoped-knowledge"
    try:
        from app.core.database import get_db_session
        from app.services.concierge.db_session_service import DEFAULT_TENANT_ID

        since = datetime.now(timezone.utc) - timedelta(days=days)

        # Resolve tenant: prefer JWT tid, then scoped_op lookup, then fallback.
        tenant_id = _tenant_from_request(request)
        resolution_path = "jwt_tid" if tenant_id else "unknown"

        # If the caller is a super admin who has NOT scoped into any operator,
        # _tenant_from_request returns 'sa_001' (the sub claim), which isn't a
        # valid UUID. In that case, show platform-wide zeros rather than
        # erroring out.
        if tenant_id and not _looks_like_uuid(tenant_id):
            return {
                "period_days": days,
                "tenant_id": tenant_id,
                "guest_sessions": 0,
                "messages_processed": 0,
                "pre_booking_drafts": 0,
                "kb_entries_added": 0,
                "escalations": 0,
                "properties": 0,
                "kb_gaps": 0,
                "note": "Super admin platform-wide view — scope into an operator to see their counts.",
                "_version": _VERSION,
                "_resolution": resolution_path,
            }

        if not tenant_id:
            tenant_id = str(DEFAULT_TENANT_ID)
            resolution_path = "default_fallback"

        count_errors: dict[str, str] = {}

        async with get_db_session() as db:
            # Open an explicit outer transaction so begin_nested() inside
            # _safe_count has a clear parent to attach SAVEPOINTs to.
            # Without this the first savepoint would have to implicitly
            # open the outer transaction — which works in practice on
            # SQLAlchemy 2.x but is less obvious to reason about and less
            # robust against future session-config changes.
            async with db.begin():
                sessions_count, err = await _safe_count(
                    db,
                    label="guest_sessions",
                    sql="""
                        SELECT COUNT(*) FROM concierge_guest_sessions
                        WHERE created_at >= :since
                          AND tenant_id = CAST(:tid AS uuid)
                    """,
                    params={"since": since, "tid": tenant_id},
                )
                if err:
                    count_errors["guest_sessions"] = err

                messages_count, err = await _safe_count(
                    db,
                    label="messages_processed",
                    sql="""
                        SELECT COUNT(*) FROM concierge_messages m
                        JOIN concierge_guest_sessions s ON s.session_id = m.session_id
                        WHERE m.created_at >= :since
                          AND s.tenant_id = CAST(:tid AS uuid)
                    """,
                    params={"since": since, "tid": tenant_id},
                )
                if err:
                    count_errors["messages_processed"] = err

                drafts_count, err = await _safe_count(
                    db,
                    label="pre_booking_drafts",
                    sql="""
                        SELECT COUNT(*) FROM pre_booking_inquiries
                        WHERE created_at >= :since
                          AND company_id = CAST(:tid AS uuid)
                    """,
                    params={"since": since, "tid": tenant_id},
                )
                if err:
                    count_errors["pre_booking_drafts"] = err

                kb_count, err = await _safe_count(
                    db,
                    label="kb_entries_added",
                    # The legacy SQL here was:
                    #     SELECT COALESCE(SUM(jsonb_array_length(faq)), 0)
                    #     FROM concierge_knowledge
                    #     WHERE tenant_id = CAST(:tid AS uuid)
                    # That query targeted migration 004's declared schema
                    # (one row per property with a JSONB `faq` array).
                    # Two things have happened since:
                    #   1. The live production `concierge_knowledge`
                    #      table has a per-row Q&A shape (category,
                    #      question, answer) and never carried a `faq`
                    #      column — hence the UndefinedColumnError we
                    #      surfaced via the audit-v4 savepoint counts.
                    #   2. The new brain path writes guidebook entries
                    #      via ScopedKnowledgeService into
                    #      `concierge_scoped_knowledge` (migration 059),
                    #      where each Q/A is its own row.
                    #      `concierge_knowledge` is the retiring legacy
                    #      path.
                    # Count active rows in the new scoped table — the
                    # source of truth the current ingest path actually
                    # writes to. The legacy SQL ignored :since, so this
                    # rewrite is also lifetime-scoped to preserve
                    # widget semantics. Switching to "added in last N
                    # days" would be a behavior change, not a fix.
                    sql="""
                        SELECT COUNT(*) FROM concierge_scoped_knowledge
                        WHERE tenant_id = CAST(:tid AS uuid)
                          AND is_active = true
                    """,
                    params={"tid": tenant_id},
                )
                if err:
                    count_errors["kb_entries_added"] = err

                esc_count, err = await _safe_count(
                    db,
                    label="escalations",
                    sql="""
                        SELECT COUNT(*) FROM concierge_escalations e
                        JOIN concierge_guest_sessions s ON s.token = e.session_token
                        WHERE e.status NOT IN ('resolved','dismissed')
                          AND s.tenant_id = CAST(:tid AS uuid)
                    """,
                    params={"tid": tenant_id},
                )
                if err:
                    count_errors["escalations"] = err

                props_count, err = await _safe_count(
                    db,
                    label="properties",
                    sql="""
                        SELECT COUNT(*) FROM properties
                        WHERE tenant_id = CAST(:tid AS uuid)
                    """,
                    params={"tid": tenant_id},
                )
                if err:
                    count_errors["properties"] = err

                gaps_count, err = await _safe_count(
                    db,
                    label="kb_gaps",
                    sql="""
                        SELECT COUNT(*) FROM concierge_knowledge_gaps
                        WHERE resolved = false
                          AND tenant_id = CAST(:tid AS uuid)
                    """,
                    params={"tid": tenant_id},
                )
                if err:
                    count_errors["kb_gaps"] = err

        response = {
            "period_days": days,
            "since": since.isoformat(),
            "tenant_id": tenant_id,
            "guest_sessions": sessions_count,
            "messages_processed": messages_count,
            "pre_booking_drafts": drafts_count,
            "kb_entries_added": kb_count,
            "escalations": esc_count,
            "properties": props_count,
            "kb_gaps": gaps_count,
            "_version": _VERSION,
            "_resolution": resolution_path,
        }
        if count_errors:
            response["_count_errors"] = count_errors
        return response

    except Exception as e:
        import traceback
        logger.exception("[Audit] summary failed")
        return {
            "period_days": days,
            "error": str(e),
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc().splitlines()[-6:],
            "guest_sessions": 0,
            "messages_processed": 0,
            "pre_booking_drafts": 0,
            "kb_entries_added": 0,
            "escalations": 0,
            "properties": 0,
            "kb_gaps": 0,
        }


@router.get("/export")
async def audit_export(
    format: str = Query(default="json", pattern="^(json|csv)$"),
    days: int = Query(default=30, ge=1, le=365),
    include: str = Query(default="sessions,messages,escalations,kb", description="Comma-separated: sessions,messages,escalations,kb,prebooking"),
):
    """
    Export full audit trail. Supports JSON and CSV.
    Date range: last N days (default 30).
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    include_set = set(include.split(","))
    result = {
        "export_generated": datetime.now(timezone.utc).isoformat(),
        "period_days": days,
        "since": since.isoformat(),
        "data": {}
    }

    try:
        from app.core.database import get_db_session
        from sqlalchemy import text

        async with get_db_session() as db:

            # ── GUEST SESSIONS ──────────────────────────────────────
            if "sessions" in include_set:
                try:
                    rows = (await db.execute(
                        text("""
                            SELECT session_id, guest_name, guest_phone, property_name,
                                   check_in, check_out, status, phase, created_at, updated_at
                            FROM concierge_guest_sessions
                            WHERE created_at >= :since
                            ORDER BY created_at DESC
                            LIMIT 1000
                        """), {"since": since}
                    )).mappings().all()
                    result["data"]["guest_sessions"] = [
                        {
                            "session_id": r["session_id"],
                            "guest_name": r["guest_name"],
                            "guest_phone": r["guest_phone"],
                            "property_name": r["property_name"],
                            "check_in": _ts(r["check_in"]),
                            "check_out": _ts(r["check_out"]),
                            "status": r["status"],
                            "phase": r["phase"],
                            "created_at": _ts(r["created_at"]),
                            "updated_at": _ts(r["updated_at"]),
                        }
                        for r in rows
                    ]
                except Exception as e:
                    result["data"]["guest_sessions"] = []
                    result["data"]["guest_sessions_error"] = str(e)

            # ── MESSAGES ────────────────────────────────────────────
            if "messages" in include_set:
                try:
                    rows = (await db.execute(
                        text("""
                            SELECT id, session_id, role, content, intent,
                                   confidence, latency_ms, created_at
                            FROM concierge_message_history
                            WHERE created_at >= :since
                            ORDER BY created_at DESC
                            LIMIT 5000
                        """), {"since": since}
                    )).mappings().all()
                    result["data"]["messages"] = [
                        {
                            "id": str(r["id"]),
                            "session_id": r["session_id"],
                            "role": r["role"],
                            "content": r["content"],
                            "intent": r["intent"],
                            "confidence": float(r["confidence"]) if r["confidence"] else None,
                            "latency_ms": r["latency_ms"],
                            "created_at": _ts(r["created_at"]),
                        }
                        for r in rows
                    ]
                except Exception as e:
                    result["data"]["messages"] = []
                    result["data"]["messages_error"] = str(e)

            # ── KB ENTRIES ───────────────────────────────────────────
            if "kb" in include_set:
                try:
                    rows = (await db.execute(
                        text("""
                            SELECT id, property_id, question, answer,
                                   source, approved_by, created_at, updated_at
                            FROM knowledge_base_entries
                            WHERE created_at >= :since
                            ORDER BY created_at DESC
                            LIMIT 1000
                        """), {"since": since}
                    )).mappings().all()
                    result["data"]["knowledge_base"] = [
                        {
                            "id": str(r["id"]),
                            "property_id": r["property_id"],
                            "question": r["question"],
                            "answer": r["answer"],
                            "source": r["source"],
                            "approved_by": r["approved_by"],
                            "created_at": _ts(r["created_at"]),
                            "updated_at": _ts(r["updated_at"]),
                        }
                        for r in rows
                    ]
                except Exception as e:
                    result["data"]["knowledge_base"] = []
                    result["data"]["knowledge_base_error"] = str(e)

    except Exception as e:
        result["error"] = str(e)
        result["note"] = "Database connection failed. Run pre_booking_setup.py to initialize."

    # ── FORMAT OUTPUT ─────────────────────────────────────────────
    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)

        for section_name, records in result.get("data", {}).items():
            if not isinstance(records, list) or not records:
                continue
            writer.writerow([f"=== {section_name.upper()} ==="])
            writer.writerow(list(records[0].keys()))
            for rec in records:
                writer.writerow(list(rec.values()))
            writer.writerow([])

        output.seek(0)
        filename = f"oyvoda_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    # JSON
    filename = f"oyvoda_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    json_str = json.dumps(result, indent=2, default=str)
    return StreamingResponse(
        iter([json_str]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
