#!/usr/bin/env python3
"""
June STT Service Configuration - WhisperX Enhanced
"""
import os
from typing import Optional

class WhisperXConfig:
    # Server Configuration
    PORT: int = int(os.getenv("STT_PORT", "8001"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    
    # Whisper Model Configuration - WhisperX Compatible
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "large-v3-turbo")
    WHISPER_DEVICE: str = os.getenv("WHISPER_DEVICE", "auto")
    WHISPER_COMPUTE_TYPE: str = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
    WHISPER_CACHE_DIR: str = os.getenv("WHISPER_CACHE_DIR", "/app/models")
    
    # Whisper Performance Configuration
    WHISPER_NUM_WORKERS: int = int(os.getenv("WHISPER_NUM_WORKERS", "1"))
    WHISPER_CPU_THREADS: int = int(os.getenv("WHISPER_CPU_THREADS", "4"))
    WHISPER_BEAM_SIZE: int = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
    
    # WhisperX Specific Configuration
    BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "8"))
    USE_BATCHED_INFERENCE: bool = os.getenv("USE_BATCHED_INFERENCE", "true").lower() == "true"
    
    # WhisperX Features
    ENABLE_WORD_TIMESTAMPS: bool = os.getenv("ENABLE_WORD_TIMESTAMPS", "true").lower() == "true"
    DIARIZATION_ENABLED: bool = os.getenv("DIARIZATION_ENABLED", "false").lower() == "true"
    MIN_SPEAKERS: int = int(os.getenv("MIN_SPEAKERS", "1"))
    MAX_SPEAKERS: int = int(os.getenv("MAX_SPEAKERS", "5"))
    
    # Silero VAD Configuration - Preprocessing for WhisperX
    SILERO_VAD_ENABLED: bool = os.getenv("SILERO_VAD_ENABLED", "true").lower() == "true"
    SILERO_VAD_THRESHOLD: float = float(os.getenv("SILERO_VAD_THRESHOLD", "0.45"))
    SILERO_MIN_SPEECH_MS: int = int(os.getenv("SILERO_MIN_SPEECH_MS", "80"))
    SILERO_MIN_SILENCE_MS: int = int(os.getenv("SILERO_MIN_SILENCE_MS", "150"))
    
    # Legacy VAD (disabled with WhisperX)
    VAD_ENABLED: bool = False
    
    # Language & Accent Settings - Latino English Optimization
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
    LANGUAGE: Optional[str] = os.getenv("WHISPER_LANGUAGE", "en")
    
    # LiveKit Configuration
    LIVEKIT_ENABLED: bool = os.getenv("LIVEKIT_ENABLED", "true").lower() == "true"
    LIVEKIT_WS_URL: str = os.getenv("LIVEKIT_WS_URL", "ws://livekit-livekit-server:80")
    LIVEKIT_API_KEY: str = os.getenv("LIVEKIT_API_KEY", "devkey")
    LIVEKIT_API_SECRET: str = os.getenv("LIVEKIT_API_SECRET", "secret")
    LIVEKIT_ROOM_NAME: str = os.getenv("LIVEKIT_ROOM_NAME", "ozzu-main")
    
    # Natural Conversation Timing - Optimized for real-time chat
    UTTERANCE_PROCESSING: bool = os.getenv("UTTERANCE_PROCESSING", "true").lower() == "true"
    MIN_UTTERANCE_SEC: float = float(os.getenv("MIN_UTTERANCE_SEC", "0.4"))
    MAX_UTTERANCE_SEC: float = float(os.getenv("MAX_UTTERANCE_SEC", "8.0"))
    SILENCE_TIMEOUT_SEC: float = float(os.getenv("SILENCE_TIMEOUT_SEC", "1.2"))
    
    # SOTA Streaming Configuration
    SOTA_MODE_ENABLED: bool = os.getenv("SOTA_MODE_ENABLED", "true").lower() == "true"
    ULTRA_FAST_PARTIALS: bool = os.getenv("ULTRA_FAST_PARTIALS", "true").lower() == "true"
    AGGRESSIVE_VAD_TUNING: bool = os.getenv("AGGRESSIVE_VAD_TUNING", "true").lower() == "true"
    STT_STREAMING_ENABLED: bool = os.getenv("STT_STREAMING_ENABLED", "true").lower() == "true"
    STT_PARTIALS_ENABLED: bool = os.getenv("STT_PARTIALS_ENABLED", "true").lower() == "true"
    STT_CONTINUOUS_PARTIALS: bool = os.getenv("STT_CONTINUOUS_PARTIALS", "true").lower() == "true"
    
    # WhisperX Enhanced Partials
    WORD_LEVEL_PARTIALS: bool = os.getenv("WORD_LEVEL_PARTIALS", "true").lower() == "true"
    PARTIAL_EMIT_INTERVAL_MS: int = int(os.getenv("PARTIAL_EMIT_INTERVAL_MS", "150"))
    PARTIAL_MIN_SPEECH_MS: int = int(os.getenv("PARTIAL_MIN_SPEECH_MS", "150"))
    
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
    STT_SERVICE_TOKEN: str = os.getenv("STT_SERVICE_TOKEN", "")
    
    # HuggingFace Token for Diarization
    HF_TOKEN: Optional[str] = os.getenv("HF_TOKEN", None)
    
    def validate_configuration(self):
        """Validate WhisperX configuration"""
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
        
        if self.DIARIZATION_ENABLED and not self.HF_TOKEN:
            errors.append("HF_TOKEN required for speaker diarization (get from https://huggingface.co/settings/tokens)")
            
        if errors:
            raise ValueError(f"Configuration errors: {'; '.join(errors)}")
    
    def log_configuration(self):
        """Log WhisperX configuration"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info("=" * 80)
        logger.info("June STT Configuration (WhisperX Enhanced)")
        logger.info("=" * 80)
        logger.info(f"  Framework: WhisperX")
        logger.info(f"  Port: {self.PORT}")
        logger.info(f"  Model: {self.WHISPER_MODEL} on {self.WHISPER_DEVICE}")
        logger.info(f"  Language: {self.LANGUAGE} (forced: {self.FORCE_LANGUAGE})")
        logger.info(f"  Accent Optimization: {self.ACCENT_OPTIMIZATION}")
        logger.info("=" * 80)
        logger.info("WhisperX Features:")
        logger.info(f"  Word-level Timestamps: {self.ENABLE_WORD_TIMESTAMPS}")
        logger.info(f"  Speaker Diarization: {self.DIARIZATION_ENABLED}")
        logger.info(f"  Silero VAD Preprocessing: {self.SILERO_VAD_ENABLED}")
        logger.info("=" * 80)
        logger.info("Timing Configuration:")
        logger.info(f"  MIN Utterance: {self.MIN_UTTERANCE_SEC}s")
        logger.info(f"  MAX Utterance: {self.MAX_UTTERANCE_SEC}s")
        logger.info(f"  Silence Timeout: {self.SILENCE_TIMEOUT_SEC}s")
        logger.info("=" * 80)
        logger.info("Streaming:")
        logger.info(f"  Enabled: {self.STT_STREAMING_ENABLED}")
        logger.info(f"  Partials: {self.PARTIAL_EMIT_INTERVAL_MS}ms interval")
        logger.info(f"  Word-level Partials: {self.WORD_LEVEL_PARTIALS}")
        logger.info("=" * 80)
        if self.INITIAL_PROMPT:
            logger.info(f"Initial Prompt: {self.INITIAL_PROMPT[:80]}...")
            logger.info("=" * 80)

config = WhisperXConfig()
config.validate_configuration()