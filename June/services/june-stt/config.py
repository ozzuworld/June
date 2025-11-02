#!/usr/bin/env python3
"""
Configuration for June STT Service - SOTA ACCURACY OPTIMIZATION
Upgraded to large-v3-turbo for competitive transcription accuracy
Optimized for English with Latin accents and technical vocabulary
"""
import os
from typing import Optional

class EnhancedConfig:
    """SOTA STT Service Configuration with accuracy optimization"""
    
    # Server Configuration
    PORT: int = int(os.getenv("STT_PORT", "8001"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    
    # SOTA WHISPER MODEL CONFIGURATION - Upgraded for competitive accuracy
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "large-v3-turbo")  # SOTA: Upgraded from "base"
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
    
    # SILERO VAD Configuration
    SILERO_VAD_ENABLED: bool = os.getenv("SILERO_VAD_ENABLED", "true").lower() == "true"
    SILERO_VAD_THRESHOLD: float = float(os.getenv("SILERO_VAD_THRESHOLD", "0.5"))
    SILERO_MIN_SPEECH_MS: int = int(os.getenv("SILERO_MIN_SPEECH_MS", "100"))
    SILERO_MIN_SILENCE_MS: int = int(os.getenv("SILERO_MIN_SILENCE_MS", "100"))
    
    # Legacy VAD (fallback only)
    VAD_ENABLED: bool = os.getenv("VAD_ENABLED", "false").lower() == "true"
    
    # SOTA TRANSCRIPTION ACCURACY SETTINGS
    # Force English detection for consistent results with accented speech
    DEFAULT_LANGUAGE: str = os.getenv("DEFAULT_LANGUAGE", "en")  # SOTA: Force English by default
    FORCE_LANGUAGE: bool = os.getenv("FORCE_LANGUAGE", "true").lower() == "true"  # SOTA: Always use default
    
    # SOTA: Enhanced prompting for accented English
    ACCENT_OPTIMIZATION: bool = os.getenv("ACCENT_OPTIMIZATION", "true").lower() == "true"
    INITIAL_PROMPT: str = os.getenv(
        "INITIAL_PROMPT", 
        "English speech with Latin accent. Mathematical terms: square root, calculations, numbers. Technical vocabulary."
    )
    
    # Transcription Quality Settings
    CONDITION_ON_PREVIOUS_TEXT: bool = os.getenv("CONDITION_ON_PREVIOUS_TEXT", "false").lower() == "true"
    TEMPERATURE: float = float(os.getenv("WHISPER_TEMPERATURE", "0.0"))  # SOTA: Keep deterministic
    LANGUAGE: Optional[str] = os.getenv("WHISPER_LANGUAGE", None)
    
    # LiveKit Configuration
    LIVEKIT_ENABLED: bool = os.getenv("LIVEKIT_ENABLED", "true").lower() == "true"
    LIVEKIT_WS_URL: str = os.getenv("LIVEKIT_WS_URL", "ws://livekit-livekit-server:80")
    LIVEKIT_API_KEY: str = os.getenv("LIVEKIT_API_KEY", "devkey")
    LIVEKIT_API_SECRET: str = os.getenv("LIVEKIT_API_SECRET", "secret")
    LIVEKIT_ROOM_NAME: str = os.getenv("LIVEKIT_ROOM_NAME", "ozzu-main")
    
    # Simplified Utterance Processing
    UTTERANCE_PROCESSING: bool = os.getenv("UTTERANCE_PROCESSING", "true").lower() == "true"
    MIN_UTTERANCE_SEC: float = float(os.getenv("MIN_UTTERANCE_SEC", "0.3"))
    MAX_UTTERANCE_SEC: float = float(os.getenv("MAX_UTTERANCE_SEC", "8.0"))
    SILENCE_TIMEOUT_SEC: float = float(os.getenv("SILENCE_TIMEOUT_SEC", "0.8"))
    
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
        """Validate configuration settings"""
        errors = []
        
        if self.LIVEKIT_ENABLED and not self.LIVEKIT_API_KEY:
            errors.append("LIVEKIT_API_KEY required when LiveKit enabled")
            
        if self.MIN_UTTERANCE_SEC >= self.MAX_UTTERANCE_SEC:
            errors.append("MIN_UTTERANCE_SEC must be less than MAX_UTTERANCE_SEC")
            
        # Silero VAD validation
        if self.SILERO_VAD_ENABLED:
            if not (0.1 <= self.SILERO_VAD_THRESHOLD <= 0.9):
                errors.append("SILERO_VAD_THRESHOLD must be between 0.1 and 0.9")
        
        # SOTA: Validate model selection
        supported_models = ["tiny", "base", "small", "medium", "large", "large-v2", "large-v3", "large-v3-turbo"]
        if self.WHISPER_MODEL not in supported_models:
            errors.append(f"WHISPER_MODEL must be one of: {supported_models}")
            
        if errors:
            raise ValueError(f"Configuration errors: {'; '.join(errors)}")
    
    def log_configuration(self):
        """Log SOTA configuration"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"🔧 SOTA June STT Configuration:")
        logger.info(f"   Server Port: {self.PORT}")
        logger.info(f"   🏆 Whisper Model: {self.WHISPER_MODEL} (SOTA UPGRADE)")
        logger.info(f"   Device: {self.WHISPER_DEVICE}")
        logger.info(f"   ⚡ Batched Inference: {self.USE_BATCHED_INFERENCE}")
        logger.info(f"   🎯 Silero VAD: {self.SILERO_VAD_ENABLED} (threshold={self.SILERO_VAD_THRESHOLD})")
        logger.info(f"   🌍 Language Forcing: {self.FORCE_LANGUAGE} (default: {self.DEFAULT_LANGUAGE})")
        logger.info(f"   🗣️ Accent Optimization: {self.ACCENT_OPTIMIZATION}")
        logger.info(f"   🔗 LiveKit: {self.LIVEKIT_ENABLED}")
        
        if self.WHISPER_MODEL == "base":
            logger.warning("⚠️ Using 'base' model - consider 'large-v3-turbo' for SOTA accuracy")
        elif self.WHISPER_MODEL == "large-v3-turbo":
            logger.info("🏆 SOTA model selected: large-v3-turbo (optimal speed/accuracy)")

# Global configuration instance
config = EnhancedConfig()
config.validate_configuration()