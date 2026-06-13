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

from fastapi import APIRouter, Body, Depends
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
_INTENT_LABELS = {
    "availability": "Availability", "amenity": "Amenity / feature", "policy": "Policy",
    "booking": "Booking", "general": "General",
}
_ROUTING_LABELS = {
    "auto_sent": "Auto-sent — high confidence",
    "routed_to_action_below_threshold": "Routed to you — confidence below auto-send threshold",
    "routed_to_action_auto_off": "Routed to you — autonomy off",
    "routed_to_action_kb_gap": "Routed to you — knowledge gap detected",
    "routed_to_action_policy_review": "Routed to you — policy review needed",
}
_CSOURCE_LABELS = {
    "model_composer": "Drafted by the model composer",
    "held_for_review": "Held for human review",
    "exception_fallback": "Exception fallback",
    "gap_blocked": "Blocked by a knowledge gap",
    "deterministic_known_fact": "Answered from known property facts",
    "intent_only": "Intent classified only",
}


def _iso(v):
    return v.isoformat() if v is not None else None


def _coerce_list(v):
    """jsonb may arrive as a Python list or a JSON string depending on the driver."""
    if not v:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            out = json.loads(v)
            return out if isinstance(out, list) else []
        except Exception:
            return []
    return []


@lru_cache(maxsize=1)
def _template() -> str:
    with open(_TEMPLATE, "r", encoding="utf-8") as fh:
        return fh.read()


async def build_demo_payload(db: AsyncSession) -> dict:
    """Assemble the unified Text+Email conversation feed for the demo tenant."""
    company = (await db.execute(
        text("SELECT display_name FROM tenants WHERE id = CAST(:t AS uuid)"), {"t": DEMO_TENANT_ID}
    )).scalar() or "Emerald Shores Stays"

    prop_info: dict[str, dict] = {}
    for r in (await db.execute(
        text("SELECT property_code, address_street, sleeps, max_occupancy FROM properties WHERE tenant_id = CAST(:t AS uuid)"),
        {"t": DEMO_TENANT_ID},
    )).mappings().all():
        prop_info[r["property_code"]] = {
            "name": (r["address_street"] or r["property_code"]).split(",")[0].strip(),
            "sleeps": r["sleeps"],
            "cap": r["max_occupancy"] or r["sleeps"] or 0,
        }

    conversations: list[dict] = []

    # ── Pre-booking inquiries (Text + Email) with AI parse/route signals ──────
    inq_rows = (await db.execute(text("""
        SELECT draft_id, platform, guest_name, message_text, draft_text, final_reply, status,
               property_external_id, requested_check_in, requested_check_out, requested_guests,
               received_at, intent, confidence, intent_confidence, draft_confidence,
               autonomy_decision, confidence_source, extracted_asks, blocked_by_gap_topics
        FROM pre_booking_inquiries
        WHERE company_id = CAST(:t AS uuid) OR tenant_id = CAST(:t AS uuid)
    """), {"t": DEMO_TENANT_ID})).mappings().all()
    for r in inq_rows:
        channel = "email" if (r["platform"] or "email") != "sms" else "text"
        code = r["property_external_id"] or ""
        bound = bool(code) and code in prop_info
        prop_label = prop_info[code]["name"] if bound else "Portfolio inquiry — no property yet"
        asks = _coerce_list(r["extracted_asks"])
        gaps = list(r["blocked_by_gap_topics"] or [])
        conf = float(r["draft_confidence"] if r["draft_confidence"] is not None else (r["confidence"] or 0))
        guests = r["requested_guests"]

        # Portfolio matching: when no property is named, match on beds (sleeps)
        # for the requested party size, best-fit (smallest that fits) first.
        candidates = []
        if not bound and guests:
            fits = [(code_, info) for code_, info in prop_info.items() if (info["sleeps"] or 0) >= guests]
            for code_, info in sorted(fits, key=lambda ci: ci[1]["sleeps"] or 0):
                candidates.append({"name": info["name"], "note": f"sleeps {info['sleeps']}", "code": code_})

        messages = [{"dir": "inbound", "text": r["message_text"] or "", "at": _iso(r["received_at"]), "kind": "message"}]
        if r["final_reply"]:
            messages.append({"dir": "outbound", "text": r["final_reply"], "at": _iso(r["received_at"]), "kind": "message"})
        elif r["draft_text"]:
            messages.append({"dir": "outbound", "text": r["draft_text"], "at": None, "kind": "draft"})

        conversations.append({
            "id": f"inq:{r['draft_id']}", "channel": channel, "stage": "pre_booking",
            "stage_label": _STAGE_LABELS["pre_booking"],
            "status": r["status"], "status_label": _STATUS_LABELS.get(r["status"], r["status"] or ""),
            "guest": r["guest_name"] or "Guest", "property": prop_label,
            "dates": f"{r['requested_check_in']} → {r['requested_check_out']}" if r["requested_check_in"] else "",
            "escalated": False, "priority": None,
            "last_preview": r["message_text"] or "", "last_at": _iso(r["received_at"]),
            "ai": {
                "intent": _INTENT_LABELS.get(r["intent"], (r["intent"] or "—").title()),
                "confidence": round(conf * 100),
                "intent_confidence": round(float(r["intent_confidence"] or 0) * 100),
                "draft_confidence": round(float(r["draft_confidence"] if r["draft_confidence"] is not None else conf) * 100),
                "confidence_source": _CSOURCE_LABELS.get(str(r["confidence_source"]), str(r["confidence_source"] or "")),
                "asks": asks,
                "bound_property": prop_label if bound else None,
                "candidates": candidates,
                "routing": _ROUTING_LABELS.get(str(r["autonomy_decision"]), str(r["autonomy_decision"] or "")),
                "gaps": gaps,
            },
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


@router.post("/api/inquiries/{draft_id}/bind")
async def bind_inquiry(
    draft_id: str,
    payload: dict = Body(default={}),
    db: AsyncSession = Depends(get_async_session),
):
    """Operator action: bind an unbound pre-booking inquiry to a property."""
    code = (payload or {}).get("property_code", "")
    result = await db.execute(
        text("""
            UPDATE pre_booking_inquiries
               SET property_external_id = :code
             WHERE draft_id = :draft_id
               AND (company_id = CAST(:t AS uuid) OR tenant_id = CAST(:t AS uuid))
        """),
        {"code": code, "draft_id": draft_id, "t": DEMO_TENANT_ID},
    )
    await db.commit()
    return JSONResponse({"ok": result.rowcount > 0, "draft_id": draft_id, "property_code": code})
