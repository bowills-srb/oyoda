"""
operator_filtered_recovery.py — "Nothing slipped through" surface + recovery

Two endpoints that close the loop on the operator's trust requirement:

  GET  /app/api/filtered          — the reassurance count. Aggregates
                                     message_normalizations by route_outcome
                                     for messages the system saw but did NOT
                                     surface as an actionable inquiry
                                     (suppressed / skipped / dropped / gate-
                                     held / unmatched). This is the "Filtered
                                     today: N" strip on the Today surface,
                                     expandable into a list.

  POST /app/api/filtered/{source_channel}/{source_message_id}/promote
                                  — the recovery pathway. Takes a message that
                                    was recorded in message_normalizations but
                                    never made it into the actionable queue,
                                    rebuilds the canonical inbound from the
                                    stored row, and routes it into
                                    pre_booking_inquiries as an operator-rescued
                                    item (status=pending_review, no AI draft).
                                    Idempotent: relies on the
                                    ON CONFLICT (thread_id, message_id) guard in
                                    _insert_pre_booking_inquiry.

Design notes
------------
* No new store. message_normalizations is already the durable audit row for
  every inbound message (persist_canonical_inbound_message), and
  pre_booking_inquiries is the table the Inquiry Operations queue already
  reads. The rescue just moves a row from "recorded" to "actionable" through
  the existing sanctioned seam (save_inquiry_from_canonical →
  persist_pre_booking_inquiry_with_normalization → _save_inquiry).

* The rescued row sets draft_source="operator_rescue". The existing
  _confidence_meta() in operator_prebooking.py routes any non-model
  draft_source to the "Manual review" label with draft_ready=False, so the
  rescued item renders correctly in the current queue UI with no frontend
  change.

* Auth / tenant resolution / scope handling mirror operator_prebooking.py
  exactly (cookie JWT, _has_valid_tenant_id, super-admin scope-in).

Wire-up: include this router under the same prefix as operator_prebooking
(prefix="/app/api"), e.g. in the app's router assembly:

    from app.api.v1.endpoints import operator_filtered_recovery
    app.include_router(operator_filtered_recovery.router)
"""

from __future__ import annotations

import base64
import json
import logging
import time as _time
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.services.operator.filtered_recovery_service import (
    FILTERED_ROUTE_OUTCOMES,
    _WINDOW_INTERVALS,
    compute_filtered_counts,
    filtered_reason_for as _filtered_reason_for,
)
from app.services.operator.realtime_hub import get_operator_realtime_hub
from app.services.operator.scope_service import get_operator_scope_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/app/api", tags=["Operator Filtered / Recovery"])
scope_service = get_operator_scope_service()


# FILTERED_ROUTE_OUTCOMES, filtered_reason_for, and compute_filtered_counts
# are defined in filtered_recovery_service and imported above. The taxonomy
# lives there so dashboard_summary_service can use the same implementation
# without a circular import.


# ─────────────────────────────────────────────────────────────────────────────
# Auth helpers — copied verbatim from operator_prebooking.py to avoid a
# cross-module import (that file defines them as private and they intentionally
# mirror operator_app.py). Keep these in sync if the auth scheme changes.
# ─────────────────────────────────────────────────────────────────────────────

def _get_current_user(request: Request):
    token = request.cookies.get("oyvoda_access")
    if not token:
        return None
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
        if payload.get("exp", 0) < _time.time():
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
        {"error": "No tenant context", "detail": "No tenant context", **(empty_payload or {})},
        status_code=403,
    )


def _mutation_error(status_code: int, code: str, message: str, retryable: bool = False) -> JSONResponse:
    return JSONResponse(
        {"error": message, "error_detail": {"code": code, "message": message, "retryable": retryable}},
        status_code=status_code,
    )


