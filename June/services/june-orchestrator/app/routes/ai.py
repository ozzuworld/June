"""AI processing routes - XTTS voice integration"""
import logging
from fastapi import APIRouter, HTTPException, Depends

from ..models import AIRequest, AIResponse
from ..core.dependencies import get_session_service
from ..services.ai_service import generate_response
from ..services.tts_service import tts_service

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/process", response_model=AIResponse)
async def process_with_ai(request: AIRequest, session_service = Depends(get_session_service)):
    """
    Process text with AI and generate XTTS audio
    - Called by STT service after transcription
    - Or direct API calls
    """
    try:
        # Get session
        session = session_service.get_session(request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Add user message to history
        session_service.add_message(
            request.session_id,
            role="user",
            content=request.text
        )

        # Generate AI response
        ai_text, processing_time = await generate_response(
            text=request.text,
            user_id=session.user_id,
            session_id=request.session_id,
            conversation_history=session.get_recent_history()
        )

        # Add AI response to history
        session_service.add_message(
            request.session_id,
            role="assistant",
            content=ai_text
        )

        # ✅ CHANGED: Use voice_id instead of language
        # Get voice_id from request or use default
        voice_id = getattr(request, 'voice_id', 'default')
        
        # Stream XTTS to LiveKit room
        ok = await tts_service.publish_to_room(
            room_name=session.room_name,
            text=ai_text,
            voice_id=voice_id,  # ✅ CHANGED: voice_id parameter
            streaming=True
        )

        if not ok:
            logger.warning("XTTS publish_to_room returned False")

        return AIResponse(
            session_id=request.session_id,
            text=ai_text,
            audio_url=None,  # Streaming; no file URL
            processing_time_ms=processing_time
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI processing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))