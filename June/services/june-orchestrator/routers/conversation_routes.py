# routers/conversation_routes.py - WORKING VERSION
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import logging

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

@router.get("/ping")
async def ping():
    return {"ok": True, "service": "june-orchestrator", "status": "healthy"}

@router.get("/whoami")
async def whoami(user_payload: Dict[str, Any] = Depends(require_user_auth)):
    """Get current authenticated user information"""
    user_id = extract_user_id(user_payload)
    username = user_payload.get("preferred_username") or user_payload.get("username")
    
    return {
        "ok": True, 
        "subject": username,
        "user_id": user_id,
        "token_present": True
    }

@router.post("/chat", response_model=ConversationOutput)
async def chat(
    payload: ConversationInput,
    user_payload: Dict[str, Any] = Depends(require_user_auth)
):
    """Process a chat message with proper authentication"""
    
    try:
        user_id = extract_user_id(user_payload)
        logger.info(f"📨 Chat request from user: {user_id}")
        logger.info(f"💬 User message: {payload.text}")
        
        # Simple AI response logic
        user_text = payload.text.lower()
        if "hello" in user_text or "hi" in user_text:
            ai_response = "Hello! I'm OZZU, your AI assistant. How can I help you today?"
        elif "weather" in user_text:
            ai_response = "I'd be happy to help with weather information, but I don't have access to current weather data yet. Is there anything else I can help you with?"
        elif "time" in user_text:
            from datetime import datetime
            current_time = datetime.now().strftime("%I:%M %p")
            ai_response = f"The current time is {current_time}."
        else:
            ai_response = f"I understand you're asking about: '{payload.text}'. I'm here to help! While I'm still learning, I can have conversations and answer questions. What would you like to know more about?"

        logger.info(f"🤖 AI response: {ai_response}")

        return ConversationOutput(
            ok=True,
            message={
                "text": ai_response,
                "role": "assistant",
                "type": "text"
            },
            conversation_id=f"conv_{user_id}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Chat processing failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e