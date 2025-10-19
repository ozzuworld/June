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
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "base")
    WHISPER_DEVICE: str = os.getenv("WHISPER_DEVICE", "auto")  # auto, cuda, cpu
    WHISPER_COMPUTE_TYPE: str = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
    WHISPER_CACHE_DIR: str = os.getenv("WHISPER_CACHE_DIR", "/app/models")
    
    # Whisper Performance Configuration (Missing parameters that caused crash)
    WHISPER_NUM_WORKERS: int = int(os.getenv("WHISPER_NUM_WORKERS", "1"))
    WHISPER_CPU_THREADS: int = int(os.getenv("WHISPER_CPU_THREADS", "4"))
    WHISPER_BEAM_SIZE: int = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
    
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
        "http://june-orchestrator.june-services.svc.cluster.local:8080"
    )
    ORCHESTRATOR_API_KEY: str = os.getenv("ORCHESTRATOR_API_KEY", "")
    ORCHESTRATOR_ENABLED: bool = bool(os.getenv("ORCHESTRATOR_ENABLED", "true").lower() == "true")

config = Config()