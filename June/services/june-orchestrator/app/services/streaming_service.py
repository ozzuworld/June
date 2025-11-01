#!/usr/bin/env python3
"""
Streaming AI Service - Concurrent processing for voice AI
Implements streaming LLM + sentence segmentation + concurrent TTS triggering
"""
import logging
import time
import asyncio
import os
from typing import Optional, AsyncIterator, Dict, Any, List
from dataclasses import dataclass
from collections import deque

from ..config import config
from ..security.cost_tracker import circuit_breaker

logger = logging.getLogger("streaming-ai")

# Feature flags (robust)

def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")

STREAMING_ENABLED      = getattr(config, "AI_STREAMING_ENABLED", _bool_env("AI_STREAMING_ENABLED", True))
CONCURRENT_TTS_ENABLED = getattr(config, "CONCURRENT_TTS_ENABLED", _bool_env("CONCURRENT_TTS_ENABLED", True))

# ... rest of file unchanged ...
