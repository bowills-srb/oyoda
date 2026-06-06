"""
Messaging Webhook Endpoints

Handles inbound messages from all channels:
  POST /api/v1/webhooks/twilio          → SMS and RCS inbound from Twilio
  POST /api/v1/webhooks/apple-messages  → Apple Messages for Business inbound
  POST /api/v1/webhooks/gmail-push      → Gmail Pub/Sub push notifications

Setup requirements:
  Twilio Console:
    - SMS webhook URL: https://your-domain.com/api/v1/webhooks/twilio
    - RCS webhook URL: same (Twilio adds 'Channel' field to distinguish)
    - HTTP Method: POST
    - Validate Twilio signatures: set TWILIO_VALIDATE_SIGNATURES=true in production

  Apple Messages for Business:
    - Webhook URL: https://your-domain.com/api/v1/webhooks/apple-messages
    - Webhook secret: set in Apple Business Register dashboard

Environment variables:
    TWILIO_AUTH_TOKEN          (for signature validation)
    TWILIO_VALIDATE_SIGNATURES (true/false, default false in dev)
    ABM_WEBHOOK_SECRET         (Apple Messages webhook secret for signature validation)
    GMAIL_PUSH_WEBHOOK_TOKEN   (optional shared secret query token for Gmail push)
"""

import hashlib
import hmac
import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, Form, Header, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse

