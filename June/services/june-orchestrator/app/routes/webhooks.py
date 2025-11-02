"""Phase 2: Refactored webhook routes - thin orchestration layer

This file is now a thin orchestration layer that delegates all business logic
to the ConversationProcessor service. Routes are responsible only for:
1. Request validation
2. Dependency injection
3. Response formatting
4. Error handling

All conversation logic, natural flow, security, and TTS orchestration
has been moved to dedicated services.
"""
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends

from ..models.requests import STTWebhookPayload
from ..models.responses import WebhookResponse
from ..core.dependencies import conversation_processor_dependency
from ..services.conversation.processor import ConversationProcessor

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/webhooks/stt", response_model=WebhookResponse)
async def handle_stt_webhook(
    payload: STTWebhookPayload,
    processor: ConversationProcessor = Depends(conversation_processor_dependency)
) -> WebhookResponse:
    """STT webhook handler - delegates to ConversationProcessor
    
    This route is now a thin orchestration layer:
    1. Validates the incoming STT webhook payload
    2. Delegates all processing to ConversationProcessor
    3. Returns the structured response
    
    All the complex logic (natural flow, security, TTS, etc.) is now
    handled by the ConversationProcessor service.
    """
    logger.info(f"🎤 STT webhook received: {payload.participant} -> {payload.room_name}")
    
    try:
        # Delegate entirely to the processor
        response = await processor.handle_stt_webhook(payload)
        
        logger.info(f"✅ STT webhook processed: {response.status}")
        return response
        
    except HTTPException:
        # Re-raise HTTP exceptions (they have proper status codes)
        raise
    except Exception as e:
        # Log internal errors and return generic 500
        logger.exception(f"❌ STT webhook processing failed: {e}")
        raise HTTPException(
            status_code=500, 
            detail="Internal error processing STT webhook"
        )


@router.get("/api/streaming/status")
async def get_streaming_status(
    processor: ConversationProcessor = Depends(conversation_processor_dependency)
):
    """Get status of the natural streaming pipeline"""
    try:
        # Get processor state
        active_online_sessions = len(processor.online_sessions)
        active_utterance_states = len(processor.utterance_manager._utterance_states)
        active_final_trackers = len(processor.final_tracker._trackers)
        
        return {
            "natural_streaming_pipeline": {
                "enabled": True,
                "partial_support": True,
                "online_llm": True,
                "concurrent_tts": True,
                "natural_flow": True,
                "natural_flow_for_finals": True,
                "sentence_buffering": True
            },
            "natural_flow_settings": processor.config.sessions.__dict__ if hasattr(processor.config, 'sessions') else {},
            "active_sessions": {
                "online_llm_sessions": active_online_sessions,
                "utterance_states": active_utterance_states,
                "final_transcript_trackers": active_final_trackers,
                "session_keys": list(processor.online_sessions.keys())
            },
            "natural_pipeline_flow": {
                "step_1": "STT receives audio frames (20-40ms)",
                "step_2": "Partials accumulated with natural boundary detection",
                "step_3": "Finals filtered by natural conversation timing", 
                "step_4": "LLM starts only on complete thoughts/questions/pauses", 
                "step_5": "TTS streams complete sentences only",
                "result": "natural conversation timing - no word-by-word responses"
            },
            "improvements": {
                "over_triggering_fixed": True,
                "final_transcript_filtering": True,
                "natural_boundaries": True,
                "sentence_buffering": True,
                "conversation_flow": "human-like timing",
                "cooldown_protection": True
            },
            "target_achieved": True
        }
    except Exception as e:
        logger.error(f"❌ Error getting streaming status: {e}")
        raise HTTPException(status_code=500, detail="Error getting streaming status")


@router.post("/api/streaming/cleanup")
async def cleanup_streaming_sessions(
    processor: ConversationProcessor = Depends(conversation_processor_dependency)
):
    """Manual cleanup of streaming sessions for debugging"""
    try:
        cleaned_sessions = 0
        cleaned_states = 0
        cleaned_trackers = 0
        
        # Cancel and clean all online sessions
        for session_key, online_session in list(processor.online_sessions.items()):
            online_session.cancel()
            del processor.online_sessions[session_key]
            cleaned_sessions += 1
        
        # Clean utterance states and trackers
        processor.utterance_manager._utterance_states.clear()
        processor.final_tracker._trackers.clear()
        
        logger.info(
            f"🧹 Manually cleaned {cleaned_sessions} sessions, "
            f"{cleaned_states} states, {cleaned_trackers} trackers"
        )
        
        return {
            "status": "cleanup_complete",
            "sessions_cleaned": cleaned_sessions,
            "utterance_states_cleaned": cleaned_states,
            "final_trackers_cleaned": cleaned_trackers,
            "remaining_sessions": len(processor.online_sessions),
            "remaining_states": len(processor.utterance_manager._utterance_states),
            "remaining_trackers": len(processor.final_tracker._trackers)
        }
    except Exception as e:
        logger.error(f"❌ Error cleaning up sessions: {e}")
        raise HTTPException(status_code=500, detail="Error cleaning up sessions")


@router.get("/api/streaming/debug")
async def debug_streaming_state(
    processor: ConversationProcessor = Depends(conversation_processor_dependency)
):
    """Debug endpoint to inspect current streaming state"""
    try:
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "online_sessions": {
                session_key: {
                    "started_at": session.started_at.isoformat(),
                    "user_id": session.user_id,
                    "utterance_id": session.utterance_id,
                    "active": session.is_active()
                }
                for session_key, session in processor.online_sessions.items()
            },
            "utterance_states_count": len(processor.utterance_manager._utterance_states),
            "final_trackers_count": len(processor.final_tracker._trackers),
            "phase_2_architecture": {
                "thin_routes": True,
                "business_logic_extracted": True,
                "dependency_injection": True,
                "conversation_processor": True,
                "natural_flow_service": True,
                "security_guard": True,
                "tts_orchestrator": True
            }
        }
    except Exception as e:
        logger.error(f"❌ Error getting debug info: {e}")
        raise HTTPException(status_code=500, detail="Error getting debug info")