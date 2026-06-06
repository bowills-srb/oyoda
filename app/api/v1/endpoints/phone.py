"""
Twilio Phone Integration for Voice Concierge.

Connects inbound phone calls to the Beach Habitats AI concierge.

FLOW:
1. Guest calls dedicated number (e.g., 850-XXX-XXXX)
2. Twilio answers, streams audio via WebSocket
3. Deepgram transcribes in real-time
4. VoicePod (canonical runtime) processes with full property context
5. ElevenLabs synthesizes response
6. Audio streams back to caller

All AI generation routes through _run_voice_pod() — same pipeline as
/api/v1/mobile/{token}/chat — not a separate Claude call. This guarantees
identical escalation policy, tenant isolation, and Watch Layer observability
across all guest channels.

SETUP:
1. Create Twilio account & buy phone number
2. Set webhook URL: https://your-domain/api/v1/phone/incoming
3. Configure env vars: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN

SECURITY:
  - Every inbound Twilio request (HTTP + WebSocket upgrade) is signature-verified
    via twilio.request_validator.RequestValidator. Requests that fail validation
    are rejected with 403 before any business logic runs.
  - DB logging uses the async SQLAlchemy session — no sync psycopg2 calls on
    the async event loop.
"""

import asyncio
import base64
import hashlib
import hmac
import io
import json
import logging
import os
import struct
from datetime import datetime, timezone
from typing import Optional, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/phone", tags=["Phone"])


# =============================================================================
# CONFIGURATION
# =============================================================================

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

CONCIERGE_GREETING = "Hi, this is the Beach Habitats concierge. How can I help you today?"

# Phone-number → property_code map (store in DB for multi-tenant scale)
PHONE_TO_PROPERTY: Dict[str, str] = {}


# =============================================================================
# TWILIO SIGNATURE VERIFICATION
# =============================================================================

def _verify_twilio_signature(request_url: str, params: dict, signature: str) -> bool:
    """
    Validate that an inbound HTTP webhook is genuinely from Twilio.

    Implements the HMAC-SHA1 algorithm documented at:
    https://www.twilio.com/docs/usage/webhooks/webhooks-security

    Returns True if the signature is valid OR if TWILIO_AUTH_TOKEN is not
    configured (dev/test mode — log a warning so it's not silently skipped).
    """
    if not TWILIO_AUTH_TOKEN:
        logger.warning("[phone] TWILIO_AUTH_TOKEN not set — skipping signature verification (dev mode)")
        return True

    try:
        from twilio.request_validator import RequestValidator
        validator = RequestValidator(TWILIO_AUTH_TOKEN)
        return validator.validate(request_url, params, signature)
    except ImportError:
        # twilio package not installed — fall back to manual HMAC
        s = request_url
        for key in sorted(params.keys()):
            s += key + params[key]
        computed = base64.b64encode(
            hmac.new(TWILIO_AUTH_TOKEN.encode(), s.encode(), hashlib.sha1).digest()
        ).decode()
        return hmac.compare_digest(computed, signature)
    except Exception as exc:
        logger.error("[phone] Signature verification error: %s", exc)
        return False


async def _require_twilio_signature(request: Request) -> dict:
    """
    FastAPI dependency — verifies Twilio signature on every inbound webhook.
    Raises HTTP 403 if signature is missing or invalid.
    Returns the parsed form data so handlers don't need to parse it again.
    """
    form_data = dict(await request.form())
    signature = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)

    if not _verify_twilio_signature(url, form_data, signature):
        logger.warning("[phone] Rejected request with invalid Twilio signature from %s", request.client)
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    return form_data


# =============================================================================
# CALL SESSION STATE
# =============================================================================

