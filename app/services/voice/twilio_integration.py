"""
Twilio voice and SMS integration endpoints.
"""

import base64
import logging
import os
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/twilio", tags=["twilio"])

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")

PHONE_PROPERTY_MAP = {}
_session_manager = None


def get_session_manager():
    global _session_manager
    if _session_manager is None:
        from app.services.voice.voice_session import VoiceSessionManager

        _session_manager = VoiceSessionManager()
    return _session_manager


def get_twilio_client():
    from twilio.rest import Client as TwilioClient

    return TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def validate_twilio_request(request: Request, body: bytes) -> bool:
    """Validate that a webhook request came from Twilio."""
    if not TWILIO_AUTH_TOKEN:
        return True

    from twilio.request_validator import RequestValidator

    validator = RequestValidator(TWILIO_AUTH_TOKEN)
    signature = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)

    params = {}
    try:
        params = dict(item.split("=", 1) for item in body.decode().split("&") if "=" in item)
    except Exception:
        params = {}

    return validator.validate(url, params, signature)


def lookup_property_code(phone_number: str, to_number: str) -> Optional[str]:
    """Look up a property code from the destination number."""
    del phone_number
    return PHONE_PROPERTY_MAP.get(to_number)


@router.post("/voice")
async def handle_incoming_call(request: Request):
    """Return TwiML that connects the call to the realtime voice stream."""
    from twilio.twiml.voice_response import Connect, Stream, VoiceResponse

    body = await request.body()
    if not validate_twilio_request(request, body):
        raise HTTPException(status_code=403, detail="Invalid signature")

    form = await request.form()
    from_number = form.get("From", "")
    to_number = form.get("To", "")
    call_sid = form.get("CallSid", str(uuid4()))
    logger.info("Incoming call: %s -> %s (%s)", from_number, to_number, call_sid)

    manager = get_session_manager()
    await manager.create_session(
        property_code=lookup_property_code(from_number, to_number),
        guest_phone=from_number,
        session_id=call_sid,
    )

    response = VoiceResponse()
    ws_url = str(request.url).replace("http", "ws", 1).replace("/voice", "/voice/stream")
    ws_url = f"{ws_url}?session_id={call_sid}"

    connect = Connect()
    stream = Stream(url=ws_url)
    stream.parameter(name="session_id", value=call_sid)
    connect.append(stream)
    response.append(connect)
    response.say(
        "Thank you for calling Beach Habitats. We're connecting you to our concierge.",
        voice="Polly.Joanna",
    )

    return Response(content=str(response), media_type="application/xml")


@router.websocket("/voice/stream")
async def voice_stream(websocket: WebSocket):
    """Handle realtime Twilio media streaming for a voice session."""
    await websocket.accept()

    session_id = websocket.query_params.get("session_id")
    manager = get_session_manager()
    session = manager.get_session(session_id)
    if not session:
        logger.error("No session found for %s", session_id)
        await websocket.close()
        return

    audio_buffer = bytearray()
    stream_sid = None

    try:
        greeting_audio = await session.get_greeting()
        async for message in websocket.iter_json():
            event = message.get("event")

            if event == "connected":
                logger.info("Stream connected for %s", session_id)
                continue

            if event == "start":
                stream_sid = message.get("streamSid")
                logger.info("Stream started for %s: %s", session_id, stream_sid)
                if greeting_audio:
                    await websocket.send_json(
                        {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": base64.b64encode(greeting_audio).decode()},
                        }
                    )
                continue

            if event == "media":
                payload = message.get("media", {}).get("payload", "")
                if not payload:
                    continue
                audio_buffer.extend(base64.b64decode(payload))
                if len(audio_buffer) > 16000:
                    response_audio = await session.process_audio(bytes(audio_buffer))
                    audio_buffer.clear()
                    if response_audio and stream_sid:
                        await websocket.send_json(
                            {
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {"payload": base64.b64encode(response_audio).decode()},
                            }
                        )
                continue

            if event == "stop":
                logger.info("Stream stopped for %s", session_id)
                break
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for %s", session_id)
    except Exception as exc:
        logger.error("WebSocket error for %s: %s", session_id, exc)
    finally:
        await manager.end_session(session_id)


@router.post("/voice/status")
async def call_status_callback(request: Request):
    """Handle Twilio call status updates."""
    form = await request.form()
    call_sid = form.get("CallSid")
    call_status = form.get("CallStatus")
    duration = form.get("CallDuration")
    logger.info("Call %s status: %s (%ss)", call_sid, call_status, duration)

    if call_status in {"completed", "busy", "failed", "no-answer", "canceled"}:
        await get_session_manager().end_session(call_sid)

    return Response(status_code=200)


@router.post("/sms")
async def handle_incoming_sms(request: Request):
    """Handle inbound SMS and return a TwiML response."""
    from twilio.twiml.messaging_response import MessagingResponse

    body = await request.body()
    if not validate_twilio_request(request, body):
        raise HTTPException(status_code=403, detail="Invalid signature")

    form = await request.form()
    from_number = form.get("From", "")
    to_number = form.get("To", "")
    message_body = form.get("Body", "")
    logger.info("Incoming SMS from %s: %s", from_number, message_body[:80])

    session_id = f"sms_{from_number}"
    manager = get_session_manager()
    session = manager.get_session(session_id)
    if not session:
        session = await manager.create_session(
            property_code=lookup_property_code(from_number, to_number),
            guest_phone=from_number,
            session_id=session_id,
        )

    response_text = await session.process_text(message_body)
    twiml = MessagingResponse()
    twiml.message(response_text)
    return Response(content=str(twiml), media_type="application/xml")


async def send_sms(to_number: str, message: str, from_number: Optional[str] = None) -> bool:
    """Send an outbound SMS message."""
    try:
        client = get_twilio_client()
        msg = client.messages.create(
            to=to_number,
            from_=from_number or TWILIO_PHONE_NUMBER,
            body=message,
        )
        logger.info("SMS sent to %s: %s", to_number, msg.sid)
        return True
    except Exception as exc:
        logger.error("Failed to send SMS to %s: %s", to_number, exc)
        return False


async def send_proactive_message(
    guest_phone: str,
    property_code: str,
    message_type: str,
) -> bool:
    """Send a templated message based on the guest journey stage."""
    from app.services.voice.voice_session import VoiceSession

    session = VoiceSession(property_code=property_code)
    await session._load_context()

    context = session.guest_context or {}
    property_name = context.get("property_name", "your vacation rental")
    templates = {
        "pre_arrival": (
            f"Hi! We're excited for your upcoming stay at {property_name}. "
            "Check-in is at 4pm. Reply with any questions!"
        ),
        "day_of": (
            f"Welcome! {property_name} is ready for you. Check-in at 4pm. "
            "WiFi and entry details are in your confirmation. Have a great stay!"
        ),
        "mid_stay": (
            f"Hope you're enjoying {property_name}! Need restaurant recommendations "
            "or help? Just reply here."
        ),
        "departure": f"We hope you loved {property_name}. Check-out is at 10am. Safe travels!",
        "post_stay": (
            f"Thank you for staying at {property_name}! How was your experience? Reply 1-5."
        ),
    }
    return await send_sms(guest_phone, templates.get(message_type, templates["mid_stay"]))


@router.get("/sessions")
async def list_active_sessions():
    """List active voice and SMS sessions."""
    manager = get_session_manager()
    return {"sessions": [session.to_dict() for session in manager.sessions.values()]}


@router.post("/test-sms")
async def test_sms(to: str, message: str):
    """Send a test SMS message."""
    return {"success": await send_sms(to, message)}
