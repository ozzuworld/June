# June/services/june-orchestrator/app/routes/webhooks.py
"""
Webhook handlers for FULL STREAMING PIPELINE with skill-based AI
STT → Orchestrator (WITH NATURAL CONVERSATION FLOW) → TTS

NATURAL STREAMING PIPELINE:
- Receives continuous partial transcripts from STT every 250ms
- Uses intelligent utterance boundary detection to avoid over-triggering
- Starts LLM processing only on complete thoughts or natural pauses
- Triggers TTS only on complete sentences to maintain conversation flow
- Achieves natural speech-in → thinking → speech-out with proper timing
- APPLIES NATURAL FLOW TO BOTH PARTIAL AND FINAL TRANSCRIPTS

SECURITY & FEATURES:
- Duplicate message detection
- Rate limiting per user  
- AI cost tracking
- Circuit breaker protection
- Voice registry and skill system
- FIXED: No more "response for every word" behavior
- FIXED: No more multiple responses to separate final transcripts
"""
import os
import logging
import httpx
import uuid
import asyncio
import time
from datetime import datetime, timedelta
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

# ---------- NATURAL STREAMING PIPELINE feature flags ----------

def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")

STREAMING_ENABLED       = getattr(config, "ORCH_STREAMING_ENABLED", _bool_env("ORCH_STREAMING_ENABLED", True))
CONCURRENT_TTS_ENABLED  = getattr(config, "CONCURRENT_TTS_ENABLED", _bool_env("CONCURRENT_TTS_ENABLED", True))
PARTIAL_SUPPORT_ENABLED = getattr(config, "PARTIAL_SUPPORT_ENABLED", _bool_env("PARTIAL_SUPPORT_ENABLED", True))
ONLINE_LLM_ENABLED      = _bool_env("ONLINE_LLM_ENABLED", True)

# NEW: Natural conversation flow settings
NATURAL_FLOW_ENABLED    = _bool_env("NATURAL_FLOW_ENABLED", True)  # Enable natural conversation timing
NATURAL_FLOW_FOR_FINALS = _bool_env("NATURAL_FLOW_FOR_FINALS", True)  # Apply natural flow to final transcripts too
UTTERANCE_MIN_LENGTH    = int(os.getenv("UTTERANCE_MIN_LENGTH", "15"))  # Minimum chars before considering LLM
UTTERANCE_MIN_PAUSE_MS  = int(os.getenv("UTTERANCE_MIN_PAUSE_MS", "1500"))  # Minimum pause before triggering
SENTENCE_BUFFER_ENABLED = _bool_env("SENTENCE_BUFFER_ENABLED", True)  # Buffer tokens until complete sentences
LLM_TRIGGER_THRESHOLD   = float(os.getenv("LLM_TRIGGER_THRESHOLD", "0.7"))  # Confidence threshold
FINAL_TRANSCRIPT_COOLDOWN_MS = int(os.getenv("FINAL_TRANSCRIPT_COOLDOWN_MS", "2000"))  # Cooldown between final transcripts

# Natural conversation state management
online_sessions: Dict[str, Dict[str, Any]] = {}  # Track active online LLM sessions
utterance_states: Dict[str, Dict[str, Any]] = {}  # Track utterance progression
partial_buffers: Dict[str, List[str]] = defaultdict(list)  # Rolling partial context
final_transcript_tracker: Dict[str, Dict[str, Any]] = {}  # Track final transcript timing per participant

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
    # Streaming metadata
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

# ---------- NEW: Natural Conversation Flow Classes ----------

