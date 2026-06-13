"""
operator_prebooking.py — Pre-Booking Inquiry Queue API

Endpoints the Oyvoda dashboard uses to surface and action AI-drafted
replies to inbound Vrbo/Airbnb/Escapia guest inquiries.

All routes are under /app/api/ to match the dashboard JS conventions.
Auth: httpOnly JWT cookie (same as the rest of the operator app).
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import time
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal, get_async_session
from app.services.feature_flags import is_ship_i_kb_retry_primary_enabled
from app.services.messaging.message_event_store import update_normalization_outcome
from app.services.operator.prebooking_queue_service import get_prebooking_queue_service
from app.services.operator.realtime_hub import get_operator_realtime_hub
from app.services.operator.scope_service import get_operator_scope_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/api", tags=["Operator Pre-Booking"])
queue_service = get_prebooking_queue_service()
scope_service = get_operator_scope_service()


async def _rollback_quietly(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except Exception:
        pass


async def _table_columns(db: AsyncSession, table_name: str) -> set[str]:
    try:
        rows = (await db.execute(
            text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = :table
            """),
            {"table": table_name},
        )).fetchall()
        return {str(r[0]) for r in rows}
    except Exception:
        await _rollback_quietly(db)
        return set()


def _existing_column(columns: set[str], *candidates: str) -> Optional[str]:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _row_visible_for_scope(row: dict, visible_property_codes: Optional[set[str]]) -> bool:
    if visible_property_codes is None:
        return True
    property_code = str(row.get("property_external_id") or "").strip()
    if not property_code:
        # Unbound inquiries still need operator review even when property
        # matching fails, so scoped operators should continue to see them.
        return True
    return property_code in visible_property_codes


async def _escalation_query_meta(db: AsyncSession) -> Optional[dict]:
    columns = await _table_columns(db, "concierge_escalations")
    if not columns:
        return None

    return {
        "id_expr": _existing_column(columns, "ticket_id", "id"),
        "type_expr": _existing_column(columns, "reason", "escalation_type"),
        "priority_expr": _existing_column(columns, "priority"),
        "status_expr": _existing_column(columns, "status"),
        "summary_expr": _existing_column(columns, "summary", "last_message"),
        "session_token_expr": _existing_column(columns, "session_token"),
        "created_at_expr": _existing_column(columns, "created_at"),
        "resolved_at_expr": _existing_column(columns, "resolved_at"),
        "tenant_expr": _existing_column(columns, "tenant_id"),
    }


async def _property_query_meta(db: AsyncSession, alias: str = "") -> Optional[dict]:
    columns = await _table_columns(db, "properties")
    if not columns:
        return None

    prefix = f"{alias}." if alias else ""
    id_col = _existing_column(columns, "property_id", "id")
    tenant_col = _existing_column(columns, "tenant_id", "company_id")
    code_candidates = [
        col for col in ("property_code", "external_id", "property_external_id", "code")
        if col in columns
    ]
    name_candidates = [
        col for col in ("property_name", "name", "address_street", "address_line1", "property_code", "external_id")
        if col in columns
    ]

    predicates = []
    if tenant_col:
        predicates.append(f"{prefix}{tenant_col} = CAST(:tid AS uuid)")
    if "deleted_at" in columns:
        predicates.append(f"{prefix}deleted_at IS NULL")
    if "is_deleted" in columns:
        predicates.append(f"COALESCE({prefix}is_deleted, FALSE) = FALSE")

    return {
        "id_expr": f"{prefix}{id_col}" if id_col else "NULL::uuid",
        "name_expr": "COALESCE(" + ", ".join(f"{prefix}{col}" for col in name_candidates) + ", 'Unknown property')" if name_candidates else "'Unknown property'",
        "join_code_exprs": [f"{prefix}{col}" for col in code_candidates],
        "where_sql": " AND ".join(predicates) if predicates else "TRUE",
    }


async def _resolve_prebooking_gaps_for_draft(
    db: AsyncSession,
    tenant_id: str,
    draft_id: str,
    resolution_notes: str,
) -> None:
    try:
        await db.execute(
            text("""
                UPDATE concierge_knowledge_gaps
                SET resolved = TRUE,
                    resolution_notes = COALESCE(NULLIF(:notes, ''), resolution_notes),
                    updated_at = NOW()
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND resolved = FALSE
                  AND COALESCE(metadata_json ->> 'draft_id', '') = :draft_id
            """),
            {"tid": tenant_id, "draft_id": draft_id, "notes": resolution_notes[:500]},
        )
    except Exception as exc:
        await _rollback_quietly(db)
        logger.debug("[PreBooking] gap auto-resolve skipped for %s: %s", draft_id, exc)


async def _record_learning_best_effort(
    db: AsyncSession,
    *,
    action: str,
    company_id: str,
    draft_id: str,
    intent: str,
    property_external_id: Optional[str],
    original_draft: Optional[str] = None,
    edited_text: Optional[str] = None,
    scope_type: str = "property",
    scope_target_id: Optional[str] = None,
) -> None:
    try:
        from app.services.messaging_brain.learning.draft_learning_service import DraftLearningService

        svc = DraftLearningService()
        if action == "approve":
            await svc.record_approval(
                db,
                company_id=company_id,
                draft_id=draft_id,
                intent=intent or "general",
                property_external_id=property_external_id,
            )
            return
        if action == "reject":
            await svc.record_rejection(
                db,
                company_id=company_id,
                draft_id=draft_id,
                intent=intent or "general",
                property_external_id=property_external_id,
            )
            return
        if action == "edit":
            if (original_draft or "").strip() != (edited_text or "").strip():
                await svc.record_edit_and_propose(
                    db,
                    company_id=company_id,
                    draft_id=draft_id,
                    original_draft=original_draft or "",
                    edited_text=edited_text or "",
                    intent=intent or "general",
                    property_external_id=property_external_id,
                    scope_type=scope_type,
                    scope_target_id=scope_target_id,
                )
            else:
                await svc.record_approval(
                    db,
                    company_id=company_id,
                    draft_id=draft_id,
                    intent=intent or "general",
                    property_external_id=property_external_id,
                )
    except Exception as learning_exc:
        await _rollback_quietly(db)
        logger.debug("[PreBooking] %s learning skipped: %s", action, learning_exc)


async def _persist_inquiry_outcome(
    *,
    tenant_id: str,
    draft_id: str,
    status: str,
    final_reply: Optional[str] = None,
    draft_text: Optional[str] = None,
    triggered_by: Optional[str] = None,
) -> Optional[dict]:
    async with SessionLocal() as write_db:
        set_clauses = ["status = :status", "replied_at = NOW()"]
        params = {"tid": tenant_id, "did": draft_id, "status": status}

        if final_reply is not None:
            set_clauses.append("final_reply = :final_reply")
            params["final_reply"] = final_reply
        if draft_text is not None:
            set_clauses.append("draft_text = :draft_text")
            params["draft_text"] = draft_text
        if triggered_by is not None:
            set_clauses.append("triggered_by = :triggered_by")
            params["triggered_by"] = triggered_by

        result = await write_db.execute(
            text(
                f"""
                UPDATE pre_booking_inquiries
                SET {", ".join(set_clauses)}
                WHERE draft_id = :did
                  AND company_id = CAST(:tid AS uuid)
                  AND status NOT IN ('replied', 'rejected')
                """
            ),
            params,
        )
        if result.rowcount == 0:
            await write_db.rollback()
            return None

        await write_db.commit()
        return await _load_inquiry_state(write_db, tenant_id=tenant_id, draft_id=draft_id)


