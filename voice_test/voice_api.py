"""
Voice Concierge API - Speed Optimized

Target: <1.5s total latency
"""

import base64
import logging
import os
import httpx
import traceback
from typing import Optional
from uuid import uuid4
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

app = FastAPI(title="Beach Habitats Voice Concierge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Reusable HTTP client for connection pooling
http_client = None

def get_http_client():
    global http_client
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=30.0)
    return http_client


class VoiceRequest(BaseModel):
    audio_data: str
    property_code: str
    mime_type: str = "audio/webm"


class VoiceResponse(BaseModel):
    transcript: str
    response_text: str
    audio_data: Optional[str] = None
    session_id: str


def get_guest_context(property_code: str) -> str:
    """Get property context from database + community knowledge."""
    
    # Try to get from database
    try:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from services.guest_concierge_service import GuestConciergeService
        
        service = GuestConciergeService()
        context = service.get_guest_context(property_code)
        
        if context.property_name and context.property_name != property_code:
            # We have real data
            return service.format_context_for_llm(context, include_local=True)
    except Exception as e:
        logger.warning(f"Could not load from database: {e}")
    
    # Fallback to hardcoded for testing
    return f"""Property: {property_code} | Community: WaterColor

WiFi: BH_{property_code} / Beach2024!
Check-in: 4PM | Check-out: 10AM

Amenities from our records: heated pool, bikes, beach wagon, grill

Note: For specific policies about beach chairs, pool heating costs, wristband access, etc. - use your knowledge about the community (WaterColor, Rosemary Beach, etc.) to give accurate answers."""


def build_system_prompt(property_code: str) -> str:
    context = get_guest_context(property_code)
    return f"""You're a helpful local for a beach rental on 30A, Florida. Be warm but BRIEF.

RULES:
- MAX 2 sentences
- No fluff, get to the point
- Sound natural, use contractions
- Use your 30A knowledge (WaterColor, Rosemary, Seaside, etc.)

Good examples:
- "Beach chairs?" → "Nope, not included - you'll need to rent those separately at the beach club, around 60-80 bucks a day."
- "WiFi?" → "BH_134MC, password Beach2024."
- "Dinner spots?" → "Bud & Alley's rooftop for sunset - trust me."
- "Pool heated?" → "It can be! Costs about 50 a day, just let us know ahead of time."

Bad (too long):
- "Great question! So the wristbands provide access to the beach club amenities including the pools and facilities, however beach chairs are actually a separate service that needs to be rented..."

{context}"""


async def transcribe_audio_fast(audio_bytes: bytes, mime_type: str) -> str:
    """Transcribe using Deepgram - optimized."""
    if not DEEPGRAM_API_KEY:
        raise HTTPException(status_code=500, detail="DEEPGRAM_API_KEY not set")
    
    logger.info(f"Audio size: {len(audio_bytes)} bytes, type: {mime_type}")
    
    url = "https://api.deepgram.com/v1/listen"
    params = {
        "model": "nova-2",
        "language": "en",
    }
    
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": mime_type,
    }
    
    client = get_http_client()
    response = await client.post(url, params=params, headers=headers, content=audio_bytes)
    
    if response.status_code != 200:
        logger.error(f"Deepgram error: {response.status_code} - {response.text}")
        raise HTTPException(status_code=500, detail=f"Deepgram error: {response.text}")
    
    data = response.json()
    transcript = data["results"]["channels"][0]["alternatives"][0]["transcript"]
    return transcript


async def generate_response_fast(transcript: str, property_code: str) -> str:
    """Generate response using Groq (fastest) -> Gemini -> Anthropic fallback."""
    
    groq_key = os.getenv("GROQ_API_KEY", "")
    gemini_key = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
    
    # Try Groq first (fastest ~200-400ms)
    if groq_key:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {groq_key}",
            "Content-Type": "application/json",
        }
        data = {
            "model": "llama-3.3-70b-versatile",
            "max_tokens": 80,
            "temperature": 0.7,
            "messages": [
                {"role": "system", "content": build_system_prompt(property_code)},
                {"role": "user", "content": transcript}
            ]
        }
        client = get_http_client()
        response = await client.post(url, headers=headers, json=data)
        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        else:
            logger.warning(f"Groq error: {response.status_code} - {response.text}")
    
    # Try Gemini second (good knowledge)
    if gemini_key:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}"
        headers = {"Content-Type": "application/json"}
        data = {
            "contents": [{
                "parts": [{"text": f"{build_system_prompt(property_code)}\n\nGuest asks: {transcript}"}]
            }],
            "generationConfig": {
                "maxOutputTokens": 100,
                "temperature": 0.7
            }
        }
        client = get_http_client()
        response = await client.post(url, headers=headers, json=data)
        if response.status_code == 200:
            result = response.json()
            try:
                return result["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError) as e:
                logger.warning(f"Gemini parse error: {e}")
        else:
            logger.warning(f"Gemini error: {response.status_code} - {response.text}")
    
    # Fallback to Anthropic
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="No LLM API key set")
    
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    data = {
        "model": "claude-3-5-haiku-20241022",
        "max_tokens": 80,
        "system": build_system_prompt(property_code),
        "messages": [{"role": "user", "content": transcript}]
    }
    
    client = get_http_client()
    response = await client.post(url, headers=headers, json=data)
    
    if response.status_code != 200:
        logger.error(f"Anthropic error: {response.status_code} - {response.text}")
        raise HTTPException(status_code=500, detail=f"Anthropic error: {response.text}")
    
    result = response.json()
    return result["content"][0]["text"]


