"""
Voice Provider: Deepgram STT (Speech-to-Text).

Thin adapter for Deepgram transcription.
No business logic - only audio → text conversion.
"""

from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    """Result from speech-to-text transcription."""
    text: str
    confidence: float
    language: str = "en"
    duration_seconds: float = 0.0
    
    # Word-level timing (optional)
    words: list = None
    
    def __post_init__(self):
        if self.words is None:
            self.words = []


@dataclass 
class DeepgramConfig:
    """Configuration for Deepgram STT."""
    api_key: str
    model: str = "nova-2"  # or "nova", "enhanced", "base"
    language: str = "en"
    punctuate: bool = True
    diarize: bool = False
    smart_format: bool = True
    

class DeepgramSTT:
    """
    Deepgram Speech-to-Text adapter.
    
    This is a thin wrapper - it does NOT:
    - Make decisions
    - Parse intent
    - Handle business logic
    
    It ONLY converts audio to text.
    
    Usage:
        stt = DeepgramSTT(config)
        result = await stt.transcribe(audio_bytes)
        text = result.text
    """
    
    def __init__(self, config: DeepgramConfig):
        self.config = config
        self._client = None
    
    async def _get_client(self):
        """Lazy initialization of Deepgram client."""
        if self._client is None:
            try:
                from deepgram import Deepgram
                self._client = Deepgram(self.config.api_key)
            except ImportError:
                logger.warning("Deepgram SDK not installed. Install with: pip install deepgram-sdk")
                raise
        return self._client
    
    async def transcribe(self, audio_data: bytes, mime_type: str = "audio/wav") -> TranscriptionResult:
        """
        Transcribe audio to text.
        
        Args:
            audio_data: Raw audio bytes
            mime_type: Audio format (audio/wav, audio/mp3, etc.)
            
        Returns:
            TranscriptionResult with text and confidence
        """
        try:
            client = await self._get_client()
            
            source = {"buffer": audio_data, "mimetype": mime_type}
            
            options = {
                "model": self.config.model,
                "language": self.config.language,
                "punctuate": self.config.punctuate,
                "diarize": self.config.diarize,
                "smart_format": self.config.smart_format,
            }
            
            response = await client.transcription.prerecorded(source, options)
            
            # Extract results
            channel = response["results"]["channels"][0]
            alternative = channel["alternatives"][0]
            
            return TranscriptionResult(
                text=alternative["transcript"],
                confidence=alternative["confidence"],
                language=self.config.language,
                words=alternative.get("words", []),
            )
            
        except Exception as e:
            logger.error(f"Deepgram transcription failed: {e}")
            # Return empty result on failure
            return TranscriptionResult(text="", confidence=0.0)
    
    async def transcribe_stream(self, audio_stream):
        """
        Transcribe streaming audio (real-time).
        
        Placeholder for WebSocket-based streaming transcription.
        """
        raise NotImplementedError("Streaming transcription not yet implemented")


# Factory function
def get_deepgram_stt(api_key: str, **kwargs) -> DeepgramSTT:
    """Create a Deepgram STT instance."""
    config = DeepgramConfig(api_key=api_key, **kwargs)
    return DeepgramSTT(config)
