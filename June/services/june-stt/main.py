#!/usr/bin/env python3
"""
June STT Enhanced - Silero VAD + LiveKit Integration + STREAMING
Intelligent speech detection + Partial transcript streaming for lower latency
OpenAI API compatible + Real-time voice chat capabilities
"""
import asyncio
import logging
import uuid
import tempfile
import soundfile as sf
import os
import time
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, Deque, Dict
from collections import deque

import numpy as np
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from livekit import rtc
from scipy import signal
import httpx

from config import config
from whisper_service import whisper_service
from livekit_token import connect_room_as_subscriber
from streaming_utils import PartialTranscriptStreamer, streaming_metrics

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("june-stt")

# -------- Feature flags (robust: config attr -> env var -> default) --------

def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")

STREAMING_ENABLED = getattr(config, "STT_STREAMING_ENABLED", _bool_env("STT_STREAMING_ENABLED", True))
PARTIALS_ENABLED  = getattr(config, "STT_PARTIALS_ENABLED",  _bool_env("STT_PARTIALS_ENABLED", True))

# Global state
room: Optional[rtc.Room] = None
room_connected: bool = False
buffers: Dict[str, Deque[np.ndarray]] = {}
utterance_states: Dict[str, dict] = {}
partial_streamers: Dict[str, PartialTranscriptStreamer] = {}
processed_utterances = 0

# Simplified constants (Silero VAD handles complexity)
SAMPLE_RATE = 16000
MAX_UTTERANCE_SEC = 8.0
MIN_UTTERANCE_SEC = 0.5
PROCESS_SLEEP_SEC = 0.1
SILENCE_TIMEOUT_SEC = 1.0
EXCLUDE_PARTICIPANTS = {"june-tts", "june-stt", "tts", "stt"}

# STREAMING: Partial processing parameters
PARTIAL_CHUNK_MS = 200  # Process partials every 200ms
PARTIAL_MIN_SPEECH_MS = 500  # Minimum speech before emitting partials

class UtteranceState:
    def __init__(self):
        self.buffer: Deque[np.ndarray] = deque()
        self.is_active = False
        self.started_at: Optional[datetime] = None
        self.last_audio_at: Optional[datetime] = None
        self.total_samples = 0
        self.first_partial_sent = False  # STREAMING: Track first partial

# Helper functions (enhanced for streaming)
# ... (rest of file unchanged from previous streaming version) ...
