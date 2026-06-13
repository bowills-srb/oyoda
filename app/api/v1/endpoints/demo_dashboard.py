"""
demo_dashboard.py — self-contained Text + Email operator console (demo).

Serves a single-page dashboard at GET /demo that unifies the fictitious
"Emerald Shores Stays" company's guest conversations across two communication
channels — Text (SMS) and Email — reading from the real concierge tables.

Seed the data first:  python scripts/seed_demo_company.py

This surface is intentionally unauthenticated and read-only (sending is
simulated client-side) — it is a demo, not the production operator app at /app.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from functools import lru_cache

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session

router = APIRouter(prefix="/demo", tags=["Demo"])

DEMO_TENANT_ID = "22222222-2222-2222-2222-222222222222"
# app/api/v1/endpoints/demo_dashboard.py → ascend to the app/ package, then static/demo
_APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_TEMPLATE = os.path.join(_APP_DIR, "static", "demo", "dashboard.html")

_STAGE_LABELS = {
    "pre_booking": "Pre-booking", "pre_arrival": "Booked · pre-arrival",
    "arrival_day": "Arrival day", "in_stay": "In-stay",
    "departure_day": "Departure day", "post_stay": "Post-stay", "expired": "Closed",
}
_STATUS_LABELS = {
    "pending_review": "AI draft · pending review", "replied": "Replied", "rejected": "Rejected",
    "active": "Active", "closed": "Closed", "expired": "Expired", "feedback_pending": "Awaiting feedback",
}


def _iso(v):
    return v.isoformat() if v is not None else None


@lru_cache(maxsize=1)
def _template() -> str:
    with open(_TEMPLATE, "r", encoding="utf-8") as fh:
        return fh.read()


async def build_demo_payload(db: AsyncSession) -> dict:
    """Assemble the unified Text+Email conversation feed for the demo tenant."""
    company = (await db.execute(
        text("SELECT display_name FROM tenants WHERE id = CAST(:t AS uuid)"), {"t": DEMO_TENANT_ID}
    )).scalar() or "Emerald Shores Stays"

    prop_names = {
        r["property_code"]: r["address_street"]
        for r in (await db.execute(
            text("SELECT property_code, address_street FROM properties WHERE tenant_id = CAST(:t AS uuid)"),
            {"t": DEMO_TENANT_ID},
        )).mappings().all()
    }

    conversations: list[dict] = []

    # ── Email pre-booking inquiries ──────────────────────────────────────────
    inq_rows = (await db.execute(text("""
        SELECT draft_id, platform, guest_name, message_text, draft_text, final_reply, status,
               property_external_id, requested_check_in, requested_check_out, received_at
        FROM pre_booking_inquiries
        WHERE company_id = CAST(:t AS uuid) OR tenant_id = CAST(:t AS uuid)
    """), {"t": DEMO_TENANT_ID})).mappings().all()
    for r in inq_rows:
        channel = "email" if (r["platform"] or "email") != "sms" else "text"
        messages = [{"dir": "inbound", "text": r["message_text"] or "", "at": _iso(r["received_at"]), "kind": "message"}]
        if r["final_reply"]:
            messages.append({"dir": "outbound", "text": r["final_reply"], "at": _iso(r["received_at"]), "kind": "message"})
        elif r["draft_text"]:
            messages.append({"dir": "outbound", "text": r["draft_text"], "at": None, "kind": "draft"})
        conversations.append({
            "id": f"inq:{r['draft_id']}", "channel": channel, "stage": "pre_booking",
            "stage_label": _STAGE_LABELS["pre_booking"],
            "status": r["status"], "status_label": _STATUS_LABELS.get(r["status"], r["status"] or ""),
            "guest": r["guest_name"] or "Guest",
            "property": prop_names.get(r["property_external_id"], r["property_external_id"] or "Unknown"),
            "dates": f"{r['requested_check_in']} → {r['requested_check_out']}" if r["requested_check_in"] else "",
            "escalated": False, "priority": None,
            "last_preview": r["message_text"] or "", "last_at": _iso(r["received_at"]),
            "messages": messages,
        })

    # ── Sessions (Text + Email) ──────────────────────────────────────────────
    sess_rows = (await db.execute(text("""
        SELECT session_id, token, guest_name, property_name, property_code,
               check_in, check_out, status, phase,
               COALESCE(property_context->>'channel','sms') AS channel,
               last_message_at, created_at
        FROM concierge_guest_sessions
        WHERE tenant_id = CAST(:t AS uuid)
    """), {"t": DEMO_TENANT_ID})).mappings().all()

    escalated_tokens = {
        r["session_token"]: r["priority"]
        for r in (await db.execute(text("""
            SELECT session_token, priority FROM concierge_escalations
            WHERE session_token IN (SELECT token FROM concierge_guest_sessions WHERE tenant_id = CAST(:t AS uuid))
        """), {"t": DEMO_TENANT_ID})).mappings().all()
    }

    for r in sess_rows:
        msgs = (await db.execute(text("""
            SELECT direction, content, created_at FROM concierge_messages
            WHERE session_id = :sid ORDER BY created_at ASC
        """), {"sid": r["session_id"]})).mappings().all()
        messages = [{"dir": m["direction"], "text": m["content"], "at": _iso(m["created_at"]), "kind": "message"} for m in msgs]
        last_preview = messages[-1]["text"] if messages else ""
        channel = "email" if r["channel"] == "email" else "text"
        is_esc = r["token"] in escalated_tokens
        conversations.append({
            "id": f"ses:{r['token']}", "channel": channel, "stage": r["phase"],
            "stage_label": ("Escalation" if is_esc else _STAGE_LABELS.get(r["phase"], r["phase"] or "")),
            "status": r["status"], "status_label": _STATUS_LABELS.get(r["status"], r["status"] or ""),
            "guest": r["guest_name"] or "Guest", "property": r["property_name"] or r["property_code"],
            "dates": f"{r['check_in']} → {r['check_out']}" if r["check_in"] else "",
            "escalated": is_esc, "priority": escalated_tokens.get(r["token"]),
            "last_preview": last_preview, "last_at": _iso(r["last_message_at"] or r["created_at"]),
            "messages": messages,
        })

    # Escalations first, then most-recent activity
    conversations.sort(key=lambda c: (0 if c["escalated"] else 1, c["last_at"] or ""), reverse=False)
    conversations.sort(key=lambda c: (c["escalated"], c["last_at"] or ""), reverse=True)

    stats = {
        "total": len(conversations),
        "text": sum(1 for c in conversations if c["channel"] == "text"),
        "email": sum(1 for c in conversations if c["channel"] == "email"),
        "escalations": sum(1 for c in conversations if c["escalated"]),
    }
    return {
        "company": company,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "stats": stats,
        "conversations": conversations,
    }


@router.get("", response_class=HTMLResponse)
async def demo_page(db: AsyncSession = Depends(get_async_session)):
    payload = await build_demo_payload(db)
    html = _template().replace("__DEMO_DATA__", json.dumps(payload))
    return HTMLResponse(html)


@router.get("/api/conversations")
async def demo_conversations(db: AsyncSession = Depends(get_async_session)):
    return JSONResponse(await build_demo_payload(db))
