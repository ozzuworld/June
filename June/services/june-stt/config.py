#!/usr/bin/env python3
"""
Configuration for June STT Service with faster-whisper v1.2.0 features
"""
import os
from typing import Optional

class Config:
    """STT Service Configuration with modern faster-whisper support"""
    
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
    
    # Modern faster-whisper v1.2.0 Features
    USE_BATCHED_INFERENCE: bool = os.getenv("STT_USE_BATCHED", "true").lower() == "true"
    BATCH_SIZE: int = int(os.getenv("STT_BATCH_SIZE", "8"))
    
    # VAD Configuration (compatible set)
    VAD_ENABLED: bool = os.getenv("VAD_ENABLED", "true").lower() == "true"
    VAD_THRESHOLD: float = float(os.getenv("VAD_THRESHOLD", "0.5"))
    VAD_MIN_SPEECH_DURATION_MS: int = int(os.getenv("VAD_MIN_SPEECH_DURATION_MS", "250"))
    VAD_MIN_SILENCE_DURATION_MS: int = int(os.getenv("VAD_MIN_SILENCE_DURATION_MS", "100"))
    VAD_SPEECH_PAD_MS: int = int(os.getenv("VAD_SPEECH_PAD_MS", "30"))
    
    # Silence Detection (Pre-filter before Whisper)
    SILENCE_RMS_THRESHOLD: float = float(os.getenv("SILENCE_RMS_THRESHOLD", "0.001"))
    SILENCE_FRAMES_THRESHOLD: int = int(os.getenv("SILENCE_FRAMES_THRESHOLD", "5"))
    
    # Transcription Quality Settings (v1.0+ support)
    CONDITION_ON_PREVIOUS_TEXT: bool = os.getenv("CONDITION_ON_PREVIOUS_TEXT", "false").lower() == "true"
    TEMPERATURE: float = float(os.getenv("WHISPER_TEMPERATURE", "0.0"))
    
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
    
    @property
    def vad_parameters(self) -> dict:
        """Get VAD parameters (compat set)"""
        return {
            "threshold": self.VAD_THRESHOLD,
            "min_speech_duration_ms": self.VAD_MIN_SPEECH_DURATION_MS,
            "min_silence_duration_ms": self.VAD_MIN_SILENCE_DURATION_MS,
            "speech_pad_ms": self.VAD_SPEECH_PAD_MS
        }

config = Config()