from app.core.database import get_db_session
from app.services.integrations.gmail_push import (
    decode_gmail_push_pubsub_payload,
    gmail_push_webhook_token,
    record_gmail_push_notification,
)
from app.services.messaging.channel_router import (
    InboundMessageHandler,
    get_channel_router,
    ChannelMessage,
    QuickReply,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Messaging Webhooks"])


# =============================================================================
# TWILIO SIGNATURE VALIDATION
# =============================================================================

def _validate_twilio_signature(
    request_url: str,
    post_params: Dict[str, str],
    x_twilio_signature: str,
    auth_token: str,
) -> bool:
    """
    Validate that a Twilio webhook request is genuine.
    https://www.twilio.com/docs/usage/webhooks/webhooks-security
    """
    try:
        from twilio.request_validator import RequestValidator
        validator = RequestValidator(auth_token)
        return validator.validate(request_url, post_params, x_twilio_signature)
    except ImportError:
        logger.warning("twilio package not installed — skipping signature validation")
        return True
    except Exception as e:
        logger.error(f"Twilio signature validation error: {e}")
        return False


def _validate_apple_signature(
    raw_body: bytes,
    signature_header: str,
    secret: str,
) -> bool:
    """
    Validate Apple Messages for Business webhook signature.
    Apple sends HMAC-SHA256 signature in X-Apple-Signature header.
    """
    try:
        expected = hmac.new(
            secret.encode(),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header or "")
    except Exception as e:
        logger.error(f"ABM signature validation error: {e}")
        return False


# =============================================================================
# TWILIO INBOUND (SMS + RCS)
# =============================================================================

@router.post("/twilio", response_class=PlainTextResponse)
async def twilio_inbound(
    request: Request,
    X_Twilio_Signature: str = Header(default=""),
):
    """
    Inbound webhook for both SMS and RCS messages from Twilio.
    Twilio sends form-encoded POST data.
    Returns TwiML XML to acknowledge.
    """
    validate = os.getenv("TWILIO_VALIDATE_SIGNATURES", "false").lower() == "true"
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")

    # Parse form data
    form_data = await request.form()
    form_dict = dict(form_data)

    # Validate signature in production
    if validate and auth_token:
        url = str(request.url)
        valid = _validate_twilio_signature(
            request_url=url,
            post_params=form_dict,
            x_twilio_signature=X_Twilio_Signature,
            auth_token=auth_token,
        )
        if not valid:
            logger.warning(f"[Webhook/Twilio] Invalid signature from {request.client.host}")
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    # Process the message
    twiml = await InboundMessageHandler.handle_twilio_inbound(form_dict)

    channel = form_dict.get("Channel", "sms")
    from_number = form_dict.get("From", "unknown")
    body_preview = form_dict.get("Body", "")[:50]
    logger.info(f"[Webhook/Twilio/{channel.upper()}] from={from_number} body='{body_preview}'")

    return PlainTextResponse(content=twiml, media_type="application/xml")


# =============================================================================
# APPLE MESSAGES FOR BUSINESS INBOUND
# =============================================================================

@router.post("/apple-messages")
async def apple_messages_inbound(
    request: Request,
    X_Apple_Signature: str = Header(default=""),
):
    """
    Inbound webhook for Apple Messages for Business.
    Apple sends JSON-encoded POST data.
    Returns empty 200 to acknowledge.
    """
    raw_body = await request.body()

    # Validate Apple signature if secret is configured
    abm_secret = os.getenv("ABM_WEBHOOK_SECRET", "")
    if abm_secret:
        valid = _validate_apple_signature(
            raw_body=raw_body,
            signature_header=X_Apple_Signature,
            secret=abm_secret,
        )
        if not valid:
            logger.warning(f"[Webhook/ABM] Invalid signature from {request.client.host}")
            raise HTTPException(status_code=403, detail="Invalid Apple Messages signature")

    import json
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.error("[Webhook/ABM] Invalid JSON payload")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    response_data = await InboundMessageHandler.handle_apple_messages_inbound(payload)

    conversation_id = payload.get("destinationId", "unknown")
    message_type = payload.get("type", "unknown")
    logger.info(f"[Webhook/ABM] conversation={conversation_id} type={message_type}")

    return response_data or {}


@router.post("/gmail-push", status_code=204)
async def gmail_push_inbound(
    request: Request,
    token: str = Query(default=""),
):
    """
    Gmail Pub/Sub push wake-up endpoint.

    Push notifications do not bypass the existing inbox worker path. They wake
    the same operator inbox sync used by scheduled polling so parsing,
    deduplication, routing, and draft generation remain single-homed.
    """
    expected = gmail_push_webhook_token()
    if expected and not hmac.compare_digest(token or "", expected):
        logger.warning("[Webhook/GmailPush] Invalid webhook token")
        raise HTTPException(status_code=403, detail="Invalid Gmail push token")

    try:
        payload = await request.json()
    except Exception:
        logger.warning("[Webhook/GmailPush] Invalid JSON payload")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        notification = decode_gmail_push_pubsub_payload(payload)
    except ValueError as exc:
        logger.warning("[Webhook/GmailPush] Invalid Pub/Sub payload: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))

    async with get_db_session() as db:
        dispatch = await record_gmail_push_notification(
            db,
            notification=notification,
        )

    if dispatch.should_trigger and dispatch.operator_id:
        from app.workers.tasks import poll_connected_inbox_for_operator

        poll_connected_inbox_for_operator.delay(
            dispatch.operator_id,
            "gmail_history",
            "gmail_push",
            dispatch.previous_history_id or "",
            notification.history_id,
        )

    logger.info(
        "[Webhook/GmailPush] watched_email=%s operator=%s history_id=%s trigger=%s reason=%s",
        notification.watched_email,
        dispatch.operator_id or "unknown",
        notification.history_id,
        dispatch.should_trigger,
        dispatch.reason or "ok",
    )
    return Response(status_code=204)


# =============================================================================
# HEALTH CHECK
# =============================================================================

@router.get("/health")
async def messaging_webhook_health():
    """
    Quick health check for the messaging webhook endpoints.
    Useful for monitoring and Twilio/Apple endpoint verification.
    """
    rcs_enabled = os.getenv("TWILIO_RCS_ENABLED", "false").lower() == "true"
    abm_configured = bool(os.getenv("ABM_BUSINESS_ACCOUNT_ID"))
    twilio_configured = bool(os.getenv("TWILIO_ACCOUNT_SID"))

    return {
        "status": "ok",
        "channels": {
            "sms": {"enabled": twilio_configured, "provider": "twilio"},
            "rcs": {"enabled": rcs_enabled, "provider": "twilio", "note": "Requires Twilio RCS alpha approval"},
            "apple_messages": {
                "enabled": abm_configured,
                "provider": "apple",
                "note": "Requires Apple Business Register approval",
            },
            "email_push": {
                "enabled": bool(os.getenv("GMAIL_PUBSUB_TOPIC")),
                "provider": "gmail_pubsub",
                "note": "Push wake-up for connected Gmail inboxes; polling remains fallback.",
            },
        },
        "webhook_endpoints": {
            "twilio": "/api/v1/webhooks/twilio",
            "apple_messages": "/api/v1/webhooks/apple-messages",
            "gmail_push": "/api/v1/webhooks/gmail-push",
        },
    }
