"""Phase 2: Enhanced webhook routes with SOTA real-time conversation engine

Cleanup: remove legacy processor fallback; route all finals/eligible partials through SOTA engine.
Added: SmartTTSQueue monitoring and control endpoints for production visibility.
"""
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends

from ..models.requests import STTWebhookPayload
from ..models.responses import WebhookResponse
from ..core.dependencies import (
    conversation_processor_dependency,  # kept for non-RT endpoints that import it
    get_redis_client,
    session_service_dependency
)
from ..services.real_time_conversation_engine import RealTimeConversationEngine
from ..services.streaming_service import streaming_ai_service
from ..services.tts_service import tts_service

logger = logging.getLogger(__name__)
router = APIRouter()

_rt_engine: Optional[RealTimeConversationEngine] = None

def get_rt_engine() -> RealTimeConversationEngine:
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
    text = (
        getattr(payload, 'text', '') or
        getattr(payload, 'transcript', '') or
        getattr(payload, 'final_text', '') or
        getattr(payload, 'partial_text', '') or
        getattr(payload, 'message', '') or
        ''
    ).strip()
    is_partial = (
        getattr(payload, 'partial', False) or
        getattr(payload, 'is_partial', False) or
        payload.event in ['partial', 'interim']
    )
    meaningful = len(text) >= 2 and text not in ['', '.', '?', '!']
    return {'text': text, 'is_partial': is_partial, 'meaningful': meaningful}


@router.post("/api/webhooks/stt", response_model=WebhookResponse)
async def handle_stt_webhook(
    payload: STTWebhookPayload,
    sessions = Depends(session_service_dependency)
) -> WebhookResponse:
    logger.info(f"🎤️ STT webhook: {payload.participant} -> {payload.room_name}")
    try:
        extracted = extract_text_and_flags(payload)
        text = extracted['text']
        is_partial = extracted['is_partial']
        meaningful = extracted['meaningful']
        if not meaningful:
            return WebhookResponse(status="skipped", message="Empty or meaningless input", success=True)
        rt_engine = get_rt_engine()
        result = await rt_engine.handle_user_input(
            session_id=payload.participant,
            room_name=payload.room_name,
            text=text,
            audio_data=getattr(payload, 'audio_data', None),
            is_partial=is_partial
        )
        status = "partial_processed" if is_partial else "response_generated"
        
        # Enhanced response with SmartTTSQueue info
        response_metadata = {
            "engine": "real_time_sota_smart_tts",
            "phrases_sent": result.get('phrases_sent', 0),
            "first_phrase_ms": result.get('first_phrase_time_ms', 0),
            "smart_tts_enabled": result.get('smart_tts_enabled', False)
        }
        
        # Add queue stats if available
        if 'queue_stats' in result:
            response_metadata["queue_stats"] = result['queue_stats']
        
        return WebhookResponse(
            status=status,
            message=f"Processed in {result.get('first_phrase_time_ms', 0):.0f}ms" if 'first_phrase_time_ms' in result else "Processed",
            success='error' not in result,
            processing_time=result.get('total_time_ms', 0),
            metadata=response_metadata
        )
    except Exception as e:
        logger.exception(f"❌ STT webhook processing failed: {e}")
        raise HTTPException(status_code=500, detail="STT processing failed")


