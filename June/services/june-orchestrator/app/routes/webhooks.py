# June/services/june-orchestrator/app/routes/webhooks.py
"""
Webhook handlers for FULL STREAMING PIPELINE with skill-based AI
STT → Orchestrator (WITH NATURAL CONVERSATION FLOW + WAKE WORD) → TTS

NATURAL STREAMING PIPELINE:
- Receives continuous partial transcripts from STT every 250ms
- Uses intelligent utterance boundary detection to avoid over-triggering
- Starts LLM processing only on complete thoughts or natural pauses
- Triggers TTS only on complete sentences to maintain conversation flow
- Achieves natural speech-in → thinking → speech-out with proper timing
- APPLIES NATURAL FLOW TO BOTH PARTIAL AND FINAL TRANSCRIPTS
- NEW: Wake word gating - mic always open, responses only after "June"

SECURITY & FEATURES:
- Duplicate message detection
- Rate limiting per user  
- AI cost tracking
- Circuit breaker protection
- Voice registry and skill system
- FIXED: No more "response for every word" behavior
- FIXED: No more multiple responses to separate final transcripts
- NEW: Wake word gating for hands-free operation
"""
import os
import logging
import httpx
import uuid
import asyncio
import time
import re
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

# ---------- NATURAL STREAMING PIPELINE + WAKE WORD feature flags ----------

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

# NEW: Wake word settings
WAKE_WORD_ENABLED       = _bool_env("WAKE_WORD_ENABLED", True)  # Enable wake word gating
WAKE_WORD              = os.getenv("WAKE_WORD", "june")  # The wake word to listen for
WAKE_WINDOW_SEC        = int(os.getenv("WAKE_WINDOW_SEC", "8"))  # How long wake stays armed (seconds)
WAKE_CASE_SENSITIVE    = _bool_env("WAKE_CASE_SENSITIVE", False)  # Case sensitivity for wake word
WAKE_REQUIRE_STANDALONE = _bool_env("WAKE_REQUIRE_STANDALONE", True)  # Require wake word as standalone token
WAKE_ACKNOWLEDGMENT    = os.getenv("WAKE_ACKNOWLEDGMENT", "Yes?")  # Response when wake word only detected

# Natural conversation state management
online_sessions: Dict[str, Dict[str, Any]] = {}  # Track active online LLM sessions
utterance_states: Dict[str, Dict[str, Any]] = {}  # Track utterance progression
partial_buffers: Dict[str, List[str]] = defaultdict(list)  # Rolling partial context
final_transcript_tracker: Dict[str, Dict[str, Any]] = {}  # Track final transcript timing per participant

# NEW: Wake word state management per (room, participant)
wake_state: Dict[str, Dict[str, Any]] = {}  # Track wake word arming per participant

# ---------- NEW: Wake Word Helper Functions ----------

def _wake_key(room: str, participant: str) -> str:
    """Generate key for wake state tracking"""
    return f"{room}:{participant}"

def _normalize_text_for_wake(text: str) -> str:
    """Normalize text for wake word detection"""
    if WAKE_CASE_SENSITIVE:
        return text.strip()
    return text.lower().strip()

def _contains_wake_word(text: str) -> bool:
    """Check if text contains the wake word"""
    if not text or not WAKE_WORD:
        return False
        
    normalized_text = _normalize_text_for_wake(text)
    wake_word = WAKE_WORD if WAKE_CASE_SENSITIVE else WAKE_WORD.lower()
    
    if WAKE_REQUIRE_STANDALONE:
        # Require wake word as standalone token (avoid partial matches)
        pattern = rf"(^|\W){re.escape(wake_word)}(\W|$)"
        return re.search(pattern, normalized_text) is not None
    else:
        # Allow wake word anywhere in text
        return wake_word in normalized_text

def _is_wake_only_phrase(text: str) -> bool:
    """Check if text is only the wake word (possibly with punctuation)"""
    if not text:
        return False
        
    # Remove punctuation and normalize
    clean_text = re.sub(r'[^\w\s]', '', text).strip()
    normalized = _normalize_text_for_wake(clean_text)
    wake_word = WAKE_WORD if WAKE_CASE_SENSITIVE else WAKE_WORD.lower()
    
    return normalized == wake_word or normalized in [f"hey {wake_word}", f"hi {wake_word}"]

def _arm_wake(room: str, participant: str):
    """Arm wake word detection for participant"""
    key = _wake_key(room, participant)
    wake_state[key] = {
        "armed": True,
        "armed_at": datetime.utcnow(),
        "participant": participant,
        "room": room
    }
    logger.info(f"🎯 Wake word armed for {participant} in {room} (window: {WAKE_WINDOW_SEC}s)")

def _is_wake_armed(room: str, participant: str) -> bool:
    """Check if wake word is currently armed for participant"""
    key = _wake_key(room, participant)
    state = wake_state.get(key)
    
    if not state or not state.get("armed"):
        return False
        
    # Check if wake window has expired
    age_seconds = (datetime.utcnow() - state["armed_at"]).total_seconds()
    if age_seconds > WAKE_WINDOW_SEC:
        # Expired - remove from state
        wake_state.pop(key, None)
        logger.debug(f"⏰ Wake window expired for {participant} ({age_seconds:.1f}s)")
        return False
        
    return True

def _disarm_wake(room: str, participant: str):
    """Disarm wake word detection for participant"""
    key = _wake_key(room, participant)
    if key in wake_state:
        del wake_state[key]
        logger.info(f"🔓 Wake word disarmed for {participant} in {room}")

