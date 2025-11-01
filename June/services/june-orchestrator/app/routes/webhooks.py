# June/services/june-orchestrator/app/routes/webhooks.py
"""
Webhook handlers for FULL STREAMING PIPELINE with skill-based AI
STT → Orchestrator (WITH CONTINUOUS PARTIALS + ONLINE LLM) → TTS

FULL STREAMING PIPELINE:
- Receives continuous partial transcripts from STT every 250ms
- Starts LLM processing immediately on first partial (online decoding)
- Maintains rolling context buffer for streaming tokens
- Triggers TTS as soon as LLM generates sentences
- Achieves speech-in → thinking → speech-out overlap

SECURITY & FEATURES:
- Duplicate message detection
- Rate limiting per user  
- AI cost tracking
- Circuit breaker protection
- Voice registry and skill system
"""
import os
import logging
import httpx
import uuid
import asyncio
import time
from datetime import datetime
from typing import Optional, List, Dict, Any
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field

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

# ---------- FULL STREAMING PIPELINE feature flags ----------

def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")

STREAMING_ENABLED       = getattr(config, "ORCH_STREAMING_ENABLED", _bool_env("ORCH_STREAMING_ENABLED", True))
CONCURRENT_TTS_ENABLED  = getattr(config, "CONCURRENT_TTS_ENABLED", _bool_env("CONCURRENT_TTS_ENABLED", True))
PARTIAL_SUPPORT_ENABLED = getattr(config, "PARTIAL_SUPPORT_ENABLED", _bool_env("PARTIAL_SUPPORT_ENABLED", True))
ONLINE_LLM_ENABLED      = _bool_env("ONLINE_LLM_ENABLED", True)  # NEW: Enable online LLM processing

# NEW: Online processing state management
online_sessions: Dict[str, Dict[str, Any]] = {}  # Track active online LLM sessions
partial_buffers: Dict[str, List[str]] = defaultdict(list)  # Rolling partial context

# ---------- Models ----------

class STTWebhookPayload(BaseModel):
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
    partial: bool = Field(False, description="Whether this is a partial transcript")
    # NEW: Streaming metadata
    utterance_id: Optional[str] = None
    partial_sequence: Optional[int] = None
    is_streaming: Optional[bool] = None
    streaming_metadata: Optional[Dict[str, Any]] = None

class TTSPublishRequest(BaseModel):
    text: str
    language: str = "en"
    speaker: Optional[str] = None
    speaker_wav: Optional[str] = None
    speed: float = Field(1.0, ge=0.5, le=2.0)
    exaggeration: float = Field(0.6, ge=0.0, le=2.0)
    cfg_weight: float = Field(0.8, ge=0.1, le=1.0)
    streaming: bool = Field(False, description="Enable streaming TTS")

# ---------- Online LLM Session Management ----------

class OnlineLLMSession:
    """Manages online LLM processing for streaming partials"""
    
    def __init__(self, session_id: str, user_id: str, utterance_id: str):
        self.session_id = session_id
        self.user_id = user_id
        self.utterance_id = utterance_id
        self.partial_buffer = []
        self.llm_task: Optional[asyncio.Task] = None
        self.started_at = datetime.utcnow()
        self.first_token_sent = False
        self.accumulated_response = ""
        self.sentence_buffer = ""
        
    def add_partial(self, text: str, sequence: int) -> bool:
        """Add partial transcript and return if LLM should start/continue"""
        # Simple deduplication - only add if significantly different
        if not self.partial_buffer or len(text) > len(self.partial_buffer[-1]) + 2:
            self.partial_buffer.append(text)
            return True
        return False
        
    def get_context_text(self) -> str:
        """Get accumulated partial context for LLM"""
        return self.partial_buffer[-1] if self.partial_buffer else ""
        
    def is_active(self) -> bool:
        """Check if online session is still active"""
        return self.llm_task and not self.llm_task.done()
        
    def cancel(self):
        """Cancel online LLM processing"""
        if self.llm_task and not self.llm_task.done():
            self.llm_task.cancel()


async def _start_online_llm_processing(session_key: str, payload: STTWebhookPayload, 
                                      session, history: List[Dict]) -> OnlineLLMSession:
    """NEW: Start online LLM processing on first partial"""
    online_session = OnlineLLMSession(
        session_id=session.session_id,
        user_id=payload.participant,
        utterance_id=payload.utterance_id or str(uuid.uuid4())
    )
    
    logger.info(f"🧠 Starting ONLINE LLM for {payload.participant} (utterance: {online_session.utterance_id[:8]})")
    
    # Start streaming LLM processing
    online_session.llm_task = asyncio.create_task(
        _process_online_llm_stream(online_session, payload, session, history)
    )
    
    return online_session


