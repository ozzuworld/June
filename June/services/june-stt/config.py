#!/usr/bin/env python3
"""
Configuration for June STT Service
"""
import os
from typing import Optional

class Config:
    """STT Service Configuration"""
    
    # Server
    PORT: int = int(os.getenv("PORT", "8080"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # Whisper Configuration
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "large-v3")
    WHISPER_DEVICE: str = os.getenv("WHISPER_DEVICE", "auto")  # auto, cuda, cpu
    WHISPER_COMPUTE_TYPE: str = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
    
    # File Processing
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
    
    # LiveKit Configuration (Internal Kubernetes URLs)
    LIVEKIT_WS_URL: str = os.getenv(
        "LIVEKIT_WS_URL", 
        "ws://livekit-livekit-server:80"
    )
    LIVEKIT_API_KEY: str = os.getenv("LIVEKIT_API_KEY", "devkey")
    LIVEKIT_API_SECRET: str = os.getenv(
        "LIVEKIT_API_SECRET", 
        "secret"
    )
    
    # Orchestrator Configuration (Internal Kubernetes URLs)
    ORCHESTRATOR_URL: str = os.getenv(
        "ORCHESTRATOR_URL", 
        "http://june-orchestrator:8080"
    )
    ORCHESTRATOR_API_KEY: str = os.getenv("ORCHESTRATOR_API_KEY", "")
    ORCHESTRATOR_ENABLED: bool = bool(os.getenv("ORCHESTRATOR_ENABLED", "true").lower() == "true")

config = Config()