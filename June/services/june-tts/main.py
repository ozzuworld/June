#!/usr/bin/env python3
"""
June TTS Service - Chatterbox TTS + LiveKit Integration + STREAMING
Adds streaming TTS support for sub-second time-to-first-audio.
"""
import os
# robust feature flags: config attr -> env var -> default

def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")

from config import config as _cfg
STREAMING_ENABLED = getattr(_cfg, "TTS_STREAMING_ENABLED", _bool_env("TTS_STREAMING_ENABLED", True))

# ---- rest of original file follows unchanged ----
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import torch
import logging
import tempfile
import asyncio
import time
import hashlib
from contextlib import asynccontextmanager
from typing import Optional, List, Union, Dict, Any

from livekit import rtc
from livekit_token import connect_room_as_publisher
import numpy as np
import soundfile as sf
import httpx

from config import config
from chatterbox_engine import chatterbox_engine
from streaming_tts import initialize_streaming_tts, stream_tts_to_room, get_streaming_tts_metrics

# Enable detailed debug logs for LiveKit and our app
os.environ.setdefault("RUST_LOG", "livekit=debug,livekit_api=debug,livekit_ffi=debug,livekit_rtc=debug")
logging.basicConfig(
    level=getattr(config, "LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("june-tts")

# ... (rest of file content remains as in previous commit) ...