async def synthesize_speech_fast(text: str) -> bytes:
    """Synthesize speech using ElevenLabs - optimized."""
    if not ELEVENLABS_API_KEY:
        raise HTTPException(status_code=500, detail="ELEVENLABS_API_KEY not set")
    
    # Smooth female voices to try:
    # "Charlotte" XB0fDUnXU5powFXDhCwa - warm, smooth
    # "Matilda" XrExE9yKIg1WjnnlVkGX - warm, friendly
    voice_id = "XrExE9yKIg1WjnnlVkGX"  # Matilda - warm & friendly
    
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY,
    }
    
    data = {
        "text": text,
        "model_id": "eleven_turbo_v2_5",  # Newer model, more natural
        "voice_settings": {
            "stability": 0.5,        # Balance natural variation
            "similarity_boost": 0.75,
            "style": 0.0,            # Neutral delivery
            "use_speaker_boost": True
        }
    }
    
    params = {
        "optimize_streaming_latency": "4",  # Max speed
        "output_format": "mp3_22050_32",    # Smaller = faster
    }
    
    client = get_http_client()
    response = await client.post(url, params=params, headers=headers, json=data)
    
    if response.status_code != 200:
        logger.error(f"ElevenLabs error: {response.status_code} - {response.text}")
        raise HTTPException(status_code=500, detail=f"ElevenLabs error: {response.text}")
    
    return response.content


@app.get("/")
async def root():
    return {
        "status": "ok",
        "version": "fast",
        "deepgram": "OK" if DEEPGRAM_API_KEY else "MISSING",
        "elevenlabs": "OK" if ELEVENLABS_API_KEY else "MISSING",
        "anthropic": "OK" if ANTHROPIC_API_KEY else "MISSING",
    }


@app.post("/api/v1/voice/process", response_model=VoiceResponse)
async def process_voice(request: VoiceRequest):
    """Process voice - speed optimized."""
    start_time = time.time()
    session_id = str(uuid4())
    
    try:
        audio_bytes = base64.b64decode(request.audio_data)
        decode_time = time.time()
        
        # Step 1: Transcribe
        transcript = await transcribe_audio_fast(audio_bytes, request.mime_type)
        t1 = time.time()
        stt_ms = (t1 - decode_time) * 1000
        
        if not transcript.strip():
            return VoiceResponse(
                transcript="",
                response_text="I didn't catch that. Could you try again?",
                session_id=session_id
            )
        
        # Step 2: Generate response
        response_text = await generate_response_fast(transcript, request.property_code)
        t2 = time.time()
        llm_ms = (t2 - t1) * 1000
        
        # Step 3: Synthesize speech
        audio_response = await synthesize_speech_fast(response_text)
        t3 = time.time()
        tts_ms = (t3 - t2) * 1000
        
        total_ms = (t3 - start_time) * 1000
        
        logger.info(f"[{transcript[:30]}] STT:{stt_ms:.0f}ms LLM:{llm_ms:.0f}ms TTS:{tts_ms:.0f}ms = {total_ms:.0f}ms")
        
        return VoiceResponse(
            transcript=transcript,
            response_text=response_text,
            audio_data=base64.b64encode(audio_response).decode(),
            session_id=session_id
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.on_event("shutdown")
async def shutdown():
    global http_client
    if http_client:
        await http_client.aclose()


if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*50)
    print("Beach Habitats Voice Concierge (FAST)")
    print("="*50)
    print(f"Deepgram:   {'OK' if DEEPGRAM_API_KEY else 'MISSING'}")
    print(f"ElevenLabs: {'OK' if ELEVENLABS_API_KEY else 'MISSING'}")
    print(f"Anthropic:  {'OK' if ANTHROPIC_API_KEY else 'MISSING'}")
    print("="*50 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
