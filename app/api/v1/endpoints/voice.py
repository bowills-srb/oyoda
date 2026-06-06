"""
API Endpoint: Voice Concierge.

Safe voice flow: STT → Decision → TTS

This endpoint does NOT contain intelligence.
It only handles audio I/O and delegates to ConciergeRunner.
"""

import base64
import time
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.orchestration import (
    ConciergeRunner,
    ConciergeRequest,
    get_concierge_runner,
)
from app.services.observability.slo_metrics import observe_voice_turn


router = APIRouter(prefix="/voice", tags=["Voice"])


# =============================================================================
# REQUEST/RESPONSE SCHEMAS
# =============================================================================

class VoiceConciergeRequest(BaseModel):
    """Request for voice concierge interaction."""
    property_id: UUID
    
    # Audio input (base64 encoded)
    audio_base64: Optional[str] = Field(None, description="Base64 encoded audio (WAV/MP3)")
    audio_mime_type: str = Field("audio/wav", description="MIME type of audio")
    
    # Or text input
    text_input: Optional[str] = Field(None, description="Text input (if not using audio)")
    
    # Guest context
    guest_id: Optional[UUID] = None
    reservation_id: Optional[str] = None
    stage: str = Field("booked", pattern="^(pre_booking|booked|in_stay|post_stay)$")
    
    # Voice response preference
    return_audio: bool = Field(True, description="Return TTS audio response")


class VoiceConciergeResponse(BaseModel):
    """Response from voice concierge."""
    # Text response (always present)
    response_text: str
    intent: Optional[str] = None
    
    # Audio response (if requested and available)
    audio_base64: Optional[str] = None
    audio_mime_type: Optional[str] = None
    
    # Decision details
    approved: Optional[bool] = None
    requires_escalation: bool = False
    
    # Suggestions
    suggestions: list = []


# =============================================================================
# ENDPOINT
# =============================================================================

@router.post("/concierge", response_model=VoiceConciergeResponse)
async def voice_concierge(request: VoiceConciergeRequest):
    """
    [NON-PROD] Legacy voice concierge backed by ConciergeRunner.

    This endpoint uses the old orchestration layer and a separate decision
    pipeline that is NOT shared with /api/v1/mobile/{token}/chat.  Guest
    messages routed here would bypass the VoicePod escalation gate, tenant
    isolation, and Watch Layer observability.

    TODO: Retire ConciergeRunner and rewrite this endpoint to call
    _run_voice_pod() from mobile_v2 once it has a real session token.
    Until then the endpoint returns 503 in production so no guest traffic
    can accidentally reach it.
    """
    start = time.perf_counter()
    import os
    if os.getenv("ENVIRONMENT", "development").lower() in ("production", "prod", "staging"):
        raise HTTPException(
            status_code=503,
            detail=(
                "[voice/concierge] This endpoint is disabled in production. "
                "Guest traffic must route through /api/v1/mobile/{token}/chat."
            ),
        )
    runner = get_concierge_runner()
    
    # Determine input text
    input_text = request.text_input
    
    if request.audio_base64 and not input_text:
        # Transcribe audio
        try:
            from app.services.voice.providers import get_deepgram_stt
            import os
            
            api_key = os.getenv("DEEPGRAM_API_KEY")
            if not api_key:
                raise HTTPException(
                    status_code=400,
                    detail="Deepgram API key not configured. Use text_input instead."
                )
            
            stt = get_deepgram_stt(api_key)
            audio_bytes = base64.b64decode(request.audio_base64)
            result = await stt.transcribe(audio_bytes, request.audio_mime_type)
            input_text = result.text
            
            if not input_text:
                return VoiceConciergeResponse(
                    response_text="I didn't catch that. Could you please repeat?",
                )
                
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="Deepgram SDK not installed."
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Transcription failed: {str(e)}"
            )
    
    if not input_text:
        raise HTTPException(
            status_code=400,
            detail="Either audio_base64 or text_input must be provided"
        )
    
    # Load real property profile from DB / MCP
    property_profile = await _load_property_profile(
        property_id=str(request.property_id),
        reservation_id=request.reservation_id,
    )
    
    # Handle with concierge
    concierge_request = ConciergeRequest(
        property_id=request.property_id,
        guest_id=request.guest_id,
        reservation_id=request.reservation_id,
        message_text=input_text,
        stage=request.stage,
    )
    
    reply = await runner.handle_message(concierge_request, property_profile)
    
    # Generate audio response if requested
    audio_response = None
    audio_mime = None
    
    if request.return_audio and reply.text:
        try:
            from app.services.voice.providers import get_elevenlabs_tts
            import os
            
            api_key = os.getenv("ELEVENLABS_API_KEY")
            voice_id = os.getenv("ELEVENLABS_VOICE_ID", "rachel")
            
            if api_key:
                tts = get_elevenlabs_tts(api_key, voice=voice_id)
                result = await tts.synthesize(reply.text)
                
                if result.audio_data:
                    audio_response = base64.b64encode(result.audio_data).decode()
                    audio_mime = "audio/mpeg"
                    
        except ImportError:
            pass  # ElevenLabs not available, skip audio
        except Exception as e:
            pass  # TTS failed, return text only
    
    response = VoiceConciergeResponse(
        response_text=reply.text,
        intent=reply.intent,
        audio_base64=audio_response,
        audio_mime_type=audio_mime,
        approved=reply.approved,
        requires_escalation=reply.requires_escalation,
        suggestions=[s.title for s in reply.suggestions] if reply.suggestions else [],
    )
    observe_voice_turn(
        total_time_ms=(time.perf_counter() - start) * 1000.0,
        escalated=bool(reply.requires_escalation),
        success=True,
    )
    return response