async def _lookup_property_for_binding(
    db: AsyncSession,
    *,
    tenant_id: str,
    property_code: str,
) -> Optional[dict]:
    columns = await _table_columns(db, "properties")
    if not columns:
        return None

    tenant_col = _existing_column(columns, "tenant_id", "company_id")
    code_cols = [col for col in ("property_code", "external_id", "property_external_id", "code") if col in columns]
    name_cols = [
        col for col in ("property_name", "name", "address_street", "address_line1", "property_code", "external_id")
        if col in columns
    ]
    if not tenant_col or not code_cols:
        return None

    name_expr = "COALESCE(" + ", ".join(name_cols) + ", :property_code)" if name_cols else ":property_code"
    code_match_sql = " OR ".join(f"{col} = :property_code" for col in code_cols)
    row = (
        await db.execute(
            text(
                f"""
                SELECT {name_expr} AS property_name
                FROM properties
                WHERE {tenant_col} = CAST(:tenant_id AS uuid)
                  AND ({code_match_sql})
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "property_code": property_code},
        )
    ).mappings().first()
    return dict(row) if row else None


async def _bind_inquiry_property(
    db: AsyncSession,
    *,
    tenant_id: str,
    operator_label: str,
    draft_id: str,
    property_code: str,
    selected_candidate_value: str = "",
    selected_candidate_type: str = "",
    search_query: str = "",
) -> dict:
    row = (
        await db.execute(
            text(
                """
                SELECT draft_id, status, gmail_message_id, property_external_id
                FROM pre_booking_inquiries
                WHERE draft_id = :draft_id
                  AND company_id = CAST(:tenant_id AS uuid)
                LIMIT 1
                """
            ),
            {"draft_id": draft_id, "tenant_id": tenant_id},
        )
    ).mappings().first()
    if not row:
        return {"ok": False, "code": "draft_not_found", "message": "Draft not found", "status_code": 404}

    status = str(row.get("status") or "").lower()
    if status in {"replied", "rejected"}:
        return {
            "ok": False,
            "code": "draft_already_actioned",
            "message": f"Draft already {status}",
            "status_code": 409,
        }

    property_row = await _lookup_property_for_binding(db, tenant_id=tenant_id, property_code=property_code)
    if not property_row:
        return {
            "ok": False,
            "code": "property_not_found",
            "message": "Property code not found for this operator",
            "status_code": 404,
        }

    inquiry_columns = await _table_columns(db, "pre_booking_inquiries")
    set_clauses = ["property_external_id = :property_code"]
    params = {
        "draft_id": draft_id,
        "tenant_id": tenant_id,
        "property_code": property_code,
    }
    if "property_external_id_source" in inquiry_columns:
        params["audit"] = json.dumps(
            {
                "previous_value": str(row.get("property_external_id") or "").strip() or None,
                "new_value": property_code,
                "source": "operator_manual",
                "selected_candidate_value": selected_candidate_value or None,
                "selected_candidate_type": selected_candidate_type or None,
                "search_query": search_query or None,
                "updated_by": operator_label,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        set_clauses.append("property_external_id_source = CAST(:audit AS jsonb)")

    await db.execute(
        text(
            f"""
            UPDATE pre_booking_inquiries
            SET {", ".join(set_clauses)}
            WHERE draft_id = :draft_id
              AND company_id = CAST(:tenant_id AS uuid)
            """
        ),
        params,
    )

    gmail_message_id = str(row.get("gmail_message_id") or "").strip()
    if gmail_message_id:
        await update_normalization_outcome(
            db,
            UUID(str(tenant_id)),
            "gmail",
            gmail_message_id,
            selected_property_code=property_code,
            selected_property_match_type="operator_manual",
            parser_notes_append=[
                {
                    "event": "operator_manual_property_bind",
                    "draft_id": draft_id,
                    "property_code": property_code,
                    "selected_candidate_value": selected_candidate_value or None,
                    "selected_candidate_type": selected_candidate_type or None,
                    "search_query": search_query or None,
                    "updated_by": operator_label,
                }
            ],
        )

    await db.commit()
    return {
        "ok": True,
        "property_code": property_code,
        "property_name": str(property_row.get("property_name") or property_code),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Auth helper (mirrors operator_app.py — avoids circular import)
# ─────────────────────────────────────────────────────────────────────────────

def _get_current_user(request: Request):
    import base64, time
    token = request.cookies.get("oyvoda_access")
    if not token:
        return None
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
        if payload.get("exp", 0) < time.time():
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
    except Exception:
        return None


def _require_user(request: Request):
    user = _get_current_user(request)
    if not user:
        raise ValueError("Not authenticated")
    return user


def _tenant_id_from_user(user: dict) -> str:
    operator_id = user.get("scoped_op") or user.get("sub", "")
    return user.get("tid") or user.get("tenant_id") or operator_id


def _has_valid_tenant_id(tenant_id: str) -> bool:
    return bool(tenant_id) and len(tenant_id) == 36 and tenant_id.count("-") == 4


def _tenant_scope_response(user: dict, *, empty_payload: dict | None = None) -> JSONResponse:
    role = user.get("role", "owner")
    scoped_operator_id = user.get("scoped_op")
    if role == "super_admin" and not scoped_operator_id:
        return JSONResponse(
            {
                "error": "Super admin must scope into an operator first",
                "detail": "Super admin must scope into an operator first (use /app/api/admin/scope)",
                **(empty_payload or {}),
            },
            status_code=403,
        )
    return JSONResponse(
        {
            "error": "No tenant context",
            "detail": "No tenant context",
            **(empty_payload or {}),
        },
        status_code=403,
    )


async def _fetch_pre_booking_rows(
    db: AsyncSession,
    tenant_id: str,
    status: str,
    limit: int,
    property_external_id: str = "",
    unbound_only: bool = False,
    assignee_id: str = "",
    team_key: str = "",
    portfolio_key: str = "",
    assigned_to_me: bool = False,
):
    """Fetch canonical pre-booking queue rows via the backend read-model service."""
    return await queue_service.fetch_queue_rows(
        session=db,
        tenant_id=tenant_id,
        status=status,
        limit=limit,
        property_external_id=property_external_id,
        unbound_only=unbound_only,
        assignee_id=assignee_id,
        team_key=team_key,
        portfolio_key=portfolio_key,
        assigned_to_me=assigned_to_me,
    )


def _mutation_error(status_code: int, code: str, message: str, retryable: bool = False) -> JSONResponse:
    return JSONResponse(
        {
            "error": message,
            "error_detail": {"code": code, "message": message, "retryable": retryable},
        },
        status_code=status_code,
    )


async def _load_inquiry_state(
    db: AsyncSession,
    *,
    tenant_id: str,
    draft_id: str,
) -> Optional[dict]:
    property_meta = await _property_query_meta(db, "p")
    binding_code_sql = "COALESCE(NULLIF(pbi.property_external_id, ''), NULLIF(mn.selected_property_code, ''))"
    if property_meta and property_meta["join_code_exprs"]:
        property_join_match = " OR ".join(
            f"{expr} = {binding_code_sql}" for expr in property_meta["join_code_exprs"]
        )
        property_join_sql = f"""
                LEFT JOIN message_normalizations mn
                  ON mn.tenant_id = CAST(:tid AS uuid)
                 AND mn.source_channel = 'gmail'
                 AND mn.source_message_id = pbi.gmail_message_id
                LEFT JOIN properties p
                  ON ({property_join_match})
                 AND {property_meta["where_sql"]}
        """
        property_name_sql = f"COALESCE({property_meta['name_expr']}, {binding_code_sql}, 'Unknown property')"
    else:
        property_join_sql = """
                LEFT JOIN message_normalizations mn
                  ON mn.tenant_id = CAST(:tid AS uuid)
                 AND mn.source_channel = 'gmail'
                 AND mn.source_message_id = pbi.gmail_message_id
        """
        property_name_sql = f"COALESCE({binding_code_sql}, 'Unknown property')"

    row = (
        await db.execute(
            text(
                f"""
                SELECT
                    pbi.draft_id,
                    pbi.status,
                    pbi.platform,
                    pbi.guest_name,
                    pbi.message_text,
                    pbi.draft_text,
                    pbi.final_reply,
                    pbi.confidence,
                    {binding_code_sql} AS property_external_id,
                    pbi.triggered_by,
                    pbi.replied_at,
                    {property_name_sql} AS property_name
                FROM pre_booking_inquiries pbi
                {property_join_sql}
                WHERE pbi.company_id = CAST(:tid AS uuid)
                  AND pbi.draft_id = :draft_id
                LIMIT 1
                """
            ),
            {"tid": tenant_id, "draft_id": draft_id},
        )
    ).mappings().first()
    if not row:
        return None

    return {
        "id": row["draft_id"],
        "status": row["status"] or "pending_review",
        "channel": row["platform"] or "email",
        "guest_name": row["guest_name"] or "Guest",
        "message_text": row["message_text"] or "",
        "message_preview": (row["message_text"] or "")[:240],
        "draft_text": row["draft_text"] or "",
        "final_reply": row["final_reply"] or "",
        "confidence": float(row["confidence"] or 0),
        "property_id": row["property_external_id"] or "",
        "property_name": row["property_name"] or "Unknown property",
        "triggered_by": row["triggered_by"] or "",
        "replied_at": row["replied_at"].isoformat() if row["replied_at"] else None,
    }


async def _publish_inquiry_event(
    *,
    tenant_id: str,
    event_name: str,
    inquiry: Optional[dict],
) -> None:
    if not inquiry:
        return
    hub = get_operator_realtime_hub()
    await hub.publish(tenant_id, event_name, inquiry)
    await hub.publish(
        tenant_id,
        "summary.updated",
        {
            "tenant_id": tenant_id,
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "draft_id": inquiry.get("id"),
        },
    )


async def _sync_queue_best_effort(
    db: AsyncSession,
    tenant_id: str,
    draft_id: str,
) -> None:
    try:
        synced = await queue_service.sync_draft(db, tenant_id, draft_id)
        if not synced:
            logger.debug("[PreBooking] queue sync returned no row for %s", draft_id)
    except Exception as exc:
        logger.warning("[PreBooking] queue sync skipped for %s: %s", draft_id, exc)


# ─────────────────────────────────────────────────────────────────────────────
# GET /app/api/inquiries — list pending pre-booking drafts
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/inquiries")
async def list_inquiries(
    request: Request,
    status: str = "pending_review",
    limit: int = 50,
    unbound_only: bool = False,
    assignee_id: str = "",
    team_key: str = "",
    portfolio_key: str = "",
    assigned_to_me: bool = False,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Return pre-booking inquiry drafts for this operator.

    status: pending_review | replied | rejected | all
    """
    try:
        user = _require_user(request)
    except ValueError:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    operator_id = user.get("scoped_op") or user.get("sub", "")
    tenant_id = user.get("tid") or user.get("tenant_id") or operator_id

    # Super admins without a scoped operator have sub="sa_001" (not a UUID).
    # Return an empty list rather than blowing up the query.
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response(user, empty_payload={"count": 0, "status_filter": status, "items": []})

    # Build status filter
    started = time.perf_counter()
    try:
        rows = await _fetch_pre_booking_rows(
            db=db,
            tenant_id=tenant_id,
            status=status,
            limit=min(limit, 100),
            unbound_only=unbound_only,
            assignee_id=(user.get("sub", "") if assigned_to_me else assignee_id),
            team_key=team_key,
            portfolio_key=portfolio_key,
            assigned_to_me=assigned_to_me,
        )
        visible_property_codes = await scope_service.visible_property_codes(
            db,
            tenant_id,
            user.get("sub", ""),
            user.get("role", "owner"),
        )
        if visible_property_codes is not None:
            rows = [row for row in rows if _row_visible_for_scope(row, visible_property_codes)]

        items = []
        for r in rows:
            confidence = float(r["confidence"] or 0)
            meta = _confidence_meta(confidence, r["policy_warnings"])
            latest_guest_turn = r["latest_guest_turn"] or r["message_text"] or ""
            extracted_asks = _safe_json_list(r["extracted_asks"]) or _safe_json_list(r["normalized_asks"])
            items.append({
                "guest_thread_id":            r.get("guest_thread_id") or "",
                "draft_id":                  r["draft_id"],
                "platform":                  r["platform"] or "unknown",
                "source_provider":           r["source_provider"] or "",
                "guest_name":                r["guest_name"] or "Guest",
                "guest_email":               r["guest_email"] or "",
                "message_text":              r["message_text"] or "",
                "latest_guest_turn":         latest_guest_turn,
                "prior_thread_context":      r["prior_thread_context"] or "",
                "draft_text":                r["draft_text"] or "",
                "intent":                    r["intent"] or "general",
                "asks":                      extracted_asks,
                "parser_source":             r["parser_source"] or "",
                "platform_listing_id":       r["platform_listing_id"] or "",
                "platform_unit_id":          r["platform_unit_id"] or "",
                "property_binding_candidates": _safe_json_list(r["property_binding_candidates"]),
                "prior_operator_commitments": _safe_json_list(r["prior_operator_commitments"]),
                "property_match_type":       r["selected_property_match_type"] or "",
                "route_outcome":             r["route_outcome"] or "",
                "fallback_reason":           r["fallback_reason"] or "",
                "assigned_operator_id":      r.get("assigned_operator_id") or "",
                "assigned_team_key":         r.get("assigned_team_key") or "",
                "portfolio_key":             r.get("portfolio_key") or "",
                "assignment_status":         r.get("assignment_status") or "unassigned",
                "latest_turn_confidence":    float(r["latest_turn_confidence"] or 0),
                "latest_turn_extracted":     bool(r["latest_turn_extracted"]),
                "autonomy_decision":         r.get("autonomy_decision") or "",
                "confidence":                confidence,
                "confidence_source":         meta["confidence_source"],
                "draft_source":              meta["draft_source"],
                "confidence_label":          meta["confidence_label"],
                "confidence_note":           meta["confidence_note"],
                "draft_ready":               bool((r["draft_text"] or "").strip()) and _is_review_ready_draft_source(meta["draft_source"]),
                "status":                    r["status"] or "pending_review",
                "property_external_id":      r["property_external_id"] or "",
                "property_name":             r["property_name"] or r["property_external_id"] or "Unknown property",
                "requested_check_in":        r["requested_check_in"].isoformat() if r["requested_check_in"] else None,
                "requested_check_out":       r["requested_check_out"].isoformat() if r["requested_check_out"] else None,
                "requested_guests":          r["requested_guests"],
                "policy_flags":              _safe_json_list(r["policy_flags"]),
                "policy_warnings":           _safe_json_list(r["policy_warnings"]),
                "received_at":               r["received_at"].isoformat() if r["received_at"] else None,
                "replied_at":                r["replied_at"].isoformat() if r["replied_at"] else None,
                "final_reply":               r["final_reply"] or "",
                "gmail_message_id":          r["gmail_message_id"] or "",
                "gmail_thread_id":           r["gmail_thread_id"] or "",
            })

        response = JSONResponse({
            "count": len(items),
            "status_filter": status,
            "unbound_only": unbound_only,
            "unbound_count": await queue_service.count_unbound_rows(
                db,
                tenant_id,
                status="pending_review",
            ),
            "items": items,
        })
        logger.info(
            "[PreBooking] list_inquiries tenant=%s status=%s limit=%s count=%s elapsed_ms=%.1f",
            tenant_id,
            status,
            limit,
            len(items),
            (time.perf_counter() - started) * 1000,
        )
        return response

    except Exception as e:
        logger.exception("[PreBooking] list_inquiries failed")
        return JSONResponse({"error": str(e), "items": []}, status_code=500)


# ─────────────────────────────────────────────────────────────────────────────
# GET /app/api/messages — unified inbox across stages + escalations
#
# Single feed the dashboard Messages section renders from. Composes three
# underlying sources into one chronological list with stage tags:
#   - pre_booking_inquiries   → stage="pre_booking"
#   - concierge_guest_sessions → stage derived from check_in/check_out vs today:
#                                  check_in >  today          → booked
#                                  in range of stay            → in_stay
#                                  check_out < today           → post_stay
#   - concierge_escalations    → stage="escalations"
#
# Query params:
#   stage:    all | pre_booking | booked | in_stay | post_stay | escalations
#   status:   pending_review | replied | rejected | all  (only applies to
#             pre_booking stage)
#   property: property_external_id to filter to (blank = all)
#   limit:    max rows per stage (default 50, cap 200)
#
# Response shape is deliberately small per item; the dashboard detail pane
# pulls the full record via the existing per-resource endpoints when needed.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/messages")
async def list_messages(
    request: Request,
    stage: str = "all",
    status: str = "all",
    property: str = "",
    unbound_only: bool = False,
    limit: int = 50,
    assignee_id: str = "",
    team_key: str = "",
    portfolio_key: str = "",
    assigned_to_me: bool = False,
    db: AsyncSession = Depends(get_async_session),
):
    """Unified messages feed — see module docstring above."""
    try:
        user = _require_user(request)
    except ValueError:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    tenant_id = user.get("tid") or user.get("tenant_id") or user.get("scoped_op") or user.get("sub", "")
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response(user, empty_payload={
            "count": 0,
            "stage": stage,
            "status": status,
            "property": property,
            "items": [],
            "stage_counts": _empty_stage_counts(),
            "properties": [],
        })

    limit = max(1, min(int(limit or 50), 200))
    items: list = []
    ship_i_kb_retry_primary = await is_ship_i_kb_retry_primary_enabled(db=db, tenant_id=tenant_id)
    visible_property_codes = await scope_service.visible_property_codes(
        db,
        tenant_id,
        user.get("sub", ""),
        user.get("role", "owner"),
    )
    want_prebooking  = stage in ("all", "pre_booking")
    want_booked      = stage in ("all", "booked")
    want_in_stay     = stage in ("all", "in_stay")
    want_post_stay   = stage in ("all", "post_stay")
    want_escalations = stage in ("all", "escalations")

    # ----- Pre-booking inquiries -----------------------------------------
    if want_prebooking:
        try:
            rows = await _fetch_pre_booking_rows(
                db=db,
                tenant_id=tenant_id,
                status=status,
                limit=limit,
                property_external_id=property,
                unbound_only=unbound_only,
                assignee_id=(user.get("sub", "") if assigned_to_me else assignee_id),
                team_key=team_key,
                portfolio_key=portfolio_key,
                assigned_to_me=assigned_to_me,
            )
            if visible_property_codes is not None:
                rows = [row for row in rows if _row_visible_for_scope(row, visible_property_codes)]
            for r in rows:
                confidence = float(r["confidence"] or 0)
                meta = _confidence_meta(confidence, r["policy_warnings"])
                latest_guest_turn = r["latest_guest_turn"] or r["message_text"] or ""
                full_draft = r["draft_text"] or ""
                asks = _safe_json_list(r["extracted_asks"]) or _safe_json_list(r["normalized_asks"])
                items.append({
                    "id":              r["draft_id"],
                    "guest_thread_id": r.get("guest_thread_id") or "",
                    "kind":            "inquiry",
                    "stage":           "pre_booking",
                    "status":          r["status"] or "pending_review",
                    "channel":         r["platform"] or "email",
                    "source_provider": r["source_provider"] or "",
                    "guest_name":      r["guest_name"] or "Guest",
                    "guest_email":     r["guest_email"] or "",
                    "message_text":    r["message_text"] or "",
                    "latest_guest_turn": latest_guest_turn,
                    "prior_thread_context": r["prior_thread_context"] or "",
                    "message_preview": (latest_guest_turn or r["message_text"] or "")[:240],
                    "draft_text":      full_draft,
                    "draft_preview":   full_draft[:240],
                    "final_reply":     r["final_reply"] or "",
                    "intent":          r["intent"] or "general",
                    "asks":            asks,
                    "parser_source":   r["parser_source"] or "",
                    "platform_listing_id": r["platform_listing_id"] or "",
                    "platform_unit_id": r["platform_unit_id"] or "",
                    "property_binding_candidates": _safe_json_list(r["property_binding_candidates"]),
                    "prior_operator_commitments": _safe_json_list(r["prior_operator_commitments"]),
                    "property_match_type": r["selected_property_match_type"] or "",
                    "route_outcome":   r["route_outcome"] or "",
                    "fallback_reason": r["fallback_reason"] or "",
                    "assigned_operator_id": r.get("assigned_operator_id") or "",
                    "assigned_team_key": r.get("assigned_team_key") or "",
                    "portfolio_key": r.get("portfolio_key") or "",
                    "assignment_status": r.get("assignment_status") or "unassigned",
                    "latest_turn_confidence": float(r["latest_turn_confidence"] or 0),
                    "latest_turn_extracted": bool(r["latest_turn_extracted"]),
                    "autonomy_decision": r.get("autonomy_decision") or "",
                    "confidence":      confidence,
                    "confidence_source": meta["confidence_source"],
                    "draft_source":      meta["draft_source"],
                    "confidence_label":  meta["confidence_label"],
                    "confidence_note":   meta["confidence_note"],
                    "draft_ready":       bool((r["draft_text"] or "").strip()) and _is_review_ready_draft_source(meta["draft_source"]),
                    "property_id":     r["property_external_id"] or "",
                    "property_name":   r["property_name"] or r["property_external_id"] or "Unknown property",
                    "check_in":        r["requested_check_in"].isoformat() if r["requested_check_in"] else None,
                    "check_out":       r["requested_check_out"].isoformat() if r["requested_check_out"] else None,
                    "occurred_at":     r["received_at"].isoformat() if r["received_at"] else None,
                    "replied_at":      r["replied_at"].isoformat() if r["replied_at"] else None,
                    "policy_flags":    _safe_json_list(r["policy_flags"]),
                    "policy_warnings": _safe_json_list(r["policy_warnings"]),
                    "blocked_by_gap_topics": _safe_json_list(r.get("blocked_by_gap_topics")),
                    "triggered_by": r.get("triggered_by") or "",
                    "gmail_message_id": r["gmail_message_id"] or "",
                    "thread_ref":      r["gmail_thread_id"] or "",
                })
        except Exception as _pe:
            logger.warning("[Messages] pre_booking fetch failed: %s", _pe)

    # ----- Guest sessions (booked / in_stay / post_stay) -----------------
    if want_booked or want_in_stay or want_post_stay:
        try:
            stage_in = []
            if want_booked:    stage_in.append("'booked'")
            if want_in_stay:   stage_in.append("'in_stay'")
            if want_post_stay: stage_in.append("'post_stay'")
            stage_clause    = f"AND derived_stage IN ({','.join(stage_in)})"
            property_clause = "" if not property else "AND property_external_id = :prop"
            rows = (await db.execute(
                text(f"""
                    SELECT * FROM (
                      SELECT
                        s.token                         AS id,
                        CAST(s.guest_thread_id AS text) AS guest_thread_id,
                        CASE
                          WHEN s.check_in IS NULL OR s.check_out IS NULL THEN 'booked'
                          WHEN s.check_in > CURRENT_DATE                THEN 'booked'
                          WHEN s.check_out < CURRENT_DATE               THEN 'post_stay'
                          ELSE 'in_stay'
                        END                             AS derived_stage,
                        s.status,
                        s.guest_name,
                        s.guest_phone,
                        s.guest_email,
                        s.property_name,
                        s.property_external_id,
                        s.check_in,
                        s.check_out,
                        s.created_at,
                        s.last_message_at,
                        (SELECT cm.content
                           FROM concierge_messages cm
                          WHERE cm.session_id = s.session_id
                          ORDER BY cm.created_at DESC
                          LIMIT 1)                AS last_message_preview
                      FROM concierge_guest_sessions s
                      WHERE s.tenant_id = CAST(:tid AS uuid)
                        AND s.status NOT IN ('expired', 'closed')
                    ) x
                    WHERE 1=1
                    {stage_clause}
                    {property_clause}
                    ORDER BY COALESCE(last_message_at, created_at) DESC
                    LIMIT :limit
                """),
                {"tid": tenant_id, "prop": property, "limit": limit},
            )).mappings().all()
            for r in rows:
                items.append({
                    "id":              r["id"],
                    "guest_thread_id": r.get("guest_thread_id") or "",
                    "kind":            "session",
                    "stage":           r["derived_stage"],
                    "status":          r["status"] or "active",
                    "channel":         "sms",
                    "guest_name":      r["guest_name"] or "Guest",
                    "guest_email":     r["guest_email"] or "",
                    "guest_phone":     r["guest_phone"] or "",
                    "message_preview": (r["last_message_preview"] or "")[:240],
                    "property_id":     r["property_external_id"] or "",
                    "property_name":   r["property_name"] or "Unknown property",
                    "check_in":        r["check_in"].isoformat() if r["check_in"] else None,
                    "check_out":       r["check_out"].isoformat() if r["check_out"] else None,
                    "occurred_at":     (r["last_message_at"] or r["created_at"]).isoformat()
                                       if (r["last_message_at"] or r["created_at"]) else None,
                    "session_token":   r["id"],
                })
        except Exception as _se:
            # Tolerate older schemas that don't have last_message_* columns.
            logger.warning("[Messages] sessions fetch failed: %s", _se)
            try:
                rows2 = (await db.execute(
                    text("""
                        SELECT
                          s.token AS id,
                          CAST(s.guest_thread_id AS text) AS guest_thread_id,
                          CASE
                            WHEN s.check_in IS NULL OR s.check_out IS NULL THEN 'booked'
                            WHEN s.check_in > CURRENT_DATE                THEN 'booked'
                            WHEN s.check_out < CURRENT_DATE               THEN 'post_stay'
                            ELSE 'in_stay'
                          END AS derived_stage,
                          s.status, s.guest_name, s.guest_phone, s.guest_email,
                          s.property_name, s.property_external_id,
                          s.check_in, s.check_out, s.created_at
                        FROM concierge_guest_sessions s
                        WHERE s.tenant_id = CAST(:tid AS uuid)
                          AND s.status NOT IN ('expired', 'closed')
                        ORDER BY s.created_at DESC
                        LIMIT :limit
                    """),
                    {"tid": tenant_id, "limit": limit},
                )).mappings().all()
                for r in rows2:
                    ds = r["derived_stage"]
                    if ds == "booked"    and not want_booked:    continue
                    if ds == "in_stay"   and not want_in_stay:   continue
                    if ds == "post_stay" and not want_post_stay: continue
                    if property and r["property_external_id"] != property: continue
                    items.append({
                        "id":              r["id"],
                        "guest_thread_id": r.get("guest_thread_id") or "",
                        "kind":            "session",
                        "stage":           ds,
                        "status":          r["status"] or "active",
                        "channel":         "sms",
                        "guest_name":      r["guest_name"] or "Guest",
                        "guest_email":     r["guest_email"] or "",
                        "guest_phone":     r["guest_phone"] or "",
                        "message_preview": "",
                        "property_id":     r["property_external_id"] or "",
                        "property_name":   r["property_name"] or "Unknown property",
                        "check_in":        r["check_in"].isoformat() if r["check_in"] else None,
                        "check_out":       r["check_out"].isoformat() if r["check_out"] else None,
                        "occurred_at":     r["created_at"].isoformat() if r["created_at"] else None,
                        "session_token":   r["id"],
                    })
            except Exception as _se2:
                logger.debug("[Messages] sessions legacy fetch also failed: %s", _se2)

    # ----- Escalations ---------------------------------------------------
    if want_escalations:
        try:
            esc_meta = await _escalation_query_meta(db)
            if not esc_meta or not esc_meta["id_expr"] or not esc_meta["session_token_expr"]:
                raise ValueError("Escalation schema unavailable for unified inbox")

            where = ["e.status IN ('pending', 'acknowledged')"]
            if esc_meta["tenant_expr"]:
                where.append("e.tenant_id = CAST(:tid AS uuid)")
            else:
                where.append("s.tenant_id = CAST(:tid AS uuid)")

            rows = (await db.execute(
                text("""
                    SELECT
                        e.""" + esc_meta["id_expr"] + """ AS escalation_id,
                        CAST(e.guest_thread_id AS text) AS guest_thread_id,
                        """ + (f"e.{esc_meta['type_expr']}" if esc_meta["type_expr"] else "NULL::text") + """ AS escalation_type,
                        """ + (f"e.{esc_meta['priority_expr']}" if esc_meta["priority_expr"] else "NULL::text") + """ AS priority,
                        """ + (f"e.{esc_meta['status_expr']}" if esc_meta["status_expr"] else "NULL::text") + """ AS status,
                        """ + (f"e.{esc_meta['summary_expr']}" if esc_meta["summary_expr"] else "NULL::text") + """ AS summary,
                        e.""" + esc_meta["session_token_expr"] + """ AS session_token,
                        """ + (f"e.{esc_meta['created_at_expr']}" if esc_meta["created_at_expr"] else "NULL::timestamptz") + """ AS created_at,
                        """ + (f"e.{esc_meta['resolved_at_expr']}" if esc_meta["resolved_at_expr"] else "NULL::timestamptz") + """ AS resolved_at,
                        s.guest_name,
                        s.property_name,
                        s.property_external_id
                    FROM concierge_escalations e
                    LEFT JOIN concierge_guest_sessions s
                           ON s.token = e.""" + esc_meta["session_token_expr"] + """
                    WHERE """ + " AND ".join(where) + """
                    ORDER BY
                      CASE """ + (f"e.{esc_meta['priority_expr']}" if esc_meta["priority_expr"] else "NULL") + """
                        WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                        WHEN 'medium' THEN 2 ELSE 3
                      END,
                      """ + (f"e.{esc_meta['created_at_expr']}" if esc_meta["created_at_expr"] else "NOW()") + """ DESC
                    LIMIT :limit
                """),
                {"tid": tenant_id, "limit": limit},
            )).mappings().all()
            for r in rows:
                if property and (r["property_external_id"] or "") != property:
                    continue
                items.append({
                    "id":              str(r["escalation_id"]),
                    "guest_thread_id": r.get("guest_thread_id") or "",
                    "kind":            "escalation",
                    "stage":           "escalations",
                    "status":          r["status"] or "pending",
                    "channel":         r["escalation_type"] or "other",
                    "priority":        r["priority"] or "medium",
                    "guest_name":      r["guest_name"] or "Guest",
                    "message_preview": (r["summary"] or "")[:240],
                    "property_id":     r["property_external_id"] or "",
                    "property_name":   r["property_name"] or "Unknown property",
                    "occurred_at":     r["created_at"].isoformat() if r["created_at"] else None,
                    "session_token":   r["session_token"] or "",
                })
        except Exception as _ee:
            logger.warning("[Messages] escalations fetch failed: %s", _ee)

    # Merge by recency.
    items.sort(key=lambda it: it.get("occurred_at") or "", reverse=True)

    # Stage counts are always unfiltered — they drive the tab badges so the
    # operator can see where volume lives even while viewing a filtered tab.
    stage_counts = await _stage_counts(db, tenant_id)

    # Property filter dropdown — properties with activity in the last 60 days.
    props = await _active_properties(db, tenant_id)

    return JSONResponse({
        "count":        len(items),
        "stage":        stage,
        "status":       status,
        "property":     property,
        "unbound_only": unbound_only,
        "ship_i_kb_retry_primary": ship_i_kb_retry_primary,
        "unbound_count": await queue_service.count_unbound_rows(
            db,
            tenant_id,
            status="pending_review",
        ),
        "stage_counts": stage_counts,
        "properties":   props,
        "items":        items,
    })


def _safe_json_list(v):
    """Defensive JSON-list parser. Returns [] on any failure."""
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try: return json.loads(v)
        except Exception: return []
    return v or []


def _is_review_ready_draft_source(draft_source: str) -> bool:
    """Sources that should surface as operator-ready review drafts."""
    return draft_source in {"model", "messaging_brain"}


def _confidence_meta(confidence: float, policy_warnings) -> dict:
    warnings = _safe_json_list(policy_warnings)
    draft_source = "model"
    for w in warnings:
        sw = str(w)
        if sw.startswith("draft_source:"):
            draft_source = sw.split(":", 1)[1] or "model"
            break
    if any(str(w).startswith("gmail_fallback_saved:") for w in warnings):
        return {
            "confidence_source": "fallback_placeholder",
            "draft_source": "gmail_fallback_saved",
            "confidence_label": "Manual review",
            "confidence_note": "No AI confidence was available. This draft was saved as a fallback for operator review.",
        }
    missing_topics = ""
    for w in warnings:
        sw = str(w)
        if sw.startswith("missing_property_knowledge:"):
            missing_topics = sw.split(":", 1)[1]
            break
    if draft_source == "kb_gap_required":
        topic_note = (
            f" Missing topics: {missing_topics.replace(',', ', ')}."
            if missing_topics else
            ""
        )
        return {
            "confidence_source": "knowledge_gap_required",
            "draft_source": "kb_gap_required",
            "confidence_label": "Knowledge gap",
            "confidence_note": "Oyvoda did not draft a guest reply because the message depends on property details that are not confirmed in the knowledge base." + topic_note,
        }
    if draft_source.startswith("fallback_grounded_guidebook_"):
        richness = draft_source.rsplit("_", 1)[-1]
        return {
            "confidence_source": "guidebook_grounded",
            "draft_source": draft_source,
            "confidence_label": f"Guidebook grounded ({richness})",
            "confidence_note": "This draft was grounded from the property's guidebook-derived knowledge. Richer guidebooks support stronger confidence than sparse ones.",
        }
    if draft_source == "fallback_grounded_property_data":
        return {
            "confidence_source": "property_facts_grounded",
            "draft_source": draft_source,
            "confidence_label": "Property facts grounded",
            "confidence_note": "This draft was grounded from structured property facts already stored for the property.",
        }
    if draft_source == "fallback_grounded_faq":
        return {
            "confidence_source": "faq_grounded",
            "draft_source": draft_source,
            "confidence_label": "FAQ grounded",
            "confidence_note": "This draft was grounded from existing property FAQ knowledge.",
        }
    if draft_source != "model":
        return {
            "confidence_source": "fallback_placeholder",
            "draft_source": draft_source,
            "confidence_label": "Manual review",
            "confidence_note": "The message was captured, but Oyvoda fell back to a safer draft path instead of a full model-generated reply.",
        }
    return {
        "confidence_source": "keyword_heuristic",
        "draft_source": "model",
        "confidence_label": f"{round((confidence or 0) * 100)}% heuristic",
        "confidence_note": "Model-generated draft using extracted email context, property data, operator guidance, and routing heuristics. This is not a send-permission score.",
    }


def _empty_stage_counts() -> dict:
    return {"pre_booking": 0, "booked": 0, "in_stay": 0,
            "post_stay": 0, "escalations": 0}


async def _assignment_candidates(db: AsyncSession, tenant_id: str, operator_id: str) -> list[dict]:
    items = []
    try:
        owner = (
            await db.execute(
                text("""
                    SELECT id, owner_name AS name, email, 'owner' AS role
                    FROM operator_accounts
                    WHERE id = CAST(:operator_id AS uuid)
                      AND tenant_id = CAST(:tid AS uuid)
                    LIMIT 1
                """),
                {"operator_id": operator_id, "tid": tenant_id},
            )
        ).mappings().first()
        if owner:
            items.append({
                "id": str(owner["id"]),
                "name": owner["name"] or owner["email"] or "Owner",
                "email": owner["email"] or "",
                "role": owner["role"],
                "team_key": owner["role"],
            })
    except Exception:
        await _rollback_quietly(db)

    try:
        rows = (
            await db.execute(
                text("""
                    SELECT id, name, email, role
                    FROM operator_team_members
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND activated = TRUE
                    ORDER BY created_at
                """),
                {"tid": tenant_id},
            )
        ).mappings().all()
        for row in rows:
            items.append({
                "id": str(row["id"]),
                "name": row["name"] or row["email"] or "Team member",
                "email": row["email"] or "",
                "role": row["role"] or "staff",
                "team_key": row["role"] or "staff",
            })
    except Exception:
        await _rollback_quietly(db)
    return items


@router.get("/inquiries/assignment-candidates")
async def list_assignment_candidates(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    try:
        user = _require_user(request)
    except ValueError:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    operator_id = user.get("scoped_op") or user.get("sub", "")
    tenant_id = user.get("tid") or user.get("tenant_id") or operator_id
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response(user, empty_payload={"items": []})

    items = await _assignment_candidates(db, tenant_id, operator_id)
    return JSONResponse({"count": len(items), "items": items})


@router.post("/inquiries/{draft_id}/assign")
async def assign_inquiry(
    draft_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    try:
        user = _require_user(request)
    except ValueError:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    operator_id = user.get("scoped_op") or user.get("sub", "")
    tenant_id = user.get("tid") or user.get("tenant_id") or operator_id
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response(user)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    assigned_operator_id = (body.get("assigned_operator_id") or "").strip()
    assigned_team_key = (body.get("assigned_team_key") or "").strip()
    portfolio_key = (body.get("portfolio_key") or "").strip()

    if assigned_operator_id:
        candidates = await _assignment_candidates(db, tenant_id, operator_id)
        if assigned_operator_id not in {item["id"] for item in candidates}:
            return JSONResponse({"error": "Assigned operator is not valid for this tenant"}, status_code=400)

    synced = await queue_service.sync_draft(db, tenant_id, draft_id)
    if not synced:
        return JSONResponse({"error": "Draft not found"}, status_code=404)

    ok = await queue_service.assign_draft(
        db,
        tenant_id,
        draft_id,
        assigned_operator_id=assigned_operator_id,
        assigned_team_key=assigned_team_key,
        portfolio_key=portfolio_key,
    )
    if not ok:
        return JSONResponse({"error": "Assignment update failed"}, status_code=500)

    return JSONResponse({
        "ok": True,
        "draft_id": draft_id,
        "assigned_operator_id": assigned_operator_id,
        "assigned_team_key": assigned_team_key,
        "portfolio_key": portfolio_key,
        "assignment_status": "assigned" if (assigned_operator_id or assigned_team_key or portfolio_key) else "unassigned",
    })


async def _build_inbox_adapter_for_tenant(
    db: AsyncSession,
    operator_id: str,
    tenant_id: str,
):
    try:
        row = (await db.execute(
            text("""
                SELECT gc.refresh_token, gc.watched_email, gc.tenant_id, COALESCE(gc.email_provider, 'gmail') AS email_provider
                FROM operator_gmail_creds gc
                WHERE gc.operator_id = CAST(:oid AS uuid)
                  AND gc.tenant_id = CAST(:tid AS uuid)
                LIMIT 1
            """),
            {"oid": operator_id, "tid": tenant_id},
        )).fetchone()
    except Exception:
        await _rollback_quietly(db)
        row = None
    if not row:
        try:
            row = (await db.execute(
                text("""
                    SELECT gc.refresh_token, gc.watched_email, gc.tenant_id, COALESCE(gc.email_provider, 'gmail') AS email_provider
                    FROM operator_gmail_creds gc
                    WHERE gc.tenant_id = CAST(:tid AS uuid)
                    ORDER BY gc.connected_at DESC NULLS LAST
                    LIMIT 1
                """),
                {"tid": tenant_id},
            )).fetchone()
        except Exception:
            await _rollback_quietly(db)
            row = None
    if not row:
        return None

    from app.services.messaging.inbox_adapters import InboxAdapterBuildError, InboxAdapterConfig, build_inbox_adapter
    from app.services.property_canonical_write_service import get_canonical_property_write_service

    if (row.email_provider or "gmail").lower() in {"gmail", "google", "microsoft", "outlook", "office365", "m365"}:
        await get_canonical_property_write_service(db).sync_tenant_sources(UUID(str(row.tenant_id)))
    try:
        return build_inbox_adapter(
            InboxAdapterConfig(
                operator_id=operator_id,
                company_id=UUID(str(row.tenant_id)),
                watched_email=row.watched_email,
                refresh_token=row.refresh_token,
                provider=row.email_provider or "gmail",
            ),
            db=db,
        )
    except InboxAdapterBuildError:
        return None


async def _stage_counts(db: AsyncSession, tenant_id: str) -> dict:
    """Per-stage activity counts for tab badges."""
    counts = _empty_stage_counts()
    try:
        r = (await db.execute(
            text("""
                SELECT COUNT(*) FROM pre_booking_inquiries
                WHERE company_id = CAST(:tid AS uuid)
                  AND archived_at IS NULL
                  AND status = 'pending_review'
            """),
            {"tid": tenant_id},
        )).scalar()
        counts["pre_booking"] = int(r or 0)
    except Exception:
        pass
    try:
        rows = (await db.execute(
            text("""
                SELECT
                  SUM(CASE WHEN check_in > CURRENT_DATE THEN 1 ELSE 0 END) AS booked,
                  SUM(CASE WHEN check_in <= CURRENT_DATE AND check_out >= CURRENT_DATE
                           THEN 1 ELSE 0 END) AS in_stay,
                  SUM(CASE WHEN check_out < CURRENT_DATE THEN 1 ELSE 0 END) AS post_stay
                FROM concierge_guest_sessions
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND status NOT IN ('expired', 'closed')
            """),
            {"tid": tenant_id},
        )).fetchone()
        if rows:
            counts["booked"]    = int(rows[0] or 0)
            counts["in_stay"]   = int(rows[1] or 0)
            counts["post_stay"] = int(rows[2] or 0)
    except Exception:
        pass
    try:
        esc_meta = await _escalation_query_meta(db)
        if not esc_meta or not esc_meta["session_token_expr"]:
            raise ValueError("Escalation schema unavailable for stage counts")
        where = ["e.status IN ('pending', 'acknowledged')"]
        if esc_meta["tenant_expr"]:
            where.append("e.tenant_id = CAST(:tid AS uuid)")
        else:
            where.append("s.tenant_id = CAST(:tid AS uuid)")
        r = (await db.execute(
            text("""
                SELECT COUNT(*)
                FROM concierge_escalations e
                LEFT JOIN concierge_guest_sessions s
                  ON s.token = e.""" + esc_meta["session_token_expr"] + """
                WHERE """ + " AND ".join(where) + """
            """),
            {"tid": tenant_id},
        )).scalar()
        counts["escalations"] = int(r or 0)
    except Exception:
        pass
    return counts


async def _active_properties(db: AsyncSession, tenant_id: str) -> list:
    """
    Properties with message or session activity in the last 60 days, for
    the property filter dropdown. Sorted by activity count DESC.
    """
    property_meta = await _property_query_meta(db, "p")
    try:
        if property_meta and property_meta["join_code_exprs"]:
            join_match = " OR ".join(f"{expr} = a.ext" for expr in property_meta["join_code_exprs"])
            rows = (await db.execute(
                text(f"""
                WITH activity AS (
                    SELECT property_external_id AS ext, COUNT(*) AS n
                    FROM pre_booking_inquiries
                    WHERE company_id = CAST(:tid AS uuid)
                      AND received_at > NOW() - INTERVAL '60 days'
                    GROUP BY property_external_id
                    UNION ALL
                    SELECT property_external_id AS ext, COUNT(*) AS n
                    FROM concierge_guest_sessions
                    WHERE tenant_id = CAST(:tid AS uuid)
                      AND created_at > NOW() - INTERVAL '60 days'
                    GROUP BY property_external_id
                )
                SELECT
                    ext AS external_id,
                    SUM(n) AS total,
                    MAX({property_meta["name_expr"]}) AS property_name
                FROM activity a
                LEFT JOIN properties p
                    ON ({join_match})
                   AND {property_meta["where_sql"]}
                WHERE a.ext IS NOT NULL AND a.ext <> ''
                GROUP BY ext
                ORDER BY total DESC
                LIMIT 200
                """),
                {"tid": tenant_id},
            )).mappings().all()
            items = [
                {"id":    r["external_id"] or "",
                 "name":  r["property_name"] or r["external_id"] or "",
                 "count": int(r["total"] or 0)}
                for r in rows
            ]
            if items:
                return items
    except Exception as _pe:
        await _rollback_quietly(db)
        logger.debug("[Messages] active_properties query failed: %s", _pe)
    try:
        if not property_meta:
            return []
        fallback_rows = (await db.execute(
            text(f"""
                SELECT
                    COALESCE(NULLIF({property_meta["code_expr"]}, ''), {property_meta["id_expr"]}::text) AS property_id,
                    {property_meta["name_expr"]} AS property_name
                FROM properties p
                WHERE {property_meta["where_sql"]}
                ORDER BY {property_meta["name_expr"]}
                LIMIT 200
            """),
            {"tid": tenant_id},
        )).mappings().all()
        return [
            {"id": r["property_id"] or "", "name": r["property_name"] or r["property_id"] or "Property", "count": 0}
            for r in fallback_rows
            if r["property_id"]
        ]
    except Exception as _fallback_exc:
        await _rollback_quietly(db)
        logger.debug("[Messages] property roster fallback failed: %s", _fallback_exc)
        return []


# ─────────────────────────────────────────────────────────────────────────────
# POST /app/api/inquiries/{draft_id}/approve — send the AI draft as-is
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/inquiries/{draft_id}/approve")
async def approve_inquiry(
    draft_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    try:
        user = _require_user(request)
    except ValueError:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    tenant_id = user.get("tid") or user.get("tenant_id") or user.get("sub", "")
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response(user)

    try:
        row = (await db.execute(
            text("""
                SELECT draft_id, draft_text, gmail_thread_id, gmail_message_id,
                       guest_email, guest_name, property_external_id, intent,
                       reply_via_gmail, status, company_id
                FROM pre_booking_inquiries
                WHERE draft_id = :did AND company_id = CAST(:tid AS uuid)
                LIMIT 1
            """),
            {"did": draft_id, "tid": tenant_id},
        )).fetchone()

        if not row:
            return _mutation_error(404, "draft_not_found", "Draft not found")

        if row.status in ("replied", "rejected"):
            return _mutation_error(409, "draft_already_actioned", f"Draft already {row.status}")

        # Send via Gmail
        sent = await _send_reply(
            db=db,
            draft_id=draft_id,
            reply_text=row.draft_text,
            gmail_thread_id=row.gmail_thread_id,
            gmail_message_id=row.gmail_message_id,
            guest_email=row.guest_email,
            guest_name=row.guest_name,
            property_external_id=row.property_external_id,
        )

        if sent:
            inquiry = await _persist_inquiry_outcome(
                tenant_id=tenant_id,
                draft_id=draft_id,
                status="replied",
                final_reply=row.draft_text,
                triggered_by="operator",
            )
            if not inquiry:
                return _mutation_error(409, "draft_already_actioned", "Draft not found or already actioned")
            await _publish_inquiry_event(tenant_id=tenant_id, event_name="inquiry.sent", inquiry=inquiry)
            await _sync_queue_best_effort(db, tenant_id, draft_id)
            await _resolve_prebooking_gaps_for_draft(
                db=db,
                tenant_id=tenant_id,
                draft_id=draft_id,
                resolution_notes="Resolved via operator-approved pre-booking reply.",
            )
            await _record_learning_best_effort(
                db,
                action="approve",
                company_id=str(row.company_id),
                draft_id=draft_id,
                intent=row.intent or "general",
                property_external_id=row.property_external_id,
            )
            return JSONResponse({"ok": True, "sent": True, "draft_id": draft_id, "inquiry": inquiry})
        else:
            return _mutation_error(500, "send_failed", "Send failed — check Gmail connection", retryable=True)

    except Exception as e:
        logger.exception("[PreBooking] approve_inquiry failed")
        return _mutation_error(500, "approve_failed", str(e), retryable=True)


# ─────────────────────────────────────────────────────────────────────────────
# POST /app/api/inquiries/{draft_id}/edit — edit text then send
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/inquiries/{draft_id}/edit")
async def edit_and_send_inquiry(
    draft_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    try:
        user = _require_user(request)
    except ValueError:
        return _mutation_error(401, "not_authenticated", "Not authenticated")

    tenant_id = user.get("tid") or user.get("tenant_id") or user.get("sub", "")
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response(user)

    try:
        body = await request.json()
    except Exception:
        return _mutation_error(400, "invalid_json", "Invalid JSON body")

    reply_text = (body.get("reply_text") or "").strip()
    if not reply_text:
        return _mutation_error(400, "reply_text_required", "reply_text is required")

    try:
        row = (await db.execute(
            text("""
                SELECT draft_id, draft_text, gmail_thread_id, gmail_message_id,
                       guest_email, guest_name, property_external_id, intent, status, company_id
                FROM pre_booking_inquiries
                WHERE draft_id = :did AND company_id = CAST(:tid AS uuid)
                LIMIT 1
            """),
            {"did": draft_id, "tid": tenant_id},
        )).fetchone()

        if not row:
            return _mutation_error(404, "draft_not_found", "Draft not found")
        if row.status in ("replied", "rejected"):
            return _mutation_error(409, "draft_already_actioned", f"Draft already {row.status}")

        sent = await _send_reply(
            db=db,
            draft_id=draft_id,
            reply_text=reply_text,
            gmail_thread_id=row.gmail_thread_id,
            gmail_message_id=row.gmail_message_id,
            guest_email=row.guest_email,
            guest_name=row.guest_name,
            property_external_id=row.property_external_id,
        )

        if sent:
            inquiry = await _persist_inquiry_outcome(
                tenant_id=tenant_id,
                draft_id=draft_id,
                status="replied",
                final_reply=reply_text,
                draft_text=reply_text,
                triggered_by="operator",
            )
            if not inquiry:
                return _mutation_error(409, "draft_already_actioned", "Draft not found or already actioned")
            await _publish_inquiry_event(tenant_id=tenant_id, event_name="inquiry.sent", inquiry=inquiry)
            await _sync_queue_best_effort(db, tenant_id, draft_id)
            await _resolve_prebooking_gaps_for_draft(
                db=db,
                tenant_id=tenant_id,
                draft_id=draft_id,
                resolution_notes="Resolved via operator-edited pre-booking reply.",
            )
            await _record_learning_best_effort(
                db,
                action="edit",
                company_id=str(row.company_id),
                draft_id=draft_id,
                intent=row.intent or "general",
                property_external_id=row.property_external_id,
                original_draft=row.draft_text,
                edited_text=reply_text,
            )
            return JSONResponse({"ok": True, "sent": True, "draft_id": draft_id, "inquiry": inquiry})
        else:
            return _mutation_error(500, "send_failed", "Send failed — check Gmail connection", retryable=True)

    except Exception as e:
        logger.exception("[PreBooking] edit_and_send_inquiry failed")
        return _mutation_error(500, "edit_failed", str(e), retryable=True)


# ─────────────────────────────────────────────────────────────────────────────
# POST /app/api/inquiries/{draft_id}/reject — discard without sending
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/inquiries/{draft_id}/reject")
async def reject_inquiry(
    draft_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    try:
        user = _require_user(request)
    except ValueError:
        return _mutation_error(401, "not_authenticated", "Not authenticated")

    tenant_id = user.get("tid") or user.get("tenant_id") or user.get("sub", "")
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response(user)

    try:
        row = (await db.execute(
            text("""
                SELECT intent, property_external_id
                FROM pre_booking_inquiries
                WHERE draft_id=:did AND company_id=CAST(:tid AS uuid)
                LIMIT 1
            """),
            {"did": draft_id, "tid": tenant_id},
        )).fetchone()
        inquiry = await _persist_inquiry_outcome(
            tenant_id=tenant_id,
            draft_id=draft_id,
            status="rejected",
        )
        if not inquiry:
            return _mutation_error(404, "draft_not_found", "Draft not found or already actioned")
        if row:
            await _record_learning_best_effort(
                db,
                action="reject",
                company_id=str(tenant_id),
                draft_id=draft_id,
                intent=row.intent or "general",
                property_external_id=row.property_external_id,
            )
        await _publish_inquiry_event(tenant_id=tenant_id, event_name="inquiry.updated", inquiry=inquiry)
        await _sync_queue_best_effort(db, tenant_id, draft_id)
        return JSONResponse({"ok": True, "rejected": True, "draft_id": draft_id, "inquiry": inquiry})

    except Exception as e:
        logger.exception("[PreBooking] reject_inquiry failed")
        return _mutation_error(500, "reject_failed", str(e), retryable=True)


@router.post("/inquiries/{draft_id}/bind-property")
async def bind_inquiry_property(
    draft_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    try:
        user = _require_user(request)
    except ValueError:
        return _mutation_error(401, "not_authenticated", "Not authenticated")

    operator_id = user.get("scoped_op") or user.get("sub", "")
    tenant_id = user.get("tid") or user.get("tenant_id") or operator_id
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response(user)

    try:
        body = await request.json()
    except Exception:
        return _mutation_error(400, "invalid_json", "Invalid JSON body")

    property_code = (body.get("property_code") or "").strip()
    if not property_code:
        return _mutation_error(400, "property_code_required", "property_code is required")

    visible_property_codes = await scope_service.visible_property_codes(
        db,
        tenant_id,
        user.get("sub", ""),
        user.get("role", "owner"),
    )
    if visible_property_codes is not None and property_code not in visible_property_codes:
        return _mutation_error(403, "property_out_of_scope", "Property is outside your scope")

    bind_result = await _bind_inquiry_property(
        db,
        tenant_id=tenant_id,
        operator_label=user.get("email") or user.get("sub") or "operator",
        draft_id=draft_id,
        property_code=property_code,
        selected_candidate_value=(body.get("selected_candidate_value") or "").strip(),
        selected_candidate_type=(body.get("selected_candidate_type") or "").strip(),
        search_query=(body.get("search_query") or "").strip(),
    )
    if not bind_result.get("ok"):
        return _mutation_error(
            int(bind_result.get("status_code") or 500),
            str(bind_result.get("code") or "bind_failed"),
            str(bind_result.get("message") or "Property bind failed"),
            retryable=int(bind_result.get("status_code") or 500) >= 500,
        )

    regenerate_error = ""
    try:
        from app.services.messaging_brain.pre_booking_retry import (
            reevaluate_existing_prebooking_inquiry,
        )

        result = await reevaluate_existing_prebooking_inquiry(
            db=db,
            tenant_id=tenant_id,
            operator_id=operator_id,
            draft_id=draft_id,
            auto_send_if_allowed=False,
        )
        if not result.get("ok"):
            regenerate_error = str(result.get("error") or "Regenerate failed after property bind")
    except Exception as exc:
        logger.warning("[PreBooking] bind_property regenerate skipped for %s: %s", draft_id, exc)
        regenerate_error = str(exc)

    inquiry = await _load_inquiry_state(db, tenant_id=tenant_id, draft_id=draft_id)
    await _publish_inquiry_event(tenant_id=tenant_id, event_name="inquiry.updated", inquiry=inquiry)
    return JSONResponse(
        {
            "ok": True,
            "draft_id": draft_id,
            "property_code": bind_result.get("property_code") or property_code,
            "property_name": bind_result.get("property_name") or property_code,
            "regenerated": not bool(regenerate_error),
            "regenerate_error": regenerate_error or None,
            "inquiry": inquiry,
        }
    )


@router.post("/inquiries/{draft_id}/regenerate")
async def regenerate_inquiry(
    draft_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    try:
        user = _require_user(request)
    except ValueError:
        return _mutation_error(401, "not_authenticated", "Not authenticated")

    operator_id = user.get("scoped_op") or user.get("sub", "")
    tenant_id = user.get("tid") or user.get("tenant_id") or operator_id
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response(user)

    try:
        from app.services.messaging_brain.pre_booking_retry import (
            reevaluate_existing_prebooking_inquiry,
        )

        result = await reevaluate_existing_prebooking_inquiry(
            db=db,
            tenant_id=tenant_id,
            operator_id=operator_id,
            draft_id=draft_id,
            auto_send_if_allowed=False,
        )
        if not result.get("ok"):
            status_code = 404 if result.get("error") == "Draft not found" else 500
            return _mutation_error(status_code, "regenerate_failed", result.get("error") or "Regenerate failed", retryable=status_code >= 500)
        inquiry = await _load_inquiry_state(db, tenant_id=tenant_id, draft_id=draft_id)
        await _publish_inquiry_event(tenant_id=tenant_id, event_name="inquiry.updated", inquiry=inquiry)
        return JSONResponse({**result, "inquiry": inquiry})
    except Exception as e:
        logger.exception("[PreBooking] regenerate_inquiry failed")
        return _mutation_error(500, "regenerate_failed", str(e), retryable=True)


# ─────────────────────────────────────────────────────────────────────────────
# GET /app/api/inquiries/stats — summary counts for the dashboard header
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/inquiries/stats")
async def inquiry_stats(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    try:
        user = _require_user(request)
    except ValueError:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    tenant_id = user.get("tid") or user.get("tenant_id") or user.get("sub", "")
    if not tenant_id:
        return JSONResponse({"pending": 0, "replied": 0, "rejected": 0, "total_30d": 0})
    # Super admins without a scoped operator have sub="sa_001" (not a UUID).
    # Return zeros for the platform-wide view rather than blowing up the query.
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response(user, empty_payload={"pending": 0, "replied": 0, "rejected": 0, "total_30d": 0})

    try:
        row = (await db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE status='pending_review') AS pending,
                    COUNT(*) FILTER (WHERE status='replied') AS replied,
                    COUNT(*) FILTER (WHERE status='rejected') AS rejected,
                    COUNT(*) AS total
                FROM pre_booking_inquiries
                WHERE company_id = CAST(:tid AS uuid)
                  AND archived_at IS NULL
                  AND received_at >= NOW() - INTERVAL '30 days'
            """),
            {"tid": tenant_id},
        )).fetchone()

        return JSONResponse({
            "pending":  int(row[0] or 0),
            "replied":  int(row[1] or 0),
            "rejected": int(row[2] or 0),
            "total_30d": int(row[3] or 0),
        })

    except Exception as e:
        logger.exception("[PreBooking] inquiry_stats failed")
        return JSONResponse({"pending": 0, "replied": 0, "rejected": 0, "total_30d": 0})


# ─────────────────────────────────────────────────────────────────────────────
# Internal: send reply via Gmail using stored operator credentials
# ─────────────────────────────────────────────────────────────────────────────

async def _send_reply(
    db,
    draft_id: str,
    reply_text: str,
    gmail_thread_id: Optional[str],
    gmail_message_id: Optional[str],
    guest_email: Optional[str],
    guest_name: Optional[str],
    property_external_id: Optional[str],
) -> bool:
    """Send reply via the configured inbox provider using operator credentials."""
    try:
        creds = (await db.execute(
            text("""
                SELECT gc.refresh_token, gc.watched_email,
                       COALESCE(gc.email_provider, 'gmail') AS email_provider,
                       oa.company_name
                FROM pre_booking_inquiries pbi
                JOIN operator_gmail_creds gc ON gc.tenant_id = pbi.company_id
                JOIN operator_accounts oa ON oa.tenant_id = pbi.company_id
                WHERE pbi.draft_id = :did
                LIMIT 1
            """),
            {"did": draft_id},
        )).fetchone()

        if not creds or not creds.refresh_token:
            logger.warning("[PreBooking] No inbox credentials found for draft %s", draft_id)
            return False

        from app.services.messaging.inbox_adapters import InboxAdapterBuildError, InboxAdapterConfig, build_reply_adapter

        try:
            sender = build_reply_adapter(
                InboxAdapterConfig(
                    operator_id="reply",
                    company_id=UUID("00000000-0000-0000-0000-000000000000"),
                    watched_email=creds.watched_email or "",
                    refresh_token=creds.refresh_token,
                    provider=creds.email_provider or "gmail",
                )
            )
        except InboxAdapterBuildError as exc:
            logger.warning("[PreBooking] Reply adapter build failed for draft %s: %s", draft_id, exc)
            return False
        if not sender:
            logger.warning("[PreBooking] Inbox adapter not configured for draft %s", draft_id)
            return False

        # If we have a thread ID, reply into it; otherwise send a new email
        if gmail_thread_id and guest_email:
            return await sender.reply(
                thread_id=gmail_thread_id,
                in_reply_to=gmail_message_id or "",
                to_address=guest_email,
                to_name=guest_name or "Guest",
                subject=f"Re: Your inquiry about {property_external_id or 'our property'}",
                body=reply_text,
                operator_name=creds.company_name or "Your Host",
            )
        elif guest_email:
            # No thread ID — send as new email (fallback)
            return await sender.reply(
                thread_id="",
                in_reply_to="",
                to_address=guest_email,
                to_name=guest_name or "Guest",
                subject=f"Re: Your inquiry about {property_external_id or 'our property'}",
                body=reply_text,
                operator_name=creds.company_name or "Your Host",
            )
        else:
            logger.warning("[PreBooking] No guest_email for draft %s — cannot send", draft_id)
            return False

    except Exception as e:
        logger.exception("[PreBooking] _send_reply failed: %s", e)
        return False
