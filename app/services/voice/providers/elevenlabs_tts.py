"""
Voice Provider: ElevenLabs TTS (Text-to-Speech).

Thin adapter for ElevenLabs speech synthesis.
No business logic - only text → audio conversion.
"""

from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class SynthesisResult:
    """Result from text-to-speech synthesis."""
    audio_data: bytes
    mime_type: str = "audio/mpeg"
    duration_seconds: float = 0.0
    character_count: int = 0


@dataclass
class ElevenLabsConfig:
    """Configuration for ElevenLabs TTS."""
    api_key: str
    voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # Rachel (default)
    model_id: str = "eleven_monolingual_v1"
    
    # Voice settings
    stability: float = 0.5
    similarity_boost: float = 0.75
    style: float = 0.0
    use_speaker_boost: bool = True
    
    # Output format
    output_format: str = "mp3_44100_128"  # mp3_22050_32, mp3_44100_64, mp3_44100_128, mp3_44100_192


# Pre-defined voice options
VOICES = {
    "rachel": "21m00Tcm4TlvDq8ikWAM",  # Warm, professional female
    "adam": "pNInz6obpgDQGcFmaJgB",    # Deep, authoritative male
    "bella": "EXAVITQu4vr4xnSDxMaL",   # Soft, friendly female
    "josh": "TxGEqnHWrfWFTfGW9XjX",    # Young, energetic male
    "elli": "MF3mGyEYCl7XYWbV9V6O",    # Young, expressive female
}


class ElevenLabsTTS:
    """
    ElevenLabs Text-to-Speech adapter.
    
    This is a thin wrapper - it does NOT:
    - Make decisions
    - Generate content
    - Handle business logic
    
    It ONLY converts text to audio.
    
    Usage:
        tts = ElevenLabsTTS(config)
        result = await tts.synthesize("Hello, welcome to your stay!")
        audio_bytes = result.audio_data
    """
    
    def __init__(self, config: ElevenLabsConfig):
        self.config = config
        self._client = None
    
    async def _get_client(self):
        """Lazy initialization of ElevenLabs client."""
        if self._client is None:
            try:
                from elevenlabs import ElevenLabs
                self._client = ElevenLabs(api_key=self.config.api_key)
            except ImportError:
                logger.warning("ElevenLabs SDK not installed. Install with: pip install elevenlabs")
                raise
        return self._client
    
    async def synthesize(self, text: str) -> SynthesisResult:
        """
        Synthesize text to speech.
        
        Args:
            text: Text to convert to speech
            
        Returns:
            SynthesisResult with audio bytes
        """
        try:
            client = await self._get_client()
            
            audio = client.text_to_speech.convert(
                voice_id=self.config.voice_id,
                model_id=self.config.model_id,
                text=text,
                voice_settings={
                    "stability": self.config.stability,
                    "similarity_boost": self.config.similarity_boost,
                    "style": self.config.style,
                    "use_speaker_boost": self.config.use_speaker_boost,
                },
                output_format=self.config.output_format,
            )
            
            # Collect audio chunks
            audio_bytes = b"".join(audio)
            
            return SynthesisResult(
                audio_data=audio_bytes,
                mime_type="audio/mpeg",
                character_count=len(text),
            )
            
        except Exception as e:
            logger.error(f"ElevenLabs synthesis failed: {e}")
            return SynthesisResult(audio_data=b"", character_count=0)
    
    async def synthesize_stream(self, text: str):
        """
        Stream synthesized audio (real-time).
        
        Yields audio chunks as they're generated.
        """
        try:
            client = await self._get_client()
            
            audio_stream = client.text_to_speech.convert_as_stream(
                voice_id=self.config.voice_id,
                model_id=self.config.model_id,
                text=text,
                voice_settings={
                    "stability": self.config.stability,
                    "similarity_boost": self.config.similarity_boost,
                },
            )
            
            for chunk in audio_stream:
                yield chunk
                
        except Exception as e:
            logger.error(f"ElevenLabs streaming failed: {e}")
            return


# Factory function
def get_elevenlabs_tts(
    api_key: str, 
    voice: str = "rachel",
    **kwargs
) -> ElevenLabsTTS:
    """
    Create an ElevenLabs TTS instance.
    
    Args:
        api_key: ElevenLabs API key
        voice: Voice name ("rachel", "adam", "bella", "josh", "elli") or voice_id
        **kwargs: Additional config options
    """
    voice_id = VOICES.get(voice, voice)  # Use name or raw ID
    config = ElevenLabsConfig(api_key=api_key, voice_id=voice_id, **kwargs)
    return ElevenLabsTTS(config)
