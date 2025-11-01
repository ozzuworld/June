# June/services/june-orchestrator/app/routes/webhooks.py
"""
Webhook handlers for event-driven architecture with skill-based AI + STREAMING
STT → Orchestrator (WITH MEMORY + SKILLS + SECURITY + STREAMING) → TTS (voice cloning for skills)

STREAMING ENHANCEMENTS:
- Partial transcript support from STT
- Concurrent AI + TTS processing
- Sentence-level TTS triggering
- First-token and first-audio latency tracking

SECURITY ENHANCEMENTS:
- Duplicate message detection
- Rate limiting per user  
- AI cost tracking
- Circuit breaker protection

CHATTERBOX TTS INTEGRATION:
- Voice registry for speaker resolution
- Emotion and pacing controls
- Enhanced voice cloning support
"""
import logging
import httpx
import tempfile
import uuid
import asyncio
import time
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

from ..config import config
from ..services.ai_service import generate_response
from ..services.streaming_service import streaming_ai_service
from ..session_manager import session_manager
from ..services.skill_service import skill_service
from ..services.voice_profile_service import voice_profile_service
from ..security.rate_limiter import rate_limiter, duplication_detector
from ..security.cost_tracker import call_tracker, circuit_breaker
from ..voice_registry import resolve_voice_reference, validate_voice_reference

logger = logging.getLogger(__name__)
router = APIRouter()

# Feature flags for streaming
STREAMING_ENABLED = config.get("ORCH_STREAMING_ENABLED", True)
CONCURRENT_TTS_ENABLED = config.get("CONCURRENT_TTS_ENABLED", True)
PARTIAL_SUPPORT_ENABLED = config.get("PARTIAL_SUPPORT_ENABLED", True)

# Streaming metrics
streaming_metrics = {
    "partial_transcripts_received": 0,
    "concurrent_tts_triggers": 0,
    "streaming_conversations": 0,
    "first_response_times": [],
    "end_to_end_times": []
}

class STTWebhookPayload(BaseModel):
    """Enhanced webhook payload with partial support"""
    event: str
    room_name: str
    participant: str
    text: str
    language: Optional[str] = None
    confidence: Optional[float] = None
    timestamp: str
    segments: Optional[List[Dict[str, Any]]] = []
    audio_data: Optional[bytes] = None
    transcript_id: Optional[str] = None
    partial: bool = Field(False, description="Whether this is a partial transcript")  # NEW

class TTSPublishRequest(BaseModel):
    """Enhanced TTS request with Chatterbox controls + streaming"""
    text: str
    language: str = "en"
    speaker: Optional[str] = None
    speaker_wav: Optional[str] = None
    speed: float = Field(1.0, ge=0.5, le=2.0)
    exaggeration: float = Field(0.6, ge=0.0, le=2.0, description="Emotion intensity")
    cfg_weight: float = Field(0.8, ge=0.1, le=1.0, description="Pacing control")
    streaming: bool = Field(False, description="Enable streaming TTS")  # NEW

