"""Add natural chat endpoint that uses NaturalConversationProcessor and Emotion service"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import logging

from ..services.conversational_ai_processor import (
    ConversationalAIProcessor,
    ConversationRequest,
    ConversationResponse
)
from ..services.conversation_memory_service import ConversationMemoryService
from ..core.dependencies import (
    conversational_ai_processor_dependency,
    conversation_memory_service_dependency,
    get_current_user,
    natural_conversation_processor_dependency,
    emotion_service_dependency,
)

logger = logging.getLogger(__name__)
router = APIRouter()

class ChatMessage(BaseModel):
    session_id: str
    message: str
    audio_data: Optional[str] = None
    context_hint: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    conversation_state: str
    context_references: List[str] = []
    followup_suggestions: List[str] = []
    topics_discussed: List[str] = []
    response_metadata: Dict[str, Any] = {}

# --- existing handlers (kept) ---
# (file content omitted here for brevity)

# --- NEW: Natural chat endpoint ---
@router.post("/chat/natural", response_model=ChatResponse)
async def chat_conversation_natural(
    chat_request: ChatMessage,
    processor = Depends(natural_conversation_processor_dependency),
    emotion = Depends(emotion_service_dependency),
    current_user: dict = Depends(get_current_user)
):
    try:
        emotion_ctx = {}
        if chat_request.audio_data:
            emotion_ctx = await emotion.analyze_voice_emotion(
                chat_request.audio_data, chat_request.session_id, chat_request.message
            )
        result = await processor.process_natural_conversation(
            session_id=chat_request.session_id,
            user_message=chat_request.message,
            audio_context=emotion_ctx or None,
        )
        adapted = emotion.adapt_response_for_emotion(
            result["response"],
            (emotion_ctx or {}).get("emotion", "neutral"),
            (emotion_ctx or {}).get("confidence", 0.5),
        )
        return ChatResponse(
            response=adapted["adapted_response"],
            conversation_state=result.get("conversation_state", "active"),
            context_references=result.get("context_used", [])[:3],
            followup_suggestions=result.get("follow_up_suggestions", [])[:3],
            topics_discussed=result.get("topics_discussed", []),
            response_metadata=result.get("response_metadata", {}),
        )
    except Exception as e:
        logger.error(f"[CHAT/NATURAL] Error: {e}")
        raise HTTPException(status_code=500, detail=f"Natural conversation failed: {str(e)}")
