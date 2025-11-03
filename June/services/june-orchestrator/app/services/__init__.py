"""Service layer exports"""
# Keep explicit imports minimal to avoid import-time errors
# Expose functions and service instances explicitly

# AI: expose generate_response function
from .ai_service import generate_response

# TTS: expose synthesize_speech function
from .tts_service import synthesize_speech

# LiveKit: expose livekit_service instance
from .livekit_service import livekit_service

# SmartTTSQueue: expose queue management functions
from .smart_tts_queue import get_smart_tts_queue, initialize_smart_tts_queue

__all__ = [
    "generate_response",
    "synthesize_speech",
    "livekit_service",
    "get_smart_tts_queue",
    "initialize_smart_tts_queue",
]