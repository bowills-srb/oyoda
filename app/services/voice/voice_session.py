"""
Voice session management for realtime concierge calls and SMS threads.
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from app.services.observability.llm_usage_tracker import LLMCallTimer, LLMUsageTracker

logger = logging.getLogger(__name__)


class SessionState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    ENDED = "ended"


@dataclass
class ConversationTurn:
    turn_id: str
    timestamp: datetime
    speaker: str
    text: str
    audio_duration_ms: int = 0
    intent: Optional[str] = None
    confidence: float = 1.0
    response_time_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "timestamp": self.timestamp.isoformat(),
            "speaker": self.speaker,
            "text": self.text,
            "audio_duration_ms": self.audio_duration_ms,
            "intent": self.intent,
            "confidence": self.confidence,
            "response_time_ms": self.response_time_ms,
        }


@dataclass
class VoiceSessionConfig:
    deepgram_api_key: str = field(default_factory=lambda: os.getenv("DEEPGRAM_API_KEY", ""))
    elevenlabs_api_key: str = field(default_factory=lambda: os.getenv("ELEVENLABS_API_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    stt_model: str = "nova-2"
    stt_language: str = "en"
    tts_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    tts_model: str = "eleven_turbo_v2"
    llm_model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 300
    silence_threshold_ms: int = 1500
    max_turn_duration_ms: int = 30000
    greeting_message: str = "Hi, this is your Beach Habitats concierge. How can I help you today?"


class VoiceSession:
    """Manage a single voice or SMS conversation."""

    def __init__(
        self,
        session_id: Optional[str] = None,
        property_code: Optional[str] = None,
        guest_phone: Optional[str] = None,
        config: Optional[VoiceSessionConfig] = None,
    ):
        self.session_id = session_id or str(uuid4())
        self.property_code = property_code
        self.guest_phone = guest_phone
        self.config = config or VoiceSessionConfig()
        self.state = SessionState.IDLE
        self.started_at: Optional[datetime] = None
        self.ended_at: Optional[datetime] = None
        self.conversation_history: List[ConversationTurn] = []
        self.guest_context: Optional[Dict[str, Any]] = None
        self.local_context: Optional[str] = None
        self._stt = None
        self._tts = None
        self._llm = None
        self._on_transcript: Optional[Callable[[str], Any]] = None
        self._on_response: Optional[Callable[[str], Any]] = None

    async def initialize(self) -> None:
        self.started_at = datetime.now(timezone.utc)
        self.state = SessionState.IDLE
        await self._load_context()
        await self._init_providers()
        logger.info("Voice session %s initialized for %s", self.session_id, self.property_code)

    async def _load_context(self) -> None:
        if not self.property_code:
            return

        try:
            from services.guest_concierge_service import GuestConciergeService

            service = GuestConciergeService()
            context = service.get_guest_context(self.property_code)
            self.guest_context = {
                "property_code": context.property_code,
                "property_name": context.property_name,
                "community": context.community,
                "has_active_booking": context.has_active_booking,
                "check_in_date": str(context.check_in_date) if context.check_in_date else None,
                "check_out_date": str(context.check_out_date) if context.check_out_date else None,
                "nights_remaining": context.nights_remaining,
                "amenities": {
                    "pool": context.has_pool,
                    "bikes": context.has_bikes,
                    "beach_gear": context.has_beach_gear,
                    "grill": context.has_grill,
                },
                "wifi_network": context.wifi_network,
                "wifi_password": context.wifi_password,
            }
            self.local_context = service.format_context_for_llm(context, include_local=True)
        except Exception as exc:
            logger.warning("Failed to load guest context for %s: %s", self.property_code, exc)

    async def _init_providers(self) -> None:
        if self.config.deepgram_api_key:
            try:
                from app.services.voice.providers.deepgram_stt import get_deepgram_stt

                self._stt = get_deepgram_stt(
                    api_key=self.config.deepgram_api_key,
                    model=self.config.stt_model,
                    language=self.config.stt_language,
                )
            except Exception as exc:
                logger.warning("Failed to initialize Deepgram STT: %s", exc)

        if self.config.elevenlabs_api_key:
            try:
                from app.services.voice.providers.elevenlabs_tts import get_elevenlabs_tts

                self._tts = get_elevenlabs_tts(
                    api_key=self.config.elevenlabs_api_key,
                    voice=self.config.tts_voice_id,
                    model_id=self.config.tts_model,
                )
            except Exception as exc:
                logger.warning("Failed to initialize ElevenLabs TTS: %s", exc)

        if self.config.anthropic_api_key:
            try:
                from anthropic import AsyncAnthropic

                self._llm = AsyncAnthropic(api_key=self.config.anthropic_api_key)
            except Exception as exc:
                logger.warning("Failed to initialize Anthropic client: %s", exc)

    def _build_system_prompt(self) -> str:
        prompt = (
            "You are a friendly and helpful guest concierge for Beach Habitats "
            "vacation rentals on 30A in Florida.\n\n"
            "Your role is to answer questions about the property and amenities, "
            "provide local dining and activity recommendations, help with "
            "check-in/check-out questions, handle simple requests, and escalate "
            "maintenance issues when needed.\n\n"
            "Keep responses warm, concise, and natural for a voice conversation."
        )
        if self.local_context:
            prompt += f"\n\n{self.local_context}"
        return prompt

    async def get_greeting(self) -> bytes:
        greeting = self.config.greeting_message
        if self.guest_context:
            property_name = self.guest_context.get("property_name", "your property")
            greeting = f"Hi, this is your Beach Habitats concierge for {property_name}. How can I help you today?"

        self.conversation_history.append(
            ConversationTurn(
                turn_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc),
                speaker="concierge",
                text=greeting,
            )
        )

        if not self._tts:
            return b""

        try:
            result = await self._tts.synthesize(greeting)
            return result.audio_data
        except Exception as exc:
            logger.error("Greeting synthesis failed: %s", exc)
            return b""

    async def process_audio(self, audio_data: bytes) -> Optional[bytes]:
        if self.state == SessionState.ENDED:
            return None

        self.state = SessionState.LISTENING
        transcript = await self._transcribe(audio_data)
        if not transcript.strip():
            self.state = SessionState.IDLE
            return None

        self.conversation_history.append(
            ConversationTurn(
                turn_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc),
                speaker="guest",
                text=transcript,
            )
        )
        if self._on_transcript:
            await self._on_transcript(transcript)

        self.state = SessionState.PROCESSING
        response_text = await self._generate_response(transcript)
        self.conversation_history.append(
            ConversationTurn(
                turn_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc),
                speaker="concierge",
                text=response_text,
            )
        )
        if self._on_response:
            await self._on_response(response_text)

        self.state = SessionState.SPEAKING
        audio = await self._synthesize(response_text)
        self.state = SessionState.IDLE
        return audio

    async def process_text(self, text: str) -> str:
        if self.state == SessionState.ENDED:
            return ""

        self.conversation_history.append(
            ConversationTurn(
                turn_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc),
                speaker="guest",
                text=text,
            )
        )
        response_text = await self._generate_response(text)
        self.conversation_history.append(
            ConversationTurn(
                turn_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc),
                speaker="concierge",
                text=response_text,
            )
        )
        return response_text

    async def _transcribe(self, audio_data: bytes) -> str:
        if not self._stt:
            logger.warning("No STT provider configured for session %s", self.session_id)
            return ""
        try:
            result = await self._stt.transcribe(audio_data)
            return result.text
        except Exception as exc:
            logger.error("Transcription failed for %s: %s", self.session_id, exc)
            return ""

    async def _generate_response(self, user_text: str) -> str:
        if not self._llm:
            logger.warning("No LLM provider configured for session %s", self.session_id)
            return "I apologize, but I'm having trouble processing your request right now."

        messages = []
        for turn in self.conversation_history[-6:]:
            role = "user" if turn.speaker == "guest" else "assistant"
            messages.append({"role": role, "content": turn.text})
        if not messages or messages[-1]["role"] != "user":
            messages.append({"role": "user", "content": user_text})

        try:
            timer = LLMCallTimer()
            response = await self._llm.messages.create(
                model=self.config.llm_model,
                max_tokens=self.config.max_tokens,
                system=self._build_system_prompt(),
                messages=messages,
            )
            await self._record_llm_usage(
                input_tokens=int(getattr(getattr(response, "usage", None), "input_tokens", 0) or 0),
                output_tokens=int(getattr(getattr(response, "usage", None), "output_tokens", 0) or 0),
                success=True,
                latency_ms=timer.elapsed_ms(),
                error_type=None,
            )
            return response.content[0].text
        except Exception as exc:
            await self._record_llm_usage(
                input_tokens=0,
                output_tokens=0,
                success=False,
                latency_ms=timer.elapsed_ms() if "timer" in locals() else 0,
                error_type=type(exc).__name__,
            )
            logger.error("LLM generation failed for %s: %s", self.session_id, exc)
            return (
                "I apologize, but I'm having trouble right now. "
                "Would you like me to connect you with our property manager?"
            )

    async def _record_llm_usage(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        success: bool,
        latency_ms: int,
        error_type: Optional[str],
    ) -> None:
        await LLMUsageTracker.record(
            service_name="voice_session",
            tenant_id=None,
            request_type="voice_response_generation",
            provider="anthropic",
            model_id=self.config.llm_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            success=success,
            latency_ms=latency_ms,
            error_type=error_type,
            metadata={
                "session_id": self.session_id,
                "property_code": self.property_code or "",
                "guest_phone": self.guest_phone or "",
                "turn_count": len(self.conversation_history),
            },
        )

    async def _synthesize(self, text: str) -> bytes:
        if not self._tts:
            logger.warning("No TTS provider configured for session %s", self.session_id)
            return b""
        try:
            result = await self._tts.synthesize(text)
            return result.audio_data
        except Exception as exc:
            logger.error("TTS synthesis failed for %s: %s", self.session_id, exc)
            return b""

    async def end(self) -> None:
        if self.state == SessionState.ENDED:
            return
        self.state = SessionState.ENDED
        self.ended_at = datetime.now(timezone.utc)
        await self._log_conversation()

    async def _log_conversation(self) -> None:
        try:
            from app.services.voice.conversation_logger import log_conversation

            await log_conversation(
                session_id=self.session_id,
                property_code=self.property_code,
                guest_phone=self.guest_phone,
                channel="voice",
                turns=self.conversation_history,
                started_at=self.started_at or datetime.now(timezone.utc),
                ended_at=self.ended_at,
            )
        except Exception as exc:
            logger.error("Failed to log conversation for %s: %s", self.session_id, exc)

    def get_transcript(self) -> str:
        return "\n".join(
            f"{'Guest' if turn.speaker == 'guest' else 'Concierge'}: {turn.text}"
            for turn in self.conversation_history
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "property_code": self.property_code,
            "guest_phone": self.guest_phone,
            "state": self.state.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "turn_count": len(self.conversation_history),
            "conversation": [turn.to_dict() for turn in self.conversation_history],
        }


class VoiceSessionManager:
    """Track and clean up concurrent voice sessions."""

    def __init__(self, config: Optional[VoiceSessionConfig] = None):
        self.config = config or VoiceSessionConfig()
        self.sessions: Dict[str, VoiceSession] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        property_code: Optional[str] = None,
        guest_phone: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> VoiceSession:
        session = VoiceSession(
            session_id=session_id,
            property_code=property_code,
            guest_phone=guest_phone,
            config=self.config,
        )
        await session.initialize()
        async with self._lock:
            self.sessions[session.session_id] = session
        return session

    def get_session(self, session_id: Optional[str]) -> Optional[VoiceSession]:
        if not session_id:
            return None
        return self.sessions.get(session_id)

    async def end_session(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        session = self.sessions.get(session_id)
        if not session:
            return
        await session.end()
        async with self._lock:
            self.sessions.pop(session_id, None)

    async def cleanup_stale_sessions(self, max_age_minutes: int = 30) -> None:
        now = datetime.now(timezone.utc)
        stale_session_ids = []
        for session_id, session in self.sessions.items():
            if session.started_at:
                age_minutes = (now - session.started_at).total_seconds() / 60
                if age_minutes > max_age_minutes:
                    stale_session_ids.append(session_id)

        for session_id in stale_session_ids:
            await self.end_session(session_id)
