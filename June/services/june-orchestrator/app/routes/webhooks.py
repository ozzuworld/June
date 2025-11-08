"""Streamlined webhook routes - Single path, no duplication

REMOVED:
- Conversation processor (redundant with RT engine)
- Preprocessing (causing Redis errors)
- Complex routing logic
- Natural flow detection (RT engine handles this)
"""
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Request

from ..models.requests import STTWebhookPayload
from ..models.responses import WebhookResponse
from ..core.dependencies import session_service_dependency
from ..services.real_time_conversation_engine import RealTimeConversationEngine
from ..services.streaming_service import streaming_ai_service
from ..services.tts_service import tts_service

logger = logging.getLogger(__name__)
router = APIRouter()

# Single global RT engine instance
_rt_engine: RealTimeConversationEngine | None = None

def get_rt_engine() -> RealTimeConversationEngine:
    global _rt_engine
    if _rt_engine is None:
        _rt_engine = RealTimeConversationEngine(
            redis_client=None,  # Disable Redis preprocessing
            tts_service=tts_service,
            streaming_ai_service=streaming_ai_service
        )
        logger.info("✅ RT engine initialized (Redis disabled)")
    return _rt_engine


@router.post("/api/webhooks/stt", response_model=WebhookResponse)
async def handle_stt_webhook(
    request: Request,
    sessions = Depends(session_service_dependency)
) -> WebhookResponse:
    """Single entry point - all STT goes through RT engine only"""
    
    # Get raw payload for debugging
    raw_body = await request.json()
    logger.info(f"📥 RAW WEBHOOK PAYLOAD: {raw_body}")
    
    # Parse into model
    try:
        payload = STTWebhookPayload(**raw_body)
    except Exception as e:
        logger.error(f"❌ Failed to parse payload: {e}")
        logger.error(f"Raw payload keys: {raw_body.keys()}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")
    
    logger.info(f"🎤️ STT webhook: {payload.participant} -> {payload.room_name}")
    logger.info(f"📝 Payload fields: text={payload.text}, event={payload.event}, partial={payload.partial}")
    
    # Extract text from various possible fields
    text = (
        getattr(payload, 'text', '') or
        getattr(payload, 'transcript', '') or
        getattr(payload, 'final_text', '') or
        ''
    ).strip()
    
    logger.info(f"📝 EXTRACTED TEXT: '{text}' (length: {len(text)})")
    
    # Determine if partial
    is_partial = (
        getattr(payload, 'partial', False) or
        getattr(payload, 'is_partial', False) or
        payload.event in ['partial', 'interim']
    )
    
    logger.info(f"🔍 IS_PARTIAL: {is_partial}, EVENT: {payload.event}")
    
    # Skip ONLY completely empty input
    if not text:
        logger.warning(f"⚠️ SKIPPING: Empty text")
        return WebhookResponse(
            status="skipped", 
            message="Empty input",
            success=True
        )
    
    # CHANGED: Allow short text - let RT engine decide what to do with it
    if len(text) < 2:
        logger.info(f"⚠️ Very short text ({len(text)} chars): '{text}' - processing anyway")
    
    # Route EVERYTHING through RT engine
    try:
        logger.info(f"🚀 CALLING RT ENGINE with text: '{text}'")
        rt_engine = get_rt_engine()
        result = await rt_engine.handle_user_input(
            session_id=payload.participant,
            room_name=payload.room_name,
            text=text,
            audio_data=getattr(payload, 'audio_data', None),
            is_partial=is_partial
        )
        
        logger.info(f"✅ RT ENGINE RESULT: {result}")
        
        status = "partial_processed" if is_partial else "response_generated"
        
        return WebhookResponse(
            status=status,
            message=f"Processed in {result.get('first_phrase_time_ms', 0):.0f}ms",
            success='error' not in result,
            processing_time=result.get('total_time_ms', 0),
            metadata={
                "engine": "real_time_only",
                "phrases_sent": result.get('phrases_sent', 0)
            }
        )
        
    except Exception as e:
        logger.exception(f"❌ STT webhook failed: {e}")
        raise HTTPException(status_code=500, detail="Processing failed")


@router.post("/api/webhooks/voice_onset")
async def handle_voice_onset(payload: dict):
    """Handle interruptions"""
    try:
        session_id = payload.get("session_id")
        room_name = payload.get("room_name")
        
        if not session_id or not room_name:
            raise HTTPException(400, "session_id and room_name required")
        
        rt_engine = get_rt_engine()
        result = await rt_engine.handle_voice_onset(session_id, room_name)
        
        return {
            "status": "interrupted",
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat(),
            "result": result
        }
        
    except Exception as e:
        logger.error(f"❌ Voice onset failed: {e}")
        raise HTTPException(500, "Interrupt failed")


@router.get("/api/streaming/status")
async def get_streaming_status():
    """Simple status endpoint"""
    try:
        rt_engine = get_rt_engine()
        return {
            "engine": "real_time_only",
            "stats": rt_engine.get_global_stats(),
            "simplified": True
        }
    except Exception as e:
        logger.error(f"❌ Status error: {e}")
        raise HTTPException(500, "Status unavailable")