"""
Operator Onboarding Setup UI + Operators Listing API

Serves:
  GET  /onboarding-setup          → Full conversational onboarding wizard (HTML)
  GET  /api/v1/operators          → List all operators (for dashboard switcher)
  POST /api/v1/operators          → Register a new operator (from completed onboarding)
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter(tags=["Operator Onboarding"])


def _load_current_user(request: Request) -> Optional[dict]:
    from app.api.v1.endpoints.operator_app import _get_current_user
    return _get_current_user(request)


def _require_authenticated_user(request: Request) -> dict:
    user = _load_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    return user


def _require_super_admin_user(request: Request) -> dict:
    user = _require_authenticated_user(request)
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Super admin access required")
    return user


def _get_operator_access_context(request: Request) -> dict:
    user = _require_authenticated_user(request)
    if user.get("role") == "super_admin":
        scoped_company_id = user.get("scoped_op")
        if not scoped_company_id:
            raise HTTPException(403, "Scope a super admin to an operator before using operator APIs")
        company_id = scoped_company_id
    else:
        company_id = user.get("sub")
    if not company_id:
        raise HTTPException(403, "Operator context is missing from the current session")
    return {
        "user": user,
        "company_id": str(company_id),
        "role": user.get("role", "owner"),
        "email": user.get("email", ""),
    }


def _require_company_access(request: Request, company_id: str) -> dict:
    ctx = _get_operator_access_context(request)
    if str(company_id) != ctx["company_id"]:
        raise HTTPException(403, "You do not have access to that operator")
    return ctx


# =============================================================================
# Operators CRUD (used by dashboard switcher)
# =============================================================================

class CreateOperatorRequest(BaseModel):
    name: str
    code: str
    logo_url: Optional[str] = None
    primary_color: str = "#0ea5e9"
    secondary_color: str = "#0284c7"
    concierge_name: str = "Coral"
    concierge_emoji: str = "🐚"
    market_name: Optional[str] = None
    support_phone: Optional[str] = None
    support_email: Optional[str] = None
    base_url: Optional[str] = None


@router.get("/operators")
async def list_operators(request: Request):
    """List all registered operators — used by the dashboard operator switcher."""
    _require_super_admin_user(request)
    from app.models.operator import get_operator_registry
    registry = get_operator_registry()
    ops = registry.list_all()
    return {
        "operators": [
            {
                "id": op.id,
                "code": op.code,
                "name": op.name,
                "logo_url": op.branding.logo_url,
                "primary_color": op.branding.primary_color,
                "concierge_name": op.branding.concierge_name,
                "concierge_emoji": op.branding.concierge_emoji,
                "market_name": getattr(op, "market_name", None),
                "is_active": op.is_active,
            }
            for op in ops
        ]
    }


@router.post("/inquiries/{draft_id}/approve")
async def approve_inquiry_draft(request: Request, draft_id: str, edited_text: str = None):
    """
    Operator approves an AI draft response to a pre-booking inquiry.
    Sends the approved text (or edited version) back to Escapia.

    If edited_text differs from the AI draft, the edit is analyzed and
    stored by the learning engine to improve future drafts.
    """
    from app.core.database import get_db_session
    from sqlalchemy import text
    import uuid

    async with get_db_session() as db:
        result = await db.execute(
            text("""
                SELECT thread_id, company_id, draft_text, status,
                       intent, property_external_id
                FROM pre_booking_inquiries
                WHERE draft_id = :draft_id
            """),
            {"draft_id": draft_id},
        )
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    _require_company_access(request, str(row.company_id))

    if row.status not in ("pending_review", "edited"):
        return {"status": "already_processed", "current_status": row.status}

    reply_text = edited_text.strip() if edited_text else row.draft_text
    final_status = "edited" if edited_text else "approved"
    learning_result = None

    async with get_db_session() as db:
        # ── Learning engine — always record what the operator did ──────────
        from app.services.concierge.operator_learning import get_learning_service
        svc = get_learning_service(db)

        if edited_text and edited_text.strip() != row.draft_text.strip():
            # Operator made changes — analyze and learn from the edit
            learning_result = await svc.record_edit(
                company_id=str(row.company_id),
                draft_id=draft_id,
                original_draft=row.draft_text,
                edited_text=edited_text.strip(),
                intent=row.intent or "general",
                property_external_id=row.property_external_id,
            )
        else:
            # Approved unchanged — positive signal
            await svc.record_approval(
                company_id=str(row.company_id),
                draft_id=draft_id,
                intent=row.intent or "general",
                property_external_id=row.property_external_id,
            )

        # ── Send reply to platform ─────────────────────────────────────────
        from app.services.concierge.escapia_unified import get_escapia_unified_handler
        handler = get_escapia_unified_handler(company_id=uuid.UUID(str(row.company_id)))

        platform_row = await db.execute(
            text("SELECT platform FROM pre_booking_inquiries WHERE draft_id = :d"),
            {"d": draft_id},
        )
        platform = (platform_row.fetchone() or ["unknown"])[0]

        success = await handler.send_platform_reply(
            thread_id=row.thread_id,
            platform=platform,
            reply_text=reply_text,
            draft_id=draft_id,
            db=db,
        )

    return {
        "draft_id": draft_id,
        "status": "replied" if success else "send_failed",
        "reply_sent": success,
        "final_status": final_status,
        "learning": learning_result,
    }


@router.post("/inquiries/{draft_id}/reject")
async def reject_inquiry_draft(request: Request, draft_id: str):
    """Operator rejects an AI draft — marks as rejected, no reply sent.
    Negative signal recorded by learning engine to flag this intent for improvement.
    """
    from app.core.database import get_db_session
    from sqlalchemy import text

    async with get_db_session() as db:
        # Load draft info before updating
        r = await db.execute(
            text("SELECT company_id, intent, property_external_id FROM pre_booking_inquiries "
                 "WHERE draft_id = :d"),
            {"d": draft_id},
        )
        row = r.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
        _require_company_access(request, str(row.company_id))

        await db.execute(
            text("""
                UPDATE pre_booking_inquiries
                SET status = 'rejected', replied_at = NOW()
                WHERE draft_id = :draft_id
            """),
            {"draft_id": draft_id},
        )
        await db.commit()

        # Record rejection signal
        if row:
            from app.services.concierge.operator_learning import get_learning_service
            svc = get_learning_service(db)
            await svc.record_rejection(
                company_id=str(row.company_id),
                draft_id=draft_id,
                intent=row.intent or "general",
                property_external_id=row.property_external_id,
            )

    return {"draft_id": draft_id, "status": "rejected"}


@router.get("/inquiries")
async def list_pending_inquiries(request: Request, company_id: str, status: str = "pending_review"):
    """List pre-booking inquiries for the operator dashboard Pre-Booking panel."""
    _require_company_access(request, company_id)
    from app.core.database import get_db_session
    from sqlalchemy import text

    async with get_db_session() as db:
        result = await db.execute(
            text("""
                SELECT draft_id, thread_id, platform, guest_name,
                       message_text, requested_check_in, requested_check_out,
                       requested_guests, property_external_id,
                       intent, confidence, draft_text,
                       policy_flags, policy_warnings,
                       status, received_at
                FROM pre_booking_inquiries
                WHERE company_id = :cid
                  AND status = :status
                ORDER BY received_at DESC
                LIMIT 50
            """),
            {"cid": company_id, "status": status},
        )
        rows = result.fetchall()

    return {
        "company_id": company_id,
        "status_filter": status,
        "count": len(rows),
        "inquiries": [
            {
                "draft_id": r.draft_id,
                "platform": r.platform,
                "guest_name": r.guest_name,
                "message": r.message_text,
                "check_in": r.requested_check_in.isoformat() if r.requested_check_in else None,
                "check_out": r.requested_check_out.isoformat() if r.requested_check_out else None,
                "guests": r.requested_guests,
                "property_id": r.property_external_id,
                "intent": r.intent,
                "confidence": float(r.confidence or 0),
                "draft_text": r.draft_text,
                "policy_flags": r.policy_flags or [],
                "policy_warnings": r.policy_warnings or [],
                "status": r.status,
                "received_at": r.received_at.isoformat(),
            }
            for r in rows
        ],
    }


# =============================================================================
# ORPHAN MESSAGE MANAGEMENT
# =============================================================================

@router.get("/orphans")
async def list_orphaned_messages(request: Request, company_id: str, status: str = "unresolved"):
    """
    List messages that couldn't be linked to a known property.
    These are awaiting operator resolution via link, resync, or dismiss.
    """
    _require_company_access(request, company_id)
    from app.core.database import get_db_session
    from sqlalchemy import text

    async with get_db_session() as db:
        result = await db.execute(
            text("""
                SELECT id, unresolved_listing_id, thread_id, message_id,
                       platform, guest_name, message_text,
                       status, resolved_listing_id, resolved_at, created_at
                FROM message_orphan_queue
                WHERE company_id = :cid::uuid
                  AND status = :status
                ORDER BY created_at DESC
                LIMIT 100
            """),
            {"cid": company_id, "status": status},
        )
        rows = result.fetchall()

    return {
        "company_id": company_id,
        "status_filter": status,
        "count": len(rows),
        "orphans": [
            {
                "orphan_id": str(r.id),
                "unresolved_listing_id": r.unresolved_listing_id,
                "thread_id": r.thread_id,
                "platform": r.platform,
                "guest_name": r.guest_name,
                "message": r.message_text,
                "status": r.status,
                "resolved_listing_id": r.resolved_listing_id,
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
                "received_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.post("/orphans/{orphan_id}/link")
async def link_orphan_to_property(request: Request, orphan_id: str, company_id: str, listing_id: str):
    """
    Operator manually links an orphaned message to the correct property.
    After linking, the message is re-processed through the normal pipeline.
    """
    _require_company_access(request, company_id)
    from app.core.database import get_db_session
    from app.services.concierge.message_history import OrphanMessageHandler
    import uuid

    async with get_db_session() as db:
        handler = OrphanMessageHandler()
        success = await handler.resolve_by_link(
            db=db,
            orphan_id=orphan_id,
            company_id=uuid.UUID(company_id),
            correct_listing_id=listing_id,
            resolved_by="operator",
        )

    return {
        "orphan_id": orphan_id,
        "linked_to": listing_id,
        "success": success,
        "note": "Message linked. Re-processing on next poll cycle." if success else "Link failed — check orphan ID.",
    }


@router.post("/orphans/{orphan_id}/resync")
async def trigger_resync_for_orphan(request: Request, orphan_id: str, company_id: str):
    """
    Trigger a PMS re-sync to discover the unknown property.
    If the property now exists in Escapia, it will be synced and the
    orphan will auto-resolve on the next poll cycle.
    """
    _require_company_access(request, company_id)
    from app.core.database import get_db_session
    from app.services.concierge.message_history import OrphanMessageHandler
    import uuid

    async with get_db_session() as db:
        handler = OrphanMessageHandler()
        success = await handler.resolve_by_resync(
            db=db,
            orphan_id=orphan_id,
            company_id=uuid.UUID(company_id),
        )

    return {
        "orphan_id": orphan_id,
        "resync_triggered": success,
        "note": "Re-sync queued. Orphan will auto-resolve if the property is found.",
    }


@router.post("/orphans/{orphan_id}/dismiss")
async def dismiss_orphan(request: Request, orphan_id: str, company_id: str):
    """Mark an orphaned message as irrelevant — no action needed."""
    _require_company_access(request, company_id)
    from app.core.database import get_db_session
    from sqlalchemy import text

    async with get_db_session() as db:
        await db.execute(
            text("""
                UPDATE message_orphan_queue
                SET status = 'irrelevant', resolved_at = NOW()
                WHERE id = :id AND company_id = :cid::uuid
            """),
            {"id": orphan_id, "cid": company_id},
        )
        await db.commit()

    return {"orphan_id": orphan_id, "status": "dismissed"}


@router.post("/operators/{company_id}/import-history")
async def trigger_historical_import(request: Request, company_id: str):
    """
    Manually trigger historical message import for an operator.
    Useful after adding new properties or if initial import failed.
    """
    _require_company_access(request, company_id)
    from app.workers.tasks import import_historical_messages_for_operator
    task = import_historical_messages_for_operator.delay(company_id)
    return {
        "status": "queued",
        "task_id": task.id,
        "company_id": company_id,
        "note": "Historical messages will be imported and FAQ signal extracted. This may take several minutes.",
    }


@router.post("/operators/{company_id}/sync-pms")
async def trigger_pms_sync(request: Request, company_id: str):
    """
    Manually trigger a PMS sync for one operator.
    Useful for first-time setup and troubleshooting.
    Returns immediately — sync runs in background via Celery.
    """
    _require_company_access(request, company_id)
    from app.workers.tasks import sync_pms_for_operator
    task = sync_pms_for_operator.delay(company_id)
    return {
        "status": "queued",
        "task_id": task.id,
        "company_id": company_id,
        "message": "PMS sync queued. Check /api/v1/operators/{company_id}/sync-status for results.",
    }


@router.get("/operators/{company_id}/sync-status")
async def get_sync_status(request: Request, company_id: str):
    """Get the most recent PMS sync result for an operator."""
    _require_company_access(request, company_id)
    from app.core.database import get_db_session
    from sqlalchemy import text
    import uuid

    async with get_db_session() as db:
        result = await db.execute(
            text("""
                SELECT success, listings_synced, bookings_synced,
                       error_message, synced_at
                FROM operator_sync_log
                WHERE company_id = :cid
                ORDER BY synced_at DESC
                LIMIT 5
            """),
            {"cid": company_id},
        )
        rows = result.fetchall()

    if not rows:
        return {"company_id": company_id, "syncs": [], "message": "No sync history yet."}

    return {
        "company_id": company_id,
        "latest": {
            "success": rows[0].success,
            "listings_synced": rows[0].listings_synced,
            "bookings_synced": rows[0].bookings_synced,
            "error": rows[0].error_message,
            "synced_at": rows[0].synced_at.isoformat(),
        },
        "history": [
            {
                "success": r.success,
                "listings_synced": r.listings_synced,
                "bookings_synced": r.bookings_synced,
                "synced_at": r.synced_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.post("/operators")
async def create_operator(request: Request, req: CreateOperatorRequest):
    """Register a new operator (called at end of onboarding)."""
    _require_super_admin_user(request)
    from app.models.operator import get_operator_registry
    registry = get_operator_registry()
    op = registry.create_operator(
        code=req.code,
        name=req.name,
        logo_url=req.logo_url or "",
        primary_color=req.primary_color,
        support_phone=req.support_phone,
        support_email=req.support_email,
        concierge_name=req.concierge_name,
        base_url=req.base_url,
    )
    op.branding.concierge_emoji = req.concierge_emoji
    op.branding.secondary_color = req.secondary_color

    # ── Auto-detect market from property addresses (fire-and-forget) ─────────
    # The onboarding request may include addresses; if not, the market
    # detection worker will run after properties are imported.
    addresses = getattr(req, "property_addresses", None) or []
    if not addresses and req.base_url:
        # Use support_email domain or base_url as a weak signal for now;
        # the worker will re-run once actual properties are in the DB.
        addresses = []

    if addresses:
        import asyncio
        from tools.event_scraper import resolve_operator_market
        asyncio.ensure_future(
            resolve_operator_market(
                property_addresses=addresses,
                operator_id=op.id,
                operator_name=op.name,
            )
        )

    return {"id": op.id, "code": op.code, "name": op.name}


# =============================================================================
# Onboarding Setup HTML
# =============================================================================

def _build_onboarding_html() -> str:
    return r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Concierge Setup</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#f8fafc;--surface:#fff;--surface2:#f1f5f9;--border:#e2e8f0;
  --primary:#0ea5e9;--primary-dark:#0369a1;--primary-light:#e0f2fe;
  --text:#0f172a;--text-muted:#64748b;--text-dim:#94a3b8;
  --green:#16a34a;--green-light:#dcfce7;--red:#dc2626;--red-light:#fee2e2;
  --amber:#d97706;--amber-light:#fef3c7;
  --font:'Inter',-apple-system,sans-serif;
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:var(--font);background:var(--bg);color:var(--text);min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:24px 16px 48px}

/* ── LAYOUT ── */
.header{width:100%;max-width:680px;display:flex;align-items:center;gap:14px;margin-bottom:28px}
.header-logo{width:36px;height:36px;background:linear-gradient(135deg,var(--primary),var(--primary-dark));border-radius:9px;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:800;font-size:14px;flex-shrink:0}
.header-title{font-size:18px;font-weight:700;letter-spacing:-.02em}
.header-sub{font-size:13px;color:var(--text-muted)}
.header-step{margin-left:auto;font-size:12px;color:var(--text-muted);white-space:nowrap}

/* ── PROGRESS BAR ── */
.progress-wrap{width:100%;max-width:680px;margin-bottom:24px}
.progress-steps{display:flex;justify-content:space-between;margin-bottom:8px}
.progress-step{display:flex;flex-direction:column;align-items:center;gap:4px;flex:1;position:relative}
.progress-step::after{content:'';position:absolute;top:12px;left:50%;width:100%;height:2px;background:var(--border);z-index:0}
.progress-step:last-child::after{display:none}
.progress-dot{width:24px;height:24px;border-radius:50%;border:2px solid var(--border);background:var(--surface);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;color:var(--text-muted);position:relative;z-index:1;transition:all .25s}
.progress-dot.done{background:var(--green);border-color:var(--green);color:#fff}
.progress-dot.active{background:var(--primary);border-color:var(--primary);color:#fff;box-shadow:0 0 0 4px rgba(14,165,233,.15)}
.progress-label{font-size:10px;color:var(--text-muted);white-space:nowrap;margin-top:2px}
.progress-label.active{color:var(--primary);font-weight:500}
.progress-bar-wrap{height:4px;background:var(--border);border-radius:4px;overflow:hidden}
.progress-bar-fill{height:100%;background:linear-gradient(90deg,var(--primary),var(--primary-dark));border-radius:4px;transition:width .4s ease}

/* ── CARD ── */
.card{width:100%;max-width:680px;background:var(--surface);border:1px solid var(--border);border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.06)}
.card-body{padding:28px 32px}

/* ── CHAT BUBBLE ── */
.agent-bubble{display:flex;gap:14px;margin-bottom:20px;animation:fadeUp .3s ease}
@keyframes fadeUp{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
.agent-avatar{width:38px;height:38px;border-radius:50%;background:linear-gradient(135deg,var(--primary),var(--primary-dark));display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0}
.agent-message{flex:1;background:var(--surface2);border-radius:4px 16px 16px 16px;padding:14px 16px;font-size:14.5px;line-height:1.65;color:var(--text)}
.agent-message strong{color:var(--primary-dark)}
.agent-message .emoji-big{font-size:28px;display:block;margin-bottom:8px}

/* ── INPUT AREA ── */
.input-area{padding:20px 32px 24px;border-top:1px solid var(--border);background:var(--surface)}

/* Text input */
.text-row{display:flex;gap:10px;align-items:center}
input[type=text], input[type=tel], input[type=email], input[type=url], input[type=password]{
  flex:1;padding:12px 16px;border:2px solid var(--border);border-radius:10px;font-size:14px;
  font-family:var(--font);color:var(--text);background:var(--bg);transition:border-color .15s;outline:none}
input:focus{border-color:var(--primary);background:#fff}
input::placeholder{color:var(--text-dim)}
input[type=password]{-webkit-text-security:disc}

.send-btn{width:44px;height:44px;border-radius:10px;border:none;background:var(--primary);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:background .15s}
.send-btn:hover{background:var(--primary-dark)}
.send-btn svg{width:18px;height:18px}
.send-btn:disabled{opacity:.4;cursor:not-allowed}

/* Select grid */
.select-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px}
.select-option{padding:12px 16px;border:2px solid var(--border);border-radius:10px;cursor:pointer;transition:all .15s;font-size:13.5px;font-weight:450;color:var(--text);background:var(--bg);display:flex;align-items:center;gap:8px}
.select-option:hover{border-color:var(--primary);background:var(--primary-light);color:var(--primary-dark)}
.select-option.selected{border-color:var(--primary);background:var(--primary-light);color:var(--primary-dark);font-weight:600}
.select-option .check{width:18px;height:18px;border-radius:50%;border:2px solid var(--border);display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:10px;transition:all .15s}
.select-option.selected .check{background:var(--primary);border-color:var(--primary);color:#fff}

/* Action buttons */
.action-btns{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.action-btn{padding:8px 16px;border-radius:8px;border:1px solid var(--border);background:transparent;color:var(--text-muted);font-size:12.5px;font-weight:500;cursor:pointer;font-family:var(--font);transition:all .15s}
.action-btn:hover{border-color:var(--primary);color:var(--primary);background:var(--primary-light)}

/* Color pickers row */
.color-row{display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap}
.color-group{display:flex;flex-direction:column;gap:5px;flex:1;min-width:140px}
.color-group label{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);font-weight:600}
.color-input-wrap{display:flex;align-items:center;gap:8px;border:2px solid var(--border);border-radius:10px;padding:6px 12px;background:var(--bg);cursor:pointer;transition:border-color .15s}
.color-input-wrap:focus-within{border-color:var(--primary)}
.color-swatch{width:24px;height:24px;border-radius:6px;border:1px solid rgba(0,0,0,.08);flex-shrink:0}
.color-hex{flex:1;font-family:monospace;font-size:13px;border:none;outline:none;background:transparent;color:var(--text)}
input[type=color]{opacity:0;position:absolute;width:0;height:0}

/* Preview card */
.preview-card{margin-top:16px;border-radius:12px;overflow:hidden;border:1px solid var(--border);max-width:280px}
.preview-header{padding:12px 16px;display:flex;align-items:center;gap:10px}
.preview-logo{height:24px;width:auto;object-fit:contain;filter:brightness(0) invert(1);max-width:100px}
.preview-name{color:#fff;font-size:13px;font-weight:600}
.preview-bubble{margin:12px;padding:10px 14px;border-radius:4px 12px 12px 12px;font-size:12px;line-height:1.5;background:#fff;border:1px solid rgba(0,0,0,.06)}

/* Summary */
.summary-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
.summary-item{padding:12px 14px;background:var(--surface2);border-radius:8px}
.summary-label{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted);margin-bottom:4px;font-weight:600}
.summary-value{font-size:14px;color:var(--text);font-weight:500}

/* Success screen */
.success-screen{display:none;flex-direction:column;align-items:center;text-align:center;padding:48px 32px}
.success-icon{font-size:64px;margin-bottom:20px;animation:pop .4s ease}
@keyframes pop{0%{transform:scale(.5)}70%{transform:scale(1.15)}100%{transform:scale(1)}}
.success-title{font-size:26px;font-weight:700;margin-bottom:10px;color:var(--text)}
.success-sub{font-size:15px;color:var(--text-muted);line-height:1.6;margin-bottom:28px;max-width:440px}
.success-actions{display:flex;gap:12px;flex-wrap:wrap;justify-content:center}
.btn-primary{padding:12px 24px;border-radius:10px;border:none;background:var(--primary);color:#fff;font-size:14px;font-weight:600;cursor:pointer;font-family:var(--font);transition:background .15s;text-decoration:none;display:inline-flex;align-items:center;gap:8px}
.btn-primary:hover{background:var(--primary-dark)}
.btn-secondary{padding:12px 24px;border-radius:10px;border:2px solid var(--border);background:transparent;color:var(--text);font-size:14px;font-weight:600;cursor:pointer;font-family:var(--font);transition:all .15s;text-decoration:none;display:inline-flex;align-items:center;gap:8px}
.btn-secondary:hover{border-color:var(--primary);color:var(--primary);background:var(--primary-light)}

/* Typing indicator */
.typing-row{display:flex;gap:14px;margin-bottom:20px}
.typing-dots{display:flex;gap:5px;padding:14px 18px;background:var(--surface2);border-radius:4px 16px 16px 16px;align-items:center}
.typing-dots span{width:7px;height:7px;background:var(--primary);border-radius:50%;animation:bounce 1.4s infinite;opacity:.5}
.typing-dots span:nth-child(2){animation-delay:.2s}
.typing-dots span:nth-child(3){animation-delay:.4s}
@keyframes bounce{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-6px)}}

.error-msg{color:var(--red);font-size:12px;margin-top:6px;display:none}
.error-msg.show{display:block}
</style>
</head>
<body>

<!-- HEADER -->
<div class="header">
  <div class="header-logo">BH</div>
  <div>
    <div class="header-title">Concierge Setup</div>
    <div class="header-sub">Set up your AI-powered guest concierge</div>
  </div>
  <div class="header-step" id="header-step">Step 1 of 8</div>
</div>

<!-- PROGRESS -->
<div class="progress-wrap">
  <div class="progress-steps">
    <div class="progress-step"><div class="progress-dot active" id="dot-basics">1</div><div class="progress-label active" id="lbl-basics">Basics</div></div>
    <div class="progress-step"><div class="progress-dot" id="dot-branding">2</div><div class="progress-label" id="lbl-branding">Branding</div></div>
    <div class="progress-step"><div class="progress-dot" id="dot-integration">3</div><div class="progress-label" id="lbl-integration">Properties</div></div>
    <div class="progress-step"><div class="progress-dot" id="dot-policies">4</div><div class="progress-label" id="lbl-policies">Policies</div></div>
    <div class="progress-step"><div class="progress-dot" id="dot-knowledge_base">5</div><div class="progress-label" id="lbl-knowledge_base">Knowledge</div></div>
    <div class="progress-step"><div class="progress-dot" id="dot-activation">6</div><div class="progress-label" id="lbl-activation">Activate</div></div>
  </div>
  <div class="progress-bar-wrap"><div class="progress-bar-fill" id="progress-fill" style="width:0%"></div></div>
</div>

<!-- CARD -->
<div class="card" id="main-card">

  <!-- Main conversation area -->
  <div id="main-screen">
    <div class="card-body" id="messages-area">
      <!-- messages injected here -->
    </div>

    <!-- Input area (swapped based on input_type) -->
    <div class="input-area" id="input-area">
      <!-- injected dynamically -->
    </div>
  </div>

  <!-- Success screen -->
  <div class="success-screen" id="success-screen">
    <div class="success-icon">🎉</div>
    <div class="success-title">Your Concierge Is Live!</div>
    <div class="success-sub" id="success-body">Your AI concierge is ready to help guests.</div>
    <div class="success-actions">
      <a href="/operator-dashboard" class="btn-primary">📊 View Dashboard</a>
      <button class="btn-secondary" onclick="startAnother()">+ Add Another Operator</button>
    </div>
  </div>

</div>

<script>
const API = '/api/v1';
let sessionId = null;
let currentInputType = 'text';
let currentOptions = [];
let selectedValue = null;
let colorPrimary = '#0ea5e9';
let colorSecondary = '#0284c7';
let currentConciergeEmoji = '🐚';
let currentConciergeName = 'Coral';
let currentLogoUrl = '';
let capturedBranding = {};

// ── STEP TRACKING ──────────────────────────────
const STEP_ORDER = ['basics','branding','integration','policies','properties','knowledge_base','activation','completed'];
function updateProgress(step, pct) {
  const stepIdx = STEP_ORDER.indexOf(step);
  STEP_ORDER.forEach((s, i) => {
    const dot = document.getElementById('dot-' + s);
    const lbl = document.getElementById('lbl-' + s);
    if (!dot) return;
    dot.className = 'progress-dot';
    lbl.className = 'progress-label';
    if (i < stepIdx) { dot.className += ' done'; dot.innerHTML = '✓'; }
    else if (i === stepIdx) { dot.className += ' active'; dot.innerHTML = (i+1)+''; lbl.className += ' active'; }
    else { dot.innerHTML = (i+1)+''; }
  });
  document.getElementById('progress-fill').style.width = pct + '%';
  const stepNum = Math.max(1, stepIdx + 1);
  document.getElementById('header-step').textContent = `Step ${stepNum} of ${STEP_ORDER.length - 1}`;
}

// ── MESSAGE RENDERING ──────────────────────────
function addAgentMessage(text, emoji) {
  const area = document.getElementById('messages-area');
  const div = document.createElement('div');
  div.className = 'agent-bubble';
  const formattedText = text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n\n/g, '<br><br>')
    .replace(/\n/g, '<br>')
    .replace(/^(#{1,3})\s+(.+)$/gm, '<strong>$2</strong>');
  div.innerHTML = `
    <div class="agent-avatar">${emoji || '🐚'}</div>
    <div class="agent-message">${formattedText}</div>`;
  area.appendChild(div);
  area.scrollTop = area.scrollHeight;
}

function showTyping() {
  const area = document.getElementById('messages-area');
  const div = document.createElement('div');
  div.className = 'typing-row'; div.id = 'typing-indicator';
  div.innerHTML = `<div style="width:38px;height:38px;border-radius:50%;background:linear-gradient(135deg,var(--primary),var(--primary-dark));display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0">🐚</div>
    <div class="typing-dots"><span></span><span></span><span></span></div>`;
  area.appendChild(div);
  area.scrollTop = area.scrollHeight;
}
function removeTyping() { document.getElementById('typing-indicator')?.remove(); }

// ── INPUT RENDERING ────────────────────────────
function renderInput(type, options, placeholder, actionBtns) {
  currentInputType = type;
  currentOptions = options || [];
  selectedValue = null;
  const area = document.getElementById('input-area');

  if (type === 'select') {
    area.innerHTML = `
      <div class="select-grid" id="select-grid">
        ${(options||[]).map(opt => `
          <div class="select-option" onclick="selectOption('${escAttr(opt.value)}', this)" data-value="${escAttr(opt.value)}">
            <div class="check"></div>
            <span>${escHtml(opt.label)}</span>
          </div>`).join('')}
      </div>
      ${(actionBtns||[]).map(b=>`<div class="action-btns"><button class="action-btn" onclick="handleAction('${escAttr(b.id)}')">${escHtml(b.label)}</button></div>`).join('')}
      <div class="action-btns" style="margin-top:12px">
        <button class="send-btn" id="select-send" onclick="sendSelected()" disabled style="width:auto;padding:10px 20px;border-radius:10px;font-size:14px;font-weight:600;font-family:var(--font)">
          Continue →
        </button>
      </div>`;
  } else if (type === 'colors') {
    area.innerHTML = `
      <div class="color-row">
        <div class="color-group">
          <label>Primary Color</label>
          <div class="color-input-wrap" onclick="document.getElementById('cp1').click()">
            <div class="color-swatch" id="swatch1" style="background:${colorPrimary}"></div>
            <input class="color-hex" id="hex1" value="${colorPrimary}" maxlength="7" oninput="onHexInput(1,this.value)">
            <input type="color" id="cp1" value="${colorPrimary}" oninput="onColorPick(1,this.value)">
          </div>
        </div>
        <div class="color-group">
          <label>Secondary Color</label>
          <div class="color-input-wrap" onclick="document.getElementById('cp2').click()">
            <div class="color-swatch" id="swatch2" style="background:${colorSecondary}"></div>
            <input class="color-hex" id="hex2" value="${colorSecondary}" maxlength="7" oninput="onHexInput(2,this.value)">
            <input type="color" id="cp2" value="${colorSecondary}" oninput="onColorPick(2,this.value)">
          </div>
        </div>
      </div>
      <div id="preview-card-wrap" style="margin-top:16px"></div>
      <div class="action-btns" style="margin-top:16px">
        <button class="send-btn" onclick="sendColors()" style="width:auto;padding:10px 20px;border-radius:10px;font-size:14px;font-weight:600;font-family:var(--font)">
          Use These Colors →
        </button>
        ${(actionBtns||[]).map(b=>`<button class="action-btn" onclick="handleAction('${escAttr(b.id)}')">${escHtml(b.label)}</button>`).join('')}
      </div>`;
    updatePreviewCard();
  } else if (type === 'secure') {
    area.innerHTML = `
      <div class="text-row">
        <input type="password" id="main-input" placeholder="${escAttr(placeholder||'Enter API key...')}" 
               onkeypress="if(event.key==='Enter')sendText()">
        <button class="send-btn" onclick="sendText()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22 2L11 13M22 2L15 22L11 13L2 9L22 2Z"/></svg>
        </button>
      </div>
      ${(actionBtns||[]).map(b=>`<button class="action-btn" style="margin-top:8px" onclick="handleAction('${escAttr(b.id)}')">${escHtml(b.label)}</button>`).join('')}
      <div class="error-msg" id="input-error"></div>`;
    setTimeout(()=>document.getElementById('main-input')?.focus(),100);
  } else {
    // Default text input
    area.innerHTML = `
      <div class="text-row">
        <input type="text" id="main-input" placeholder="${escAttr(placeholder||'Type your answer...')}"
               onkeypress="if(event.key==='Enter')sendText()">
        <button class="send-btn" onclick="sendText()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22 2L11 13M22 2L15 22L11 13L2 9L22 2Z"/></svg>
        </button>
      </div>
      <div class="action-btns">
        ${(actionBtns||[]).map(b=>`<button class="action-btn" onclick="handleAction('${escAttr(b.id)}')">${escHtml(b.label)}</button>`).join('')}
      </div>
      <div class="error-msg" id="input-error"></div>`;
    setTimeout(()=>document.getElementById('main-input')?.focus(),100);
  }
}

function hideInput() { document.getElementById('input-area').innerHTML = ''; }

// ── SELECT HELPERS ─────────────────────────────
function selectOption(val, el) {
  document.querySelectorAll('.select-option').forEach(o=>o.classList.remove('selected'));
  el.classList.add('selected');
  selectedValue = val;
  const btn = document.getElementById('select-send');
  if (btn) btn.disabled = false;
}
function sendSelected() {
  if (!selectedValue) return;
  sendInput(selectedValue);
}

// ── COLOR HELPERS ──────────────────────────────
function onColorPick(n, val) {
  if (n===1) { colorPrimary=val; } else { colorSecondary=val; }
  document.getElementById('hex'+n).value = val;
  document.getElementById('swatch'+n).style.background = val;
  updatePreviewCard();
}
function onHexInput(n, val) {
  if (!/^#[0-9a-fA-F]{6}$/.test(val)) return;
  if (n===1) colorPrimary=val; else colorSecondary=val;
  document.getElementById('swatch'+n).style.background = val;
  document.getElementById('cp'+n).value = val;
  updatePreviewCard();
}
function updatePreviewCard() {
  const wrap = document.getElementById('preview-card-wrap');
  if (!wrap) return;
  wrap.innerHTML = `
    <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px;font-weight:600">Preview</div>
    <div class="preview-card">
      <div class="preview-header" style="background:linear-gradient(135deg,${colorPrimary},${colorSecondary})">
        <span style="font-size:18px">${currentConciergeEmoji}</span>
        <span class="preview-name">${escHtml(currentConciergeName)}</span>
      </div>
      <div style="padding:8px 10px 10px">
        <div class="preview-bubble">Hey! How can I help you today? 😊</div>
      </div>
    </div>`;
}
function sendColors() {
  sendInput(`${colorPrimary},${colorSecondary}`);
}

// ── SEND INPUT ─────────────────────────────────
function sendText() {
  const input = document.getElementById('main-input');
  if (!input) return;
  const val = input.value.trim();
  if (!val) { showError('Please enter a value'); return; }
  sendInput(val);
}
function showError(msg) {
  const e = document.getElementById('input-error');
  if (e) { e.textContent=msg; e.classList.add('show'); setTimeout(()=>e.classList.remove('show'),3000); }
}

async function sendInput(value) {
  if (!sessionId) return;
  hideInput();
  showTyping();
  try {
    const data = await postJSON(`${API}/onboarding/input`, { session_id:sessionId, input_value:value });
    removeTyping();
    handleResponse(data);
  } catch(e) {
    removeTyping();
    addAgentMessage(`Sorry, I hit an error: ${e.message}. Please try again.`, '⚠️');
    renderInput(currentInputType, currentOptions, null, null);
  }
}

function handleAction(actionId) {
  const actionMap = {
    'skip':         ()=>sendInput('skip'),
    'skip_logo':    ()=>sendInput('skip'),
    'use_defaults': ()=>sendInput('use defaults'),
    'start_policies':()=>sendInput('start'),
    'activate':     ()=>sendInput('activate'),
    'build_kb':     ()=>sendInput('build'),
    'other_market': ()=>renderInput('text',null,'Your market name (e.g., "Destin, FL")',null),
    'other_pms':    ()=>renderInput('text',null,'Your PMS name',null),
    'test_first':   ()=>sendInput('test first'),
    'help':         ()=>addAgentMessage('No worries! Just ask me any questions and I\'ll help you out.', '🤝'),
  };
  const fn = actionMap[actionId];
  if (fn) fn(); else sendInput(actionId);
}

// ── API ────────────────────────────────────────
async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) { const e = await r.json().catch(()=>({detail:r.status})); throw new Error(e.detail||r.status); }
  return r.json();
}
async function postJSON(url, body) {
  return fetchJSON(url, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
}

// ── RESPONSE HANDLER ───────────────────────────
function handleResponse(data) {
  // Capture branding as it's set
  if (data.step === 'branding') {
    // Will be captured per-question by tracking pending_question via URL
  }
  
  addAgentMessage(data.message, currentConciergeEmoji || '🐚');
  updateProgress(data.step, data.progress_percent);

  if (data.is_complete) {
    // Register operator and show success screen
    registerAndComplete();
    return;
  }

  if (data.show_input) {
    // Map special cases to our richer input types
    let inputType = data.input_type;
    // If the message talks about colors, use color picker
    if (data.message.toLowerCase().includes('brand colors') || data.message.toLowerCase().includes('your brand color')) {
      inputType = 'colors';
    }
    setTimeout(() => {
      renderInput(inputType, data.input_options, data.input_placeholder, data.action_buttons);
    }, 100);
  } else if (data.action_buttons && data.action_buttons.length) {
    // Show action buttons without text input
    setTimeout(() => {
      const area = document.getElementById('input-area');
      area.innerHTML = `<div class="action-btns">${data.action_buttons.map(b=>`
        <button class="action-btn" style="font-size:14px;padding:10px 20px" onclick="handleAction('${escAttr(b.id)}')">
          ${escHtml(b.label)}
        </button>`).join('')}</div>`;
    }, 100);
  }
}

async function registerAndComplete() {
  // Register operator via API
  try {
    await postJSON(`${API}/operators`, capturedBranding);
  } catch(e) {
    console.warn('Could not register operator:', e.message);
  }
  // Show success screen
  document.getElementById('main-screen').style.display = 'none';
  const s = document.getElementById('success-screen');
  s.style.display = 'flex';
  document.getElementById('success-body').innerHTML =
    `<strong>${capturedBranding.concierge_emoji||'🐚'} ${capturedBranding.concierge_name||'Coral'}</strong> is live for ` +
    `<strong>${capturedBranding.name||'your company'}</strong>.<br>` +
    `Your dashboard and guest links are ready.`;
}

function startAnother() { location.reload(); }

// ── UTILS ──────────────────────────────────────
function escHtml(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function escAttr(s) { return (s||'').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }

// ── INIT ───────────────────────────────────────
(async function init() {
  try {
    const data = await postJSON(`${API}/onboarding/start`, {});
    sessionId = data.session_id;
    addAgentMessage(data.message, '🐚');
    updateProgress(data.step, data.progress_percent);
    renderInput(data.input_type, data.input_options, data.input_placeholder, data.action_buttons);
  } catch(e) {
    addAgentMessage('Having trouble connecting. Please refresh the page.', '⚠️');
  }
})();

// Intercept input sends to capture branding fields
const _origSendInput = sendInput;
window.sendInput = async function(value) {
  // Sniff branding fields by tracking what step + pending question we're on
  // We'll track via the last message content
  const lastMsg = document.querySelector('.agent-bubble:last-of-type .agent-message');
  const msgText = lastMsg?.textContent || '';
  if (msgText.includes("company name") || msgText.includes("What's your company name")) capturedBranding.name = value;
  if (msgText.includes("concierge") && msgText.includes("name")) { capturedBranding.concierge_name = value; currentConciergeName = value; }
  if (msgText.includes("emoji")) { capturedBranding.concierge_emoji = value; currentConciergeEmoji = value; }
  if (msgText.includes("logo")) { capturedBranding.logo_url = value === 'skip' ? '' : value; currentLogoUrl = value; }
  if (msgText.includes("brand colors") || msgText.includes("primary color")) {
    const parts = value.split(',');
    capturedBranding.primary_color = parts[0]?.trim() || colorPrimary;
    capturedBranding.secondary_color = parts[1]?.trim() || colorSecondary;
  }
  return _origSendInput(value);
};
</script>
</body>
</html>""";


@router.get("/onboarding-setup", response_class=HTMLResponse, include_in_schema=False)
async def serve_onboarding_setup():
    return HTMLResponse(content=_build_onboarding_html())
