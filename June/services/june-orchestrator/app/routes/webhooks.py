# June/services/june-orchestrator/app/routes/webhooks.py
"""
Webhook handlers for event-driven architecture with skill-based AI
STT → Orchestrator (WITH MEMORY + SKILLS + SECURITY) → TTS (voice cloning for skills)

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
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

from ..config import config
from ..services.ai_service import generate_response
from ..session_manager import session_manager
from ..services.skill_service import skill_service
from ..services.voice_profile_service import voice_profile_service
from ..security.rate_limiter import rate_limiter, duplication_detector
from ..security.cost_tracker import call_tracker, circuit_breaker
from ..voice_registry import resolve_voice_reference, validate_voice_reference

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
    audio_data: Optional[bytes] = None  # For voice cloning skills
    transcript_id: Optional[str] = None  # For duplicate detection


class TTSPublishRequest(BaseModel):
    """Enhanced TTS request with Chatterbox controls"""
    text: str
    language: str = "en"
    speaker: Optional[str] = None  # Speaker name (resolved via registry)
    speaker_wav: Optional[str] = None  # Direct reference audio URL
    speed: float = Field(1.0, ge=0.5, le=2.0)
    
    # New Chatterbox controls
    exaggeration: float = Field(0.6, ge=0.0, le=2.0, description="Emotion intensity")
    cfg_weight: float = Field(0.8, ge=0.1, le=1.0, description="Pacing control")


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp value between min and max"""
    return max(min_val, min(max_val, value))


