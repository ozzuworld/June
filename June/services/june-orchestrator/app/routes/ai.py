"""AI processing routes"""
import logging
from fastapi import APIRouter, HTTPException

from ..models import AIRequest, AIResponse
from ..session_manager import session_manager
from ..services.ai_service import generate_response
from ..services.tts_service import synthesize_speech

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/process", response_model=AIResponse)
async def process_with_ai(request: AIRequest):
    """
    Process text with AI and generate TTS
    
    This is called by:
    - STT service after transcription
    - Direct API calls
    """
    try:
        # Get session
        session = session_manager.get_session(request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Add user message to history
        session_manager.add_to_history(
            request.session_id,
            role="user",
            content=request.text
        )
        
        # Generate AI response
        ai_text, processing_time = await generate_response(
            text=request.text,
            user_id=session.user_id,
            session_id=request.session_id,
            conversation_history=session.conversation_history
        )
        
        # Add AI response to history
        session_manager.add_to_history(
            request.session_id,
            role="assistant",
            content=ai_text
        )
        
        # Generate TTS (optional)
        audio_url = None
        audio_bytes = await synthesize_speech(
            text=ai_text,
            language=request.language
        )
        
        if audio_bytes:
            # In production, upload to storage and return URL
            # For now, just indicate it's available
            audio_url = f"/api/audio/{request.session_id}/latest"
        
        return AIResponse(
            session_id=request.session_id,
            text=ai_text,
            audio_url=audio_url,
            processing_time_ms=processing_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI processing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))