@router.post("/api/webhooks/voice_onset")
async def handle_voice_onset(payload: dict):
    try:
        session_id = payload.get("session_id")
        room_name = payload.get("room_name")
        if not session_id or not room_name:
            raise HTTPException(status_code=400, detail="session_id and room_name required")
        rt_engine = get_rt_engine()
        result = await rt_engine.handle_voice_onset(session_id, room_name)
        logger.info(f"🛑 Voice onset handled: {result.get('handled', False)}")
        
        # Enhanced response with interruption details
        response = {
            "status": "voice_onset_handled", 
            "interrupted": result.get('handled', False), 
            "session_id": session_id, 
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Add interrupt details if available
        if 'interrupt_result' in result:
            response["interrupt_details"] = result['interrupt_result']
            
        return response
        
    except Exception as e:
        logger.error(f"❌ Voice onset handling failed: {e}")
        raise HTTPException(status_code=500, detail="Voice onset handling failed")


@router.get("/api/streaming/status")
async def get_streaming_status():
    try:
        rt_engine = get_rt_engine()
        from ..services.streaming_service import streaming_ai_service
        return {
            "sota_real_time_engine": rt_engine.get_global_stats(),
            "streaming_ai_service": streaming_ai_service.get_metrics(),
            "pipeline_optimizations": {
                "phrase_min_tokens": 4,
                "token_gap_ms": 60,
                "first_phrase_urgency_tokens": 2,
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
    try:
        rt_engine = get_rt_engine()
        from ..services.streaming_service import streaming_ai_service
        
        debug_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "sota_engine_active": True,
            "active_conversations": {sid: rt_engine.get_conversation_stats(sid) for sid in list(rt_engine.active_conversations.keys())},
            "streaming_metrics": streaming_ai_service.get_metrics(),
            "payload_normalization": "active"
        }
        
        # Add SmartTTSQueue debug info if available
        try:
            from ..services import get_smart_tts_queue
            smart_tts = get_smart_tts_queue()
            if smart_tts:
                debug_data["smart_tts_global_stats"] = smart_tts.get_global_stats()
        except ImportError:
            debug_data["smart_tts_available"] = False
            
        return debug_data
        
    except Exception as e:
        logger.error(f"❌ Debug error: {e}")
        raise HTTPException(status_code=500, detail="Debug failed")


# New SmartTTSQueue Monitoring Endpoints

@router.get("/api/tts/queue/status")
async def get_tts_queue_status():
    """
    Get SmartTTSQueue global status and health metrics
    
    Returns comprehensive queue statistics, processing metrics,
    and health information for monitoring production systems.
    """
    try:
        rt_engine = get_rt_engine()
        
        # Get engine health
        engine_health = await rt_engine.health_check()
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "queue_enabled": engine_health.get('smart_tts_enabled', False),
            "engine_health": engine_health,
            "conversation_stats": rt_engine.get_global_stats(),
            "monitoring": "production_ready",
            "natural_conversation_flow": True
        }
        
    except Exception as e:
        logger.error(f"❌ TTS queue status error: {e}")
        raise HTTPException(status_code=500, detail="Queue status unavailable")


@router.get("/api/tts/queue/session/{session_id}")
async def get_session_tts_status(session_id: str):
    """
    Get TTS queue status for specific session
    
    Args:
        session_id: User session identifier
        
    Returns session-specific queue information including
    pending phrases, processing status, and conversation metrics.
    """
    try:
        rt_engine = get_rt_engine()
        session_stats = rt_engine.get_conversation_stats(session_id)
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "session_id": session_id,
            "session_stats": session_stats,
            "conversation_active": session_stats.get('active', False),
            "queue_info": session_stats.get('tts_queue', {})
        }
        
    except Exception as e:
        logger.error(f"❌ Session TTS status error for {session_id}: {e}")
        raise HTTPException(status_code=500, detail="Session status unavailable")


@router.post("/api/tts/queue/interrupt/{session_id}")
async def interrupt_session_tts(session_id: str):
    """
    Manually interrupt TTS for specific session
    
    Args:
        session_id: User session identifier
        
    Useful for debugging or handling edge cases where
    automatic interruption doesn't work as expected.
    """
    try:
        rt_engine = get_rt_engine()
        
        # Use the conversation engine's voice onset handler
        result = await rt_engine.handle_voice_onset(session_id, "manual_interrupt")
        
        logger.info(f"🛑 Manual interrupt requested for {session_id}")
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "session_id": session_id,
            "interrupt_result": result,
            "status": "interrupted" if result.get('handled') else "no_action",
            "source": "manual_api_call"
        }
        
    except Exception as e:
        logger.error(f"❌ Manual interrupt failed for {session_id}: {e}")
        raise HTTPException(status_code=500, detail="Interrupt failed")


@router.get("/api/tts/queue/health")
async def get_tts_queue_health():
    """
    Comprehensive TTS queue health check
    
    Returns detailed health information for monitoring
    and alerting systems. Includes queue capacity,
    processing latency, and error rates.
    """
    try:
        rt_engine = get_rt_engine()
        health_data = await rt_engine.health_check()
        
        # Add timestamp and additional metadata
        health_response = {
            "timestamp": datetime.utcnow().isoformat(),
            "overall_health": "healthy" if health_data.get('engine_healthy') else "unhealthy",
            "health_details": health_data,
            "monitoring_version": "v1.0",
            "natural_conversation": True
        }
        
        return health_response
        
    except Exception as e:
        logger.error(f"❌ TTS queue health check failed: {e}")
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "overall_health": "unhealthy",
            "error": str(e),
            "monitoring_version": "v1.0"
        }