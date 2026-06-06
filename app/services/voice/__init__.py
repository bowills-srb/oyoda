"""
Beach Habitats voice module.

The voice stack depends on optional providers and integration libraries, so
exports are resolved lazily to avoid breaking unrelated imports.
"""

from importlib import import_module
from typing import Any

__all__ = [
    "DeepgramSTT",
    "DeepgramConfig",
    "TranscriptionResult",
    "get_deepgram_stt",
    "ElevenLabsTTS",
    "ElevenLabsConfig",
    "SynthesisResult",
    "VOICES",
    "get_elevenlabs_tts",
    "VoiceSession",
    "VoiceSessionManager",
    "VoiceSessionConfig",
    "SessionState",
    "ConversationTurn",
    "log_conversation",
    "log_single_turn",
    "log_feedback",
    "export_training_data",
    "get_conversation_stats",
]


_EXPORT_MAP = {
    "DeepgramSTT": ("app.services.voice.providers", "DeepgramSTT"),
    "DeepgramConfig": ("app.services.voice.providers", "DeepgramConfig"),
    "TranscriptionResult": ("app.services.voice.providers", "TranscriptionResult"),
    "get_deepgram_stt": ("app.services.voice.providers", "get_deepgram_stt"),
    "ElevenLabsTTS": ("app.services.voice.providers", "ElevenLabsTTS"),
    "ElevenLabsConfig": ("app.services.voice.providers", "ElevenLabsConfig"),
    "SynthesisResult": ("app.services.voice.providers", "SynthesisResult"),
    "VOICES": ("app.services.voice.providers", "VOICES"),
    "get_elevenlabs_tts": ("app.services.voice.providers", "get_elevenlabs_tts"),
    "VoiceSession": ("app.services.voice.voice_session", "VoiceSession"),
    "VoiceSessionManager": ("app.services.voice.voice_session", "VoiceSessionManager"),
    "VoiceSessionConfig": ("app.services.voice.voice_session", "VoiceSessionConfig"),
    "SessionState": ("app.services.voice.voice_session", "SessionState"),
    "ConversationTurn": ("app.services.voice.voice_session", "ConversationTurn"),
    "log_conversation": ("app.services.voice.conversation_logger", "log_conversation"),
    "log_single_turn": ("app.services.voice.conversation_logger", "log_single_turn"),
    "log_feedback": ("app.services.voice.conversation_logger", "log_feedback"),
    "export_training_data": ("app.services.voice.conversation_logger", "export_training_data"),
    "get_conversation_stats": ("app.services.voice.conversation_logger", "get_conversation_stats"),
}


def __getattr__(name: str) -> Any:
    module_name, attr_name = _EXPORT_MAP.get(name, (None, None))
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
