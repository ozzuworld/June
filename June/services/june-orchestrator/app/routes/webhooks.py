# June/services/june-orchestrator/app/routes/webhooks.py
"""
Webhook handlers for event-driven architecture with skill-based AI + STREAMING
"""
import os
# robust feature flags

def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")

from ..config import config as _cfg
STREAMING_ENABLED       = getattr(_cfg, "ORCH_STREAMING_ENABLED", _bool_env("ORCH_STREAMING_ENABLED", True))
CONCURRENT_TTS_ENABLED  = getattr(_cfg, "CONCURRENT_TTS_ENABLED", _bool_env("CONCURRENT_TTS_ENABLED", True))
PARTIAL_SUPPORT_ENABLED = getattr(_cfg, "PARTIAL_SUPPORT_ENABLED", _bool_env("PARTIAL_SUPPORT_ENABLED", True))

# ---- rest of original file follows unchanged from previous commit ----
from fastapi import APIRouter, HTTPException, Header
import logging
import httpx
import tempfile
import uuid
import asyncio
import time
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

# ... (rest of file content remains as updated earlier) ...