# =============================================================================
# Property Profile Loader
# =============================================================================

async def _load_property_profile(
    property_id: str,
    reservation_id: Optional[str] = None,
) -> dict:
    """
    Load real property facts from the MCP / DB layer.

    Falls back to safe empty defaults if the property is not found so the
    endpoint never surfaces hardcoded credentials.
    """
    try:
        from app.mcp.registry import get_mcp_registry
        registry = get_mcp_registry()

        # Try to derive property_code from the property_id
        property_code: Optional[str] = None
        try:
            from app.core.database import get_db_session
            from sqlalchemy import select, text
            async with get_db_session() as db:
                row = (await db.execute(
                    text("SELECT property_code FROM properties WHERE id = :pid LIMIT 1"),
                    {"pid": property_id},
                )).fetchone()
                if row:
                    property_code = row[0]
        except Exception:
            pass

        if not property_code:
            return _empty_property_profile()

        result = await registry.call(
            server_name="concierge",
            tool_name="get_property_basics",
            operator_id="op_beach_habitats",
            params={"property_code": property_code},
        )

        if result.success and result.data:
            d = result.data
            return {
                "operational_constraints": {
                    "check_in_time": d.get("check_in_time", "4:00 PM"),
                    "check_out_time": d.get("check_out_time", "10:00 AM"),
                    "late_checkout_available": True,
                    "max_occupancy": d.get("max_occupancy"),
                    "pets_allowed": d.get("pets_allowed", False),
                    "quiet_hours_start": d.get("quiet_hours_start"),
                    "quiet_hours_end": d.get("quiet_hours_end"),
                },
                "access": {
                    "wifi_network": d.get("wifi_network"),
                    "wifi_password": d.get("wifi_password"),
                    "lock_type": d.get("lock_type"),
                    "check_in_instructions": d.get("check_in_instructions"),
                },
                "amenities": {
                    "has_pool": d.get("has_pool", False),
                    "pool_heated": d.get("pool_heated", False),
                    "has_hot_tub": d.get("has_hot_tub", False),
                    "has_grill": d.get("has_grill", False),
                    "has_bikes": d.get("has_bikes", False),
                    "bike_count": d.get("bike_count", 0),
                    "has_beach_gear": d.get("has_beach_gear", False),
                },
            }
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"[voice] Property profile load failed: {exc}")

    return _empty_property_profile()


def _empty_property_profile() -> dict:
    """Safe empty profile — no credentials, no hardcoded defaults."""
    return {
        "operational_constraints": {
            "check_in_time": "4:00 PM",
            "check_out_time": "10:00 AM",
            "late_checkout_available": False,
        },
        "access": {},
        "amenities": {},
    }


@router.post("/transcribe")
async def transcribe_audio(audio_base64: str, mime_type: str = "audio/wav"):
    """
    Transcribe audio to text (STT only).
    
    Useful for testing or custom flows.
    """
    try:
        from app.services.voice.providers import get_deepgram_stt
        import os
        
        api_key = os.getenv("DEEPGRAM_API_KEY")
        if not api_key:
            raise HTTPException(status_code=400, detail="Deepgram API key not configured")
        
        stt = get_deepgram_stt(api_key)
        audio_bytes = base64.b64decode(audio_base64)
        result = await stt.transcribe(audio_bytes, mime_type)
        
        return {
            "text": result.text,
            "confidence": result.confidence,
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/synthesize")
async def synthesize_speech(text: str, voice: str = "rachel"):
    """
    Synthesize text to speech (TTS only).
    
    Useful for testing or custom flows.
    """
    try:
        from app.services.voice.providers import get_elevenlabs_tts
        import os
        
        api_key = os.getenv("ELEVENLABS_API_KEY")
        if not api_key:
            raise HTTPException(status_code=400, detail="ElevenLabs API key not configured")
        
        tts = get_elevenlabs_tts(api_key, voice=voice)
        result = await tts.synthesize(text)
        
        return {
            "audio_base64": base64.b64encode(result.audio_data).decode() if result.audio_data else None,
            "mime_type": "audio/mpeg",
            "character_count": result.character_count,
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
