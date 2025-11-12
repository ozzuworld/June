"""
SIMPLIFIED Webhook Handler
Replaces the complex RealTimeConversationEngine pipeline

Simple flow: STT → SimpleVoiceAssistant → TTS

UPDATED:
- Register participants with ConversationManager
- Mark audio as available when transcripts arrive
"""
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request
from typing import Dict, Any

from ..services.simple_assistant import get_assistant
from ..core.dependencies import get_conversation_manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/webhooks/stt")
async def handle_stt_webhook(request: Request) -> Dict[str, Any]:
    """
    Main STT webhook endpoint
    
    Handles both partial and final transcripts with simple buffering
    ✅ UPDATED: Registers participants with ConversationManager
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

        # Extract audio data if present
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

        # ✅ CRITICAL: Register participant with ConversationManager
        conversation_mgr = get_conversation_manager()
        
        # Register if not already registered
        if not conversation_mgr.is_participant_in_room(session_id, room_name):
            participant = conversation_mgr.register_participant(
                room_name=room_name,
                session_id=session_id,
                identity=session_id,  # Use session_id as identity
                name=payload.get("participant_name")  # Optional display name
            )
            logger.info(f"✅ Registered participant: {session_id[:8]}... in room '{room_name}'")
        
        # Mark participant as connected and publishing audio
        # (if they're sending transcripts, they must be publishing audio)
        conversation_mgr.mark_participant_connected(room_name, session_id)
        
        # Update audio track info (mark as publishing)
        # We don't have the actual track_sid from STT, but we know audio is available
        participant_info = conversation_mgr.get_participant_info(session_id)
        if participant_info and not participant_info.is_publishing_audio:
            # Use a synthetic track_sid for now
            conversation_mgr.update_audio_track(
                room_name=room_name,
                identity=session_id,
                track_sid=f"audio_{session_id[:8]}",
                is_publishing=True
            )
            logger.info(f"🎤 Marked audio as available for {session_id[:8]}...")

        # Get assistant and process
        assistant = get_assistant()

        # Pass to assistant
        result = await assistant.handle_transcript(
            session_id=session_id,
            room_name=room_name,
            text=text,
            is_partial=is_partial,
            audio_data=audio_data,
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
    ✅ UPDATED: Include ConversationManager stats
    """
    try:
        assistant = get_assistant()
        conversation_mgr = get_conversation_manager()
        
        stats = assistant.get_stats()
        conv_stats = conversation_mgr.get_stats()
        
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "mode": "simple_pipeline",
            "description": "Direct STT → LLM → TTS flow",
            "stats": stats,
            "conversation_manager": conv_stats
        }
    except Exception as e:
        logger.error(f"❌ Status error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/sessions/{session_id}/history")
async def clear_session_history(session_id: str):
    """
    Clear conversation history for a session
    ✅ UPDATED: Also clear from ConversationManager
    """
    try:
        assistant = get_assistant()
        conversation_mgr = get_conversation_manager()
        
        assistant.clear_session(session_id)
        conversation_mgr.clear_session(session_id)
        
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