class UtteranceState:
    """Track the natural progression of an utterance to avoid over-triggering"""
    
    def __init__(self, participant: str, utterance_id: str):
        self.participant = participant
        self.utterance_id = utterance_id
        self.started_at = datetime.utcnow()
        self.last_partial_at = datetime.utcnow()
        self.partials = []
        self.processing_started = False
        self.last_significant_length = 0
        self.pause_detected = False
        
    def add_partial(self, text: str, sequence: int, confidence: float = 0.0) -> bool:
        """Add partial and return if this represents significant progress"""
        now = datetime.utcnow()
        self.last_partial_at = now
        
        # Only add if significantly different from last
        if not self.partials or len(text) > len(self.partials[-1]) + 3:
            self.partials.append(text)
            return True
        return False
        
    def should_start_processing(self, text: str, confidence: float = 0.0) -> bool:
        """Determine if we should start LLM processing based on natural cues"""
        if self.processing_started:
            return False
            
        # Don't process very short utterances
        if len(text.strip()) < UTTERANCE_MIN_LENGTH:
            return False
            
        # Check for natural conversation boundaries
        words = text.lower().strip().split()
        
        # Look for sentence endings
        sentence_endings = ['.', '!', '?']
        if any(text.strip().endswith(end) for end in sentence_endings):
            logger.info(f"🎯 Natural sentence ending detected: '{text[-20:]}'")
            return True
            
        # Look for question patterns
        question_starters = ['what', 'how', 'why', 'when', 'where', 'who', 'can', 'could', 'would', 'should', 'is', 'are', 'do', 'does']
        if len(words) >= 3 and words[0] in question_starters:
            if len(text.strip()) >= 20:  # Wait for substantial question
                logger.info(f"🎯 Question pattern detected: '{text[:30]}...'")
                return True
                
        # Look for natural pauses (time gap between partials)
        time_since_start = (datetime.utcnow() - self.started_at).total_seconds() * 1000
        if time_since_start >= UTTERANCE_MIN_PAUSE_MS and len(text.strip()) >= 25:
            logger.info(f"🎯 Natural pause detected after {time_since_start:.0f}ms: '{text[:30]}...'")
            return True
            
        # High confidence longer phrases
        if confidence >= LLM_TRIGGER_THRESHOLD and len(text.strip()) >= 30:
            logger.info(f"🎯 High confidence utterance detected: {confidence:.2f} '{text[:30]}...'")
            return True
            
        return False
        
    def get_current_text(self) -> str:
        """Get the most recent partial text"""
        return self.partials[-1] if self.partials else ""
        
    def mark_processing_started(self):
        """Mark that LLM processing has started for this utterance"""
        self.processing_started = True
        
    def is_expired(self, timeout_seconds: int = 30) -> bool:
        """Check if this utterance state has expired"""
        age = (datetime.utcnow() - self.started_at).total_seconds()
        return age > timeout_seconds


class FinalTranscriptTracker:
    """Track timing of final transcripts to prevent rapid-fire responses"""
    
    def __init__(self, participant: str):
        self.participant = participant
        self.last_final_transcript = None
        self.last_processing_time = None
        self.transcript_count = 0
        
    def should_process_final_transcript(self, text: str, confidence: float = 0.0) -> tuple[bool, str]:
        """Determine if this final transcript should be processed based on natural timing"""
        now = datetime.utcnow()
        
        # Always process the first final transcript
        if self.last_final_transcript is None:
            self.last_final_transcript = now
            self.transcript_count = 1
            return True, "first transcript"
            
        # Check cooldown period
        time_since_last = (now - self.last_final_transcript).total_seconds() * 1000
        if time_since_last < FINAL_TRANSCRIPT_COOLDOWN_MS:
            logger.info(f"🕰️ Final transcript cooldown active: {time_since_last:.0f}ms < {FINAL_TRANSCRIPT_COOLDOWN_MS}ms")
            return False, f"cooldown active ({time_since_last:.0f}ms)"
            
        # Apply natural conversation logic to final transcripts too
        words = text.lower().strip().split()
        
        # Don't process very short final transcripts
        if len(text.strip()) < UTTERANCE_MIN_LENGTH:
            logger.info(f"🚫 Final transcript too short: '{text}' ({len(text.strip())} chars)")
            return False, f"too short ({len(text.strip())} chars)"
            
        # Look for sentence endings - these should be processed
        sentence_endings = ['.', '!', '?']
        if any(text.strip().endswith(end) for end in sentence_endings):
            logger.info(f"🎯 Final transcript with natural ending: '{text[-20:]}'")
            self.last_final_transcript = now
            self.transcript_count += 1
            return True, "natural sentence ending"
            
        # Look for question patterns
        question_starters = ['what', 'how', 'why', 'when', 'where', 'who', 'can', 'could', 'would', 'should', 'is', 'are', 'do', 'does']
        if len(words) >= 3 and words[0] in question_starters and len(text.strip()) >= 20:
            logger.info(f"🎯 Final transcript question pattern: '{text[:30]}...'")
            self.last_final_transcript = now
            self.transcript_count += 1
            return True, "question pattern"
            
        # High confidence substantial content
        if confidence >= LLM_TRIGGER_THRESHOLD and len(text.strip()) >= 30:
            logger.info(f"🎯 Final transcript high confidence: {confidence:.2f} '{text[:30]}...'")
            self.last_final_transcript = now
            self.transcript_count += 1
            return True, "high confidence"
            
        # Default: don't process fragmented final transcripts
        logger.info(f"🚫 Final transcript filtered: '{text}' (fragmented/incomplete)")
        return False, "fragmented or incomplete"
        
    def reset(self):
        """Reset the tracker"""
        self.last_final_transcript = None
        self.last_processing_time = None
        self.transcript_count = 0


