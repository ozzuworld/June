# June/services/june-orchestrator/schemas/conversation.py - VERIFIED VERSION
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class ConversationInput(BaseModel):
    """Input schema matching mobile app payload"""
    model_config = ConfigDict(extra="ignore")
    
    # Mobile app sends 'text' field (not 'user_input')
    text: Optional[str] = None
    audio_b64: Optional[str] = None
    language: str = "en"
    voice_id: Optional[str] = "default"
    tool_hints: Optional[List[str]] = None
    metadata: dict = Field(default_factory=dict)


class MessageArtifact(BaseModel):
    """Response message structure"""
    id: str
    role: str  # "assistant", "user", etc.
    text: Optional[str] = None
    audio_url: Optional[str] = None


class ConversationOutput(BaseModel):
    """Response schema for conversation endpoint"""
    ok: bool
    conversation_id: Optional[str] = None
    message: Optional[MessageArtifact] = None
    used_tools: Optional[List[str]] = None
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

# Alternative response format that mobile app might expect
class SimpleConversationOutput(BaseModel):
    """Simplified response format"""
    ok: bool = True
    message: dict
    conversation_id: Optional[str] = None