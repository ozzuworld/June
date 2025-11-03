"""Add streaming natural chat endpoint with phrase-level TTS publish"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import logging
import asyncio

from ..core.dependencies import (
    get_current_user,
    natural_conversation_processor_dependency,
    emotion_service_dependency,
    conversation_processor_dependency,
    session_service_dependency,
)
from ..services.streaming_service import streaming_ai_service
from ..services.tts_service import tts_service

logger = logging.getLogger(__name__)
router = APIRouter()

class ChatMessage(BaseModel):
    session_id: str
    message: str
    audio_data: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    conversation_state: str
    context_references: List[str] = []
    followup_suggestions: List[str] = []
    topics_discussed: List[str] = []
    response_metadata: Dict[str, Any] = {}

@router.post("/chat/natural", response_model=ChatResponse)
async def chat_conversation_natural(
    chat_request: ChatMessage,
    processor = Depends(natural_conversation_processor_dependency),
    emotion = Depends(emotion_service_dependency),
    convo = Depends(conversation_processor_dependency),
    sessions = Depends(session_service_dependency),
    current_user: dict = Depends(get_current_user)
):
    try:
        # Determine room from session
        room_name = sessions.get_room_for_session(chat_request.session_id) if hasattr(sessions, 'get_room_for_session') else chat_request.session_id

        # Emotion from optional audio
        emotion_ctx: Dict[str, Any] = {}
        if chat_request.audio_data:
            emotion_ctx = await emotion.analyze_voice_emotion(
                chat_request.audio_data, chat_request.session_id, chat_request.message
            )

        # Build conversation history from session processor
        history = convo.session_service.get_history(chat_request.session_id) if hasattr(convo, 'session_service') else []

        # TTS callback publishes each phrase chunk immediately to room
        async def tts_callback(phrase: str):
            try:
                await tts_service.publish_to_room(
                    room_name=room_name,
                    text=phrase,
                    language="en",
                    speaker=None,
                    voice_id=None,
                    speed=1.0,
                )
            except Exception as e:
                logger.warning(f"TTS publish error: {e}")

        # Start streaming AI and concurrently speak phrases
        collected_text: List[str] = []
        async for token in streaming_ai_service.generate_streaming_response(
            text=chat_request.message,
            conversation_history=history,
            user_id=current_user.get("sub","user"),
            session_id=chat_request.session_id,
            tts_callback=tts_callback,
        ):
            collected_text.append(token)

        full_text = "".join(collected_text).strip()
        if not full_text:
            full_text = "OK."

        # Adapt final text to emotion
        adapted = emotion.adapt_response_for_emotion(
            full_text,
            (emotion_ctx or {}).get("emotion", "neutral"),
            (emotion_ctx or {}).get("confidence", 0.5),
        )

        return ChatResponse(
            response=adapted["adapted_response"],
            conversation_state="active",
            context_references=[],
            followup_suggestions=[],
            topics_discussed=[],
            response_metadata={"streaming": True},
        )
    except Exception as e:
        logger.error(f"[CHAT/NATURAL] streaming error: {e}")
        raise HTTPException(status_code=500, detail=f"Natural streaming failed: {str(e)}")