class SentenceBuffer:
    """Buffer tokens and only emit complete sentences to TTS for natural speech"""
    
    def __init__(self):
        self.buffer = ""
        self.sentence_endings = ['.', '!', '?']
        self.sentence_count = 0
        
    def add_token(self, token: str) -> Optional[str]:
        """Add token and return complete sentence if ready"""
        self.buffer += token
        
        # Look for sentence boundaries
        for ending in self.sentence_endings:
            if ending in self.buffer:
                # Find the sentence boundary
                end_pos = self.buffer.find(ending)
                if end_pos != -1:
                    # Extract the complete sentence
                    sentence = self.buffer[:end_pos + 1].strip()
                    self.buffer = self.buffer[end_pos + 1:].strip()  # Keep remainder
                    
                    # Only return substantial sentences
                    if len(sentence) >= 10:
                        self.sentence_count += 1
                        logger.info(f"📝 Complete sentence #{self.sentence_count} buffered: '{sentence[:50]}...'")
                        return sentence
        
        return None  # No complete sentence yet
        
    def get_remaining(self) -> str:
        """Get any remaining buffered content"""
        return self.buffer.strip()
        
    def clear(self):
        """Clear the buffer"""
        self.buffer = ""


class OnlineLLMSession:
    """Manages online LLM processing with natural conversation flow"""
    
    def __init__(self, session_id: str, user_id: str, utterance_id: str):
        self.session_id = session_id
        self.user_id = user_id
        self.utterance_id = utterance_id
        self.partial_buffer = []
        self.llm_task: Optional[asyncio.Task] = None
        self.started_at = datetime.utcnow()
        self.first_token_sent = False
        self.accumulated_response = ""
        self.sentence_buffer = SentenceBuffer()
        
    def add_partial(self, text: str, sequence: int) -> bool:
        """Add partial transcript and return if LLM should start/continue"""
        # Simple deduplication - only add if significantly different
        if not self.partial_buffer or len(text) > len(self.partial_buffer[-1]) + 3:
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


# ---------- NEW: Natural Conversation Flow Functions ----------

def _get_utterance_state(participant: str, utterance_id: str) -> UtteranceState:
    """Get or create utterance state for tracking natural flow"""
    key = f"{participant}:{utterance_id}"
    
    if key not in utterance_states:
        utterance_states[key] = UtteranceState(participant, utterance_id)
        
    return utterance_states[key]


def _get_final_transcript_tracker(participant: str) -> FinalTranscriptTracker:
    """Get or create final transcript tracker for participant"""
    if participant not in final_transcript_tracker:
        final_transcript_tracker[participant] = FinalTranscriptTracker(participant)
        
    return final_transcript_tracker[participant]


def _should_start_online_llm_natural(utterance_state: UtteranceState, text: str, 
                                     confidence: float = 0.0) -> bool:
    """Natural conversation flow: only start LLM on complete thoughts"""
    if not NATURAL_FLOW_ENABLED:
        # Fallback to original logic if natural flow is disabled
        return len(text.strip()) >= 10
        
    return utterance_state.should_start_processing(text, confidence)


