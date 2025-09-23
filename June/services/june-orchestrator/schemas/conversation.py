from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class ConversationInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: Optional[str] = None
    audio_b64: Optional[str] = None
    language: str = "en"
    voice_id: Optional[str] = None
    tool_hints: Optional[List[str]] = None
    metadata: dict = Field(default_factory=dict)


class MessageArtifact(BaseModel):
    id: str
    role: str
    text: Optional[str] = None
    audio_url: Optional[str] = None


class ConversationOutput(BaseModel):
    ok: bool
    conversation_id: Optional[str] = None
    message: Optional[MessageArtifact] = None
    used_tools: Optional[List[str]] = None
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
