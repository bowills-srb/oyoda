"""
Twilio SMS Integration — Canonical Concierge Stack

Inbound SMS → signature verification → session lookup → VoicePod → TwiML reply.

All AI generation routes through VoicePod (_run_voice_pod from mobile_v2),
giving SMS the same escalation policy, tenant isolation, and Watch Layer
observability as the mobile chat channel.

SECURITY
  - Every inbound Twilio webhook is HMAC-SHA1 signature-verified before any
    business logic runs (see _require_twilio_signature dependency).
  - DB operations use the async SQLAlchemy session — no sync psycopg2 on the
    async event loop.

SETUP
  1. Configure Twilio webhook: https://your-domain/api/v1/sms/incoming
  2. Set env vars: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER
"""

import base64
import hashlib
import hmac
import logging
import os
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.db.session import get_async_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sms", tags=["SMS"])


# =============================================================================
# CONFIGURATION
# =============================================================================

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class SMSMessage(BaseModel):
    to: str
    body: str
    property_code: Optional[str] = None


class ProactiveMessageRequest(BaseModel):
    property_code: str
    guest_phone: str
    message_type: str
    custom_message: Optional[str] = None


# =============================================================================
# TWILIO SIGNATURE VERIFICATION
# =============================================================================

def _verify_twilio_signature(request_url: str, params: dict, signature: str) -> bool:
    """
    Validate an inbound Twilio webhook signature (HMAC-SHA1).
    Returns True in dev mode when TWILIO_AUTH_TOKEN is unset.
    """
    if not TWILIO_AUTH_TOKEN:
        logger.warning("[sms] TWILIO_AUTH_TOKEN not set — skipping signature check (dev mode)")
        return True
    try:
        from twilio.request_validator import RequestValidator
        return RequestValidator(TWILIO_AUTH_TOKEN).validate(request_url, params, signature)
    except ImportError:
        s = request_url + "".join(k + params[k] for k in sorted(params))
        computed = base64.b64encode(
            hmac.new(TWILIO_AUTH_TOKEN.encode(), s.encode(), hashlib.sha1).digest()
        ).decode()
        return hmac.compare_digest(computed, signature)
    except Exception as exc:
        logger.error("[sms] Signature verification error: %s", exc)
        return False


async def _require_twilio_signature(request: Request) -> dict:
    """FastAPI dependency — rejects requests with invalid Twilio signatures."""
    form_data = dict(await request.form())
    signature = request.headers.get("X-Twilio-Signature", "")
    if not _verify_twilio_signature(str(request.url), form_data, signature):
        logger.warning("[sms] Rejected request with bad Twilio signature from %s", request.client)
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    return form_data


# =============================================================================
# SESSION / PROPERTY LOOKUP
# =============================================================================

async def _lookup_session_by_phone(phone_number: str, db: AsyncSession) -> Optional[object]:
    """
    Find the most-recent active session for a phone number.
    Checks BOTH lead guest phone AND group members (additional guests
    who joined via the share link).

    Returns the concierge_guest_sessions row, which may include a
    `_member_name` attribute for group members (used for personalisation).
    """
    try:
        from app.services.concierge.group_session import get_group_session_service
        svc = get_group_session_service()
        return await svc.get_session_for_phone(db, phone_number)
    except Exception as exc:
        logger.warning("[sms] Phone→session lookup failed: %s", exc)
        return None


# =============================================================================
# INBOUND WEBHOOK (canonical path)
# =============================================================================