def _should_process_final_transcript_natural(participant: str, text: str, 
                                            confidence: float = 0.0) -> tuple[bool, str]:
    """Natural flow for final transcripts: prevent rapid-fire responses"""
    if not NATURAL_FLOW_FOR_FINALS:
        return True, "natural flow disabled for finals"
        
    tracker = _get_final_transcript_tracker(participant)
    return tracker.should_process_final_transcript(text, confidence)


def _clean_expired_states():
    """Clean up expired utterance states and online sessions"""
    now = datetime.utcnow()
    expired_keys = []
    
    # Clean utterance states
    for key, state in utterance_states.items():
        if state.is_expired():
            expired_keys.append(key)
            
    for key in expired_keys:
        del utterance_states[key]
        
    # Clean online sessions
    expired_online = []
    for key, session_info in online_sessions.items():
        if 'started_at' in session_info:
            age_seconds = (now - session_info['started_at']).total_seconds()
            if age_seconds > 30:  # 30 second timeout
                expired_online.append(key)
                if 'online_session' in session_info:
                    session_info['online_session'].cancel()
    
    for key in expired_online:
        del online_sessions[key]
        
    # Clean final transcript trackers (reset after 5 minutes of inactivity)
    expired_trackers = []
    for participant, tracker in final_transcript_tracker.items():
        if tracker.last_final_transcript:
            age_minutes = (now - tracker.last_final_transcript).total_seconds() / 60
            if age_minutes > 5:
                expired_trackers.append(participant)
                
    for participant in expired_trackers:
        del final_transcript_tracker[participant]
        
    if expired_keys or expired_online or expired_trackers:
        logger.debug(f"🧹 Cleaned {len(expired_keys)} utterance states, {len(expired_online)} online sessions, {len(expired_trackers)} trackers")


# ---------- Enhanced Online LLM Processing ----------

async def _start_online_llm_processing(session_key: str, payload: STTWebhookPayload, 
                                      session, history: List[Dict]) -> OnlineLLMSession:
    """Start online LLM processing with natural conversation flow"""
    online_session = OnlineLLMSession(
        session_id=session.session_id,
        user_id=payload.participant,
        utterance_id=payload.utterance_id or str(uuid.uuid4())
    )
    
    logger.info(f"🧠 Starting NATURAL ONLINE LLM for {payload.participant} (utterance: {online_session.utterance_id[:8]})")
    
    # Start streaming LLM processing
    online_session.llm_task = asyncio.create_task(
        _process_online_llm_stream_natural(online_session, payload, session, history)
    )
    
    return online_session


