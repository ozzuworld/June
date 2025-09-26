# June/services/june-orchestrator/routers/conversation_routes.py
# UPDATED for low-latency TTS

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Dict, Any, Optional
import logging
import hashlib
import time

from shared import require_user_auth, extract_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["Conversation"])

class ConversationInput(BaseModel):
    text: str
    language: str = "en"
    voice_id: Optional[str] = "default"
    metadata: dict = {}

class ConversationOutput(BaseModel):
    ok: bool = True
    message: dict
    conversation_id: Optional[str] = None
    # NEW: TTS information for frontend
    tts: Optional[dict] = None

@router.post("/chat", response_model=ConversationOutput)
async def chat(
    payload: ConversationInput,
    user_payload: Dict[str, Any] = Depends(require_user_auth)
):
    """Process chat with direct TTS URL for low latency"""
    
    try:
        user_id = extract_user_id(user_payload)
        logger.info(f"📨 Chat request from user: {user_id}")
        
        # Generate AI response (your existing logic)
        user_text = payload.text.lower()
        if "hello" in user_text or "hi" in user_text:
            ai_response = "Hello! I'm OZZU, your AI assistant. How can I help you today?"
        elif "weather" in user_text:
            ai_response = "I'd be happy to help with weather information, but I don't have access to current weather data yet. Is there anything else I can help you with?"
        else:
            ai_response = f"I understand you're asking about: '{payload.text}'. I'm here to help! What would you like to know more about?"

        # Generate TTS URL for direct frontend access
        tts_info = None
        if ai_response:
            # Create unique TTS request ID
            tts_request_id = hashlib.md5(
                f"{ai_response}{payload.voice_id}{time.time()}".encode()
            ).hexdigest()[:16]
            
            tts_info = {
                "url": f"https://tts.allsafe.world/tts/generate",
                "method": "POST",
                "headers": {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {user_payload.get('access_token', '')}"
                },
                "payload": {
                    "text": ai_response,
                    "language": payload.language,
                    "voice_id": payload.voice_id,
                    "format": "wav",
                    "speed": 1.0,
                    "request_id": tts_request_id
                },
                "request_id": tts_request_id
            }

        logger.info(f"🤖 AI response: {ai_response}")
        logger.info(f"🎵 TTS URL provided for direct frontend access")

        return ConversationOutput(
            ok=True,
            message={
                "text": ai_response,
                "role": "assistant",
                "type": "text"
            },
            conversation_id=f"conv_{user_id}",
            tts=tts_info  # Frontend can use this directly
        )
        
    except Exception as e:
        logger.error(f"❌ Chat processing failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e

# NEW: Endpoint to get TTS URL without full conversation
@router.post("/tts/url")
async def get_tts_url(
    request: dict,
    user_payload: Dict[str, Any] = Depends(require_user_auth)
):
    """Get TTS URL for direct frontend access"""
    
    text = request.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="Text is required")
    
    # Generate unique request ID
    request_id = hashlib.md5(f"{text}{time.time()}".encode()).hexdigest()[:16]
    
    return {
        "tts_url": "https://tts.allsafe.world/tts/generate",
        "method": "POST",
        "headers": {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {user_payload.get('access_token', '')}"
        },
        "payload": {
            "text": text,
            "language": request.get("language", "en"),
            "voice_id": request.get("voice_id", "default"),
            "format": "wav",
            "speed": request.get("speed", 1.0),
            "request_id": request_id
        },
        "request_id": request_id
    }