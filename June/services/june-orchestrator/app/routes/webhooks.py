# June/services/june-orchestrator/app/routes/webhooks.py
"""
Webhook handlers for FULL STREAMING PIPELINE with skill-based AI
STT → Orchestrator (WITH NATURAL CONVERSATION FLOW + WAKE WORD) → TTS

Adds wake-word gating so microphone can be open but responses only occur after wake word.
"""
# ... existing imports unchanged
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

# ---------- NATURAL STREAMING + WAKE WORD feature flags ----------

def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")

STREAMING_ENABLED       = getattr(config, "ORCH_STREAMING_ENABLED", _bool_env("ORCH_STREAMING_ENABLED", True))
CONCURRENT_TTS_ENABLED  = getattr(config, "CONCURRENT_TTS_ENABLED", _bool_env("CONCURRENT_TTS_ENABLED", True))
PARTIAL_SUPPORT_ENABLED = getattr(config, "PARTIAL_SUPPORT_ENABLED", _bool_env("PARTIAL_SUPPORT_ENABLED", True))
ONLINE_LLM_ENABLED      = _bool_env("ONLINE_LLM_ENABLED", True)

# Natural flow
NATURAL_FLOW_ENABLED    = _bool_env("NATURAL_FLOW_ENABLED", True)
NATURAL_FLOW_FOR_FINALS = _bool_env("NATURAL_FLOW_FOR_FINALS", True)
UTTERANCE_MIN_LENGTH    = int(os.getenv("UTTERANCE_MIN_LENGTH", "15"))
UTTERANCE_MIN_PAUSE_MS  = int(os.getenv("UTTERANCE_MIN_PAUSE_MS", "1500"))
SENTENCE_BUFFER_ENABLED = _bool_env("SENTENCE_BUFFER_ENABLED", True)
LLM_TRIGGER_THRESHOLD   = float(os.getenv("LLM_TRIGGER_THRESHOLD", "0.7"))
FINAL_TRANSCRIPT_COOLDOWN_MS = int(os.getenv("FINAL_TRANSCRIPT_COOLDOWN_MS", "2000"))

# Wake word settings
WAKE_WORD               = os.getenv("WAKE_WORD", "june")
WAKE_WINDOW_SEC         = int(os.getenv("WAKE_WINDOW_SEC", "8"))
WAKE_CASE_SENSITIVE     = _bool_env("WAKE_CASE_SENSITIVE", False)
WAKE_REQUIRE_STANDALONE = _bool_env("WAKE_REQUIRE_STANDALONE", True)  # Only accept as standalone word
ALLOW_WHI LE_LISTEN     = _bool_env("ALLOW_WHILE_LISTEN", True)  # if True, answer only after wake; mic always on

# State
online_sessions: Dict[str, Dict[str, Any]] = {}
utterance_states: Dict[str, Dict[str, Any]] = {}
partial_buffers: Dict[str, List[str]] = defaultdict(list)
final_transcript_tracker: Dict[str, Dict[str, Any]] = {}

# Wake state per (room, participant)
wake_state: Dict[str, Dict[str, Any]] = {}

def _wake_key(room: str, participant: str) -> str:
    return f"{room}:{participant}"

def _normalize_text(t: str) -> str:
    if WAKE_CASE_SENSITIVE:
        return t
    return t.lower()

def _contains_wake_word(text: str) -> bool:
    t = _normalize_text(text or "")
    ww = WAKE_WORD if WAKE_CASE_SENSITIVE else WAKE_WORD.lower()
    if not t:
        return False
    # Require standalone token (default)
    import re
    if WAKE_REQUIRE_STANDALONE:
        pattern = rf"(^|\W){re.escape(ww)}(\W|$)"
        return re.search(pattern, t) is not None
    return ww in t

def _arm_wake(room: str, participant: str):
    wake_state[_wake_key(room, participant)] = {
        "armed": True,
        "armed_at": datetime.utcnow(),
    }

def _is_wake_armed(room: str, participant: str) -> bool:
    k = _wake_key(room, participant)
    s = wake_state.get(k)
    if not s or not s.get("armed"):
        return False
    age = (datetime.utcnow() - s["armed_at"]).total_seconds()
    if age > WAKE_WINDOW_SEC:
        wake_state.pop(k, None)
        return False
    return True

def _disarm_wake(room: str, participant: str):
    wake_state.pop(_wake_key(room, participant), None)

# [The rest of original file remains unchanged until webhook handlers]
