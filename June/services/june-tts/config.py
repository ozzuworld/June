#!/usr/bin/env python3
"""
Configuration for June TTS Service
"""
import os

class Config:
    """TTS Service Configuration"""
    
    # Server
    PORT: int = int(os.getenv("PORT", "8000"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # TTS Configuration
    TTS_MODEL: str = os.getenv("TTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2")
    TTS_DEVICE: str = os.getenv("TTS_DEVICE", "auto")  # auto, cuda, cpu
    
    # LiveKit Configuration (Internal Kubernetes URLs)
    LIVEKIT_WS_URL: str = os.getenv(
        "LIVEKIT_WS_URL", 
        # Standardize default to june-services namespace
        "ws://livekit-livekit-server.june-services.svc.cluster.local:80"
    )
    LIVEKIT_API_KEY: str = os.getenv("LIVEKIT_API_KEY", "devkey")
    LIVEKIT_API_SECRET: str = os.getenv(
        "LIVEKIT_API_SECRET", 
        "secret"
    )

    # Orchestrator URL (standardized)
    ORCHESTRATOR_URL: str = os.getenv(
        "ORCHESTRATOR_URL",
        "http://june-orchestrator.june-services.svc.cluster.local:8080"
    )
    
    # Audio Configuration
    SAMPLE_RATE: int = 24000
    CHANNELS: int = 1
    
config = Config()