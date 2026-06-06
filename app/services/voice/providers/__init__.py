"""
Voice Providers.

Thin adapters for speech-to-text and text-to-speech services.
These do NOT contain business logic - only audio conversion.

Providers:
- DeepgramSTT: Speech-to-text via Deepgram
- ElevenLabsTTS: Text-to-speech via ElevenLabs
"""

from .deepgram_stt import (
    DeepgramSTT,
    DeepgramConfig,
    TranscriptionResult,
    get_deepgram_stt,
)

from .elevenlabs_tts import (
    ElevenLabsTTS,
    ElevenLabsConfig,
    SynthesisResult,
    VOICES,
    get_elevenlabs_tts,
)


__all__ = [
    # Deepgram STT
    "DeepgramSTT",
    "DeepgramConfig",
    "TranscriptionResult",
    "get_deepgram_stt",
    
    # ElevenLabs TTS
    "ElevenLabsTTS",
    "ElevenLabsConfig",
    "SynthesisResult",
    "VOICES",
    "get_elevenlabs_tts",
]
