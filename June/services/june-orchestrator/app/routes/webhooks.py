"""Phase 2: Enhanced webhook routes with SOTA real-time conversation engine

This file now integrates the SOTA real-time conversation engine for
natural turn-taking and sub-1.5s latency based on 2024-2025 research.
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


@router.post("/api/webhooks/stt", response_model=WebhookResponse)
async def handle_stt_webhook(
    payload: STTWebhookPayload,
    processor: ConversationProcessor = Depends(conversation_processor_dependency),
    sessions = Depends(session_service_dependency)
) -> WebhookResponse:
    """STT webhook handler with SOTA real-time conversation processing"""
    logger.info(f"🎙️ STT webhook: {payload.participant} -> {payload.room_name}")
    
    try:
        # Get real-time engine
        rt_engine = get_rt_engine()
        
        # Determine if this is a partial or final transcript
        is_partial = getattr(payload, 'is_partial', False) or not getattr(payload, 'transcript', '').strip()
        
        if is_partial and hasattr(payload, 'transcript'):
            # Handle partial with potential early AI start
            result = await rt_engine.handle_user_input(
                session_id=payload.participant,
                room_name=payload.room_name,
                text=payload.transcript,
                audio_data=getattr(payload, 'audio_data', None),
                is_partial=True
            )
            
            return WebhookResponse(
                status="partial_processed",
                message=f"Partial processed: {payload.transcript[:30]}...",
                success=True,
                processing_time=result.get("processing_time", 0)
            )
        
        else:
            # Handle final transcript with SOTA timing
            result = await rt_engine.handle_user_input(
                session_id=payload.participant,
                room_name=payload.room_name,
                text=payload.transcript,
                audio_data=getattr(payload, 'audio_data', None),
                is_partial=False
            )
            
            if "error" in result:
                return WebhookResponse(
                    status="error",
                    message=f"Processing failed: {result['error']}",
                    success=False
                )
            
            return WebhookResponse(
                status="response_generated",
                message=f"Response delivered in {result.get('first_phrase_time_ms', 0):.0f}ms",
                success=True,
                processing_time=result.get('total_time_ms', 0),
                metadata={
                    "phrases_sent": result.get('phrases_sent', 0),
                    "complexity": result.get('complexity', 'unknown'),
                    "sota_target_met": result.get('target_met', False),
                    "first_phrase_ms": result.get('first_phrase_time_ms', 0)
                }
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"❌ STT webhook processing failed: {e}")
        
        # Fallback to legacy processor for safety
        try:
            legacy_response = await processor.handle_stt_webhook(payload)
            logger.warning(f"⚠️ Used legacy processor fallback")
            return legacy_response
        except Exception as fallback_error:
            logger.error(f"❌ Legacy fallback also failed: {fallback_error}")
            raise HTTPException(status_code=500, detail="STT processing failed")


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
                "first_phrase_urgency_tokens": 3,
                "target_first_phrase_ms": 200,
                "target_normal_response_ms": 800,
                "interruption_detect_ms": 200
            },
            "research_based": "2024-2025 voice AI best practices"
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
        }
    except Exception as e:
        logger.error(f"❌ Debug error: {e}")
        raise HTTPException(status_code=500, detail="Debug failed")
