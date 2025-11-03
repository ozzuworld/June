"""Phase 2: Enhanced webhook routes with SOTA real-time conversation engine

Fixed STT payload normalization and routing to real-time engine.
"""
import logging
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends

from ..models.requests import STTWebhookPayload
from ..models.responses import WebhookResponse
from ..core.dependencies import (
    conversation_processor_dependency,
    get_redis_client,
    session_service_dependency
)
from ..services.conversation.processor import ConversationProcessor
from ..services.real_time_conversation_engine import RealTimeConversationEngine
from ..services.streaming_service import streaming_ai_service
from ..services.tts_service import tts_service

logger = logging.getLogger(__name__)
router = APIRouter()

# Global real-time engine instance
_rt_engine: Optional[RealTimeConversationEngine] = None

def get_rt_engine() -> RealTimeConversationEngine:
    """Get real-time conversation engine singleton"""
    global _rt_engine
    if _rt_engine is None:
        _rt_engine = RealTimeConversationEngine(
            redis_client=get_redis_client(),
            tts_service=tts_service,
            streaming_ai_service=streaming_ai_service
        )
        logger.info("✅ Real-time conversation engine initialized")
    return _rt_engine


def extract_text_and_flags(payload: STTWebhookPayload) -> Dict[str, Any]:
    """Normalize STT payload fields to standard format"""
    # Extract text from various possible field names
    text = (
        getattr(payload, 'text', '') or
        getattr(payload, 'transcript', '') or
        getattr(payload, 'final_text', '') or
        getattr(payload, 'partial_text', '') or
        getattr(payload, 'message', '') or
        ''
    ).strip()
    
    # Determine if partial
    is_partial = (
        getattr(payload, 'partial', False) or
        getattr(payload, 'is_partial', False) or
        payload.event in ['partial', 'interim'] or
        not getattr(payload, 'is_final', True)
    )
    
    # Only process if we have meaningful text
    meaningful = len(text) >= 2 and text not in ['', '.', '?', '!']
    
    return {
        'text': text,
        'is_partial': is_partial,
        'meaningful': meaningful,
        'confidence': getattr(payload, 'confidence', 0.8)
    }


@router.post("/api/webhooks/stt", response_model=WebhookResponse)
async def handle_stt_webhook(
    payload: STTWebhookPayload,
    processor: ConversationProcessor = Depends(conversation_processor_dependency),
    sessions = Depends(session_service_dependency)
) -> WebhookResponse:
    """STT webhook handler with SOTA real-time conversation processing"""
    logger.info(f"🎙️ STT webhook: {payload.participant} -> {payload.room_name}")
    
    try:
        # Normalize STT payload
        extracted = extract_text_and_flags(payload)
        text = extracted['text']
        is_partial = extracted['is_partial']
        meaningful = extracted['meaningful']
        
        # Skip empty or meaningless inputs
        if not meaningful:
            logger.debug(f"Skipping empty/meaningless STT: '{text}'")
            return WebhookResponse(
                status="skipped",
                message="Empty or meaningless input",
                success=True
            )
        
        # Use real-time engine for finals and confident partials
        if not is_partial or (len(text.split()) >= 3):
            rt_engine = get_rt_engine()
            
            result = await rt_engine.handle_user_input(
                session_id=payload.participant,
                room_name=payload.room_name,
                text=text,
                audio_data=getattr(payload, 'audio_data', None),
                is_partial=is_partial
            )
            
            if "error" in result:
                logger.warning(f"RT engine error, falling back to legacy: {result['error']}")
                # Fall through to legacy
            else:
                # Successfully processed by real-time engine
                status = "partial_processed" if is_partial else "response_generated"
                return WebhookResponse(
                    status=status,
                    message=f"SOTA processed in {result.get('first_phrase_time_ms', 0):.0f}ms",
                    success=True,
                    processing_time=result.get('total_time_ms', 0),
                    metadata={
                        "phrases_sent": result.get('phrases_sent', 0),
                        "complexity": result.get('complexity', 'unknown'),
                        "sota_target_met": result.get('target_met', False),
                        "engine": "real_time_sota"
                    }
                )
        
        # Fallback to legacy processor (partials, errors, or safety)
        logger.debug(f"Using legacy processor for: partial={is_partial}, text='{text[:30]}...'")
        legacy_response = await processor.handle_stt_webhook(payload)
        
        # Add note that legacy was used
        if hasattr(legacy_response, 'metadata') and legacy_response.metadata:
            legacy_response.metadata['engine'] = 'legacy_fallback'
        
        return legacy_response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"❌ STT webhook processing failed: {e}")
        
        # Final fallback to legacy processor
        try:
            legacy_response = await processor.handle_stt_webhook(payload)
            logger.warning(f"⚠️ Emergency fallback to legacy processor successful")
            return legacy_response
        except Exception as fallback_error:
            logger.error(f"❌ Emergency fallback also failed: {fallback_error}")
            raise HTTPException(status_code=500, detail="STT processing completely failed")


@router.post("/api/webhooks/voice_onset")
async def handle_voice_onset(
    payload: dict,  # {"session_id": str, "room_name": str}
):
    """Handle voice onset (interruption) events from STT"""
    try:
        session_id = payload.get("session_id")
        room_name = payload.get("room_name")
        
        if not session_id or not room_name:
            raise HTTPException(status_code=400, detail="session_id and room_name required")
        
        rt_engine = get_rt_engine()
        result = await rt_engine.handle_voice_onset(session_id, room_name)
        
        logger.info(f"🛑 Voice onset handled: {result.get('handled', False)}")
        
        return {
            "status": "voice_onset_handled",
            "interrupted": result.get('handled', False),
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Voice onset handling failed: {e}")
        raise HTTPException(status_code=500, detail="Voice onset handling failed")


@router.get("/api/streaming/status")
async def get_streaming_status():
    """Get SOTA streaming pipeline status"""
    try:
        rt_engine = get_rt_engine()
        from ..services.streaming_service import streaming_ai_service
        streaming_stats = streaming_ai_service.get_metrics()
        
        return {
            "sota_real_time_engine": rt_engine.get_global_stats(),
            "streaming_ai_service": streaming_stats,
            "pipeline_optimizations": {
                "phrase_min_tokens": 4,
                "token_gap_ms": 60,
                "first_phrase_urgency_tokens": 2,  # Reduced for faster first phrase
                "target_first_phrase_ms": 200,
                "target_normal_response_ms": 800,
                "interruption_detect_ms": 200
            },
            "research_based": "2024-2025 voice AI best practices",
            "normalization_active": True
        }
    except Exception as e:
        logger.error(f"❌ Error getting SOTA status: {e}")
        raise HTTPException(status_code=500, detail="Error getting status")


@router.get("/api/streaming/debug")
async def debug_streaming_state():
    """Debug SOTA streaming state"""
    try:
        rt_engine = get_rt_engine()
        
        active_conversations = {
            sid: rt_engine.get_conversation_stats(sid)
            for sid in list(rt_engine.active_conversations.keys())
        }
        
        from ..services.streaming_service import streaming_ai_service
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "sota_engine_active": True,
            "active_conversations": active_conversations,
            "streaming_metrics": streaming_ai_service.get_metrics(),
            "payload_normalization": "active",
            "legacy_fallback": "available"
        }
    except Exception as e:
        logger.error(f"❌ Debug error: {e}")
        raise HTTPException(status_code=500, detail="Debug failed")
