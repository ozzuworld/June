"""Phase 2: Enhanced webhook routes with SOTA real-time conversation engine

Cleanup: remove legacy processor fallback; route all finals/eligible partials through SOTA engine.
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
    logger.info(f"🎙️ STT webhook: {payload.participant} -> {payload.room_name}")
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
        return WebhookResponse(
            status=status,
            message=f"Processed in {result.get('first_phrase_time_ms', 0):.0f}ms" if 'first_phrase_time_ms' in result else "Processed",
            success='error' not in result,
            processing_time=result.get('total_time_ms', 0),
            metadata={
                "engine": "real_time_sota",
                "phrases_sent": result.get('phrases_sent', 0),
                "first_phrase_ms": result.get('first_phrase_time_ms', 0)
            }
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
        return {"status": "voice_onset_handled", "interrupted": result.get('handled', False), "session_id": session_id, "timestamp": datetime.utcnow().isoformat()}
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
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "sota_engine_active": True,
            "active_conversations": {sid: rt_engine.get_conversation_stats(sid) for sid in list(rt_engine.active_conversations.keys())},
            "streaming_metrics": streaming_ai_service.get_metrics(),
            "payload_normalization": "active"
        }
    except Exception as e:
        logger.error(f"❌ Debug error: {e}")
        raise HTTPException(status_code=500, detail="Debug failed")
