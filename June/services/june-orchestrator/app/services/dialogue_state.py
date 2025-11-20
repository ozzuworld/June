"""
Dialogue State Management for June Orchestrator
Phase 1 Implementation

Provides:
- DialogueState enum for tracking conversation state
- Intent class for intent recognition
- ConversationContext for rich context management
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class DialogueState(str, Enum):
    """Dialogue states for task-oriented conversations"""
    GREETING = "greeting"
    INTENT_RECOGNITION = "intent_recognition"
    SLOT_FILLING = "slot_filling"
    CONFIRMATION = "confirmation"
    EXECUTION = "execution"
    CLARIFICATION = "clarification"
    ERROR_RECOVERY = "error_recovery"
    CLOSING = "closing"
    GENERAL_CONVERSATION = "general_conversation"


@dataclass
class Intent:
    """User intent with confidence and slots"""
    name: str
    confidence: float
    slots: Dict[str, Any] = field(default_factory=dict)
    domain: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Validate confidence score"""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be between 0 and 1, got {self.confidence}")
    
    def is_confident(self, threshold: float = 0.7) -> bool:
        """Check if intent confidence exceeds threshold"""
        return self.confidence >= threshold
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "name": self.name,
            "confidence": self.confidence,
            "slots": self.slots,
            "domain": self.domain,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class ConversationTurn:
    """Single turn in conversation"""
    role: str  # "user" or "assistant"
    content: str
    intent: Optional[Intent] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "role": self.role,
            "content": self.content,
            "intent": self.intent.to_dict() if self.intent else None,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class ConversationContext:
    """
    Rich conversation context with dialogue state tracking
    
    This is the heart of the enhanced conversation management system.
    It tracks everything needed for intelligent, context-aware conversations.
    """
    session_id: str
    
    # Dialogue state
    current_state: DialogueState = DialogueState.GENERAL_CONVERSATION
    current_intent: Optional[Intent] = None
    pending_slots: List[str] = field(default_factory=list)
    filled_slots: Dict[str, Any] = field(default_factory=dict)
    
    # Multi-turn tracking
    topic_history: List[str] = field(default_factory=list)
    current_topic: Optional[str] = None
    context_switches: int = 0
    
    # Memory management
    short_term_memory: List[ConversationTurn] = field(default_factory=list)
    long_term_memory: Dict[str, Any] = field(default_factory=dict)
    semantic_memory: List[str] = field(default_factory=list)
    
    # User modeling
    user_preferences: Dict[str, Any] = field(default_factory=dict)
    conversation_style: str = "balanced"  # "formal", "casual", "balanced", "technical"

    # ✅ MULTILINGUAL: Language tracking
    detected_language: str = "en"  # Language detected from user's speech (from STT)
    requested_language: Optional[str] = None  # Language explicitly requested by user (e.g., "tell a story in Japanese")

    # Metrics
    total_turns: int = 0
    successful_intents: int = 0
    clarification_requests: int = 0
    context_window_compressions: int = 0
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    
    def add_turn(
        self, 
        role: str, 
        content: str, 
        intent: Optional[Intent] = None,
        metadata: Optional[Dict] = None
    ):
        """
        Add a conversational turn with context tracking
        
        Args:
            role: "user" or "assistant"
            content: Message content
            intent: Detected intent (if any)
            metadata: Additional metadata
        """
        turn = ConversationTurn(
            role=role,
            content=content,
            intent=intent,
            metadata=metadata or {},
            timestamp=datetime.utcnow()
        )
        
        self.short_term_memory.append(turn)
        self.total_turns += 1
        self.last_activity = datetime.utcnow()
        
        # Update successful intents
        if intent and intent.is_confident():
            self.successful_intents += 1
        
        # Trim short-term memory if too long
        if len(self.short_term_memory) > 15:
            # Keep last 10 turns
            self.short_term_memory = self.short_term_memory[-10:]
            self.context_window_compressions += 1
            logger.info(f"Compressed context window for session {self.session_id[:8]}...")
    
    def update_state(self, new_state: DialogueState):
        """Update dialogue state"""
        old_state = self.current_state
        self.current_state = new_state
        logger.debug(f"State transition: {old_state} → {new_state}")
    
    def update_intent(self, intent: Intent):
        """Update current intent"""
        self.current_intent = intent
        
        # Extract slots if present
        if intent.slots:
            self.filled_slots.update(intent.slots)
    
    def add_slot(self, slot_name: str, slot_value: Any):
        """Add a filled slot"""
        self.filled_slots[slot_name] = slot_value
        
        # Remove from pending if it was pending
        if slot_name in self.pending_slots:
            self.pending_slots.remove(slot_name)
    
    def get_pending_slots(self) -> List[str]:
        """Get list of unfilled required slots"""
        return self.pending_slots.copy()
    
    def is_slot_filled(self, slot_name: str) -> bool:
        """Check if a slot is filled"""
        return slot_name in self.filled_slots
    
    def get_slot_value(self, slot_name: str) -> Optional[Any]:
        """Get value of a filled slot"""
        return self.filled_slots.get(slot_name)
    
    def clear_slots(self):
        """Clear all slots (for new intent)"""
        self.filled_slots.clear()
        self.pending_slots.clear()
    
    def switch_topic(self, new_topic: str):
        """Handle topic switch"""
        if self.current_topic and self.current_topic != new_topic:
            self.topic_history.append(self.current_topic)
            self.context_switches += 1
            logger.info(f"Topic switch: '{self.current_topic}' → '{new_topic}'")
        
        self.current_topic = new_topic
    
    def get_recent_history(self, max_turns: int = 10) -> List[Dict[str, str]]:
        """
        Get recent conversation history formatted for LLM

        Args:
            max_turns: Maximum number of turns to return (default: 10 for better context)

        Returns:
            List of message dicts with role and content
        """
        recent_turns = self.short_term_memory[-max_turns:]
        
        return [
            {
                "role": turn.role,
                "content": turn.content,
                "timestamp": turn.timestamp.isoformat()
            }
            for turn in recent_turns
        ]
    
    def get_context_summary(self) -> str:
        """
        Generate a context summary for LLM prompts

        Returns:
            String summary of current context
        """
        summary_parts = []

        # ✅ MULTILINGUAL: Add language context
        if self.requested_language and self.requested_language != self.detected_language:
            summary_parts.append(f"User speaks {self.detected_language} but requested response in {self.requested_language}")
        elif self.detected_language != "en":
            summary_parts.append(f"Conversation language: {self.detected_language}")

        if self.current_topic:
            summary_parts.append(f"Current topic: {self.current_topic}")

        if self.current_intent:
            summary_parts.append(f"Current intent: {self.current_intent.name} (confidence: {self.current_intent.confidence:.2f})")

        if self.filled_slots:
            slots_str = ", ".join(f"{k}={v}" for k, v in self.filled_slots.items())
            summary_parts.append(f"Known information: {slots_str}")

        if self.pending_slots:
            summary_parts.append(f"Still need: {', '.join(self.pending_slots)}")

        if self.conversation_style != "balanced":
            summary_parts.append(f"User prefers {self.conversation_style} style")

        return ". ".join(summary_parts) if summary_parts else "New conversation"
    
    def should_summarize(self) -> bool:
        """Check if context should be summarized"""
        return len(self.short_term_memory) > 10
    
    def get_stats(self) -> Dict[str, Any]:
        """Get conversation statistics"""
        return {
            "session_id": self.session_id,
            "state": self.current_state,
            "total_turns": self.total_turns,
            "successful_intents": self.successful_intents,
            "clarification_requests": self.clarification_requests,
            "context_switches": self.context_switches,
            "compressions": self.context_window_compressions,
            "conversation_style": self.conversation_style,
            "memory_turns": len(self.short_term_memory),
            "filled_slots": len(self.filled_slots),
            "pending_slots": len(self.pending_slots),
            "duration_minutes": (datetime.utcnow() - self.created_at).total_seconds() / 60
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "session_id": self.session_id,
            "current_state": self.current_state,
            "current_intent": self.current_intent.to_dict() if self.current_intent else None,
            "pending_slots": self.pending_slots,
            "filled_slots": self.filled_slots,
            "topic_history": self.topic_history,
            "current_topic": self.current_topic,
            "context_switches": self.context_switches,
            "short_term_memory": [turn.to_dict() for turn in self.short_term_memory],
            "semantic_memory": self.semantic_memory,
            "user_preferences": self.user_preferences,
            "conversation_style": self.conversation_style,
            "detected_language": self.detected_language,  # ✅ MULTILINGUAL
            "requested_language": self.requested_language,  # ✅ MULTILINGUAL
            "total_turns": self.total_turns,
            "successful_intents": self.successful_intents,
            "clarification_requests": self.clarification_requests,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationContext":
        """Create from dictionary"""
        # Recreate Intent if present
        intent = None
        if data.get("current_intent"):
            intent_data = data["current_intent"]
            intent = Intent(
                name=intent_data["name"],
                confidence=intent_data["confidence"],
                slots=intent_data.get("slots", {}),
                domain=intent_data.get("domain")
            )
        
        # Recreate conversation turns
        turns = []
        for turn_data in data.get("short_term_memory", []):
            turn_intent = None
            if turn_data.get("intent"):
                ti = turn_data["intent"]
                turn_intent = Intent(
                    name=ti["name"],
                    confidence=ti["confidence"],
                    slots=ti.get("slots", {}),
                    domain=ti.get("domain")
                )
            
            turn = ConversationTurn(
                role=turn_data["role"],
                content=turn_data["content"],
                intent=turn_intent,
                metadata=turn_data.get("metadata", {}),
                timestamp=datetime.fromisoformat(turn_data["timestamp"])
            )
            turns.append(turn)
        
        return cls(
            session_id=data["session_id"],
            current_state=DialogueState(data["current_state"]),
            current_intent=intent,
            pending_slots=data.get("pending_slots", []),
            filled_slots=data.get("filled_slots", {}),
            topic_history=data.get("topic_history", []),
            current_topic=data.get("current_topic"),
            context_switches=data.get("context_switches", 0),
            short_term_memory=turns,
            semantic_memory=data.get("semantic_memory", []),
            user_preferences=data.get("user_preferences", {}),
            conversation_style=data.get("conversation_style", "balanced"),
            detected_language=data.get("detected_language", "en"),  # ✅ MULTILINGUAL
            requested_language=data.get("requested_language"),  # ✅ MULTILINGUAL
            total_turns=data.get("total_turns", 0),
            successful_intents=data.get("successful_intents", 0),
            clarification_requests=data.get("clarification_requests", 0),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_activity=datetime.fromisoformat(data["last_activity"])
        )