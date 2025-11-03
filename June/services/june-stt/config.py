#!/usr/bin/env python3
"""
June STT Service Configuration - Enhanced for Latino English Accent
"""
import os
from typing import Optional

class EnhancedConfig:
    # Server Configuration
    PORT: int = int(os.getenv("STT_PORT", "8001"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    
    # Whisper Model Configuration - Enhanced for accented speech
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "large-v3-turbo")  # Upgraded default
    WHISPER_DEVICE: str = os.getenv("WHISPER_DEVICE", "auto")
    WHISPER_COMPUTE_TYPE: str = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
    WHISPER_CACHE_DIR: str = os.getenv("WHISPER_CACHE_DIR", "/app/models")
    
    # Whisper Performance Configuration
    WHISPER_NUM_WORKERS: int = int(os.getenv("WHISPER_NUM_WORKERS", "1"))
    WHISPER_CPU_THREADS: int = int(os.getenv("WHISPER_CPU_THREADS", "4"))
    WHISPER_BEAM_SIZE: int = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
    
    # Processing Options
    USE_BATCHED_INFERENCE: bool = os.getenv("USE_BATCHED_INFERENCE", "true").lower() == "true"
    BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "8"))
    
    # Dynamic Model Loading
    DYNAMIC_MODEL_LOADING: bool = os.getenv("DYNAMIC_MODEL_LOADING", "true").lower() == "true"
    MODEL_UNLOAD_TIMEOUT: int = int(os.getenv("MODEL_UNLOAD_TIMEOUT", "300"))
    
    # Silero VAD Configuration - Enhanced for accented speech
    SILERO_VAD_ENABLED: bool = os.getenv("SILERO_VAD_ENABLED", "true").lower() == "true"
    SILERO_VAD_THRESHOLD: float = float(os.getenv("SILERO_VAD_THRESHOLD", "0.45"))  # More sensitive for accents
    SILERO_MIN_SPEECH_MS: int = int(os.getenv("SILERO_MIN_SPEECH_MS", "80"))        # Faster detection
    SILERO_MIN_SILENCE_MS: int = int(os.getenv("SILERO_MIN_SILENCE_MS", "150"))     # Accent-friendly
    
    # Legacy VAD (fallback only)
    VAD_ENABLED: bool = os.getenv("VAD_ENABLED", "false").lower() == "true"
    
    # Language & Accent Settings - Critical for Latino English
    DEFAULT_LANGUAGE: str = os.getenv("DEFAULT_LANGUAGE", "en")
    FORCE_LANGUAGE: bool = os.getenv("FORCE_LANGUAGE", "true").lower() == "true"
    ACCENT_OPTIMIZATION: bool = os.getenv("ACCENT_OPTIMIZATION", "true").lower() == "true"
    INITIAL_PROMPT: str = os.getenv(
        "INITIAL_PROMPT", 
        "English speech with Latino accent. Technology terms: Kubernetes, Docker, API, microservices, Redis, database, configuration, orchestrator, deployment. Common words: can't, you can't, understand, explain, quantum, mechanics, particles, algorithm."
    )
    
    # Transcription Quality Settings
    CONDITION_ON_PREVIOUS_TEXT: bool = os.getenv("CONDITION_ON_PREVIOUS_TEXT", "false").lower() == "true"
    TEMPERATURE: float = float(os.getenv("WHISPER_TEMPERATURE", "0.0"))
    LANGUAGE: Optional[str] = os.getenv("WHISPER_LANGUAGE", "en")  # Force English
    
    # LiveKit Configuration
    LIVEKIT_ENABLED: bool = os.getenv("LIVEKIT_ENABLED", "true").lower() == "true"
    LIVEKIT_WS_URL: str = os.getenv("LIVEKIT_WS_URL", "ws://livekit-livekit-server:80")
    LIVEKIT_API_KEY: str = os.getenv("LIVEKIT_API_KEY", "devkey")
    LIVEKIT_API_SECRET: str = os.getenv("LIVEKIT_API_SECRET", "secret")
    LIVEKIT_ROOM_NAME: str = os.getenv("LIVEKIT_ROOM_NAME", "ozzu-main")
    
    # Natural Conversation Timing - Optimized for real-time chat
    UTTERANCE_PROCESSING: bool = os.getenv("UTTERANCE_PROCESSING", "true").lower() == "true"
    MIN_UTTERANCE_SEC: float = float(os.getenv("MIN_UTTERANCE_SEC", "0.4"))      # More responsive
    MAX_UTTERANCE_SEC: float = float(os.getenv("MAX_UTTERANCE_SEC", "8.0"))       # Faster chunks
    SILENCE_TIMEOUT_SEC: float = float(os.getenv("SILENCE_TIMEOUT_SEC", "1.2"))   # Natural pauses
    
    # SOTA Streaming Configuration - For immediate feedback
    SOTA_MODE_ENABLED: bool = os.getenv("SOTA_MODE_ENABLED", "true").lower() == "true"
    ULTRA_FAST_PARTIALS: bool = os.getenv("ULTRA_FAST_PARTIALS", "true").lower() == "true"
    AGGRESSIVE_VAD_TUNING: bool = os.getenv("AGGRESSIVE_VAD_TUNING", "true").lower() == "true"
    STT_STREAMING_ENABLED: bool = os.getenv("STT_STREAMING_ENABLED", "true").lower() == "true"
    STT_PARTIALS_ENABLED: bool = os.getenv("STT_PARTIALS_ENABLED", "true").lower() == "true"
    STT_CONTINUOUS_PARTIALS: bool = os.getenv("STT_CONTINUOUS_PARTIALS", "true").lower() == "true"
    
    # Faster partial delivery
    PARTIAL_EMIT_INTERVAL_MS: int = int(os.getenv("PARTIAL_EMIT_INTERVAL_MS", "150"))  # Faster
    PARTIAL_MIN_SPEECH_MS: int = int(os.getenv("PARTIAL_MIN_SPEECH_MS", "150"))        # Quicker start
    
    # Anti-feedback Configuration
    EXCLUDE_PARTICIPANTS: set = {
        "june-tts", "june-stt", "tts", "stt", 
        *os.getenv("EXCLUDE_PARTICIPANTS", "").split(",")
    } - {""}
    
    # Orchestrator Integration
    ORCHESTRATOR_URL: str = os.getenv(
        "ORCHESTRATOR_URL", 
        "http://june-orchestrator.june-services.svc.cluster.local:8080"
    )
    ORCHESTRATOR_ENABLED: bool = os.getenv("ORCHESTRATOR_ENABLED", "true").lower() == "true"
    
    def validate_configuration(self):
        errors = []
        
        if self.LIVEKIT_ENABLED and not self.LIVEKIT_API_KEY:
            errors.append("LIVEKIT_API_KEY required when LiveKit enabled")
            
        if self.MIN_UTTERANCE_SEC >= self.MAX_UTTERANCE_SEC:
            errors.append("MIN_UTTERANCE_SEC must be less than MAX_UTTERANCE_SEC")
            
        if self.SILERO_VAD_ENABLED:
            if not (0.1 <= self.SILERO_VAD_THRESHOLD <= 0.9):
                errors.append("SILERO_VAD_THRESHOLD must be between 0.1 and 0.9")
        
        supported_models = ["tiny", "base", "small", "medium", "large", "large-v2", "large-v3", "large-v3-turbo"]
        if self.WHISPER_MODEL not in supported_models:
            errors.append(f"WHISPER_MODEL must be one of: {supported_models}")
            
        if errors:
            raise ValueError(f"Configuration errors: {'; '.join(errors)}")
    
    def log_configuration(self):
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"June STT Configuration (Latino Accent Optimized):")
        logger.info(f"  Port: {self.PORT}")
        logger.info(f"  Whisper: {self.WHISPER_MODEL} on {self.WHISPER_DEVICE}")
        logger.info(f"  Language: {self.LANGUAGE} (forced: {self.FORCE_LANGUAGE})")
        logger.info(f"  Accent Optimization: {self.ACCENT_OPTIMIZATION}")
        logger.info(f"  Timing: MIN={self.MIN_UTTERANCE_SEC}s, MAX={self.MAX_UTTERANCE_SEC}s, SILENCE={self.SILENCE_TIMEOUT_SEC}s")
        logger.info(f"  VAD: Silero={self.SILERO_VAD_ENABLED} (threshold={self.SILERO_VAD_THRESHOLD})")
        logger.info(f"  Streaming: {self.STT_STREAMING_ENABLED}, Partials: {self.PARTIAL_EMIT_INTERVAL_MS}ms")
        logger.info(f"  Batched: {self.USE_BATCHED_INFERENCE} (size={self.BATCH_SIZE})")
        logger.info(f"  Initial Prompt: {self.INITIAL_PROMPT[:50]}...")

config = EnhancedConfig()
config.validate_configuration()