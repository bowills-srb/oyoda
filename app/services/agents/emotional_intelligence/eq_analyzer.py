"""
Emotional Intelligence (EQ) Layer

Real-time sentiment analysis and dynamic persona adaptation.

This module:
1. Analyzes acoustic signals (pitch, pace, tone) from voice
2. Analyzes text sentiment from chat
3. Detects urgency and emotional state
4. Triggers persona shifts in the Voice Pod

Integrations:
- Hume AI (acoustic sentiment)
- Deepgram (has sentiment in transcription)
- Text-based fallback using Claude

The goal: A guest who is frustrated gets "Crisis Resolution" mode,
while a relaxed guest gets "Beach Chill" mode.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class EmotionalState(str, Enum):
    """Detected emotional states."""
    CALM = "calm"
    HAPPY = "happy"
    EXCITED = "excited"
    NEUTRAL = "neutral"
    CONFUSED = "confused"
    FRUSTRATED = "frustrated"
    ANXIOUS = "anxious"
    ANGRY = "angry"
    URGENT = "urgent"


class UrgencyLevel(str, Enum):
    """Urgency levels for response adaptation."""
    LOW = "low"           # Casual inquiry, take your time
    NORMAL = "normal"     # Standard question
    ELEVATED = "elevated" # Some time pressure
    HIGH = "high"         # Needs quick resolution
    CRISIS = "crisis"     # Emergency - immediate action needed


@dataclass
class SentimentSignals:
    """Raw sentiment signals from various sources."""
    # Acoustic signals (from voice)
    pitch_variance: Optional[float] = None  # High = excited/frustrated
    speech_rate: Optional[float] = None     # Fast = urgent/anxious
    volume_level: Optional[float] = None    # Loud = frustrated/angry
    pause_frequency: Optional[float] = None # Many pauses = confused/thinking
    
    # Text signals
    exclamation_count: int = 0
    question_count: int = 0
    caps_ratio: float = 0.0
    negative_words: List[str] = field(default_factory=list)
    urgency_words: List[str] = field(default_factory=list)
    
    # Conversation context
    repeated_questions: int = 0  # Asking same thing = frustrated
    message_length_trend: str = "stable"  # "increasing" = elaborating, "decreasing" = giving up


@dataclass
class EmotionalContext:
    """Full emotional context for a conversation."""
    # Primary assessment
    emotional_state: EmotionalState = EmotionalState.NEUTRAL
    urgency_level: UrgencyLevel = UrgencyLevel.NORMAL
    confidence: float = 0.5
    
    # Underlying signals
    signals: SentimentSignals = field(default_factory=SentimentSignals)
    
    # Recommended adaptations
    persona_mode: str = "default"  # default, empathetic, crisis, celebratory
    response_style: str = "normal"  # normal, concise, detailed, reassuring
    suggested_tone: str = "friendly"  # friendly, professional, urgent, calming
    
    # History
    state_history: List[Tuple[datetime, EmotionalState]] = field(default_factory=list)
    
    def to_prompt_context(self) -> str:
        """Generate context string for LLM prompt."""
        if self.urgency_level == UrgencyLevel.CRISIS:
            return (
                f"URGENT: Guest appears {self.emotional_state.value}. "
                f"Use {self.persona_mode} mode. Keep responses SHORT and actionable. "
                f"Prioritize immediate resolution."
            )
        elif self.urgency_level == UrgencyLevel.HIGH:
            return (
                f"Guest seems {self.emotional_state.value}. "
                f"Be {self.suggested_tone} and efficient. Skip pleasantries."
            )
        elif self.emotional_state in [EmotionalState.FRUSTRATED, EmotionalState.ANXIOUS]:
            return (
                f"Guest may be {self.emotional_state.value}. "
                f"Be extra {self.suggested_tone}. Acknowledge their concern first."
            )
        elif self.emotional_state in [EmotionalState.HAPPY, EmotionalState.EXCITED]:
            return (
                f"Guest is {self.emotional_state.value}! "
                f"Match their energy. Feel free to be enthusiastic."
            )
        else:
            return ""  # No special adaptation needed


# Keyword lists for text analysis
URGENCY_KEYWORDS = {
    "crisis": ["emergency", "urgent", "asap", "immediately", "right now", "help", 
               "locked out", "can't get in", "no power", "flooding", "broken"],
    "high": ["quickly", "soon", "waiting", "still", "already", "need", "must",
             "before", "tonight", "today"],
    "elevated": ["wondering", "could you", "when", "how long"],
}

NEGATIVE_KEYWORDS = [
    "frustrated", "angry", "upset", "annoyed", "disappointed", "terrible",
    "awful", "horrible", "unacceptable", "ridiculous", "wrong", "broken",
    "doesn't work", "not working", "failed", "problem", "issue", "complaint"
]

POSITIVE_KEYWORDS = [
    "thank", "thanks", "great", "awesome", "perfect", "wonderful", "amazing",
    "love", "beautiful", "excellent", "fantastic", "appreciate"
]


class EQAnalyzer:
    """
    Analyzes emotional state from text and acoustic signals.
    
    Usage:
        analyzer = EQAnalyzer()
        
        # Analyze text message
        context = await analyzer.analyze_text(
            "I've been waiting 30 minutes and still can't get the door code to work!!"
        )
        
        # Analyze with acoustic data (from voice)
        context = await analyzer.analyze_combined(
            text="The door won't open",
            acoustic_data={"pitch_variance": 0.8, "speech_rate": 1.5}
        )
        
        # Get prompt adaptation
        prompt_context = context.to_prompt_context()
    """
    
    def __init__(self):
        self._hume_client = None  # Lazy init
        self._conversation_history: Dict[str, List[EmotionalContext]] = {}
    
    async def analyze_text(
        self,
        text: str,
        conversation_id: Optional[str] = None,
        previous_messages: Optional[List[str]] = None,
    ) -> EmotionalContext:
        """
        Analyze emotional state from text only.
        
        This is used for chat-based interactions.
        """
        signals = SentimentSignals()
        
        text_lower = text.lower()
        
        # Count exclamations and questions
        signals.exclamation_count = text.count("!")
        signals.question_count = text.count("?")
        
        # Check caps ratio (YELLING?)
        alpha_chars = [c for c in text if c.isalpha()]
        if alpha_chars:
            signals.caps_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
        
        # Find urgency words
        for level, keywords in URGENCY_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    signals.urgency_words.append(kw)
        
        # Find negative words
        for word in NEGATIVE_KEYWORDS:
            if word in text_lower:
                signals.negative_words.append(word)
        
        # Check for repeated questions (frustration signal)
        if previous_messages:
            current_intent = self._extract_intent(text)
            for prev in previous_messages[-3:]:
                if self._extract_intent(prev) == current_intent:
                    signals.repeated_questions += 1
        
        # Determine emotional state and urgency
        emotional_state, urgency, confidence = self._classify_from_signals(signals)
        
        # Build context
        context = EmotionalContext(
            emotional_state=emotional_state,
            urgency_level=urgency,
            confidence=confidence,
            signals=signals,
            persona_mode=self._determine_persona_mode(emotional_state, urgency),
            response_style=self._determine_response_style(emotional_state, urgency),
            suggested_tone=self._determine_tone(emotional_state, urgency),
        )
        
        # Track history
        if conversation_id:
            if conversation_id not in self._conversation_history:
                self._conversation_history[conversation_id] = []
            self._conversation_history[conversation_id].append(context)
            context.state_history = [
                (datetime.utcnow(), c.emotional_state) 
                for c in self._conversation_history[conversation_id][-5:]
            ]
        
        return context
    
    async def analyze_acoustic(
        self,
        acoustic_data: Dict[str, float],
    ) -> SentimentSignals:
        """
        Analyze acoustic signals from voice.
        
        Expected data from Deepgram/Hume:
        - pitch_variance: 0.0-1.0 (higher = more emotional)
        - speech_rate: words per second (normal ~2.5)
        - volume_level: 0.0-1.0
        - pause_frequency: pauses per sentence
        """
        signals = SentimentSignals(
            pitch_variance=acoustic_data.get("pitch_variance"),
            speech_rate=acoustic_data.get("speech_rate"),
            volume_level=acoustic_data.get("volume_level"),
            pause_frequency=acoustic_data.get("pause_frequency"),
        )
        
        return signals
    
    async def analyze_combined(
        self,
        text: str,
        acoustic_data: Optional[Dict[str, float]] = None,
        conversation_id: Optional[str] = None,
    ) -> EmotionalContext:
        """
        Analyze with both text and acoustic signals.
        
        This is the full analysis for voice interactions.
        """
        # Start with text analysis
        context = await self.analyze_text(text, conversation_id)
        
        # Enhance with acoustic data if available
        if acoustic_data:
            acoustic_signals = await self.analyze_acoustic(acoustic_data)
            
            # Merge signals
            context.signals.pitch_variance = acoustic_signals.pitch_variance
            context.signals.speech_rate = acoustic_signals.speech_rate
            context.signals.volume_level = acoustic_signals.volume_level
            context.signals.pause_frequency = acoustic_signals.pause_frequency
            
            # Re-classify with enhanced signals
            emotional_state, urgency, confidence = self._classify_from_signals(
                context.signals, include_acoustic=True
            )
            
            context.emotional_state = emotional_state
            context.urgency_level = urgency
            context.confidence = min(confidence + 0.2, 1.0)  # More confident with acoustic
            
            # Update adaptations
            context.persona_mode = self._determine_persona_mode(emotional_state, urgency)
            context.response_style = self._determine_response_style(emotional_state, urgency)
            context.suggested_tone = self._determine_tone(emotional_state, urgency)
        
        return context
    
    def _extract_intent(self, text: str) -> str:
        """Extract rough intent for comparison."""
        # Simple keyword-based intent extraction
        text_lower = text.lower()
        
        if any(w in text_lower for w in ["wifi", "password", "internet"]):
            return "wifi"
        if any(w in text_lower for w in ["door", "code", "lock", "key"]):
            return "access"
        if any(w in text_lower for w in ["check", "in", "out", "time"]):
            return "timing"
        if any(w in text_lower for w in ["restaurant", "eat", "food", "dinner"]):
            return "dining"
        
        return "general"
    
    def _classify_from_signals(
        self,
        signals: SentimentSignals,
        include_acoustic: bool = False,
    ) -> Tuple[EmotionalState, UrgencyLevel, float]:
        """Classify emotional state and urgency from signals."""
        
        # Start with defaults
        state = EmotionalState.NEUTRAL
        urgency = UrgencyLevel.NORMAL
        confidence = 0.5
        
        # Check for crisis-level urgency
        crisis_words = set(URGENCY_KEYWORDS["crisis"])
        if any(w in crisis_words for w in signals.urgency_words):
            urgency = UrgencyLevel.CRISIS
            state = EmotionalState.URGENT
            confidence = 0.9
            return state, urgency, confidence
        
        # Check negative signals
        negative_score = len(signals.negative_words)
        if signals.exclamation_count > 2:
            negative_score += 1
        if signals.caps_ratio > 0.3:
            negative_score += 2
        if signals.repeated_questions > 0:
            negative_score += signals.repeated_questions
        
        # Check positive signals
        # (would need to track positive words too)
        
        # Acoustic boost
        if include_acoustic:
            if signals.pitch_variance and signals.pitch_variance > 0.7:
                negative_score += 1
            if signals.speech_rate and signals.speech_rate > 3.5:
                negative_score += 1
                urgency = max(urgency, UrgencyLevel.ELEVATED)
            if signals.volume_level and signals.volume_level > 0.8:
                negative_score += 1
        
        # Classify based on score
        if negative_score >= 4:
            state = EmotionalState.ANGRY
            urgency = UrgencyLevel.HIGH
            confidence = 0.85
        elif negative_score >= 2:
            state = EmotionalState.FRUSTRATED
            urgency = UrgencyLevel.ELEVATED
            confidence = 0.75
        elif negative_score >= 1:
            state = EmotionalState.ANXIOUS
            confidence = 0.65
        
        # Check for high urgency keywords
        if any(w in URGENCY_KEYWORDS["high"] for w in signals.urgency_words):
            urgency = max(urgency, UrgencyLevel.HIGH)
        elif any(w in URGENCY_KEYWORDS["elevated"] for w in signals.urgency_words):
            urgency = max(urgency, UrgencyLevel.ELEVATED)
        
        return state, urgency, confidence
    
    def _determine_persona_mode(
        self,
        state: EmotionalState,
        urgency: UrgencyLevel,
    ) -> str:
        """Determine which persona mode to use."""
        if urgency == UrgencyLevel.CRISIS:
            return "crisis"
        if state in [EmotionalState.FRUSTRATED, EmotionalState.ANGRY]:
            return "empathetic"
        if state in [EmotionalState.ANXIOUS, EmotionalState.CONFUSED]:
            return "reassuring"
        if state in [EmotionalState.HAPPY, EmotionalState.EXCITED]:
            return "celebratory"
        return "default"
    
    def _determine_response_style(
        self,
        state: EmotionalState,
        urgency: UrgencyLevel,
    ) -> str:
        """Determine response style."""
        if urgency in [UrgencyLevel.CRISIS, UrgencyLevel.HIGH]:
            return "concise"
        if state == EmotionalState.CONFUSED:
            return "detailed"
        if state in [EmotionalState.FRUSTRATED, EmotionalState.ANXIOUS]:
            return "reassuring"
        return "normal"
    
    def _determine_tone(
        self,
        state: EmotionalState,
        urgency: UrgencyLevel,
    ) -> str:
        """Determine suggested tone."""
        if urgency == UrgencyLevel.CRISIS:
            return "urgent"
        if state in [EmotionalState.FRUSTRATED, EmotionalState.ANGRY]:
            return "calming"
        if state in [EmotionalState.ANXIOUS]:
            return "reassuring"
        if state in [EmotionalState.HAPPY, EmotionalState.EXCITED]:
            return "enthusiastic"
        return "friendly"


# Singleton
_eq_analyzer: Optional[EQAnalyzer] = None


def get_eq_analyzer() -> EQAnalyzer:
    """Get or create EQ analyzer instance."""
    global _eq_analyzer
    if _eq_analyzer is None:
        _eq_analyzer = EQAnalyzer()
    return _eq_analyzer
