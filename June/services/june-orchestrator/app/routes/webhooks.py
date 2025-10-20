# June/services/june-orchestrator/app/routes/webhooks.py
"""
Webhook handlers for event-driven architecture
STT → Orchestrator (WITH MEMORY) → TTS (via LiveKit room)
"""
import logging
import httpx
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from ..config import config
from ..services.ai_service import generate_response
from ..session_manager import session_manager

logger = logging.getLogger(__name__)
router = APIRouter()


class STTWebhookPayload(BaseModel):
    """Webhook payload from STT service"""
    event: str
    room_name: str
    participant: str
    text: str
    language: Optional[str] = None
    confidence: Optional[float] = None
    timestamp: str
    segments: Optional[List[Dict[str, Any]]] = []


class TTSPublishRequest(BaseModel):
    """Request to publish TTS audio to room"""
    room_name: str
    text: str
    language: str = "en"
    speaker: str = "Claribel Dervla"
    speed: float = 1.0


@router.post("/api/webhooks/stt")
async def handle_stt_webhook(
    payload: STTWebhookPayload,
    authorization: str = Header(None)
):
    """
    Handle transcription webhook from STT service
    
    ✅ FIXED: Now properly uses conversation history!
    
    Flow:
    1. Receive transcription from STT
    2. Get or create session for room (WITH MEMORY)
    3. Load conversation history
    4. Process with AI (with full context)
    5. Save both sides of conversation
    6. Update session metrics
    7. Trigger TTS to speak in the room
    """
    logger.info(f"🎤 STT Webhook: {payload.participant} in {payload.room_name}")
    logger.info(f"💬 Transcription: {payload.text}")
    
    # Verify service token (if configured)
    if hasattr(config.services, 'stt_service_token') and config.services.stt_service_token:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing authorization")
        
        token = authorization.replace("Bearer ", "")
        if token != config.services.stt_service_token:
            raise HTTPException(status_code=401, detail="Invalid token")
    
    try:
        # 🔥 CRITICAL FIX: Get or create session for this room
        logger.info(f"🔍 Looking up session for room: {payload.room_name}")
        session = session_manager.get_or_create_session_for_room(
            room_name=payload.room_name,
            user_id=payload.participant
        )
        logger.info(f"✅ Using session: {session.session_id} (messages: {len(session.conversation_history)})")
        
        # Get conversation history (THIS WAS ALWAYS EMPTY BEFORE!)
        conversation_history = session.get_recent_history()
        
        logger.info(f"📚 Loaded conversation history: {len(conversation_history)} messages")
        if conversation_history:
            # Log last few messages for debugging
            recent_preview = conversation_history[-3:] if len(conversation_history) > 3 else conversation_history
            for msg in recent_preview:
                role = msg.get('role', 'unknown')
                content = msg.get('content', '')[:50]
                logger.info(f"  {role}: {content}...")
        
        # Process transcription with AI (NOW WITH MEMORY!)
        logger.info(f"🤖 Processing with AI (with {len(conversation_history)} history messages)...")
        ai_response, processing_time = await generate_response(
            text=payload.text,
            user_id=payload.participant,
            session_id=session.session_id,
            conversation_history=conversation_history  # ✅ NOW HAS ACTUAL MEMORY!
        )
        
        logger.info(f"✅ AI Response ({processing_time}ms): {ai_response[:100]}...")
        
        # 💾 Save BOTH sides of the conversation to memory
        session_manager.add_to_history(
            session.session_id,
            role="user",
            content=payload.text,
            metadata={
                "confidence": payload.confidence,
                "language": payload.language,
                "timestamp": payload.timestamp
            }
        )
        
        session_manager.add_to_history(
            session.session_id,
            role="assistant",
            content=ai_response,
            metadata={
                "processing_time_ms": processing_time,
                "model": "gemini-2.0-flash-exp"
            }
        )
        
        # 📊 Update session metrics
        session_manager.update_session_metrics(
            session.session_id,
            tokens_used=len(payload.text) // 4 + len(ai_response) // 4,  # Rough estimate
            response_time_ms=processing_time
        )
        
        logger.info(f"💾 Saved conversation exchange to session (total: {len(session.conversation_history)} messages)")
        
        # Trigger TTS to speak in the room
        await trigger_tts_in_room(
            room_name=payload.room_name,
            text=ai_response,
            language=payload.language or "en"
        )
        
        # Get session stats for response
        session_stats = session.to_dict()
        
        return {
            "status": "success",
            "session_id": session.session_id,
            "message_count": session.message_count,
            "ai_response": ai_response,
            "processing_time_ms": processing_time,
            "conversation_length": len(session.conversation_history),
            "session_stats": session_stats
        }
        
    except Exception as e:
        logger.error(f"❌ Webhook processing error: {e}")
        logger.exception("Full traceback:")
        raise HTTPException(status_code=500, detail=str(e))


async def trigger_tts_in_room(
    room_name: str,
    text: str,
    language: str = "en"
):
    """
    Trigger TTS service to speak in the LiveKit room
    
    Args:
        room_name: LiveKit room name
        text: Text to synthesize
        language: Language code
    """
    try:
        tts_url = f"{config.services.tts_base_url}/publish-to-room"
        
        logger.info(f"🔊 Triggering TTS for room: {room_name}")
        logger.info(f"📝 Text length: {len(text)} chars")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                tts_url,
                json={
                    "room_name": room_name,
                    "text": text,
                    "language": language,
                    "speaker": "Claribel Dervla",
                    "speed": 1.0
                }
            )
            
            if response.status_code == 200:
                logger.info(f"✅ TTS triggered successfully")
                result = response.json()
                logger.info(f"📊 TTS result: {result}")
            else:
                logger.error(f"❌ TTS trigger failed: {response.status_code}")
                logger.error(f"Response: {response.text}")
                
    except httpx.TimeoutException:
        logger.error(f"❌ TTS request timed out for room {room_name}")
    except Exception as e:
        logger.error(f"❌ Failed to trigger TTS: {e}")
        logger.exception("Full traceback:")
        # Don't raise - this shouldn't break the webhook


@router.post("/api/tts/publish")
async def publish_tts_to_room(request: TTSPublishRequest):
    """
    Direct endpoint to trigger TTS in a room
    (Can be called by external services or frontend)
    """
    logger.info(f"🔊 Publishing TTS to room: {request.room_name}")
    
    await trigger_tts_in_room(
        room_name=request.room_name,
        text=request.text,
        language=request.language
    )
    
    return {
        "status": "success",
        "room_name": request.room_name,
        "text_length": len(request.text)
    }


@router.get("/api/sessions/stats")
async def get_sessions_stats():
    """Get overall session statistics"""
    stats = session_manager.get_stats()
    
    return {
        "status": "success",
        "stats": stats
    }


@router.get("/api/sessions/{session_id}/history")
async def get_session_history(session_id: str, max_messages: int = 50):
    """Get conversation history for a session"""
    session = session_manager.get_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    history = session.get_recent_history(max_messages)
    
    return {
        "status": "success",
        "session_id": session_id,
        "history": history,
        "total_messages": len(session.conversation_history),
        "session_info": session.to_dict()
    }


@router.post("/api/sessions/{session_id}/clear")
async def clear_session_history(session_id: str):
    """Clear conversation history for a session (keep session alive)"""
    session = session_manager.get_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    old_count = len(session.conversation_history)
    session.conversation_history = []
    session.message_count = 0
    
    logger.info(f"🧹 Cleared {old_count} messages from session {session_id}")
    
    return {
        "status": "success",
        "session_id": session_id,
        "cleared_messages": old_count,
        "message": "Conversation history cleared"
    }