def _get_wake_status(room: str, participant: str) -> Dict[str, Any]:
    """Get current wake status for participant"""
    key = _wake_key(room, participant)
    state = wake_state.get(key)
    
    if not state:
        return {"armed": False, "wake_word": WAKE_WORD, "enabled": WAKE_WORD_ENABLED}
        
    armed = _is_wake_armed(room, participant)
    time_remaining = 0
    
    if armed and state.get("armed_at"):
        elapsed = (datetime.utcnow() - state["armed_at"]).total_seconds()
        time_remaining = max(0, WAKE_WINDOW_SEC - elapsed)
        
    return {
        "armed": armed,
        "wake_word": WAKE_WORD,
        "enabled": WAKE_WORD_ENABLED,
        "time_remaining_sec": round(time_remaining, 1) if armed else 0,
        "armed_at": state["armed_at"].isoformat() if state.get("armed_at") else None
    }

# [Continue with all the existing classes and functions from the original file...]
# The rest of the file remains the same but with wake word integration in handlers

# I'll just show the key handler changes since the file is very long

@router.post("/api/webhooks/stt")
async def handle_stt_webhook(payload: STTWebhookPayload, authorization: str = Header(None)):
    """ENHANCED: Handle both partial and final transcripts with natural conversation flow + wake word gating"""
    
    # Handle continuous partial transcripts with natural flow + wake word gating
    if payload.partial and PARTIAL_SUPPORT_ENABLED and ONLINE_LLM_ENABLED:
        return await _handle_partial_transcript_natural_with_wake(payload)

    # Handle final transcript with natural flow + wake word gating
    logger.info(f"🎤 STT Webhook: {payload.participant} in {payload.room_name}")
    logger.info(f"💬 Final Transcription: {payload.text}")
    
    # NEW: Wake word gating for final transcripts
    if WAKE_WORD_ENABLED:
        # Check if text contains wake word
        if _contains_wake_word(payload.text):
            if _is_wake_only_phrase(payload.text):
                # Just the wake word - acknowledge but don't process as conversation
                _arm_wake(payload.room_name, payload.participant)
                
                # Send acknowledgment response
                if WAKE_ACKNOWLEDGMENT:
                    await _trigger_tts(payload.room_name, WAKE_ACKNOWLEDGMENT, payload.language or "en", streaming=False)
                
                return {
                    "status": "wake_word_detected",
                    "wake_status": _get_wake_status(payload.room_name, payload.participant),
                    "message": f"Wake word '{WAKE_WORD}' detected - ready for commands",
                    "acknowledgment_sent": bool(WAKE_ACKNOWLEDGMENT)
                }
            else:
                # Wake word + content - arm and continue processing
                _arm_wake(payload.room_name, payload.participant)
                logger.info(f"🎯 Wake word detected with content - armed and processing: '{payload.text}'")
        
        # Check if wake is armed (required for processing)
        if not _is_wake_armed(payload.room_name, payload.participant):
            logger.info(f"🔒 Final transcript ignored - wake word not armed: '{payload.text}'")
            return {
                "status": "wake_not_armed",
                "wake_status": _get_wake_status(payload.room_name, payload.participant),
                "message": f"Final transcript ignored - say '{WAKE_WORD}' first",
                "text": payload.text
            }
    
    # [Rest of the original final transcript handling logic continues...]
    # Apply natural flow filtering, security checks, etc.
    # At the end, disarm wake word after successful processing
    
    # NEW: Disarm wake word after successful processing
    if WAKE_WORD_ENABLED and _is_wake_armed(payload.room_name, payload.participant):
        _disarm_wake(payload.room_name, payload.participant)
        logger.info(f"🔓 Wake word disarmed after successful response to {payload.participant}")
    
    return result


async def _handle_partial_transcript_natural_with_wake(payload: STTWebhookPayload) -> Dict[str, Any]:
    """Handle partial transcripts with natural conversation flow + wake word gating"""
    logger.info(f"⚡ PARTIAL transcript #{payload.partial_sequence or 0} from {payload.participant}: '{payload.text}'")
    
    # NEW: Wake word detection in partials
    if WAKE_WORD_ENABLED:
        if _contains_wake_word(payload.text):
            _arm_wake(payload.room_name, payload.participant)
            logger.info(f"🎯 Wake word detected in partial - armed for {payload.participant}")
            
            return {
                "status": "wake_word_detected_in_partial",
                "wake_status": _get_wake_status(payload.room_name, payload.participant),
                "message": "Wake word detected - waiting for command"
            }
        
        # Check if wake is armed (required for LLM processing)
        if not _is_wake_armed(payload.room_name, payload.participant):
            logger.debug(f"🔒 Partial ignored - wake not armed: '{payload.text}'")
            return {
                "status": "partial_ignored_wake_not_armed",
                "wake_status": _get_wake_status(payload.room_name, payload.participant),
                "message": f"Partial ignored - say '{WAKE_WORD}' first"
            }
    
    # [Continue with existing natural flow logic for partials...]

# Additional wake word status endpoints...
@router.get("/api/wake/status")
async def get_wake_status():
    """Get current wake word status for all participants"""
    return {
        "wake_word_system": {
            "enabled": WAKE_WORD_ENABLED,
            "wake_word": WAKE_WORD,
            "window_seconds": WAKE_WINDOW_SEC
        },
        "active_wake_states": len(wake_state)
    }
