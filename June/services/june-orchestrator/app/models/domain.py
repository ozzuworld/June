"""Domain models for the June Orchestrator"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
import uuid


class Message(BaseModel):
    """Single conversation message"""
    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SkillSession(BaseModel):
    """Skill state management for individual sessions"""
    active_skill: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    turn_count: int = 0
    activated_at: Optional[datetime] = None
    waiting_for_input: bool = False
    
    def activate_skill(self, skill_name: str):
        """Activate a skill"""
        self.active_skill = skill_name
        self.context = {}
        self.turn_count = 0
        self.activated_at = datetime.utcnow()
        self.waiting_for_input = True
    
    def deactivate_skill(self):
        """Deactivate current skill"""
        self.active_skill = None
        self.context = {}
        self.turn_count = 0
        self.activated_at = None
        self.waiting_for_input = False
    
    def increment_turn(self):
        """Increment skill turn counter"""
        self.turn_count += 1
    
    def is_active(self) -> bool:
        """Check if a skill is currently active"""
        return self.active_skill is not None


class Session(BaseModel):
    """Clean session model with conversation memory"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    room_name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_activity: datetime = Field(default_factory=datetime.utcnow)
    status: str = "active"
    messages: List[Message] = Field(default_factory=list)
    access_token: Optional[str] = None
    
    # Metrics
    message_count: int = 0
    total_tokens_used: int = 0
    avg_response_time_ms: int = 0
    
    # Context management
    context_summary: Optional[str] = None
    max_history_messages: int = 20
    
    # Skill state
    skill_session: SkillSession = Field(default_factory=SkillSession)
    
    @classmethod
    def create(cls, user_id: str, room_name: Optional[str] = None) -> "Session":
        """Create new session"""
        if not room_name:
            room_name = f"room-{user_id}-{uuid.uuid4().hex[:8]}"
        
        return cls(user_id=user_id, room_name=room_name)
    
    def update_activity(self):
        """Update last activity timestamp"""
        self.last_activity = datetime.utcnow()
    
    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None):
        """Add message to conversation history with metadata"""
        message = Message(
            role=role,
            content=content,
            metadata=metadata or {}
        )
        self.messages.append(message)
        self.message_count += 1
        self.update_activity()
    
    def get_recent_history(self, max_messages: Optional[int] = None) -> List[Dict]:
        """Get recent conversation history"""
        max_msg = max_messages or self.max_history_messages
        
        # Always include context summary if it exists
        history = []
        if self.context_summary:
            history.append({
                "role": "system",
                "content": self.context_summary
            })
        
        # Add recent messages
        recent_messages = self.messages[-max_msg:]
        for msg in recent_messages:
            history.append({
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
                "metadata": msg.metadata
            })
        
        return history
    
    def should_summarize(self) -> bool:
        """Check if conversation should be summarized"""
        return len(self.messages) > self.max_history_messages
    
    def is_expired(self, timeout_hours: int = 24) -> bool:
        """Check if session has expired"""
        expiry_time = self.last_activity + timedelta(hours=timeout_hours)
        return datetime.utcnow() > expiry_time
    
    def update_metrics(self, tokens_used: int = 0, response_time_ms: int = 0):
        """Update session metrics"""
        self.total_tokens_used += tokens_used
        
        # Update average response time
        if response_time_ms > 0:
            if self.avg_response_time_ms == 0:
                self.avg_response_time_ms = response_time_ms
            else:
                # Running average
                self.avg_response_time_ms = int(
                    (self.avg_response_time_ms + response_time_ms) / 2
                )


class SessionStats(BaseModel):
    """Session manager statistics"""
    active_sessions: int
    active_rooms: int
    total_sessions_created: int
    total_messages: int
    total_tokens: int
    avg_messages_per_session: float
    active_skills: int
    skills_in_use: Dict[str, int]


class UtteranceState(BaseModel):
    """Track the natural progression of an utterance"""
    participant: str
    utterance_id: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    last_partial_at: datetime = Field(default_factory=datetime.utcnow)
    partials: List[str] = Field(default_factory=list)
    processing_started: bool = False
    last_significant_length: int = 0
    pause_detected: bool = False
    
    def add_partial(self, text: str, sequence: int, confidence: float = 0.0) -> bool:
        """Add partial and return if this represents significant progress"""
        now = datetime.utcnow()
        self.last_partial_at = now
        
        # Only add if significantly different from last
        if not self.partials or len(text) > len(self.partials[-1]) + 3:
            self.partials.append(text)
            return True
        return False
    
    def get_current_text(self) -> str:
        """Get the most recent partial text"""
        return self.partials[-1] if self.partials else ""
    
    def mark_processing_started(self):
        """Mark that LLM processing has started for this utterance"""
        self.processing_started = True
    
    def is_expired(self, timeout_seconds: int = 30) -> bool:
        """Check if this utterance state has expired"""
        age = (datetime.utcnow() - self.started_at).total_seconds()
        return age > timeout_seconds