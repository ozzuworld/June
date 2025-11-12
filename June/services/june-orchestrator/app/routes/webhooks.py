"""
SIMPLIFIED Webhook Handler
Replaces the complex RealTimeConversationEngine pipeline

Simple flow: STT → SimpleVoiceAssistant → TTS
"""
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request
from typing import Dict, Any

from ..services.simple_assistant import get_assistant

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/webhooks/stt")
async def handle_stt_webhook(request: Request) -> Dict[str, Any]:
    """
    Main STT webhook endpoint
    
    Handles both partial and final transcripts with simple buffering
    """
    try:
        # Parse payload
        payload = await request.json()

        # Log incoming payload
        logger.debug(f"📥 Received payload: {payload}")

        # Extract fields (handles various STT formats)
        session_id = payload.get("participant") or payload.get("session_id") or "unknown"
        room_name = payload.get("room_name") or payload.get("roomName") or "unknown"

        # Get text from various possible fields
        text = (
            payload.get("text")
            or payload.get("transcript")
            or payload.get("final_text")
            or payload.get("content")
            or ""
        ).strip()

        # Determine if partial
        is_partial = (
            payload.get("partial", False)
            or payload.get("is_partial", False)
            or payload.get("event") == "partial"
            or payload.get("type") == "partial"
        )

        # ✅ ADD: Extract audio data
        audio_data = payload.get("audio_data")
        if audio_data and isinstance(audio_data, str):
            try:
                import base64
                audio_data = base64.b64decode(audio_data)
            except Exception as e:
                logger.warning(f"⚠️ Failed to base64-decode audio_data: {e}")
                audio_data = None

        # Validate input
        if not text:
            logger.warning("⚠️ Empty text received, skipping")
            return {
                "status": "skipped",
                "reason": "empty_text",
                "timestamp": datetime.utcnow().isoformat()
            }

        if not room_name or room_name == "unknown":
            logger.error(f"❌ Invalid room_name: {room_name}")
            raise HTTPException(status_code=400, detail="room_name is required")

        # Log incoming request
        status_label = "PARTIAL" if is_partial else "FINAL"
        logger.info(
            f"📥 [{status_label}] "
            f"Session: {session_id[:8]}... "
            f"Room: {room_name} "
            f"Text: '{text[:50]}...'"
        )

        # Get assistant and process
        assistant = get_assistant()

        # ✅ UPDATE: Pass audio to assistant
        result = await assistant.handle_transcript(
            session_id=session_id,
            room_name=room_name,
            text=text,
            is_partial=is_partial,
            audio_data=audio_data,  # ← NEW
        )

        # Add metadata to response
        result["timestamp"] = datetime.utcnow().isoformat()
        result["session_id"] = session_id
        result["room_name"] = room_name

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal error: {str(e)}"
        )



@router.post("/api/webhooks/voice_onset")
async def handle_voice_onset(request: Request):
    """
    Handle user interruptions (voice onset detection)
    
    Called when user starts speaking while assistant is talking
    """
    try:
        payload = await request.json()
        
        session_id = payload.get("session_id") or payload.get("participant")
        room_name = payload.get("room_name") or payload.get("roomName")
        
        if not session_id or not room_name:
            raise HTTPException(
                status_code=400,
                detail="session_id and room_name are required"
            )
        
        logger.info(f"🛑 Voice onset detected: {session_id[:8]}... in room {room_name}")
        
        # Handle interruption
        assistant = get_assistant()
        result = await assistant.handle_interruption(session_id, room_name)
        
        result["timestamp"] = datetime.utcnow().isoformat()
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Voice onset error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/streaming/status")
async def get_streaming_status():
    """
    Get assistant status and statistics
    """
    try:
        assistant = get_assistant()
        stats = assistant.get_stats()
        
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "mode": "simple_pipeline",
            "description": "Direct STT → LLM → TTS flow",
            "stats": stats
        }
    except Exception as e:
        logger.error(f"❌ Status error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/sessions/{session_id}/history")
async def clear_session_history(session_id: str):
    """
    Clear conversation history for a session
    """
    try:
        assistant = get_assistant()
        assistant.clear_session(session_id)
        
        return {
            "status": "success",
            "message": f"History cleared for session {session_id}",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"❌ Clear history error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/sessions/{session_id}/history")
async def get_session_history(session_id: str):
    """
    Get conversation history for a session
    """
    try:
        assistant = get_assistant()
        history = assistant.history.get_history(session_id)
        
        return {
            "status": "success",
            "session_id": session_id,
            "message_count": len(history),
            "history": history,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"❌ Get history error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))