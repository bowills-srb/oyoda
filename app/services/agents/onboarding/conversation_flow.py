"""
Conversation Flow Management

Manages the conversational state for onboarding,
including message history, context, and resumption.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class ConversationState(str, Enum):
    """State of the conversation."""
    ACTIVE = "active"
    WAITING_FOR_INPUT = "waiting_for_input"
    PROCESSING = "processing"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ConversationMessage:
    """A message in the conversation."""
    role: str  # user, assistant, system
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OnboardingConversation:
    """
    Manages the conversation flow for onboarding.
    
    Tracks:
    - Message history
    - Current state
    - Context for LLM
    - Resumption data
    """
    
    session_id: str
    state: ConversationState = ConversationState.ACTIVE
    messages: List[ConversationMessage] = field(default_factory=list)
    
    # Current context
    current_topic: Optional[str] = None
    pending_action: Optional[str] = None
    
    # For LLM context
    system_context: str = ""
    
    def add_user_message(self, content: str, metadata: Dict[str, Any] = None):
        """Add a user message."""
        self.messages.append(ConversationMessage(
            role="user",
            content=content,
            metadata=metadata or {},
        ))
    
    def add_assistant_message(self, content: str, metadata: Dict[str, Any] = None):
        """Add an assistant message."""
        self.messages.append(ConversationMessage(
            role="assistant",
            content=content,
            metadata=metadata or {},
        ))
    
    def get_recent_messages(self, count: int = 10) -> List[Dict[str, str]]:
        """Get recent messages for LLM context."""
        recent = self.messages[-count:]
        return [
            {"role": m.role, "content": m.content}
            for m in recent
        ]
    
    def get_full_context(self) -> str:
        """Get full conversation context for LLM."""
        lines = [self.system_context] if self.system_context else []
        
        for msg in self.messages[-10:]:
            prefix = "User:" if msg.role == "user" else "Assistant:"
            lines.append(f"{prefix} {msg.content}")
        
        return "\n\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage."""
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp.isoformat(),
                    "metadata": m.metadata,
                }
                for m in self.messages
            ],
            "current_topic": self.current_topic,
            "pending_action": self.pending_action,
            "system_context": self.system_context,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OnboardingConversation":
        """Deserialize from storage."""
        conv = cls(
            session_id=data["session_id"],
            state=ConversationState(data.get("state", "active")),
            current_topic=data.get("current_topic"),
            pending_action=data.get("pending_action"),
            system_context=data.get("system_context", ""),
        )
        
        for msg_data in data.get("messages", []):
            conv.messages.append(ConversationMessage(
                role=msg_data["role"],
                content=msg_data["content"],
                timestamp=datetime.fromisoformat(msg_data["timestamp"]) if msg_data.get("timestamp") else datetime.utcnow(),
                metadata=msg_data.get("metadata", {}),
            ))
        
        return conv