def _safe_json_list(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return []
    return v or []


# ─────────────────────────────────────────────────────────────────────────────
# GET /app/api/filtered — the "nothing slipped through" reassurance surface
#
# Query params:
#   window:  today | 7d | 30d   (default today)
#   reason:  blank = all reasons, or one of the reason buckets
#            (suppressed | non_guest | needs_review | system) to drill in
#   limit:   max rows when listing (default 50, cap 200)
#   counts_only: true = return only the per-reason counts (for the Today strip)
#
# Response:
#   {
#     "window": "today",
#     "total": 42,
#     "counts": {"suppressed": 9, "non_guest": 18, "needs_review": 3, "system": 12},
#     "items": [ {source_channel, source_message_id, route_outcome, reason,
#                 sender_display_name, sender_address, raw_subject, preview,
#                 sent_at, selected_property_code, promotable}, ... ]
#   }
# ─────────────────────────────────────────────────────────────────────────────

# Outcomes whose reason bucket makes them sensible to promote into the guest
# queue. System/vendor lanes are visible for reassurance but not promotable —
# promoting a Mailchimp newsletter into the inquiry queue would be noise.
_PROMOTABLE_REASONS = {"suppressed", "needs_review", "non_guest"}


@router.get("/filtered")
async def list_filtered(
    request: Request,
    window: str = "today",
    reason: str = "",
    limit: int = 50,
    counts_only: bool = False,
    db: AsyncSession = Depends(get_async_session),
):
    try:
        user = _require_user(request)
    except ValueError:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    tenant_id = _tenant_id_from_user(user)
    empty = {"window": window, "total": 0, "counts": {}, "items": []}
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response(user, empty_payload=empty)

    visible_property_codes = await scope_service.visible_property_codes(
        db, tenant_id, user.get("sub", ""), user.get("role", "owner")
    )

    # Counts come from the shared service so the card and drawer are always
    # derived from the same implementation.
    count_result = await compute_filtered_counts(
        db, tenant_id, window=window, visible_property_codes=visible_property_codes
    )
    counts = count_result["counts"]
    total = count_result["total"]
    requested_reason = (reason or "").strip()

    if counts_only:
        return JSONResponse({
            "window": window,
            "reason": requested_reason,
            "total": total,
            "counts": counts,
            "items": [],
        })

    # Row list — only fetched when the drawer needs full detail.
    interval = _WINDOW_INTERVALS.get(window, "1 day")
    outcomes = list(FILTERED_ROUTE_OUTCOMES.keys())
    cap = max(1, min(int(limit or 50), 200))
    started = _time.perf_counter()
    try:
        rows = (await db.execute(
            text(
                """
                SELECT
                    source_channel,
                    source_message_id,
                    route_outcome,
                    sender_display_name,
                    sender_address,
                    raw_subject,
                    latest_guest_turn,
                    full_message_text,
                    sent_at,
                    selected_property_code,
                    fallback_reason
                FROM message_normalizations
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND route_outcome = ANY(:outcomes)
                  AND COALESCE(sent_at, updated_at) > NOW() - CAST(:interval AS interval)
                ORDER BY COALESCE(sent_at, updated_at) DESC
                LIMIT :hard_cap
                """
            ),
            {"tid": tenant_id, "outcomes": outcomes, "interval": interval, "hard_cap": 2000},
        )).mappings().all()
    except Exception:
        logger.exception("[Filtered] list_filtered row query failed tenant=%s", tenant_id)
        return JSONResponse({**empty, "error": "filtered_query_failed"}, status_code=500)

    items: list[dict] = []
    for r in rows:
        row_reason = _filtered_reason_for(r["route_outcome"]) or "system"
        if visible_property_codes is not None:
            code = str(r["selected_property_code"] or "").strip()
            if code and code not in visible_property_codes:
                continue
        if requested_reason and row_reason != requested_reason:
            continue
        preview = (r["latest_guest_turn"] or r["full_message_text"] or "")[:240]
        items.append({
            "source_channel": r["source_channel"],
            "source_message_id": r["source_message_id"],
            "route_outcome": r["route_outcome"],
            "reason": row_reason,
            "sender_display_name": r["sender_display_name"] or "",
            "sender_address": r["sender_address"] or "",
            "raw_subject": r["raw_subject"] or "",
            "preview": preview,
            "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
            "selected_property_code": r["selected_property_code"] or "",
            "fallback_reason": r["fallback_reason"] or "",
            "promotable": row_reason in _PROMOTABLE_REASONS,
        })

    logger.info(
        "[Filtered] list_filtered tenant=%s window=%s reason=%s total=%s elapsed_ms=%.1f",
        tenant_id, window, requested_reason or "all", total,
        (_time.perf_counter() - started) * 1000,
    )
    return JSONResponse({
        "window": window,
        "reason": requested_reason,
        "total": total,
        "counts": counts,
        "items": items[:cap],
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /app/api/filtered/{source_channel}/{source_message_id}/promote
#
# Recovery pathway: rebuild the canonical inbound from the stored
# message_normalizations row and route it into pre_booking_inquiries as an
# operator-rescued item. Idempotent via ON CONFLICT (thread_id, message_id).
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/filtered/{source_channel}/{source_message_id}/promote")
async def promote_filtered_message(
    source_channel: str,
    source_message_id: str,
    request: Request,
    db: AsyncSession = Depends(get_async_session),
):
    try:
        user = _require_user(request)
    except ValueError:
        return _mutation_error(401, "not_authenticated", "Not authenticated")

    tenant_id = _tenant_id_from_user(user)
    if not _has_valid_tenant_id(tenant_id):
        return _tenant_scope_response(user)

    # 1) Load the durable audit row.
    try:
        row = (await db.execute(
            text(
                """
                SELECT
                    source_channel, source_provider, source_thread_id,
                    source_message_id, sender_role, sender_display_name,
                    sender_address, sent_at, raw_subject, latest_guest_turn,
                    prior_thread_context, full_message_text, structured_asks,
                    prior_operator_commitments, property_binding_candidates,
                    channel_constraints, parser_used, parser_version,
                    parser_notes, latest_turn_confidence, latest_turn_extracted,
                    selected_property_code, route_outcome
                FROM message_normalizations
                WHERE tenant_id = CAST(:tid AS uuid)
                  AND source_channel = :sc
                  AND source_message_id = :smid
                LIMIT 1
                """
            ),
            {"tid": tenant_id, "sc": source_channel, "smid": source_message_id},
        )).mappings().first()
    except Exception:
        await _rollback_quietly(db)
        logger.exception("[Filtered] promote load failed tenant=%s smid=%s", tenant_id, source_message_id)
        return _mutation_error(500, "promote_load_failed", "Could not load the message", retryable=True)

    if not row:
        return _mutation_error(404, "message_not_found", "No recorded message with that id")

    # 2) Scope guard — a scoped operator may only rescue into properties they
    #    can see (rows with no property code remain rescuable; see list scope).
    selected_code = str(row["selected_property_code"] or "").strip()
    if selected_code:
        visible_property_codes = await scope_service.visible_property_codes(
            db, tenant_id, user.get("sub", ""), user.get("role", "owner")
        )
        if visible_property_codes is not None and selected_code not in visible_property_codes:
            return _mutation_error(403, "property_out_of_scope", "Property is outside your scope")

    # 3) Rebuild the canonical inbound from stored columns. CanonicalInboundMessage
    #    is a flat dataclass; message_normalizations stores every field it needs.
    from app.services.messaging.inbound_normalizer import CanonicalInboundMessage
    from app.services.messaging_brain.persistence.prebooking_inquiry_types import (
        InquirySaveContext,
    )
    from app.services.messaging_brain.persistence.prebooking_inquiry_store import (
        save_inquiry_from_canonical,
    )

    inbound = CanonicalInboundMessage(
        source_channel=row["source_channel"] or source_channel,
        source_provider=row["source_provider"] or "",
        source_thread_id=row["source_thread_id"] or "",
        source_message_id=row["source_message_id"] or source_message_id,
        sender_role=row["sender_role"] or "guest",
        sender_display_name=row["sender_display_name"] or "Guest",
        sender_address=row["sender_address"] or "",
        sent_at=row["sent_at"] or datetime.now(timezone.utc),
        raw_subject=row["raw_subject"] or "",
        latest_guest_turn=row["latest_guest_turn"] or "",
        prior_thread_context=row["prior_thread_context"] or "",
        full_message_text=row["full_message_text"] or row["latest_guest_turn"] or "",
        structured_asks=_safe_json_list(row["structured_asks"]),
        prior_operator_commitments=_safe_json_list(row["prior_operator_commitments"]),
        property_binding_candidates=_safe_json_list(row["property_binding_candidates"]),
        channel_constraints=(
            row["channel_constraints"]
            if isinstance(row["channel_constraints"], dict)
            else (json.loads(row["channel_constraints"]) if row["channel_constraints"] else {})
        ),
        parser_used=row["parser_used"] or "operator_rescue",
        parser_version=row["parser_version"] or "v1",
        parser_notes=_safe_json_list(row["parser_notes"]),
        latest_turn_confidence=float(row["latest_turn_confidence"] or 0.0),
        latest_turn_extracted=bool(row["latest_turn_extracted"]),
        guest_name=row["sender_display_name"] or "Guest",
        guest_email=row["sender_address"] or "",
        identity=None,
    )

    # 4) Build a minimal save context for a rescued, draft-less item.
    #    draft_source="operator_rescue" → _confidence_meta renders "Manual
    #    review", draft_ready=False. status becomes pending_review because
    #    decision != "send_now".
    operator_label = user.get("email") or user.get("sub") or "operator"
    context = InquirySaveContext(
        draft_id=str(uuid4()),
        company_id=UUID(str(tenant_id)),
        intent="operator_rescue",
        confidence=0.0,
        draft_text="",
        decision="review",
        selected_property_code=selected_code,
        draft_source="operator_rescue",
        policy_warnings=[f"operator_rescue:from_route_outcome={row['route_outcome'] or 'unknown'}"],
        confidence_source="intent_only",
        review_verdict="hold",
        triggered_by=f"operator_promote:{operator_label}",
    )

    try:
        save_result = await save_inquiry_from_canonical(
            db=db,
            inbound=inbound,
            context=context,
            normalization_kwargs={
                "route_outcome": "pre_booking_operator_rescued",
                "draft_source": "operator_rescue",
            },
        )
    except Exception:
        await _rollback_quietly(db)
        logger.exception("[Filtered] promote save failed tenant=%s smid=%s", tenant_id, source_message_id)
        return _mutation_error(500, "promote_save_failed", "Could not move the message into the queue", retryable=True)

    status = getattr(save_result, "status", "") or ""
    inserted = bool(getattr(save_result, "inserted", False))

    # duplicate_skipped means it was already in the queue (idempotent re-tap or
    # a race) — that's a success from the operator's point of view.
    already = status in {"duplicate", "duplicate_skipped"}
    if not inserted and not already:
        return _mutation_error(
            500,
            "promote_not_saved",
            f"Message could not be queued ({status or 'unknown'})",
            retryable=True,
        )

    # Nudge the realtime hub so the queue refreshes wherever the operator is.
    try:
        hub = get_operator_realtime_hub()
        await hub.publish(tenant_id, "inquiry.updated", {
            "draft_id": context.draft_id,
            "source_message_id": source_message_id,
            "promoted": True,
        })
        await hub.publish(tenant_id, "summary.updated", {
            "tenant_id": tenant_id,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        })
    except Exception as exc:
        logger.debug("[Filtered] promote realtime publish skipped: %s", exc)

    return JSONResponse({
        "ok": True,
        "promoted": True,
        "already_in_queue": already,
        "draft_id": context.draft_id,
        "guest_thread_id": getattr(save_result, "guest_thread_id", None),
        "source_channel": source_channel,
        "source_message_id": source_message_id,
        "status": "queued_for_review",
    })


async def _rollback_quietly(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except Exception:
        pass