@router.post("/incoming")
async def handle_incoming_sms(
    background_tasks: BackgroundTasks,
    form_data: dict = Depends(_require_twilio_signature),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Twilio webhook — inbound SMS.
    Signature verified before this handler runs.
    Routes through VoicePod for consistent policy across all channels.
    """
    from_number: str = form_data.get("From", "")
    body: str = form_data.get("Body", "").strip()

    logger.info("[sms] Inbound from %s: %.80s", from_number, body)

    # Resolve session from guest phone number (lead OR group member)
    db_row = await _lookup_session_by_phone(from_number, db)

    if db_row:
        token = getattr(db_row, "token", None)
        session_id = getattr(db_row, "session_id", None)
        member_name = getattr(db_row, "_member_name", None)  # set for group members only

        # Rate limit check for group members
        if member_name and session_id:
            try:
                from app.services.concierge.group_session import get_group_session_service
                svc = get_group_session_service()
                within_limit = await svc.check_and_increment_message_count(
                    db, session_id, from_number
                )
                if not within_limit:
                    twiml = (
                        '<?xml version="1.0" encoding="UTF-8"?>'
                        "<Response><Message>You've reached the message limit for this stay. "
                        "Please contact the host directly for further assistance.</Message></Response>"
                    )
                    return Response(content=twiml, media_type="application/xml")
            except Exception as _rle:
                logger.debug("[sms] Rate limit check skipped: %s", _rle)

        response_text = await _generate_via_voice_pod(body, token, db_row, db)
    else:
        # No active session — guest texted the number directly without a Coral link
        response_text = (
            "Hi! 🐚 This is Beach Habitats Concierge. "
            "It looks like I don't have your booking on file. "
            "Please contact your host for your personalized concierge link, "
            "or call us at (850) 733-7433."
        )

    # ── Human-feel: typing delay + response variation ──────────────────────
    # Skip delay for urgent keywords (gate codes, emergencies)
    is_urgent = any(w in body.lower() for w in ["gate", "door", "lock", "code", "key", "emergency", "911"])
    if db_row and not is_urgent:
        try:
            from app.services.messaging.human_feel import apply_typing_delay, apply_response_variation
            guest_first = (getattr(db_row, "guest_name", "") or "").split()[0]
            response_text = apply_response_variation(response_text, guest_first)
            await apply_typing_delay(response_text)
        except Exception as _hfe:
            logger.debug("[sms] human_feel skipped (non-fatal): %s", _hfe)

    # Log asynchronously — don't block the response
    background_tasks.add_task(
        _log_sms_async,
        from_number,
        body,
        response_text,
        getattr(db_row, "property_code", None) if db_row else None,
    )

    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{response_text}</Message></Response>"
    )
    return Response(content=twiml, media_type="application/xml")


# =============================================================================
# CANONICAL RUNTIME — VoicePod
# =============================================================================

async def _generate_via_voice_pod(
    message: str,
    token: Optional[str],
    db_row,
    db: AsyncSession,
) -> str:
    """
    Route an SMS message through VoicePod — same runtime as mobile chat.
    Falls back to a safe handoff message on failure.
    """
    FALLBACK = (
        "I'm having a technical issue right now. "
        "Please call Beach Habitats directly at (850) 733-7433 for immediate help."
    )
    try:
        from app.services.concierge.db_session_service import DEFAULT_TENANT_ID

        session_tenant_id = getattr(db_row, "tenant_id", None) or DEFAULT_TENANT_ID
        pod_response = await _run_voice_pod(
            message=message,
            db_session=db,
            db_row=db_row,
            session_tenant_id=session_tenant_id,
            token=token or "",
        )
        return pod_response.text
    except Exception as exc:
        logger.error("[sms] VoicePod routing failed: %s", exc, exc_info=True)
        return FALLBACK


async def _run_voice_pod(*args, **kwargs):
    """Thin wrapper so SMS tests can patch the VoicePod seam directly."""
    from app.api.v1.endpoints.mobile_v2 import _run_voice_pod as mobile_run_voice_pod

    return await mobile_run_voice_pod(*args, **kwargs)


# =============================================================================
# OUTBOUND / PROACTIVE MESSAGING
# =============================================================================

@router.post("/send")
async def send_sms(message: SMSMessage):
    """Send an outbound SMS via Twilio."""
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
        raise HTTPException(status_code=500, detail="Twilio credentials not configured")
    try:
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(
            body=message.body,
            from_=TWILIO_PHONE_NUMBER,
            to=message.to,
        )
        return {"sid": msg.sid, "status": msg.status, "to": message.to}
    except Exception as exc:
        logger.error("[sms] Send failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


PROACTIVE_TEMPLATES = {
    "pre_arrival_3day": (
        "Hi! Your stay at {property_name} is coming up in 3 days! 🏖️\n"
        "Check-in is at {check_in_time}. Reply here with any questions.\n— Beach Habitats"
    ),
    "pre_arrival_1day": (
        "Tomorrow's the day! 🌴\n"
        "{property_name} check-in: {check_in_time}\n"
        "WiFi: {wifi_network} / {wifi_password}\n"
        "See you soon!"
    ),
    "arrival_day": (
        "Welcome to 30A! 🏠 {property_name} is ready.\n"
        "Check-in at {check_in_time}. Text us anytime!"
    ),
    "mid_stay": "Hope you're enjoying {property_name}! 😊 Need tips or help? Just text!",
    "pre_checkout": (
        "Your last day at {property_name} 🌅\n"
        "Check-out is at {check_out_time}. Safe travels — hope to see you back!"
    ),
    "post_stay": (
        "Thanks for staying at {property_name}! 🙏\n"
        "Would you mind leaving a quick review? It really helps! See you next time on 30A!"
    ),
}


@router.post("/proactive")
async def send_proactive_message(
    request: ProactiveMessageRequest,
    db: AsyncSession = Depends(get_async_session),
):
    """Send a proactive lifecycle message to a guest."""
    if request.custom_message:
        body = request.custom_message
    else:
        db_row = await _lookup_session_by_phone(request.guest_phone, db)
        if not db_row:
            raise HTTPException(status_code=404, detail="No active session found for that guest phone")

        from app.services.messaging_brain.proactive_trigger_adapter import (
            build_sms_proactive_intent,
            compose_proactive_draft,
        )

        template = PROACTIVE_TEMPLATES.get(request.message_type)
        if not template:
            raise HTTPException(status_code=400, detail=f"Unknown message_type: {request.message_type}")

        try:
            intent = await build_sms_proactive_intent(
                session_row=db_row,
                message_type=request.message_type,
            )
            draft = await compose_proactive_draft(intent, db_session=db)
            body = str(draft.response_text or "").strip()
            if not body:
                raise RuntimeError("empty proactive brain draft")
        except Exception as exc:
            logger.warning("[sms/proactive] composer_fallback_template_used message_type=%s reason=%s", request.message_type, type(exc).__name__)
            body = template.format(
                property_name=getattr(db_row, "property_name", "your property"),
                check_in_time="4:00 PM",
                check_out_time="10:00 AM",
                wifi_network="",
                wifi_password="",
            )

    return await send_sms(SMSMessage(to=request.guest_phone, body=body, property_code=request.property_code))


# =============================================================================
# ASYNC DB LOGGING
# =============================================================================

async def _log_sms_async(
    from_number: str,
    message_text: str,
    response_text: str,
    property_code: Optional[str],
):
    """
    Log an SMS exchange to the DB using a fresh async session.
    Called as a background task so it never blocks the webhook response.
    """
    try:
        from app.db.session import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("""
                    INSERT INTO guest_conversations (
                        property_code, guest_phone, channel, direction,
                        message_text, response_text
                    ) VALUES (
                        :property_code, :phone, 'sms', 'inbound', :msg, :resp
                    )
                """),
                {
                    "property_code": property_code,
                    "phone": from_number,
                    "msg": message_text,
                    "resp": response_text,
                },
            )
            await db.commit()
    except Exception as exc:
        logger.error("[sms] DB log failed: %s", exc)


# =============================================================================
# UTILITY
# =============================================================================

@router.post("/test")
async def test_sms_response(
    message: str,
    from_number: str = "+15551234567",
    db: AsyncSession = Depends(get_async_session),
):
    """Test SMS pipeline without sending. Resolves session from phone if available."""
    db_row = await _lookup_session_by_phone(from_number, db)
    token = getattr(db_row, "token", None) if db_row else None
    response = (
        await _generate_via_voice_pod(message, token, db_row, db)
        if db_row
        else "No active session found for that number."
    )
    return {
        "input": message,
        "response": response,
        "session_found": bool(db_row),
        "character_count": len(response),
    }
