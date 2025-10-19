# June/services/june-orchestrator/app/routes/webhooks.py
"""
Webhook handlers for event-driven architecture
STT → Orchestrator → TTS (via LiveKit room)
"""
import logging
import httpx
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from ..config import config
from ..services.ai_service import generate_response

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
    
    Flow:
    1. Receive transcription from STT
    2. Process with AI (Gemini)
    3. Trigger TTS to speak in the room
    """
    logger.info(f"🎤 STT Webhook: {payload.participant} in {payload.room_name}")
    logger.info(f"💬 Transcription: {payload.text}")
    
    # Verify service token (if configured)
    if config.services.stt_service_token:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing authorization")
        
        token = authorization.replace("Bearer ", "")
        if token != config.services.stt_service_token:
            raise HTTPException(status_code=401, detail="Invalid token")
    
    try:
        # Process transcription with AI
        logger.info(f"🤖 Processing with AI...")
        ai_response, processing_time = await generate_response(
            text=payload.text,
            user_id=payload.participant,
            session_id=payload.room_name,
            conversation_history=[]  # Could maintain history per room
        )
        
        logger.info(f"✅ AI Response ({processing_time}ms): {ai_response[:100]}...")
        
        # Trigger TTS to speak in the room
        await trigger_tts_in_room(
            room_name=payload.room_name,
            text=ai_response,
            language=payload.language or "en"
        )
        
        return {
            "status": "success",
            "ai_response": ai_response,
            "processing_time_ms": processing_time
        }
        
    except Exception as e:
        logger.error(f"❌ Webhook processing error: {e}")
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
            else:
                logger.error(f"❌ TTS trigger failed: {response.status_code}")
                logger.error(f"Response: {response.text}")
                
    except Exception as e:
        logger.error(f"❌ Failed to trigger TTS: {e}")
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


# Add to main.py
"""
# In June/services/june-orchestrator/app/main.py

from .routes.webhooks import router as webhooks_router

app.include_router(webhooks_router, tags=["Webhooks"])
"""