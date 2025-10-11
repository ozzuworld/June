"""
Chat Endpoints
"""
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException

from ..models import ChatRequest, ChatResponse
from ..dependencies import simple_auth, get_current_user
from ..services import ai_service, tts_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    auth_data: dict = Depends(simple_auth)
):
    """
    Chat with AI assistant
    Optional audio response
    """
    try:
        user_id = await get_current_user(auth_data)
        
        logger.info(f"Chat request from {user_id}: {request.text[:50]}...")
        
        start_time = datetime.utcnow()
        
        # Generate AI response
        ai_text = await ai_service.generate_response(
            text=request.text,
            user_id=user_id,
            temperature=request.temperature
        )
        
        response_data = {
            "message": {
                "text": ai_text,
                "user_id": user_id
            }
        }
        
        # Generate audio if requested
        if request.include_audio:
            audio_bytes = await tts_service.synthesize_binary(
                text=ai_text,
                user_id=user_id,
                language=request.language
            )
            
            if audio_bytes:
                response_data["audio"] = {
                    "format": "wav",
                    "size_bytes": len(audio_bytes),
                    "data": audio_bytes.hex()  # or base64
                }
        
        # Calculate response time
        end_time = datetime.utcnow()
        response_time_ms = int((end_time - start_time).total_seconds() * 1000)
        
        return ChatResponse(
            message=response_data["message"],
            audio=response_data.get("audio"),
            response_time_ms=response_time_ms,
            timestamp=end_time
        )
        
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))