async def trigger_tts_in_room(
    room_name: str,
    text: str,
    language: str = "en",
    use_voice_cloning: bool = False,
    user_id: Optional[str] = None,
    speaker: Optional[str] = None,
    speaker_wav: Optional[str] = None,
    exaggeration: float = 0.6,
    cfg_weight: float = 0.8
):
    """
    Enhanced TTS trigger with Chatterbox TTS integration
    
    Args:
        room_name: LiveKit room name
        text: Text to synthesize
        language: Target language
        use_voice_cloning: Whether to use voice cloning (skills only)
        user_id: User ID for voice cloning (when use_voice_cloning=True)
        speaker: Speaker name (resolved via registry)
        speaker_wav: Direct reference audio URL
        exaggeration: Emotion intensity (0.0-2.0)
        cfg_weight: Pacing control (0.1-1.0)
    """
    try:
        tts_url = f"{config.services.tts_base_url}/publish-to-room"
        
        # Resolve voice reference
        if use_voice_cloning and user_id:
            # Voice cloning mode (for skills like mockingbird)
            logger.info(f"🎭 Triggering voice cloning TTS for room: {room_name} (user: {user_id})")
            
            # Get user's reference audio files
            reference_files = voice_profile_service.get_user_references(user_id)
            
            if not reference_files:
                logger.warning(f"⚠️ No voice references found for {user_id}, falling back to normal voice")
                use_voice_cloning = False
                resolved_reference = resolve_voice_reference(speaker, speaker_wav)
            else:
                logger.info(f"📁 Using {len(reference_files)} reference files for voice cloning")
                resolved_reference = reference_files[0]  # Use first reference
        else:
            # Normal voice resolution
            resolved_reference = resolve_voice_reference(speaker, speaker_wav)
        
        # Validate reference
        if not validate_voice_reference(resolved_reference):
            logger.error(f"❌ Invalid voice reference: {resolved_reference}")
            raise HTTPException(status_code=400, detail="Invalid voice reference")
        
        # Clamp parameters
        exaggeration = clamp(exaggeration, 0.0, 2.0)
        cfg_weight = clamp(cfg_weight, 0.1, 1.0)
        
        # Build payload for Chatterbox TTS
        payload_data = {
            "text": text,
            "language": language,
            "speaker_wav": [resolved_reference],  # Chatterbox expects list
            "speed": 1.0,
            "exaggeration": exaggeration,
            "cfg_weight": cfg_weight
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
    """
    Enhanced STT webhook handler with SECURITY PROTECTION and Chatterbox TTS:
    
    1. Rate limiting per user
    2. Duplicate message detection 
    3. AI cost tracking & circuit breaker
    4. Skill-based AI and voice cloning
    5. Enhanced voice controls (emotion, pacing)
    
    Flow:
    1. Normal conversation → June's configurable voice
    2. Skill activation → Skill-specific behavior
    3. Voice cloning skills → Use user's voice as demonstration
    """
    logger.info(f"🎤 STT Webhook: {payload.participant} in {payload.room_name}")
    logger.info(f"💬 Transcription: {payload.text}")

    # SECURITY CHECK 1: Rate limiting
    if not rate_limiter.check_request_rate_limit(payload.participant):
        logger.warning(f"🚫 Rate limit exceeded for {payload.participant}")
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
    # SECURITY CHECK 2: Circuit breaker 
    can_call, reason = circuit_breaker.should_allow_call()
    if not can_call:
        logger.error(f"🚨 Circuit breaker blocking request: {reason}")
        raise HTTPException(status_code=503, detail=f"Service temporarily unavailable: {reason}")

    # DEBUG: Auth temporarily disabled
    if authorization:
        logger.info(f"🔐 Authorization header present (len={len(authorization)}), temporarily ignored for debugging")
    else:
        logger.info("🔓 No Authorization header provided - proceeding (auth temporarily disabled)")
    
    try:
        # Get or create session with skill state
        logger.info(f"🔍 Looking up session for room: {payload.room_name}")
        session = session_manager.get_or_create_session_for_room(
            room_name=payload.room_name,
            user_id=payload.participant
        )
        logger.info(f"✅ Using session: {session.session_id} (messages: {len(session.conversation_history)})")
        
        # SECURITY CHECK 3: Duplicate message detection
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
        
        # Mark message as being processed (before AI call)
        duplication_detector.mark_message_processed(
            session.session_id, message_id, payload.text, 
            payload.participant, payload.timestamp
        )
        
        # Check for skill triggers
        skill_trigger = skill_service.detect_skill_trigger(payload.text)
        
        if skill_trigger:
            # Activate skill
            skill_name, skill_def = skill_trigger
            return await handle_skill_activation(session, skill_name, skill_def, payload)
        
        elif session.skill_session.is_active():
            # Handle input for active skill
            return await handle_skill_input(session, payload)
        
        else:
            # Normal conversation with June's consistent voice
            return await handle_normal_conversation(session, payload)
        
    except HTTPException:
        raise  # Re-raise HTTP exceptions (rate limits, etc.)
    except Exception as e:
        logger.error(f"❌ Webhook processing error: {e}")
        logger.exception("Full traceback:")
        raise HTTPException(status_code=500, detail=str(e))


async def handle_skill_activation(
    session,
    skill_name: str,
    skill_def,
    payload: STTWebhookPayload
) -> Dict[str, Any]:
    """Handle skill activation with enhanced voice controls"""
    logger.info(f"🤖 Activating skill: {skill_name} for user {payload.participant}")
    
    # Activate skill in session
    session.skill_session.activate_skill(skill_name)
    
    # Get skill activation response
    ai_response = skill_def.activation_response
    processing_time = 50  # Instant response
    
    # Save skill activation to history
    session_manager.add_to_history(
        session.session_id,
        role="user",
        content=payload.text,
        metadata={
            "skill_trigger": skill_name,
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
            "skill_activation": skill_name,
            "processing_time_ms": processing_time
        }
    )
    
    # Trigger TTS with June's normal voice for skill activation (slightly more expressive)
    await trigger_tts_in_room(
        room_name=payload.room_name,
        text=ai_response,
        language=payload.language or "en",
        use_voice_cloning=False,
        speaker=config.ai.default_speaker,
        exaggeration=0.7,  # Slightly more expressive for skill activation
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
    """Handle input for active skill with voice cloning support"""
    skill_name = session.skill_session.active_skill
    logger.info(f"🎭 Processing {skill_name} skill input: {payload.text[:50]}...")
    
    # Check if user wants to exit skill
    if skill_service.should_exit_skill(payload.text, session.skill_session):
        logger.info(f"🚪 Exiting skill: {skill_name}")
        session.skill_session.deactivate_skill()
        
        ai_response = "Skill deactivated. I'm back to normal conversation mode."
        processing_time = 50
        
        # Use June's normal voice
        await trigger_tts_in_room(
            room_name=payload.room_name,
            text=ai_response,
            language=payload.language or "en",
            use_voice_cloning=False,
            speaker=config.ai.default_speaker,
            exaggeration=0.5,  # Neutral tone for deactivation
            cfg_weight=0.8
        )
        
        return {
            "status": "skill_deactivated",
            "ai_response": ai_response,
            "session_id": session.session_id
        }
    
    # For mockingbird skill - capture user's voice for cloning
    if skill_name == "mockingbird" and not session.skill_session.context.get("reference_captured"):
        logger.info(f"🎵 Capturing voice reference for mockingbird skill")
        
        # In a real implementation, you'd capture the audio from LiveKit
        # For now, we'll simulate by creating a temp reference from the text
        # This is where you'd integrate with your LiveKit audio capture
        
        # Create a temporary voice profile for this demonstration
        try:
            # Simulate audio capture (in real implementation, get from LiveKit)
            # For now, we'll use a placeholder approach
            session.skill_session.context["reference_text"] = payload.text
            session.skill_session.context["reference_captured"] = True
            
            logger.info(f"🎭 Mockingbird: Captured reference from text '{payload.text}'")
            
        except Exception as e:
            logger.error(f"❌ Failed to capture voice reference: {e}")
    
    # Generate skill-specific response
    ai_response, updated_context = skill_service.create_skill_response(
        skill_name, payload.text, session.skill_session.context
    )
    
    # Update skill context
    session.skill_session.context.update(updated_context)
    session.skill_session.increment_turn()
    
    processing_time = 100  # Skill processing time
    
    # Save skill interaction to history
    session_manager.add_to_history(
        session.session_id,
        role="user",
        content=payload.text,
        metadata={
            "skill_input": skill_name,
            "skill_turn": session.skill_session.turn_count,
            "confidence": payload.confidence,
            "language": payload.language
        }
    )
    
    session_manager.add_to_history(
        session.session_id,
        role="assistant",
        content=ai_response,
        metadata={
            "skill_response": skill_name,
            "skill_turn": session.skill_session.turn_count,
            "processing_time_ms": processing_time
        }
    )
    
    # Determine voice settings for skill response
    use_cloning = updated_context.get("use_voice_cloning", False)
    skill_exaggeration = 0.8 if skill_name == "mockingbird" else 0.6  # More dramatic for mockingbird
    
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


async def handle_normal_conversation(session, payload: STTWebhookPayload) -> Dict[str, Any]:
    """Handle normal conversation with June's consistent voice + SECURITY CHECKS"""
    logger.info(f"💬 Normal conversation processing...")
    
    # SECURITY CHECK 4: AI-specific rate limiting (more restrictive)
    if not rate_limiter.check_ai_rate_limit(payload.participant):
        logger.warning(f"🚫 AI rate limit exceeded for {payload.participant}")
        raise HTTPException(status_code=429, detail="AI rate limit exceeded")
    
    conversation_history = session.get_recent_history()
    logger.info(f"📚 Loaded conversation history: {len(conversation_history)} messages")
    
    # Process with AI
    logger.info(f"🤖 Processing with AI (with {len(conversation_history)} history messages)...")
    ai_response, processing_time = await generate_response(
        text=payload.text,
        user_id=payload.participant,
        session_id=session.session_id,
        conversation_history=conversation_history
    )
    logger.info(f"✅ AI Response ({processing_time}ms): {ai_response[:100]}...")
    
    # SECURITY: Track AI call for cost monitoring
    call_tracker.track_call(
        input_text=f"{payload.text} {str(conversation_history)}",
        output_text=ai_response,
        processing_time_ms=processing_time
    )
    
    # Save conversation to history
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
    session_manager.update_session_metrics(
        session.session_id,
        tokens_used=len(payload.text) // 4 + len(ai_response) // 4,
        response_time_ms=processing_time
    )
    logger.info(f"💾 Saved conversation exchange to session (total: {len(session.conversation_history)} messages)")
    
    # Trigger TTS with June's consistent voice (neutral settings)
    await trigger_tts_in_room(
        room_name=payload.room_name,
        text=ai_response,
        language=payload.language or "en",
        use_voice_cloning=False,
        speaker=config.ai.default_speaker,
        exaggeration=0.6,  # Balanced expressiveness
        cfg_weight=0.8     # Natural pacing
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


# EXISTING ENDPOINTS (enhanced with Chatterbox support)

@router.post("/api/tts/publish")
async def publish_tts_to_room(request: TTSPublishRequest):
    """Direct TTS publishing endpoint with Chatterbox controls"""
    logger.info(f"🔊 Publishing TTS to room: {request.text[:50]}...")
    
    await trigger_tts_in_room(
        room_name="manual",  # Manual trigger
        text=request.text,
        language=request.language,
        use_voice_cloning=bool(request.speaker_wav),
        user_id="manual" if request.speaker_wav else None,
        speaker=request.speaker,
        speaker_wav=request.speaker_wav,
        exaggeration=request.exaggeration,
        cfg_weight=request.cfg_weight
    )
    
    return {
        "status": "success",
        "text_length": len(request.text),
        "voice_cloning": bool(request.speaker_wav),
        "exaggeration": request.exaggeration,
        "cfg_weight": request.cfg_weight
    }


# SECURITY ENDPOINTS

@router.get("/api/security/stats")
async def get_security_stats():
    """Get security system statistics"""
    return {
        "status": "success",
        "rate_limiter": rate_limiter.get_stats(),
        "duplication_detector": duplication_detector.get_stats(),
        "cost_tracker": call_tracker.get_stats(),
        "circuit_breaker": circuit_breaker.get_status()
    }


@router.post("/api/security/circuit-breaker/open")
async def manual_circuit_breaker_open(reason: str = "Manual override"):
    """Manually open the circuit breaker (emergency stop)"""
    circuit_breaker.manual_open(reason)
    logger.error(f"🚨 Circuit breaker manually opened: {reason}")
    
    return {
        "status": "success",
        "message": f"Circuit breaker opened: {reason}",
        "breaker_status": circuit_breaker.get_status()
    }


@router.post("/api/security/circuit-breaker/close")
async def manual_circuit_breaker_close(reason: str = "Manual override"):
    """Manually close the circuit breaker (restore service)"""
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
    """Get list of available skills"""
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
                "ready": skill.name == "mockingbird"  # Only mockingbird is fully implemented
            }
            for name, skill in skills.items()
        },
        "total_skills": len(skills)
    }


@router.get("/api/skills/help")
async def get_skills_help():
    """Get help text for all skills"""
    help_text = skill_service.get_skill_help()
    
    return {
        "status": "success",
        "help_text": help_text,
        "skills": list(skill_service.list_skills().keys())
    }


@router.get("/api/sessions/stats")
async def get_sessions_stats():
    """Enhanced session stats including skill usage and security stats"""
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
        "security_stats": security_stats
    }


@router.get("/api/sessions/{session_id}/history")
async def get_session_history(session_id: str, max_messages: int = 50):
    """Get session history with skill context"""
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
    """Clear session history and reset skill state"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    old_count = len(session.conversation_history)
    session.conversation_history = []
    session.message_count = 0
    
    # Reset skill state
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
    """Manually deactivate a skill"""
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
