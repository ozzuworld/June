"""AI processing routes - updated to use SessionService instead of legacy session_manager"""
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
    Process text with AI and generate TTS (streaming via Chatterbox)
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

        # Stream TTS to LiveKit room using canonical endpoint
        ok = await tts_service.publish_to_room(
            room_name=session.room_name,
            text=ai_text,
            language=request.language,
            predefined_voice_id=None,   # set if you want a specific built-in voice
            voice_reference=None,       # set if you want cloning
            speed=1.0,
            emotion_level=0.5,
            temperature=0.9,
            cfg_weight=0.3,
            seed=None
        )

        if not ok:
            logger.warning("TTS publish_to_room returned False")

        return AIResponse(
            session_id=request.session_id,
            text=ai_text,
            audio_url=None,              # Streaming; no file URL
            processing_time_ms=processing_time
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI processing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