def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp value between min and max"""
    return max(min_val, min(max_val, value))

async def trigger_streaming_tts(
    room_name: str,
    text: str,
    language: str = "en",
    use_voice_cloning: bool = False,
    user_id: Optional[str] = None,
    speaker: Optional[str] = None,
    speaker_wav: Optional[str] = None,
    exaggeration: float = 0.6,
    cfg_weight: float = 0.8
) -> Dict[str, Any]:
    """NEW: Streaming TTS trigger for concurrent processing"""
    try:
        tts_url = f"{config.services.tts_base_url}/stream-to-room"
        
        # Resolve voice reference (reuse existing logic)
        if use_voice_cloning and user_id:
            reference_files = voice_profile_service.get_user_references(user_id)
            if not reference_files:
                logger.warning(f"⚠️ No voice references found for {user_id}, falling back to normal voice")
                resolved_reference = resolve_voice_reference(speaker, speaker_wav)
            else:
                resolved_reference = reference_files[0]
        else:
            resolved_reference = resolve_voice_reference(speaker, speaker_wav)
        
        # Validate reference
        if not validate_voice_reference(resolved_reference):
            logger.error(f"❌ Invalid voice reference: {resolved_reference}")
            return {"success": False, "error": "Invalid voice reference"}
        
        # Clamp parameters
        exaggeration = clamp(exaggeration, 0.0, 2.0)
        cfg_weight = clamp(cfg_weight, 0.1, 1.0)
        
        payload_data = {
            "text": text,
            "language": language,
            "speaker_wav": [resolved_reference] if resolved_reference else None,
            "exaggeration": exaggeration,
            "cfg_weight": cfg_weight
        }
        
        logger.info(f"⚡ Streaming TTS: '{text[:30]}...', first_audio_target: <200ms")
        
        async with httpx.AsyncClient(timeout=15.0) as client:  # Shorter timeout for streaming
            response = await client.post(tts_url, json=payload_data)
            
            if response.status_code == 200:
                result = response.json()
                first_audio_ms = result.get('first_audio_ms', 0)
                total_time_ms = result.get('total_time_ms', 0)
                
                logger.info(f"✅ Streaming TTS complete: first_audio={first_audio_ms:.0f}ms, total={total_time_ms:.0f}ms")
                streaming_metrics["concurrent_tts_triggers"] += 1
                
                return {"success": True, **result}
            else:
                logger.error(f"❌ Streaming TTS failed: {response.status_code}")
                return {"success": False, "error": f"TTS error: {response.status_code}"}
                
    except Exception as e:
        logger.error(f"❌ Streaming TTS error: {e}")
        return {"success": False, "error": str(e)}

async def trigger_tts_in_room(
    room_name: str,
    text: str,
    language: str = "en",
    use_voice_cloning: bool = False,
    user_id: Optional[str] = None,
    speaker: Optional[str] = None,
    speaker_wav: Optional[str] = None,
    exaggeration: float = 0.6,
    cfg_weight: float = 0.8,
    streaming: bool = False  # NEW parameter
):
    """Enhanced TTS trigger with streaming option"""
    if streaming and STREAMING_ENABLED:
        return await trigger_streaming_tts(
            room_name, text, language, use_voice_cloning, user_id, 
            speaker, speaker_wav, exaggeration, cfg_weight
        )
    
    # Regular TTS (existing implementation)
    try:
        tts_url = f"{config.services.tts_base_url}/publish-to-room"
        
        # Resolve voice reference
        if use_voice_cloning and user_id:
            reference_files = voice_profile_service.get_user_references(user_id)
            if not reference_files:
                logger.warning(f"⚠️ No voice references found for {user_id}, falling back to normal voice")
                use_voice_cloning = False
                resolved_reference = resolve_voice_reference(speaker, speaker_wav)
            else:
                logger.info(f"📁 Using {len(reference_files)} reference files for voice cloning")
                resolved_reference = reference_files[0]
        else:
            resolved_reference = resolve_voice_reference(speaker, speaker_wav)
        
        if not validate_voice_reference(resolved_reference):
            logger.error(f"❌ Invalid voice reference: {resolved_reference}")
            raise HTTPException(status_code=400, detail="Invalid voice reference")
        
        # Clamp parameters
        exaggeration = clamp(exaggeration, 0.0, 2.0)
        cfg_weight = clamp(cfg_weight, 0.1, 1.0)
        
        payload_data = {
            "text": text,
            "language": language,
            "speaker_wav": [resolved_reference] if resolved_reference else None,
            "speed": 1.0,
            "exaggeration": exaggeration,
            "cfg_weight": cfg_weight,
            "streaming": streaming
        }
        
        logger.info(f"🔊 TTS Request: text='{text[:50]}...', voice='{resolved_reference}', exag={exaggeration}, cfg={cfg_weight}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(tts_url, json=payload_data)
            
            if response.status_code == 200:
                result = response.json()
                synthesis_time = result.get('synthesis_time_ms', 0)
                audio_size = result.get('audio_size', 0)
                
                logger.info(f"✅ TTS triggered successfully: {synthesis_time:.1f}ms, {audio_size} bytes")
                
                if use_voice_cloning:
                    logger.info(f"🎭 Voice cloning demonstration completed")
                    
            else:
                logger.error(f"❌ TTS trigger failed: {response.status_code}")
                logger.error(f"Response: {response.text}")
                
    except httpx.TimeoutException:
        logger.error(f"❌ TTS request timed out for room {room_name}")
    except Exception as e:
        logger.error(f"❌ Failed to trigger TTS: {e}")
        logger.exception("Full traceback:")

@router.post("/api/webhooks/stt")
async def handle_stt_webhook(
    payload: STTWebhookPayload,
    authorization: str = Header(None)
):
    """Enhanced STT webhook handler with STREAMING + SECURITY"""
    # Handle partial transcripts (Phase 1 streaming)
    if payload.partial and PARTIAL_SUPPORT_ENABLED:
        return await handle_partial_transcript(payload)
    
    # Regular processing (unchanged but with streaming options)
    logger.info(f"🎤 STT Webhook: {payload.participant} in {payload.room_name}")
    logger.info(f"💬 Transcription: {payload.text}")

    # SECURITY CHECKS (unchanged)
    if not rate_limiter.check_request_rate_limit(payload.participant):
        logger.warning(f"😫 Rate limit exceeded for {payload.participant}")
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
    can_call, reason = circuit_breaker.should_allow_call()
    if not can_call:
        logger.error(f"🚨 Circuit breaker blocking request: {reason}")
        raise HTTPException(status_code=503, detail=f"Service temporarily unavailable: {reason}")

    if authorization:
        logger.info(f"🔐 Authorization header present (len={len(authorization)}), temporarily ignored for debugging")
    else:
        logger.info("🔓 No Authorization header provided - proceeding (auth temporarily disabled)")
    
    try:
        # Get or create session
        logger.info(f"🔍 Looking up session for room: {payload.room_name}")
        session = session_manager.get_or_create_session_for_room(
            room_name=payload.room_name,
            user_id=payload.participant
        )
        logger.info(f"✅ Using session: {session.session_id} (messages: {len(session.conversation_history)})")
        
        # Duplicate detection
        message_id = payload.transcript_id or str(uuid.uuid4())
        if duplication_detector.is_duplicate_message(
            session.session_id, message_id, payload.text, 
            payload.participant, payload.timestamp
        ):
            logger.warning(f"🔄 Duplicate message blocked: {message_id}")
            return {
                "status": "duplicate_blocked",
                "message_id": message_id,
                "session_id": session.session_id
            }
        
        duplication_detector.mark_message_processed(
            session.session_id, message_id, payload.text, 
            payload.participant, payload.timestamp
        )
        
        # Check for skill triggers
        skill_trigger = skill_service.detect_skill_trigger(payload.text)
        
        if skill_trigger:
            skill_name, skill_def = skill_trigger
            return await handle_skill_activation(session, skill_name, skill_def, payload)
        elif session.skill_session.is_active():
            return await handle_skill_input(session, payload)
        else:
            # Normal conversation with streaming option
            return await handle_normal_conversation_with_streaming(session, payload)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Webhook processing error: {e}")
        logger.exception("Full traceback:")
        raise HTTPException(status_code=500, detail=str(e))

async def handle_partial_transcript(payload: STTWebhookPayload) -> Dict[str, Any]:
    """NEW: Handle partial transcripts from streaming STT"""
    logger.info(f"⚡ PARTIAL transcript: '{payload.text}' from {payload.participant}")
    streaming_metrics["partial_transcripts_received"] += 1
    
    # For now, just acknowledge partials
    # In future: could trigger predictive processing
    return {
        "status": "partial_acknowledged",
        "participant": payload.participant,
        "partial_text": payload.text,
        "timestamp": payload.timestamp
    }

async def handle_normal_conversation_with_streaming(
    session, 
    payload: STTWebhookPayload
) -> Dict[str, Any]:
    """Enhanced normal conversation with streaming + concurrent processing"""
    
    conversation_start = time.time()
    
    if STREAMING_ENABLED:
        return await _handle_streaming_conversation(session, payload, conversation_start)
    else:
        return await _handle_regular_conversation(session, payload, conversation_start)

async def _handle_streaming_conversation(
    session, 
    payload: STTWebhookPayload,
    start_time: float
) -> Dict[str, Any]:
    """NEW: Streaming conversation processing with concurrent TTS"""
    logger.info(f"⚡ STREAMING conversation processing...")
    streaming_metrics["streaming_conversations"] += 1
    
    # Security checks
    if not rate_limiter.check_ai_rate_limit(payload.participant):
        logger.warning(f"😫 AI rate limit exceeded for {payload.participant}")
        raise HTTPException(status_code=429, detail="AI rate limit exceeded")
    
    conversation_history = session.get_recent_history()
    logger.info(f"📚 Loaded conversation history: {len(conversation_history)} messages")
    
    # Prepare concurrent TTS callback
    async def tts_callback(sentence: str):
        """Callback for concurrent TTS triggering"""
        await trigger_tts_in_room(
            room_name=payload.room_name,
            text=sentence,
            language=payload.language or "en",
            use_voice_cloning=False,
            speaker=config.ai.default_speaker,
            exaggeration=0.6,
            cfg_weight=0.8,
            streaming=True  # Use streaming TTS
        )
    
    # Stream AI response with concurrent TTS
    logger.info(f"🤖 Processing with STREAMING AI + concurrent TTS...")
    
    ai_response_parts = []
    first_token_time = None
    
    async for token in streaming_ai_service.generate_streaming_response(
        text=payload.text,
        conversation_history=conversation_history,
        user_id=payload.participant,
        session_id=session.session_id,
        tts_callback=tts_callback if CONCURRENT_TTS_ENABLED else None
    ):
        if first_token_time is None:
            first_token_time = (time.time() - start_time) * 1000
            streaming_metrics["first_response_times"].append(first_token_time)
            logger.info(f"⚡ First AI token in {first_token_time:.0f}ms")
            
        ai_response_parts.append(token)
    
    # Combine response
    ai_response = "".join(ai_response_parts)
    total_time = (time.time() - start_time) * 1000
    streaming_metrics["end_to_end_times"].append(total_time)
    
    logger.info(f"✅ Streaming conversation complete ({total_time:.0f}ms): {ai_response[:100]}...")
    
    # Track costs and save history
    call_tracker.track_call(
        input_text=f"{payload.text} {str(conversation_history)}",
        output_text=ai_response,
        processing_time_ms=total_time
    )
    
    # Save to history
    session_manager.add_to_history(
        session.session_id, "user", payload.text,
        metadata={"confidence": payload.confidence, "language": payload.language, "timestamp": payload.timestamp}
    )
    session_manager.add_to_history(
        session.session_id, "assistant", ai_response,
        metadata={"processing_time_ms": total_time, "model": "gemini-2.0-flash-exp", "streaming": True}
    )
    
    session_manager.update_session_metrics(
        session.session_id,
        tokens_used=len(payload.text) // 4 + len(ai_response) // 4,
        response_time_ms=total_time
    )
    
    # If concurrent TTS was disabled, trigger final TTS
    if not CONCURRENT_TTS_ENABLED:
        await trigger_tts_in_room(
            room_name=payload.room_name,
            text=ai_response,
            language=payload.language or "en",
            use_voice_cloning=False,
            speaker=config.ai.default_speaker,
            exaggeration=0.6,
            cfg_weight=0.8,
            streaming=True
        )
    
    return {
        "status": "streaming_success",
        "session_id": session.session_id,
        "ai_response": ai_response,
        "processing_time_ms": round(total_time, 2),
        "first_token_ms": round(first_token_time, 2) if first_token_time else 0,
        "concurrent_tts_used": CONCURRENT_TTS_ENABLED,
        "streaming_mode": True
    }

async def _handle_regular_conversation(
    session, 
    payload: STTWebhookPayload,
    start_time: float
) -> Dict[str, Any]:
    """Regular conversation processing (unchanged)"""
    logger.info(f"💬 Normal conversation processing...")
    
    if not rate_limiter.check_ai_rate_limit(payload.participant):
        logger.warning(f"😫 AI rate limit exceeded for {payload.participant}")
        raise HTTPException(status_code=429, detail="AI rate limit exceeded")
    
    conversation_history = session.get_recent_history()
    logger.info(f"📚 Loaded conversation history: {len(conversation_history)} messages")
    
    logger.info(f"🤖 Processing with AI (with {len(conversation_history)} history messages)...")
    ai_response, processing_time = await generate_response(
        text=payload.text,
        user_id=payload.participant,
        session_id=session.session_id,
        conversation_history=conversation_history
    )
    logger.info(f"✅ AI Response ({processing_time}ms): {ai_response[:100]}...")
    
    call_tracker.track_call(
        input_text=f"{payload.text} {str(conversation_history)}",
        output_text=ai_response,
        processing_time_ms=processing_time
    )
    
    # Save conversation to history
    session_manager.add_to_history(
        session.session_id, "user", payload.text,
        metadata={"confidence": payload.confidence, "language": payload.language, "timestamp": payload.timestamp}
    )
    session_manager.add_to_history(
        session.session_id, "assistant", ai_response,
        metadata={"processing_time_ms": processing_time, "model": "gemini-2.0-flash-exp"}
    )
    session_manager.update_session_metrics(
        session.session_id,
        tokens_used=len(payload.text) // 4 + len(ai_response) // 4,
        response_time_ms=processing_time
    )
    logger.info(f"💾 Saved conversation exchange to session (total: {len(session.conversation_history)} messages)")
    
    # Trigger TTS
    logger.info(f"🔊 Triggering normal TTS for room: {payload.room_name}")
    logger.info(f"📝 Text length: {len(ai_response)} chars")
    
    await trigger_tts_in_room(
        room_name=payload.room_name,
        text=ai_response,
        language=payload.language or "en",
        use_voice_cloning=False,
        speaker=config.ai.default_speaker,
        exaggeration=0.6,
        cfg_weight=0.8
    )
    
    return {
        "status": "success",
        "session_id": session.session_id,
        "message_count": session.message_count,
        "ai_response": ai_response,
        "processing_time_ms": processing_time,
        "conversation_length": len(session.conversation_history),
        "session_stats": session.to_dict()
    }

# SKILL HANDLERS (unchanged but could add streaming)
async def handle_skill_activation(session, skill_name: str, skill_def, payload: STTWebhookPayload) -> Dict[str, Any]:
    """Handle skill activation (unchanged)"""
    logger.info(f"🤖 Activating skill: {skill_name} for user {payload.participant}")
    
    session.skill_session.activate_skill(skill_name)
    ai_response = skill_def.activation_response
    processing_time = 50
    
    session_manager.add_to_history(
        session.session_id, "user", payload.text,
        metadata={"skill_trigger": skill_name, "confidence": payload.confidence, "language": payload.language, "timestamp": payload.timestamp}
    )
    
    session_manager.add_to_history(
        session.session_id, "assistant", ai_response,
        metadata={"skill_activation": skill_name, "processing_time_ms": processing_time}
    )
    
    await trigger_tts_in_room(
        room_name=payload.room_name,
        text=ai_response,
        language=payload.language or "en",
        use_voice_cloning=False,
        speaker=config.ai.default_speaker,
        exaggeration=0.7,
        cfg_weight=0.8
    )
    
    return {
        "status": "skill_activated",
        "skill_name": skill_name,
        "session_id": session.session_id,
        "ai_response": ai_response,
        "processing_time_ms": processing_time,
        "skill_state": session.skill_session.to_dict()
    }

async def handle_skill_input(session, payload: STTWebhookPayload) -> Dict[str, Any]:
    """Handle skill input (unchanged)"""
    skill_name = session.skill_session.active_skill
    logger.info(f"🎭 Processing {skill_name} skill input: {payload.text[:50]}...")
    
    if skill_service.should_exit_skill(payload.text, session.skill_session):
        logger.info(f"🚪 Exiting skill: {skill_name}")
        session.skill_session.deactivate_skill()
        
        ai_response = "Skill deactivated. I'm back to normal conversation mode."
        processing_time = 50
        
        await trigger_tts_in_room(
            room_name=payload.room_name,
            text=ai_response,
            language=payload.language or "en",
            use_voice_cloning=False,
            speaker=config.ai.default_speaker,
            exaggeration=0.5,
            cfg_weight=0.8
        )
        
        return {
            "status": "skill_deactivated",
            "ai_response": ai_response,
            "session_id": session.session_id
        }
    
    # For mockingbird skill
    if skill_name == "mockingbird" and not session.skill_session.context.get("reference_captured"):
        logger.info(f"🎵 Capturing voice reference for mockingbird skill")
        session.skill_session.context["reference_text"] = payload.text
        session.skill_session.context["reference_captured"] = True
        logger.info(f"🎭 Mockingbird: Captured reference from text '{payload.text}'")
    
    # Generate skill response
    ai_response, updated_context = skill_service.create_skill_response(
        skill_name, payload.text, session.skill_session.context
    )
    
    session.skill_session.context.update(updated_context)
    session.skill_session.increment_turn()
    
    processing_time = 100
    
    # Save skill interaction
    session_manager.add_to_history(
        session.session_id, "user", payload.text,
        metadata={"skill_input": skill_name, "skill_turn": session.skill_session.turn_count, "confidence": payload.confidence, "language": payload.language}
    )
    
    session_manager.add_to_history(
        session.session_id, "assistant", ai_response,
        metadata={"skill_response": skill_name, "skill_turn": session.skill_session.turn_count, "processing_time_ms": processing_time}
    )
    
    # TTS with skill-specific settings
    use_cloning = updated_context.get("use_voice_cloning", False)
    skill_exaggeration = 0.8 if skill_name == "mockingbird" else 0.6
    
    await trigger_tts_in_room(
        room_name=payload.room_name,
        text=ai_response,
        language=payload.language or "en",
        use_voice_cloning=use_cloning,
        user_id=payload.participant if use_cloning else None,
        speaker=config.ai.default_speaker if not use_cloning else None,
        exaggeration=skill_exaggeration,
        cfg_weight=0.8
    )
    
    return {
        "status": "skill_processed",
        "skill_name": skill_name,
        "session_id": session.session_id,
        "ai_response": ai_response,
        "processing_time_ms": processing_time,
        "skill_state": session.skill_session.to_dict(),
        "voice_cloning_used": use_cloning
    }

async def _handle_regular_conversation(
    session, 
    payload: STTWebhookPayload,
    start_time: float
) -> Dict[str, Any]:
    """Regular conversation (existing implementation)"""
    logger.info(f"💬 Normal conversation processing...")
    
    if not rate_limiter.check_ai_rate_limit(payload.participant):
        logger.warning(f"😫 AI rate limit exceeded for {payload.participant}")
        raise HTTPException(status_code=429, detail="AI rate limit exceeded")
    
    conversation_history = session.get_recent_history()
    logger.info(f"📚 Loaded conversation history: {len(conversation_history)} messages")
    
    logger.info(f"🤖 Processing with AI (with {len(conversation_history)} history messages)...")
    ai_response, processing_time = await generate_response(
        text=payload.text,
        user_id=payload.participant,
        session_id=session.session_id,
        conversation_history=conversation_history
    )
    logger.info(f"✅ AI Response ({processing_time}ms): {ai_response[:100]}...")
    
    call_tracker.track_call(
        input_text=f"{payload.text} {str(conversation_history)}",
        output_text=ai_response,
        processing_time_ms=processing_time
    )
    
    # Save conversation
    session_manager.add_to_history(
        session.session_id, "user", payload.text,
        metadata={"confidence": payload.confidence, "language": payload.language, "timestamp": payload.timestamp}
    )
    session_manager.add_to_history(
        session.session_id, "assistant", ai_response,
        metadata={"processing_time_ms": processing_time, "model": "gemini-2.0-flash-exp"}
    )
    session_manager.update_session_metrics(
        session.session_id,
        tokens_used=len(payload.text) // 4 + len(ai_response) // 4,
        response_time_ms=processing_time
    )
    logger.info(f"💾 Saved conversation exchange to session (total: {len(session.conversation_history)} messages)")
    
    logger.info(f"🔊 Triggering normal TTS for room: {payload.room_name}")
    logger.info(f"📝 Text length: {len(ai_response)} chars")
    
    await trigger_tts_in_room(
        room_name=payload.room_name,
        text=ai_response,
        language=payload.language or "en",
        use_voice_cloning=False,
        speaker=config.ai.default_speaker,
        exaggeration=0.6,
        cfg_weight=0.8
    )
    
    return {
        "status": "success",
        "session_id": session.session_id,
        "message_count": session.message_count,
        "ai_response": ai_response,
        "processing_time_ms": processing_time,
        "conversation_length": len(session.conversation_history),
        "session_stats": session.to_dict()
    }

# EXISTING ENDPOINTS (enhanced with streaming)

@router.post("/api/tts/publish")
async def publish_tts_to_room(request: TTSPublishRequest):
    """Direct TTS publishing with streaming support"""
    logger.info(f"🔊 Publishing TTS to room: {request.text[:50]}...")
    
    await trigger_tts_in_room(
        room_name="manual",
        text=request.text,
        language=request.language,
        use_voice_cloning=bool(request.speaker_wav),
        user_id="manual" if request.speaker_wav else None,
        speaker=request.speaker,
        speaker_wav=request.speaker_wav,
        exaggeration=request.exaggeration,
        cfg_weight=request.cfg_weight,
        streaming=request.streaming  # NEW: Use streaming if requested
    )
    
    return {
        "status": "success",
        "text_length": len(request.text),
        "voice_cloning": bool(request.speaker_wav),
        "exaggeration": request.exaggeration,
        "cfg_weight": request.cfg_weight,
        "streaming_used": request.streaming and STREAMING_ENABLED
    }

# NEW STREAMING ENDPOINTS

@router.get("/api/streaming/status")
async def get_streaming_status():
    """NEW: Get streaming system status and metrics"""
    avg_first_token = sum(streaming_metrics["first_response_times"]) / len(streaming_metrics["first_response_times"]) if streaming_metrics["first_response_times"] else 0
    avg_end_to_end = sum(streaming_metrics["end_to_end_times"]) / len(streaming_metrics["end_to_end_times"]) if streaming_metrics["end_to_end_times"] else 0
    
    return {
        "streaming_enabled": STREAMING_ENABLED,
        "concurrent_tts_enabled": CONCURRENT_TTS_ENABLED,
        "partial_support_enabled": PARTIAL_SUPPORT_ENABLED,
        "metrics": {
            "partial_transcripts_received": streaming_metrics["partial_transcripts_received"],
            "concurrent_tts_triggers": streaming_metrics["concurrent_tts_triggers"],
            "streaming_conversations": streaming_metrics["streaming_conversations"],
            "avg_first_token_ms": round(avg_first_token, 1),
            "avg_end_to_end_ms": round(avg_end_to_end, 1)
        },
        "streaming_ai_metrics": streaming_ai_service.get_metrics()
    }

@router.post("/api/streaming/configure")
async def configure_streaming(
    streaming_enabled: bool = True,
    concurrent_tts: bool = True,
    partial_support: bool = True
):
    """NEW: Configure streaming parameters (runtime)"""
    global STREAMING_ENABLED, CONCURRENT_TTS_ENABLED, PARTIAL_SUPPORT_ENABLED
    
    STREAMING_ENABLED = streaming_enabled
    CONCURRENT_TTS_ENABLED = concurrent_tts
    PARTIAL_SUPPORT_ENABLED = partial_support
    
    logger.info(f"⚙️ Streaming configuration updated: streaming={streaming_enabled}, concurrent_tts={concurrent_tts}, partials={partial_support}")
    
    return {
        "status": "success",
        "configuration": {
            "streaming_enabled": STREAMING_ENABLED,
            "concurrent_tts_enabled": CONCURRENT_TTS_ENABLED,
            "partial_support_enabled": PARTIAL_SUPPORT_ENABLED
        }
    }

# EXISTING ENDPOINTS (unchanged)

@router.get("/api/security/stats")
async def get_security_stats():
    return {
        "status": "success",
        "rate_limiter": rate_limiter.get_stats(),
        "duplication_detector": duplication_detector.get_stats(),
        "cost_tracker": call_tracker.get_stats(),
        "circuit_breaker": circuit_breaker.get_status()
    }

@router.post("/api/security/circuit-breaker/open")
async def manual_circuit_breaker_open(reason: str = "Manual override"):
    circuit_breaker.manual_open(reason)
    logger.error(f"🚨 Circuit breaker manually opened: {reason}")
    return {
        "status": "success",
        "message": f"Circuit breaker opened: {reason}",
        "breaker_status": circuit_breaker.get_status()
    }

@router.post("/api/security/circuit-breaker/close")
async def manual_circuit_breaker_close(reason: str = "Manual override"):
    circuit_breaker.manual_close(reason)
    logger.info(f"🔧 Circuit breaker manually closed: {reason}")
    return {
        "status": "success",
        "message": f"Circuit breaker closed: {reason}",
        "breaker_status": circuit_breaker.get_status()
    }

# SKILL AND SESSION ENDPOINTS (unchanged)

@router.get("/api/skills")
async def get_available_skills():
    skills = skill_service.list_skills()
    return {
        "status": "success",
        "skills": {
            name: {
                "name": skill.name,
                "type": skill.skill_type,
                "description": skill.description,
                "help_text": skill.help_text,
                "triggers": skill.triggers,
                "ready": skill.name == "mockingbird"
            }
            for name, skill in skills.items()
        },
        "total_skills": len(skills)
    }

@router.get("/api/skills/help")
async def get_skills_help():
    help_text = skill_service.get_skill_help()
    return {
        "status": "success",
        "help_text": help_text,
        "skills": list(skill_service.list_skills().keys())
    }

@router.get("/api/sessions/stats")
async def get_sessions_stats():
    stats = session_manager.get_stats()
    voice_stats = voice_profile_service.get_stats()
    security_stats = {
        "rate_limiter": rate_limiter.get_stats(),
        "duplication_detector": duplication_detector.get_stats(),
        "cost_tracker": call_tracker.get_stats(),
        "circuit_breaker": circuit_breaker.get_status()
    }
    
    return {
        "status": "success", 
        "session_stats": stats,
        "voice_profile_stats": voice_stats,
        "security_stats": security_stats,
        "streaming_stats": streaming_metrics  # NEW
    }

@router.get("/api/sessions/{session_id}/history")
async def get_session_history(session_id: str, max_messages: int = 50):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "status": "success",
        "session_id": session_id,
        "history": session.get_recent_history(max_messages),
        "total_messages": len(session.conversation_history),
        "skill_state": session.skill_session.to_dict(),
        "session_info": session.to_dict()
    }

@router.post("/api/sessions/{session_id}/clear")
async def clear_session_history(session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    old_count = len(session.conversation_history)
    session.conversation_history = []
    session.message_count = 0
    session.skill_session.deactivate_skill()
    
    logger.info(f"🧹 Cleared {old_count} messages and reset skills for session {session_id}")
    
    return {
        "status": "success",
        "session_id": session_id,
        "cleared_messages": old_count,
        "skill_reset": True,
        "message": "Conversation history and skills cleared"
    }

@router.post("/api/sessions/{session_id}/skills/{skill_name}/deactivate")
async def deactivate_skill(session_id: str, skill_name: str):
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if session.skill_session.active_skill != skill_name:
        raise HTTPException(
            status_code=400, 
            detail=f"Skill {skill_name} is not active (current: {session.skill_session.active_skill})"
        )
    
    session.skill_session.deactivate_skill()
    logger.info(f"🚪 Manually deactivated skill {skill_name} for session {session_id}")
    
    return {
        "status": "success",
        "session_id": session_id,
        "deactivated_skill": skill_name,
        "message": f"Skill {skill_name} deactivated"
    }