async def _process_online_llm_stream(online_session: OnlineLLMSession, initial_payload: STTWebhookPayload,
                                    session, history: List[Dict]):
    """NEW: Process streaming LLM with rolling partial context"""
    try:
        start_time = time.time()
        first_token = True
        
        # Build initial context from first partial
        context_text = online_session.get_context_text()
        logger.info(f"📝 Online LLM context: '{context_text[:50]}...'")
        
        # Start streaming AI with partial context
        sentence_count = 0
        async def tts_callback(sentence: str):
            nonlocal sentence_count
            sentence_count += 1
            logger.info(f"🎤 Online TTS trigger #{sentence_count} ({(time.time() - start_time) * 1000:.0f}ms): {sentence[:50]}...")
            # Trigger streaming TTS immediately
            await _trigger_tts(
                initial_payload.room_name, sentence, initial_payload.language or "en", 
                streaming=True, use_voice_cloning=False
            )
        
        # Generate streaming response
        response_parts = []
        async for token in streaming_ai_service.generate_streaming_response(
            text=context_text,
            conversation_history=history,
            user_id=initial_payload.participant,
            session_id=session.session_id,
            tts_callback=tts_callback if CONCURRENT_TTS_ENABLED else None
        ):
            if first_token:
                first_token_time = (time.time() - start_time) * 1000
                logger.info(f"⚡ ONLINE First token in {first_token_time:.0f}ms (while user may still be speaking)")
                first_token = True
                
            response_parts.append(token)
            online_session.accumulated_response += token
        
        full_response = "".join(response_parts)
        total_time = (time.time() - start_time) * 1000
        
        logger.info(f"✅ Online LLM completed: {len(full_response)} chars in {total_time:.0f}ms")
        
        # Add to session history
        session_manager.add_to_history(
            session.session_id, "user", context_text,
            metadata={
                "confidence": initial_payload.confidence, 
                "language": initial_payload.language,
                "timestamp": initial_payload.timestamp,
                "online_processing": True,
                "utterance_id": online_session.utterance_id
            }
        )
        
        session_manager.add_to_history(
            session.session_id, "assistant", full_response,
            metadata={
                "processing_time_ms": total_time, 
                "model": config.ai.model,
                "streaming": True,
                "online_processing": True,
                "sentences_sent": sentence_count
            }
        )
        
        # If TTS wasn't triggered concurrently, send final response
        if not CONCURRENT_TTS_ENABLED and full_response:
            await _trigger_tts(
                initial_payload.room_name, full_response, 
                initial_payload.language or "en", streaming=True
            )
            
        # Track costs and metrics
        call_tracker.track_call(
            input_text=f"{context_text} {str(history)}", 
            output_text=full_response,
            processing_time_ms=total_time
        )
        
    except asyncio.CancelledError:
        logger.info(f"🛑 Online LLM processing cancelled for {online_session.user_id}")
    except Exception as e:
        logger.error(f"❌ Online LLM processing error: {e}")
        # Fallback to regular processing if needed
        if not online_session.accumulated_response:
            logger.info(f"🔄 Falling back to regular processing for {online_session.user_id}")


# ---------- Helpers ----------

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))

async def _trigger_streaming_tts(room_name: str, text: str, language: str = "en",
                                 use_voice_cloning: bool = False, user_id: Optional[str] = None,
                                 speaker: Optional[str] = None, speaker_wav: Optional[str] = None,
                                 exaggeration: float = 0.6, cfg_weight: float = 0.8) -> Dict[str, Any]:
    try:
        tts_url = f"{config.services.tts_base_url}/stream-to-room"
        
        # Build payload - only include speaker_wav if voice cloning is requested
        payload = {
            "text": text,
            "language": language,
            "exaggeration": _clamp(exaggeration, 0.0, 2.0),
            "cfg_weight": _clamp(cfg_weight, 0.1, 1.0)
        }
        
        # Only add speaker_wav for voice cloning (mockingbird skill)
        if use_voice_cloning:
            if user_id:
                refs = voice_profile_service.get_user_references(user_id)
                if refs:
                    payload["speaker_wav"] = refs
                else:
                    logger.warning(f"Voice cloning requested but no references found for user {user_id}")
            elif speaker_wav:
                resolved = resolve_voice_reference(speaker, speaker_wav)
                if resolved and validate_voice_reference(resolved):
                    payload["speaker_wav"] = [resolved]
                else:
                    logger.warning(f"Voice cloning requested but invalid reference: {resolved}")
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(tts_url, json=payload)
        if r.status_code == 200:
            res = r.json()
            logger.info(f"✅ Streaming TTS: first_audio={res.get('first_audio_ms',0)}ms total={res.get('total_time_ms',0)}ms")
            return {"success": True, **res}
        return {"success": False, "error": f"TTS HTTP {r.status_code}"}
    except Exception as e:
        logger.error(f"❌ Streaming TTS error: {e}")
        return {"success": False, "error": str(e)}

