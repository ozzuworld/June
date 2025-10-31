#!/usr/bin/env python3
"""
Simplified Configuration for June STT Service with faster-whisper
Follows faster-whisper best practices and built-in capabilities
"""
import os
from typing import Optional

class Config:
    """Simplified STT Service Configuration - relies on faster-whisper defaults"""
    
    # Server
    PORT: int = int(os.getenv("PORT", "8080"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # Whisper Configuration
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "base")
    WHISPER_DEVICE: str = os.getenv("WHISPER_DEVICE", "auto")  # auto, cuda, cpu
    WHISPER_COMPUTE_TYPE: str = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
    WHISPER_CACHE_DIR: str = os.getenv("WHISPER_CACHE_DIR", "/app/models")
    
    # Whisper Performance Configuration
    WHISPER_NUM_WORKERS: int = int(os.getenv("WHISPER_NUM_WORKERS", "1"))
    WHISPER_CPU_THREADS: int = int(os.getenv("WHISPER_CPU_THREADS", "4"))
    WHISPER_BEAM_SIZE: int = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
    
    # Batched inference (recommended for throughput)
    USE_BATCHED_INFERENCE: bool = os.getenv("STT_USE_BATCHED", "true").lower() == "true"
    BATCH_SIZE: int = int(os.getenv("STT_BATCH_SIZE", "8"))
    
    # VAD Configuration - disabled by default for English voice chat
    # Enable for long recordings or noisy environments
    VAD_ENABLED: bool = os.getenv("VAD_ENABLED", "false").lower() == "true"
    
    # Optional RMS prefilter - disabled by default (let faster-whisper handle silence)
    RMS_PREFILTER_ENABLED: bool = os.getenv("STT_RMS_PREFILTER", "false").lower() == "true"
    SILENCE_RMS_THRESHOLD: float = float(os.getenv("SILENCE_RMS_THRESHOLD", "0.001"))
    
    # Transcription Quality Settings
    CONDITION_ON_PREVIOUS_TEXT: bool = os.getenv("CONDITION_ON_PREVIOUS_TEXT", "false").lower() == "true"
    TEMPERATURE: float = float(os.getenv("WHISPER_TEMPERATURE", "0.0"))
    LANGUAGE: Optional[str] = os.getenv("WHISPER_LANGUAGE", None)  # Set to "en" for English-only
    
    # File Processing
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
    
    # LiveKit Configuration
    LIVEKIT_WS_URL: str = os.getenv(
        "LIVEKIT_WS_URL", 
        "ws://livekit-livekit-server:80"
    )
    LIVEKIT_API_KEY: str = os.getenv("LIVEKIT_API_KEY", "devkey")
    LIVEKIT_API_SECRET: str = os.getenv(
        "LIVEKIT_API_SECRET", 
        "secret"
    )
    
    # Orchestrator Configuration
    ORCHESTRATOR_URL: str = os.getenv(
        "ORCHESTRATOR_URL", 
        "http://june-orchestrator.june-services.svc.cluster.local:8080"
    )
    ORCHESTRATOR_API_KEY: str = os.getenv("ORCHESTRATOR_API_KEY", "")
    ORCHESTRATOR_ENABLED: bool = bool(os.getenv("ORCHESTRATOR_ENABLED", "true").lower() == "true")

config = Config()