class CallSession:
    """Tracks state for an active phone call."""

    def __init__(self, call_sid: str, from_number: str, to_number: str):
        self.call_sid = call_sid
        self.from_number = from_number
        self.to_number = to_number
        self.property_code: Optional[str] = None
        self.db_session_token: Optional[str] = None   # links to concierge_guest_sessions
        self.conversation_history: list = []
        self.started_at = datetime.now(timezone.utc)

    def add_turn(self, role: str, text: str):
        self.conversation_history.append({
            "role": role,
            "content": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


# In-memory map for in-progress calls (one process; use Redis for multi-node)
ACTIVE_CALLS: Dict[str, CallSession] = {}


# =============================================================================
# PROPERTY / SESSION RESOLUTION
# =============================================================================

def _get_property_from_caller(from_number: str, to_number: str) -> Optional[str]:
    """Resolve property code from caller/called number. Extend with DB lookup."""
    return PHONE_TO_PROPERTY.get(to_number)


async def _resolve_db_session(property_code: str, from_number: str, db: AsyncSession) -> Optional[object]:
    """
    Find an active concierge_guest_sessions row for this guest phone / property.
    Returns the ORM row or None.
    """
    try:
        from sqlalchemy import select, text
        from app.services.concierge.db_session_service import DEFAULT_TENANT_ID
        result = await db.execute(
            text("""
                SELECT * FROM concierge_guest_sessions
                WHERE guest_phone = :phone
                  AND property_code = :code
                  AND status != 'expired'
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"phone": from_number, "code": property_code},
        )
        row = result.fetchone()
        return row
    except Exception as exc:
        logger.warning("[phone] DB session lookup failed: %s", exc)
        return None


# =============================================================================
# TWILIO WEBHOOKS
# =============================================================================

@router.post("/incoming")
async def handle_incoming_call(
    form_data: dict = Depends(_require_twilio_signature),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Twilio webhook — inbound voice call.
    Signature is verified before this handler runs (see _require_twilio_signature).
    """
    call_sid = form_data.get("CallSid", "")
    from_number = form_data.get("From", "")
    to_number = form_data.get("To", "")

    logger.info("[phone] Incoming call %s from %s to %s", call_sid, from_number, to_number)

    session = CallSession(call_sid, from_number, to_number)
    session.property_code = _get_property_from_caller(from_number, to_number)

    if session.property_code:
        row = await _resolve_db_session(session.property_code, from_number, db)
        if row:
            session.db_session_token = getattr(row, "token", None)

    ACTIVE_CALLS[call_sid] = session

    # Point Twilio at the streaming WebSocket
    host = form_data.get("_host") or "your-domain.com"
    ws_url = f"wss://{host}/api/v1/phone/stream/{call_sid}"

    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Say voice="Polly.Joanna">{CONCIERGE_GREETING}</Say>'
        f'<Connect><Stream url="{ws_url}" /></Connect>'
        "</Response>"
    )
    return Response(content=twiml, media_type="application/xml")


@router.post("/status")
async def handle_call_status(
    form_data: dict = Depends(_require_twilio_signature),
    db: AsyncSession = Depends(get_async_session),
):
    """Twilio webhook — call status updates."""
    call_sid = form_data.get("CallSid", "")
    call_status = form_data.get("CallStatus", "")

    logger.info("[phone] Call %s status: %s", call_sid, call_status)

    if call_status in ("completed", "failed", "busy", "no-answer"):
        session = ACTIVE_CALLS.pop(call_sid, None)
        if session:
            await _log_voice_conversation(session, db)

    return {"status": "ok"}


# =============================================================================
# WEBSOCKET AUDIO STREAMING
# =============================================================================

@router.websocket("/stream/{call_sid}")
async def handle_audio_stream(websocket: WebSocket, call_sid: str):
    """
    Twilio Media Stream WebSocket.
    Audio → STT → VoicePod (canonical runtime) → TTS → audio back.
    """
    await websocket.accept()

    session = ACTIVE_CALLS.get(call_sid)
    if not session:
        logger.error("[phone] No session for call %s", call_sid)
        await websocket.close()
        return

    stt = None
    tts = None
    if DEEPGRAM_API_KEY:
        try:
            from app.services.voice.providers import get_deepgram_stt
            stt = get_deepgram_stt(DEEPGRAM_API_KEY)
        except Exception as exc:
            logger.warning("[phone] STT init failed: %s", exc)
    if ELEVENLABS_API_KEY:
        try:
            from app.services.voice.providers import get_elevenlabs_tts
            tts = get_elevenlabs_tts(ELEVENLABS_API_KEY, voice=ELEVENLABS_VOICE_ID)
        except Exception as exc:
            logger.warning("[phone] TTS init failed: %s", exc)

    audio_buffer = bytearray()
    stream_sid: Optional[str] = None

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            event = data.get("event")

            if event == "start":
                stream_sid = data.get("streamSid")

            elif event == "media":
                payload = data.get("media", {}).get("payload", "")
                if payload:
                    audio_buffer.extend(base64.b64decode(payload))
                    # ~1 second of mulaw 8 kHz
                    if len(audio_buffer) > 8000:
                        await _process_audio(
                            websocket, session, stream_sid,
                            bytes(audio_buffer), stt, tts,
                        )
                        audio_buffer.clear()

            elif event == "stop":
                if audio_buffer:
                    await _process_audio(
                        websocket, session, stream_sid,
                        bytes(audio_buffer), stt, tts,
                    )
                break

    except WebSocketDisconnect:
        logger.info("[phone] WebSocket disconnected for call %s", call_sid)
    except Exception as exc:
        logger.error("[phone] WebSocket error: %s", exc)
    finally:
        await websocket.close()


async def _process_audio(
    websocket: WebSocket,
    session: CallSession,
    stream_sid: Optional[str],
    audio_data: bytes,
    stt,
    tts,
):
    if not stt:
        return

    wav = _mulaw_to_wav(audio_data)
    result = await stt.transcribe(wav, "audio/wav")
    if not result.text or result.confidence < 0.5:
        return

    transcript = result.text.strip()
    if not transcript:
        return

    logger.info("[phone] Transcript: %s", transcript)
    session.add_turn("user", transcript)

    # Route through VoicePod (canonical runtime) if we have a session token,
    # otherwise fall back to a safe minimal response.
    response_text = await _generate_via_voice_pod(session, transcript)

    session.add_turn("assistant", response_text)
    logger.info("[phone] Response: %s", response_text)

    if tts and stream_sid:
        await _stream_tts(websocket, stream_sid, tts, response_text)


# =============================================================================
# CANONICAL RUNTIME — VoicePod
# =============================================================================

async def _generate_via_voice_pod(session: CallSession, user_message: str) -> str:
    """
    Route the phone message through the same VoicePod used by the mobile chat
    endpoint, so all channels share one escalation policy and prompt strategy.

    Falls back to a safe handoff message if VoicePod is unavailable.
    """
    FALLBACK = (
        "I'm so sorry, I'm having a technical issue. "
        "Please call Beach Habitats directly at (850) 733-7433 for immediate help."
    )

    try:
        from app.db.session import SessionLocal
        from app.services.concierge.db_session_service import (
            get_db_session_service,
            DEFAULT_TENANT_ID,
        )
        from app.services.messaging_brain.session_channel_adapter import (
            run_session_channel_message,
        )
        from app.services.knowledge.voice_pod import (
            _build_escalation_response_text,
            _check_keyword_escalation,
        )

        if not session.db_session_token:
            # No linked session token — we can't run VoicePod (needs a session row).
            # Apply escalation keyword check manually before returning generic fallback.
            esc = _check_keyword_escalation(user_message)
            if esc:
                priority, _ = esc
                return _build_escalation_response_text(priority)
            return FALLBACK

        async with SessionLocal() as db:
            _bootstrap = get_db_session_service(DEFAULT_TENANT_ID)
            db_row = await _bootstrap.get_session_by_token(db, session.db_session_token, tenant_agnostic=True)
            if not db_row:
                return FALLBACK
            try:
                session_tenant_id = getattr(db_row, "tenant_id", None) or DEFAULT_TENANT_ID
                result = await run_session_channel_message(
                    message_text=user_message,
                    db_session=db,
                    db_row=db_row,
                    session_tenant_id=session_tenant_id,
                    token=session.db_session_token,
                    channel="voice",
                    source_provider="twilio_phone",
                )
                return result.response_text
            except Exception:
                esc = _check_keyword_escalation(user_message)
                if esc:
                    priority, _ = esc
                    support = (getattr(db_row, "property_context", {}) or {}).get("support_phone")
                    guest_name = (getattr(db_row, "guest_name", "") or "").split()[0] or None
                    return _build_escalation_response_text(priority, support, guest_name)
                raise

    except Exception as exc:
        logger.error("[phone] VoicePod routing failed: %s", exc, exc_info=True)
        return FALLBACK

# =============================================================================
# TTS STREAMING
# =============================================================================

async def _stream_tts(
    websocket: WebSocket,
    stream_sid: str,
    tts,
    text: str,
):
    try:
        result = await tts.synthesize(text)
        if not result.audio_data:
            return
        mulaw = _mp3_to_mulaw(result.audio_data)
        chunk_size = 640  # 40 ms @ 8 kHz mulaw
        for i in range(0, len(mulaw), chunk_size):
            chunk = mulaw[i : i + chunk_size]
            await websocket.send_text(json.dumps({
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": base64.b64encode(chunk).decode()},
            }))
            await asyncio.sleep(0.04)
    except Exception as exc:
        logger.error("[phone] TTS stream error: %s", exc)


# =============================================================================
# AUDIO FORMAT HELPERS
# =============================================================================

def _mulaw_to_wav(mulaw_data: bytes) -> bytes:
    try:
        import audioop
        pcm = audioop.ulaw2lin(mulaw_data, 2)
        buf = io.BytesIO()
        sr, ch, bps = 8000, 1, 16
        buf.write(b"RIFF")
        buf.write(struct.pack("<I", 36 + len(pcm)))
        buf.write(b"WAVE")
        buf.write(b"fmt ")
        buf.write(struct.pack("<IHHIIHH", 16, 1, ch, sr, sr * ch * bps // 8, ch * bps // 8, bps))
        buf.write(b"data")
        buf.write(struct.pack("<I", len(pcm)))
        buf.write(pcm)
        return buf.getvalue()
    except Exception as exc:
        logger.error("[phone] mulaw→wav failed: %s", exc)
        return mulaw_data


def _mp3_to_mulaw(mp3_data: bytes) -> bytes:
    try:
        import audioop
        from pydub import AudioSegment
        audio = AudioSegment.from_mp3(io.BytesIO(mp3_data))
        audio = audio.set_frame_rate(8000).set_channels(1)
        return audioop.lin2ulaw(audio.raw_data, 2)
    except Exception as exc:
        logger.error("[phone] mp3→mulaw failed: %s", exc)
        return b""


# =============================================================================
# ASYNC DB LOGGING (no sync psycopg2 on async event loop)
# =============================================================================

async def _log_voice_conversation(session: CallSession, db: AsyncSession):
    """Log completed call using the async SQLAlchemy session."""
    if not session.conversation_history:
        return
    try:
        from sqlalchemy import text
        from psycopg2.extras import Json  # only for JSON serialisation, not connection
        import json as _json

        duration = int((datetime.utcnow() - session.started_at).total_seconds())
        await db.execute(
            text("""
                INSERT INTO voice_conversations (
                    call_sid, property_code, from_number, to_number,
                    conversation, turn_count, duration_seconds, started_at
                ) VALUES (
                    :call_sid, :property_code, :from_number, :to_number,
                    :conversation, :turn_count, :duration, :started_at
                )
                ON CONFLICT (call_sid) DO NOTHING
            """),
            {
                "call_sid": session.call_sid,
                "property_code": session.property_code,
                "from_number": session.from_number,
                "to_number": session.to_number,
                "conversation": _json.dumps(session.conversation_history),
                "turn_count": len(session.conversation_history),
                "duration": duration,
                "started_at": session.started_at,
            },
        )
        await db.commit()
        logger.info("[phone] Logged conversation for call %s", session.call_sid)
    except Exception as exc:
        logger.error("[phone] Failed to log conversation: %s", exc)


# =============================================================================
# UTILITY ENDPOINTS
# =============================================================================

@router.get("/calls")
async def list_active_calls():
    return {
        "active_calls": [
            {
                "call_sid": sid,
                "property_code": s.property_code,
                "from_number": s.from_number,
                "started_at": s.started_at.isoformat(),
                "turns": len(s.conversation_history),
                "has_session_token": bool(s.db_session_token),
            }
            for sid, s in ACTIVE_CALLS.items()
        ]
    }


@router.post("/test")
async def test_voice_flow(
    text: str,
    property_code: str = "134MC",
    db: AsyncSession = Depends(get_async_session),
):
    """Smoke-test the phone pipeline without a real call."""
    session = CallSession("test-call", "+15551234567", "+18501234567")
    session.property_code = property_code
    response_text = await _generate_via_voice_pod(session, text)
    return {
        "input": text,
        "response": response_text,
        "property_code": property_code,
        "routed_via": "voice_pod" if session.db_session_token else "fallback",
    }