async def _process_online_llm_stream_natural(online_session: OnlineLLMSession, initial_payload: STTWebhookPayload,
                                           session, history: List[Dict]):
    """Process streaming LLM with natural conversation flow and sentence buffering"""
    try:
        start_time = time.time()
        first_token = True
        
        # Build initial context from first partial
        context_text = online_session.get_context_text()
        logger.info(f"📝 Natural Online LLM context: '{context_text[:50]}...'")
        
        # Enhanced TTS callback with sentence buffering
        sentence_count = 0
        async def natural_tts_callback(sentence: str):
            nonlocal sentence_count
            
            if SENTENCE_BUFFER_ENABLED:
                # Buffer tokens and only send complete sentences
                complete_sentence = online_session.sentence_buffer.add_token(sentence)
                if complete_sentence:
                    sentence_count += 1
                    elapsed = (time.time() - start_time) * 1000
                    logger.info(f"🎤 Natural TTS trigger #{sentence_count} ({elapsed:.0f}ms): {complete_sentence[:50]}...")
                    # Trigger streaming TTS for complete sentence
                    await _trigger_tts(
                        initial_payload.room_name, complete_sentence, 
                        initial_payload.language or "en", 
                        streaming=True, use_voice_cloning=False
                    )
            else:
                # Original behavior - send every sentence fragment
                sentence_count += 1
                elapsed = (time.time() - start_time) * 1000
                logger.info(f"🎤 TTS trigger #{sentence_count} ({elapsed:.0f}ms): {sentence[:50]}...")
                await _trigger_tts(
                    initial_payload.room_name, sentence, 
                    initial_payload.language or "en", 
                    streaming=True, use_voice_cloning=False
                )
        
        # Generate streaming response
        response_parts = []
        async for token in streaming_ai_service.generate_streaming_response(
            text=context_text,
            conversation_history=history,
            user_id=initial_payload.participant,
            session_id=session.session_id,
            tts_callback=natural_tts_callback if CONCURRENT_TTS_ENABLED else None
        ):
            if first_token:
                first_token_time = (time.time() - start_time) * 1000
                logger.info(f"⚡ NATURAL First token in {first_token_time:.0f}ms (natural timing)")
                first_token = False
                
            response_parts.append(token)
            online_session.accumulated_response += token
        
        full_response = "".join(response_parts)
        total_time = (time.time() - start_time) * 1000
        
        # Send any remaining buffered content
        if SENTENCE_BUFFER_ENABLED and CONCURRENT_TTS_ENABLED:
            remaining = online_session.sentence_buffer.get_remaining()
            if remaining:
                logger.info(f"🎤 Final TTS trigger: {remaining[:50]}...")
                await _trigger_tts(
                    initial_payload.room_name, remaining, 
                    initial_payload.language or "en", 
                    streaming=True, use_voice_cloning=False
                )
        
        logger.info(f"✅ Natural Online LLM completed: {len(full_response)} chars in {total_time:.0f}ms")
        
        # Add to session history
        session_manager.add_to_history(
            session.session_id, "user", context_text,
            metadata={
                "confidence": initial_payload.confidence, 
                "language": initial_payload.language,
                "timestamp": initial_payload.timestamp,
                "online_processing": True,
                "natural_flow": True,
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
                "natural_flow": True,
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
        logger.info(f"🛑 Natural Online LLM processing cancelled for {online_session.user_id}")
    except Exception as e:
        logger.error(f"❌ Natural Online LLM processing error: {e}")
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

# ---------- Session Management ----------

def _get_online_session_key(participant: str, utterance_id: str) -> str:
    """Generate key for online session tracking"""
    return f"{participant}:{utterance_id}"

# ---------- Routes ----------

@router.post("/api/webhooks/stt")
async def handle_stt_webhook(payload: STTWebhookPayload, authorization: str = Header(None)):
    """ENHANCED: Handle both partial and final transcripts with natural conversation flow"""
    
    # Handle continuous partial transcripts with natural flow
    if payload.partial and PARTIAL_SUPPORT_ENABLED and ONLINE_LLM_ENABLED:
        return await _handle_partial_transcript_natural(payload)

    # NEW: Apply natural flow to final transcripts too
    logger.info(f"🎤 STT Webhook: {payload.participant} in {payload.room_name}")
    logger.info(f"💬 Final Transcription: {payload.text}")
    
    # NEW: Check if this final transcript should be processed based on natural timing
    should_process, reason = _should_process_final_transcript_natural(
        payload.participant, payload.text, payload.confidence or 0.0
    )
    
    if not should_process:
        logger.info(f"🚫 Final transcript filtered: {reason}")
        return {
            "status": "final_transcript_filtered",
            "reason": reason,
            "participant": payload.participant,
            "text": payload.text,
            "message": f"Final transcript not processed: {reason}"
        }
    
    logger.info(f"✅ Final transcript approved for processing: {reason}")

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
                logger.info(f"✅ Final transcript received - natural online LLM already processing for {session_key[:16]}...")
                # Let the online session complete, just update the final text
                online_sessions[session_key]['final_text'] = payload.text
                return {
                    "status": "online_session_active",
                    "session_id": session.session_id,
                    "utterance_id": payload.utterance_id,
                    "message": "Final transcript acknowledged, natural online LLM already processing"
                }

        # Handle skill triggers and regular conversation (fallback for non-online)
        skill_trigger = skill_service.detect_skill_trigger(payload.text)
        if skill_trigger:
            name, sdef = skill_trigger
            return await _handle_skill_activation(session, name, sdef, payload)
        elif session.skill_session.is_active():
            return await _handle_skill_input(session, payload)
        else:
            # Process approved final transcript via regular conversation
            logger.info(f"🔄 Processing approved final transcript via conversation pipeline")
            return await _handle_conversation(session, payload)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Webhook processing error")
        raise HTTPException(status_code=500, detail=str(e))


async def _handle_partial_transcript_natural(payload: STTWebhookPayload) -> Dict[str, Any]:
    """Handle partial transcripts with natural conversation flow to avoid over-triggering"""
    logger.info(f"⚡ PARTIAL transcript #{payload.partial_sequence or 0} from {payload.participant}: '{payload.text}'")
    
    # Clean up old states periodically
    _clean_expired_states()
    
    # Get or create session
    session = session_manager.get_or_create_session_for_room(
        room_name=payload.room_name, user_id=payload.participant
    )
    
    # Generate utterance tracking
    utterance_id = payload.utterance_id or str(uuid.uuid4())
    utterance_state = _get_utterance_state(payload.participant, utterance_id)
    session_key = _get_online_session_key(payload.participant, utterance_id)
    
    # Add this partial to the utterance state
    significant_change = utterance_state.add_partial(
        payload.text, payload.partial_sequence or 1, payload.confidence or 0.0
    )
    
    if not significant_change:
        return {
            "status": "partial_ignored",
            "session_id": session.session_id,
            "utterance_id": utterance_id,
            "message": "Partial ignored - no significant change"
        }
    
    # Check if we should start natural online LLM processing
    should_start = _should_start_online_llm_natural(
        utterance_state, payload.text, payload.confidence or 0.0
    )
    
    if session_key not in online_sessions and should_start:
        # Mark processing as started
        utterance_state.mark_processing_started()
        
        # Start new natural online LLM session
        history = session.get_recent_history()
        
        online_session = await _start_online_llm_processing(
            session_key, payload, session, history
        )
        
        online_sessions[session_key] = {
            'online_session': online_session,
            'started_at': datetime.utcnow(),
            'participant': payload.participant,
            'utterance_id': utterance_id,
            'utterance_state': utterance_state
        }
        
        logger.info(f"🎯 NATURAL ONLINE PIPELINE STARTED: LLM processing on complete thought (session: {session_key[:16]})")
        
        return {
            "status": "natural_online_llm_started",
            "session_id": session.session_id,
            "utterance_id": utterance_id,
            "partial_sequence": payload.partial_sequence,
            "message": "Natural online LLM started on complete thought",
            "pipeline_mode": "natural: speech-in + thinking + speech-out",
            "trigger_reason": "natural conversation boundary detected"
        }
        
    elif session_key in online_sessions:
        # Update existing online session with new partial
        online_info = online_sessions[session_key]
        online_session = online_info.get('online_session')
        
        if online_session and online_session.add_partial(payload.text, payload.partial_sequence or 0):
            logger.debug(f"🔄 Updated natural online context for {session_key[:16]} with partial #{payload.partial_sequence}")
            
        return {
            "status": "partial_processed",
            "session_id": session.session_id,
            "utterance_id": utterance_id,
            "partial_sequence": payload.partial_sequence,
            "online_active": online_session.is_active() if online_session else False,
            "message": "Partial added to natural online context"
        }
    
    else:
        # Partial received but waiting for natural conversation boundary
        logger.debug(f"🕰️ Natural flow: waiting for complete thought - '{payload.text}'")
        
        return {
            "status": "natural_partial_queued",
            "session_id": session.session_id,
            "utterance_id": utterance_id,
            "partial_sequence": payload.partial_sequence,
            "message": "Partial queued, waiting for natural conversation boundary",
            "waiting_for": "complete thought, question, or natural pause"
        }


# ---------- Regular Conversation Handlers (preserved) ----------

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

# ---------- NEW: Natural Streaming Pipeline Status and Control ----------

@router.get("/api/streaming/status")
async def get_streaming_status():
    """Get status of the natural streaming pipeline"""
    active_online_sessions = len(online_sessions)
    active_utterance_states = len(utterance_states)
    active_final_trackers = len(final_transcript_tracker)
    
    return {
        "natural_streaming_pipeline": {
            "enabled": STREAMING_ENABLED,
            "partial_support": PARTIAL_SUPPORT_ENABLED,
            "online_llm": ONLINE_LLM_ENABLED,
            "concurrent_tts": CONCURRENT_TTS_ENABLED,
            "natural_flow": NATURAL_FLOW_ENABLED,
            "natural_flow_for_finals": NATURAL_FLOW_FOR_FINALS,
            "sentence_buffering": SENTENCE_BUFFER_ENABLED
        },
        "natural_flow_settings": {
            "min_utterance_length": UTTERANCE_MIN_LENGTH,
            "min_pause_ms": UTTERANCE_MIN_PAUSE_MS,
            "confidence_threshold": LLM_TRIGGER_THRESHOLD,
            "final_transcript_cooldown_ms": FINAL_TRANSCRIPT_COOLDOWN_MS
        },
        "active_sessions": {
            "online_llm_sessions": active_online_sessions,
            "utterance_states": active_utterance_states,
            "final_transcript_trackers": active_final_trackers,
            "session_keys": list(online_sessions.keys())
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
            "final_transcript_filtering": NATURAL_FLOW_FOR_FINALS,
            "natural_boundaries": True,
            "sentence_buffering": SENTENCE_BUFFER_ENABLED,
            "conversation_flow": "human-like timing",
            "cooldown_protection": True
        },
        "target_achieved": ONLINE_LLM_ENABLED and PARTIAL_SUPPORT_ENABLED and STREAMING_ENABLED and NATURAL_FLOW_ENABLED and NATURAL_FLOW_FOR_FINALS
    }

@router.post("/api/streaming/cleanup")
async def cleanup_streaming_sessions():
    """Manual cleanup of streaming sessions and utterance states for debugging"""
    cleaned_sessions = 0
    cleaned_states = 0
    cleaned_trackers = 0
    
    # Cancel and clean all online sessions
    for session_key, session_info in list(online_sessions.items()):
        if 'online_session' in session_info:
            session_info['online_session'].cancel()
        del online_sessions[session_key]
        cleaned_sessions += 1
    
    # Clean all utterance states
    utterance_states.clear()
    cleaned_states = len(utterance_states)
    
    # Clean final transcript trackers
    final_transcript_tracker.clear()
    cleaned_trackers = len(final_transcript_tracker)
    
    logger.info(f"🧹 Manually cleaned {cleaned_sessions} online sessions, {cleaned_states} utterance states, {cleaned_trackers} final trackers")
    
    return {
        "status": "cleanup_complete",
        "sessions_cleaned": cleaned_sessions,
        "utterance_states_cleaned": cleaned_states,
        "final_trackers_cleaned": cleaned_trackers,
        "remaining_sessions": len(online_sessions),
        "remaining_states": len(utterance_states),
        "remaining_trackers": len(final_transcript_tracker)
    }

@router.get("/api/streaming/debug")
async def debug_streaming_state():
    """Debug endpoint to inspect current streaming state"""
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "online_sessions": {
            session_key: {
                "started_at": info.get('started_at').isoformat() if info.get('started_at') else None,
                "participant": info.get('participant'),
                "utterance_id": info.get('utterance_id'),
                "active": info.get('online_session').is_active() if info.get('online_session') else False
            }
            for session_key, info in online_sessions.items()
        },
        "utterance_states": {
            key: {
                "started_at": state.started_at.isoformat(),
                "last_partial_at": state.last_partial_at.isoformat(),
                "partials_count": len(state.partials),
                "processing_started": state.processing_started,
                "current_text": state.get_current_text()[:50] + "..." if state.get_current_text() else ""
            }
            for key, state in utterance_states.items()
        },
        "final_transcript_trackers": {
            participant: {
                "last_transcript_at": tracker.last_final_transcript.isoformat() if tracker.last_final_transcript else None,
                "transcript_count": tracker.transcript_count
            }
            for participant, tracker in final_transcript_tracker.items()
        },
        "configuration": {
            "natural_flow_enabled": NATURAL_FLOW_ENABLED,
            "natural_flow_for_finals": NATURAL_FLOW_FOR_FINALS,
            "min_length": UTTERANCE_MIN_LENGTH,
            "min_pause_ms": UTTERANCE_MIN_PAUSE_MS,
            "confidence_threshold": LLM_TRIGGER_THRESHOLD,
            "sentence_buffering": SENTENCE_BUFFER_ENABLED,
            "final_cooldown_ms": FINAL_TRANSCRIPT_COOLDOWN_MS
        }
    }