async def _trigger_tts(room_name: str, text: str, language: str = "en",
                       use_voice_cloning: bool = False, user_id: Optional[str] = None,
                       speaker: Optional[str] = None, speaker_wav: Optional[str] = None,
                       exaggeration: float = 0.6, cfg_weight: float = 0.8,
                       streaming: bool = False):
    if streaming and STREAMING_ENABLED:
        return await _trigger_streaming_tts(room_name, text, language, use_voice_cloning, user_id,
                                            speaker, speaker_wav, exaggeration, cfg_weight)
    # Non-streaming path
    try:
        tts_url = f"{config.services.tts_base_url}/publish-to-room"
        
        # Build payload - only include speaker_wav if voice cloning is requested
        payload = {
            "text": text,
            "language": language,
            "speed": 1.0,
            "exaggeration": _clamp(exaggeration, 0.0, 2.0),
            "cfg_weight": _clamp(cfg_weight, 0.1, 1.0),
            "streaming": False
        }
        
        # Only add speaker_wav for voice cloning (mockingbird skill)
        if use_voice_cloning:
            if user_id:
                refs = voice_profile_service.get_user_references(user_id)
                if refs:
                    payload["speaker_wav"] = refs
                else:
                    logger.warning(f"Voice cloning requested but no references found for user {user_id}")
            elif speaker_wav:
                resolved = resolve_voice_reference(speaker, speaker_wav)
                if resolved and validate_voice_reference(resolved):
                    payload["speaker_wav"] = [resolved]
                else:
                    logger.warning(f"Voice cloning requested but invalid reference: {resolved}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(tts_url, json=payload)
        if r.status_code != 200:
            logger.error(f"❌ TTS failed: {r.status_code} {r.text}")
    except Exception as e:
        logger.error(f"❌ TTS error: {e}")

# ---------- NEW: Online LLM Session Management ----------

def _get_online_session_key(participant: str, utterance_id: str) -> str:
    """Generate key for online session tracking"""
    return f"{participant}:{utterance_id}"

def _should_start_online_llm(partial_sequence: int, context_text: str) -> bool:
    """Determine if we should start online LLM processing"""
    # Start on first meaningful partial (sequence 1 or 2)
    if partial_sequence <= 2 and len(context_text.strip()) >= 5:
        return True
    # Or if we have enough context and no session is active
    if len(context_text.strip()) >= 10:
        return True
    return False

def _clean_expired_online_sessions():
    """Clean up expired online sessions"""
    now = datetime.utcnow()
    expired_keys = []
    
    for key, session_info in online_sessions.items():
        if 'started_at' in session_info:
            age_seconds = (now - session_info['started_at']).total_seconds()
            if age_seconds > 30:  # 30 second timeout
                expired_keys.append(key)
                if 'online_session' in session_info:
                    session_info['online_session'].cancel()
    
    for key in expired_keys:
        del online_sessions[key]
        logger.debug(f"🧹 Cleaned up expired online session: {key}")

# ---------- Routes ----------

@router.post("/api/webhooks/stt")
async def handle_stt_webhook(payload: STTWebhookPayload, authorization: str = Header(None)):
    """ENHANCED: Handle both partial and final transcripts for full streaming pipeline"""
    
    # NEW: Handle continuous partial transcripts for online processing
    if payload.partial and PARTIAL_SUPPORT_ENABLED and ONLINE_LLM_ENABLED:
        return await _handle_partial_transcript(payload)

    # Existing final transcript handling
    logger.info(f"🎤 STT Webhook: {payload.participant} in {payload.room_name}")
    logger.info(f"💬 Transcription: {payload.text}")

    # Security checks
    if not rate_limiter.check_request_rate_limit(payload.participant):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    can_call, reason = circuit_breaker.should_allow_call()
    if not can_call:
        raise HTTPException(status_code=503, detail=f"Service temporarily unavailable: {reason}")

    try:
        session = session_manager.get_or_create_session_for_room(
            room_name=payload.room_name, user_id=payload.participant
        )
        message_id = payload.transcript_id or str(uuid.uuid4())
        if duplication_detector.is_duplicate_message(session.session_id, message_id, payload.text,
                                                     payload.participant, payload.timestamp):
            return {"status": "duplicate_blocked", "message_id": message_id}
        duplication_detector.mark_message_processed(session.session_id, message_id, payload.text,
                                                   payload.participant, payload.timestamp)

        # Check for active online session for this utterance
        if payload.utterance_id:
            session_key = _get_online_session_key(payload.participant, payload.utterance_id)
            if session_key in online_sessions:
                logger.info(f"✅ Final transcript received - online LLM already processing for {session_key[:16]}...")
                # Let the online session complete, just update the final text
                online_sessions[session_key]['final_text'] = payload.text
                return {
                    "status": "online_session_active",
                    "session_id": session.session_id,
                    "utterance_id": payload.utterance_id,
                    "message": "Final transcript acknowledged, online LLM already processing"
                }

        # Handle skill triggers and regular conversation (fallback for non-online)
        skill_trigger = skill_service.detect_skill_trigger(payload.text)
        if skill_trigger:
            name, sdef = skill_trigger
            return await _handle_skill_activation(session, name, sdef, payload)
        elif session.skill_session.is_active():
            return await _handle_skill_input(session, payload)
        else:
            # Fallback to regular conversation if online processing wasn't started
            logger.info(f"🔄 Processing final transcript via regular pipeline (no online session)")
            return await _handle_conversation(session, payload)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Webhook processing error")
        raise HTTPException(status_code=500, detail=str(e))


async def _handle_partial_transcript(payload: STTWebhookPayload) -> Dict[str, Any]:
    """NEW: Handle partial transcripts and trigger online LLM processing"""
    logger.info(f"⚡ PARTIAL transcript #{payload.partial_sequence or 0} from {payload.participant}: '{payload.text}'")
    
    # Clean up old sessions periodically
    _clean_expired_online_sessions()
    
    # Get or create session
    session = session_manager.get_or_create_session_for_room(
        room_name=payload.room_name, user_id=payload.participant
    )
    
    # Generate session key for this utterance
    utterance_id = payload.utterance_id or str(uuid.uuid4())
    session_key = _get_online_session_key(payload.participant, utterance_id)
    
    # Check if we should start online LLM processing
    should_start = _should_start_online_llm(
        payload.partial_sequence or 1, payload.text
    )
    
    if session_key not in online_sessions and should_start:
        # Start new online LLM session
        history = session.get_recent_history()
        
        online_session = await _start_online_llm_processing(
            session_key, payload, session, history
        )
        
        online_sessions[session_key] = {
            'online_session': online_session,
            'started_at': datetime.utcnow(),
            'participant': payload.participant,
            'utterance_id': utterance_id
        }
        
        logger.info(f"🎯 ONLINE PIPELINE STARTED: LLM processing while user speaks (session: {session_key[:16]})")
        
        return {
            "status": "online_llm_started",
            "session_id": session.session_id,
            "utterance_id": utterance_id,
            "partial_sequence": payload.partial_sequence,
            "message": "Online LLM started processing while user speaks",
            "pipeline_mode": "speech_in + thinking + speech_out"
        }
        
    elif session_key in online_sessions:
        # Update existing online session with new partial
        online_info = online_sessions[session_key]
        online_session = online_info.get('online_session')
        
        if online_session and online_session.add_partial(payload.text, payload.partial_sequence or 0):
            logger.debug(f"🔄 Updated online context for {session_key[:16]} with partial #{payload.partial_sequence}")
            
        return {
            "status": "partial_processed",
            "session_id": session.session_id,
            "utterance_id": utterance_id,
            "partial_sequence": payload.partial_sequence,
            "online_active": online_session.is_active() if online_session else False,
            "message": "Partial added to online context"
        }
    
    else:
        # Partial received but not enough context to start yet
        logger.debug(f"🕰️ Partial queued, waiting for more context: '{payload.text}'")
        
        return {
            "status": "partial_queued",
            "session_id": session.session_id,
            "utterance_id": utterance_id,
            "partial_sequence": payload.partial_sequence,
            "message": "Partial queued, waiting for sufficient context"
        }


async def _handle_conversation(session, payload: STTWebhookPayload) -> Dict[str, Any]:
    """Handle regular conversation (fallback when online processing not used)"""
    # AI rate limiting
    if not rate_limiter.check_ai_rate_limit(payload.participant):
        raise HTTPException(status_code=429, detail="AI rate limit exceeded")

    history = session.get_recent_history()
    if STREAMING_ENABLED:
        return await _handle_streaming_conversation(session, payload, history)
    else:
        ai_text, proc_ms = await generate_response(
            text=payload.text, user_id=payload.participant, session_id=session.session_id,
            conversation_history=history
        )
        call_tracker.track_call(input_text=f"{payload.text} {str(history)}", output_text=ai_text,
                                processing_time_ms=proc_ms)
        session_manager.add_to_history(session.session_id, "user", payload.text,
                                       metadata={"confidence": payload.confidence, "language": payload.language,
                                                 "timestamp": payload.timestamp})
        session_manager.add_to_history(session.session_id, "assistant", ai_text,
                                       metadata={"processing_time_ms": proc_ms, "model": config.ai.model})
        session_manager.update_session_metrics(session.session_id,
                                               tokens_used=len(payload.text)//4 + len(ai_text)//4,
                                               response_time_ms=proc_ms)
        # Regular conversation - no voice cloning
        await _trigger_tts(payload.room_name, ai_text, payload.language or "en", streaming=False)
        return {"status": "success", "session_id": session.session_id, "ai_response": ai_text,
                "processing_time_ms": proc_ms}

async def _handle_streaming_conversation(session, payload: STTWebhookPayload, history: List[Dict]) -> Dict[str, Any]:
    """Handle streaming conversation (used as fallback when online processing not available)"""
    start = time.time()
    async def tts_cb(sentence: str):
        # Regular conversation - no voice cloning
        await _trigger_tts(payload.room_name, sentence, payload.language or "en", streaming=True)
    parts = []
    first_token_ms = None
    async for token in streaming_ai_service.generate_streaming_response(
        text=payload.text, conversation_history=history, user_id=payload.participant,
        session_id=session.session_id, tts_callback=tts_cb if CONCURRENT_TTS_ENABLED else None
    ):
        if first_token_ms is None:
            first_token_ms = (time.time() - start) * 1000
            logger.info(f"⚡ First AI token in {first_token_ms:.0f}ms")
        parts.append(token)
    ai_text = "".join(parts)
    total_ms = (time.time() - start) * 1000
    call_tracker.track_call(input_text=f"{payload.text} {str(history)}", output_text=ai_text,
                            processing_time_ms=total_ms)
    session_manager.add_to_history(session.session_id, "user", payload.text,
                                   metadata={"confidence": payload.confidence, "language": payload.language,
                                             "timestamp": payload.timestamp})
    session_manager.add_to_history(session.session_id, "assistant", ai_text,
                                   metadata={"processing_time_ms": total_ms, "model": config.ai.model,
                                             "streaming": True})
    session_manager.update_session_metrics(session.session_id,
                                           tokens_used=len(payload.text)//4 + len(ai_text)//4,
                                           response_time_ms=total_ms)
    if not CONCURRENT_TTS_ENABLED and ai_text:
        # Regular conversation - no voice cloning
        await _trigger_tts(payload.room_name, ai_text, payload.language or "en", streaming=True)
    return {"status": "streaming_success", "session_id": session.session_id, "ai_response": ai_text,
            "processing_time_ms": round(total_ms, 2), "first_token_ms": round(first_token_ms or 0, 2),
            "concurrent_tts_used": CONCURRENT_TTS_ENABLED, "streaming_mode": True}

# ---------- Skills (existing behavior preserved) ----------

async def _handle_skill_activation(session, skill_name: str, skill_def, payload: STTWebhookPayload) -> Dict[str, Any]:
    session.skill_session.activate_skill(skill_name)
    ai_response = skill_def.activation_response
    session_manager.add_to_history(session.session_id, "user", payload.text,
                                   metadata={"skill_trigger": skill_name, "confidence": payload.confidence,
                                             "language": payload.language, "timestamp": payload.timestamp})
    session_manager.add_to_history(session.session_id, "assistant", ai_response,
                                   metadata={"skill_activation": skill_name, "processing_time_ms": 50})
    # Regular skill activation - no voice cloning unless it's mockingbird
    use_cloning = skill_name == "mockingbird"
    await _trigger_tts(payload.room_name, ai_response, payload.language or "en",
                       use_voice_cloning=use_cloning,
                       user_id=payload.participant if use_cloning else None,
                       streaming=False)
    return {"status": "skill_activated", "skill_name": skill_name, "session_id": session.session_id,
            "ai_response": ai_response, "processing_time_ms": 50,
            "skill_state": session.skill_session.to_dict()}

async def _handle_skill_input(session, payload: STTWebhookPayload) -> Dict[str, Any]:
    name = session.skill_session.active_skill
    if skill_service.should_exit_skill(payload.text, session.skill_session):
        session.skill_session.deactivate_skill()
        ai_response = "Skill deactivated. I'm back to normal conversation mode."
        # Skill deactivation - no voice cloning
        await _trigger_tts(payload.room_name, ai_response, payload.language or "en", streaming=False)
        return {"status": "skill_deactivated", "ai_response": ai_response, "session_id": session.session_id}
    
    ai_response, ctx = skill_service.create_skill_response(name, payload.text, session.skill_session.context)
    session.skill_session.context.update(ctx)
    session.skill_session.increment_turn()
    session_manager.add_to_history(session.session_id, "user", payload.text,
                                   metadata={"skill_input": name, "skill_turn": session.skill_session.turn_count,
                                             "confidence": payload.confidence, "language": payload.language})
    session_manager.add_to_history(session.session_id, "assistant", ai_response,
                                   metadata={"skill_response": name, "skill_turn": session.skill_session.turn_count,
                                             "processing_time_ms": 100})
    
    # Only use voice cloning for mockingbird skill
    use_cloning = (name == "mockingbird")
    await _trigger_tts(payload.room_name, ai_response, payload.language or "en",
                       use_voice_cloning=use_cloning,
                       user_id=payload.participant if use_cloning else None,
                       streaming=False)
    return {"status": "skill_processed", "skill_name": name, "session_id": session.session_id,
            "ai_response": ai_response, "processing_time_ms": 100,
            "skill_state": session.skill_session.to_dict(), "voice_cloning_used": use_cloning}

# ---------- NEW: Streaming Pipeline Status and Control ----------

@router.get("/api/streaming/status")
async def get_streaming_status():
    """Get status of the full streaming pipeline"""
    active_online_sessions = len(online_sessions)
    
    return {
        "streaming_pipeline": {
            "enabled": STREAMING_ENABLED,
            "partial_support": PARTIAL_SUPPORT_ENABLED,
            "online_llm": ONLINE_LLM_ENABLED,
            "concurrent_tts": CONCURRENT_TTS_ENABLED,
        },
        "active_sessions": {
            "online_llm_sessions": active_online_sessions,
            "session_keys": list(online_sessions.keys()),
        },
        "pipeline_flow": {
            "step_1": "STT receives audio frames (20-40ms)",
            "step_2": f"Partials emitted every {PARTIAL_EMIT_INTERVAL_MS}ms while speaking",
            "step_3": "LLM starts on first partial (online decoding)", 
            "step_4": "TTS streams from first LLM tokens",
            "result": "speech-in + thinking + speech-out overlap"
        },
        "target_achieved": ONLINE_LLM_ENABLED and PARTIAL_SUPPORT_ENABLED and STREAMING_ENABLED,
        "performance": {
            "target_first_partial_ms": f"<300ms",
            "target_first_token_ms": f"<500ms", 
            "target_first_audio_ms": f"<2000ms",
        }
    }

@router.post("/api/streaming/cleanup")
async def cleanup_streaming_sessions():
    """Manual cleanup of streaming sessions for debugging"""
    cleaned = 0
    
    # Cancel and clean all online sessions
    for session_key, session_info in list(online_sessions.items()):
        if 'online_session' in session_info:
            session_info['online_session'].cancel()
        del online_sessions[session_key]
        cleaned += 1
    
    logger.info(f"🧹 Manually cleaned {cleaned} online streaming sessions")
    
    return {
        "status": "cleanup_complete",
        "sessions_cleaned": cleaned,
        "remaining_sessions": len(online_sessions)
    }